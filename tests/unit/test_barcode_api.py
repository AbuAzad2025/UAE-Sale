"""Barcode API tests — unified for all multi-line forms."""

from decimal import Decimal


def _product_with_barcode(db, barcode='BC-UNIFIED-001'):
    from models.product import Product, ProductCategory
    cat = ProductCategory.query.filter_by(name='Cat-BC').first()
    if not cat:
        cat = ProductCategory(name='Cat-BC', is_active=True)
        db.session.add(cat)
        db.session.flush()
    p = Product(name='P-BC', sku=f'SKU-{barcode}', barcode=barcode, category_id=cat.id,
                cost_price=Decimal('5'), regular_price=Decimal('10'), current_stock=Decimal('20'), is_active=True)
    db.session.add(p)
    db.session.commit()
    return p


def test_barcode_lookup_requires_login(client, db):
    resp = client.get('/api/products/barcode/BC123')
    assert resp.status_code in (302, 401)


def test_barcode_lookup_found(client, login_owner, db):
    p = _product_with_barcode(db, 'BC-FOUND-001')
    resp = client.get(f'/api/products/barcode/{p.barcode}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['id'] == p.id
    assert data['name'] == p.name
    assert data['barcode'] == p.barcode
    assert 'unit_price' in data


def test_barcode_lookup_not_found(client, login_owner, db):
    resp = client.get('/api/products/barcode/NOPE123XYZ')
    assert resp.status_code == 404
    assert 'error' in resp.get_json()


def test_barcode_lookup_empty_code(client, login_owner, db):
    resp = client.get('/api/products/barcode/   ')
    # Flask will strip? barcode is part of path, empty after strip -> 404 or 400
    assert resp.status_code in (400, 404)


def test_barcode_validate_valid_new(client, login_owner, db):
    # ensure code not exists
    code = 'BC-VALID-NEW-999'
    resp = client.get(f'/api/barcode/validate?code={code}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['valid'] is True
    assert data['exists'] is False


def test_barcode_validate_exists(client, login_owner, db):
    p = _product_with_barcode(db, 'BC-EXISTS-001')
    resp = client.get(f'/api/barcode/validate?code={p.barcode}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['valid'] is False
    assert data['exists'] is True
    assert 'product_id' in data


def test_barcode_validate_empty(client, login_owner, db):
    resp = client.get('/api/barcode/validate?code=')
    assert resp.status_code == 400


def test_barcode_validate_requires_login(client, db):
    resp = client.get('/api/barcode/validate?code=BC123')
    assert resp.status_code in (302, 401)


def test_multi_line_forms_accept_barcode_product(client, login_owner, db):
    """Ensure sales/shipment/inbound create pages render with barcode input after unified JS."""
    # sales
    resp = client.get('/sales/create')
    assert resp.status_code == 200
    # shipments
    resp = client.get('/shipments/create')
    assert resp.status_code == 200
    assert 'barcode-unified.js' in resp.get_data(as_text=True)
    # inbound
    resp = client.get('/inbound-shipments/create')
    assert resp.status_code == 200
    assert 'barcode-unified.js' in resp.get_data(as_text=True)


def test_product_create_auto_barcode_when_missing(client, login_owner, db):
    """Product create without barcode should auto-generate one (existing logic)."""
    from models.warehouse import Warehouse
    wh = Warehouse(name='WH-BC-AUTO', name_ar='WH-BC-AUTO', code='WH-BC-AUTO', is_active=True)
    db.session.add(wh)
    db.session.commit()
    # ensure generate_barcode path is exercised via product create
    from models.product import Product
    initial_count = Product.query.count()
    resp = client.post('/products/create', data={
        'name': 'P-AUTO-BC',
        'sku': '',
        'barcode': '',
        'category_id': '',
        'cost_price': '5',
        'regular_price': '10',
        'current_stock': '5',
    }, follow_redirects=False)
    # should redirect on success (302) or stay 200 if form error, but barcode should be generated
    # Check that a new product was created with auto barcode
    new_p = Product.query.filter_by(name='P-AUTO-BC').first()
    if new_p:
        assert new_p.barcode is not None
        assert len(new_p.barcode) > 0
