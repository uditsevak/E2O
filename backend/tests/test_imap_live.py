"""Integration tests against a real IMAP server.

Skipped unless E2O_IMAP_TEST is set to "host:ssl_port:starttls_port:username:password", e.g.
a throwaway local Dovecot with a self-signed certificate and cPanel-style "INBOX.Sent" folders
(see docs/dev-imap.md). The tests create and delete their own folders.
"""

import imaplib
import os
import ssl
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import Direction
from app.sources.base import SourceAuthError, SourceConfigError, SourceTemporaryError
from app.sources.imap import utf7
from app.sources.imap.client import ImapClient, ImapSettings, TlsCertificateError, quote_mailbox
from app.sources.imap.connector import ImapConnector
from tests.fake_imap import make_email

SPEC = os.environ.get("E2O_IMAP_TEST")
pytestmark = pytest.mark.skipif(not SPEC, reason="E2O_IMAP_TEST not set")


@pytest.fixture(scope="module")
def server() -> dict:
    assert SPEC
    host, ssl_port, starttls_port, username, password = SPEC.split(":")
    return {
        "host": host,
        "ssl_port": int(ssl_port),
        "starttls_port": int(starttls_port),
        "username": username,
        "password": password,
    }


def _settings(server: dict, **overrides: object) -> ImapSettings:
    values = {
        "host": server["host"],
        "port": server["ssl_port"],
        "security": "ssl",
        "username": server["username"],
        "password": server["password"],
        "tls_verify": False,
        "timeout": 10,
        **overrides,
    }
    return ImapSettings(**values)  # type: ignore[arg-type]


class Mailbox:
    """Writes test mail with plain imaplib, independent of the code under test."""

    def __init__(self, server: dict) -> None:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self.conn = imaplib.IMAP4_SSL(server["host"], server["ssl_port"], ssl_context=ctx)
        self.conn.login(server["username"], server["password"])
        self.created: list[str] = []

    def create(self, name: str) -> str:
        self.conn.create(quote_mailbox(name))
        self.created.append(name)
        return name

    def append(self, folder: str, raw: bytes, when: datetime) -> None:
        typ, _ = self.conn.append(
            quote_mailbox(folder), None, imaplib.Time2Internaldate(when.timestamp()), raw
        )
        assert typ == "OK"

    def flags(self, folder: str) -> list[bytes]:
        self.conn.select(quote_mailbox(folder), readonly=True)
        _, data = self.conn.fetch("1:*", "(FLAGS)")
        return [d for d in data if d]

    def close(self) -> None:
        for name in reversed(self.created):
            self.conn.delete(quote_mailbox(name))
        self.conn.logout()


@pytest.fixture
def mailbox(server: dict):  # type: ignore[no-untyped-def]
    mb = Mailbox(server)
    yield mb
    mb.close()


def test_self_signed_certificate_is_reported(server: dict) -> None:
    with pytest.raises(TlsCertificateError), ImapClient(_settings(server, tls_verify=True)):
        pass


def test_wrong_password(server: dict) -> None:
    with pytest.raises(SourceAuthError) as exc, ImapClient(_settings(server, password="wrong")):
        pass
    assert "rejected the username or password" in str(exc.value)


def test_unknown_host_and_closed_port(server: dict) -> None:
    with pytest.raises(SourceConfigError, match="couldn't find the mail server"):
        ImapClient(_settings(server, host="no-such-host.invalid")).open()
    with pytest.raises(SourceTemporaryError):
        ImapClient(_settings(server, port=1)).open()


def test_ssl_on_plain_port_gives_a_helpful_error(server: dict) -> None:
    with pytest.raises((SourceConfigError, SourceTemporaryError)):
        ImapClient(_settings(server, port=server["starttls_port"], security="ssl")).open()


def test_starttls(server: dict) -> None:
    with ImapClient(_settings(server, port=server["starttls_port"], security="starttls")) as client:
        assert any(f.name.upper() == "INBOX" for f in client.list_folders())


async def test_end_to_end_backfill_and_incremental(server: dict, mailbox: Mailbox) -> None:
    tag = uuid.uuid4().hex[:6]
    inbox = mailbox.create(f"INBOX.e2o-in-{tag}")
    sent = mailbox.create(f"INBOX.e2o-sent-{tag}")
    hindi = mailbox.create(f"INBOX.{utf7.encode('भेजे गए')}-{tag}")
    now = datetime.now(UTC)
    first = make_email(
        subject=f"RFQ {tag} flanges",
        when=now - timedelta(days=2),
        attachments=[("rfq.pdf", "application/pdf", b"%PDF-1.4 x")],
    )
    mailbox.append(inbox, first, now - timedelta(days=2))
    mailbox.append(inbox, make_email(subject=f"ancient {tag}"), now - timedelta(days=400))
    mailbox.append(
        sent, make_email(subject=f"Re: RFQ {tag} flanges", sender="sales@dc.test"), now - timedelta(days=1)
    )

    connector = ImapConnector(_settings(server), inbound_folder=inbox, outbound_folder=sent, batch_size=2)
    discovered = await connector.connect()
    folders = {f.name: f for f in discovered.details["folders"]}
    assert inbox in folders and sent in folders
    assert folders[hindi].display_name == f"INBOX.भेजे गए-{tag}"

    pages = [p async for p in connector.backfill(now - timedelta(days=30))]
    inbound = [i for p in pages if p.stream == Direction.inbound for i in p.items]
    outbound = [i for p in pages if p.stream == Direction.outbound for i in p.items]
    assert len(inbound) == 1 and len(outbound) == 1
    assert f"RFQ {tag} flanges".encode() in inbound[0].raw
    assert b"%PDF" in inbound[0].raw or b"JVBERi" in inbound[0].raw  # attachment came through (base64)
    assert inbound[0].received_at is not None

    # Read-only: nothing was marked as read.
    assert all(b"\\Seen" not in f for f in mailbox.flags(inbox))

    cursor = [p for p in pages if p.stream == Direction.inbound][-1].cursor
    assert [i for p in [p async for p in connector.fetch_new(cursor)] for i in p.items] == []

    mailbox.append(inbox, make_email(subject=f"new {tag}"), now)
    new_pages = [p async for p in connector.fetch_new(cursor)]
    new_items = [i for p in new_pages for i in p.items]
    assert len(new_items) == 1 and f"new {tag}".encode() in new_items[0].raw


async def test_sent_folder_detected_by_name_on_cpanel_layout(server: dict, mailbox: Mailbox) -> None:
    with ImapClient(_settings(server)) as client:
        names = {f.name for f in client.list_folders()}
    if "INBOX.Sent" not in names:
        mailbox.create("INBOX.Sent")
    result = await ImapConnector(_settings(server)).connect()
    assert result.config_updates["inbound_folder"] == "INBOX"
    assert result.config_updates["outbound_folder"] == "INBOX.Sent"
