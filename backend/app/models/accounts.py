import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin, TenantScoped, str_enum


class Role(enum.StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"

    @property
    def rank(self) -> int:
        return {Role.member: 0, Role.admin: 1, Role.owner: 2}[self]


class User(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    # Always stored lower-cased (see app.auth.service.normalize_email).
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None]
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    last_login_at: Mapped[datetime | None]


class AuthSession(IdMixin, CreatedAtMixin, Base):
    """A signed-in browser. The cookie holds a random token; we store only its SHA-256."""

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    user_agent: Mapped[str | None] = mapped_column(String(500))
    ip: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(lazy="joined")


class Workspace(IdMixin, CreatedAtMixin, Base):
    """A tenant: one business."""

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200))
    # Workspace-level configuration (timezone, business profile, ...). Never secrets.
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Membership(TenantScoped, IdMixin, CreatedAtMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[Role] = mapped_column(str_enum(Role))

    user: Mapped[User] = relationship(lazy="joined")
    workspace: Mapped[Workspace] = relationship(lazy="joined")


class Invite(TenantScoped, IdMixin, CreatedAtMixin, Base):
    __tablename__ = "invites"

    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[Role] = mapped_column(str_enum(Role))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None]
    accepted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None]

    invited_by: Mapped[User | None] = relationship(foreign_keys=[invited_by_id], lazy="joined")
