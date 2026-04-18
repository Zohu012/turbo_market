from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.api.v1.auth import router as auth_router
from app.api.v1.vehicles import router as vehicles_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.sellers import router as sellers_router
from app.api.v1.admin import router as admin_router

# Public — login only
router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)

# All other routes require a valid JWT
_protected = APIRouter(dependencies=[Depends(get_current_user)])
_protected.include_router(vehicles_router)
_protected.include_router(analytics_router)
_protected.include_router(sellers_router)
_protected.include_router(admin_router)

router.include_router(_protected)
