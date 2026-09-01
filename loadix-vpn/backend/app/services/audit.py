from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

log = logging.getLogger(__name__)


async def write_audit(
    db: AsyncSession,
    *,
    actor_telegram_id: int | None,
    action: str,
    target: str | None = None,
    meta: dict | None = None,
    note: str | None = None,
) -> None:
    try:
        db.add(
            AuditLog(
                actor_telegram_id=actor_telegram_id,
                action=action,
                target=target,
                meta=meta,
                note=note,
            )
        )
        await db.flush()
    except Exception as e:
        log.warning("audit write failed: %s", e)
