"""Shipment routes — permission and workflow."""

from models.shipment import Shipment


def _warehouse(db, name='WH-R'):
    from models.warehouse import Warehouse
    w = Warehouse(name=name, name_ar=name, code=name, is_active=True)
    db.session.add(w)
    db.session.commit()
    return w


def test_shipments_list_requires_login(client, db):
    assert client.get('/shipments').status_code in (302, 401)


def test_owner_can_list_and_create(client, login_owner, db):
    wh = _warehouse(db, 'WH-LIST')
    # create via service to have data
    from services.shipment_service import ShipmentService
    from models.product import Product, ProductCategory
    from decimal import Decimal
    cat = ProductCategory(name='Cat-R', is_active=True)
    db.session.add(cat)
    db.session.flush()
    p = Product(name='P-R', sku='SKU-R', category_id=cat.id, cost_price=Decimal('5'), regular_price=Decimal('10'), current_stock=Decimal('10'), is_active=True)
    db.session.add(p)
    db.session.commit()
    ShipmentService.create_shipment(from_warehouse_id=wh.id, destination_name='موقع الاختبار', lines_data=[{'product_id': p.id, 'quantity': 1}])
    resp = client.get('/shipments')
    assert resp.status_code == 200
    assert 'الإرساليات' in resp.get_data(as_text=True)
    # create page
    assert client.get('/shipments/create').status_code == 200


def test_shipment_workflow_via_routes(client, login_owner, db):
    wh = _warehouse(db, 'WH-FLOW')
    from models.product import Product, ProductCategory
    from decimal import Decimal
    cat = ProductCategory(name='Cat-F', is_active=True)
    db.session.add(cat)
    db.session.flush()
    p = Product(name='P-F', sku='SKU-F', category_id=cat.id, cost_price=Decimal('5'), regular_price=Decimal('10'), current_stock=Decimal('10'), is_active=True)
    db.session.add(p)
    db.session.commit()
    from services.shipment_service import ShipmentService
    s = ShipmentService.create_shipment(from_warehouse_id=wh.id, destination_name='موقع الطائف', lines_data=[{'product_id': p.id, 'quantity': 2}])
    # send
    assert client.post(f'/shipments/{s.id}/send').status_code == 302
    db.session.refresh(s)
    assert s.status == 'in_transit'
    # arrive
    assert client.post(f'/shipments/{s.id}/arrive').status_code == 302
    db.session.refresh(s)
    assert s.status == 'arrived'
    # start selling
    assert client.post(f'/shipments/{s.id}/start-selling').status_code == 302
    db.session.refresh(s)
    assert s.status == 'selling'
    # close
    assert client.post(f'/shipments/{s.id}/close').status_code == 302
    db.session.refresh(s)
    assert s.status == 'closed'
    # view shows sales section (empty but renders)
    html = client.get(f'/shipments/{s.id}').get_data(as_text=True)
    assert s.shipment_number in html


def test_seller_blocked_if_no_permission(client, login_seller, db):
    # seller role in conftest has manage_sales etc but not manage_warehouse
    resp = client.get('/shipments')
    # permission_required should 302/403
    assert resp.status_code in (302, 403)


def test_shipment_sale_link(client, login_owner, db):
    """Sale created with shipment_id is visible on shipment view."""
    from models.product import Product, ProductCategory
    from decimal import Decimal
    wh = _warehouse(db, 'WH-LINK')
    cat = ProductCategory(name='Cat-LINK', is_active=True)
    db.session.add(cat)
    db.session.flush()
    p = Product(name='P-LINK', sku='SKU-LINK', category_id=cat.id, cost_price=Decimal('5'), regular_price=Decimal('10'), current_stock=Decimal('10'), is_active=True)
    db.session.add(p)
    db.session.commit()
    from services.shipment_service import ShipmentService
    s = ShipmentService.create_shipment(from_warehouse_id=wh.id, destination_name='موقع', lines_data=[{'product_id': p.id, 'quantity': 1}])
    # create a sale linked to shipment
    from models.customer import Customer
    from models.sale import Sale
    cust = Customer(name='C-LINK', customer_type='regular', is_active=True)
    db.session.add(cust)
    db.session.flush()
    from models.user import User
    seller = User.query.filter_by(is_owner=True).first()
    sale = Sale(sale_number=f'S-LINK-{s.id}', customer_id=cust.id, seller_id=seller.id, warehouse_id=wh.id, shipment_id=s.id,
                total_amount=Decimal('100'), amount_base=Decimal('100'), paid_amount=Decimal('0'), paid_amount_base=Decimal('0'), balance_due=Decimal('100'), currency='AED', exchange_rate=Decimal('1'), payment_status='unpaid', status='confirmed', is_active=True)
    db.session.add(sale)
    db.session.commit()
    html = client.get(f'/shipments/{s.id}').get_data(as_text=True)
    assert sale.sale_number in html
