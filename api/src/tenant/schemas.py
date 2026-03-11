"""Pydantic schemas and validators for tenant registration and updates."""

from datetime import datetime
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

__all__ = ["TenantCreate", "TenantUpdate", "TenantLoginRequest", "TenantResponse"]


COMPANY_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9._-]{1,98}[a-zA-Z0-9])?$")

COMMON_PASSWORDS: frozenset[str] = frozenset(
    pw.lower()
    for pw in [
        "Password1!", "Welcome1!", "Changeme1!", "Admin123!", "Qwerty123!",
        "Letmein1!", "Passw0rd!", "Abc12345!", "Iloveyou1!", "Master123!",
        "P@ssw0rd", "P@ssword1", "Password123!", "Summer2024!", "Winter2024!",
    ]
)


def _validate_company_username(value: str) -> str:
    username = value.strip()
    if not COMPANY_USERNAME_PATTERN.fullmatch(username):
        raise ValueError(
            "Company username must be 3-100 chars, use letters/numbers/._-, and cannot start or end with punctuation"
        )
    return username


def _validate_password_strength(value: str) -> str:
    if not any(ch.isupper() for ch in value):
        raise ValueError("Password must include at least one uppercase letter")
    if not any(ch.islower() for ch in value):
        raise ValueError("Password must include at least one lowercase letter")
    if not any(ch.isdigit() for ch in value):
        raise ValueError("Password must include at least one number")
    if not any(not ch.isalnum() for ch in value):
        raise ValueError("Password must include at least one special character")
    if value.lower() in COMMON_PASSWORDS:
        raise ValueError("Password is too common — please choose a stronger one")
    return value


def _check_password_does_not_contain_username(name: str, password: str) -> None:
    if name.lower() in password.lower():
        raise ValueError("Password must not contain the company username")


class TenantCreate(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    webhook_url: str | None = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_company_username(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password_strength(value)

    @model_validator(mode="after")
    def password_must_not_contain_username(self) -> Self:
        _check_password_does_not_contain_username(self.name, self.password)
        return self


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=100)
    webhook_url: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_company_username(value)


class TenantLoginRequest(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_company_username(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password_strength(value)

    @model_validator(mode="after")
    def password_must_not_contain_username(self) -> Self:
        _check_password_does_not_contain_username(self.name, self.password)
        return self


class TenantResponse(BaseModel):
    id: UUID
    name: str
    api_key: str | None = None
    webhook_url: str | None = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
