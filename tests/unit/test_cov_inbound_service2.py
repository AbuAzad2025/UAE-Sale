"""InboundShipmentService edge coverage — real DB (sqlite in unit suite)."""
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
    cat = ProductCategory.query.filter_by(name='Cat-INB-S2').first()
    if not cat:
        cat = ProductCategory(name='Cat-INB-S2', is_active=True)
        db.session.add(cat)
        db.session.flush()
    p = Product(name=name, sku=sku, category_id=cat.id, cost_price=Decimal('5'),
                regular_price=Decimal('10'), current_stock=Decimal('20'), is_active=True)
    db.session.add(p)
    db.session.flush()
    return p


_SEQ = {'n': 0}


def _make(db):
    from services.inbound_shipment_service import InboundShipmentService as Svc
    _SEQ['n'] += 1
    tag = f"INB2-{_SEQ['n']}"
    wh = _warehouse(db, f'WH-{tag}')
    p = _product(db, f'P-{tag}', f'SKU-{tag}')
    s = Svc.create_shipment(
        warehouse_id=wh.id, carrier='DHL', tracking_number='TRK1',
        lines_data=[{'product_id': p.id, 'quantity_expected': 4, 'unit_cost': 6}])
    return Svc, s


def test_not_found_errors(db):
    Svc, _ = _make(db)
    for fn in (Svc.arrive, Svc.inspect_shipment, Svc.put_away, Svc.close, Svc.cancel):
        with pytest.raises(ValueError, match='غير موجودة'):
            fn(999999)


def test_arrive_twice_raises(db):
    Svc, s = _make(db)
    Svc.arrive(s.id)
    with pytest.raises(ValueError):
        Svc.arrive(s.id)


def test_inspect_with_explicit_data(db):
    Svc, s = _make(db)
    Svc.arrive(s.id)
    line_id = s.lines[0].id
    s = Svc.inspect_shipment(s.id, inspection_data=[
        {'line_id': line_id, 'quantity_accepted': 3}])
    assert s.status == 'inspected'
    assert s.lines[0].quantity_accepted == Decimal('3')
    assert s.inspected_at is not None


def test_inspect_invalid_line_raises(db):
    Svc, s = _make(db)
    Svc.arrive(s.id)
    with pytest.raises(ValueError, match='غير صالح'):
        Svc.inspect_shipment(s.id, inspection_data=[{'line_id': 999999, 'quantity_accepted': 1}])


def test_inspect_out_of_range_raises(db):
    Svc, s = _make(db)
    Svc.arrive(s.id)
    line_id = s.lines[0].id
    with pytest.raises(ValueError, match='خارج النطاق'):
        Svc.inspect_shipment(s.id, inspection_data=[
            {'line_id': line_id, 'quantity_accepted': 99}])
    with pytest.raises(ValueError, match='خارج النطاق'):
        Svc.inspect_shipment(s.id, inspection_data=[
            {'line_id': line_id, 'quantity_accepted': -1}])


def test_inspect_with_bin_and_lot(db):
    Svc, s = _make(db)
    Svc.arrive(s.id)
    line_id = s.lines[0].id
    s = Svc.inspect_shipment(s.id, inspection_data=[
        {'line_id': line_id, 'quantity_accepted': 4,
         'warehouse_bin_id': 7, 'lot_id': 9}])
    assert s.lines[0].warehouse_bin_id == 7
    assert s.lines[0].lot_id == 9


def test_inspect_line_from_other_shipment_rejected(db):
    Svc, s = _make(db)
    _, other = _make(db)
    Svc.arrive(s.id)
    with pytest.raises(ValueError, match='غير صالح'):
        Svc.inspect_shipment(s.id, inspection_data=[
            {'line_id': other.lines[0].id, 'quantity_accepted': 1}])


def test_cancel_from_put_away_raises(db):
    Svc, s = _make(db)
    Svc.arrive(s.id)
    Svc.inspect_shipment(s.id)
    Svc.put_away(s.id)
    with pytest.raises(ValueError, match='تم إدخالها'):
        Svc.cancel(s.id)


