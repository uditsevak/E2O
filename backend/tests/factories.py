"""Direct-to-DB fixtures for tests that need data without going through a mailbox."""

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_json
from app.models import (
    Attachment,
    Direction,
    Message,
    RawMessage,
    SourceConnection,
    SourceKind,
    SourceStatus,
)


async def make_source(
    db: AsyncSession, workspace_id: uuid.UUID, address: str = "sales@example.com"
) -> SourceConnection:
    source = SourceConnection(
        workspace_id=workspace_id,
        kind=SourceKind.imap,
        display_name=address,
        account_address=address,
        config={"host": "imap.example.com", "port": 993, "security": "ssl", "username": address},
        credentials_encrypted=encrypt_json({"password": "s3cret-imap-password"}),
        status=SourceStatus.active,
        backfill_days=30,
    )
    db.add(source)
    await db.flush()
    return source


async def make_message(
    db: AsyncSession,
    source: SourceConnection,
    subject: str = "RFQ for flanges",
    with_attachment: bool = True,
) -> Message:
    sha = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    raw = RawMessage(
        workspace_id=source.workspace_id,
        source_connection_id=source.id,
        provider_item_id=f"INBOX:1:{uuid.uuid4().int % 10_000}",
        direction=Direction.inbound,
        media_type="message/rfc822",
        folder="INBOX",
        blob_key=f"ws/{source.workspace_id}/raw/{source.id}/{sha[:2]}/{sha}.eml",
        size_bytes=100,
        sha256=sha,
        fetched_at=datetime.now(UTC),
    )
    db.add(raw)
    await db.flush()
    message = Message(
        workspace_id=source.workspace_id,
        raw_message_id=raw.id,
        source_connection_id=source.id,
        direction=Direction.inbound,
        subject=subject,
        from_address="buyer@customer.com",
        sent_at=datetime.now(UTC),
        body_text='Please quote 100 nos WNRF 4" #150 A105',
        snippet="Please quote",
        normalizer_version=1,
        attachment_count=1 if with_attachment else 0,
    )
    db.add(message)
    await db.flush()
    if with_attachment:
        db.add(
            Attachment(
                workspace_id=source.workspace_id,
                message_id=message.id,
                part_index=0,
                filename="rfq.pdf",
                content_type="application/pdf",
                size_bytes=10,
                sha256=sha,
                blob_key=f"ws/{source.workspace_id}/att/{sha[:2]}/{sha}",
            )
        )
        await db.flush()
    return message
