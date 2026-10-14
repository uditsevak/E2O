from datetime import UTC, datetime, timedelta

import pytest

from app.models import Direction
from app.sources.base import FetchPage, SourceAuthError
from app.sources.imap.client import ImapSettings
from app.sources.imap.connector import ImapConnector
from tests.fake_imap import FakeFolder, FakeMailbox, make_email

NOW = datetime.now(UTC)


def _connector(mailbox: FakeMailbox, password: str = "app-password", **kw: object) -> ImapConnector:
    settings = ImapSettings("imap.example.com", 993, "ssl", "sales@example.com", password)
    return ImapConnector(settings, client_factory=mailbox.client_factory, **kw)  # type: ignore[arg-type]


async def _collect(pages) -> list[FetchPage]:  # type: ignore[no-untyped-def]
    return [p async for p in pages]


@pytest.fixture
def mailbox() -> FakeMailbox:
    mb = FakeMailbox(folders={"INBOX": FakeFolder(), "Sent Items": FakeFolder(uidvalidity=2000)})
    inbox = mb.folders["INBOX"]
    inbox.add(NOW - timedelta(days=60), make_email(subject="old"))
    inbox.add(NOW - timedelta(days=3), make_email(subject="recent 1"))
    inbox.add(NOW - timedelta(days=1), make_email(subject="recent 2"))
    mb.folders["Sent Items"].add(NOW - timedelta(days=1), make_email(subject="Re: recent 1"))
    return mb


async def test_connect_discovers_folders(mailbox: FakeMailbox) -> None:
    result = await _connector(mailbox).connect()
    assert result.config_updates == {"inbound_folder": "INBOX", "outbound_folder": "Sent Items"}


async def test_connect_with_wrong_password(mailbox: FakeMailbox) -> None:
    with pytest.raises(SourceAuthError):
        await _connector(mailbox, password="nope").connect()


async def test_backfill_reads_window_from_both_folders(mailbox: FakeMailbox) -> None:
    connector = _connector(mailbox, outbound_folder="Sent Items")
    pages = await _collect(connector.backfill(NOW - timedelta(days=30)))
    inbound = [i for p in pages if p.stream == Direction.inbound for i in p.items]
    outbound = [i for p in pages if p.stream == Direction.outbound for i in p.items]
    assert len(inbound) == 2 and len(outbound) == 1
    assert inbound[0].provider_item_id == "INBOX:1000:2"
    assert outbound[0].direction == Direction.outbound
    assert pages[-1].cursor["folder"] == "Sent Items"
    inbound_cursor = [p for p in pages if p.stream == Direction.inbound][-1].cursor
    assert inbound_cursor["last_uid"] == 3 and inbound_cursor["uidvalidity"] == 1000
    # Read-only: every folder was opened with EXAMINE and the connection was closed.
    assert all(c.startswith(("EXAMINE", "SEARCH", "FETCH")) for c in mailbox.commands)
    assert mailbox.opened == mailbox.closed


async def test_fetch_new_continues_from_cursor(mailbox: FakeMailbox) -> None:
    connector = _connector(mailbox)
    first = await _collect(connector.backfill(NOW - timedelta(days=30)))
    cursor = first[-1].cursor

    # Nothing new: no items, cursor unchanged (the "n:*" quirk must not re-fetch the last one).
    again = await _collect(connector.fetch_new(cursor))
    assert [i for p in again for i in p.items] == []
    assert again[-1].cursor["last_uid"] == 3

    mailbox.folders["INBOX"].add(NOW, make_email(subject="brand new"))
    pages = await _collect(connector.fetch_new(cursor))
    items = [i for p in pages for i in p.items]
    assert [i.provider_item_id for i in items] == ["INBOX:1000:4"]
    assert pages[-1].cursor["last_uid"] == 4


async def test_fetch_new_without_history_starts_from_now(mailbox: FakeMailbox) -> None:
    pages = await _collect(_connector(mailbox).fetch_new(None))
    assert [i for p in pages for i in p.items] == []
    assert pages[-1].cursor["last_uid"] == 3


async def test_uidvalidity_change_rescans_from_last_seen_date(mailbox: FakeMailbox) -> None:
    connector = _connector(mailbox)
    cursor = (await _collect(connector.backfill(NOW - timedelta(days=30))))[-1].cursor

    # Server rebuilt the mailbox: new UIDVALIDITY, UIDs renumbered.
    old = mailbox.folders["INBOX"]
    rebuilt = FakeFolder(uidvalidity=5555)
    for _, (when, raw) in sorted(old.messages.items()):
        rebuilt.add(when, raw)
    mailbox.folders["INBOX"] = rebuilt

    pages = await _collect(connector.fetch_new(cursor))
    items = [i for p in pages for i in p.items]
    # Re-scan covers the latest message again (dedupe by content hash happens at store time).
    assert items and all(i.provider_item_id.startswith("INBOX:5555:") for i in items)
    assert "old" not in b"".join(i.raw for i in items).decode()
    assert pages[-1].cursor["uidvalidity"] == 5555


async def test_oversized_messages_are_skipped(mailbox: FakeMailbox) -> None:
    mailbox.folders["INBOX"].add(NOW, make_email(subject="huge", body="x" * 5000))
    connector = _connector(mailbox, max_message_bytes=2000)
    pages = await _collect(connector.backfill(NOW - timedelta(days=30)))
    assert sum(p.skipped for p in pages) == 1
    assert pages[0].cursor["last_uid"] == 4  # skipped messages don't block progress


async def test_batches(mailbox: FakeMailbox) -> None:
    for i in range(7):
        mailbox.folders["INBOX"].add(NOW, make_email(subject=f"m{i}"))
    pages = await _collect(_connector(mailbox, batch_size=3).backfill(NOW - timedelta(days=30)))
    inbound = [p for p in pages if p.stream == Direction.inbound]
    assert [len(p.items) for p in inbound] == [3, 3, 3]
    assert [p.cursor["last_uid"] for p in inbound] == [4, 7, 10]


async def test_older_mail_at_higher_uids_is_not_fetched_after_backfill() -> None:
    """A message dragged into the inbox later gets a high UID but an old date. It is outside
    the backfill window, so the incremental fetch afterwards must not pick it up either."""
    mb = FakeMailbox()
    mb.folders["INBOX"].add(NOW - timedelta(days=1), make_email(subject="recent"))
    mb.folders["INBOX"].add(NOW - timedelta(days=200), make_email(subject="moved in later"))
    connector = _connector(mb)
    pages = await _collect(connector.backfill(NOW - timedelta(days=30)))
    assert [i.provider_item_id for p in pages for i in p.items] == ["INBOX:1000:1"]
    later = await _collect(connector.fetch_new(pages[-1].cursor))
    assert [i for p in later for i in p.items] == []
