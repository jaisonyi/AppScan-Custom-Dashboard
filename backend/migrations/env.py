from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config.settings import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_URL = f"sqlite:///{PROJECT_ROOT / 'data' / 'aspm.db'}"
_raw_db_url = settings.database_url or DEFAULT_DB_URL
# configparser (used internally by alembic) treats '%' as interpolation syntax.
# Escape every '%' as '%%' so configparser stores them as literal '%',
# which SQLAlchemy then correctly decodes (e.g. '%40' → '@').
config.set_main_option("sqlalchemy.url", _raw_db_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
