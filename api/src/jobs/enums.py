"""Enumerations for job processing state transitions."""

import enum

class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    QUEUED_AI_OUTAGE = "QUEUED_AI_OUTAGE"
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    DEAD = "DEAD"