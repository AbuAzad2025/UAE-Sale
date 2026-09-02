"""First-run setup script for UAE-Sale.

1. Applies Alembic migrations (schema).
2. Calls :func:`utils.system_init.ensure_system_integrity`, which creates the
   minimal owner user, roles and permissions required for the first login.

Everything else (GL chart of accounts, currencies, warehouses, categories,
customers, products) is created by the owner through the web UI after login.
SystemSettings and the default Tenant auto-create on first access
(``SystemSettings.get_current()`` / ``Tenant.get_current()``).

Usage::

    python init_dev.py
"""
import os
import sys

os.environ['FLASK_ENV'] = 'development'
os.environ['DEBUG'] = '1'
# create_app() runs ensure_system_integrity automatically; keep that
# no-op here (testing) and call it explicitly AFTER migrations below.
os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'dev-test-secret-key-2026')
os.environ.setdefault('CARD_ENCRYPTION_KEY', 'card-encryption-key-2026')
os.environ.setdefault('OWNER_PASSWORD', 'TestOwner@1983@yyyy!')
os.environ.setdefault('OWNER_USERNAME', 'owner')
os.environ.setdefault('DATABASE_URL', 'postgresql://postgres:123@localhost:5432/uae_sale_dev')
os.environ.setdefault('SQLALCHEMY_DATABASE_URI', os.environ['DATABASE_URL'])
os.environ.setdefault('MASTER_KEY_SEED', 'Azad@1983')
os.environ.setdefault('CACHE_TYPE', 'SimpleCache')
os.environ.setdefault('RATELIMIT_STORAGE_URI', 'memory://')
os.environ.setdefault('RATELIMIT_ENABLED', 'false')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _run_migrations(app):
    """Apply Alembic migrations to head (needs an app context)."""
    from alembic.config import Config
    from alembic import command

    cfg = Config(os.path.join(os.path.dirname(__file__), 'migrations', 'alembic.ini'))
    cfg.set_main_option('script_location', 'migrations')
    cfg.set_main_option('sqlalchemy.url', os.environ['SQLALCHEMY_DATABASE_URI'])

    with app.app_context():
        command.upgrade(cfg, 'head')
        print('[migrations] Schema is at head')

    # migrations/env.py sets ALEMBIC_RUNNING=1 in this same process, which
    # makes ensure_system_integrity() bail out. Clear it before seeding.
    os.environ.pop('ALEMBIC_RUNNING', None)


def _seed_minimal_runtime(app):
    """Seed the owner user, roles and permissions (idempotent)."""
    from utils.system_init import ensure_system_integrity

    # FORCE is set only now, after create_app() fired (so the automatic
    # call during boot was a no-op against the empty schema).
    os.environ['SYSTEM_INTEGRITY_FORCE'] = '1'
    with app.app_context():
        ensure_system_integrity(app)
    os.environ.pop('SYSTEM_INTEGRITY_FORCE', None)
    print('[integrity] Owner / roles / permissions seeded')


def main():
    print('=' * 60)
    print('  UAE-Sale ERP - First-Run Initialization')
    print('=' * 60)

    print('[1/3] Booting application...')
    from app import create_app  # noqa: E402  (must be after env setup)
    app = create_app()

    print('[2/3] Applying migrations...')
    _run_migrations(app)

    print('[3/3] Seeding minimal runtime data...')
    _seed_minimal_runtime(app)

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
        print(f"    Password:  set via OWNER_PASSWORD env var")
        print()
        print('  Next steps (via web UI after login):')
        print('    1. Owner panel -> Chart of Accounts')
        print('    2. Owner panel -> Currencies')
        print('    3. Owner panel -> Warehouses')
        print('    4. Settings   -> Product / Expense Categories')
        print()
        print('=' * 60)
        print('  Done.  Start the server:  python app.py')
        print('=' * 60)


if __name__ == '__main__':
    main()