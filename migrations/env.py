"""Alembic environment. Uses the app's SQLModel metadata and DATABASE_URL.

Run with ``alembic upgrade head`` / ``alembic revision --autogenerate``. The DB URL
comes from ``app.config`` so migrations always target the same database the app uses.
Batch mode is on so SQLite can ALTER TABLE (add columns, etc.) safely.
"""
from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Importing the models registers every table on SQLModel.metadata.
from app import config as app_config
from app import models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", app_config.DATABASE_URL)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=app_config.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
