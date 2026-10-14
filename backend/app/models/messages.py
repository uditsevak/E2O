import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ARRAY, BigInteger, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin, TenantScoped, str_enum
from app.models.sources import SourceConnection


class Direction(enum.StrEnum):
    inbound = "inbound"  # received (inbox)
    outbound = "outbound"  # sent by the business (sent folder) — drives reply detection


class RawMessage(TenantScoped, IdMixin, Base):
    """Exactly what the source gave us. Insert-only: never updated, never re-fetched.

    The bytes live in blob storage (blob_key). Everything downstream (Message, Attachment,
    classification, extraction) is derived from this and can be rebuilt with a new
    normalizer / prompt / model without touching the mailbox again.
    """

    __tablename__ = "raw_messages"
    __table_args__ = (
        UniqueConstraint("source_connection_id", "provider_item_id"),
        Index("ix_raw_messages_source_sha256", "source_connection_id", "sha256"),
    )

    source_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_connections.id", ondelete="CASCADE"), index=True
    )
    # Unique within the connection, e.g. "INBOX:1700000000:42" for IMAP (folder:uidvalidity:uid).
    provider_item_id: Mapped[str] = mapped_column(String(500))
    direction: Mapped[Direction] = mapped_column(str_enum(Direction))
    media_type: Mapped[str] = mapped_column(String(100))  # "message/rfc822", later "application/json"
    folder: Mapped[str | None] = mapped_column(String(500))
    blob_key: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    provider_received_at: Mapped[datetime | None]
    fetched_at: Mapped[datetime]


class Message(TenantScoped, IdMixin, CreatedAtMixin, Base):
    """Normalized view of one RawMessage (1:1). Re-derivable; updated in place on re-normalize."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_ws_rfc_message_id", "workspace_id", "rfc_message_id"),
        Index("ix_messages_ws_sent_at", "workspace_id", "sent_at"),
    )

    raw_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_messages.id", ondelete="CASCADE"), unique=True
    )
    source_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_connections.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[Direction] = mapped_column(str_enum(Direction))

    rfc_message_id: Mapped[str | None] = mapped_column(String(1000))
    in_reply_to: Mapped[str | None] = mapped_column(String(1000))
    reference_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)

    subject: Mapped[str] = mapped_column(Text, default="")
    from_address: Mapped[str | None] = mapped_column(String(320))
    from_name: Mapped[str | None] = mapped_column(String(500))
    # [{"name": str | None, "address": str}]
    to_addresses: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    cc_addresses: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    reply_to_addresses: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    sent_at: Mapped[datetime | None]

    body_text: Mapped[str] = mapped_column(Text, default="")
    body_html: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str] = mapped_column(String(500), default="")
    attachment_count: Mapped[int] = mapped_column(default=0)

    normalizer_version: Mapped[int]
    # Non-fatal problems found while parsing (bad charset, malformed header, ...).
    parse_warnings: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)

    source_connection: Mapped[SourceConnection] = relationship(lazy="joined")
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="message", order_by="Attachment.part_index", cascade="all, delete-orphan"
    )


class Attachment(TenantScoped, IdMixin, CreatedAtMixin, Base):
    __tablename__ = "attachments"
    __table_args__ = (UniqueConstraint("message_id", "part_index"),)

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    part_index: Mapped[int]  # position among the message's attachments; stable across re-normalize
    filename: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    # Content-addressed per workspace: the same PDF CC'd to three inboxes is stored once.
    blob_key: Mapped[str] = mapped_column(String(500))
    is_inline: Mapped[bool] = mapped_column(default=False)
    content_id: Mapped[str | None] = mapped_column(String(500))

    message: Mapped[Message] = relationship(back_populates="attachments")
