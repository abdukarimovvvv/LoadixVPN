from aiogram import Router

from bot.handlers import admin, buy, myvpn, ping, plans, referral, renew, start, status, support, trial


def build_router() -> Router:
    root = Router(name="root")
    root.include_router(start.router)
    root.include_router(plans.router)
    root.include_router(buy.router)
    root.include_router(myvpn.router)
    root.include_router(status.router)
    root.include_router(renew.router)
    root.include_router(trial.router)
    root.include_router(ping.router)
    root.include_router(support.router)
    root.include_router(referral.router)
    root.include_router(admin.router)
    return root
