from __future__ import annotations

import logging

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


async def send_message(chat_id: int, text: str, parse_mode: str | None = "HTML") -> bool:
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
    payload: dict[str, object] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
        if r.status_code != 200:
            log.warning("telegram sendMessage failed: %s %s", r.status_code, r.text)
            return False
        return True
    except Exception as e:
        log.exception("telegram sendMessage error: %s", e)
        return False


async def send_photo_bytes(chat_id: int, photo: bytes, caption: str | None = None) -> bool:
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendPhoto"
    data: dict[str, object] = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption
        data["parse_mode"] = "HTML"
    files = {"photo": ("qr.png", photo, "image/png")}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, data=data, files=files)
        if r.status_code != 200:
            log.warning("telegram sendPhoto failed: %s %s", r.status_code, r.text)
            return False
        return True
    except Exception as e:
        log.exception("telegram sendPhoto error: %s", e)
        return False
