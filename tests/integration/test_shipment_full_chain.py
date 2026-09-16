"""Full shipment chain — إرسالية → بيع → دفع → إيصال → فاتورة (end-to-end)."""

from decimal import Decimal


def _warehouse(db, name):
    from models.warehouse import Warehouse
    w = Warehouse(name=name, name_ar=name, code=name, is_active=True)
    db.session.add(w)
    db.session.commit()
    return w


def _product(db, name, sku, price=Decimal('10'), cost=Decimal('5')):
    from models.product import Product, ProductCategory
    cat = ProductCategory.query.filter_by(name='Cat-CHAIN').first()
    if not cat:
        cat = ProductCategory(name='Cat-CHAIN', is_active=True)
        db.session.add(cat)
        db.session.flush()
    p = Product(name=name, sku=sku, category_id=cat.id, cost_price=cost, regular_price=price, current_stock=Decimal('100'), is_active=True)
    db.session.add(p)
    db.session.commit()
    return p


def test_shipment_full_chain_sale_payment_invoice(client, login_owner, db):
    """Outbound shipment → sale → payment → receipt → invoice visibility."""
    from services.shipment_service import ShipmentService
    from models.customer import Customer
    from models.sale import Sale
    from models.payment import Payment
    from models.user import User
    wh = _warehouse(db, 'WH-CHAIN')
    p = _product(db, 'P-CHAIN', 'SKU-CHAIN-001')
    # 1. Create shipment
    s = ShipmentService.create_shipment(from_warehouse_id=wh.id, destination_name='موقع اختبار الشامل', lines_data=[{'product_id': p.id, 'quantity': 5, 'unit_cost': 5, 'unit_price': 10}])
    assert s.status == 'draft'
    # 2. Workflow to selling
    ShipmentService.send_shipment(s.id)
    ShipmentService.arrive_shipment(s.id)
    ShipmentService.start_selling(s.id)
    db.session.refresh(s)
    assert s.status == 'selling'
    # 3. Create sale linked to shipment
    cust = Customer(name='C-CHAIN', customer_type='regular', is_active=True)
    db.session.add(cust)
    db.session.flush()
    seller = User.query.filter_by(is_owner=True).first()
    sale = Sale(sale_number=f'S-CHAIN-{s.id}', customer_id=cust.id, seller_id=seller.id, warehouse_id=wh.id, shipment_id=s.id,
                total_amount=Decimal('50'), amount_base=Decimal('50'), paid_amount=Decimal('0'), paid_amount_base=Decimal('0'), balance_due=Decimal('50'), currency='AED', exchange_rate=Decimal('1'), payment_status='unpaid', status='confirmed', is_active=True)
    db.session.add(sale)
    db.session.commit()
    assert sale.shipment_id == s.id
    # 4. Create payment (receipt) for sale
    pay = Payment(payment_number=f'PAY-CHAIN-{s.id}', payment_type='sale_payment', direction='incoming', sale_id=sale.id, customer_id=cust.id, amount=Decimal('50'), amount_base=Decimal('50'), payment_method='cash', currency='AED', exchange_rate=Decimal('1'))
    db.session.add(pay)
    db.session.commit()
    assert pay.sale_id == sale.id
    # 5. Close shipment after sale paid
    ShipmentService.close_shipment(s.id)
    db.session.refresh(s)
    assert s.status == 'closed'
    # 6. Verify view shows linked sale
    html = client.get(f'/shipments/{s.id}').get_data(as_text=True)
    assert s.shipment_number in html
    assert sale.sale_number in html


def test_inbound_full_chain_putaway_updates_stock_and_po(client, login_owner, db):
    """Inbound shipment → put_away → stock + PO status."""
    from services.inbound_shipment_service import InboundShipmentService
    from models.supplier import Supplier
    from models.erp_modules import PurchaseOrder
    from models.warehouse import Warehouse
    from decimal import Decimal as D
    wh = _warehouse(db, 'WH-INB-CHAIN2')
    p = _product(db, 'P-INB-CHAIN2', 'SKU-INB-CHAIN2', price=D('20'), cost=D('10'))
    supplier = Supplier(name='Sup-CHAIN', is_active=True)
    db.session.add(supplier)
    db.session.commit()
    # Create PO
    from services.erp_modules_service import PurchaseOrderService
    po = PurchaseOrderService.create_po(supplier_id=supplier.id, warehouse_id=wh.id, lines_data=[{'product_id': p.id, 'quantity': 10, 'unit_cost': 10}], user_id=1)
    assert po.status in ('draft', 'submitted', 'approved')
    # Create inbound linked to PO
    s = InboundShipmentService.create_shipment(warehouse_id=wh.id, supplier_id=supplier.id, purchase_order_id=po.id, lines_data=[{'product_id': p.id, 'quantity_expected': 10, 'unit_cost': 10}])
    assert s.status == 'in_transit'
    before_stock = p.current_stock
    InboundShipmentService.arrive(s.id)
    InboundShipmentService.inspect_shipment(s.id)
    InboundShipmentService.put_away(s.id)
    db.session.refresh(p)
    assert p.current_stock == before_stock + D('10')
    db.session.refresh(po)
    assert po.status in ('received', 'partially_received')
    InboundShipmentService.close(s.id)
    assert s.status == 'closed'
