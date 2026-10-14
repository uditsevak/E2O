import json
import uuid
from collections.abc import Callable
from functools import lru_cache
from importlib import resources
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import Ws, WsAdmin
from app.api.schemas import (
    FolderOut,
    ImapConnectIn,
    ImapPresetOut,
    ImapSettingsIn,
    ImapTestOut,
    SourceOut,
    SourceUpdateIn,
)
from app.config import get_settings
from app.core.crypto import decrypt_json, encrypt_json
from app.jobs.tasks import enqueue_sync
from app.models import RawMessage, SourceConnection, SourceKind, SourceStatus
from app.sources.base import SourceError
from app.sources.imap.client import Folder, ImapSettings
from app.sources.imap.connector import ImapConnector

router = APIRouter(tags=["sources"])

ImapConnectorFactory = Callable[[ImapSettings, str | None, str | None], ImapConnector]


def get_imap_connector_factory() -> ImapConnectorFactory:
    def factory(settings: ImapSettings, inbound: str | None, outbound: str | None) -> ImapConnector:
        return ImapConnector(settings, inbound_folder=inbound, outbound_folder=outbound)

    return factory


ImapFactory = Annotated[ImapConnectorFactory, Depends(get_imap_connector_factory)]


@lru_cache
def _presets() -> list[ImapPresetOut]:
    text = (resources.files("app.sources") / "imap_presets.json").read_text(encoding="utf-8")
    return [ImapPresetOut(**p) for p in json.loads(text)]


@router.get("/sources/imap-presets")
async def imap_presets() -> list[ImapPresetOut]:
    return _presets()


def _imap_settings(body: ImapSettingsIn) -> ImapSettings:
    return ImapSettings(
        host=body.host.strip(),
        port=body.port,
        security=body.security,  # type: ignore[arg-type]
        username=body.username.strip(),
        password=body.password,
        tls_verify=body.tls_verify,
        timeout=get_settings().imap_timeout_seconds,
    )


def _folder_out(folder: Folder) -> FolderOut:
    return FolderOut(name=folder.name, display_name=folder.display_name, special_use=folder.special_use)


async def _test_imap(body: ImapSettingsIn, factory: ImapConnectorFactory) -> ImapTestOut:
    connector = factory(_imap_settings(body), body.inbound_folder, body.outbound_folder)
    try:
        result = await connector.connect()
    except SourceError as exc:
        return ImapTestOut(ok=False, error=str(exc), error_code=exc.code)
    folders: list[Folder] = result.details.get("folders", [])
    return ImapTestOut(
        ok=True,
        inbound_folder=result.config_updates.get("inbound_folder"),
        outbound_folder=result.config_updates.get("outbound_folder"),
        folders=[_folder_out(f) for f in folders if f.selectable],
    )


async def _message_counts(ctx: Ws) -> dict[uuid.UUID, int]:
    rows = await ctx.db.execute(
        select(RawMessage.source_connection_id, func.count())
        .where(RawMessage.workspace_id == ctx.workspace_id)
        .group_by(RawMessage.source_connection_id)
    )
    return {source_id: count for source_id, count in rows.all()}


def _source_out(source: SourceConnection, count: int = 0) -> SourceOut:
    safe_keys = ("host", "port", "security", "username", "tls_verify", "inbound_folder", "outbound_folder")
    return SourceOut.model_validate(
        {
            **{c: getattr(source, c) for c in SourceOut.model_fields if hasattr(source, c)},
            "settings": {k: source.config.get(k) for k in safe_keys if k in source.config},
            "message_count": count,
        }
    )


async def _get_source(ctx: Ws, source_id: uuid.UUID) -> SourceConnection:
    source = await ctx.db.scalar(
        select(SourceConnection).where(
            SourceConnection.id == source_id, SourceConnection.workspace_id == ctx.workspace_id
        )
    )
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mailbox not found")
    return source


@router.get("/w/{workspace_id}/sources")
async def list_sources(ctx: Ws) -> list[SourceOut]:
    sources = (
        await ctx.db.scalars(
            select(SourceConnection)
            .where(SourceConnection.workspace_id == ctx.workspace_id)
            .order_by(SourceConnection.created_at)
        )
    ).all()
    counts = await _message_counts(ctx)
    return [_source_out(s, counts.get(s.id, 0)) for s in sources]


