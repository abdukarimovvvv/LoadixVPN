from __future__ import annotations

import secrets

from app.core.config import settings

SERVER_ADDR = "panel.loadix.cyou"
SERVER_PORT = 38443


def generate_password() -> str:
    """Hysteria2 auth is HTTP-callback based (see hysteria_auth.py) — the
    standalone server has no per-peer config to write, so a device is just
    a random password checked against the DB on every connection."""
    return secrets.token_urlsafe(24)


def build_uri(password: str, name: str) -> str:
    from urllib.parse import quote

    tag = quote(name or "loadix")
    return (
        f"hysteria2://{quote(password)}@{SERVER_ADDR}:{SERVER_PORT}/"
        f"?sni={SERVER_ADDR}#{tag}"
    )
