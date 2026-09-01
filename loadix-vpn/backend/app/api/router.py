from fastapi import APIRouter

from app.api.routes.admin import router as admin_router
from app.api.routes.bot_webhook import router as bot_router
from app.api.routes.payments import router as payments_router
from app.api.routes.public import router as public_router
from app.api.routes.promo import router as promo_router
from app.api.routes.referrals import router as referrals_router
from app.api.routes.subscription import router as subscription_router


api_router = APIRouter(prefix="/api")
api_router.include_router(public_router)
api_router.include_router(subscription_router)
api_router.include_router(payments_router)
api_router.include_router(admin_router)
api_router.include_router(bot_router)
api_router.include_router(referrals_router)
api_router.include_router(promo_router)
