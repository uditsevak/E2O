import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models import Direction, SourceKind
from app.sources.base import ConnectResult, Cursor, FetchPage, RawItem, SourceConnector
from app.sources.imap.client import Folder, ImapClient, ImapSettings, imap_date

SENT_FOLDER_NAMES = (
    "sent",
    "sent items",
    "sent messages",
    "sent mail",
    "sent-mail",
    "sentmail",
    "sent email",
    "sent emails",
    "[gmail]/sent mail",
    "[google mail]/sent mail",
)

# When a mailbox is rebuilt on the server (UIDVALIDITY changes) we re-scan from a little
# before the newest message we had seen; already-stored mail is skipped by content hash.
UIDVALIDITY_RESCAN_MARGIN = timedelta(days=2)


def pick_inbox(folders: list[Folder]) -> str:
    for folder in folders:
        if folder.name.upper() == "INBOX":
            return folder.name
    return "INBOX"


def pick_sent(folders: list[Folder]) -> str | None:
    selectable = [f for f in folders if f.selectable]
    for folder in selectable:
        if "\\sent" in folder.flags:
            return folder.name

    def matches(folder: Folder) -> bool:
        name = folder.display_name.lower()
        leaf = name.rsplit(folder.delimiter, 1)[-1] if folder.delimiter else name
        return name in SENT_FOLDER_NAMES or leaf in SENT_FOLDER_NAMES

    candidates = [f for f in selectable if matches(f)]
    if not candidates:
        return None
    # Prefer the shallowest folder ("Sent" over "Archive/2019/Sent"), then the shortest name.
    candidates.sort(key=lambda f: (f.name.count(f.delimiter) if f.delimiter else 0, len(f.name)))
    return candidates[0].name


def _chunks(items: list[int], size: int) -> list[list[int]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


class ImapConnector(SourceConnector):
    kind = SourceKind.imap

    def __init__(
        self,
        settings: ImapSettings,
        inbound_folder: str | None = None,
        outbound_folder: str | None = None,
        batch_size: int = 25,
        max_message_bytes: int = 40 * 1024 * 1024,
        client_factory: Callable[[ImapSettings], ImapClient] = ImapClient,
    ) -> None:
        self.settings = settings
        self.inbound_folder = inbound_folder or "INBOX"
        self.outbound_folder = outbound_folder
        self.batch_size = batch_size
        self.max_message_bytes = max_message_bytes
        self._client_factory = client_factory

    async def connect(self) -> ConnectResult:
        def work() -> list[Folder]:
            with self._client_factory(self.settings) as client:
                return client.list_folders()

        folders = await asyncio.to_thread(work)
        names = {f.name for f in folders}
        inbound = self.inbound_folder if self.inbound_folder in names else pick_inbox(folders)
        outbound = self.outbound_folder if self.outbound_folder in names else pick_sent(folders)
        return ConnectResult(
            config_updates={"inbound_folder": inbound, "outbound_folder": outbound},
            details={"folders": folders},
        )

    async def backfill(self, since: datetime) -> AsyncGenerator[FetchPage]:
        async for page in self._stream(Direction.inbound, self.inbound_folder, None, since):
            yield page
        if self.outbound_folder:
            async for page in self._stream(Direction.outbound, self.outbound_folder, None, since):
                yield page

    async def fetch_new(self, cursor: Cursor | None) -> AsyncGenerator[FetchPage]:
        async for page in self._stream(Direction.inbound, self.inbound_folder, cursor, None):
            yield page

    async def fetch_sent(self, cursor: Cursor | None) -> AsyncGenerator[FetchPage]:
        if not self.outbound_folder:
            return
        async for page in self._stream(Direction.outbound, self.outbound_folder, cursor, None):
            yield page

    async def _stream(
        self, direction: Direction, folder: str, cursor: Cursor | None, since: datetime | None
    ) -> AsyncGenerator[FetchPage]:
        client = self._client_factory(self.settings)
        await asyncio.to_thread(client.open)
        try:
            state = await asyncio.to_thread(client.examine, folder)
            resumable = (
                cursor is not None
                and cursor.get("folder") == folder
                and cursor.get("uidvalidity") == state.uidvalidity
            )
            last_date: str | None = cursor.get("last_date") if cursor else None

            def make_cursor(last_uid: int, newest: str | None) -> Cursor:
                return {
                    "folder": folder,
                    "uidvalidity": state.uidvalidity,
                    "last_uid": last_uid,
                    "last_date": newest,
                }

            if resumable:
                assert cursor is not None
                last_uid = int(cursor.get("last_uid", 0))
                found = await asyncio.to_thread(client.search_uids, "UID", f"{last_uid + 1}:*")
                uids = [u for u in found if u > last_uid]  # "n:*" always returns the last message
            else:
                window_start = since
                if window_start is None and last_date:
                    window_start = datetime.fromisoformat(last_date) - UIDVALIDITY_RESCAN_MARGIN
                if window_start is None:
                    # No history wanted: start from "now".
                    start_uid = (state.uidnext - 1) if state.uidnext else 0
                    if not state.uidnext:
                        existing = await asyncio.to_thread(client.search_uids, "ALL")
                        start_uid = existing[-1] if existing else 0
                    yield FetchPage(stream=direction, items=[], cursor=make_cursor(start_uid, last_date))
                    return
                last_uid = 0
                uids = await asyncio.to_thread(client.search_uids, "SINCE", imap_date(window_start.date()))

            if not uids:
                baseline = last_uid
                if not resumable and state.uidnext:
                    baseline = state.uidnext - 1
                yield FetchPage(stream=direction, items=[], cursor=make_cursor(baseline, last_date))
                return

            # After a date-window scan, everything up to the folder's top (as of EXAMINE) has been
            # considered: older mail at higher UIDs (moved in later) is outside the window, so the
            # final cursor must not leave it for fetch_new to pick up.
            floor = (state.uidnext - 1) if (not resumable and state.uidnext) else 0
            chunks = _chunks(uids, self.batch_size)
            for n, chunk in enumerate(chunks):
                sizes = await asyncio.to_thread(client.fetch_sizes, chunk)
                wanted = [u for u in chunk if sizes.get(u, 0) <= self.max_message_bytes]
                fetched = await asyncio.to_thread(client.fetch_messages, wanted)
                items: list[RawItem] = []
                for msg in fetched:
                    items.append(
                        RawItem(
                            provider_item_id=f"{folder}:{state.uidvalidity}:{msg.uid}",
                            direction=direction,
                            raw=msg.raw,
                            media_type="message/rfc822",
                            folder=folder,
                            received_at=msg.internaldate,
                        )
                    )
                    if msg.internaldate:
                        stamp = msg.internaldate.astimezone(UTC).isoformat()
                        if last_date is None or stamp > last_date:
                            last_date = stamp
                top = max(chunk) if n < len(chunks) - 1 else max(max(chunk), floor)
                yield FetchPage(
                    stream=direction,
                    items=items,
                    cursor=make_cursor(top, last_date),
                    skipped=len(chunk) - len(wanted),
                )
        finally:
            await asyncio.to_thread(client.close)


def imap_settings_from(config: dict[str, Any], credentials: dict[str, Any], timeout: float) -> ImapSettings:
    return ImapSettings(
        host=config["host"],
        port=int(config["port"]),
        security=config.get("security", "ssl"),
        username=config["username"],
        password=credentials["password"],
        tls_verify=bool(config.get("tls_verify", True)),
        timeout=timeout,
    )
