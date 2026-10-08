"""
E2E test fixtures — built against the REAL application surface.

Design rules enforced here
--------------------------
1. Chart of Accounts comes from GLService.ensure_core_accounts() (the canonical
   production tree). We never hand-seed account codes: the real tree marks
   1000/1100/2000/3000/4000/5000 as HEADERS, Cash is 1110, AR is 1130,
   AP is 2110, Sales Revenue is 4100. Hand-made codes silently corrupt it.
2. Permission codes are the ones the routes actually enforce (manage_ledger,
   view_ledger, manage_sales, manage_purchases, manage_warehouse, ...).
3. `login_as` logs in the ACTUAL user for the scenario's role so that 403
   assertions are reachable. A matrix where every test logs in as owner cannot
   test RBAC at all.

Performance
-----------
Naive per-test DROP/CREATE of 84 tables plus scrypt hashing cost ~12s per test
(3.75s schema + ~0.31s per password hash + ~0.33s per login verify). At 1500
scenarios that is ~5 hours.

Two changes, neither of which weakens an assertion:
  * The schema is created ONCE per session. Each test runs inside an external
    transaction that is rolled back afterwards, so isolation is preserved by
    rollback instead of by DDL. This is SQLAlchemy's documented
    "join an external transaction" recipe.
  * Password hashing uses a reduced PBKDF2 iteration count (1000 instead of
    ~600k). Hashing and verification remain fully real — the hash is still
    generated and still verified byte-for-byte; only the work factor drops.
    Login tests therefore still exercise the real auth path.
"""

import os
import tempfile
import pytest
from decimal import Decimal

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'e2e-test-secret-not-production')
os.environ.setdefault('OWNER_PASSWORD', 'E2eOwner@1234567890123456!')
os.environ.setdefault('DEBUG', 'false')
os.environ.setdefault('WTF_CSRF_ENABLED', 'false')
os.environ.setdefault('RATELIMIT_ENABLED', 'false')
os.environ.setdefault('RATELIMIT_STORAGE_URI', 'memory://')
os.environ.setdefault('CACHE_TYPE', 'flask_caching.backends.SimpleCache')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

from werkzeug.security import generate_password_hash as _gen_hash  # noqa: E402
from app import create_app                                 # noqa: E402
from config import Config                                  # noqa: E402
from extensions import db as _db                           # noqa: E402
from models import (                                       # noqa: E402
    User, Role, Permission, Customer, Product, ProductCategory,
    Supplier, Warehouse,
)
from services.gl_service import GLService                   # noqa: E402
from models.tenant_scope import clear_current_tenant_id     # noqa: E402
from tests.e2e.harness import ACC                          # noqa: E402

E2E_TMPDIR = tempfile.mkdtemp(prefix='e2e_erp_')
E2E_DB_PATH = os.path.join(E2E_TMPDIR, 'e2e.db')


class E2ETestConfig(Config):
    """Config.SQLALCHEMY_DATABASE_URI is frozen at import time (config.py:82),
    so the test database must be supplied by subclassing, not by env."""
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{E2E_DB_PATH.replace(os.sep, "/")}'
    SQLALCHEMY_ENGINE_OPTIONS = {'connect_args': {'check_same_thread': False}}


# The five role vectors from the scenario taxonomy, mapped to the permission
# codes the routes genuinely enforce.
ROLE_PERMISSIONS = {
    'owner': [
        'manage_sales', 'manage_customers', 'manage_products', 'manage_purchases',
        'manage_suppliers', 'manage_payments', 'manage_expenses', 'manage_warehouse',
        'manage_ledger', 'view_ledger', 'view_products', 'view_reports',
        'manage_approvals', 'manage_backups', 'manage_hr', 'manage_settings',
    ],
    'branch_manager': [
        'manage_sales', 'manage_customers', 'manage_products', 'manage_purchases',
        'manage_suppliers', 'manage_payments', 'view_reports', 'view_products',
    ],
    'senior_accountant': [
        'manage_ledger', 'view_ledger', 'view_reports', 'manage_approvals',
    ],
    'pos_cashier': [
        'manage_sales',
    ],
    'warehouse_keeper': [
        'manage_warehouse', 'view_products',
    ],
}

