"""Sync one source connection: pull raw items and store them, page by page.

Safe to run repeatedly and to kill at any point:
- raw items are keyed by (connection, provider_item_id) and also skipped when the same bytes
  were already stored for the connection (covers IMAP UIDVALIDITY resets);
- the cursor for a stream is saved in the same transaction as the page's items.
"""

import hashlib
import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tenancy import bind_workspace
from app.models import RawMessage, SourceConnection, SourceStatus
from app.sources.base import FetchPage, SourceConnector, SourceError
from app.sources.registry import build_connector
from app.storage.blobs import BlobStore, raw_message_key

log = logging.getLogger(__name__)

ConnectorFactory = Callable[[SourceConnection], SourceConnector]
OnStored = Callable[[list[uuid.UUID]], Awaitable[None]]


@dataclass
class SyncResult:
    source_id: uuid.UUID
    stored: int = 0
    duplicates: int = 0
    skipped: int = 0
    pages: int = 0
    backfilled: bool = False
    new_raw_ids: list[uuid.UUID] = field(default_factory=list)


async def _store_page(
    db: AsyncSession, source: SourceConnection, page: FetchPage, blobs: BlobStore, result: SyncResult
) -> list[uuid.UUID]:
    hashes = {item.provider_item_id: hashlib.sha256(item.raw).hexdigest() for item in page.items}
    known_hashes: set[str] = set()
    if hashes:
        known_hashes = set(
            (
                await db.scalars(
                    select(RawMessage.sha256).where(
                        RawMessage.source_connection_id == source.id,
                        RawMessage.sha256.in_(set(hashes.values())),
                    )
                )
            ).all()
        )

    new_ids: list[uuid.UUID] = []
    now = datetime.now(UTC)
    for item in page.items:
        sha = hashes[item.provider_item_id]
        if sha in known_hashes:
            result.duplicates += 1
            continue
        key = raw_message_key(source.workspace_id, source.id, sha)
        if not await blobs.exists(key):
            await blobs.put(key, item.raw, item.media_type)
        inserted = await db.scalar(
            insert(RawMessage)
            .values(
                id=uuid.uuid4(),
                workspace_id=source.workspace_id,
                source_connection_id=source.id,
                provider_item_id=item.provider_item_id,
                direction=item.direction,
                media_type=item.media_type,
                folder=item.folder,
                blob_key=key,
                size_bytes=len(item.raw),
                sha256=sha,
                provider_received_at=item.received_at,
                fetched_at=now,
            )
            .on_conflict_do_nothing(index_elements=["source_connection_id", "provider_item_id"])
            .returning(RawMessage.id)
        )
        if inserted is None:
            result.duplicates += 1
            continue
        known_hashes.add(sha)
        new_ids.append(inserted)

    cursor = dict(source.sync_cursor or {})
    cursor[page.stream.value] = page.cursor
    source.sync_cursor = cursor
    result.stored += len(new_ids)
    result.skipped += page.skipped
    result.pages += 1
    return new_ids


async def _consume(
    pages: AsyncGenerator[FetchPage],
    db: AsyncSession,
    source: SourceConnection,
    blobs: BlobStore,
    result: SyncResult,
    on_stored: OnStored | None,
) -> None:
    async with aclosing(pages) as stream:
        async for page in stream:
            new_ids = await _store_page(db, source, page, blobs, result)
            await db.commit()
            result.new_raw_ids.extend(new_ids)
            if new_ids and on_stored is not None:
                await on_stored(new_ids)


async def sync_source(
    sessionmaker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    blobs: BlobStore,
    *,
    connector_factory: ConnectorFactory = build_connector,
    on_stored: OnStored | None = None,
) -> SyncResult:
    result = SyncResult(source_id=source_id)
    async with sessionmaker() as db:
        source = await db.get(SourceConnection, source_id)
        if source is None or source.status != SourceStatus.active:
            log.info("skip sync for source %s (missing or not active)", source_id)
            return result
        bind_workspace(db, source.workspace_id)
        source.last_sync_started_at = datetime.now(UTC)
        await db.commit()

        try:
            connector = connector_factory(source)
            if source.backfill_completed_at is None:
                since = datetime.now(UTC) - timedelta(days=source.backfill_days)
                if source.backfill_days > 0:
                    await _consume(connector.backfill(since), db, source, blobs, result, on_stored)
                source.backfill_completed_at = datetime.now(UTC)
                await db.commit()
                result.backfilled = True
            cursor = source.sync_cursor or {}
            await _consume(connector.fetch_new(cursor.get("inbound")), db, source, blobs, result, on_stored)
            cursor = source.sync_cursor or {}
            await _consume(connector.fetch_sent(cursor.get("outbound")), db, source, blobs, result, on_stored)
        except SourceError as exc:
            await db.rollback()
            source = await db.get_one(SourceConnection, source_id)
            source.last_error = str(exc)
            source.last_error_at = datetime.now(UTC)
            if not exc.retryable:
                source.status = SourceStatus.error
            await db.commit()
            log.warning(
                "sync failed for source %s: %s (retryable=%s)", source_id, type(exc).__name__, exc.retryable
            )
            raise

        source.last_synced_at = datetime.now(UTC)
        source.last_error = None
        source.last_error_at = None
        await db.commit()
    log.info(
        "synced source %s: stored=%d duplicates=%d skipped=%d pages=%d",
        source_id,
        result.stored,
        result.duplicates,
        result.skipped,
        result.pages,
    )
    return result
