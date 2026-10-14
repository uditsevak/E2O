"""Tenant isolation: workspace A must never see or touch workspace B's data.

Two layers are tested:
1. Every API route under /api/w/{workspace_id}/... (discovered automatically, so new routes are
   covered without editing this file) refuses non-members, and object ids from another
   workspace are 404 even through a workspace the caller belongs to.
2. The ORM safety net: a session bound to a workspace filters reads/updates/deletes and refuses
   writes for another workspace even when a query forgets its `where`.
"""

import re
import uuid

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantViolation, bind_workspace
from app.db import get_sessionmaker
from app.main import app
from app.models import Attachment, Membership, Message, SourceConnection
from tests.conftest import SignedIn
from tests.factories import make_message, make_source

WORKSPACE_ROUTES = [
    (method.upper(), path)
    for path, operations in sorted(app.openapi()["paths"].items())
    if "{workspace_id}" in path
    for method in sorted(operations)
]


def test_route_sweep_found_routes() -> None:
    paths = {p for _, p in WORKSPACE_ROUTES}
    assert "/api/w/{workspace_id}/messages" in paths
    assert "/api/w/{workspace_id}/sources" in paths
    assert len(WORKSPACE_ROUTES) >= 15


def _fill(path: str, workspace_id: str, other: dict[str, str] | None = None) -> str:
    other = other or {}

    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name == "workspace_id":
            return workspace_id
        return other.get(name, str(uuid.uuid4()))

    return re.sub(r"\{(\w+)\}", repl, path)


@pytest.mark.parametrize(("method", "path"), WORKSPACE_ROUTES)
async def test_non_members_get_404_on_every_workspace_route(
    signed_in: SignedIn, method: str, path: str
) -> None:
    _, ws_b = await signed_in("b@example.com", workspace="B Corp")
    client_a, _ = await signed_in("a@example.com", workspace="A Corp")
    url = _fill(path, ws_b["id"])
    resp = await client_a.request(method, url, json={} if method in {"POST", "PATCH", "PUT"} else None)
    assert resp.status_code == 404, f"{method} {url} -> {resp.status_code} {resp.text}"


async def test_objects_of_another_workspace_are_not_reachable(signed_in: SignedIn, db: AsyncSession) -> None:
    client_a, ws_a = await signed_in("a@example.com", workspace="A Corp")
    _, ws_b = await signed_in("b@example.com", workspace="B Corp")
    source_b = await make_source(db, uuid.UUID(ws_b["id"]))
    message_b = await make_message(db, source_b)
    attachment_b = (await db.scalars(select(Attachment).where(Attachment.message_id == message_b.id))).one()
    await db.commit()

    a = ws_a["id"]
    checks = [
        ("GET", f"/api/w/{a}/messages/{message_b.id}"),
        ("GET", f"/api/w/{a}/messages/{message_b.id}/html"),
        ("GET", f"/api/w/{a}/attachments/{attachment_b.id}/download"),
        ("GET", f"/api/w/{a}/sources/{source_b.id}"),
        ("PATCH", f"/api/w/{a}/sources/{source_b.id}"),
        ("POST", f"/api/w/{a}/sources/{source_b.id}/sync"),
        ("DELETE", f"/api/w/{a}/sources/{source_b.id}"),
    ]
    for method, url in checks:
        resp = await client_a.request(method, url, json={} if method == "PATCH" else None)
        assert resp.status_code == 404, f"{method} {url} -> {resp.status_code}"

    listing = (await client_a.get(f"/api/w/{a}/messages")).json()
    assert listing["total"] == 0
    listing = (await client_a.get(f"/api/w/{a}/messages", params={"source_id": str(source_b.id)})).json()
    assert listing["total"] == 0
    assert (await client_a.get(f"/api/w/{a}/sources")).json() == []

    # Nothing was changed in B.
    await db.refresh(source_b)
    assert source_b.credentials_encrypted is not None


async def _two_workspaces(signed_in: SignedIn, db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    _, ws_a = await signed_in("a@example.com", workspace="A Corp")
    _, ws_b = await signed_in("b@example.com", workspace="B Corp")
    a, b = uuid.UUID(ws_a["id"]), uuid.UUID(ws_b["id"])
    await make_message(db, await make_source(db, a), subject="A's enquiry")
    await make_message(db, await make_source(db, b), subject="B's enquiry")
    await db.commit()
    return a, b


async def test_bound_session_filters_unscoped_reads(signed_in: SignedIn, db: AsyncSession) -> None:
    a, _ = await _two_workspaces(signed_in, db)
    async with get_sessionmaker()() as session:
        bind_workspace(session, a)
        subjects = (await session.scalars(select(Message.subject))).all()
        assert subjects == ["A's enquiry"]
        assert await session.scalar(select(func.count()).select_from(Message)) == 1
        # Joins and relationship loads stay inside the workspace too.
        joined = (await session.scalars(select(SourceConnection).join(Message))).all()
        assert {s.workspace_id for s in joined} == {a}
        assert len((await session.scalars(select(Membership))).all()) == 1


async def test_bound_session_filters_bulk_update_and_delete(signed_in: SignedIn, db: AsyncSession) -> None:
    a, b = await _two_workspaces(signed_in, db)
    async with get_sessionmaker()() as session:
        bind_workspace(session, a)
        await session.execute(update(Message).values(subject="overwritten"))
        await session.execute(delete(Attachment))
        await session.commit()

    subjects = dict((await db.execute(select(Message.workspace_id, Message.subject))).all())
    assert subjects == {a: "overwritten", b: "B's enquiry"}
    remaining = (await db.scalars(select(Attachment.workspace_id))).all()
    assert remaining == [b]


async def test_bound_session_refuses_writes_for_another_workspace(
    signed_in: SignedIn, db: AsyncSession
) -> None:
    a, b = await _two_workspaces(signed_in, db)
    async with get_sessionmaker()() as session:
        bind_workspace(session, a)
        session.add(
            SourceConnection(
                workspace_id=b, kind="imap", display_name="x", account_address="x@y.z", backfill_days=1
            )
        )
        with pytest.raises(TenantViolation):
            await session.flush()


async def test_bound_session_fills_in_workspace_on_new_rows(signed_in: SignedIn, db: AsyncSession) -> None:
    a, _ = await _two_workspaces(signed_in, db)
    async with get_sessionmaker()() as session:
        bind_workspace(session, a)
        source = SourceConnection(kind="imap", display_name="x", account_address="new@y.z", backfill_days=1)
        session.add(source)
        await session.flush()
        assert source.workspace_id == a


async def test_session_cannot_be_rebound(signed_in: SignedIn, db: AsyncSession) -> None:
    a, b = await _two_workspaces(signed_in, db)
    async with get_sessionmaker()() as session:
        bind_workspace(session, a)
        bind_workspace(session, a)  # idempotent
        with pytest.raises(TenantViolation):
            bind_workspace(session, b)
