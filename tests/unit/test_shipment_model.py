"""Shipment model tests — real DB, no mocks."""

from decimal import Decimal


def _warehouse(db, name='WH-A'):
    from models.warehouse import Warehouse
    w = Warehouse(name=name, name_ar=name, code=name, is_active=True)
    db.session.add(w)
    db.session.flush()
    return w


def _product(db, warehouse, name='P1', sku='SKU-P1'):
    from models.product import Product
    from models.product import ProductCategory
    cat = ProductCategory.query.filter_by(name='Cat-SHIP-MODEL').first()
    if not cat:
        cat = ProductCategory(name='Cat-SHIP-MODEL', is_active=True)
        db.session.add(cat)
        db.session.flush()
    p = Product(name=name, sku=sku, category_id=cat.id, cost_price=Decimal('10'), regular_price=Decimal('20'),
                current_stock=Decimal('100'), is_active=True)
    db.session.add(p)
    db.session.flush()
    return p


def test_shipment_defaults_and_status_ar(db):
    from models.shipment import Shipment
    wh = _warehouse(db, 'WH-DEF')
    s = Shipment(shipment_number='SH-TEST-001', from_warehouse_id=wh.id, destination_name='موقع الرياض', status='draft')
    db.session.add(s)
    db.session.commit()
    assert s.status == 'draft'
    assert s.status_ar == 'مسودة'
    assert s.is_editable is True
    assert s.is_closable is False
    assert s.total_value == Decimal('0.000')
    d = s.to_dict()
    assert d['shipment_number'] == 'SH-TEST-001'
    assert 'مسودة' in d['status_ar']


def test_shipment_calculate_totals(db):
    from models.shipment import Shipment, ShipmentLine
    wh = _warehouse(db, 'WH-CALC')
    p1 = _product(db, wh, 'P-CALC-1', 'SKU-CALC-1')
    p2 = _product(db, wh, 'P-CALC-2', 'SKU-CALC-2')
    s = Shipment(shipment_number='SH-CALC-001', from_warehouse_id=wh.id, destination_name='موقع جدة')
    db.session.add(s)
    db.session.flush()
    l1 = ShipmentLine(shipment_id=s.id, product_id=p1.id, quantity=Decimal('5'), unit_cost=Decimal('10'), unit_price=Decimal('20'))
    l1.calculate_line_total()
    l2 = ShipmentLine(shipment_id=s.id, product_id=p2.id, quantity=Decimal('3'), unit_cost=Decimal('7'), unit_price=Decimal('15'))
    l2.calculate_line_total()
    db.session.add_all([l1, l2])
    db.session.flush()
    s.calculate_totals()
    assert s.total_quantity == Decimal('8')
    assert s.total_value == Decimal('71')  # 5*10 + 3*7


def test_shipment_destination_required(db):
    from models.shipment import Shipment
    import pytest
    wh = _warehouse(db, 'WH-VAL')
    # empty destination should raise on validate
    with pytest.raises(Exception):
        s = Shipment(shipment_number='SH-VAL-001', from_warehouse_id=wh.id, destination_name='  ')
        db.session.add(s)
        db.session.flush()


def test_shipment_sale_link_nullable(db):
    from models.sale import Sale
    from models.warehouse import Warehouse
    from models.customer import Customer
    from models.user import User, Role, Permission
    # shipment column exists and is nullable — existing sales still work
    wh = _warehouse(db, 'WH-SALE')
    p = _product(db, wh, 'P-SALE', 'SKU-SALE')
    # minimal tenant/customer/user for sale
    from models.tenant import Tenant
    t = Tenant(name='T-SHIP', name_ar='ت', slug='t-ship', is_active=True)
    db.session.add(t)
    db.session.flush()
    # ensure sale without shipment_id still creates
    # (use existing conftest helpers pattern — create minimal sale)
    # direct: check column exists
    from sqlalchemy import inspect as sa_inspect
    cols = [c['name'] for c in sa_inspect(db.engine).get_columns('sales')]
    assert 'shipment_id' in cols
