from __future__ import annotations

import asyncio
import logging
import re
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
        self._csrf_token: str | None = None
        self._cookie_expires_at: float = 0
        self._lock = asyncio.Lock()

    @property
    def stub(self) -> bool:
        return self._stub

    async def _fetch_csrf_token(self, client: httpx.AsyncClient) -> str:
        r = await client.get(f"{self._base_url}/", timeout=15)
        r.raise_for_status()
        match = re.search(r'name="csrf-token" content="([^"]+)"', r.text)
        if not match:
            raise XUIError("could not find csrf-token on panel home page")
        # cookies set on this GET (pre-login session) carry over via the client's jar
        return match.group(1)

    async def _login(self, client: httpx.AsyncClient) -> None:
        async with self._lock:
            if self._cookie and time.time() < self._cookie_expires_at - 30:
                return
            csrf_token = await self._fetch_csrf_token(client)
            r = await client.post(
                f"{self._base_url}/login",
                json={"username": self._username, "password": self._password},
                headers={"X-CSRF-Token": csrf_token},
                timeout=15,
            )
            if r.status_code != 200:
                raise XUIError(f"login failed: {r.status_code} {r.text}")
            data = r.json()
            if not data.get("success"):
                raise XUIError(f"login failed: {data}")
            self._cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
            self._csrf_token = csrf_token
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
            if self._csrf_token:
                headers["X-CSRF-Token"] = self._csrf_token
            r = await client.request(method, f"{self._base_url}{path}", headers=headers, timeout=20, **kwargs)
        if r.status_code != 200:
            raise XUIError(f"{method} {path} -> {r.status_code} {r.text}")
        return r.json()

    async def _get_inbound(self) -> dict:
        resp = await self._request("GET", f"/panel/api/inbounds/get/{self._inbound_id}")
        obj = resp.get("obj")
        if not obj:
            raise XUIError(f"get inbound {self._inbound_id} failed: {resp}")
        return obj

    async def _update_inbound(self, inbound: dict) -> None:
        resp = await self._request(
            "POST", f"/panel/api/inbounds/update/{self._inbound_id}", json=inbound
        )
        if not resp.get("success"):
            raise XUIError(f"update inbound failed: {resp}")

    @staticmethod
    def _client_obj(data: XUIClientData) -> dict:
        return {
            "id": data.client_uuid,
            "flow": data.flow,
            "email": data.email,
            "limitIp": data.limit_ip,
            "totalGB": data.total_gb * 1024 * 1024 * 1024,
            "expiryTime": data.expire_ts_ms,
            "enable": data.enable,
            "tgId": 0,
            "subId": "",
        }

    async def add_client(self, data: XUIClientData) -> None:
        if self._stub:
            log.info("XUI STUB add_client uuid=%s email=%s", data.client_uuid, data.email)
            return
        inbound = await self._get_inbound()
        clients = inbound["settings"]["clients"]
        clients[:] = [c for c in clients if c.get("id") != data.client_uuid]
        clients.append(self._client_obj(data))
        await self._update_inbound(inbound)

    async def update_client(self, data: XUIClientData) -> None:
        if self._stub:
            log.info("XUI STUB update_client uuid=%s", data.client_uuid)
            return
        inbound = await self._get_inbound()
        clients = inbound["settings"]["clients"]
        clients[:] = [c for c in clients if c.get("id") != data.client_uuid]
        clients.append(self._client_obj(data))
        await self._update_inbound(inbound)

    async def disable_client(self, client_uuid: str, email: str) -> None:
        if self._stub:
            log.info("XUI STUB disable_client uuid=%s", client_uuid)
            return
        inbound = await self._get_inbound()
        clients = inbound["settings"]["clients"]
        for c in clients:
            if c.get("id") == client_uuid:
                c["enable"] = False
        await self._update_inbound(inbound)

    async def delete_client(self, client_uuid: str) -> None:
        if self._stub:
            log.info("XUI STUB delete_client uuid=%s", client_uuid)
            return
        inbound = await self._get_inbound()
        clients = inbound["settings"]["clients"]
        clients[:] = [c for c in clients if c.get("id") != client_uuid]
        await self._update_inbound(inbound)

    async def get_client_traffic(self, email: str) -> int:
        if self._stub:
            return 0
        inbound = await self._get_inbound()
        for stat in inbound.get("clientStats", []):
            if stat.get("email") == email:
                return int(stat.get("up", 0)) + int(stat.get("down", 0))
        return 0


xui = XUIClient()
