from __future__ import annotations

import hashlib
import hmac
import logging
from decimal import Decimal

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


class CryptoBotError(RuntimeError):
    pass


async def create_invoice(amount: Decimal, description: str, payload: str) -> dict:
    if not settings.CRYPTOBOT_TOKEN:
        raise CryptoBotError("CRYPTOBOT_TOKEN not configured")
    headers = {"Crypto-Pay-API-Token": settings.CRYPTOBOT_TOKEN}
    body = {
        "currency_type": "fiat",
        "fiat": "RUB",
        "amount": str(amount),
        "accepted_assets": "USDT,TON,BTC,ETH,BNB,TRX,USDC",
        "description": description[:1024],
        "payload": payload,
        "allow_comments": False,
        "allow_anonymous": True,
        "expires_in": 3600,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{settings.CRYPTOBOT_BASE_URL}/createInvoice", json=body, headers=headers)
    if r.status_code != 200:
        raise CryptoBotError(f"createInvoice http {r.status_code}: {r.text}")
    data = r.json()
    if not data.get("ok"):
        raise CryptoBotError(f"createInvoice failed: {data}")
    return data["result"]


def verify_webhook_signature(body: bytes, signature: str | None) -> bool:
    if not signature or not settings.CRYPTOBOT_TOKEN:
        return False
    secret = hashlib.sha256(settings.CRYPTOBOT_TOKEN.encode()).digest()
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
