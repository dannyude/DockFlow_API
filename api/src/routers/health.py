"""Health-check endpoints used for liveness/readiness monitoring."""

from fastapi import APIRouter

from api.src.config_package import settings

cfg = settings.get_settings()

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Return service metadata for infrastructure health probes."""
    return {
        "status": "ok",
        "service": cfg.app_name,
        "version": cfg.app_version,
        "environment": cfg.app_env,
    }
