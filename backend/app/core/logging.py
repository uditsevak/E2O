"""Logging setup.

Rule: never log secrets or mail content. Log ids (workspace, source, message), counts and
error classes. The redaction filter below is a last line of defence, not a licence.
"""

import logging
import re

_SECRET_PATTERNS = [
    re.compile(
        r"(?i)(password|passwd|secret|token|authorization|api[_-]?key)(['\"]?\s*[:=]\s*)(['\"]?)[^\s'\",}]+"
    ),
]


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(r"\1\2\3[REDACTED]", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_e2o_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactSecretsFilter())
    root.addHandler(handler)
    root.setLevel(level)
    root._e2o_configured = True  # type: ignore[attr-defined]