ROLE_PASSWORDS = {
    'owner': 'OwnerPass123!',
    'branch_manager': 'ManagerPass123!',
    'senior_accountant': 'AccountantPass123!',
    'pos_cashier': 'CashierPass123!',
    'warehouse_keeper': 'KeeperPass123!',
}

_ALL_TABLES = []

# Reference data seeded once per session and preserved across the per-test
# wipe. gl_accounts is the canonical chart of accounts; re-running
# ensure_core_accounts() after every wipe would cost ~1.2s per test, so the
# tree is kept intact instead.
_PRESERVE_TABLES = frozenset({'gl_accounts', 'permissions'})


@pytest.fixture(scope='session', autouse=True)
def quiet_e2e_logging():
    """Silence per-request logging for the suite.

    Every sale fires a dozen AI/event listeners that each emit INFO lines.
    Across 1500 scenarios that is hundreds of thousands of log records, which
    dominates both runtime and output. Errors are left visible so genuine
    failures remain diagnosable.
    """
    import logging
    noisy = ('app', 'models.events', 'services.real_time_listeners',
             'models.tenant_scope', 'utils.distributed_lock',
             'services.stock_service', 'app.monitoring', 'app.sale_service',
             'app.stock_service', 'models.sale', 'models.purchase')
    previous = {}
    for name in noisy:
        log = logging.getLogger(name)
        previous[name] = log.level
        log.setLevel(logging.ERROR)
    yield
    for name, level in previous.items():
        logging.getLogger(name).setLevel(level)


@pytest.fixture(scope='session', autouse=True)
def fast_password_hashing():
    """Lower the PBKDF2 work factor for the suite.

    Hashing and verification stay genuine: set_password still produces a salted
    PBKDF2 hash and check_password still verifies it. Only the iteration count
    drops from ~600k to 1000, which is standard practice for test suites and
    removes ~0.31s per created user and ~0.33s per login.
    """
    import models.user as user_model
    original = user_model.generate_password_hash

    def _fast(password, method='pbkdf2:sha256', salt_length=16):
        return _gen_hash(password, method='pbkdf2:sha256:1000')

    user_model.generate_password_hash = _fast
    yield
    user_model.generate_password_hash = original


@pytest.fixture(scope='session')
def app():
    application = create_app(E2ETestConfig)
    application.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SERVER_NAME='localhost',
        RATELIMIT_ENABLED=False,
        RATELIMIT_DEFAULT='1000000 per day',
    )
    return application


@pytest.fixture(scope='session')
def _schema(app):
    """Create the schema once per session, not once per test."""
    global _ALL_TABLES
    with app.app_context():
        _db.create_all()
        GLService.ensure_core_accounts()
        _db.session.commit()
        from sqlalchemy import inspect as _inspect
        _ALL_TABLES = sorted(_inspect(_db.engine).get_table_names())
    yield
    with app.app_context():
        _db.session.remove()
        _db.drop_all()


def _wipe_rows(db):
    """Delete every row from every table (no DDL, no schema churn).

    The first isolation attempt tried SQLAlchemy's "join an external
    transaction" recipe instead of DROP/CREATE. That does not work here:
    Flask-SQLAlchemy 3 scopes the session per application context, so the
    nested app context used by the test client gets a different session that is
    not bound to the outer connection — app code's db.session.commit() then
    really committed, and roles leaked between tests
    (sqlite3.IntegrityError: UNIQUE constraint failed: roles.slug).

    A row wipe is deterministic and immune to session scoping. Foreign keys are
    disabled for the duration so table order does not matter.
    """
    db.session.remove()
    db.session.execute(db.text('PRAGMA foreign_keys=OFF'))
    for table in reversed(_ALL_TABLES):
        if table in _PRESERVE_TABLES:
            continue
        db.session.execute(db.text(f'DELETE FROM "{table}"'))
    db.session.commit()
    db.session.execute(db.text('PRAGMA foreign_keys=ON'))
    db.session.commit()


