"""A small, blocking, read-only IMAP client on top of imaplib.

Read-only is enforced here: mailboxes are opened with EXAMINE and bodies are fetched with
BODY.PEEK[], so we never change \\Seen flags or anything else on the user's mailbox.

All server/network failures are mapped to SourceError subclasses with messages that are safe
and useful to show to a non-technical user.
"""

import imaplib
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import date, datetime
from types import TracebackType
from typing import Any, Literal, Self

from app.sources.base import SourceAuthError, SourceConfigError, SourceError, SourceTemporaryError
from app.sources.imap import utf7

Security = Literal["ssl", "starttls", "none"]

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class TlsCertificateError(SourceConfigError):
    code = "tls_cert"


@dataclass(frozen=True)
class ImapSettings:
    host: str
    port: int
    security: Security
    username: str
    password: str
    tls_verify: bool = True
    timeout: float = 30

    def __repr__(self) -> str:  # never print the password
        return f"ImapSettings(host={self.host!r}, port={self.port}, security={self.security!r})"


@dataclass(frozen=True)
class Folder:
    name: str  # raw name as the server knows it (modified UTF-7)
    delimiter: str | None
    flags: frozenset[str]  # lower-cased, e.g. {"\\hasnochildren", "\\sent"}

    @property
    def display_name(self) -> str:
        return utf7.decode(self.name)

    @property
    def selectable(self) -> bool:
        return not ({"\\noselect", "\\nonexistent"} & self.flags)

    @property
    def special_use(self) -> str | None:
        for use in ("\\sent", "\\drafts", "\\trash", "\\junk", "\\archive", "\\all", "\\flagged"):
            if use in self.flags:
                return use[1:]
        if self.name.upper() == "INBOX":
            return "inbox"
        return None


@dataclass(frozen=True)
class MailboxState:
    uidvalidity: int
    uidnext: int | None
    exists: int


@dataclass(frozen=True)
class FetchedMessage:
    uid: int
    internaldate: datetime | None
    raw: bytes


