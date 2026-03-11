"""Authentication dependencies for protected API endpoints."""

import logging
import uuid
from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.src.config_package.settings import get_settings
from api.src.database.postgres_client import get_session
from api.src.users.models import User, UserStatus

_cfg = get_settings()
SECRET_KEY = _cfg.SECRET_KEY
ALGORITHM = _cfg.ALGORITHM

security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_session)
) -> User:
    """
    Validate access token with comprehensive database checks.

    Checks performed:
    1. Token structure and signature
    2. Token expiration
    3. User exists
    4. Session version (detects password change/logout all)
    5. Password change timestamp (additional safety)
    6. Account status (active, suspended, deactivated)
    """

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Decode token
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])

        user_id = payload.get("sub")
        token_type = payload.get("type")
        issued_at = payload.get("iat")
        session_version: int = payload.get("session_version", 0)

        if not user_id or token_type != "access":
            raise credentials_exception

        if not isinstance(issued_at, int):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing 'iat' claim",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError as exc:
            raise credentials_exception from exc

    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    except jwt.PyJWTError as exc:
        raise credentials_exception from exc

    # Fetch user from database
    smt = select(User).where(User.id == user_uuid)
    result = await session.execute(smt)
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception

    # Check session version
    if user.session_version != session_version:
        logger.info("Session invalidated for user %s: session version mismatch.", user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check password change timestamp
    token_issued_at = datetime.fromtimestamp(issued_at, tz=timezone.utc)
    if user.password_changed_at and token_issued_at < user.password_changed_at:
        logger.info("Token issued before password change for user %s.", user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalid due to password change. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check account status
    if user.status == UserStatus.SUSPENDED:
        logger.info("Suspended account access attempt for user %s.", user_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended. Contact support.",
        )

    if user.status == UserStatus.DEACTIVATED:
        logger.info("Deactivated account access attempt for user %s.", user.email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )

    # if user is not active
    if user.status != UserStatus.ACTIVE:
        logger.info("Inactive account access attempt for user %s.", user_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive.",
        )

    # All checks passed
    return user

# check if the current user is active
async def get_current_active_user(
    current_user: User = Depends(get_current_user)
    ) -> User:
    """Return the authenticated user only if the account is active."""
    if current_user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user.",
        )
    return current_user