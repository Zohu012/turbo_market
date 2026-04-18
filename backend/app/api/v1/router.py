from fastapi import APIRouter

from app.api.v1.vehicles import router as vehicles_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.sellers import router as sellers_router
from app.api.v1.admin import router as admin_router

router = APIRouter(prefix="/api/v1")
router.include_router(vehicles_router)
router.include_router(analytics_router)
router.include_router(sellers_router)
router.include_router(admin_router)
