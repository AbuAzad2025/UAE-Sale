from alembic import context
from sqlalchemy import engine_from_config, pool
from logging.config import fileConfig
import logging
import sys
import os

config = context.config
fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')

# IMPORTANT: Import models FIRST to register them with db.metadata
# This must happen before accessing db.metadata
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    import models  # This registers all models with db.metadata
    from extensions import db
    target_metadata = db.metadata
except Exception as e:
    logger.warning(f"Could not load models: {e}")
    target_metadata = None

# Try to get metadata from Flask app context (for Flask-Migrate) as fallback
if target_metadata is None:
    try:
        from flask import current_app
        if current_app:
            target_metadata = current_app.extensions['migrate'].db.metadata
    except (RuntimeError, ImportError, KeyError):
        pass

def get_engine_url():
    """Get database URL from config, with fallbacks."""
    section = config.get_section(config.config_ini_section)
    if section and 'sqlalchemy.url' in section:
        return section['sqlalchemy.url']
    url = config.get_main_option('sqlalchemy.url')
    if url:
        return url
    return os.environ.get('DATABASE_URL', 'postgresql+psycopg2://postgres:123@localhost:5432/uae_sale')

def run_migrations_offline():
    url = get_engine_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    url = get_engine_url()
    connectable = engine_from_config(
        {'sqlalchemy.url': url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()