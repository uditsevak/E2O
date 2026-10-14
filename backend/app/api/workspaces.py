import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, Ws, WsAdmin
from app.api.schemas import (
    InviteCreatedOut,
    InviteCreateIn,
    InviteOut,
    InvitePreviewOut,
    MemberOut,
    MemberUpdateIn,
    MyWorkspaceOut,
    WorkspaceCreateIn,
    WorkspaceOut,
    WorkspaceUpdateIn,
)
from app.auth.service import normalize_email
from app.config import get_settings
from app.core.security import hash_token, new_token
from app.core.tenancy import bind_workspace
from app.models import Invite, Membership, Role, User, Workspace

router = APIRouter(tags=["workspaces"])

DEFAULT_WORKSPACE_SETTINGS = {"timezone": "Asia/Kolkata"}


@router.post("/workspaces", status_code=status.HTTP_201_CREATED)
async def create_workspace(body: WorkspaceCreateIn, user: CurrentUser, db: DB) -> MyWorkspaceOut:
    workspace = Workspace(
        name=body.name.strip(), settings=dict(DEFAULT_WORKSPACE_SETTINGS), created_by_id=user.id
    )
    db.add(workspace)
    await db.flush()
    db.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.owner))
    await db.commit()
    return MyWorkspaceOut(
        id=workspace.id, name=workspace.name, created_at=workspace.created_at, role=Role.owner
    )


@router.get("/w/{workspace_id}")
async def get_workspace(ctx: Ws) -> MyWorkspaceOut:
    workspace = await ctx.db.get_one(Workspace, ctx.workspace_id)
    return MyWorkspaceOut(
        id=workspace.id, name=workspace.name, created_at=workspace.created_at, role=ctx.role
    )


@router.patch("/w/{workspace_id}")
async def update_workspace(body: WorkspaceUpdateIn, ctx: WsAdmin) -> WorkspaceOut:
    workspace = await ctx.db.get_one(Workspace, ctx.workspace_id)
    if body.name is not None:
        workspace.name = body.name.strip()
    await ctx.db.commit()
    return WorkspaceOut.model_validate(workspace)


# --- members ----------------------------------------------------------------------------------


@router.get("/w/{workspace_id}/members")
async def list_members(ctx: Ws) -> list[MemberOut]:
    memberships = (
        await ctx.db.scalars(
            select(Membership)
            .where(Membership.workspace_id == ctx.workspace_id)
            .order_by(Membership.created_at)
        )
    ).all()
    return [
        MemberOut(
            user_id=m.user_id, name=m.user.name, email=m.user.email, role=m.role, joined_at=m.created_at
        )
        for m in memberships
    ]


async def _get_membership(ctx: Ws, user_id: uuid.UUID) -> Membership:
    membership = await ctx.db.scalar(
        select(Membership).where(Membership.workspace_id == ctx.workspace_id, Membership.user_id == user_id)
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return membership


async def _owner_count(ctx: Ws) -> int:
    return (
        await ctx.db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.workspace_id == ctx.workspace_id, Membership.role == Role.owner)
        )
        or 0
    )