def imap_date(d: date) -> str:
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def quote_mailbox(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _server_text(exc: BaseException) -> str:
    text = str(exc)
    if text.startswith("b'") or text.startswith('b"'):
        text = text[2:-1]
    return re.sub(r"\s+", " ", text).strip()[:200]


def _auth_message(server_text: str, host: str) -> str:
    t = server_text.lower()
    if "application-specific password" in t or "app password" in t or "gmail" in host:
        return (
            "The mail server rejected the password. Gmail and Google Workspace need an app password "
            "(Google Account → Security → 2-Step Verification → App passwords)."
        )
    if "imap" in t and ("enable" in t or "disabled" in t or "not allowed" in t):
        return "IMAP access is turned off for this mailbox. Turn it on in your mail settings, then try again."
    base = "The mail server rejected the username or password."
    if "zoho" in host:
        base += " Zoho needs IMAP turned on, and an app-specific password if two-factor login is on."
    return f"{base} (Server said: {server_text})" if server_text else base


_LIST_RE = re.compile(
    rb'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.*)$', re.IGNORECASE
)
_FETCH_START_RE = re.compile(rb"^\d+ \(")
_UID_RE = re.compile(rb"\bUID (\d+)")
_SIZE_RE = re.compile(rb"\bRFC822\.SIZE (\d+)")
_INTERNALDATE_RE = re.compile(rb'\bINTERNALDATE "([^"]+)"')


def _unquote(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return text


def parse_list_response(data: list[Any]) -> list[Folder]:
    folders: list[Folder] = []
    for item in data:
        if item is None:
            continue
        literal: bytes | None = None
        if isinstance(item, tuple):
            line, literal = item[0], item[1]
        else:
            line = item
        match = _LIST_RE.match(line.strip())
        if not match:
            continue
        name = literal.decode("utf-8", errors="replace") if literal is not None else _unquote(match["name"])
        delim_raw = match["delim"]
        delimiter = None if delim_raw.upper() == b"NIL" else _unquote(delim_raw)
        flags = frozenset(f.lower() for f in match["flags"].decode("ascii", errors="replace").split())
        folders.append(Folder(name=name, delimiter=delimiter, flags=flags))
    return folders


def _split_fetch_response(data: list[Any]) -> list[tuple[bytes, bytes | None]]:
    """imaplib returns FETCH responses as a mix of (header, literal) tuples and bytes
    continuation lines. Regroup them as (metadata, literal) per message."""
    entries: list[tuple[bytes, bytes | None]] = []
    meta: bytes | None = None
    literal: bytes | None = None
    for item in data:
        if item is None:
            continue
        if isinstance(item, tuple):
            if meta is not None:
                entries.append((meta, literal))
            meta, literal = item[0], item[1]
        elif _FETCH_START_RE.match(item):
            if meta is not None:
                entries.append((meta, literal))
            meta, literal = item, None
        elif meta is not None:
            meta += item
    if meta is not None:
        entries.append((meta, literal))
    return entries


def parse_internaldate(raw: bytes) -> datetime | None:
    try:
        return datetime.strptime(raw.decode().strip(), "%d-%b-%Y %H:%M:%S %z")
    except ValueError:
        return None


def parse_fetch_sizes(data: list[Any]) -> dict[int, int]:
    sizes: dict[int, int] = {}
    for meta, _ in _split_fetch_response(data):
        uid, size = _UID_RE.search(meta), _SIZE_RE.search(meta)
        if uid and size:
            sizes[int(uid[1])] = int(size[1])
    return sizes


def parse_fetch_messages(data: list[Any]) -> list[FetchedMessage]:
    messages: list[FetchedMessage] = []
    for meta, literal in _split_fetch_response(data):
        uid = _UID_RE.search(meta)
        if not uid or literal is None:
            continue
        internal = _INTERNALDATE_RE.search(meta)
        messages.append(
            FetchedMessage(
                uid=int(uid[1]),
                internaldate=parse_internaldate(internal[1]) if internal else None,
                raw=literal,
            )
        )
    return messages


class ImapClient:
    def __init__(self, settings: ImapSettings) -> None:
        self.settings = settings
        self._conn: imaplib.IMAP4 | None = None

    # -- lifecycle ---------------------------------------------------------------------------

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    def _ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        if not self.settings.tls_verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def open(self) -> None:
        s = self.settings
        try:
            if s.security == "ssl":
                conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                    s.host, s.port, ssl_context=self._ssl_context(), timeout=s.timeout
                )
            else:
                conn = imaplib.IMAP4(s.host, s.port, timeout=s.timeout)
                if s.security == "starttls":
                    conn.starttls(ssl_context=self._ssl_context())
        except socket.gaierror as exc:
            raise SourceConfigError(
                f"We couldn't find the mail server “{s.host}”. Check the IMAP server address."
            ) from exc
        except ssl.SSLCertVerificationError as exc:
            raise TlsCertificateError(
                f"The security certificate of “{s.host}” could not be verified. Your hosting provider may "
                "use a different server name (check your hosting control panel), or you can choose to "
                "allow this server's certificate."
            ) from exc
        except ssl.SSLError as exc:
            raise SourceConfigError(
                "A secure connection could not be set up. Usually IMAP uses port 993 with SSL, "
                "or port 143 with STARTTLS."
            ) from exc
        except TimeoutError as exc:
            raise SourceTemporaryError(
                f"The mail server “{s.host}” did not respond in time. Check the server and port, "
                "or try again in a few minutes."
            ) from exc
        except ConnectionRefusedError as exc:
            raise SourceTemporaryError(
                f"The mail server “{s.host}” refused the connection on port {s.port}. "
                "Check the port and security setting."
            ) from exc
        except imaplib.IMAP4.error as exc:
            if s.security == "starttls":
                raise SourceConfigError("This server does not support STARTTLS on this port.") from exc
            raise SourceTemporaryError("The mail server closed the connection unexpectedly.") from exc
        except OSError as exc:
            raise SourceTemporaryError(
                f"Could not connect to “{s.host}”: {exc.strerror or 'network error'}."
            ) from exc

        try:
            if s.password.isascii() and s.username.isascii():
                conn.login(s.username, s.password)
            else:
                creds = f"\0{s.username}\0{s.password}".encode()
                conn.authenticate("PLAIN", lambda _: creds)
        except imaplib.IMAP4.abort as exc:
            self._safe_logout(conn)
            raise SourceTemporaryError("The mail server closed the connection during sign-in.") from exc
        except imaplib.IMAP4.error as exc:
            self._safe_logout(conn)
            raise SourceAuthError(_auth_message(_server_text(exc), s.host.lower())) from exc
        except (TimeoutError, OSError) as exc:
            self._safe_logout(conn)
            raise SourceTemporaryError("The mail server stopped responding during sign-in.") from exc
        self._conn = conn

    @staticmethod
    def _safe_logout(conn: imaplib.IMAP4) -> None:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001, S110 - best effort on an already-failing connection
            pass

    def close(self) -> None:
        if self._conn is not None:
            self._safe_logout(self._conn)
            self._conn = None

    # -- commands ----------------------------------------------------------------------------

    @property
    def conn(self) -> imaplib.IMAP4:
        if self._conn is None:
            raise RuntimeError("IMAP client is not open")
        return self._conn

    def _run(self, what: str, fn: Any, *args: Any) -> tuple[str, list[Any]]:
        try:
            typ, data = fn(*args)
        except imaplib.IMAP4.abort as exc:
            raise SourceTemporaryError(f"The mail server dropped the connection while {what}.") from exc
        except imaplib.IMAP4.error as exc:
            raise SourceError(f"The mail server refused {what}: {_server_text(exc)}") from exc
        except (TimeoutError, OSError) as exc:
            raise SourceTemporaryError(f"The mail server stopped responding while {what}.") from exc
        if typ != "OK":
            text = _server_text(Exception(data[0] if data else b""))
            raise SourceError(f"The mail server refused {what}: {text}")
        return typ, data

    def list_folders(self) -> list[Folder]:
        _, data = self._run("listing folders", self.conn.list)
        return parse_list_response(data)

    def examine(self, folder: str) -> MailboxState:
        try:
            _, data = self._run(
                f"opening folder “{utf7.decode(folder)}”", self.conn.select, quote_mailbox(folder), True
            )
        except SourceError as exc:
            if isinstance(exc, SourceTemporaryError):
                raise
            raise SourceConfigError(
                f"The folder “{utf7.decode(folder)}” could not be opened. Pick another folder."
            ) from exc

        def code(name: str) -> int | None:
            _, values = self.conn.response(name)
            if values and values[0] is not None:
                try:
                    return int(values[0])
                except (TypeError, ValueError):
                    return None
            return None

        uidvalidity = code("UIDVALIDITY")
        if uidvalidity is None:
            raise SourceTemporaryError("The mail server did not report folder details. Try again later.")
        exists = int(data[0]) if data and data[0] and data[0].isdigit() else 0
        return MailboxState(uidvalidity=uidvalidity, uidnext=code("UIDNEXT"), exists=exists)

    def search_uids(self, *criteria: str) -> list[int]:
        _, data = self._run("searching messages", self.conn.uid, "SEARCH", *criteria)
        if not data or not data[0]:
            return []
        return sorted({int(x) for x in data[0].split()})

    def fetch_sizes(self, uids: list[int]) -> dict[int, int]:
        if not uids:
            return {}
        _, data = self._run(
            "reading message sizes", self.conn.uid, "FETCH", _uid_set(uids), "(UID RFC822.SIZE)"
        )
        return parse_fetch_sizes(data)

    def fetch_messages(self, uids: list[int]) -> list[FetchedMessage]:
        if not uids:
            return []
        _, data = self._run(
            "downloading messages", self.conn.uid, "FETCH", _uid_set(uids), "(UID INTERNALDATE BODY.PEEK[])"
        )
        return parse_fetch_messages(data)


def _uid_set(uids: list[int]) -> str:
    return ",".join(str(u) for u in uids)
