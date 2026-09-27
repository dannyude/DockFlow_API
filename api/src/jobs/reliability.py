"""Reliability constants and time helpers for breaker/sweeper behavior."""

from datetime import datetime, timedelta, timezone

AI_BREAKER_FAILURE_KEY = "docflow:ai:breaker:consecutive_failures"
AI_BREAKER_OPEN_UNTIL_KEY = "docflow:ai:breaker:open_until"
AI_BREAKER_FAILURE_THRESHOLD = 5
AI_BREAKER_OPEN_SECONDS = 10 * 60

PENDING_SWEEP_MINUTES = 10
SWEEPER_INTERVAL_MINUTES = 5

# Maximum times the sweeper will re-enqueue a stuck job before declaring it
# DEAD. Prevents a poison job from being re-queued indefinitely every cycle.
MAX_ENQUEUE_ATTEMPTS = 5


def utcnow() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


def pending_cutoff() -> datetime:
    """Return the age cutoff used to identify stale queued jobs."""
    return utcnow() - timedelta(minutes=PENDING_SWEEP_MINUTES)
