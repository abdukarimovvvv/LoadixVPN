# Admin Subscriptions List & Traffic Top Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two admin panel features to the LoadixVPN Telegram bot: a paginated "all users with subscriptions" list, and a top-20 traffic-usage ranking.

**Architecture:** Follow the existing three-layer pattern used by every other admin feature: FastAPI route in `backend/app/api/routes/admin.py` (already gated by `require_admin_telegram_id` at router level) → thin async client function in `bot/bot/services/backend_client.py` → aiogram callback handler + render helper in `bot/bot/handlers/admin.py`, wired to a button in `bot/bot/keyboards/admin.py::admin_menu()`.

**Tech Stack:** Python, FastAPI, SQLAlchemy 2.0 async ORM, aiogram 3.x, httpx (bot→backend client), Pydantic.

## Global Constraints

- Reuse `require_admin_telegram_id` — do not add any new auth code (spec: "No new authentication/authorization model").
- Traffic figures read the existing DB-cached `Subscription.traffic_used_bytes` column only — no new calls to `XUIClient`/3X-UI (spec: "No live per-request Xray/3X-UI queries").
- Subscriptions list: 10 users per page, ordered by `User.created_at DESC` (spec Feature 1).
- Traffic top: fixed top 20, `Subscription.status == "active"` only, ordered by `traffic_used_bytes DESC` (spec Feature 2).
- No CSV/file export, no per-device traffic breakdown (spec non-goals).
- Follow existing code conventions exactly: `html.escape` for user-supplied text, `_render()` edit-in-place helper, `admin_back()` / `BackendError` error-handling pattern, `callback_data` prefixed `"adm:"`.
- This repo has no pytest/test infrastructure (verified: no `pytest` in `backend/requirements.txt`, no `conftest.py`, no `test_*.py` anywhere in `backend/`). Do not invent one. Verification steps in this plan use `curl` against a locally running backend (stub Xray mode) — matching how every existing admin endpoint in this codebase is actually verified.

---

## File Structure

- **Modify** `backend/app/api/routes/admin.py` — add two new `GET` routes: `/admin/users/subscriptions` and `/admin/subscriptions/traffic-top`.
- **Modify** `backend/app/schemas/admin.py` — add two new Pydantic response models: `UserSubscriptionItem`/`UserSubscriptionsPage`, `TrafficTopItem`.
- **Modify** `bot/bot/services/backend_client.py` — add `admin_users_subscriptions(telegram_id, page, page_size=10)` and `admin_traffic_top(telegram_id)`.
- **Modify** `bot/bot/keyboards/admin.py` — add two buttons to `admin_menu()`, add new `admin_subs_pagination(page, has_prev, has_next)` keyboard helper.
- **Modify** `bot/bot/handlers/admin.py` — add `_render_subs()`, `_render_traffic()` render helpers and `cb_subs`, `cb_traffic` callback handlers.

---

### Task 1: Backend schema + `/admin/users/subscriptions` route

**Files:**
- Modify: `backend/app/schemas/admin.py`
- Modify: `backend/app/api/routes/admin.py`

**Interfaces:**
- Produces: `GET /admin/users/subscriptions?page={int}&page_size={int}` (mounted under router prefix `/admin`, so full path `/api/admin/users/subscriptions`) returning JSON:
  ```json
  {
    "items": [
      {"telegram_id": 123, "username": "bob", "plan_name": "Месяц", "status": "active", "expire_date": "2026-10-01T00:00:00+00:00"}
    ],
    "total": 42,
    "page": 0,
    "page_size": 10
  }
  ```
  `plan_name` and `status`/`expire_date` are `null` when the user has no subscription at all. `status` is one of `"active"`, `"expired"`, `"disabled"`, or `null`.

- [ ] **Step 1: Add response schemas**

Open `backend/app/schemas/admin.py` and add at the end of the file:

```python
class UserSubscriptionItem(BaseModel):
    telegram_id: int
    username: str | None = None
    plan_name: str | None = None
    status: str | None = None
    expire_date: str | None = None


class UserSubscriptionsPage(BaseModel):
    items: list[UserSubscriptionItem]
    total: int
    page: int
    page_size: int
```

- [ ] **Step 2: Add the route**

Open `backend/app/api/routes/admin.py`. Add this import alongside the existing schema import (near line 18):

