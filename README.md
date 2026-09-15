# LoadixVPN

Telegram-first VPN-сервис на базе **VLESS Reality** (+ WireGuard). Trial через лендинг, платные подписки через Telegram-бота, выдача ключей — через 3X-UI / Xray.

Подробная документация (архитектура, локальный запуск, API, cron-джобы, интеграция с CryptoBot и 3X-UI) — в [`loadix-vpn/README.md`](loadix-vpn/README.md).

## Стек

- **Backend**: FastAPI + async SQLAlchemy + Alembic + APScheduler
- **Bot**: aiogram 3.x (long-polling)
- **БД**: PostgreSQL, Redis
- **VPN**: Xray (VLESS Reality) + WireGuard, управляются через 3X-UI
- **Прокси**: nginx (лендинг + reverse proxy)

## Структура репозитория

```
LoadixVPN/
└── loadix-vpn/
    ├── backend/    # FastAPI приложение
    ├── bot/        # Telegram-бот (aiogram)
    ├── frontend/   # лендинг с формой trial
    ├── nginx/      # reverse proxy конфиг
    └── docker-compose.yml
```

## Быстрый старт

```bash
cd loadix-vpn
cp .env.example .env
docker compose up -d --build
```

Подробности — в [loadix-vpn/README.md](loadix-vpn/README.md).

## Продакшен

Продакшен-окружение (Docker Compose) собирается образами из этого кода — после любого изменения нужен `docker compose build`, простого `--force-recreate` без пересборки недостаточно.

Часть эксплуатационной логики (например, детект использования VPN-ключа с нескольких устройств) живёт в отдельном системном хелпере на VPS вне Docker-контейнеров и требует отдельной синхронизации с этим репозиторием.
