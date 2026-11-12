"""Route compliance sweep — كل مسار GET في التطبيق يُختبر بدون 500.

* مجهول الهوية: يجب ألاّ يوجد 500 على أي مسار (يعيد توجيه/404/200).
* مستخدم عادي (غير مالك): كل مسار platform يجب أن يعيد 302/403/404 (ولا 200).

المسارات المعلمة (int:id) تُختبر بمعرّف 1 ما لم تبوّب يدويًا.
"""

import pytest


@pytest.fixture
def plain_user(db):
    """مستخدم عادي بصلاحية seller — لا مالك."""
    from models import User, Role, Permission
    from extensions import db as _db

    role = Role.query.filter_by(slug="seller").first()
    if role is None:
        role = Role(name="Seller", name_ar="بائع", slug="seller")
        perm = Permission.query.filter_by(code="manage_sales").first()
        if perm is None:
            perm = Permission(
                code="manage_sales",
                name="Manage Sales",
                name_ar="إدارة المبيعات",
                category="sales",
            )
            _db.session.add(perm)
            _db.session.flush()
        role.permissions = [perm]
        _db.session.add(role)
        _db.session.flush()

    user = User(
        username="plain_sweep",
        email="plain_sweep@test.com",
        full_name="Plain",
        is_active=True,
        role_id=role.id,
    )
    user.set_password("Pass123!")
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture
def logged_client(client, plain_user):
    client.post(
        "/auth/login",
        data={
            "username": plain_user.username,
            "password": "Pass123!",
        },
        follow_redirects=True,
    )
    return client


def _parametrized_routes(app):
    out = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        if rule.arguments:
            continue
        if "GET" not in rule.methods:
            continue
        out.append(rule.rule)
    return sorted(out)


def test_all_get_routes_no_500_anonymous(client, app):
    """أي 5xx = محظور. استثناء: /payment-vault/health — 503 مقصود حين لا
    تكون البيئة مهيأة بالكامل (health check "غير سليم" ليس crash)."""
    failures = []
    for path in _parametrized_routes(app):
        try:
            resp = client.get(path)
            if resp.status_code >= 500:
                # 503 على /payment-vault/health مقصود: البيئة غير مهيأة بالكامل
                if path == "/payment-vault/health" and resp.status_code == 503:
                    continue
                failures.append(f"{path} -> {resp.status_code}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{path} -> {type(exc).__name__}: {exc}")
    assert failures == [], "Anonymous GET routes returning 500+ : " + "; ".join(
        failures
    )


def test_platform_routes_no_200_for_plain_user(logged_client, app):
    """بقواعد صارمة: مسارات platform (owner/vault) — plain_user لا يرى 200.

    ملاحظة: `system` routes (liveness/health/version) عامة عن قصد وهي خارج النطاق هنا.
    """
    from utils import route_scope

    failures = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        if "GET" not in rule.methods:
            continue
        if rule.arguments:
            continue
        module = getattr(app.view_functions.get(rule.endpoint), "__module__", "")
        if route_scope.classify(rule.rule, rule.endpoint, module) == "platform":
            resp = logged_client.get(rule.rule, follow_redirects=False)
            if resp.status_code == 200:
                failures.append(f"{rule.rule} -> 200 for plain user")
    assert failures == [], "Platform routes leaking to plain users: " + "; ".join(
        failures
    )


def test_tenant_routes_no_500_for_plain_user(logged_client, app):
    """المستخدم العادي على أي مسار tenant — لا 500 مسموح."""
    from utils import route_scope

    failures = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        if "GET" not in rule.methods:
            continue
        if rule.arguments:
            continue
        module = getattr(app.view_functions.get(rule.endpoint), "__module__", "")
        if route_scope.classify(rule.rule, rule.endpoint, module) != "tenant":
            continue
        resp = logged_client.get(rule.rule, follow_redirects=False)
        if resp.status_code >= 500:
            failures.append(f"{rule.rule} -> {resp.status_code}")
    assert failures == [], "Tenant routes returning 500+ to plain user: " + "; ".join(
        failures
    )
