from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str

    BOT_TOKEN: str
    BOT_USERNAME: str | None = None

    INTERNAL_API_TOKEN: str = "change_me_internal"

    PAYMENT_PROVIDER_TOKEN: str = ""

    CRYPTOBOT_TOKEN: str | None = None
    CRYPTOBOT_WEBHOOK_SECRET: str
    CRYPTOBOT_ASSET: str = "USDT"
    CRYPTOBOT_BASE_URL: str = "https://pay.crypt.bot/api"

    XUI_BASE_URL: str
    XUI_USERNAME: str
    XUI_PASSWORD: str
    XUI_INBOUND_ID: int
    XUI_STUB: bool = True

    REALITY_PUBLIC_KEY: str
    REALITY_SHORT_ID: str = "00000000"
    REALITY_SNI: str
    REALITY_PORT: int = 443
    REALITY_FLOW: str = "xtls-rprx-vision"

    DOMAIN: str
    PUBLIC_BASE_URL: str = ""

    ADMIN_TELEGRAM_IDS: str = ""

    TRIAL_DURATION_HOURS: int = 24
    TRIAL_TRAFFIC_GB: int = 1
    TRIAL_DEVICE_LIMIT: int = 1

    NOTIFY_BEFORE_EXPIRE_HOURS: int = 24

    @property
    def admin_telegram_ids(self) -> set[int]:
        return {int(x) for x in self.ADMIN_TELEGRAM_IDS.split(",") if x.strip().isdigit()}


settings = Settings()
