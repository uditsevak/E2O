from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import GoogleIdentity
from app.models import User


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == normalize_email(email)))


async def user_from_google(db: AsyncSession, identity: GoogleIdentity) -> User:
    """Find or create the user for a Google identity.

    An existing email/password account is linked only when Google says the email is verified;
    otherwise someone could take over an account by registering its address at Google.
    """
    user = await db.scalar(select(User).where(User.google_sub == identity.sub))
    if user is not None:
        return user

    email = normalize_email(identity.email)
    user = await get_user_by_email(db, email)
    if user is not None:
        if not identity.email_verified:
            raise PermissionError("This Google account's email is not verified.")
        user.google_sub = identity.sub
        user.email_verified = True
        return user

    user = User(
        email=email,
        name=identity.name or email.split("@")[0],
        google_sub=identity.sub,
        email_verified=identity.email_verified,
    )
    db.add(user)
    return user
