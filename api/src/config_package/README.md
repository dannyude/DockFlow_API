# Config Package

Application configuration loaded from environment variables.

## Files

- `settings.py`: Pydantic settings model and cached loader (`get_settings`).
- `__init__.py`: Package marker and exports.

## Notes

- Centralizes runtime configuration for API, database, Redis/Celery, OpenAI, and object storage.
- Expected `.env` values are defined by the settings schema.
