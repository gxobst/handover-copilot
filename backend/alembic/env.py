import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import get_settings
from app.db.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata


def get_url() -> str:
    """Dynamically resolve database URL from env, alembic config, or app settings."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        ini_url = config.get_main_option("sqlalchemy.url")
        if ini_url and ini_url != "sqlite:///./handover.db":
            url = ini_url
        else:
            url = get_settings().database_url
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section, {}) or {}
    configuration["sqlalchemy.url"] = get_url()

    connect_args = {}
    if configuration["sqlalchemy.url"].startswith("sqlite"):
        connect_args["check_same_thread"] = False
        db_file = configuration["sqlalchemy.url"].removeprefix("sqlite:///").split("?")[0]
        if db_file and not db_file.startswith(":memory:"):
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
