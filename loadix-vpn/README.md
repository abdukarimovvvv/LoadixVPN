# LOADIX VPN — MVP SaaS

Telegram-first VPN-сервис на базе **VLESS Reality**. Trial — через лендинг, платные подписки — через Telegram-бота и CryptoBot, выдача ключей — через 3X-UI / Xray.

## Архитектура

| Сервис | Описание |
|--------|----------|
| `postgres` | основная БД (UTC) |
| `redis` | кэш / будущая очередь |
| `backend` | FastAPI + async SQLAlchemy + Alembic + APScheduler |
| `bot` | aiogram 3.x, long-polling |
| `nginx` | reverse proxy + статический landing |

3X-UI / Xray ставятся отдельно на VPS и подключаются по API (`XUI_*` env). Для локальной разработки есть `XUI_STUB=true` — все вызовы в 3X-UI логируются и возвращают success.

## Структура проекта

```
loadix-vpn/
├── backend/
│   ├── app/
│   │   ├── api/routes/        # public, subscription, payments, admin, bot_webhook
│   │   ├── core/              # config, logging, security
│   │   ├── db/                # base, session, seed
│   │   ├── models/            # users, plans, subscriptions, payments, trials
│   │   ├── schemas/           # pydantic v2
│   │   ├── services/          # xui_client, cryptobot, telegram, qr, vless, scheduler
│   │   └── main.py
│   ├── alembic/               # миграции
│   └── requirements.txt
├── bot/
│   └── bot/
│       ├── handlers/          # start, plans, buy, myvpn, status, renew, support, admin
│       ├── keyboards/
│       ├── services/          # backend_client
│       └── main.py
├── frontend/index.html        # landing + форма trial
├── nginx/nginx.conf
├── docker-compose.yml
├── .env.example
└── README.md
```

## Быстрый старт (локально)

```bash
cp .env.example .env
# отредактируйте BOT_TOKEN, BOT_USERNAME, ADMIN_TELEGRAM_IDS, INTERNAL_API_TOKEN
docker compose up -d --build
```

Что произойдёт автоматически:
1. `postgres` поднимется и пройдёт healthcheck.
2. `backend` дождётся postgres, прогонит `alembic upgrade head`, засидит дефолтные тарифы (`trial`, `week`, `month`, `quarter`), запустит APScheduler.
3. `bot` дождётся backend и запустит long-polling.
4. `nginx` отдаст landing на `http://localhost/` и проксирует API на `/api/`.

Проверка:
- `GET http://localhost/health` → `{"status":"ok"}`
- `GET http://localhost/api/plans` → список тарифов
- Telegram: `/start` боту → ответит приветствием и меню

## Telegram-бот

Команды пользователя:
- `/start` — приветствие + меню
- `/plans` — список тарифов
- `/buy` — купить (создание счёта в CryptoBot)
- `/myvpn` — VLESS URI + QR
- `/status` — срок действия и трафик
- `/renew` — продление
- `/support` — контакт поддержки

Админ-команды (доступны только telegram_id из `ADMIN_TELEGRAM_IDS`):
- `/admin` — панель
- `/stats` — статистика
- `/users` — последние пользователи
- `/broadcast` — рассылка (двухшаговая)
- `/ban <id>` / `/unban <id>`

Бот общается с backend по внутренней docker-сети с заголовком `X-Internal-Token: $INTERNAL_API_TOKEN`. Админские endpoints дополнительно проверяют `X-Telegram-Id` против `ADMIN_TELEGRAM_IDS` на backend.

## CryptoBot