@router.patch("/w/{workspace_id}/members/{user_id}")
async def update_member(user_id: uuid.UUID, body: MemberUpdateIn, ctx: WsAdmin) -> MemberOut:
    membership = await _get_membership(ctx, user_id)
    touches_owner = Role.owner in (membership.role, body.role)
    if touches_owner and ctx.role != Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can change owners")
    if membership.role == Role.owner and body.role != Role.owner and await _owner_count(ctx) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A workspace needs at least one owner")
    membership.role = body.role
    await ctx.db.commit()
    return MemberOut(
        user_id=membership.user_id,
        name=membership.user.name,
        email=membership.user.email,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.delete("/w/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: uuid.UUID, ctx: Ws) -> None:
    membership = await _get_membership(ctx, user_id)
    leaving_self = user_id == ctx.user.id
    if not leaving_self:
        ctx.require(Role.admin)
        if membership.role == Role.owner and ctx.role != Role.owner:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can remove an owner")
    if membership.role == Role.owner and await _owner_count(ctx) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A workspace needs at least one owner")
    await ctx.db.delete(membership)
    await ctx.db.commit()


# --- invites ----------------------------------------------------------------------------------


def _accept_url(token: str) -> str:
    return f"{get_settings().app_url.rstrip('/')}/invite/{token}"


@router.post("/w/{workspace_id}/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(body: InviteCreateIn, ctx: WsAdmin) -> InviteCreatedOut:
    if body.role == Role.owner and ctx.role != Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can invite another owner")
    email = normalize_email(body.email)
    already_member = await ctx.db.scalar(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == ctx.workspace_id, User.email == email)
    )
    if already_member:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{email} is already in this workspace")

    token = new_token()
    invite = Invite(
        workspace_id=ctx.workspace_id,
        email=email,
        role=body.role,
        token_hash=hash_token(token),
        invited_by_id=ctx.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().invite_ttl_days),
    )
    ctx.db.add(invite)
    await ctx.db.commit()
    return InviteCreatedOut(invite=InviteOut.model_validate(invite), accept_url=_accept_url(token))


@router.get("/w/{workspace_id}/invites")
async def list_invites(ctx: WsAdmin) -> list[InviteOut]:
    invites = (
        await ctx.db.scalars(
            select(Invite)
            .where(
                Invite.workspace_id == ctx.workspace_id,
                Invite.accepted_at.is_(None),
                Invite.revoked_at.is_(None),
                Invite.expires_at > func.now(),
            )
            .order_by(Invite.created_at.desc())
        )
    ).all()
    return [InviteOut.model_validate(i) for i in invites]


@router.delete("/w/{workspace_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(invite_id: uuid.UUID, ctx: WsAdmin) -> None:
    invite = await ctx.db.scalar(
        select(Invite).where(Invite.id == invite_id, Invite.workspace_id == ctx.workspace_id)
    )
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    invite.revoked_at = datetime.now(UTC)
    await ctx.db.commit()


async def _invite_by_token(db: DB, token: str) -> Invite:
    # Token lookup is the one deliberately cross-workspace query: the token is the credential.
    invite = await db.scalar(select(Invite).where(Invite.token_hash == hash_token(token)))
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite link is not valid")
    return invite


def _invite_problem(invite: Invite) -> str | None:
    if invite.revoked_at:
        return "This invite was cancelled. Ask for a new one."
    if invite.accepted_at:
        return "This invite has already been used."
    if invite.expires_at <= datetime.now(UTC):
        return "This invite has expired. Ask for a new one."
    return None


@router.get("/invites/{token}")
async def preview_invite(token: str, db: DB) -> InvitePreviewOut:
    invite = await _invite_by_token(db, token)
    workspace = await db.get_one(Workspace, invite.workspace_id)
    problem = _invite_problem(invite)
    return InvitePreviewOut(
        workspace_name=workspace.name,
        email=invite.email,
        role=invite.role,
        invited_by=invite.invited_by.name if invite.invited_by else None,
        valid=problem is None,
        reason=problem,
    )


@router.post("/invites/{token}/accept")
async def accept_invite(token: str, user: CurrentUser, db: DB, response: Response) -> MyWorkspaceOut:
    invite = await _invite_by_token(db, token)
    if problem := _invite_problem(invite):
        raise HTTPException(status.HTTP_410_GONE, problem)
    if normalize_email(user.email) != invite.email:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"This invite is for {invite.email}. Sign in with that email to accept it.",
        )
    bind_workspace(db, invite.workspace_id)
    workspace = await db.get_one(Workspace, invite.workspace_id)
    existing = await db.scalar(
        select(Membership).where(
            Membership.workspace_id == invite.workspace_id, Membership.user_id == user.id
        )
    )
    role = existing.role if existing else invite.role
    if existing is None:
        db.add(Membership(workspace_id=invite.workspace_id, user_id=user.id, role=invite.role))
    invite.accepted_at = datetime.now(UTC)
    invite.accepted_by_id = user.id
    await db.commit()
    return MyWorkspaceOut(id=workspace.id, name=workspace.name, created_at=workspace.created_at, role=role)
