"""تدقيق شمولي لعزل المسارات في التطبيق (514 مسارًا معروفًا).

كل مسار مُسجَّل في المستودع يُصنَّف صراحةً إلى:

* ``public``  — صفحة عامة بدون أي بيانات مستأجر (landing, pricing, support).
* ``system``  — نقاط فحص/رصد بسيطة (health, version) — لا بيانات إطلاقًا.
* ``platform``— لوحة المالك/المزود فقط؛ `is_owner` / الحسابات الفوق-مالكة.
* ``tenant``  — بيانات الشركة حصرًا؛ يجب أن يحوي رمز تمرير عزل واحدًا على
                الأقل (get_owned_or_404 / tenant_id / permission_required …).

أي إضافة مسار جديد إلى التطبيق تسقط الفحص حتى يُصنَّف في هذا الملف
(عبر MODULE_SCOPE أو SPECIAL_ROUTES) مع رمز عزل واحد على الأقل عند `tenant`.
"""
import inspect

MODULE_SCOPE = {
    'routes.advanced_ledger': 'tenant',
    'routes.ai': 'tenant',
    'routes.api': 'tenant',
    'routes.api_analytics': 'tenant',
    'routes.api_docs': 'public',
    'routes.api_enhanced': 'tenant',
    'routes.approvals': 'tenant',
    'routes.auth': 'public',
    'routes.cheques': 'tenant',
    'routes.customers': 'tenant',
    'routes.erp_modules': 'tenant',
    'routes.expenses': 'tenant',
    'routes.gamification': 'tenant',
    'routes.graphql': 'tenant',
    'routes.hr': 'tenant',
    'routes.inbound_shipments': 'tenant',
    'routes.language': 'public',
    'routes.ledger': 'tenant',
    'routes.maintenance': 'tenant',
    'routes.main': 'tenant',
    'routes.monitoring': 'platform',
    'utils.monitoring': 'system',
    'routes.owner': 'platform',
    'routes.payment_vault': 'platform',
    'routes.payments': 'tenant',
    'routes.products': 'tenant',
    'routes.public': 'public',
    'routes.purchases': 'tenant',
    'routes.reports': 'tenant',
    'routes.returns': 'tenant',
    'routes.sales': 'tenant',
    'routes.shipments': 'tenant',
    'routes.suppliers': 'tenant',
    'routes.support': 'tenant',
    'routes.users': 'tenant',
    'routes.warehouse': 'tenant',
    'routes.whatsapp': 'tenant',
    'routes.writeoffs': 'tenant',
}

SPECIAL_ROUTES = {
    ('/', 'main.index'): 'public',
    ('/api/client-errors', 'api.client_errors'): 'public',
    ('/api/health', 'api.health'): 'system',
    ('/api/healthz', 'api.healthz'): 'system',
    ('/api/version', 'api.version'): 'system',
    ('/monitoring/health', 'monitoring.health'): 'system',  # bare liveness probe
}

# علامات تمرير العزل في مصدر الدالة (واحدة كافية لكل `tenant`-class route)
TENANT_MARKERS = (
    'get_owned_or_404',
    'visible_to',
    'tenant_id',
    'get_current_tenant_id',
    'current_tenant',
    'TenantScoped',
    'scope',
    'permission_required',
    'owner_required',
    'tenant_required',
    'login_required',
)

VALID_SCOPES = frozenset({'tenant', 'platform', 'public', 'system'})


def classify(path, endpoint, module):
    key = (path, endpoint)
    if key in SPECIAL_ROUTES:
        return SPECIAL_ROUTES[key]
    return MODULE_SCOPE.get(module, 'tenant')


def markers_in_source(fn_source, markers=TENANT_MARKERS):
    return [m for m in markers if m in fn_source]


def source_of(fn):
    try:
        return inspect.getsource(fn)
    except (OSError, TypeError):
        return ''


def audit_routes(app):
    report = []
    with app.app_context():
        for rule in app.url_map.iter_rules():
            if rule.endpoint == 'static':
                continue
            fn = app.view_functions.get(rule.endpoint)
            module = getattr(fn, '__module__', '') if fn else ''
            scope = classify(rule.rule, rule.endpoint, module)
            src = source_of(fn)
            hits = markers_in_source(src) if fn else []
            entry = {
                'path': rule.rule,
                'endpoint': rule.endpoint,
                'module': module,
                'scope': scope,
                'markers': hits,
                'source': src,
            }
            report.append(entry)
    return report
