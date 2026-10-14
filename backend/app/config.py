from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Dev-only fallbacks so `uv run` works out of the box. Refused when ENV=prod.
_DEV_SECRET_KEY = "dev-insecure-secret-key-change-me"  # noqa: S105 - refused in prod
_DEV_ENCRYPTION_KEY = "s_puiGGRJN_voMN6V4QOUbOjoCOI5GrpiNbhmLC4Oks="


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"

    # Public URL of the web app. The API is served under {app_url}/api via the frontend proxy,
    # so cookies and OAuth redirects are same-origin.
    app_url: str = "http://localhost:3000"
    database_url: str = "postgresql+psycopg://e2o:e2o@localhost:5433/e2o"

    # Signs short-lived state (OAuth state cookie).
    secret_key: SecretStr = SecretStr(_DEV_SECRET_KEY)
    # Comma-separated Fernet keys. The first encrypts; all are tried for decryption (rotation).
    secrets_encryption_keys: SecretStr = SecretStr(_DEV_ENCRYPTION_KEY)

    session_cookie_name: str = "e2o_session"
    session_ttl_days: int = 30
    cookie_secure: bool | None = None  # defaults to True when app_url is https

    # Google sign-in for app users (OIDC: openid email profile). Separate from mailbox OAuth.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None

    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = "./var/blobs"
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None  # e.g. Cloudflare R2 / MinIO endpoint
    s3_region: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None

    sync_interval_minutes: int = 5
    default_backfill_days: int = 30
    max_backfill_days: int = 180
    imap_timeout_seconds: int = 30
    imap_fetch_batch_size: int = 25
    max_message_bytes: int = 40 * 1024 * 1024

    invite_ttl_days: int = 7

    log_level: str = "INFO"

    extra_allowed_origins: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _refuse_dev_secrets_in_prod(self) -> "Settings":
        if self.env == "prod":
            if self.secret_key.get_secret_value() == _DEV_SECRET_KEY:
                raise ValueError("SECRET_KEY must be set in prod")
            if self.secrets_encryption_keys.get_secret_value() == _DEV_ENCRYPTION_KEY:
                raise ValueError("SECRETS_ENCRYPTION_KEYS must be set in prod")
        return self

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_url.startswith("https://")

    @property
    def allowed_origins(self) -> set[str]:
        return {self.app_url.rstrip("/"), *(o.rstrip("/") for o in self.extra_allowed_origins)}

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def psycopg_conninfo(self) -> str:
        """Plain libpq URL (for procrastinate), derived from the SQLAlchemy URL."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