def test_close_from_wrong_state_raises(db):
    Svc, s = _make(db)
    with pytest.raises(ValueError):
        Svc.close(s.id)


def test_create_missing_product_id_raises(db):
    Svc, _ = _make(db)
    wh = _warehouse(db, 'WH-INB2X')
    with pytest.raises(ValueError):
        Svc.create_shipment(warehouse_id=wh.id, lines_data=[{'quantity_expected': 2}])


def test_put_away_updates_linked_po(db):
    from datetime import date
    from models import Supplier
    from models.erp_modules import PurchaseOrder
    from services.inbound_shipment_service import InboundShipmentService as Svc
    _SEQ['n'] += 1
    tag = f"PO-{_SEQ['n']}"
    wh = _warehouse(db, f'WH-{tag}')
    p = _product(db, f'P-{tag}', f'SKU-{tag}')
    sup = Supplier(name=f'SUP-{tag}')
    db.session.add(sup)
    db.session.flush()
    po = PurchaseOrder(po_number=f'PO-{tag}', supplier_id=sup.id,
                       warehouse_id=wh.id, po_date=date.today(), status='approved')
    db.session.add(po)
    db.session.flush()
    # full acceptance -> received
    s = Svc.create_shipment(warehouse_id=wh.id, purchase_order_id=po.id,
                            lines_data=[{'product_id': p.id, 'quantity_expected': 2}])
    Svc.arrive(s.id)
    Svc.inspect_shipment(s.id)
    Svc.put_away(s.id)
    db.session.refresh(po)
    assert po.status == 'received'
    # partial acceptance -> partially_received
    po2 = PurchaseOrder(po_number=f'PO2-{tag}', supplier_id=sup.id,
                        warehouse_id=wh.id, po_date=date.today(), status='approved')
    db.session.add(po2)
    db.session.flush()
    s2 = Svc.create_shipment(warehouse_id=wh.id, purchase_order_id=po2.id,
                             lines_data=[{'product_id': p.id, 'quantity_expected': 4}])
    Svc.arrive(s2.id)
    Svc.inspect_shipment(s2.id, inspection_data=[
        {'line_id': s2.lines[0].id, 'quantity_accepted': 1}])
    Svc.put_away(s2.id)
    db.session.refresh(po2)
    assert po2.status == 'partially_received'


def test_put_away_stock_fallback_signature(monkeypatch, db):
    from services import stock_service as stock_mod
    from services.inbound_shipment_service import InboundShipmentService as Svc
    _SEQ['n'] += 1
    tag = f"FB-{_SEQ['n']}"
    wh = _warehouse(db, f'WH-{tag}')
    p = _product(db, f'P-{tag}', f'SKU-{tag}')
    real = stock_mod.StockService.adjust_stock

    def old_sig(product_id, quantity, **kw):
        if 'post_gl' in kw:
            raise TypeError('no post_gl')
        return real(product_id, quantity)

    monkeypatch.setattr(stock_mod.StockService, 'adjust_stock', staticmethod(old_sig))
    s = Svc.create_shipment(warehouse_id=wh.id,
                            lines_data=[{'product_id': p.id, 'quantity_expected': 2}])
    Svc.arrive(s.id)
    Svc.inspect_shipment(s.id)
    s = Svc.put_away(s.id)
    assert s.status == 'put_away'


def test_gen_number_fallback(monkeypatch, db):
    import services.inbound_shipment_service as mod
    monkeypatch.setattr(mod, 'generate_number', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('x')))
    from services.inbound_shipment_service import InboundShipmentService as Svc
    wh = _warehouse(db, 'WH-INB2F')
    p = _product(db, 'P-INB2F', 'SKU-INB2F')
    s = Svc.create_shipment(warehouse_id=wh.id,
                            lines_data=[{'product_id': p.id, 'quantity_expected': 1}])
    assert s.shipment_number.startswith('INB-')
