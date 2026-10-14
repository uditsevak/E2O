import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import resolve_session
from app.config import get_settings
from app.core.tenancy import bind_workspace
from app.db import get_db
from app.models import Membership, Role, User

DB = Annotated[AsyncSession, Depends(get_db)]


async def current_user_optional(request: Request, db: DB) -> User | None:
    token = request.cookies.get(get_settings().session_cookie_name)
    session = await resolve_session(db, token)
    return session.user if session else None


async def current_user(user: Annotated[User | None, Depends(current_user_optional)]) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


@dataclass(frozen=True)
class WorkspaceContext:
    """Proof that the current user belongs to `workspace_id`.

    Creating it binds the request's DB session to the workspace (see app.core.tenancy), so
    every TenantScoped query in this request is confined to it.
    """

    workspace_id: uuid.UUID
    user: User
    role: Role
    db: AsyncSession

    def require(self, role: Role) -> None:
        if self.role.rank < role.rank:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Only a workspace {role.value} can do this")


async def workspace_context(workspace_id: uuid.UUID, user: CurrentUser, db: DB) -> WorkspaceContext:
    membership = await db.scalar(
        select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user.id)
    )
    if membership is None:
        # 404, not 403: don't reveal that the workspace exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    bind_workspace(db, workspace_id)
    return WorkspaceContext(workspace_id=workspace_id, user=user, role=membership.role, db=db)


Ws = Annotated[WorkspaceContext, Depends(workspace_context)]


def require_role(role: Role) -> Callable[..., Coroutine[Any, Any, WorkspaceContext]]:
    async def dep(ctx: Ws) -> WorkspaceContext:
        ctx.require(role)
        return ctx

    return dep


WsAdmin = Annotated[WorkspaceContext, Depends(require_role(Role.admin))]
WsOwner = Annotated[WorkspaceContext, Depends(require_role(Role.owner))]
