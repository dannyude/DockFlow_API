import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context as alembic_context

# 1. ADD YOUR PROJECT ROOT TO PYTHON'S PATH
# This allows Alembic to see your 'api' folder
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# 2. IMPORT YOUR SETTINGS AND MODELS
from api.src.config_package.settings import get_settings
from api.src.database.postgres_client import Base
from api.src.tenant import models as tenant_models
from api.src.jobs import models as job_models
from api.src.auth import models as auth_models
from api.src.users import models as user_models

settings = get_settings()

config = getattr(alembic_context, "config")
configure = getattr(alembic_context, "configure")
begin_transaction = getattr(alembic_context, "begin_transaction")
run_migrations = getattr(alembic_context, "run_migrations")
is_offline_mode = getattr(alembic_context, "is_offline_mode")

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 3. INJECT YOUR DATABASE URL DYNAMICALLY
# We strip out +asyncpg because Alembic needs a synchronous connection
sync_db_url = settings.database_url.replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", sync_db_url)

# 4. POINT ALEMBIC TO YOUR METADATA
target_metadata = Base.metadata
_ = (tenant_models, job_models, auth_models, user_models)

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with begin_transaction():
        run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        configure(
            connection=connection, target_metadata=target_metadata
        )

        with begin_transaction():
            run_migrations()

if is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()