"""IMAP "modified UTF-7" mailbox names (RFC 3501 §5.1.3).

Servers send folder names like "&BCcEMARBBEIEPgRC-" or "Gesendete Objekte"; we keep the raw
name for talking to the server and decode it only for showing people.
"""

import base64


def decode(name: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(name):
        ch = name[i]
        if ch != "&":
            out.append(ch)
            i += 1
            continue
        end = name.find("-", i)
        if end == -1:
            return name  # malformed; show as-is
        chunk = name[i + 1 : end]
        if not chunk:
            out.append("&")
        else:
            b64 = chunk.replace(",", "/")
            b64 += "=" * (-len(b64) % 4)
            try:
                out.append(base64.b64decode(b64).decode("utf-16-be"))
            except (ValueError, UnicodeDecodeError):
                return name
        i = end + 1
    return "".join(out)


def encode(name: str) -> str:
    out: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            data = "".join(pending).encode("utf-16-be")
            out.append("&" + base64.b64encode(data).decode().rstrip("=").replace("/", ",") + "-")
            pending.clear()

    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            pending.append(ch)
    flush()
    return "".join(out)
