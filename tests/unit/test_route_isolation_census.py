"""الاختبار القانوني: 499 مسارًا — كل مسار مُصنَّف + كل مسار 'tenant' يحمل دليل عزل.

هذا الفحص يُفشل التطوير لو:

* سُجِّل مسار جديد بدون إدخال تصنيفه في ``MODULE_SCOPE``/``SPECIAL_ROUTES``.
* أُضيفت دالة إلى مسار `tenant` بدون أي رمز عزل في مصدرها.
"""
import pytest


def test_every_route_is_classified(app):
    from utils import route_scope

    with app.app_context():
        for rule in app.url_map.iter_rules():
            if rule.endpoint == 'static':
                continue
            scope = route_scope.classify(rule.rule, rule.endpoint,
                                         getattr(app.view_functions.get(rule.endpoint),
                                                 '__module__', ''))
            assert scope in route_scope.VALID_SCOPES, rule.rule


def test_tenant_routes_carry_isolation_evidence(app):
    from utils import route_scope

    failures = []
    with app.app_context():
        for entry in route_scope.audit_routes(app):
            if entry['scope'] != 'tenant':
                continue
            if not entry['markers']:
                failures.append(f"{entry['path']} ({entry['endpoint']})")
    assert failures == [], 'tenant routes without isolation evidence: ' + ', '.join(failures)


def test_owner_and_vault_are_platform(app):
    from utils import route_scope

    with app.app_context():
        for rule in app.url_map.iter_rules():
            if rule.endpoint == 'static':
                continue
            module = getattr(app.view_functions.get(rule.endpoint), '__module__', '')
            if module in ('routes.owner', 'routes.payment_vault'):
                scope = route_scope.classify(rule.rule, rule.endpoint, module)
                assert scope == 'platform', (rule.rule, scope)


def test_public_modules_are_public(app):
    from utils import route_scope

    PUBLIC = {'routes.public', 'routes.auth', 'routes.language', 'routes.api_docs'}
    with app.app_context():
        for rule in app.url_map.iter_rules():
            if rule.endpoint == 'static':
                continue
            module = getattr(app.view_functions.get(rule.endpoint), '__module__', '')
            if module in PUBLIC:
                scope = route_scope.classify(rule.rule, rule.endpoint, module)
                assert scope == 'public', (rule.rule, scope)


def test_every_module_prefix_in_scope_map(app):
    from utils import route_scope

    with app.app_context():
        seen = set()
        for rule in app.url_map.iter_rules():
            if rule.endpoint == 'static':
                continue
            fn = app.view_functions.get(rule.endpoint)
            module = getattr(fn, '__module__', '') if fn else ''
            if module and module != 'static' and module not in route_scope.MODULE_SCOPE:
                seen.add(module)
        assert seen == set(), f'unclassified modules: {sorted(seen)}'


def test_full_inventory_count(app):
    from utils import route_scope

    audit = route_scope.audit_routes(app)
    assert len(audit) == 542
    scopes = {}
    for entry in audit:
        scopes[entry['scope']] = scopes.get(entry['scope'], 0) + 1
    # نطاقات معروفة للتحقق من سلامة المسح — أي تغيير يزيح العدد وباهتز
    assert scopes.get('tenant', 0) == 387
    assert scopes.get('platform', 0) == 121
    assert scopes.get('public', 0) == 27
    assert scopes.get('system', 0) == 7
