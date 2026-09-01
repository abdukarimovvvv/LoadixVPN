from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    BOT_TOKEN: str
    BOT_USERNAME: str | None = None

    BACKEND_BASE_URL: str = "http://backend:8000"
    INTERNAL_API_TOKEN: str = "change_me_internal"

    ADMIN_TELEGRAM_IDS: str = ""
    SUPPORT_USERNAME: str = "support"
    DOMAIN: str = "example.com"

    # Telegram Payments provider token (e.g. YooKassa via @BotFather). Empty = disabled (fallback to CryptoBot).
    PAYMENT_PROVIDER_TOKEN: str = ""

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.ADMIN_TELEGRAM_IDS.split(",") if x.strip().isdigit()}


settings = Settings()