```python
from app.schemas.admin import BanIn, BroadcastIn, BroadcastOut, GrantIn, StatsOut, TrafficTopItem, UserSubscriptionItem, UserSubscriptionsPage
```

(the `TrafficTopItem` name is added here now so Task 1 and Task 2 don't produce a merge conflict on the same import line — it is defined in Task 2, Step 1, before this route file is exercised end-to-end).

Add the route directly after `admin_users` (after line 40, before `admin_user_card` at line 43):

```python
@router.get("/users/subscriptions", response_model=UserSubscriptionsPage)
async def admin_users_subscriptions(
    page: int = 0, page_size: int = 10, db: AsyncSession = Depends(get_db)
) -> UserSubscriptionsPage:
    from app.models.plan import Plan

    if page < 0:
        page = 0
    if page_size < 1 or page_size > 100:
        page_size = 10

    total = (await db.execute(select(func.count(User.id)))).scalar_one()

    res = await db.execute(
        select(User)
        .order_by(User.created_at.desc())
        .limit(page_size)
        .offset(page * page_size)
    )
    users = list(res.scalars().all())

    items: list[UserSubscriptionItem] = []
    for u in users:
        res2 = await db.execute(
            select(Subscription)
            .where(Subscription.user_id == u.id)
            .order_by(Subscription.start_date.desc())
            .limit(1)
        )
        sub = res2.scalar_one_or_none()
        plan_name = None
        status = None
        expire_date = None
        if sub is not None:
            status = sub.status
            expire_date = sub.expire_date.isoformat()
            plan = await db.get(Plan, sub.plan_id)
            plan_name = plan.name if plan else None
        items.append(
            UserSubscriptionItem(
                telegram_id=u.telegram_id,
                username=u.username,
                plan_name=plan_name,
                status=status,
                expire_date=expire_date,
            )
        )

    return UserSubscriptionsPage(items=items, total=int(total), page=page, page_size=page_size)
```

- [ ] **Step 3: Verify the backend starts and the route responds**

Run (from `loadix-vpn/`):
```bash
docker compose up -d backend
sleep 3
curl -s -H "X-Internal-Token: $(grep '^INTERNAL_API_TOKEN=' .env | cut -d= -f2)" \
     -H "X-Telegram-Id: $(grep '^ADMIN_TELEGRAM_IDS=' .env | cut -d= -f2 | cut -d, -f1)" \
     "http://localhost:8000/api/admin/users/subscriptions?page=0&page_size=10" | python3 -m json.tool
```
Expected: HTTP 200, JSON with `items` (array, possibly empty), `total`, `page: 0`, `page_size: 10`. If `.env` has no admin ID / token set locally, first set `ADMIN_TELEGRAM_IDS` and `INTERNAL_API_TOKEN` in `.env`, then `docker compose up -d backend` again to pick them up (per project convention — `restart` alone does not reload `.env`, must recreate the container).

- [ ] **Step 4: Commit**

```bash
cd /Users/oybekabdukarimov/Desktop/LoadixVPN/loadix-vpn
git add backend/app/schemas/admin.py backend/app/api/routes/admin.py
git commit -m "feat(backend): add /admin/users/subscriptions paginated list endpoint"
```

---

### Task 2: Backend `/admin/subscriptions/traffic-top` route

**Files:**
- Modify: `backend/app/schemas/admin.py`
- Modify: `backend/app/api/routes/admin.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent route), but Task 1's Step 2 import line already references `TrafficTopItem` by name — this task's Step 1 must define it with that exact name for Task 1's import to resolve.
- Produces: `GET /admin/subscriptions/traffic-top` (full path `/api/admin/subscriptions/traffic-top`) returning JSON:
  ```json
  {
    "items": [
      {"telegram_id": 123, "username": "bob", "plan_name": "Месяц", "traffic_used_bytes": 1073741824, "traffic_limit_gb": 50}
    ]
  }
  ```
  `traffic_limit_gb == 0` means unlimited. List is already sorted descending by `traffic_used_bytes`, max 20 items.

- [ ] **Step 1: Add response schemas**

Open `backend/app/schemas/admin.py` and add at the end of the file:

```python
class TrafficTopItem(BaseModel):
    telegram_id: int
    username: str | None = None
    plan_name: str | None = None
    traffic_used_bytes: int
    traffic_limit_gb: int


class TrafficTopOut(BaseModel):
    items: list[TrafficTopItem]
```

- [ ] **Step 2: Add the route**

Open `backend/app/api/routes/admin.py`. Extend the import from Task 1, Step 2 to also include `TrafficTopOut` (it should now read):

```python
from app.schemas.admin import BanIn, BroadcastIn, BroadcastOut, GrantIn, StatsOut, TrafficTopItem, TrafficTopOut, UserSubscriptionItem, UserSubscriptionsPage
```

Add the route directly after the `admin_users_subscriptions` route added in Task 1 (before `admin_user_card`):

```python
@router.get("/subscriptions/traffic-top", response_model=TrafficTopOut)
async def admin_traffic_top(db: AsyncSession = Depends(get_db)) -> TrafficTopOut:
    from app.models.plan import Plan

    res = await db.execute(
        select(Subscription)
        .where(Subscription.status == SubscriptionStatus.ACTIVE.value)
        .order_by(Subscription.traffic_used_bytes.desc())
        .limit(20)
    )
    subs = list(res.scalars().all())

    items: list[TrafficTopItem] = []
    for sub in subs:
        user = await db.get(User, sub.user_id) if sub.user_id else None
        plan = await db.get(Plan, sub.plan_id)
        items.append(
            TrafficTopItem(
                telegram_id=user.telegram_id if user else 0,
                username=user.username if user else None,
                plan_name=plan.name if plan else None,
                traffic_used_bytes=sub.traffic_used_bytes,
                traffic_limit_gb=sub.traffic_limit_gb,
            )
        )

    return TrafficTopOut(items=items)
```

- [ ] **Step 3: Verify the backend starts and the route responds**

Run (from `loadix-vpn/`):
```bash
docker compose up -d backend
sleep 3
curl -s -H "X-Internal-Token: $(grep '^INTERNAL_API_TOKEN=' .env | cut -d= -f2)" \
     -H "X-Telegram-Id: $(grep '^ADMIN_TELEGRAM_IDS=' .env | cut -d= -f2 | cut -d, -f1)" \
     "http://localhost:8000/api/admin/subscriptions/traffic-top" | python3 -m json.tool
```
Expected: HTTP 200, JSON with `items` (array, possibly empty, at most 20 entries, `traffic_used_bytes` descending).

- [ ] **Step 4: Commit**

```bash
cd /Users/oybekabdukarimov/Desktop/LoadixVPN/loadix-vpn
git add backend/app/schemas/admin.py backend/app/api/routes/admin.py
git commit -m "feat(backend): add /admin/subscriptions/traffic-top endpoint"
```

---

### Task 3: Bot backend_client functions

**Files:**
- Modify: `bot/bot/services/backend_client.py`

**Interfaces:**
- Consumes: `GET /api/admin/users/subscriptions` (Task 1), `GET /api/admin/subscriptions/traffic-top` (Task 2) — both live once Tasks 1–2 are deployed; this task can be written and reviewed independently since it only calls `_request()`.
- Produces:
  - `admin_users_subscriptions(telegram_id: int, page: int = 0, page_size: int = 10) -> dict` — returns the raw `{items, total, page, page_size}` JSON.
  - `admin_traffic_top(telegram_id: int) -> dict` — returns the raw `{items}` JSON.

- [ ] **Step 1: Add the two client functions**

Open `bot/bot/services/backend_client.py`. Add directly after `admin_users` (after line 245, before `admin_user_card`):

```python
async def admin_users_subscriptions(telegram_id: int, page: int = 0, page_size: int = 10) -> dict:
    return await _request(
        "GET",
        "/api/admin/users/subscriptions",
        telegram_id=telegram_id,
        params={"page": page, "page_size": page_size},
    )


async def admin_traffic_top(telegram_id: int) -> dict:
    return await _request(
        "GET",
        "/api/admin/subscriptions/traffic-top",
        telegram_id=telegram_id,
    )
```

- [ ] **Step 2: Verify with a manual smoke script**

With the backend running from Task 1/2 verification (`docker compose up -d backend`), and the bot's `.env` pointing `BACKEND_BASE_URL` at it, run from `loadix-vpn/bot/`:

```bash
cd /Users/oybekabdukarimov/Desktop/LoadixVPN/loadix-vpn/bot
python3 -c "
import asyncio, os, sys
sys.path.insert(0, '.')
os.environ.setdefault('BACKEND_BASE_URL', 'http://localhost:8000')
from bot.services.backend_client import admin_users_subscriptions, admin_traffic_top

async def main():
    admin_id = int(open('../.env').read().split('ADMIN_TELEGRAM_IDS=')[1].split()[0].split(',')[0])
    print(await admin_users_subscriptions(admin_id, page=0, page_size=10))
    print(await admin_traffic_top(admin_id))

asyncio.run(main())
"
```
Expected: two dicts printed, no exception, matching the shapes from Task 1 Step 3 / Task 2 Step 3.

- [ ] **Step 3: Commit**

```bash
cd /Users/oybekabdukarimov/Desktop/LoadixVPN/loadix-vpn
git add bot/bot/services/backend_client.py
git commit -m "feat(bot): add backend_client functions for subs list and traffic top"
```

---

### Task 4: Keyboards — menu buttons + subscriptions pagination

**Files:**
- Modify: `bot/bot/keyboards/admin.py`

**Interfaces:**
- Produces:
  - `admin_menu()` — modified to include two new buttons: `callback_data="adm:subs:0"` and `callback_data="adm:traffic"`.
  - `admin_subs_pagination(page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup` — new helper: a row with "◀ Назад" (`callback_data=f"adm:subs:{page-1}"`, only if `has_prev`) and "Вперёд ▶" (`callback_data=f"adm:subs:{page+1}"`, only if `has_next`), followed by the standard `[‹ В админку]` row.

- [ ] **Step 1: Add the two menu buttons**

Open `bot/bot/keyboards/admin.py`. Modify `admin_menu()` (lines 6–25) — add a new row after the "👥 Пользователи / 👤 Найти юзера" row:

```python
def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
            [
                InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users"),
                InlineKeyboardButton(text="👤 Найти юзера", callback_data="adm:find"),
            ],
            [
                InlineKeyboardButton(text="📋 Подписки", callback_data="adm:subs:0"),
                InlineKeyboardButton(text="📈 Трафик", callback_data="adm:traffic"),
            ],
            [
                InlineKeyboardButton(text="🎁 Выдать тариф", callback_data="adm:grant"),
                InlineKeyboardButton(text="🚫 Бан / Анбан", callback_data="adm:ban"),
            ],
            [
                InlineKeyboardButton(text="🎟️ Промокоды", callback_data="adm:promo"),
                InlineKeyboardButton(text="📣 Рассылка", callback_data="adm:broadcast"),
            ],
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:refresh")],
            [InlineKeyboardButton(text="‹ Назад в меню", callback_data="back:menu")],
        ]
    )
