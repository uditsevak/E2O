"""Turn raw RFC 822 bytes into a clean, normalized structure.

Real-world Indian SME mail is messy: wrong or missing charsets, Outlook/Rediff quirks,
forwarded emails attached as message/rfc822, PDFs sent as application/octet-stream. Parsing
never raises on bad input; problems are collected in `warnings`.
"""

import email
import email.policy
import email.utils
import hashlib
import html
import mimetypes
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.headerregistry import Address
from email.message import Message
from html.parser import HTMLParser

from charset_normalizer import from_bytes

PARSER_VERSION = 1

MAX_BODY_TEXT_CHARS = 200_000
MAX_BODY_HTML_CHARS = 1_000_000
SNIPPET_CHARS = 240
_DETECT_MIN_BYTES = 200

# Labels that are commonly wrong in the wild, mapped to the superset browsers actually use.
_CHARSET_ALIASES = {
    "iso-8859-1": "cp1252",
    "latin1": "cp1252",
    "latin-1": "cp1252",
    "us-ascii": "cp1252",
    "ascii": "cp1252",
    "ks_c_5601-1987": "cp949",
    "gb2312": "gb18030",
    "gbk": "gb18030",
    "x-sjis": "shift_jis",
    "utf8": "utf-8",
    "unicode-1-1-utf-7": "utf-7",
}


@dataclass
class ParsedAddress:
    name: str | None
    address: str

    def as_dict(self) -> dict[str, str | None]:
        return {"name": self.name, "address": self.address}


@dataclass
class ParsedAttachment:
    filename: str
    content_type: str
    data: bytes
    is_inline: bool
    content_id: str | None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass
