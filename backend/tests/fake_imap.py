"""In-memory stand-in for ImapClient, with real-world-ish quirks."""

from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from typing import Self

from app.sources.base import SourceAuthError
from app.sources.imap.client import FetchedMessage, Folder, ImapSettings, MailboxState

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
}


@dataclass
class FakeFolder:
    uidvalidity: int = 1000
    next_uid: int = 1
    messages: dict[int, tuple[datetime, bytes]] = field(default_factory=dict)
    flags: frozenset[str] = frozenset()

    def add(self, when: datetime, raw: bytes) -> int:
        uid = self.next_uid
        self.messages[uid] = (when, raw)
        self.next_uid += 1
        return uid


@dataclass
class FakeMailbox:
    password: str = "app-password"
    delimiter: str = "/"
    folders: dict[str, FakeFolder] = field(default_factory=lambda: {"INBOX": FakeFolder()})
    commands: list[str] = field(default_factory=list)
    opened: int = 0
    closed: int = 0

    def client_factory(self, settings: ImapSettings) -> "FakeImapClient":
        return FakeImapClient(self, settings)


class FakeImapClient:
    def __init__(self, mailbox: FakeMailbox, settings: ImapSettings) -> None:
        self.mailbox = mailbox
        self.settings = settings
        self.selected: str | None = None

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def open(self) -> None:
        if self.settings.password != self.mailbox.password:
            raise SourceAuthError("The mail server rejected the username or password.")
        self.mailbox.opened += 1

    def close(self) -> None:
        self.mailbox.closed += 1

    def list_folders(self) -> list[Folder]:
        return [
            Folder(name=n, delimiter=self.mailbox.delimiter, flags=f.flags)
            for n, f in self.mailbox.folders.items()
        ]

    def examine(self, folder: str) -> MailboxState:
        self.mailbox.commands.append(f"EXAMINE {folder}")
        self.selected = folder
        f = self.mailbox.folders[folder]
        return MailboxState(uidvalidity=f.uidvalidity, uidnext=f.next_uid, exists=len(f.messages))

    def _folder(self) -> FakeFolder:
        assert self.selected is not None
        return self.mailbox.folders[self.selected]

    def search_uids(self, *criteria: str) -> list[int]:
        self.mailbox.commands.append("SEARCH " + " ".join(criteria))
        msgs = self._folder().messages
        if criteria == ("ALL",):
            return sorted(msgs)
        if criteria[0] == "UID":
            start = int(criteria[1].split(":")[0])
            found = [u for u in sorted(msgs) if u >= start]
            # Real servers: "n:*" always includes the highest UID even if it is < n.
            return found or ([max(msgs)] if msgs else [])
        if criteria[0] == "SINCE":
            day, mon, year = criteria[1].split("-")
            since = datetime(int(year), _MONTHS[mon], int(day)).date()
            return sorted(u for u, (when, _) in msgs.items() if when.date() >= since)
        raise AssertionError(f"unsupported search {criteria}")

    def fetch_sizes(self, uids: list[int]) -> dict[int, int]:
        msgs = self._folder().messages
        return {u: len(msgs[u][1]) for u in uids if u in msgs}

    def fetch_messages(self, uids: list[int]) -> list[FetchedMessage]:
        self.mailbox.commands.append(f"FETCH {len(uids)}")
        msgs = self._folder().messages
        return [FetchedMessage(uid=u, internaldate=msgs[u][0], raw=msgs[u][1]) for u in uids if u in msgs]


def make_email(
    subject: str = "RFQ: WNRF flanges",
    sender: str = "Buyer <buyer@customer.com>",
    to: str = "sales@dcengineering.in",
    body: str = 'Please quote 100 nos 4" #150 WNRF A105.',
    when: datetime | None = None,
    message_id: str | None = None,
    in_reply_to: str | None = None,
    attachments: list[tuple[str, str, bytes]] | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg["Message-ID"] = message_id or make_msgid(domain="customer.com")
    if when:
        msg["Date"] = format_datetime(when)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    for filename, ctype, data in attachments or []:
        maintype, subtype = ctype.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()
