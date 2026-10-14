"""The source connector contract.

A connector knows how to read one kind of source (an IMAP mailbox, Gmail, Microsoft Graph,
later IndiaMART / TradeIndia / WhatsApp). It only *reads*; nothing here sends, deletes or
marks anything as read.

Connectors are stateless between runs. Progress is an opaque, JSON-serialisable cursor per
stream that the sync job persists after every page, so a crash resumes where it stopped and
re-running a page is harmless (raw items are de-duplicated by `provider_item_id`).
"""

import abc
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from app.models import Direction, SourceKind

Cursor = dict[str, Any]


@dataclass(frozen=True)
class RawItem:
    """One message exactly as the source returned it."""

    provider_item_id: str  # unique within the connection
    direction: Direction
    raw: bytes
    media_type: str  # "message/rfc822" for email; JSON for portal leads / chat messages later
    folder: str | None = None
    received_at: datetime | None = None


@dataclass(frozen=True)
class FetchPage:
    stream: Direction
    items: list[RawItem]
    cursor: Cursor  # persist this after the items are stored
    skipped: int = 0  # items deliberately not fetched (e.g. over the size limit)


@dataclass
class ConnectResult:
    """Outcome of validating credentials and discovering the account's layout."""

    # Non-secret settings learned while connecting (e.g. which folder is "Sent").
    config_updates: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


class SourceError(Exception):
    """Base for connector failures. `str(exc)` must be safe to show to the user."""

    code: ClassVar[str] = "source_error"
    retryable: ClassVar[bool] = True


class SourceAuthError(SourceError):
    """Credentials rejected. Needs the user; not retried."""

    code = "auth_failed"
    retryable = False


class SourceConfigError(SourceError):
    """Settings are wrong (host, port, folder). Needs the user; not retried."""

    code = "bad_config"
    retryable = False


class SourceTemporaryError(SourceError):
    """Network trouble, timeouts, server busy. Retried with backoff."""

    code = "temporary"
    retryable = True


class SourceConnector(abc.ABC):
    kind: ClassVar[SourceKind]

    @abc.abstractmethod
    async def connect(self) -> ConnectResult:
        """Validate credentials and discover settings. Must not read message content."""

    @abc.abstractmethod
    def backfill(self, since: datetime) -> AsyncGenerator[FetchPage]:
        """Everything (inbound and outbound) received/sent on or after `since`."""

    @abc.abstractmethod
    def fetch_new(self, cursor: Cursor | None) -> AsyncGenerator[FetchPage]:
        """Inbound items after `cursor`."""

    @abc.abstractmethod
    def fetch_sent(self, cursor: Cursor | None) -> AsyncGenerator[FetchPage]:
        """Outbound items (the business's replies) after `cursor`. Sources without a concept
        of sent items yield nothing."""