@router.get("/w/{workspace_id}/sources/{source_id}")
async def get_source(source_id: uuid.UUID, ctx: Ws) -> SourceOut:
    source = await _get_source(ctx, source_id)
    counts = await _message_counts(ctx)
    return _source_out(source, counts.get(source.id, 0))


@router.post("/w/{workspace_id}/sources/imap/test")
async def test_imap(body: ImapSettingsIn, ctx: WsAdmin, factory: ImapFactory) -> ImapTestOut:
    return await _test_imap(body, factory)


@router.post("/w/{workspace_id}/sources/imap", status_code=status.HTTP_201_CREATED)
async def connect_imap(body: ImapConnectIn, ctx: WsAdmin, factory: ImapFactory) -> SourceOut:
    settings = get_settings()
    check = await _test_imap(body, factory)
    if not check.ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, check.error or "Could not connect")

    email = body.email.strip().lower()
    backfill_days = settings.default_backfill_days if body.backfill_days is None else body.backfill_days
    source = SourceConnection(
        workspace_id=ctx.workspace_id,
        kind=SourceKind.imap,
        display_name=(body.display_name or email).strip(),
        account_address=email,
        config={
            "host": body.host.strip(),
            "port": body.port,
            "security": body.security,
            "username": body.username.strip(),
            "tls_verify": body.tls_verify,
            "inbound_folder": check.inbound_folder,
            "outbound_folder": check.outbound_folder,
        },
        credentials_encrypted=encrypt_json({"password": body.password}),
        status=SourceStatus.active,
        backfill_days=min(backfill_days, settings.max_backfill_days),
        created_by_id=ctx.user.id,
    )
    ctx.db.add(source)
    try:
        await ctx.db.commit()
    except IntegrityError:
        await ctx.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"{email} is already connected") from None
    await enqueue_sync(source.id)
    return _source_out(source)


@router.patch("/w/{workspace_id}/sources/{source_id}")
async def update_source(
    source_id: uuid.UUID, body: SourceUpdateIn, ctx: WsAdmin, factory: ImapFactory
) -> SourceOut:
    source = await _get_source(ctx, source_id)
    if body.display_name is not None:
        source.display_name = body.display_name.strip()

    reconnect = (
        body.password is not None or body.inbound_folder is not None or body.outbound_folder is not None
    )
    if reconnect:
        if source.kind != SourceKind.imap:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only IMAP mailboxes have these settings")
        if body.password is None and source.credentials_encrypted is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter the password to reconnect this mailbox")
        password = body.password or decrypt_json(source.credentials_encrypted or b"")["password"]
        check = await _test_imap(
            ImapSettingsIn(
                host=source.config["host"],
                port=source.config["port"],
                security=source.config.get("security", "ssl"),
                username=source.config["username"],
                password=password,
                tls_verify=source.config.get("tls_verify", True),
                inbound_folder=body.inbound_folder or source.config.get("inbound_folder"),
                outbound_folder=body.outbound_folder or source.config.get("outbound_folder"),
            ),
            factory,
        )
        if not check.ok:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, check.error or "Could not connect")
        source.config = {
            **source.config,
            "inbound_folder": check.inbound_folder,
            "outbound_folder": check.outbound_folder,
        }
        source.credentials_encrypted = encrypt_json({"password": password})
        source.status = SourceStatus.active
        source.last_error = None
        source.last_error_at = None

    if body.paused is not None and source.status in (SourceStatus.active, SourceStatus.paused):
        source.status = SourceStatus.paused if body.paused else SourceStatus.active

    await ctx.db.commit()
    if source.status == SourceStatus.active and (reconnect or body.paused is False):
        await enqueue_sync(source.id)
    counts = await _message_counts(ctx)
    return _source_out(source, counts.get(source.id, 0))


@router.post("/w/{workspace_id}/sources/{source_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_now(source_id: uuid.UUID, ctx: Ws) -> dict[str, bool]:
    source = await _get_source(ctx, source_id)
    if source.status != SourceStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "This mailbox is not active")
    return {"queued": await enqueue_sync(source.id)}


@router.delete("/w/{workspace_id}/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_source(source_id: uuid.UUID, ctx: WsAdmin) -> None:
    """Stop reading this mailbox and delete its stored password. Emails already imported stay."""
    source = await _get_source(ctx, source_id)
    source.credentials_encrypted = None
    source.status = SourceStatus.disconnected
    await ctx.db.commit()
