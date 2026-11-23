"""Maintenance has two operational roles; the manager can perform all of them."""
import os
os.environ.setdefault('PYTHONIOENCODING','utf-8')


def test_maintenance_roles_are_only_reception_and_engineer():
    src = open('utils/system_init.py', encoding='utf-8').read()
    block = src[src.index('"maintenance_reception": ('):]
    # no extra maintenance role definitions remain
    for extra in ('"maintenance_cashier": (', '"maintenance_closer": (',
                  '"maintenance_discount": (', '"maintenance_settings": ('):
        assert extra not in block, extra


def test_both_maintenance_roles_and_manager_have_full_purpose():
    src = open('utils/system_init.py', encoding='utf-8').read()
    required = {
        'maintenance_view', 'maintenance_receive', 'maintenance_work',
        'maintenance_cashier', 'maintenance_close', 'maintenance_discount',
        'maintenance_settings', 'maintenance_purchase',
    }
    # reception block and engineer block each carry the full set
    for start, end in [('"maintenance_reception": (','"maintenance_engineer": ('),
                       ('"maintenance_engineer": (','}')]:
        block = src[src.index(start):src.index(end, src.index(start))]
        for code in required:
            assert f'"{code}"' in block, (start, code)
    # manager still holds every maintenance permission
    i = src.index('"manager": (')
    manager = src[i:src.index('"seller": (', i)]
    for code in required:
        assert f'"{code}"' in manager, code


def test_safety_gate_allows_every_maintenance_write_endpoint():
    """The 503 safety gate must not silently reject real write endpoints."""
    import routes.maintenance as maintenance_routes
    from app import create_app
    app = create_app()
    allowed = maintenance_routes.ALLOWED_WRITE_ENDPOINTS
    with app.app_context():
        registered = {r.endpoint for r in app.url_map.iter_rules()
                      if r.endpoint.startswith('maintenance.')}
        write = {r.endpoint for r in app.url_map.iter_rules()
                 if r.endpoint.startswith('maintenance.')
                 and ({'POST', 'PUT', 'PATCH', 'DELETE'} & r.methods)}
        assert allowed - registered == set(), allowed - registered
        assert write - allowed == set(), write - allowed


def test_maintenance_sidebar_has_only_three_core_links():
    base = open('templates/base.html', encoding='utf-8').read()
    i = base.index("request.endpoint.startswith('maintenance.')")
    block = base[i:base.index('{% endif %}', base.index('</ul>', i))]
    # exactly the three core links remain in the sidebar
    assert "maintenance.list_orders" in block
    assert "maintenance.create_order" in block
    assert "maintenance.settings" in block
    for removed in ('maintenance.purchases_list', 'maintenance.maintenance_cost_report',
                    'maintenance.devices_list', 'maintenance.services_list'):
        assert removed not in block, removed
    # the removed modules are still reachable as quick actions on the orders page
    listing = open('templates/maintenance/list.html', encoding='utf-8').read()
    for href in ('maintenance.purchases_list', 'maintenance.maintenance_cost_report',
                 'maintenance.devices_list', 'maintenance.services_list'):
        assert href in listing, href
