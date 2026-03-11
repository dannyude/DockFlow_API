import asyncio
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.testclient import TestClient

from api.src.tenant.routes import tenants as tenants_router
from api.src.tenant.schemas import TenantLoginRequest


def _fake_request() -> Any:
    """Minimal request-like object that satisfies slowapi."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/tenants/login",
        "headers": [],
        "query_string": b"",
    }
    from starlette.requests import Request
    return Request(scope)


def test_login_tenant_returns_api_key_on_success(monkeypatch):
    tenant = SimpleNamespace(
        id=uuid4(),
        name="acme",
        webhook_url="https://example.test/webhook",
        is_active=True,
        created_at="2026-03-09T00:00:00Z",
    )

    async def fake_authenticate_tenant(_db, **kwargs):
        if kwargs.get("tenant_name") == "acme" and kwargs.get("raw_password") == "SuperSecret123!":
            return tenant
        return None

    async def fake_rotate_tenant_api_key(_db, *, tenant):
        return tenant, "docflow_live_test_key"

    monkeypatch.setattr(tenants_router, "authenticate_tenant", fake_authenticate_tenant)
    monkeypatch.setattr(tenants_router, "rotate_tenant_api_key", fake_rotate_tenant_api_key)

    result = asyncio.run(
        tenants_router.login_tenant(
            request=_fake_request(),
            login_in=TenantLoginRequest(name="acme", password="SuperSecret123!"),
            db=cast(Any, object()),
        )
    )

    assert result.name == "acme"
    assert result.api_key == "docflow_live_test_key"


def test_login_tenant_rejects_invalid_credentials(monkeypatch):
    async def fake_authenticate_tenant(_db, **kwargs):
        _ = kwargs
        return None

    monkeypatch.setattr(tenants_router, "authenticate_tenant", fake_authenticate_tenant)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            tenants_router.login_tenant(
                request=_fake_request(),
                login_in=TenantLoginRequest(name="acme", password="Wrongpass123!"),
                db=cast(Any, object()),
            )
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid tenant credentials"


def test_login_request_rejects_invalid_company_username():
    with pytest.raises(ValidationError):
        TenantLoginRequest(name="-acme", password="ValidPass123!")


def test_login_request_rejects_weak_password():
    with pytest.raises(ValidationError):
        TenantLoginRequest(name="acme", password="alllowercase123")


def test_login_request_rejects_common_password():
    with pytest.raises(ValidationError, match="too common"):
        TenantLoginRequest(name="acme", password="Password1!")


def test_login_request_rejects_password_containing_username():
    with pytest.raises(ValidationError, match="must not contain the company username"):
        TenantLoginRequest(name="acme", password="MyAcme123!")
