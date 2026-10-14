import uuid

import httpx
import pytest
from procrastinate.testing import InMemoryConnector
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sources import get_imap_connector_factory
from app.core.crypto import decrypt_json
from app.main import app
from app.models import SourceConnection, SourceStatus
from app.sources.imap.client import Folder, ImapSettings
from app.sources.imap.connector import ImapConnector
from tests.conftest import ClientFactory, SignedIn, signup
from tests.fake_imap import FakeFolder, FakeMailbox

PASSWORD = "app-password"


@pytest.fixture(autouse=True)
def fake_mailbox() -> FakeMailbox:
    mb = FakeMailbox(
        password=PASSWORD,
        delimiter=".",  # Dovecot / cPanel layout
        folders={"INBOX": FakeFolder(), "INBOX.Sent": FakeFolder(), "INBOX.Drafts": FakeFolder()},
    )

    def factory() -> object:
        def build(settings: ImapSettings, inbound: str | None, outbound: str | None) -> ImapConnector:
            return ImapConnector(settings, inbound, outbound, client_factory=mb.client_factory)

        return build

    app.dependency_overrides[get_imap_connector_factory] = factory
    yield mb
    app.dependency_overrides.pop(get_imap_connector_factory, None)


def _imap(**overrides: object) -> dict:
    return {
        "email": "Sales@DCEngineering.in",
        "host": "mail.dcengineering.in",
        "port": 993,
        "security": "ssl",
        "username": "sales@dcengineering.in",
        "password": PASSWORD,
        **overrides,
    }


async def test_presets(client: httpx.AsyncClient) -> None:
    presets = (await client.get("/api/sources/imap-presets")).json()
    ids = {p["id"] for p in presets}
    assert {"gmail", "zoho_in", "godaddy", "rediffmail_pro", "other"} <= ids
    assert next(p for p in presets if p["id"] == "microsoft")["available"] is False


async def test_test_connection(signed_in: SignedIn) -> None:
    client, ws = await signed_in()
    ok = (await client.post(f"/api/w/{ws['id']}/sources/imap/test", json=_imap())).json()
    assert ok["ok"] is True
    assert ok["inbound_folder"] == "INBOX" and ok["outbound_folder"] == "INBOX.Sent"
    assert {f["name"] for f in ok["folders"]} == {"INBOX", "INBOX.Sent", "INBOX.Drafts"}

    bad = (await client.post(f"/api/w/{ws['id']}/sources/imap/test", json=_imap(password="wrong"))).json()
    assert bad == {
        "ok": False,
        "error": "The mail server rejected the username or password.",
        "error_code": "auth_failed",
        "inbound_folder": None,
        "outbound_folder": None,
        "folders": [],
    }


async def test_connect_stores_encrypted_password_and_queues_sync(
    signed_in: SignedIn, db: AsyncSession, jobs: InMemoryConnector
) -> None:
    client, ws = await signed_in()
    resp = await client.post(f"/api/w/{ws['id']}/sources/imap", json=_imap(backfill_days=15))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["account_address"] == "sales@dcengineering.in"
    assert body["status"] == "active" and body["backfill_days"] == 15
    assert body["settings"]["outbound_folder"] == "INBOX.Sent"
    assert PASSWORD not in resp.text

    source = await db.get_one(SourceConnection, uuid.UUID(body["id"]))
    assert source.credentials_encrypted and PASSWORD.encode() not in source.credentials_encrypted
    assert decrypt_json(source.credentials_encrypted) == {"password": PASSWORD}
    assert "password" not in source.config

    queued = [j for j in jobs.jobs.values() if j["task_name"] == "sync_source"]
    assert [j["args"] for j in queued] == [{"source_id": body["id"]}]

    listing = await client.get(f"/api/w/{ws['id']}/sources")
    assert [s["id"] for s in listing.json()] == [body["id"]]
    assert PASSWORD not in listing.text

    dup = await client.post(f"/api/w/{ws['id']}/sources/imap", json=_imap())
    assert dup.status_code == 409


async def test_connect_rejects_bad_credentials(signed_in: SignedIn, db: AsyncSession) -> None:
    client, ws = await signed_in()
    resp = await client.post(f"/api/w/{ws['id']}/sources/imap", json=_imap(password="wrong"))
    assert resp.status_code == 422
    assert "rejected" in resp.json()["detail"]
    assert (await db.scalars(select(SourceConnection))).all() == []


async def test_members_cannot_connect_mailboxes(signed_in: SignedIn, make_client: ClientFactory) -> None:
    owner, ws = await signed_in("owner@example.com")
    token = (
        (await owner.post(f"/api/w/{ws['id']}/invites", json={"email": "m@example.com"}))
        .json()["accept_url"]
        .rsplit("/", 1)[-1]
    )
    member = make_client()
    await signup(member, "m@example.com")
    await member.post(f"/api/invites/{token}/accept")
    assert (await member.post(f"/api/w/{ws['id']}/sources/imap", json=_imap())).status_code == 403
    assert (await member.post(f"/api/w/{ws['id']}/sources/imap/test", json=_imap())).status_code == 403
    assert (await member.get(f"/api/w/{ws['id']}/sources")).status_code == 200


async def test_pause_resume_reconnect_and_disconnect(
    signed_in: SignedIn, db: AsyncSession, jobs: InMemoryConnector, fake_mailbox: FakeMailbox
) -> None:
    client, ws = await signed_in()
    sid = (await client.post(f"/api/w/{ws['id']}/sources/imap", json=_imap())).json()["id"]
    base = f"/api/w/{ws['id']}/sources/{sid}"

    paused = await client.patch(base, json={"paused": True})
    assert paused.json()["status"] == "paused"
    assert (await client.post(f"{base}/sync")).status_code == 409
    assert (await client.patch(base, json={"paused": False})).json()["status"] == "active"

    # Owner changed the mailbox password: sync marks the source as needing attention...
    source = await db.get_one(SourceConnection, uuid.UUID(sid))
    source.status = SourceStatus.error
    source.last_error = "The mail server rejected the username or password."
    await db.commit()
    # ...and entering the new password fixes it.
    fake_mailbox.password = "new-app-password"
    wrong = await client.patch(base, json={"password": "still-old"})
    assert wrong.status_code == 422
    fixed = await client.patch(base, json={"password": "new-app-password", "display_name": "Sales inbox"})
    assert fixed.status_code == 200
    assert fixed.json()["status"] == "active" and fixed.json()["last_error"] is None
    assert fixed.json()["display_name"] == "Sales inbox"

    assert (await client.delete(base)).status_code == 204
    await db.refresh(source)
    assert source.status == SourceStatus.disconnected and source.credentials_encrypted is None
    # Reconnecting a disconnected mailbox needs the password again.
    assert (await client.patch(base, json={"inbound_folder": "INBOX"})).status_code == 400


def test_folder_out_hides_unselectable() -> None:
    from app.api.sources import _folder_out

    out = _folder_out(Folder(name="&U,BTFw-", delimiter="/", flags=frozenset({"\\sent"})))
    assert out.display_name == "台北" and out.special_use == "sent"
