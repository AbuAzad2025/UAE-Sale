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
    Supplier, Warehouse, Tenant,
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
    # config.py:147 reads RATELIMIT_ENABLED from the environment *at import
    # time*, so the os.environ.setdefault above only works while this file is
    # the first thing to import config. Anything that imports config earlier --
    # a pytest plugin loaded with -p, a different conftest ordering, an IDE
    # runner -- leaves it True, flask-limiter turns itself on during
    # limiter.init_app(), and auth.login starts returning 429 roughly 75
    # scenarios into the run. That failure looks like cross-test pollution
    # because it depends on how many tests ran before it.
    #
    # Declaring it here pins it before create_app() runs, so the limiter is off
    # regardless of import order. Updating app.config afterwards does not help:
    # flask-limiter caches the flag when the extension is initialised.
    RATELIMIT_ENABLED = False


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
    # The three role vectors below are taken verbatim from the application's
    # own definitions in tests/unit/test_erp_role_isolation.py so the E2E
    # matrix and the unit suite agree on what each role may do.
    #   manager   -> "broader permissions but NOT manage_ledger or admin"
    #   accountant-> "ledger + expenses + reports, but NOT sales or POS"
    #   viewer    -> "view_reports ONLY - no write access anywhere"
    'manager': [
        'manage_sales', 'manage_customers', 'manage_products', 'manage_purchases',
        'manage_payments', 'view_reports', 'manage_expenses', 'manage_warehouse',
        'view_costs',
        # utils/system_init.py gives 'manager' manage_users, which is the only
        # seeded role besides owner that can reach /users/create and
        # /users/<id>/delete.
        'manage_users',
    ],
    'accountant': [
        'view_ledger', 'manage_ledger', 'manage_expenses', 'view_reports',
        'manage_payments',
    ],
    'viewer': [
        'view_reports',
    ],
    # utils/system_init.py:228 defines the 'hr' role with manage_hr as its only
    # permission, which is the sole gate on all 21 /hr/* routes.
    'hr': [
        'manage_hr',
    ],
}

