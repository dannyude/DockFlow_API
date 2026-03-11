"""Postgres engine/session setup shared by API routes and Celery workers."""

from typing import AsyncGenerator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from api.src.config_package import settings

# Get the DATABASE URL
cfg = settings.get_settings()
DATABASE_URL = cfg.database_url
if not DATABASE_URL:
    raise ValueError("DB_URL not set in .env or config")

# Create the async engine
_echo_sql = cfg.app_env == "development"
engine = create_async_engine(DATABASE_URL, echo=_echo_sql)

# Create the sync engine/session for Celery workers
SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")
sync_engine = create_engine(SYNC_DATABASE_URL, echo=_echo_sql)
SyncSessionLocal = sessionmaker(bind=sync_engine, autoflush=False, autocommit=False)

# Create the async session maker
async_session = async_sessionmaker(
    bind=engine,
    expire_on_commit=False
)

# Create the base class for all models
class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy ORM models."""

# Function to create database tables
async def create_db_and_tables() -> None:
    """Create all database tables from registered SQLAlchemy metadata."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
# Async dependency to get a session
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a transactional async DB session for FastAPI request handling."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise