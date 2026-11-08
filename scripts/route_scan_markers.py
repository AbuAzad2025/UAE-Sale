"""Loose static scan — كم مسار في التطبيق يحمل علامة عزل (tenant) داخل دالته؟"""
import inspect
import sys
import os

sys.path.insert(0, '.')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret')
os.environ.setdefault('OWNER_PASSWORD', 'TestOwner@1234567890123456!')
os.environ.setdefault('DEBUG', 'true')

from app import create_app  # noqa: E402

TENANT_MODULES = [
    'routes.advanced_ledger', 'routes.ai', 'routes.api', 'routes.api_analytics',
    'routes.approvals', 'routes.cheques', 'routes.customers', 'routes.erp_modules',
    'routes.expenses', 'routes.gamification', 'routes.graphql', 'routes.hr',
    'routes.inbound_shipments', 'routes.ledger', 'routes.main', 'routes.owner',
    'routes.payments', 'routes.products', 'routes.purchases', 'routes.reports',
    'routes.returns', 'routes.sales', 'routes.shipments', 'routes.suppliers',
    'routes.users', 'routes.warehouse', 'routes.whatsapp', 'routes.writeoffs',
]

MARKERS = (
    'get_owned_or_404', 'tenant_id', 'get_current_tenant_id', 'TenantScoped',
    'scope', 'scoped', 'visible_to', 'current_tenant', 'assert_',
    'permission_required', 'login_required', 'owner_required', 'tenant_required',
)


def handler_source(fn):
    try:
        return inspect.getsource(fn)
    except (OSError, TypeError):
        return ''


def main():
    app = create_app()
    hits, misses = [], []
    with app.app_context():
        for rule in app.url_map.iter_rules():
            if rule.endpoint == 'static':
                continue
            fn = app.view_functions.get(rule.endpoint)
            module = getattr(fn, '__module__', '') if fn else ''
            if module not in TENANT_MODULES:
                continue
            src = handler_source(fn)
            if any(m in src for m in MARKERS):
                hits.append((rule.rule, rule.endpoint))
            else:
                misses.append((rule.rule, rule.endpoint, module))

    print('tenant-module routes:', len(hits) + len(misses))
    print('with isolation marker:', len(hits))
    print('NO marker:', len(misses))
    print('---')
    for path, endpoint, module in sorted(misses):
        print(f'{path}  {endpoint}  ({module})')


if __name__ == '__main__':
    main()
