from fastapi import Header, HTTPException, status

from app.core.config import settings


async def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    if not x_internal_token or x_internal_token != settings.INTERNAL_API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


async def require_admin_telegram_id(
    x_internal_token: str | None = Header(default=None),
    x_telegram_id: int | None = Header(default=None),
) -> int:
    await require_internal_token(x_internal_token)
    if x_telegram_id is None or x_telegram_id not in settings.admin_telegram_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return x_telegram_id