ROLE_PASSWORDS = {
    'owner': 'OwnerPass123!',
    'branch_manager': 'ManagerPass123!',
    'senior_accountant': 'AccountantPass123!',
    'pos_cashier': 'CashierPass123!',
    'warehouse_keeper': 'KeeperPass123!',
    'manager': 'RoleManager123!',
    'accountant': 'RoleAccountant123!',
    'viewer': 'RoleViewer123!',
    'hr': 'RoleHrOfficer123!',
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


def pytest_addoption(parser):
    """Exact, composable sharding for the matrix.

    pytest-shard was tried first and rejected: it does not compose with -k
    (shard 0 reported 3368 and shard 1 reported 3352 of an 840-test domain,
    i.e. they overlapped and double counted). Sharding here runs against the
    already-filtered item list, so `-k E2E-CHE- --e2e-shard-id 0/1` splits
    that domain exactly in half with no overlap.
    """
    group = parser.getgroup('e2e')
    group.addoption('--e2e-shard-id', type=int, default=0,
                    help='zero-based shard index')
    group.addoption('--e2e-num-shards', type=int, default=1,
                    help='total number of shards')
    group.addoption('--e2e-route-report', default=None,
                    help='write the set of URL rules this session actually '
                         'exercised to this JSON path')


def pytest_configure(config):
    target = config.getoption('--e2e-route-report', default=None)
    if target:
        os.environ['_E2E_ROUTE_REPORT_TARGET'] = target


_HIT_RULES = set()


@pytest.fixture(scope='session', autouse=True)
def route_recorder(app):
    """Record every URL rule the suite really exercises.

    Scenario count and endpoint coverage are different things. The matrix runs
    24570 scenarios, but each domain runner cycles a handful of paths, so the
    suite was passing 24640 assertions while touching roughly a fifth of the
    application's routes. Nothing in the run summary showed that, so the gap
    was invisible.

    Recording at the Flask layer (not by grepping the test source) means the
    number comes from requests that were really issued, and a route only
    counts as covered if it was reached.
    """
    from flask import request

    @app.before_request
    def _record():
        if request.url_rule is not None:
            _HIT_RULES.add(request.url_rule.rule)

    yield _HIT_RULES

    target = app.config.get('_E2E_ROUTE_REPORT')
    if target:
        import json
        with open(target, 'w', encoding='utf-8') as fh:
            json.dump(sorted(_HIT_RULES), fh, indent=1)


def pytest_collection_modifyitems(config, items):
    total = config.getoption('--e2e-num-shards', default=1) or 1
    if total <= 1:
        return
    shard_id = config.getoption('--e2e-shard-id', default=0)
    if shard_id >= total:
        raise pytest.UsageError(
            f'--e2e-shard-id {shard_id} is out of range for '
            f'--e2e-num-shards {total}')
    kept = [it for idx, it in enumerate(items) if idx % total == shard_id]
    dropped = [it for idx, it in enumerate(items) if idx % total != shard_id]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept


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
    route_report = os.environ.get('_E2E_ROUTE_REPORT_TARGET')
    if route_report:
        application.config['_E2E_ROUTE_REPORT'] = route_report
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
        # The wipe removes the fiscal period too, and a posting is refused
        # unless it lands inside an OPEN one - so re-open the current year,
        # exactly as the application factory does at boot.
        try:
            from datetime import date as _date
            from services.fiscal_period_guard import ensure_periods_for_years
            this_year = _date.today().year
            # A NARROW range on purpose - see tests/conftest.py. A test that
            # needs a year with no period must be able to find one.
            ensure_periods_for_years(range(this_year - 1, this_year + 2))
        except Exception:
            pass
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


def _make_user(role_slug: str, tenant_id=None) -> User:
    """Create one user per role with exactly that role's permissions.

    ``tenant_id`` is applied at construction rather than assigned afterwards:
    `users` is registered as tenant-scoped, so the immutability guard in
    models/tenant_scope.py rejects changing tenant_id on an already-persisted
    row. Building the row correctly avoids fighting that guard.
    """
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
        tenant_id=tenant_id,
    )
    user.set_password(ROLE_PASSWORDS[role_slug])
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture(scope='function')
def e2e_tenant(db):
    """The tenant every fixture row and every non-owner user belongs to.

    Tenant.max_users defaults to 5 and UserService._check_tenant_quota refuses
    a create once the active non-owner users reach that ceiling. With eight
    non-owner roles plus the users-domain creation cells, the default quota was
    exhausted and /users/create started failing with 'بلغ المستأجر الحد
    الأقصى للمستخدمين' - a quota refusal, not an authorisation one. The
    ceiling is raised here so the quota check stays a separate, deliberate
    test rather than an accidental blocker everywhere else.
    """
    tenant = Tenant.query.filter_by(slug='e2e-tenant').first()
    if tenant is None:
        tenant = Tenant(name='E2E Tenant', name_ar='مستأجر الاختبار',
                        slug='e2e-tenant', country='UAE', is_active=True,
                        max_users=100)
        db.session.add(tenant)
        db.session.commit()
    return tenant


@pytest.fixture(scope='function')
def users(db, e2e_tenant):
    """Every role user, created inside the rolled-back transaction.

    Non-owner users are attached to a tenant on purpose. app.py:353-356 only
    calls set_current_tenant_id() when current_user.tenant_id is set and
    otherwise does set_current_tenant_id(None), and models/tenant_scope.py:218
    returns the query UNFILTERED when the current tenant is None. With a
    tenant-less user the auto-filter never engages, so every "another tenant
    must not be visible" assertion passes vacuously and the isolation coverage
    across the whole suite was meaningless. The owner keeps tenant_id None
    because the platform owner legitimately bypasses the filter.
    """
    made = {}
    for slug in ROLE_PERMISSIONS:
        # Non-owners get the tenant at construction time; the owner keeps
        # tenant_id None because the platform owner legitimately bypasses the
        # tenant filter (app.py sets tenant None for is_owner).
        tenant_for_user = None if slug == 'owner' else e2e_tenant.id
        made[slug] = _make_user(slug, tenant_id=tenant_for_user)
    db.session.commit()
    return made


@pytest.fixture(scope='function')
def owner(db, users):
    return users['owner']


