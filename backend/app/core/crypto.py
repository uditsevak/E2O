"""Encryption at rest for connector secrets (IMAP passwords, OAuth refresh tokens)."""

import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import get_settings


class SecretDecryptionError(RuntimeError):
    pass


@lru_cache
def _fernet() -> MultiFernet:
    raw = get_settings().secrets_encryption_keys.get_secret_value()
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("SECRETS_ENCRYPTION_KEYS is empty")
    return MultiFernet([Fernet(k) for k in keys])


def encrypt_json(data: dict[str, Any]) -> bytes:
    return _fernet().encrypt(json.dumps(data, separators=(",", ":")).encode())


def decrypt_json(token: bytes) -> dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(token))
    except InvalidToken as exc:
        raise SecretDecryptionError("could not decrypt stored credentials") from exc


def rotate(token: bytes) -> bytes:
    """Re-encrypt with the current primary key."""
    return _fernet().rotate(token)
