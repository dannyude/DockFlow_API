"""Tenant management and tenant-authentication API routes."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.src.database.postgres_client import get_session
from api.src.dependencies import get_current_tenant
from api.src.rate_limit import limiter
from api.src.tenant.crud import authenticate_tenant
from api.src.tenant.crud import create_tenant as create_tenant_record
from api.src.tenant.crud import deactivate_tenant, rotate_tenant_api_key, update_tenant
from api.src.tenant.models import Tenant
from api.src.tenant.schemas import TenantCreate, TenantLoginRequest, TenantResponse, TenantUpdate


router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


def _to_tenant_response(tenant: Tenant, *, api_key: str | None = None) -> TenantResponse:
    """Map a tenant ORM model to an API-safe response payload."""
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        api_key=api_key,
        webhook_url=tenant.webhook_url,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TenantResponse)
async def create_tenant(
    tenant: TenantCreate,
    db: AsyncSession = Depends(get_session),
) -> TenantResponse:
    """Create a new tenant and return credentials including initial API key."""
    try:
        new_tenant, raw_api_key = await create_tenant_record(db, tenant_in=tenant)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _to_tenant_response(new_tenant, api_key=raw_api_key)


@router.post("/login", response_model=TenantResponse)
@limiter.limit("5/minute")
async def login_tenant(
    request: Request,
    login_in: TenantLoginRequest,
    db: AsyncSession = Depends(get_session),
) -> TenantResponse:
    """Authenticate tenant credentials and rotate API key on successful login."""
    _ = request
    tenant = await authenticate_tenant(
        db,
        tenant_name=login_in.name,
        raw_password=login_in.password,
    )
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid tenant credentials",
        )

    tenant, raw_api_key = await rotate_tenant_api_key(db, tenant=tenant)
    return _to_tenant_response(tenant, api_key=raw_api_key)


@router.get("/me", response_model=TenantResponse)
async def get_tenant_me(
    current_tenant: Tenant = Depends(get_current_tenant),
) -> TenantResponse:
    """Return the currently authenticated tenant profile."""
    return _to_tenant_response(current_tenant)


@router.patch("/me", response_model=TenantResponse)
async def patch_tenant_me(
    tenant_update: TenantUpdate,
    db: AsyncSession = Depends(get_session),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> TenantResponse:
    """Update mutable fields for the currently authenticated tenant."""
    updated = await update_tenant(
        db,
        tenant=current_tenant,
        tenant_data=tenant_update.model_dump(exclude_unset=True),
    )
    return _to_tenant_response(updated)


@router.delete("/me")
async def deactivate_tenant_me(
    db: AsyncSession = Depends(get_session),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> dict[str, str]:
    """Deactivate the current tenant account."""
    deactivated = await deactivate_tenant(db, tenant=current_tenant)
    return {"tenant_id": str(deactivated.id), "status": "deactivated"}