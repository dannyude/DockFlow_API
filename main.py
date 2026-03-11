"""FastAPI application entrypoint and startup lifecycle wiring."""

from contextlib import asynccontextmanager
from typing import Any, cast
from rich.traceback import install

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.src.config_package import settings
from api.src.database.model_registry import import_models
from api.src.database.postgres_client import Base, engine as async_engine
from api.src.rate_limit import limiter
from api.src.routers.health import router as health_router
from api.src.routers.jobs import router as jobs_router
from api.src.services.storage import ensure_bucket_exists
from api.src.tenant.routes.tenants import router as tenants_router

install(show_locals=True)

cfg = settings.get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize model metadata and storage dependencies on app startup."""
    import_models()
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ensure_bucket_exists()
    yield


app = FastAPI(title=cfg.app_name, version=cfg.app_version, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, cast(Any, _rate_limit_exceeded_handler))
app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(tenants_router)
