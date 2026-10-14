import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_sessionmaker
from app.models import Attachment, Direction, Message, RawMessage, SourceConnection, SourceStatus
from app.pipeline.normalize import normalize_raw_message
from app.sources.base import SourceAuthError, SourceTemporaryError
from app.sources.imap.client import ImapSettings
from app.sources.imap.connector import ImapConnector
from app.sources.sync import sync_source
from app.storage.blobs import LocalBlobStore, get_blob_store
from tests.conftest import SignedIn
from tests.factories import make_source
from tests.fake_imap import FakeFolder, FakeMailbox, make_email

NOW = datetime.now(UTC)
PDF = b"%PDF-1.4 fake"


def _mailbox() -> FakeMailbox:
    mb = FakeMailbox(folders={"INBOX": FakeFolder(), "Sent": FakeFolder(uidvalidity=77)})
    mb.folders["INBOX"].add(
        NOW - timedelta(days=2),
        make_email(
            subject="RFQ 1", message_id="<rfq1@c.com>", attachments=[("rfq.pdf", "application/pdf", PDF)]
        ),
    )
    mb.folders["INBOX"].add(NOW - timedelta(days=1), make_email(subject="RFQ 2", message_id="<rfq2@c.com>"))
    mb.folders["INBOX"].add(NOW - timedelta(days=90), make_email(subject="too old"))
    mb.folders["Sent"].add(
        NOW - timedelta(hours=20),
        make_email(subject="Re: RFQ 1", sender="sales@dc.in", in_reply_to="<rfq1@c.com>"),
    )
    return mb


def _factory(mb: FakeMailbox):  # type: ignore[no-untyped-def]
    def build(source: SourceConnection) -> ImapConnector:
        settings = ImapSettings("imap.example.com", 993, "ssl", "u", "app-password")
        return ImapConnector(
            settings, inbound_folder="INBOX", outbound_folder="Sent", client_factory=mb.client_factory
        )

    return build


async def _source(signed_in: SignedIn, db: AsyncSession) -> SourceConnection:
    _, ws = await signed_in()
    source = await make_source(db, uuid.UUID(ws["id"]))
    await db.commit()
    return source


