"""Tenant data-access operations for lifecycle and credential management."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.src.tenant.models import Tenant
from api.src.tenant.schemas import TenantCreate
from api.src.auth.security import hash_api_key as _hash_api_key
from api.src.auth.security import verify_password as _verify_password
from api.src.auth.security import hash_password as _hash_password
from api.src.auth.security import generate_raw_api_key as _generate_raw_api_key



async def create_tenant(db: AsyncSession, *, tenant_in: TenantCreate) -> tuple[Tenant, str]:
    """Create a tenant, hash credentials, and return the raw API key once."""
    existing = await db.execute(select(Tenant).where(Tenant.name == tenant_in.name))
    if existing.scalar_one_or_none() is not None:
        raise ValueError("Tenant with this name already exists")

    raw_api_key = _generate_raw_api_key()
    hashed_api_key = _hash_api_key(raw_api_key)

    tenant = Tenant(
        name=tenant_in.name,
        api_key=hashed_api_key,
        login_password_hash=_hash_password(tenant_in.password),
        webhook_url=tenant_in.webhook_url,
        is_active=tenant_in.is_active,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    return tenant, raw_api_key


async def authenticate_tenant(
    db: AsyncSession,
    *,
    tenant_name: str,
    raw_password: str,
) -> Tenant | None:
    """Authenticate an active tenant by name and password."""
    result = await db.execute(
        select(Tenant).where(
            Tenant.name == tenant_name,
            Tenant.is_active.is_(True),
        )
    )
    tenant = result.scalar_one_or_none()

    if not tenant or not _verify_password(raw_password, tenant.login_password_hash):
        return None

    return tenant


async def rotate_tenant_api_key(db: AsyncSession, *, tenant: Tenant) -> tuple[Tenant, str]:
    """Rotate and persist a tenant API key, returning the new raw key."""
    raw_api_key = _generate_raw_api_key()
    tenant.api_key = _hash_api_key(raw_api_key)
    await db.commit()
    await db.refresh(tenant)
    return tenant, raw_api_key


async def update_tenant(
    db: AsyncSession,
    *,
    tenant: Tenant,
    tenant_data: dict[str, object],
) -> Tenant:
    """Apply tenant field updates with uniqueness validation for names."""
    update_data = tenant_data

    if "name" in update_data:
        existing = await db.execute(
            select(Tenant).where(Tenant.name == update_data["name"], Tenant.id != tenant.id)
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError("Tenant with this name already exists")

    for field_name, value in update_data.items():
        setattr(tenant, field_name, value)

    await db.commit()
    await db.refresh(tenant)
    return tenant




async def deactivate_tenant(db: AsyncSession, *, tenant: Tenant) -> Tenant:
    """Soft-deactivate a tenant by toggling `is_active` to `False`."""
    tenant.is_active = False
    await db.commit()
    await db.refresh(tenant)
    return tenant