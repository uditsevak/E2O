from datetime import UTC, date, datetime, timedelta, timezone

from app.sources.imap import utf7
from app.sources.imap.client import (
    Folder,
    ImapSettings,
    imap_date,
    parse_fetch_messages,
    parse_fetch_sizes,
    parse_internaldate,
    parse_list_response,
    quote_mailbox,
)
from app.sources.imap.connector import pick_inbox, pick_sent


def test_list_parsing_across_servers() -> None:
    data = [
        # Gmail
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
        b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
        b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
        # Dovecot / cPanel style, unquoted atoms
        b'(\\HasNoChildren) "." INBOX.Sent',
        # Literal name
        (b'(\\HasNoChildren) "/" {12}', b'Sent "Items"'),
        None,
        b'(\\HasNoChildren) NIL "Notes"',
    ]
    folders = parse_list_response(data)
    names = [f.name for f in folders]
    assert names == [
        "INBOX",
        "[Gmail]/All Mail",
        "[Gmail]/Sent Mail",
        "[Gmail]",
        "INBOX.Sent",
        'Sent "Items"',
        "Notes",
    ]
    gmail_sent = folders[2]
    assert gmail_sent.special_use == "sent" and gmail_sent.delimiter == "/"
    assert not folders[3].selectable
    assert folders[4].delimiter == "."
    assert folders[6].delimiter is None


def _folders(*specs: tuple[str, str, set[str]]) -> list[Folder]:
    return [Folder(name=n, delimiter=d, flags=frozenset(f)) for n, d, f in specs]


def test_pick_sent_prefers_special_use() -> None:
    folders = _folders(("INBOX", "/", set()), ("Sent", "/", set()), ("[Gmail]/Gesendet", "/", {"\\sent"}))
    assert pick_sent(folders) == "[Gmail]/Gesendet"


def test_pick_sent_by_name_variants() -> None:
    assert pick_sent(_folders(("INBOX", ".", set()), ("INBOX.Sent", ".", set()))) == "INBOX.Sent"
    assert pick_sent(_folders(("INBOX", "/", set()), ("Sent Items", "/", set()))) == "Sent Items"
    assert pick_sent(_folders(("INBOX", "/", set()), ("Sent Messages", "/", set()))) == "Sent Messages"
    assert pick_sent(_folders(("Archive/2019/Sent", "/", set()), ("Sent", "/", set()))) == "Sent"
    assert pick_sent(_folders(("INBOX", "/", set()), ("Drafts", "/", set()))) is None
    assert pick_sent(_folders(("Sent", "/", {"\\noselect"}))) is None


def test_pick_inbox_is_case_insensitive() -> None:
    assert pick_inbox(_folders(("Inbox", "/", set()))) == "Inbox"
    assert pick_inbox([]) == "INBOX"


def test_modified_utf7_round_trip() -> None:
    assert utf7.decode("~peter/mail/&U,BTFw-/&ZeVnLIqe-") == "~peter/mail/台北/日本語"  # RFC 3501 example
    assert utf7.decode("Sent &- Received") == "Sent & Received"
    for name in ["भेजे गए", "Gesendete Objekte", "R&D", "Отправленные", "plain"]:
        assert utf7.decode(utf7.encode(name)) == name
    assert utf7.encode("R&D") == "R&-D"
    assert utf7.decode("broken&AAA") == "broken&AAA"


def test_fetch_response_parsing_handles_server_orderings() -> None:
    raw1, raw2 = b"Subject: one\r\n\r\nbody", b"Subject: two\r\n\r\nbody"
    data = [
        (b'1 (UID 41 INTERNALDATE "14-Oct-2026 10:22:33 +0530" BODY[] {24}', raw1),
        b")",
        # UID after the literal (seen on some servers)
        (b'2 (INTERNALDATE " 4-Oct-2026 09:00:00 +0000" BODY[] {24}', raw2),
        b" UID 42)",
        # Unsolicited flag update without UID: ignored
        b"3 (FLAGS (\\Seen))",
    ]
    messages = parse_fetch_messages(data)
    assert [(m.uid, m.raw) for m in messages] == [(41, raw1), (42, raw2)]
    assert messages[0].internaldate == datetime(
        2026, 10, 14, 10, 22, 33, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    assert messages[1].internaldate == datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


def test_fetch_size_parsing() -> None:
    data = [b"1 (UID 7 RFC822.SIZE 1200)", b"2 (RFC822.SIZE 99 UID 8)"]
    assert parse_fetch_sizes(data) == {7: 1200, 8: 99}


def test_helpers() -> None:
    assert imap_date(date(2026, 3, 5)) == "05-Mar-2026"
    assert quote_mailbox('Sent "Items"') == '"Sent \\"Items\\""'
    assert parse_internaldate(b"garbage") is None
    assert "secret" not in repr(ImapSettings("h", 993, "ssl", "u", "secret"))
