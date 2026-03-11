"""Async Redis client configuration for caching and queue-adjacent features."""

import redis.asyncio as redis
from api.src.config_package import settings

cfg = settings.get_settings()

# Connect to our new Redis Stack container
redis_db = redis.from_url(cfg.redis_url, decode_responses=True)