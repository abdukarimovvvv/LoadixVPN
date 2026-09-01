from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, model_serializer


class TrialIn(BaseModel):
    email: str | None = None
    user_agent: str | None = None


class TrialOut(BaseModel):
    vless_uri: str
    qr_base64: str
    expire_date: datetime
    traffic_limit_gb: int
    bot_url: str

    @model_serializer(mode='wrap', when_used='json')
    def serialize_model(self, serializer, info):
        data = serializer(self)
        if data.get('traffic_limit_gb') == 0:
            data['traffic_limit_gb'] = "∞"
        return data