@pytest.fixture(scope='function')
def login_as(client, users):
    """Log in as the scenario's real role. Returns the logged-in User.

    The session is cleared FIRST on every call. /auth/login short-circuits
    when current_user.is_authenticated (routes/auth.py:76) and redirects to
    the dashboard without reading the posted credentials, so logging in
    while a session already exists silently keeps the previous identity.
    That made every RBAC assertion in this suite pass vacuously: the
    "denied" roles were still the owner, so both the 200-expectation and the
    403-expectation halves of each matrix were decided by the owner's
    permissions rather than the role under test.

    Clearing the cookie jar is what makes the switch real; /auth/logout is
    not sufficient on its own because Flask-Login keeps current_user bound
    for the lifetime of the app context (see test_matrix.py:3495).
    """
    def _login(role_slug: str) -> User:
        # Drop any existing session before authenticating.
        client.get('/auth/logout')
        with client.session_transaction() as sess:
            sess.clear()
        user = users[role_slug]
        resp = client.post('/auth/login', data={
            'username': user.username,
            'password': ROLE_PASSWORDS[role_slug],
        }, follow_redirects=False)
        assert resp.status_code in (302, 303), (
            f'login failed for {role_slug}: status {resp.status_code}')
        # Guard against the silent no-op returning: the session must now
        # belong to the role we asked for, not to whoever was logged in
        # before this call.
        with client.session_transaction() as sess:
            logged_in_as = sess.get('_user_id')
        assert str(logged_in_as) == str(user.id), (
            f'login_as({role_slug!r}) did not switch identity: session holds '
            f'user {logged_in_as!r}, expected {user.id!r}')
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
def customer(db, e2e_tenant):
    c = Customer(
        name='E2E Customer', name_ar='عميل',
        customer_type='regular', phone='+0000000000',
        email='e2e_customer@test.local',
        credit_limit=Decimal('100000'), balance=Decimal('0'), is_active=True,
    )
    c.tenant_id = e2e_tenant.id
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
def product(db, category, e2e_tenant):
    p = Product(
        name='E2E Brake Pad', name_ar=' pads', sku='E2E-SKU-0001',
        category_id=category.id,
        cost_price=Decimal('50.000'), regular_price=Decimal('100.000'),
        current_stock=Decimal('100'), min_stock_alert=Decimal('10'),
        is_active=True,
    )
    p.tenant_id = e2e_tenant.id
    db.session.add(p)
    db.session.commit()
    return p


@pytest.fixture(scope='function')
def warehouse(db, e2e_tenant):
    w = Warehouse(
        name='E2E Main', name_ar='رئيسي', code='E2E-WH-1',
        location='E2E', is_main=True, is_active=True,
    )
    w.tenant_id = e2e_tenant.id
    db.session.add(w)
    db.session.commit()
    return w


@pytest.fixture(scope='function')
def supplier(db, e2e_tenant):
    s = Supplier(
        name='E2E Supplier', name_ar='مورد', phone='+0000000001',
        email='e2e_supplier@test.local', is_active=True,
    )
    s.tenant_id = e2e_tenant.id
    db.session.add(s)
    db.session.commit()
    return s


@pytest.fixture(scope='function')
def purchase(db, owner, supplier, product, warehouse):
    """Seed a purchase directly."""
    from models.purchase import Purchase, PurchaseLine
    pur = Purchase(
        purchase_number='P-CONF-001',
        supplier_id=supplier.id,
        warehouse_id=warehouse.id,
        supplier_name=supplier.name,
        currency='ILS',
        exchange_rate=Decimal('1'),
        subtotal=Decimal('500'),
        tax_amount=Decimal('0'),
        total_amount=Decimal('500'),
        amount_base=Decimal('500'),
        status='confirmed',
        user_id=owner.id,
    )
    db.session.add(pur)
    db.session.flush()
    db.session.add(PurchaseLine(
        purchase_id=pur.id,
        product_id=product.id,
        quantity=Decimal('10'),
        unit_cost=Decimal('50'),
        line_total=Decimal('500'),
    ))
    db.session.commit()
    return pur


@pytest.fixture(scope='function')
def sale(db, client, login_as, customer, product, warehouse):
    """Create a sale and return the Sale object."""
    from tests.e2e.harness import sale_form
    login_as('owner')
    data = sale_form(
        customer,
        [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
        warehouse=warehouse,
    )
    r = client.post('/sales/create', data=data)
    assert r.status_code in (302, 303)
    sid = r.headers.get('Location', '').split('/')[-1]
    from models.sale import Sale
    return Sale.query.get(int(sid))
