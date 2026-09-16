"""Inbound shipment routes — permission and workflow."""

from models.inbound_shipment import InboundShipment


def _warehouse(db, name='WH-INB-R'):
    from models.warehouse import Warehouse
    w = Warehouse(name=name, name_ar=name, code=name, is_active=True)
    db.session.add(w)
    db.session.commit()
    return w


def test_inbound_list_requires_login(client, db):
    assert client.get('/inbound-shipments').status_code in (302, 401)


def test_owner_can_list_and_create(client, login_owner, db):
    wh = _warehouse(db, 'WH-INB-LIST')
    from models.product import Product, ProductCategory
    from decimal import Decimal
    cat = ProductCategory(name='Cat-INB-R', is_active=True)
    db.session.add(cat)
    db.session.flush()
    p = Product(name='P-INB-R', sku='SKU-INB-R', category_id=cat.id, cost_price=Decimal('5'), regular_price=Decimal('10'), current_stock=Decimal('10'), is_active=True)
    db.session.add(p)
    db.session.commit()
    from services.inbound_shipment_service import InboundShipmentService
    InboundShipmentService.create_shipment(warehouse_id=wh.id, lines_data=[{'product_id': p.id, 'quantity_expected': 1}])
    resp = client.get('/inbound-shipments')
    assert resp.status_code == 200
    assert 'الشحنات الواردة' in resp.get_data(as_text=True)
    assert client.get('/inbound-shipments/create').status_code == 200


def test_inbound_workflow_via_routes(client, login_owner, db):
    wh = _warehouse(db, 'WH-INB-FLOW')
    from models.product import Product, ProductCategory
    from decimal import Decimal
    cat = ProductCategory(name='Cat-INB-FLOW', is_active=True)
    db.session.add(cat)
    db.session.flush()
    p = Product(name='P-INB-FLOW', sku='SKU-INB-FLOW', category_id=cat.id, cost_price=Decimal('5'), regular_price=Decimal('10'), current_stock=Decimal('10'), is_active=True)
    db.session.add(p)
    db.session.commit()
    from services.inbound_shipment_service import InboundShipmentService
    s = InboundShipmentService.create_shipment(warehouse_id=wh.id, lines_data=[{'product_id': p.id, 'quantity_expected': 2}])
    assert client.post(f'/inbound-shipments/{s.id}/arrive').status_code == 302
    db.session.refresh(s)
    assert s.status == 'arrived'
    assert client.post(f'/inbound-shipments/{s.id}/inspect').status_code == 302
    db.session.refresh(s)
    assert s.status == 'inspected'
    assert client.post(f'/inbound-shipments/{s.id}/put-away').status_code == 302
    db.session.refresh(s)
    assert s.status == 'put_away'
    assert client.post(f'/inbound-shipments/{s.id}/close').status_code == 302
    db.session.refresh(s)
    assert s.status == 'closed'
    html = client.get(f'/inbound-shipments/{s.id}').get_data(as_text=True)
    assert s.shipment_number in html


def test_seller_blocked(client, login_seller, db):
    assert client.get('/inbound-shipments').status_code in (302, 403)


def test_tenant_isolation(client, app, db):
    """Tenant A cannot see inbound shipments of tenant B."""
    from models.tenant import Tenant
    from models.tenant_scope import set_current_tenant_id, clear_current_tenant_id
    from models.warehouse import Warehouse
    from models.product import Product, ProductCategory
    from decimal import Decimal
    from services.inbound_shipment_service import InboundShipmentService
    # create two tenants/warehouses via service helpers
    t_a = Tenant(name='T-INB-A', name_ar='ت', slug='t-inb-a', is_active=True)
    t_b = Tenant(name='T-INB-B', name_ar='ت', slug='t-inb-b', is_active=True)
    db.session.add_all([t_a, t_b])
    db.session.flush()
    wh_a = Warehouse(name='WH-INB-ISO-A', name_ar='WH-INB-ISO-A', code='WH-INB-ISO-A', tenant_id=t_a.id, is_active=True)
    wh_b = Warehouse(name='WH-INB-ISO-B', name_ar='WH-INB-ISO-B', code='WH-INB-ISO-B', tenant_id=t_b.id, is_active=True)
    db.session.add_all([wh_a, wh_b])
    db.session.flush()
    cat = ProductCategory(name='Cat-INB-ISO', is_active=True)
    db.session.add(cat)
    db.session.flush()
    p = Product(name='P-INB-ISO', sku='SKU-INB-ISO', category_id=cat.id, cost_price=Decimal('5'), regular_price=Decimal('10'), current_stock=Decimal('10'), is_active=True)
    db.session.add(p)
    db.session.commit()
    set_current_tenant_id(t_a.id)
    try:
        s_a = InboundShipmentService.create_shipment(warehouse_id=wh_a.id, tenant_id=t_a.id, lines_data=[{'product_id': p.id, 'quantity_expected': 1}])
    finally:
        clear_current_tenant_id()
    set_current_tenant_id(t_b.id)
    try:
        rows = InboundShipment.query.all()
        ids = {r.id for r in rows}
        assert s_a.id not in ids
    finally:
        clear_current_tenant_id()
