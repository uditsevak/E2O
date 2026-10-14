import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, TenantScoped, str_enum


class SourceKind(enum.StrEnum):
    imap = "imap"
    gmail = "gmail"
    microsoft = "microsoft"
    # v1 sources; the connector interface is designed for them but they are not built yet.
    indiamart = "indiamart"
    tradeindia = "tradeindia"
    whatsapp = "whatsapp"


class SourceStatus(enum.StrEnum):
    active = "active"
    error = "error"  # needs the user to act (e.g. password changed); not retried automatically
    paused = "paused"
    disconnected = "disconnected"  # credentials deleted; data kept


class SourceConnection(TenantScoped, IdMixin, CreatedAtMixin, Base):
    __tablename__ = "source_connections"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "account_address"),)

    kind: Mapped[SourceKind] = mapped_column(str_enum(SourceKind))
    display_name: Mapped[str] = mapped_column(String(200))
    # The mailbox address / portal account id this connection reads.
    account_address: Mapped[str] = mapped_column(String(320))
    # Non-secret connector settings (host, port, folders, ...).
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Fernet-encrypted JSON (passwords, refresh tokens). Never returned by the API, never logged.
    credentials_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)

    status: Mapped[SourceStatus] = mapped_column(str_enum(SourceStatus), default=SourceStatus.active)
    # User-safe description of the last failure (no secrets, no mail content).
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None]

    # Opaque per-stream cursors owned by the connector, e.g. {"inbound": {...}, "outbound": {...}}.
    sync_cursor: Mapped[dict[str, Any]] = mapped_column(default=dict)
    backfill_days: Mapped[int]
    backfill_completed_at: Mapped[datetime | None]
    last_synced_at: Mapped[datetime | None]
    last_sync_started_at: Mapped[datetime | None]

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