class ParsedEmail:
    message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    subject: str = ""
    from_: ParsedAddress | None = None
    to: list[ParsedAddress] = field(default_factory=list)
    cc: list[ParsedAddress] = field(default_factory=list)
    reply_to: list[ParsedAddress] = field(default_factory=list)
    date: datetime | None = None
    body_text: str = ""
    body_html: str | None = None
    attachments: list[ParsedAttachment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def snippet(self) -> str:
        text = re.sub(r"\s+", " ", self.body_text).strip()
        return text[:SNIPPET_CHARS]


# --- helpers ----------------------------------------------------------------------------------


def _clean_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    match = re.search(r"<([^<>]+)>", value)
    if match:
        value = match.group(1)
    value = value.strip().strip("<>").strip()
    return value[:1000] or None


def _ids(value: str | None) -> list[str]:
    if not value:
        return []
    found = re.findall(r"<([^<>]+)>", value)
    if not found:
        found = value.split()
    return [i.strip()[:1000] for i in found if i.strip()]


def _header(msg: Message, name: str, warnings: list[str]) -> str | None:
    try:
        value = msg.get(name)
    except Exception:  # noqa: BLE001 - malformed headers raise all sorts of errors
        warnings.append(f"unreadable {name} header")
        return None
    if value is None:
        return None
    return str(value)


def _addresses(msg: Message, name: str, warnings: list[str]) -> list[ParsedAddress]:
    result: list[ParsedAddress] = []
    try:
        header = msg.get(name)
        if header is None:
            return []
        addrs = getattr(header, "addresses", None)
        if addrs is not None:
            for a in addrs:
                if isinstance(a, Address) and a.addr_spec and "@" in a.addr_spec:
                    result.append(ParsedAddress(name=a.display_name or None, address=a.addr_spec.lower()))
            if result:
                return result
    except Exception:  # noqa: BLE001
        warnings.append(f"malformed {name} header")
    # Fallback: the forgiving legacy parser on the raw header text.
    raw_values = msg.get_all(name, []) if hasattr(msg, "get_all") else []
    for display, addr in email.utils.getaddresses([str(v) for v in raw_values]):
        if addr and "@" in addr:
            result.append(ParsedAddress(name=display or None, address=addr.strip().lower()))
    return result


def _date(msg: Message, warnings: list[str]) -> datetime | None:
    raw = _header(msg, "Date", warnings)
    if not raw:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        warnings.append("unparseable Date header")
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def decode_text(data: bytes, declared: str | None, warnings: list[str]) -> str:
    charset = (declared or "").strip().strip('"').lower()
    charset = _CHARSET_ALIASES.get(charset, charset)
    if charset and charset not in {"unknown-8bit", "x-unknown", "unknown", "default"}:
        try:
            return data.decode(charset)
        except LookupError:
            warnings.append(f"unknown charset {charset!r}")
        except UnicodeDecodeError:
            warnings.append(f"text did not match declared charset {charset!r}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # Statistical detection is only trustworthy on longer text; on a few bytes it happily
    # "detects" CJK. Undeclared non-UTF-8 mail is overwhelmingly Windows-1252 (old Outlook).
    if len(data) >= _DETECT_MIN_BYTES:
        best = from_bytes(data).best()
        if best is not None and best.percent_chaos < 0.2:
            return str(best)
    return data.decode("cp1252", errors="replace")


class _HtmlToText(HTMLParser):
    _BLOCK = frozenset(
        {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "hr"}
    )
    _SKIP = frozenset({"script", "style", "head", "title"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _HtmlToText()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # noqa: BLE001
        return html.unescape(re.sub(r"<[^>]+>", " ", markup))
    text = "".join(parser.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


_MAGIC = [
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/x-ole-storage"),  # .xls/.doc (legacy Office)
]

_OFFICE_BY_EXT = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".csv": "text/csv",
    ".dwg": "image/vnd.dwg",
    ".dxf": "image/vnd.dxf",
}


def sniff_content_type(data: bytes, declared: str, filename: str) -> str:
    """Fix the content type when the sender's mail client got it wrong (very common)."""
    declared = (declared or "application/octet-stream").lower()
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if declared not in {
        "application/octet-stream",
        "application/x-unknown",
        "application/unknown",
        "binary/octet-stream",
    }:
        return declared
    for magic, ctype in _MAGIC:
        if data.startswith(magic):
            if ctype == "application/x-ole-storage":
                return _OFFICE_BY_EXT.get(ext, "application/vnd.ms-excel" if ext == ".xls" else declared)
            return ctype
    if ext in _OFFICE_BY_EXT:
        return _OFFICE_BY_EXT[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or declared


_UNSAFE_FILENAME = re.compile(r"[\x00-\x1f\x7f/\\]+")


def _safe_filename(name: str | None, content_type: str, index: int) -> str:
    if name:
        name = _UNSAFE_FILENAME.sub("_", name).strip().strip(".") or None
    if not name:
        ext = mimetypes.guess_extension(content_type) or ".bin"
        if content_type == "message/rfc822":
            ext = ".eml"
        name = f"attachment-{index + 1}{ext}"
    return name[:250]


def _payload_bytes(part: Message) -> bytes:
    if part.get_content_type() == "message/rfc822":
        inner = part.get_payload()
        if isinstance(inner, list) and inner:
            inner = inner[0]
        if isinstance(inner, Message):
            return inner.as_bytes(policy=email.policy.compat32)
        return b""
    data = part.get_payload(decode=True)
    return data if isinstance(data, bytes) else b""


# --- main entry point -------------------------------------------------------------------------


def parse_email(raw: bytes) -> ParsedEmail:
    out = ParsedEmail()
    try:
        msg: Message = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:  # noqa: BLE001
        out.warnings.append("message could not be parsed with the strict parser")
        msg = email.message_from_bytes(raw, policy=email.policy.compat32)

    w = out.warnings
    out.message_id = _clean_id(_header(msg, "Message-ID", w))
    out.in_reply_to = _clean_id(_header(msg, "In-Reply-To", w))
    out.references = _ids(_header(msg, "References", w))
    out.subject = re.sub(r"\s+", " ", _header(msg, "Subject", w) or "").strip()
    from_list = _addresses(msg, "From", w)
    out.from_ = from_list[0] if from_list else None
    out.to = _addresses(msg, "To", w)
    out.cc = _addresses(msg, "Cc", w)
    out.reply_to = _addresses(msg, "Reply-To", w)
    out.date = _date(msg, w)

    text_parts: list[str] = []
    html_parts: list[str] = []
    for part in _walk_leaves(msg):
        content_type = part.get_content_type()
        disposition = (part.get_content_disposition() or "").lower()
        try:
            filename = part.get_filename()
        except Exception:  # noqa: BLE001
            filename = None
            w.append("unreadable attachment filename")

        is_body_text = (
            content_type in {"text/plain", "text/html"} and disposition != "attachment" and not filename
        )
        if is_body_text:
            data = _payload_bytes(part)
            text = decode_text(data, part.get_content_charset(), w)
            (text_parts if content_type == "text/plain" else html_parts).append(text)
            continue

        if content_type.startswith("multipart/"):
            continue
        data = _payload_bytes(part)
        if not data:
            continue
        index = len(out.attachments)
        safe_name = _safe_filename(filename, content_type, index)
        out.attachments.append(
            ParsedAttachment(
                filename=safe_name,
                content_type=sniff_content_type(data, content_type, safe_name),
                data=data,
                is_inline=disposition == "inline" or (disposition == "" and bool(part.get("Content-ID"))),
                content_id=_clean_id(str(part.get("Content-ID"))) if part.get("Content-ID") else None,
            )
        )

    if html_parts:
        out.body_html = "\n".join(html_parts)[:MAX_BODY_HTML_CHARS]
    if text_parts:
        out.body_text = "\n\n".join(t.strip() for t in text_parts if t.strip())
    elif out.body_html:
        out.body_text = html_to_text(out.body_html)
    out.body_text = out.body_text.replace("\r\n", "\n")[:MAX_BODY_TEXT_CHARS]
    return out


def _walk_leaves(msg: Message) -> list[Message]:
    """Leaf parts in order, without descending into attached emails (message/rfc822), which
    are kept whole as attachments: forwarded enquiries often arrive that way."""
    leaves: list[Message] = []

    def visit(part: Message) -> None:
        if part.get_content_type() == "message/rfc822":
            leaves.append(part)
            return
        if part.is_multipart():
            payload = part.get_payload()
            if isinstance(payload, list):
                for child in payload:
                    if isinstance(child, Message):
                        visit(child)
            return
        leaves.append(part)

    visit(msg)
    return leaves


__all__ = ["PARSER_VERSION", "ParsedEmail", "parse_email"]
