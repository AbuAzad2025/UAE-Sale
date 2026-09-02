"""First-run setup script for UAE-Sale.

Applies Alembic migrations then lets ``ensure_system_integrity``
create the minimal owner/permissions/roles required for the first
login.  Everything else (GL accounts, currencies, warehouse, categories)
must be configured by the owner via the web UI after logging in.

Usage::

    python init_dev.py
"""
import os
import sys
from datetime import datetime

os.environ['FLASK_ENV'] = 'development'
os.environ['DEBUG'] = '1'
os.environ.setdefault('SECRET_KEY', 'dev-test-secret-key-2026')
os.environ.setdefault('CARD_ENCRYPTION_KEY', 'card-encryption-key-2026')
os.environ.setdefault('OWNER_PASSWORD', 'TestOwner@1983@yyyy!')
os.environ.setdefault('OWNER_USERNAME', 'owner')
os.environ.setdefault('DATABASE_URL', 'postgresql://postgres:123@localhost:5432/uae_sale_dev')
os.environ.setdefault('SQLALCHEMY_DATABASE_URI', os.environ.get('DATABASE_URL', ''))
os.environ.setdefault('MASTER_KEY_SEED', 'Azad@1983')
os.environ.setdefault('CACHE_TYPE', 'SimpleCache')
os.environ.setdefault('RATELIMIT_STORAGE_URI', 'memory://')
os.environ.setdefault('RATELIMIT_ENABLED', 'false')
os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SYSTEM_INTEGRITY_FORCE', '1')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _run_migrations():
    """Apply Alembic migrations to head."""
    from alembic.config import Config
    from alembic import command

    cfg = Config(os.path.join(os.path.dirname(__file__), 'migrations', 'alembic.ini'))
    cfg.set_main_option('script_location', 'migrations')
    cfg.set_main_option('sqlalchemy.url', os.environ['SQLALCHEMY_DATABASE_URI'])

    command.upgrade(cfg, 'head')
    print('[migrations] Schema is at head')


def main():
    print('=' * 60)
    print('  UAE-Sale ERP - First-Run Initialization')
    print('=' * 60)

    print('[1/2] Applying migrations...')
    _run_migrations()

    print('[2/2] Booting application (seeds owner/permissions automatically)...')
    from app import create_app  # noqa: E402  (must be after env setup)
    app = create_app()

    with app.app_context():
        from models import User, Role, Permission, SystemSettings, Tenant
        print()
        print('--- Minimal first-run seeds complete ---')
        print(f"  Users:       {User.query.count()}")
        print(f"  Roles:       {Role.query.count()}")
        print(f"  Permissions: {Permission.query.count()}")
        print(f"  Tenants:     {Tenant.query.count()}")
        print(f"  Settings:    {SystemSettings.query.count()}")
        print()
        print('  Owner login:')
        print(f"    Username:  {os.environ.get('OWNER_USERNAME', 'owner')}")
        print(f"    Password:  {'*' * len(os.environ.get('OWNER_PASSWORD', ''))}")
        print()
        print('  Next steps (via web UI after login):')
        print('    1. Owner panel → Chart of Accounts')
        print('    2. Owner panel → Currencies')
        print('    3. Owner panel → Warehouses')
        print('    4. Settings   → Product / Expense Categories')
        print()
        print('=' * 60)
        print('  Done.  Start the server:  python app.py')
        print('=' * 60)


if __name__ == '__main__':
    main()
