import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import Ws
from app.api.schemas import (
    AddressOut,
    AttachmentOut,
    MessageDetailOut,
    MessageListItemOut,
    MessageListOut,
    OverviewOut,
)
from app.models import Attachment, Direction, Message, SourceConnection, SourceStatus, Workspace
from app.storage.blobs import get_blob_store

router = APIRouter(tags=["messages"])


def _list_item(m: Message) -> MessageListItemOut:
    return MessageListItemOut(
        id=m.id,
        direction=m.direction,
        subject=m.subject,
        from_address=m.from_address,
        from_name=m.from_name,
        sent_at=m.sent_at,
        snippet=m.snippet,
        attachment_count=m.attachment_count,
        source_id=m.source_connection_id,
        source_name=m.source_connection.display_name,
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/w/{workspace_id}/messages")
async def list_messages(
    ctx: Ws,
    direction: Direction | None = None,
    source_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MessageListOut:
    conditions = [Message.workspace_id == ctx.workspace_id]
    if direction is not None:
        conditions.append(Message.direction == direction)
    if source_id is not None:
        conditions.append(Message.source_connection_id == source_id)
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        conditions.append(
            or_(
                Message.subject.ilike(pattern),
                Message.from_address.ilike(pattern),
                Message.from_name.ilike(pattern),
                Message.snippet.ilike(pattern),
            )
        )
    total = await ctx.db.scalar(select(func.count()).select_from(Message).where(*conditions)) or 0
    rows = (
        await ctx.db.scalars(
            select(Message)
            .where(*conditions)
            .order_by(Message.sent_at.desc().nulls_last(), Message.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return MessageListOut(items=[_list_item(m) for m in rows], total=total, limit=limit, offset=offset)


@router.get("/w/{workspace_id}/messages/{message_id}")
async def get_message(message_id: uuid.UUID, ctx: Ws) -> MessageDetailOut:
    message = await ctx.db.scalar(
        select(Message)
        .options(selectinload(Message.attachments))
        .where(Message.id == message_id, Message.workspace_id == ctx.workspace_id)
    )
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email not found")
    return MessageDetailOut(
        **_list_item(message).model_dump(),
        rfc_message_id=message.rfc_message_id,
        in_reply_to=message.in_reply_to,
        to_addresses=[AddressOut(**a) for a in message.to_addresses],
        cc_addresses=[AddressOut(**a) for a in message.cc_addresses],
        reply_to_addresses=[AddressOut(**a) for a in message.reply_to_addresses],
        body_text=message.body_text,
        has_html=bool(message.body_html),
        attachments=[AttachmentOut.model_validate(a) for a in message.attachments],
        parse_warnings=message.parse_warnings,
    )


# Shown inside a sandboxed iframe: no scripts, no remote images (tracking pixels), no forms.
_HTML_CSP = "default-src 'none'; img-src data: cid:; style-src 'unsafe-inline'; font-src data:"


@router.get("/w/{workspace_id}/messages/{message_id}/html")
async def get_message_html(message_id: uuid.UUID, ctx: Ws) -> Response:
    body_html = await ctx.db.scalar(
        select(Message.body_html).where(Message.id == message_id, Message.workspace_id == ctx.workspace_id)
    )
    if not body_html:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This email has no HTML version")
    return Response(
        content=body_html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": f"{_HTML_CSP}; sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/w/{workspace_id}/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: uuid.UUID, ctx: Ws) -> Response:
    attachment = await ctx.db.scalar(
        select(Attachment).where(Attachment.id == attachment_id, Attachment.workspace_id == ctx.workspace_id)
    )
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    data = await get_blob_store().get(attachment.blob_key)
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(attachment.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/w/{workspace_id}/overview")
async def overview(ctx: Ws) -> OverviewOut:
    workspace = await ctx.db.get_one(Workspace, ctx.workspace_id)
    tz = ZoneInfo(workspace.settings.get("timezone", "Asia/Kolkata"))
    now_local = datetime.now(tz)
    start_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    start_week = (
        (now_local - timedelta(days=now_local.weekday()))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )

    async def count_since(since: datetime) -> int:
        return (
            await ctx.db.scalar(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.workspace_id == ctx.workspace_id,
                    Message.direction == Direction.inbound,
                    Message.sent_at >= since,
                )
            )
            or 0
        )

    sources = (
        await ctx.db.scalars(
            select(SourceConnection).where(
                SourceConnection.workspace_id == ctx.workspace_id,
                SourceConnection.status != SourceStatus.disconnected,
            )
        )
    ).all()
    synced = [s.last_synced_at for s in sources if s.last_synced_at]
    return OverviewOut(
        messages_today=await count_since(start_today),
        messages_this_week=await count_since(start_week),
        sources_connected=len(sources),
        sources_with_errors=sum(1 for s in sources if s.status == SourceStatus.error or s.last_error),
        last_synced_at=max(synced) if synced else None,
    )
