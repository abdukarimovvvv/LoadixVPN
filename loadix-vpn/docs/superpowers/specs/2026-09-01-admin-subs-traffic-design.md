# Design: Admin panel — subscriptions list & traffic top

Date: 2026-09-01

## Context

The LoadixVPN admin panel is a Telegram bot menu (aiogram 3.x) backed by a FastAPI
backend (`backend/app/api/routes/admin.py`), authenticated via
`ADMIN_TELEGRAM_IDS` allowlist + `require_admin_telegram_id` dependency. There is
no separate web admin UI — `frontend/index.html` is an unrelated static page.

Today the admin "👥 Пользователи" button (`cb_users`, `bot/bot/handlers/admin.py`)
shows only the last 20 users' telegram_id/username/ban-role flags — no
subscription info. There is no traffic-usage view at all.

Traffic is already tracked: `Subscription.traffic_used_bytes` is refreshed every
5 minutes by `backend/app/services/scheduler.py::_check_traffic()`, which sums
`XUIClient.get_client_traffic(email)` across all devices on each active
subscription.

## Goals

1. One button to view all users together with their subscription status (plan,
   active/expired, expiry date), paginated.
2. One button to view a traffic-usage ranking across users, to spot the heaviest
   consumers.

## Non-goals

- No new authentication/authorization model — reuse the existing admin allowlist
  and `require_admin_telegram_id`.
- No live per-request Xray/3X-UI queries — traffic figures come from the existing
  DB cache (`traffic_used_bytes`), refreshed at most every 5 minutes by the
  scheduler. Acceptable staleness; avoids added load on 3X-UI.
- No CSV/file export.
- No per-device traffic breakdown — subscription-level totals only (matches
  current data model).

## Feature 1: Paginated user+subscription list

**Entry point:** new inline button "📋 Подписки" in `admin_menu()`
(`bot/bot/keyboards/admin.py`), placed next to "👥 Пользователи".
`callback_data="adm:subs:0"` (trailing int = zero-based page index).

**Backend:** `GET /api/admin/users/subscriptions?page={n}&page_size=10` added to
`backend/app/api/routes/admin.py` (router already has
`dependencies=[Depends(require_admin_telegram_id)]`, so no extra auth code
needed). Query: `User` outer-joined to each user's most recent `Subscription`
(joined to `Plan` for the plan name), ordered by `User.created_at DESC`,
`OFFSET page*10 LIMIT 10`. Response: `{items: [...], total: int, page: int,
page_size: 10}`. Each item: `telegram_id`, `username`, `plan_name` (nullable),
`status` (`active` / `expired` / `disabled` / `none`), `expire_date` (nullable
ISO string).

**Bot:** `backend_client.py` gets `admin_users_subscriptions(page: int) -> dict`
calling the endpoint above. `handlers/admin.py` gets `_render_subs(message,
page: int, edit: bool)` following the `_render_users` pattern — formats each row
as:

```
🆔 <telegram_id> @<username>
   📦 <plan_name> · <status_emoji> <status> · до <expire_date>
```
(or `— нет подписки` when `plan_name` is null). Below the list: pagination row
`[◀ Назад]  [Вперёд ▶]` with `callback_data="adm:subs:{page-1}"` /
`"adm:subs:{page+1}"` (omit whichever button would go out of bounds), then the
usual `[‹ Назад в меню]` row. New callback handler `cb_subs` matches
`F.data.startswith("adm:subs:")`, extracts the page, calls `_render_subs`.

**Page size:** 10 users/page, newest-registered first — matches the existing
"👥 Пользователи" list's feel and keeps each Telegram message short.

## Feature 2: Traffic usage top-20

**Entry point:** new inline button "📈 Трафик" in `admin_menu()`,
`callback_data="adm:traffic"`.

**Backend:** `GET /api/admin/subscriptions/traffic-top` added to the same admin
router. Query: `Subscription` where `status == ACTIVE`, joined to `User` and
`Plan`, `ORDER BY traffic_used_bytes DESC LIMIT 20`. Response: list of
`{telegram_id, username, plan_name, traffic_used_bytes, traffic_limit_gb}`
(`traffic_limit_gb == 0` means unlimited).

**Bot:** `backend_client.py::admin_traffic_top() -> list[dict]`.
`handlers/admin.py::_render_traffic(message, edit: bool)` formats:

```
#1 🆔 <telegram_id> @<username>
   📦 <plan_name> · <used_gb> GB / <limit_gb or "∞"> GB (<pct>%)
```

sorted as returned (already DESC). No pagination — fixed top-20, single
message. Footer: `[‹ Назад в меню]` only. New callback handler `cb_traffic`
matches `F.data == "adm:traffic"`.

**Scope:** top-20 among **active** subscriptions only (not banned/disabled/
expired) — this reflects current real load, not historical noise from churned
users.

**Data freshness:** reads `Subscription.traffic_used_bytes` as already
maintained by the existing scheduler job — no new Xray/3X-UI calls, no new
staleness beyond the existing 5-minute refresh cycle.

## Files touched

- `backend/app/api/routes/admin.py` — two new `GET` routes.
- `bot/bot/services/backend_client.py` — two new async client functions.
- `bot/bot/handlers/admin.py` — two new callback handlers + two render helpers.
- `bot/bot/keyboards/admin.py` — two new buttons in `admin_menu()`, pagination
  keyboard helper for the subscriptions list.

## Error handling

Both render helpers follow the existing convention in `_render_users` /
`_render_stats`: on backend error, edit the message to a short error line and
fall back to `admin_back()` keyboard rather than raising into the handler.

## Testing

- Backend: unit test for both new routes — empty DB, single page, page beyond
  range (`items: []`), unlimited-traffic plan formatting (`traffic_limit_gb ==
  0` → "∞").
- Bot: manual verification against a staging backend (existing project
  convention — no aiogram handler test suite currently exists).
