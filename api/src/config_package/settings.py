"""Centralized runtime settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Get the path to this file (.env location)
ENV_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".env"

class Settings(BaseSettings):
    """Application settings, loaded from .env file."""
    app_name: str = "DocFlow API"
    app_env: str = "development"
    app_version: str = "1.0.0"

    database_url: str


    # jwt settings
    SECRET_KEY: str
    ALGORITHM: str

    # OpenAI settings
    openai_api_key: str
    openai_model: str
    openai_base_url: str = "https://api.openai.com"

    # Celery/Redis settings
    redis_url: str
    celery_task_default_queue: str = "default"

    # S3 settings
    s3_endpoint_url: str | None = None
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_region: str
    s3_bucket_name: str


    # Config to specify the .env file location
    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

@lru_cache
def get_settings() -> Settings:
    """Return cached settings to avoid repeated environment parsing."""
    return Settings()  # pyright: ignore[reportCallIssue]