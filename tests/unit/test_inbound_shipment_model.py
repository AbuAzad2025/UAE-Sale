"""Inbound shipment model tests."""

from decimal import Decimal


def _warehouse(db, name='WH-INB-M'):
    from models.warehouse import Warehouse
    w = Warehouse(name=name, name_ar=name, code=name, is_active=True)
    db.session.add(w)
    db.session.flush()
    return w


def _product(db, name='P-INB-M', sku='SKU-INB-M'):
    from models.product import Product, ProductCategory
    cat = ProductCategory.query.filter_by(name='Cat-INB-M').first()
    if not cat:
        cat = ProductCategory(name='Cat-INB-M', is_active=True)
        db.session.add(cat)
        db.session.flush()
    p = Product(name=name, sku=sku, category_id=cat.id, cost_price=Decimal('5'), regular_price=Decimal('10'), current_stock=Decimal('50'), is_active=True)
    db.session.add(p)
    db.session.flush()
    return p


def test_inbound_defaults(db):
    from models.inbound_shipment import InboundShipment
    wh = _warehouse(db, 'WH-INB-DEF')
    s = InboundShipment(shipment_number='INB-TEST-001', warehouse_id=wh.id, status='in_transit')
    db.session.add(s)
    db.session.commit()
    assert s.status == 'in_transit'
    assert s.status_ar == 'في الطريق'
    assert s.total_quantity == Decimal('0.000')


def test_inbound_totals(db):
    from models.inbound_shipment import InboundShipment, InboundShipmentLine
    wh = _warehouse(db, 'WH-INB-CALC')
    p1 = _product(db, 'P-INB-C1', 'SKU-INB-C1')
    p2 = _product(db, 'P-INB-C2', 'SKU-INB-C2')
    s = InboundShipment(shipment_number='INB-CALC-001', warehouse_id=wh.id)
    db.session.add(s)
    db.session.flush()
    l1 = InboundShipmentLine(inbound_shipment_id=s.id, product_id=p1.id, quantity_expected=Decimal('4'), unit_cost=Decimal('10'))
    l1.calculate_line_total()
    l2 = InboundShipmentLine(inbound_shipment_id=s.id, product_id=p2.id, quantity_expected=Decimal('2'), unit_cost=Decimal('7'))
    l2.calculate_line_total()
    db.session.add_all([l1, l2])
    db.session.flush()
    s.calculate_totals()
    assert s.total_quantity == Decimal('6')
    assert s.total_value == Decimal('54')
