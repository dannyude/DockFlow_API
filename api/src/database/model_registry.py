"""Utilities to force-import ORM models for metadata registration."""

from importlib import import_module


def import_models() -> None:
    """Import all ORM modules so SQLAlchemy metadata includes every table."""
    import_module("api.src.jobs.models")
    import_module("api.src.tenant.models")
    import_module("api.src.users.models")
    import_module("api.src.auth.models")
