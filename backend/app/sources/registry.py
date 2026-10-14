from app.config import get_settings
from app.core.crypto import decrypt_json
from app.models import SourceConnection, SourceKind
from app.sources.base import SourceConfigError, SourceConnector
from app.sources.imap.connector import ImapConnector, imap_settings_from


def build_connector(source: SourceConnection) -> SourceConnector:
    """Instantiate the connector for a stored connection (decrypting its credentials)."""
    settings = get_settings()
    if source.credentials_encrypted is None:
        raise SourceConfigError("This mailbox is disconnected. Connect it again to resume syncing.")
    credentials = decrypt_json(source.credentials_encrypted)
    if source.kind == SourceKind.imap:
        return ImapConnector(
            imap_settings_from(source.config, credentials, settings.imap_timeout_seconds),
            inbound_folder=source.config.get("inbound_folder"),
            outbound_folder=source.config.get("outbound_folder"),
            batch_size=settings.imap_fetch_batch_size,
            max_message_bytes=settings.max_message_bytes,
        )
    raise SourceConfigError(f"{source.kind.value} sources are not supported yet.")
