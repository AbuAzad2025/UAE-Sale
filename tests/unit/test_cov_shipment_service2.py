"""ShipmentService edge coverage — real DB (sqlite in unit suite)."""
from decimal import Decimal

import pytest


def _warehouse(db, name):
    from models.warehouse import Warehouse
    w = Warehouse(name=name, name_ar=name, code=name, is_active=True)
    db.session.add(w)
    db.session.flush()
    return w


def _product(db, name, sku):
    from models.product import Product, ProductCategory
    cat = ProductCategory.query.filter_by(name='Cat-SHIP-S2').first()
    if not cat:
        cat = ProductCategory(name='Cat-SHIP-S2', is_active=True)
        db.session.add(cat)
        db.session.flush()
    p = Product(name=name, sku=sku, category_id=cat.id, cost_price=Decimal('5'),
                regular_price=Decimal('10'), current_stock=Decimal('50'), is_active=True)
    db.session.add(p)
    db.session.flush()
    return p


def _make(db):
    from services.shipment_service import ShipmentService
    wh = _warehouse(db, 'WH-S2')
    p = _product(db, 'P-S2', 'SKU-S2')
    return ShipmentService, ShipmentService.create_shipment(
        from_warehouse_id=wh.id, destination_name='موقع s2',
        lines_data=[{'product_id': p.id, 'quantity': 1}])


def test_not_found_errors(db):
    Svc, _ = _make(db)
    for fn in (Svc.send_shipment, Svc.arrive_shipment, Svc.start_selling,
               Svc.close_shipment, Svc.cancel_shipment):
        with pytest.raises(ValueError, match='غير موجودة'):
            fn(999999)


def test_double_cancel_raises(db):
    Svc, s = _make(db)
    Svc.cancel_shipment(s.id)
    with pytest.raises(ValueError, match='ملغاة بالفعل'):
        Svc.cancel_shipment(s.id)


def test_start_selling_from_draft_raises(db):
    Svc, s = _make(db)
    with pytest.raises(ValueError):
        Svc.start_selling(s.id)


def test_send_from_selling_raises(db):
    Svc, s = _make(db)
    Svc.send_shipment(s.id)
    Svc.arrive_shipment(s.id)
    Svc.start_selling(s.id)
    with pytest.raises(ValueError):
        Svc.send_shipment(s.id)
    with pytest.raises(ValueError):
        Svc.arrive_shipment(s.id)


def test_create_aliases_and_relations(db):
    from services.shipment_service import ShipmentService
    wh = _warehouse(db, 'WH-S2B')
    dest = _warehouse(db, 'WH-S2-DEST')
    p = _product(db, 'P-S2B', 'SKU-S2B')
    s = ShipmentService.create_shipment(
        from_warehouse_id=wh.id, destination_name='  موقع فرعي  ',
        destination_warehouse_id=dest.id, destination_type='warehouse',
        tenant_id=None, created_by_id=None, assigned_to_id=None,
        lines_data=[{'product_id': p.id, 'quantity': 3, 'cost': '7.5', 'price': '15'}],
        notes='n',
    )
    assert s.destination_name == 'موقع فرعي'
    assert s.destination_type == 'warehouse'
    assert s.destination_warehouse_id == dest.id
    assert s.lines[0].unit_cost == Decimal('7.5')
    assert s.lines[0].unit_price == Decimal('15')
    assert s.total_quantity == Decimal('3')


def test_create_missing_product_id_raises(db):
    from services.shipment_service import ShipmentService
    wh = _warehouse(db, 'WH-S2C')
    with pytest.raises(ValueError):
        ShipmentService.create_shipment(
            from_warehouse_id=wh.id, destination_name='موقع',
            lines_data=[{'quantity': 2}])


def test_create_negative_quantity_raises(db):
    from services.shipment_service import ShipmentService
    wh = _warehouse(db, 'WH-S2D')
    p = _product(db, 'P-S2D', 'SKU-S2D')
    with pytest.raises(ValueError):
        ShipmentService.create_shipment(
            from_warehouse_id=wh.id, destination_name='موقع',
            lines_data=[{'product_id': p.id, 'quantity': -1}])


def test_get_or_404(db):
    from werkzeug.exceptions import NotFound
    from services.shipment_service import ShipmentService
    _, s = _make(db)
    assert ShipmentService.get_shipment_or_404(s.id).id == s.id
    with pytest.raises(NotFound):
        ShipmentService.get_shipment_or_404(999999)


def test_generate_number_fallback(monkeypatch, db):
    import services.shipment_service as mod
    monkeypatch.setattr(mod, 'generate_number', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('x')))
    from services.shipment_service import ShipmentService
    wh = _warehouse(db, 'WH-S2E')
    p = _product(db, 'P-S2E', 'SKU-S2E')
    s = ShipmentService.create_shipment(
        from_warehouse_id=wh.id, destination_name='موقع',
        lines_data=[{'product_id': p.id, 'quantity': 1}])
    assert s.shipment_number.startswith('SH-')