async def test_sync_backfills_then_continues(signed_in: SignedIn, db: AsyncSession, tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = await _source(signed_in, db)
    mb = _mailbox()
    blobs = LocalBlobStore(tmp_path)
    stored: list[uuid.UUID] = []

    async def on_stored(ids: list[uuid.UUID]) -> None:
        stored.extend(ids)

    result = await sync_source(
        get_sessionmaker(), source.id, blobs, connector_factory=_factory(mb), on_stored=on_stored
    )
    assert result.backfilled and result.stored == 3  # 2 inbound in window + 1 sent
    assert sorted(stored) == sorted(result.new_raw_ids)

    await db.refresh(source)
    assert source.backfill_completed_at and source.last_synced_at and source.last_error is None
    assert (
        source.sync_cursor["inbound"]["last_uid"] == 3
    )  # window search returned uids 1-2; baseline moves on
    assert source.sync_cursor["outbound"]["folder"] == "Sent"

    rows = (await db.scalars(select(RawMessage).order_by(RawMessage.provider_item_id))).all()
    assert [(r.direction, r.provider_item_id) for r in rows] == [
        (Direction.inbound, "INBOX:1000:1"),
        (Direction.inbound, "INBOX:1000:2"),
        (Direction.outbound, "Sent:77:1"),
    ]
    assert await blobs.get(rows[0].blob_key) == mb.folders["INBOX"].messages[1][1]

    # Second run: nothing new.
    again = await sync_source(get_sessionmaker(), source.id, blobs, connector_factory=_factory(mb))
    assert again.stored == 0 and not again.backfilled

    # New mail arrives.
    mb.folders["INBOX"].add(NOW, make_email(subject="RFQ 3"))
    third = await sync_source(get_sessionmaker(), source.id, blobs, connector_factory=_factory(mb))
    assert third.stored == 1
    assert await db.scalar(select(func.count()).select_from(RawMessage)) == 4


async def test_sync_is_idempotent_after_a_crash(signed_in: SignedIn, db: AsyncSession, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """If the cursor was lost (crash before commit, UIDVALIDITY reset), re-fetched mail is not duplicated."""
    source = await _source(signed_in, db)
    mb = _mailbox()
    blobs = LocalBlobStore(tmp_path)
    await sync_source(get_sessionmaker(), source.id, blobs, connector_factory=_factory(mb))

    await db.execute(
        text("UPDATE source_connections SET sync_cursor = '{}', backfill_completed_at = NULL WHERE id = :id"),
        {"id": source.id},
    )
    await db.commit()
    mb.folders["INBOX"].uidvalidity = 9999  # provider ids change too
    result = await sync_source(get_sessionmaker(), source.id, blobs, connector_factory=_factory(mb))
    assert result.stored == 0 and result.duplicates == 3
    assert await db.scalar(select(func.count()).select_from(RawMessage)) == 3


async def test_auth_failure_marks_source_and_is_not_retried(
    signed_in: SignedIn, db: AsyncSession, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    source = await _source(signed_in, db)
    mb = _mailbox()
    mb.password = "changed-by-owner"
    with pytest.raises(SourceAuthError):
        await sync_source(
            get_sessionmaker(), source.id, LocalBlobStore(tmp_path), connector_factory=_factory(mb)
        )
    await db.refresh(source)
    assert source.status == SourceStatus.error
    assert "password" in (source.last_error or "")

    # Error sources are skipped until the user fixes them.
    result = await sync_source(
        get_sessionmaker(), source.id, LocalBlobStore(tmp_path), connector_factory=_factory(mb)
    )
    assert result.stored == 0


async def test_temporary_failure_keeps_source_active_and_progress(
    signed_in: SignedIn, db: AsyncSession, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    source = await _source(signed_in, db)
    mb = _mailbox()
    good = _factory(mb)

    class Flaky(ImapConnector):
        async def fetch_sent(self, cursor):  # type: ignore[no-untyped-def,override]
            raise SourceTemporaryError("The mail server did not respond in time.")
            yield  # pragma: no cover

    def flaky_factory(s: SourceConnection) -> ImapConnector:
        c = good(s)
        c.__class__ = Flaky
        return c

    with pytest.raises(SourceTemporaryError):
        await sync_source(
            get_sessionmaker(), source.id, LocalBlobStore(tmp_path), connector_factory=flaky_factory
        )
    await db.refresh(source)
    assert source.status == SourceStatus.active
    assert source.last_error == "The mail server did not respond in time."
    assert source.backfill_completed_at is not None  # backfill pages were committed
    assert await db.scalar(select(func.count()).select_from(RawMessage)) == 3


async def test_raw_messages_are_immutable(signed_in: SignedIn, db: AsyncSession, tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = await _source(signed_in, db)
    await sync_source(
        get_sessionmaker(), source.id, LocalBlobStore(tmp_path), connector_factory=_factory(_mailbox())
    )
    with pytest.raises(DBAPIError, match="immutable"):
        await db.execute(text("UPDATE raw_messages SET folder = 'x'"))
    await db.rollback()


async def test_normalize_creates_message_and_attachments(signed_in: SignedIn, db: AsyncSession) -> None:
    source = await _source(signed_in, db)
    blobs = get_blob_store()
    result = await sync_source(get_sessionmaker(), source.id, blobs, connector_factory=_factory(_mailbox()))

    for raw_id in result.new_raw_ids:
        async with get_sessionmaker()() as session:
            await normalize_raw_message(session, raw_id, blobs)
            await session.commit()

    messages = (await db.scalars(select(Message).order_by(Message.sent_at))).all()
    assert [m.subject for m in messages] == ["RFQ 1", "RFQ 2", "Re: RFQ 1"]
    rfq1, _, reply = messages
    assert rfq1.rfc_message_id == "rfq1@c.com" and rfq1.attachment_count == 1
    assert reply.direction == Direction.outbound and reply.in_reply_to == "rfq1@c.com"

    attachment = (await db.scalars(select(Attachment))).one()
    assert attachment.filename == "rfq.pdf" and attachment.content_type == "application/pdf"
    assert await blobs.get(attachment.blob_key) == PDF

    # Re-running is a no-op that keeps ids stable; forcing re-parses in place.
    async with get_sessionmaker()() as session:
        again = await normalize_raw_message(session, rfq1.raw_message_id, blobs, force=True)
        await session.commit()
    assert again is not None and again.id == rfq1.id
    assert await db.scalar(select(func.count()).select_from(Attachment)) == 1
    assert (await db.scalars(select(Attachment.id))).one() == attachment.id