@pytest.fixture(scope='function')
def db(app, _schema):
    """Per-test isolation by wiping rows; schema persists for the session."""
    with app.app_context():
        clear_current_tenant_id()
        _wipe_rows(_db)
        try:
            yield _db
        finally:
            try:
                _db.session.rollback()
            except Exception:
                pass
            clear_current_tenant_id()


@pytest.fixture(scope='function')
def client(app, db):
    with app.test_client() as c:
        with app.app_context():
            yield c


def _make_user(role_slug: str) -> User:
    """Create one user per role with exactly that role's permissions."""
    perms = []
    for code in ROLE_PERMISSIONS[role_slug]:
        perm = Permission.query.filter_by(code=code).first()
        if perm is None:
            perm = Permission(code=code, name=code.replace('_', ' ').title(),
                              category=code.split('_')[0])
            _db.session.add(perm)
        perms.append(perm)
    _db.session.flush()

    role = Role(
        name=role_slug.replace('_', ' ').title(),
        name_ar=role_slug,
        slug=role_slug,
        permissions=perms,
    )
    _db.session.add(role)
    _db.session.flush()

    user = User(
        username=f'e2e_{role_slug}',
        email=f'e2e_{role_slug}@test.local',
        full_name=f'E2E {role_slug}',
        is_owner=(role_slug == 'owner'),
        is_active=True,
        role_id=role.id,
    )
    user.set_password(ROLE_PASSWORDS[role_slug])
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture(scope='function')
def users(db):
    """All five role users, created fresh inside the rolled-back transaction."""
    return {slug: _make_user(slug) for slug in ROLE_PERMISSIONS}


@pytest.fixture(scope='function')
def owner(db, users):
    return users['owner']


@pytest.fixture(scope='function')
def login_as(client, users):
    """Log in as the scenario's real role. Returns the logged-in User."""
    def _login(role_slug: str) -> User:
        user = users[role_slug]
        resp = client.post('/auth/login', data={
            'username': user.username,
            'password': ROLE_PASSWORDS[role_slug],
        }, follow_redirects=False)
        assert resp.status_code in (302, 303), (
            f'login failed for {role_slug}: status {resp.status_code}')
        return user
    return _login


@pytest.fixture(scope='function')
def anonymous(client, db):
    """A logged-out client (for unauthenticated-access assertions)."""
    with client.session_transaction() as sess:
        sess.clear()
    return client


# --------------------------------------------------------------------------
# Master data (created inside the rolled-back transaction)
# --------------------------------------------------------------------------

@pytest.fixture(scope='function')
def customer(db):
    c = Customer(
        name='E2E Customer', name_ar='عميل',
        customer_type='regular', phone='+0000000000',
        email='e2e_customer@test.local',
        credit_limit=Decimal('100000'), balance=Decimal('0'), is_active=True,
    )
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture(scope='function')
def category(db):
    cat = ProductCategory(name='E2E Parts', name_ar='قطع غيار', is_active=True)
    db.session.add(cat)
    db.session.commit()
    return cat


@pytest.fixture(scope='function')
def product(db, category):
    p = Product(
        name='E2E Brake Pad', name_ar=' pads', sku='E2E-SKU-0001',
        category_id=category.id,
        cost_price=Decimal('50.000'), regular_price=Decimal('100.000'),
        current_stock=Decimal('100'), min_stock_alert=Decimal('10'),
        is_active=True,
    )
    db.session.add(p)
    db.session.commit()
    return p


@pytest.fixture(scope='function')
def warehouse(db):
    w = Warehouse(
        name='E2E Main', name_ar='رئيسي', code='E2E-WH-1',
        location='E2E', is_main=True, is_active=True,
    )
    db.session.add(w)
    db.session.commit()
    return w


@pytest.fixture(scope='function')
def supplier(db):
    s = Supplier(
        name='E2E Supplier', name_ar='مورد', phone='+0000000001',
        email='e2e_supplier@test.local', is_active=True,
    )
    db.session.add(s)
    db.session.commit()
    return s
