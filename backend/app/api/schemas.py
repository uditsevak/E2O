import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.auth.passwords import MIN_PASSWORD_LENGTH
from app.models import Direction, Role, SourceKind, SourceStatus


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth -------------------------------------------------------------------------------------


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class UserOut(Out):
    id: uuid.UUID
    email: str
    name: str
    has_password: bool
    has_google: bool


class WorkspaceOut(Out):
    id: uuid.UUID
    name: str
    created_at: datetime


class MyWorkspaceOut(WorkspaceOut):
    role: Role


class MeOut(BaseModel):
    user: UserOut
    workspaces: list[MyWorkspaceOut]


class AuthConfigOut(BaseModel):
    google_enabled: bool


# --- workspaces & team ------------------------------------------------------------------------


class WorkspaceCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)


class MemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: Role
    joined_at: datetime


class MemberUpdateIn(BaseModel):
    role: Role


class InviteCreateIn(BaseModel):
    email: EmailStr
    role: Role = Role.member


class InviteOut(Out):
    id: uuid.UUID
    email: str
    role: Role
    created_at: datetime
    expires_at: datetime


class InviteCreatedOut(BaseModel):
    invite: InviteOut
    # Shown once; we store only a hash of the token.
    accept_url: str


class InvitePreviewOut(BaseModel):
    workspace_name: str
    email: str
    role: Role
    invited_by: str | None
    valid: bool
    reason: str | None = None


# --- sources ----------------------------------------------------------------------------------


class ImapSettingsIn(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=993, ge=1, le=65535)
    security: str = Field(default="ssl", pattern="^(ssl|starttls|none)$")
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=500)
    tls_verify: bool = True
    inbound_folder: str | None = None
    outbound_folder: str | None = None


class ImapConnectIn(ImapSettingsIn):
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=200)
    backfill_days: int | None = Field(default=None, ge=0)


class FolderOut(BaseModel):
    name: str  # as the server names it (use this when saving)
    display_name: str  # decoded for people
    special_use: str | None


class ImapTestOut(BaseModel):
    ok: bool
    error: str | None = None
    error_code: str | None = None
    inbound_folder: str | None = None
    outbound_folder: str | None = None
    folders: list[FolderOut] = []


class SourceOut(Out):
    id: uuid.UUID
    kind: SourceKind
    display_name: str
    account_address: str
    status: SourceStatus
    last_error: str | None
    last_error_at: datetime | None
    last_synced_at: datetime | None
    last_sync_started_at: datetime | None
    backfill_days: int
    backfill_completed_at: datetime | None
    created_at: datetime
    settings: dict[str, Any] = Field(description="Non-secret settings, e.g. host and folders")
    message_count: int = 0


class SourceUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    paused: bool | None = None
    password: str | None = Field(default=None, min_length=1, max_length=500)
    inbound_folder: str | None = None
    outbound_folder: str | None = None


class ImapPresetOut(BaseModel):
    id: str
    label: str
    host: str | None
    port: int
    security: str
    help: str
    help_url: str | None = None
    available: bool = True


# --- messages ---------------------------------------------------------------------------------


class AddressOut(BaseModel):
    name: str | None = None
    address: str


class AttachmentOut(Out):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    is_inline: bool


class MessageListItemOut(Out):
    id: uuid.UUID
    direction: Direction
    subject: str
    from_address: str | None
    from_name: str | None
    sent_at: datetime | None
    snippet: str
    attachment_count: int
    source_id: uuid.UUID
    source_name: str


class MessageListOut(BaseModel):
    items: list[MessageListItemOut]
    total: int
    limit: int
    offset: int


class MessageDetailOut(MessageListItemOut):
    rfc_message_id: str | None
    in_reply_to: str | None
    to_addresses: list[AddressOut]
    cc_addresses: list[AddressOut]
    reply_to_addresses: list[AddressOut]
    body_text: str
    has_html: bool
    attachments: list[AttachmentOut]
    parse_warnings: list[str]


class OverviewOut(BaseModel):
    messages_today: int
    messages_this_week: int
    sources_connected: int
    sources_with_errors: int
    last_synced_at: datetime | None
