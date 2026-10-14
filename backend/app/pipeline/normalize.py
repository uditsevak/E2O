"""Pipeline step 1: RawMessage → Message + Attachments.

Idempotent: running it again for the same raw message updates the Message in place (ids stay
stable for anything that links to it) and only re-parses when the parser version changed.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import bind_workspace
from app.models import Attachment, Message, RawMessage
from app.pipeline.email_parser import PARSER_VERSION, parse_email
from app.storage.blobs import BlobStore, attachment_key

log = logging.getLogger(__name__)


async def normalize_raw_message(
    db: AsyncSession, raw_message_id: uuid.UUID, blobs: BlobStore, *, force: bool = False
) -> Message | None:
    raw = await db.get(RawMessage, raw_message_id)
    if raw is None:
        log.warning("raw message %s not found", raw_message_id)
        return None
    bind_workspace(db, raw.workspace_id)

    message = await db.scalar(select(Message).where(Message.raw_message_id == raw.id))
    if message is not None and message.normalizer_version >= PARSER_VERSION and not force:
        return message

    if raw.media_type != "message/rfc822":
        log.info("no normalizer for media type %s (raw %s)", raw.media_type, raw.id)
        return None

    data = await blobs.get(raw.blob_key)
    parsed = parse_email(data)

    if message is None:
        message = Message(
            workspace_id=raw.workspace_id,
            raw_message_id=raw.id,
            source_connection_id=raw.source_connection_id,
            direction=raw.direction,
            normalizer_version=PARSER_VERSION,
        )
        db.add(message)

    message.direction = raw.direction
    message.rfc_message_id = parsed.message_id
    message.in_reply_to = parsed.in_reply_to
    message.reference_ids = parsed.references
    message.subject = parsed.subject
    message.from_address = parsed.from_.address if parsed.from_ else None
    message.from_name = parsed.from_.name if parsed.from_ else None
    message.to_addresses = [a.as_dict() for a in parsed.to]
    message.cc_addresses = [a.as_dict() for a in parsed.cc]
    message.reply_to_addresses = [a.as_dict() for a in parsed.reply_to]
    message.sent_at = parsed.date or raw.provider_received_at
    message.body_text = parsed.body_text
    message.body_html = parsed.body_html
    message.snippet = parsed.snippet
    message.attachment_count = len(parsed.attachments)
    message.normalizer_version = PARSER_VERSION
    message.parse_warnings = parsed.warnings
    await db.flush()

    existing = {
        a.part_index: a
        for a in (await db.scalars(select(Attachment).where(Attachment.message_id == message.id))).all()
    }
    for index, att in enumerate(parsed.attachments):
        sha = att.sha256
        key = attachment_key(raw.workspace_id, sha)
        if not await blobs.exists(key):
            await blobs.put(key, att.data, att.content_type)
        row = existing.pop(index, None)
        if row is None:
            row = Attachment(workspace_id=raw.workspace_id, message_id=message.id, part_index=index)
            db.add(row)
        row.filename = att.filename
        row.content_type = att.content_type
        row.size_bytes = len(att.data)
        row.sha256 = sha
        row.blob_key = key
        row.is_inline = att.is_inline
        row.content_id = att.content_id
    for stale in existing.values():
        await db.delete(stale)

    await db.flush()
    return message
