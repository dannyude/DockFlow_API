"""Pydantic schemas for job submission and job status API responses."""

from typing import Any, Union

from pydantic import BaseModel, field_validator


class JobCreate(BaseModel):
    extraction_schema: Union[dict[str, Any], list[Any], str]
    webhook_url: str | None = None

    @field_validator("extraction_schema")
    @classmethod
    def schema_must_not_be_empty(cls, value: Union[dict[str, Any], list[Any], str]) -> Union[dict[str, Any], list[Any], str]:
        if isinstance(value, str) and not value.strip():
            raise ValueError("extraction_schema must not be empty")
        if isinstance(value, (dict, list)) and len(value) == 0:
            raise ValueError("extraction_schema must not be empty")
        return value


class JobResponse(BaseModel):
    job_id: str
    correlation_id: str
    status: str
    message: str = "Job accepted and queued for processing"


class JobStatusResponse(BaseModel):
    job_id: str
    correlation_id: str
    status: str
    progress_message: str | None = None
    result: dict | None = None
    error: str | None = None
    created_at: str
    completed_at: str | None = None
