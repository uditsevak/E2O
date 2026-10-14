from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, CurrentUser
from app.api.schemas import AuthConfigOut, LoginIn, MeOut, MyWorkspaceOut, SignupIn, UserOut
from app.auth import google
from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.service import get_user_by_email, normalize_email, user_from_google
from app.auth.sessions import clear_session_cookie, end_session, start_session
from app.config import get_settings
from app.models import Membership, User

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        has_password=user.password_hash is not None,
        has_google=user.google_sub is not None,
    )


def safe_next(next_path: str | None) -> str:
    """Only allow same-site relative redirects."""
    if next_path and next_path.startswith("/") and not next_path.startswith("//") and "\\" not in next_path:
        return next_path
    return "/"


@router.get("/config")
async def auth_config() -> AuthConfigOut:
    return AuthConfigOut(google_enabled=get_settings().google_enabled)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: SignupIn, request: Request, response: Response, db: DB) -> UserOut:
    email = normalize_email(body.email)
    if await get_user_by_email(db, email):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with this email already exists. Sign in instead."
        )
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with this email already exists. Sign in instead."
        ) from None
    await start_session(db, user, request, response)
    await db.commit()
    return user_out(user)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: DB) -> UserOut:
    user = await get_user_by_email(db, body.email)
    if user is None or not verify_password(user.password_hash, body.password):
        if user is not None and user.password_hash is None and user.google_sub:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This account uses Google sign-in.")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    await start_session(db, user, request, response)
    await db.commit()
    return user_out(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: DB) -> None:
    await end_session(db, request.cookies.get(get_settings().session_cookie_name))
    clear_session_cookie(response)


@router.get("/me")
async def me(user: CurrentUser, db: DB) -> MeOut:
    memberships = (
        await db.scalars(
            select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at)
        )
    ).all()
    return MeOut(
        user=user_out(user),
        workspaces=[
            MyWorkspaceOut(
                id=m.workspace.id, name=m.workspace.name, created_at=m.workspace.created_at, role=m.role
            )
            for m in memberships
        ],
    )


@router.get("/google/start", include_in_schema=False)
async def google_start(next: Annotated[str | None, Query()] = None) -> RedirectResponse:
    settings = get_settings()
    if not settings.google_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Google sign-in is not set up")
    url, state_cookie = google.build_authorization(safe_next(next))
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        google.STATE_COOKIE,
        state_cookie,
        max_age=google.STATE_TTL_SECONDS,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/api/auth/google",
    )
    return response


@router.get("/google/callback", include_in_schema=False)
async def google_callback(
    request: Request,
    db: DB,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    def fail(message: str) -> RedirectResponse:
        resp = RedirectResponse(f"/login?error={quote(message)}", status_code=status.HTTP_302_FOUND)
        resp.delete_cookie(google.STATE_COOKIE, path="/api/auth/google")
        return resp

    if error or not code:
        return fail("Google sign-in was cancelled.")
    try:
        data = google.read_state_cookie(request.cookies.get(google.STATE_COOKIE), state)
        identity = await google.exchange_code(code, data["verifier"], data["nonce"])
        user = await user_from_google(db, identity)
    except google.GoogleAuthError as exc:
        return fail(str(exc))
    except PermissionError as exc:
        return fail(str(exc))

    await db.flush()
    response = RedirectResponse(safe_next(data.get("next")), status_code=status.HTTP_302_FOUND)
    response.delete_cookie(google.STATE_COOKIE, path="/api/auth/google")
    await start_session(db, user, request, response)
    await db.commit()
    return response
