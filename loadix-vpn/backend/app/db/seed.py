from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import Plan

log = logging.getLogger(__name__)


# Stars-only pricing. traffic_limit_gb=0 means unlimited.
DEFAULT_PLANS: list[dict] = [
    {
        "code": "trial",
        "name": "Trial 24h",
        "price_rub": Decimal("0"),
        "price_stars": 0,
        "duration_days": 0,
        "traffic_limit_gb": 5,
        "device_limit": 1,
        "is_active": True,
        "is_trial": True,
    },
    {
        "code": "s_30",
        "name": "30 дней",
        "price_rub": Decimal("0"),
        "price_stars": 100,
        "duration_days": 30,
        "traffic_limit_gb": 0,
        "device_limit": 1,
        "is_active": True,
        "is_trial": False,
    },
    {
        "code": "s_45",
        "name": "45 дней",
        "price_rub": Decimal("0"),
        "price_stars": 150,
        "duration_days": 45,
        "traffic_limit_gb": 0,
        "device_limit": 3,
        "is_active": True,
        "is_trial": False,
    },
    {
        "code": "s_90",
        "name": "90 дней",
        "price_rub": Decimal("0"),
        "price_stars": 300,
        "duration_days": 90,
        "traffic_limit_gb": 0,
        "device_limit": 5,
        "is_active": True,
        "is_trial": False,
    },
]


async def seed_plans(db: AsyncSession) -> None:
    existing = (await db.execute(select(Plan.code))).scalars().all()
    existing_set = set(existing)
    created = 0
    for data in DEFAULT_PLANS:
        if data["code"] in existing_set:
            continue
        db.add(Plan(**data))
        created += 1
    if created:
        await db.commit()
        log.info("seeded %d plans", created)
