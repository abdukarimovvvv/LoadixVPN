from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_serializer


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    price_rub: Decimal
    price_stars: int
    duration_days: int
    traffic_limit_gb: int
    device_limit: int
    is_active: bool
    is_trial: bool

    @model_serializer(mode='wrap', when_used='json')
    def serialize_model(self, serializer, info):
        """Custom serializer to convert unlimited traffic (0) to ∞."""
        data = serializer(self)
        if data.get('traffic_limit_gb') == 0:
            data['traffic_limit_gb'] = "∞"
        return data


class PlanCreateIn(BaseModel):
    code: str
    name: str
    price_rub: Decimal = Decimal("0")
    price_stars: int = 0
    duration_days: int
    traffic_limit_gb: int
    device_limit: int = 1
    is_active: bool = True
    is_trial: bool = False
