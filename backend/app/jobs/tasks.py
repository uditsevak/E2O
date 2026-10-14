"""Job definitions. Every job is idempotent and safe to retry.

Queues:
- "sync": talking to mailboxes (slow, network-bound)
- "pipeline": per-message processing (normalize → classify → extract → ... in later slices)
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from procrastinate import RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import or_, select

from app.config import get_settings
from app.db import get_sessionmaker
from app.jobs.app import job_app
from app.models import Message, RawMessage, SourceConnection, SourceStatus
from app.pipeline.normalize import normalize_raw_message
from app.sources.base import SourceTemporaryError
from app.sources.sync import sync_source
from app.storage.blobs import get_blob_store

log = logging.getLogger(__name__)

# Unprocessed raw messages older than this are re-enqueued by the sweeper.
SWEEP_AFTER = timedelta(minutes=10)
SWEEP_BATCH = 500


# --- enqueue helpers --------------------------------------------------------------------------


async def enqueue_sync(source_id: uuid.UUID) -> bool:
    """Queue a sync unless one is already waiting. Returns True if a job was queued."""
    try:
        await sync_source_job.configure(
            lock=f"source:{source_id}", queueing_lock=f"sync:{source_id}"
        ).defer_async(source_id=str(source_id))
    except AlreadyEnqueued:
        return False
    return True


async def enqueue_processing(raw_message_ids: list[uuid.UUID]) -> None:
    for raw_id in raw_message_ids:
        try:
            await process_raw_message_job.configure(queueing_lock=f"process:{raw_id}").defer_async(
                raw_message_id=str(raw_id)
            )
        except AlreadyEnqueued:
            pass


# --- jobs -------------------------------------------------------------------------------------


@job_app.task(
    name="sync_source",
    queue="sync",
    retry=RetryStrategy(max_attempts=5, exponential_wait=15, retry_exceptions={SourceTemporaryError}),
)
async def sync_source_job(source_id: str) -> None:
    await sync_source(
        get_sessionmaker(), uuid.UUID(source_id), get_blob_store(), on_stored=enqueue_processing
    )


@job_app.task(
    name="process_raw_message", queue="pipeline", retry=RetryStrategy(max_attempts=3, exponential_wait=10)
)
async def process_raw_message_job(raw_message_id: str) -> None:
    async with get_sessionmaker()() as db:
        await normalize_raw_message(db, uuid.UUID(raw_message_id), get_blob_store())
        await db.commit()


@job_app.periodic(cron="* * * * *", periodic_id="schedule_syncs")
@job_app.task(name="schedule_syncs", queue="sync", queueing_lock="schedule_syncs")
async def schedule_syncs(timestamp: int) -> None:
    """Every minute: queue syncs that are due, and re-queue raw messages that never got
    processed (e.g. the process was killed between storing and enqueueing)."""
    settings = get_settings()
    now = datetime.now(UTC)
    due_before = now - timedelta(minutes=settings.sync_interval_minutes)
    async with get_sessionmaker()() as db:
        # Keyed on the last *attempt*, so a failing mailbox is retried once per interval, not
        # every minute. Overlap is prevented by the job's queueing lock + lock.
        due = (
            await db.scalars(
                select(SourceConnection.id).where(
                    SourceConnection.status == SourceStatus.active,
                    or_(
                        SourceConnection.last_sync_started_at.is_(None),
                        SourceConnection.last_sync_started_at < due_before,
                    ),
                )
            )
        ).all()
        orphans = (
            await db.scalars(
                select(RawMessage.id)
                .outerjoin(Message, Message.raw_message_id == RawMessage.id)
                .where(
                    Message.id.is_(None),
                    RawMessage.media_type == "message/rfc822",
                    RawMessage.fetched_at < now - SWEEP_AFTER,
                )
                .limit(SWEEP_BATCH)
            )
        ).all()

    for source_id in due:
        await enqueue_sync(source_id)
    if orphans:
        log.info("re-queueing %d unprocessed raw messages", len(orphans))
        await enqueue_processing(list(orphans))
