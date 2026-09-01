from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


@dataclass
class XUIClientData:
    client_uuid: str
    email: str
    total_gb: int
    expire_ts_ms: int
    limit_ip: int = 1
    flow: str = ""
    enable: bool = True


class XUIError(RuntimeError):
    pass


class XUIClient:
    """Async wrapper around 3X-UI panel API. Supports STUB mode for local dev."""

    def __init__(self) -> None:
        self._base_url = settings.XUI_BASE_URL.rstrip("/")
        self._username = settings.XUI_USERNAME
        self._password = settings.XUI_PASSWORD
        self._inbound_id = settings.XUI_INBOUND_ID
        self._stub = settings.XUI_STUB
        self._cookie: str | None = None
        self._cookie_expires_at: float = 0
        self._lock = asyncio.Lock()

    @property
    def stub(self) -> bool:
        return self._stub

    async def _login(self, client: httpx.AsyncClient) -> None:
        async with self._lock:
            if self._cookie and time.time() < self._cookie_expires_at - 30:
                return
            r = await client.post(
                f"{self._base_url}/login",
                data={"username": self._username, "password": self._password},
                timeout=15,
            )
            if r.status_code != 200:
                raise XUIError(f"login failed: {r.status_code} {r.text}")
            data = r.json()
            if not data.get("success"):
                raise XUIError(f"login failed: {data}")
            self._cookie = "; ".join(f"{k}={v}" for k, v in r.cookies.items())
            self._cookie_expires_at = time.time() + 50 * 60

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        if self._stub:
            log.info("XUI STUB %s %s", method, path)
            return {"success": True, "msg": "stub", "obj": {}}
        async with httpx.AsyncClient(verify=False) as client:
            await self._login(client)
            headers = kwargs.pop("headers", {}) or {}
            if self._cookie:
                headers["Cookie"] = self._cookie
            r = await client.request(method, f"{self._base_url}{path}", headers=headers, timeout=20, **kwargs)
        if r.status_code != 200:
            raise XUIError(f"{method} {path} -> {r.status_code} {r.text}")
        return r.json()

    async def add_client(self, data: XUIClientData) -> None:
        if self._stub:
            log.info("XUI STUB add_client uuid=%s email=%s", data.client_uuid, data.email)
            return
        client_obj = {
            "id": data.client_uuid,
            "flow": data.flow,
            "email": data.email,
            "limitIp": data.limit_ip,
            "totalGB": data.total_gb * 1024 * 1024 * 1024,
            "expiryTime": data.expire_ts_ms,
            "enable": data.enable,
            "tgId": "",
            "subId": "",
        }
        payload = {
            "id": self._inbound_id,
            "settings": json.dumps({"clients": [client_obj]}),
        }
        resp = await self._request("POST", "/panel/api/inbounds/addClient", json=payload)
        if not resp.get("success"):
            raise XUIError(f"addClient failed: {resp}")

    async def update_client(self, data: XUIClientData) -> None:
        if self._stub:
            log.info("XUI STUB update_client uuid=%s", data.client_uuid)
            return
        client_obj = {
            "id": data.client_uuid,
            "flow": data.flow,
            "email": data.email,
            "limitIp": data.limit_ip,
            "totalGB": data.total_gb * 1024 * 1024 * 1024,
            "expiryTime": data.expire_ts_ms,
            "enable": data.enable,
            "tgId": "",
            "subId": "",
        }
        payload = {
            "id": self._inbound_id,
            "settings": json.dumps({"clients": [client_obj]}),
        }
        resp = await self._request(
            "POST", f"/panel/api/inbounds/updateClient/{data.client_uuid}", json=payload
        )
        if not resp.get("success"):
            raise XUIError(f"updateClient failed: {resp}")

    async def disable_client(self, client_uuid: str, email: str) -> None:
        if self._stub:
            log.info("XUI STUB disable_client uuid=%s", client_uuid)
            return
        client_obj = {"id": client_uuid, "email": email, "enable": False}
        payload = {"id": self._inbound_id, "settings": json.dumps({"clients": [client_obj]})}
        await self._request("POST", f"/panel/api/inbounds/updateClient/{client_uuid}", json=payload)

    async def delete_client(self, client_uuid: str) -> None:
        if self._stub:
            log.info("XUI STUB delete_client uuid=%s", client_uuid)
            return
        await self._request("POST", f"/panel/api/inbounds/{self._inbound_id}/delClient/{client_uuid}")

    async def get_client_traffic(self, email: str) -> int:
        if self._stub:
            return 0
        resp = await self._request("GET", f"/panel/api/inbounds/getClientTraffics/{email}")
        obj = resp.get("obj") or {}
        return int(obj.get("up", 0)) + int(obj.get("down", 0))


xui = XUIClient()
