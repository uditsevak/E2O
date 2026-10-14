import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_sessionmaker
from app.pipeline.normalize import normalize_raw_message
from app.sources.imap.client import ImapSettings
from app.sources.imap.connector import ImapConnector
from app.sources.sync import sync_source
from app.storage.blobs import get_blob_store
from tests.conftest import SignedIn
from tests.factories import make_source
from tests.fake_imap import FakeFolder, FakeMailbox, make_email

NOW = datetime.now(UTC)
PDF = b"%PDF-1.4 fake drawing"


async def _seed(signed_in: SignedIn, db: AsyncSession):  # type: ignore[no-untyped-def]
    client, ws = await signed_in()
    source = await make_source(db, uuid.UUID(ws["id"]), address="sales@dc.in")
    await db.commit()
    mb = FakeMailbox(folders={"INBOX": FakeFolder(), "Sent": FakeFolder()})
    mb.folders["INBOX"].add(
        NOW - timedelta(hours=5),
        make_email(
            subject="RFQ: SS316 slip-on flanges",
            sender="Anil Mehta <anil@buyer.co.in>",
            when=NOW - timedelta(hours=5),
            attachments=[("drawing.pdf", "application/pdf", PDF)],
        ),
    )
    mb.folders["INBOX"].add(
        NOW - timedelta(hours=2),
        make_email(
            subject="Newsletter: steel prices", sender="news@steel.example", when=NOW - timedelta(hours=2)
        ),
    )
    mb.folders["Sent"].add(
        NOW - timedelta(hours=1),
        make_email(
            subject="Re: RFQ: SS316 slip-on flanges", sender="sales@dc.in", when=NOW - timedelta(hours=1)
        ),
    )

    def factory(s):  # type: ignore[no-untyped-def]
        return ImapConnector(
            ImapSettings("h", 993, "ssl", "u", "app-password"),
            "INBOX",
            "Sent",
            client_factory=mb.client_factory,
        )

    blobs = get_blob_store()
    result = await sync_source(get_sessionmaker(), source.id, blobs, connector_factory=factory)
    for raw_id in result.new_raw_ids:
        async with get_sessionmaker()() as session:
            await normalize_raw_message(session, raw_id, blobs)
            await session.commit()
    return client, ws


async def test_list_search_and_filter(signed_in: SignedIn, db: AsyncSession) -> None:
    client, ws = await _seed(signed_in, db)
    base = f"/api/w/{ws['id']}/messages"

    listing = (await client.get(base)).json()
    assert listing["total"] == 3
    assert [m["subject"] for m in listing["items"]] == [
        "Re: RFQ: SS316 slip-on flanges",
        "Newsletter: steel prices",
        "RFQ: SS316 slip-on flanges",
    ]
    assert listing["items"][2]["source_name"] == "sales@dc.in"

    inbound = (await client.get(base, params={"direction": "inbound"})).json()
    assert inbound["total"] == 2
    assert (await client.get(base, params={"q": "anil"})).json()["total"] == 1
    assert (await client.get(base, params={"q": "SS316"})).json()["total"] == 2
    assert (await client.get(base, params={"q": "100%_"})).json()["total"] == 0  # LIKE wildcards escaped
    page = (await client.get(base, params={"limit": 1, "offset": 1})).json()
    assert [m["subject"] for m in page["items"]] == ["Newsletter: steel prices"]


async def test_detail_html_and_attachment(signed_in: SignedIn, db: AsyncSession) -> None:
    client, ws = await _seed(signed_in, db)
    base = f"/api/w/{ws['id']}"
    items = (await client.get(f"{base}/messages", params={"q": "Anil"})).json()["items"]
    detail = (await client.get(f"{base}/messages/{items[0]['id']}")).json()
    assert detail["from_name"] == "Anil Mehta"
    assert detail["to_addresses"] == [{"name": None, "address": "sales@dcengineering.in"}]
    assert "Please quote" in detail["body_text"]
    assert detail["has_html"] is False
    [att] = detail["attachments"]
    assert att["filename"] == "drawing.pdf"

    download = await client.get(f"{base}/attachments/{att['id']}/download")
    assert download.status_code == 200 and download.content == PDF
    assert download.headers["content-type"] == "application/pdf"
    assert "drawing.pdf" in download.headers["content-disposition"]
    assert download.headers["x-content-type-options"] == "nosniff"

    assert (await client.get(f"{base}/messages/{items[0]['id']}/html")).status_code == 404


async def test_overview(signed_in: SignedIn, db: AsyncSession) -> None:
    client, ws = await _seed(signed_in, db)
    overview = (await client.get(f"/api/w/{ws['id']}/overview")).json()
    assert overview["messages_this_week"] >= overview["messages_today"]
    assert overview["sources_connected"] == 1
    assert overview["sources_with_errors"] == 0
    assert overview["last_synced_at"] is not None
