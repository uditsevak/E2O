import uuid
from datetime import UTC, datetime, timedelta

from procrastinate.testing import InMemoryConnector
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.tasks import enqueue_processing, enqueue_sync, schedule_syncs
from app.models import Direction, RawMessage, SourceStatus
from tests.conftest import SignedIn
from tests.factories import make_source


def _queued(jobs: InMemoryConnector, task: str) -> list[dict]:
    return [j["args"] for j in jobs.jobs.values() if j["task_name"] == task and j["status"] == "todo"]


async def test_enqueue_sync_is_deduplicated(jobs: InMemoryConnector) -> None:
    source_id = uuid.uuid4()
    assert await enqueue_sync(source_id) is True
    assert await enqueue_sync(source_id) is False
    assert _queued(jobs, "sync_source") == [{"source_id": str(source_id)}]


async def test_enqueue_processing_is_deduplicated(jobs: InMemoryConnector) -> None:
    raw_id = uuid.uuid4()
    await enqueue_processing([raw_id, raw_id])
    assert _queued(jobs, "process_raw_message") == [{"raw_message_id": str(raw_id)}]


async def test_scheduler_queues_due_sources_and_orphans(
    signed_in: SignedIn, db: AsyncSession, jobs: InMemoryConnector
) -> None:
    _, ws = await signed_in()
    workspace_id = uuid.UUID(ws["id"])
    due = await make_source(db, workspace_id, "due@example.com")
    fresh = await make_source(db, workspace_id, "fresh@example.com")
    fresh.last_sync_started_at = datetime.now(UTC)
    broken = await make_source(db, workspace_id, "broken@example.com")
    broken.status = SourceStatus.error
    orphan = RawMessage(
        workspace_id=workspace_id,
        source_connection_id=due.id,
        provider_item_id="INBOX:1:1",
        direction=Direction.inbound,
        media_type="message/rfc822",
        blob_key="ws/x/raw/y.eml",
        size_bytes=1,
        sha256="0" * 64,
        fetched_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db.add(orphan)
    await db.commit()

    await schedule_syncs(timestamp=0)

    assert _queued(jobs, "sync_source") == [{"source_id": str(due.id)}]
    assert _queued(jobs, "process_raw_message") == [{"raw_message_id": str(orphan.id)}]
