"""Object-storage utilities for uploading/downloading job files."""

import uuid
import logging
from functools import lru_cache

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

from api.src.config_package.settings import get_settings

cfg = get_settings()
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client() -> BaseClient:
    """Return a cached S3-compatible client.

    boto3 clients are thread-safe, so a single reused client keeps its
    connection pool warm instead of rebuilding one on every call.
    """
    return boto3.client(
        "s3",
        endpoint_url=cfg.s3_endpoint_url,
        aws_access_key_id=cfg.s3_access_key_id,
        aws_secret_access_key=cfg.s3_secret_access_key,
        region_name=cfg.s3_region,
    )


def ensure_bucket_exists() -> bool:
    """Ensure the configured bucket exists; return False if endpoint is unavailable."""
    client = _client()
    try:
        existing_buckets = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
        if cfg.s3_bucket_name not in existing_buckets:
            client.create_bucket(Bucket=cfg.s3_bucket_name)
        return True
    except (EndpointConnectionError, ClientError, BotoCoreError) as exc:
        logger.warning(
            "Skipping S3 bucket initialization: endpoint '%s' is unavailable or misconfigured (%s)",
            cfg.s3_endpoint_url,
            exc,
        )
        return False


async def upload_to_s3(
    file_bytes: bytes,
    filename: str,
    tenant_id: str,
    *,
    correlation_id: str,
) -> str:
    """Upload file bytes and return the generated object key."""
    import asyncio

    s3 = _client()
    object_key = f"{tenant_id}/{correlation_id}/{uuid.uuid4()}-{filename}"

    await asyncio.to_thread(
        s3.put_object,
        Bucket=cfg.s3_bucket_name,
        Key=object_key,
        Body=file_bytes,
        Metadata={"correlation_id": correlation_id},
    )
    return object_key


def download_from_s3(file_s3_key: str) -> bytes:
    """Download and return raw bytes for a previously uploaded object key."""
    client = _client()
    response = client.get_object(Bucket=cfg.s3_bucket_name, Key=file_s3_key)
    return response["Body"].read()
