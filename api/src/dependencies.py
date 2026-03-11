"""Shared FastAPI dependencies used across routers."""

import hashlib

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.src.database.postgres_client import get_session
from api.src.tenant.models import Tenant


async def get_current_tenant(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_session),
) -> Tenant:
    """Resolve and validate the tenant from the `X-API-Key` header."""
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    result = await db.execute(select(Tenant).where(Tenant.api_key == key_hash, Tenant.is_active.is_(True)))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
        )
    return tenant
