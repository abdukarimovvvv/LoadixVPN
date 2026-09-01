from __future__ import annotations

from urllib.parse import quote

from app.core.config import settings


def generate_vless_reality_uri(client_uuid: str, email: str | None = None) -> str:
    host = settings.DOMAIN
    port = settings.REALITY_PORT
    params = (
        "encryption=none"
        "&security=reality"
        f"&sni={quote(settings.REALITY_SNI)}"
        "&fp=chrome"
        "&type=tcp"
        f"&flow={settings.REALITY_FLOW}"
        f"&pbk={quote(settings.REALITY_PUBLIC_KEY)}"
        f"&sid={settings.REALITY_SHORT_ID}"
    )
    tag = quote(email or "loadix")
    return f"vless://{client_uuid}@{host}:{port}?{params}#{tag}"