1. Создайте магазин в [@CryptoBot](https://t.me/CryptoBot) → получите `CRYPTOBOT_TOKEN`.
2. В разделе **Webhooks** добавьте URL: `https://<DOMAIN>/api/payments/webhook`.
3. Заполните `.env`: `CRYPTOBOT_TOKEN`, `CRYPTOBOT_WEBHOOK_SECRET`, `CRYPTOBOT_ASSET=USDT`.
4. Сигнатура webhook проверяется как `HMAC-SHA256(sha256(token), body)` по заголовку `crypto-pay-api-signature`.

Flow оплаты:
- Пользователь → `/buy` → выбирает тариф → бот зовёт `POST /api/payments/invoice` → backend создаёт `Payment(pending)` + invoice в CryptoBot → возвращает `pay_url`.
- Пользователь оплачивает → CryptoBot шлёт webhook → backend:
  - проверяет HMAC,
  - находит `Payment` по `payload`,
  - помечает `paid`,
  - создаёт/продлевает `Subscription`,
  - вызывает `xui.add_client` / `update_client`,
  - отправляет VLESS URI и QR пользователю напрямую через Telegram Bot API.

## 3X-UI / Xray

На VPS:
1. Установите 3X-UI и Xray (см. официальный гид 3X-UI).
2. Сгенерируйте Reality keypair: `xray x25519` → запишите `private/public`.
3. Создайте inbound VLESS+Reality, запомните **inboundId**.
4. Заполните `.env`:
   - `XUI_BASE_URL=https://your-vps:54321`
   - `XUI_USERNAME`, `XUI_PASSWORD`, `XUI_INBOUND_ID`
   - `REALITY_PUBLIC_KEY` (публичная часть), `REALITY_SHORT_ID`, `REALITY_SNI`
   - `DOMAIN` — публичное доменное имя для VLESS URI
   - `XUI_STUB=false`

`XUIClient` поддерживает: login, addClient, updateClient, disableClient, deleteClient, getClientTraffics.

## Cron / APScheduler

Каждые 5 минут backend выполняет:
- `_expire_overdue` — `status=ACTIVE && expire_date<=now` → disable в 3X-UI, статус `EXPIRED`, уведомление пользователю.
- `_notify_expiring` — за 24 часа до окончания (`NOTIFY_BEFORE_EXPIRE_HOURS`) отправляется напоминание; флаг `notified_expiring` исключает повторы.
- `_check_traffic` — если активна реальная 3X-UI интеграция, обновляет `traffic_used_bytes`, при превышении лимита выключает клиента.

## Landing / Trial

`http://<host>/` → `frontend/index.html` (Bootstrap, без сборки). Форма POST → `/api/trial`:
- 1 trial на IP (`trials.ip_address UNIQUE`),
- длительность `TRIAL_DURATION_HOURS` (24h),
- лимит `TRIAL_TRAFFIC_GB` (1 GB),
- `device_limit=1`,
- ответ: `vless_uri`, `qr_base64`, `expire_date`, ссылка на бота.

Если за nginx — backend подхватит реальный IP клиента из `X-Forwarded-For` / `X-Real-IP`.

## API endpoints

Public:
- `POST /api/trial`
- `GET /api/plans`
- `POST /api/payments/webhook` (CryptoBot)

Internal (требуют `X-Internal-Token`):
- `GET /api/subscription/{telegram_id}`
- `GET /api/subscription/{telegram_id}/last`
- `POST /api/payments/invoice`

Admin (требуют `X-Internal-Token` + `X-Telegram-Id` в `ADMIN_TELEGRAM_IDS`):
- `GET /api/admin/users`
- `POST /api/admin/users/ban`
- `GET /api/admin/stats`
- `POST /api/admin/broadcast`

## Notes

- Все даты в UTC (`DateTime(timezone=True)`).
- Идентификаторы — `UUID4`.
- Статусы — строковые enum-значения (`UserRole`, `SubscriptionStatus`, `PaymentStatus`).
- Trial выдаётся анонимно — `subscriptions.user_id IS NULL`.
- Логи: stdout, уровень INFO.
- Production: смените `SECRET_KEY`, `INTERNAL_API_TOKEN`, `CRYPTOBOT_WEBHOOK_SECRET`; настройте TLS на nginx; зафиксируйте `XUI_STUB=false`.
