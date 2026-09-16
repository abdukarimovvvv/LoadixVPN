from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_serializer


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_uuid: str
    name: str | None
    vless_uri: str
    created_at: datetime


class DeviceWithQR(DeviceOut):
    qr_base64: str


class DeviceAddIn(BaseModel):
    name: str | None = None


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plan_id: UUID
    status: str
    is_trial: bool
    start_date: datetime
    expire_date: datetime
    traffic_limit_gb: int
    traffic_used_bytes: int
    device_limit: int
    devices: list[DeviceOut] = []

    @model_serializer(mode='wrap', when_used='json')
    def serialize_model(self, serializer, info):
        data = serializer(self)
        if data.get('traffic_limit_gb') == 0:
            data['traffic_limit_gb'] = "∞"
        return data


class SubscriptionWithDevices(SubscriptionOut):
    devices: list[DeviceWithQR] = []


class RenewIn(BaseModel):
    telegram_id: int
    plan_code: str


class VpnConfigIn(BaseModel):
    name: str | None = None


class VpnRawConfigOut(BaseModel):
    config: str
    protocol: str
    qr_base64: str