```

- [ ] **Step 2: Add the pagination keyboard helper**

In the same file, add after `admin_back()` (after line 64):

```python
def admin_subs_pagination(page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    nav_row = []
    if has_prev:
        nav_row.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"adm:subs:{page - 1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶", callback_data=f"adm:subs:{page + 1}"))
    rows = [nav_row] if nav_row else []
    rows.append([InlineKeyboardButton(text="‹ В админку", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
```

- [ ] **Step 3: Verify with a quick import check**

```bash
cd /Users/oybekabdukarimov/Desktop/LoadixVPN/loadix-vpn/bot
python3 -c "
import sys; sys.path.insert(0, '.')
from bot.keyboards.admin import admin_menu, admin_subs_pagination
m = admin_menu()
assert any(b.callback_data == 'adm:subs:0' for row in m.inline_keyboard for b in row)
assert any(b.callback_data == 'adm:traffic' for row in m.inline_keyboard for b in row)
kb = admin_subs_pagination(0, has_prev=False, has_next=True)
assert kb.inline_keyboard[0][0].callback_data == 'adm:subs:1'
kb2 = admin_subs_pagination(1, has_prev=True, has_next=False)
assert kb2.inline_keyboard[0][0].callback_data == 'adm:subs:0'
print('OK')
"
```
Expected: prints `OK` with no assertion error.

- [ ] **Step 4: Commit**

```bash
cd /Users/oybekabdukarimov/Desktop/LoadixVPN/loadix-vpn
git add bot/bot/keyboards/admin.py
git commit -m "feat(bot): add admin menu buttons and pagination keyboard for subs/traffic"
```

---

### Task 5: Bot handlers — render helpers + callbacks

**Files:**
- Modify: `bot/bot/handlers/admin.py`

**Interfaces:**
- Consumes:
  - `admin_users_subscriptions(telegram_id, page, page_size=10) -> dict` (Task 3)
  - `admin_traffic_top(telegram_id) -> dict` (Task 3)
  - `admin_subs_pagination(page, has_prev, has_next) -> InlineKeyboardMarkup` (Task 4)
  - `admin_menu()`, `admin_back()`, `_render(msg, text, kb, edit)`, `_is_admin(uid)`, `BackendError` — all pre-existing.
- Produces:
  - `_render_subs(message: Message, telegram_id: int, page: int = 0, edit: bool = False) -> None`
  - `_render_traffic(message: Message, telegram_id: int, edit: bool = False) -> None`
  - Callback handlers `cb_subs` (matches `F.data.startswith("adm:subs:")`) and `cb_traffic` (matches `F.data == "adm:traffic"`).

- [ ] **Step 1: Update imports**

Open `bot/bot/handlers/admin.py`. Modify the imports at lines 13–27:

```python
from bot.keyboards.admin import admin_back, admin_grant_plans, admin_menu, admin_subs_pagination, promo_list_actions, promo_menu, user_card_actions
from bot.services.backend_client import (
    BackendError,
    admin_ban,
    admin_broadcast,
    admin_grant,
    admin_promo_create,
    admin_promo_list,
    admin_promo_toggle,
    admin_revoke_subscription,
    admin_stats,
    admin_traffic_top,
    admin_user_card,
    admin_users,
    admin_users_subscriptions,
    list_plans,
)
```

- [ ] **Step 2: Add `_render_subs` and `_render_traffic` helpers**

Add directly after `_render_users` (after line 92, before `_fmt_user_card`):

```python
_STATUS_LABEL = {"active": "✅ активна", "expired": "⏳ истекла", "disabled": "⛔ отключена"}


async def _render_subs(message: Message, telegram_id: int, page: int = 0, edit: bool = False) -> None:
    try:
        data = await admin_users_subscriptions(telegram_id, page=page, page_size=10)
    except BackendError as e:
        await _render(message, f"⚠️ Ошибка: {e.message}", admin_back(), edit)
        return
    items = data.get("items", [])
    total = data.get("total", 0)
    page_size = data.get("page_size", 10)
    if not items:
        await _render(message, "Пользователей нет.", admin_back(), edit)
        return
    total_pages = max(1, (total + page_size - 1) // page_size)
    lines = [f"📋 <b>Подписки пользователей</b> (стр. {page + 1}/{total_pages}, всего {total})\n"]
    for it in items:
        raw_username = it.get("username") or ""
        username = f"@{html.escape(raw_username)}" if raw_username else "—"
        lines.append(f"🆔 <code>{it['telegram_id']}</code> {username}")
        if it.get("plan_name"):
            status = _STATUS_LABEL.get(it.get("status") or "", it.get("status") or "—")
            expire = (it.get("expire_date") or "")[:10] or "—"
            lines.append(f"   📦 {html.escape(it['plan_name'])} · {status} · до {expire}")
        else:
            lines.append("   — нет подписки")
    kb = admin_subs_pagination(page, has_prev=page > 0, has_next=(page + 1) * page_size < total)
    await _render(message, "\n".join(lines), kb, edit)


async def _render_traffic(message: Message, telegram_id: int, edit: bool = False) -> None:
    try:
        data = await admin_traffic_top(telegram_id)
    except BackendError as e:
        await _render(message, f"⚠️ Ошибка: {e.message}", admin_back(), edit)
        return
    items = data.get("items", [])
    if not items:
        await _render(message, "Активных подписок с трафиком нет.", admin_back(), edit)
        return
    lines = ["📈 <b>Топ по расходу трафика</b> (среди активных)\n"]
    for i, it in enumerate(items, start=1):
        raw_username = it.get("username") or ""
        username = f"@{html.escape(raw_username)}" if raw_username else "—"
        used_gb = (it.get("traffic_used_bytes") or 0) / (1024 ** 3)
        limit_gb = it.get("traffic_limit_gb") or 0
        limit_label = "∞" if limit_gb == 0 else f"{limit_gb}"
        pct = f" ({used_gb / limit_gb * 100:.0f}%)" if limit_gb else ""
        plan_name = html.escape(it["plan_name"]) if it.get("plan_name") else "—"
        lines.append(f"#{i} 🆔 <code>{it['telegram_id']}</code> {username}")
        lines.append(f"   📦 {plan_name} · {used_gb:.2f} GB / {limit_label} GB{pct}")
    await _render(message, "\n".join(lines), admin_back(), edit)
```

- [ ] **Step 3: Add callback handlers**

Add directly after `cb_users` (after line 235, before `cb_grant_start`):

```python
@router.callback_query(F.data.startswith("adm:subs:"))
async def cb_subs(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    page = int(cb.data.split(":", 2)[2])
    await _render_subs(cb.message, cb.from_user.id, page=page, edit=True)
    await cb.answer()


@router.callback_query(F.data == "adm:traffic")
async def cb_traffic(cb: CallbackQuery) -> None:
    if not cb.from_user or not _is_admin(cb.from_user.id) or not cb.message:
        await cb.answer()
        return
    await _render_traffic(cb.message, cb.from_user.id, edit=True)
    await cb.answer()
```

- [ ] **Step 4: Verify with a module import check**

```bash
cd /Users/oybekabdukarimov/Desktop/LoadixVPN/loadix-vpn/bot
python3 -c "
import sys; sys.path.insert(0, '.')
import bot.handlers.admin as m
assert hasattr(m, '_render_subs')
assert hasattr(m, '_render_traffic')
assert hasattr(m, 'cb_subs')
assert hasattr(m, 'cb_traffic')
print('OK')
"
```
Expected: prints `OK` with no `ImportError`/`AttributeError`. This catches typos in the new imports (Step 1) before running the full bot.

- [ ] **Step 5: End-to-end manual verification against the running stack**

With backend running (Task 1/2 verification) and at least one test user + subscription seeded in the DB (use the existing `/grant` admin command against a test telegram_id if the DB is empty), start the bot:

```bash
cd /Users/oybekabdukarimov/Desktop/LoadixVPN/loadix-vpn
docker compose up -d backend bot
```

In Telegram, as an account listed in `ADMIN_TELEGRAM_IDS`, send `/admin`, then tap "📋 Подписки" — verify the list renders with pagination buttons that work in both directions, and tap "📈 Трафик" — verify the top list renders (or the empty-state message if no active subscriptions have traffic yet).

- [ ] **Step 6: Commit**

```bash
cd /Users/oybekabdukarimov/Desktop/LoadixVPN/loadix-vpn
git add bot/bot/handlers/admin.py
git commit -m "feat(bot): render subscriptions list and traffic top in admin panel"
```

---

## Self-Review

**Spec coverage:**
- Feature 1 (paginated user+subscription list, 10/page, newest first, plan/status/expiry) → Tasks 1, 3, 4, 5. ✅
- Feature 2 (traffic top-20, active subscriptions only, DB-cached `traffic_used_bytes`, no live Xray calls) → Tasks 2, 3, 5. ✅
- Non-goals respected: no new auth code, no CSV export, no per-device breakdown, no live 3X-UI calls — confirmed none of the tasks touch `XUIClient` or `core/security.py`. ✅
- Error handling convention (`BackendError` → `admin_back()` fallback) → present in both `_render_subs` and `_render_traffic`. ✅
- File list matches spec's "Files touched" section exactly (`admin.py` backend routes, `backend_client.py`, `handlers/admin.py`, `keyboards/admin.py`), plus `schemas/admin.py` which the spec's route description implies (response models) but didn't list explicitly — added here since FastAPI routes need a `response_model`. ✅

**Placeholder scan:** No TBD/TODO; all code blocks are complete and copy-pasteable. ✅

**Type consistency:** `admin_users_subscriptions` returns `dict` in both `backend_client.py` (Task 3) and is consumed as `dict` in `_render_subs` (Task 5) — consistent. `admin_traffic_top` same. `admin_subs_pagination(page, has_prev, has_next)` signature matches between definition (Task 4) and call site (Task 5). Backend response field names (`items`, `total`, `page`, `page_size`, `telegram_id`, `username`, `plan_name`, `status`, `expire_date`, `traffic_used_bytes`, `traffic_limit_gb`) match 1:1 between Pydantic schemas (Tasks 1–2) and the `.get(...)` / `[...]` accesses in the render helpers (Task 5). ✅

**Testing note:** This repo has no pytest infrastructure; all verification steps use `curl`/manual Python snippets against the actual running stack, per Global Constraints.
