"""HTTP integration tests for inventory routes: /products/*, /warehouse/*, /suppliers/*."""
from decimal import Decimal

from extensions import db
from models import (
    Payment,
    Product,
    ProductCategory,
    Purchase,
    StockMovement,
    Supplier,
    Warehouse,
)


def _make_warehouse(name='Main Warehouse', code='WH-MAIN-01', is_main=True):
    wh = Warehouse(
        name=name, name_ar=name, code=code, location='Dubai',
        is_active=True, is_main=is_main,
    )
    db.session.add(wh)
    db.session.commit()
    return wh


def _product_form(warehouse_id, **over):
    data = {
        'name': 'فلتر زيت أصلي',
        'name_ar': 'فلتر زيت',
        'sku': 'SKU-INV-001',
        'part_number': 'PN-INV-1',
        'barcode': 'BC-INV-001',
        'regular_price': '120.500',
        'merchant_price': '100',
        'partner_price': '10',
        'cost_price': '50.000',
        'current_stock': '25',
        'min_stock_alert': '5',
        'unit': 'piece',
        'location': 'A-12',
        'description': 'وصف المنتج',
        'notes': 'ملاحظات',
        'warehouse_id': str(warehouse_id),
    }
    data.update(over)
    return data


def _edit_form(product, warehouse_id, **over):
    data = {
        'name': product.name,
        'name_ar': product.name_ar or '',
        'sku': product.sku or '',
        'part_number': product.part_number or '',
        'barcode': product.barcode or '',
        'category_id': str(product.category_id or 0),
        'regular_price': '150',
        'cost_price': '60',
        'min_stock_alert': '10',
        'current_stock': '130',
        'warehouse_id': str(warehouse_id),
    }
    data.update(over)
    return data


def _supplier_form(**over):
    data = {
        'name': 'Gulf Auto Parts',
        'name_en': 'Gulf Auto Parts Trading',
        'company_name': 'Gulf Auto Parts LLC',
        'phone': '+971509876543',
        'phone2': '+971501112233',
        'email': 'sales@gulfparts.ae',
        'website': 'https://gulfparts.ae',
        'address': 'Industrial Area 5',
        'city': 'Sharjah',
        'country': 'UAE',
        'tax_number': 'TRN-100200300',
        'commercial_registration': 'CR-778899',
        'supplier_type': 'parts',
        'rating': '4',
        'credit_limit': '25000.500',
        'payment_terms_days': '45',
        'preferred_currency': 'AED',
        'initial_balance': '1500',
        'tags': 'parts,oil',
        'notes': 'مورد موثوق',
        'is_verified': 'on',
    }
    data.update(over)
    return data


class TestProductsPages:
    def test_requires_login(self, client):
        resp = client.get('/products/', follow_redirects=False)
        assert resp.status_code == 302

    def test_index_renders_and_filters(self, client, login_owner, test_product):
        resp = client.get('/products/')
        assert resp.status_code == 200
        assert b'Test Brake Pad' in resp.data
        assert b'SKU-TEST-001' in resp.data

        resp = client.get('/products/?search=Brake')
        assert resp.status_code == 200
        assert b'SKU-TEST-001' in resp.data

        resp = client.get(f'/products/?category={test_product.category_id}&per_page=5&page=1')
        assert resp.status_code == 200

        resp = client.get('/products/?stock=low')
        assert resp.status_code == 200

        ghost = Product(
            name='Ghost Item', sku='SKU-GHOST-9', regular_price=Decimal('10'),
            current_stock=Decimal('0'), min_stock_alert=Decimal('2'), is_active=True,
        )
        db.session.add(ghost)
        db.session.commit()

        resp = client.get('/products/?stock=out')
        assert resp.status_code == 200
        assert b'Ghost Item' in resp.data

    def test_create_get_renders(self, client, login_owner, test_category):
        resp = client.get('/products/create')
        assert resp.status_code == 200

    def test_view_detail_and_bogus_404(self, client, login_owner, test_product):
        resp = client.get(f'/products/{test_product.id}')
        assert resp.status_code == 200
        assert b'Test Brake Pad' in resp.data
        assert client.get('/products/999999').status_code == 404


class TestProductsCreate:
    def test_post_persists_with_prices_and_initial_movement(self, client, login_owner, db, test_category):
        wh = _make_warehouse()
        resp = client.post(
            '/products/create',
            data=_product_form(wh.id, category_id=str(test_category.id)),
            follow_redirects=False,
        )
        assert resp.status_code == 302

        product = Product.query.filter_by(sku='SKU-INV-001').one()
        assert product.name_ar == 'فلتر زيت'
        assert product.regular_price == Decimal('120.5')
        assert product.cost_price == Decimal('50')
        assert product.current_stock == Decimal('25')
        assert product.category_id == test_category.id
        assert product.barcode == 'BC-INV-001'

        movement = StockMovement.query.filter_by(product_id=product.id).one()
        assert movement.movement_type == 'adjustment'
        assert movement.quantity == Decimal('25')
        assert movement.warehouse_id == wh.id
        assert movement.reference_type == 'Product Creation'

    def test_post_without_warehouse_rejected(self, client, login_owner, db):
        form = _product_form(None)
        del form['warehouse_id']
        resp = client.post('/products/create', data=form)
        assert resp.status_code == 200
        assert Product.query.filter_by(sku='SKU-INV-001').count() == 0

    def test_post_with_bogus_warehouse_rejected(self, client, login_owner, db):
        resp = client.post('/products/create', data=_product_form(999999))
        assert resp.status_code == 200
        assert Product.query.filter_by(sku='SKU-INV-001').count() == 0

    def test_auto_sku_and_barcode_when_missing(self, client, login_owner, db):
        wh = _make_warehouse()
        form = _product_form(wh.id, sku='', barcode='')
        resp = client.post('/products/create', data=form, follow_redirects=False)
        assert resp.status_code == 302
        product = Product.query.filter_by(name_ar='فلتر زيت').one()
        assert product.sku
        assert product.sku.startswith('SKU-')
        assert product.barcode


class TestProductsEditDelete:
    def test_price_change_persists_with_movement(self, client, login_owner, db, test_product):
        wh = _make_warehouse()
        resp = client.post(
            f'/products/{test_product.id}/edit',
            data=_edit_form(test_product, wh.id),
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/products/{test_product.id}')

        db.session.expire_all()
        product = db.session.get(Product, test_product.id)
        assert product.regular_price == Decimal('150')
        assert product.cost_price == Decimal('60')
        assert product.current_stock == Decimal('130')

        movement = StockMovement.query.filter_by(
            product_id=product.id, reference_type='Product Update'
        ).one()
        assert movement.quantity == Decimal('30')

    def test_negative_stock_blocked(self, client, login_owner, db, test_product):
        wh = _make_warehouse()
        before = StockMovement.query.count()
        resp = client.post(
            f'/products/{test_product.id}/edit',
            data=_edit_form(test_product, wh.id, current_stock='-3'),
        )
        assert resp.status_code == 200
        db.session.expire_all()
        assert db.session.get(Product, test_product.id).current_stock == Decimal('100')
        assert StockMovement.query.count() == before

    def test_delete_soft_deactivates_when_sales_exist(self, client, login_owner, db, test_product, test_sale):
        resp = client.post(f'/products/{test_product.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        db.session.expire_all()
        product = db.session.get(Product, test_product.id)
        assert product is not None
        assert product.is_active is False

    def test_delete_hard_removes_row(self, client, login_owner, db, test_product):
        pid = test_product.id
        resp = client.post(f'/products/{pid}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert db.session.get(Product, pid) is None
        assert client.get(f'/products/{pid}').status_code == 404


class TestProductsAdjustStock:
    def test_add_increases_stock_and_writes_movement(self, client, login_owner, db, owner_user, test_product):
        _make_warehouse()
        resp = client.post(f'/products/{test_product.id}/adjust-stock', data={
            'adjustment_type': 'add', 'quantity': '7.5', 'reason': 'جرد', 'notes': 'تسوية جرد',
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True, body
        assert body['new_stock'] == 107.5

        db.session.expire_all()
        assert db.session.get(Product, test_product.id).current_stock == Decimal('107.5')
        movement = StockMovement.query.filter_by(product_id=test_product.id).one()
        assert movement.movement_type == 'adjustment'
        assert movement.quantity == Decimal('7.5')
        assert movement.user_id == owner_user.id

    def test_set_rewrites_stock(self, client, login_owner, db, test_product):
        _make_warehouse()
        resp = client.post(f'/products/{test_product.id}/adjust-stock', data={
            'adjustment_type': 'set', 'quantity': '42',
        })
        body = resp.get_json()
        assert body['success'] is True
        assert body['new_stock'] == 42.0
        db.session.expire_all()
        assert db.session.get(Product, test_product.id).current_stock == Decimal('42')
        movement = StockMovement.query.filter_by(product_id=test_product.id).one()
        assert movement.quantity == Decimal('-58')

    def test_subtract_below_zero_rejected(self, client, login_owner, db, test_product):
        _make_warehouse()
        resp = client.post(f'/products/{test_product.id}/adjust-stock', data={
            'adjustment_type': 'subtract', 'quantity': '999',
        })
        body = resp.get_json()
        assert body['success'] is False
        db.session.expire_all()
        assert db.session.get(Product, test_product.id).current_stock == Decimal('100')
        assert StockMovement.query.filter_by(product_id=test_product.id).count() == 0

    def test_invalid_type_and_zero_quantity_rejected(self, client, login_owner, db, test_product):
        _make_warehouse()
        bad_type = client.post(f'/products/{test_product.id}/adjust-stock', data={
            'adjustment_type': 'bogus', 'quantity': '5',
        }).get_json()
        assert bad_type['success'] is False

        zero_qty = client.post(f'/products/{test_product.id}/adjust-stock', data={
            'adjustment_type': 'add', 'quantity': '0',
        }).get_json()
        assert zero_qty['success'] is False
        db.session.expire_all()
        assert db.session.get(Product, test_product.id).current_stock == Decimal('100')
        assert StockMovement.query.filter_by(product_id=test_product.id).count() == 0


class TestProductsApiAndCategories:
    def test_api_search_matches_name_sku(self, client, login_owner, test_product):
        resp = client.get('/products/api/search?q=Brake')
        assert resp.status_code == 200
        results = resp.get_json()
        assert any(r['id'] == test_product.id for r in results)
        hit = next(r for r in results if r['id'] == test_product.id)
        assert hit['price'] == 100.0
        assert hit['stock'] == 100.0
        assert hit['text'].startswith('Test Brake Pad')

    def test_api_search_excludes_inactive_and_empty_q_returns_active(self, client, login_owner, db, test_product):
        inactive = Product(
            name='Hidden Oil Filter', sku='SKU-HIDDEN-1', regular_price=Decimal('20'),
            current_stock=Decimal('3'), is_active=False,
        )
        db.session.add(inactive)
        db.session.commit()

        assert client.get('/products/api/search?q=Hidden').get_json() == []

        results = client.get('/products/api/search').get_json()
        ids = [r['id'] for r in results]
        assert test_product.id in ids
        assert inactive.id not in ids

    def test_categories_page_lists_rows(self, client, login_owner, test_category):
        resp = client.get('/products/categories')
        assert resp.status_code == 200
        assert b'Spare Parts' in resp.data

    def test_category_create_json_persists(self, client, login_owner, db):
        resp = client.post('/products/categories/create', json={'name': 'Electronics'})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert ProductCategory.query.filter_by(name='Electronics').one().id == body['category']['id']

    def test_category_duplicate_and_empty_rejected(self, client, login_owner, db):
        resp = client.post('/products/categories/create', data={'name': 'Suspension'},
                           follow_redirects=False)
        assert resp.status_code == 302

        dup = client.post('/products/categories/create', data={'name': 'suspension'},
                          follow_redirects=False)
        assert dup.status_code == 302
        assert ProductCategory.query.filter_by(name='Suspension').count() == 1

        empty = client.post('/products/categories/create', data={}, follow_redirects=False)
        assert empty.status_code == 302
        assert ProductCategory.query.count() == 1


class TestWarehousePages:
    def test_index_movements_list_low_out_render(self, client, login_owner, db, test_product):
        wh = _make_warehouse()
        db.session.add(StockMovement(
            product_id=test_product.id, warehouse_id=wh.id,
            movement_type='purchase', quantity=Decimal('40'),
        ))
        db.session.commit()

        assert client.get('/warehouse/').status_code == 200
        resp = client.get(f"/warehouse/movements?type=purchase&warehouse={wh.id}")
        assert resp.status_code == 200
        assert client.get('/warehouse/movements').status_code == 200
        assert client.get('/warehouse/list').status_code == 200
        assert client.get('/warehouse/low-stock').status_code == 200
        assert client.get('/warehouse/out-of-stock').status_code == 200

    def test_low_and_out_of_stock_list_correct_products(self, client, login_owner, db, test_category):
        low = Product(
            name='LowStock Widget', sku='SKU-LOW-1', category_id=test_category.id,
            regular_price=Decimal('30'), cost_price=Decimal('15'),
            current_stock=Decimal('5'), min_stock_alert=Decimal('10'), is_active=True,
        )
        out = Product(
            name='OutOfStock Gadget', sku='SKU-OUT-1', category_id=test_category.id,
            regular_price=Decimal('80'), cost_price=Decimal('40'),
            current_stock=Decimal('0'), min_stock_alert=Decimal('2'), is_active=True,
        )
        db.session.add_all([low, out])
        db.session.commit()

        resp = client.get('/warehouse/low-stock')
        assert resp.status_code == 200
        assert b'LowStock Widget' in resp.data
        assert b'OutOfStock Gadget' in resp.data

        resp = client.get('/warehouse/out-of-stock')
        assert resp.status_code == 200
        assert b'OutOfStock Gadget' in resp.data
        assert b'LowStock Widget' not in resp.data

    def test_view_warehouse_and_bogus_404(self, client, login_owner, db, test_product):
        wh1 = _make_warehouse(name='Al Ain Depot', code='WH-AIN-01')
        wh2 = _make_warehouse(name='Fujairah Depot', code='WH-FUJ-01', is_main=False)
        db.session.add_all([
            StockMovement(product_id=test_product.id, warehouse_id=wh1.id,
                          movement_type='purchase', quantity=Decimal('40')),
            StockMovement(product_id=test_product.id, warehouse_id=wh2.id,
                          movement_type='purchase', quantity=Decimal('15')),
        ])
        db.session.commit()

        resp = client.get(f'/warehouse/{wh1.id}')
        assert resp.status_code == 200
        assert client.get('/warehouse/888888').status_code == 404


class TestWarehouseCrud:
    def test_get_create_page(self, client, login_owner):
        assert client.get('/warehouse/create').status_code == 200

    def test_post_creates_warehouse(self, client, login_owner, db):
        resp = client.post('/warehouse/create', data={
            'name': 'Ajman Store', 'name_ar': 'مستودع عجمان',
            'code': 'WH-AJM-01', 'location': 'Ajman Industrial',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert '/warehouse/list' in resp.headers['Location']

        wh = Warehouse.query.filter_by(code='WH-AJM-01').one()
        assert wh.is_active is True
        assert wh.is_main is False
        assert wh.name_ar == 'مستودع عجمان'

    def test_post_child_with_parent(self, client, login_owner, db):
        parent = _make_warehouse()
        resp = client.post('/warehouse/create', data={
            'name': 'Child Branch', 'location': 'Dubai Marina',
            'parent_id': str(parent.id),
        }, follow_redirects=False)
        assert resp.status_code == 302
        child = Warehouse.query.filter_by(name='Child Branch').one()
        assert child.parent_id == parent.id

    def test_post_missing_name_or_location_rejected(self, client, login_owner, db):
        resp = client.post('/warehouse/create', data={'name': '', 'location': 'Somewhere'})
        assert resp.status_code == 200
        resp = client.post('/warehouse/create', data={'name': 'No Location', 'location': ''})
        assert resp.status_code == 200
        assert Warehouse.query.filter_by(name='No Location').count() == 0
        assert Warehouse.query.count() == 0

    def test_post_duplicate_code_rejected(self, client, login_owner, db):
        _make_warehouse(code='WH-DUP-01')
        resp = client.post('/warehouse/create', data={
            'name': 'Second Try', 'location': 'RAK', 'code': 'WH-DUP-01',
        })
        assert resp.status_code == 200
        assert Warehouse.query.filter_by(code='WH-DUP-01').count() == 1

    def test_delete_main_blocked(self, client, login_owner, db):
        wh = _make_warehouse(is_main=True)
        resp = client.post(f'/warehouse/{wh.id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        db.session.expire_all()
        assert db.session.get(Warehouse, wh.id).is_active is True

    def test_delete_soft_when_movements_exist(self, client, login_owner, db, test_product):
        wh = _make_warehouse(name='Side WH', code='WH-SIDE-01', is_main=False)
        db.session.add(StockMovement(
            product_id=test_product.id, warehouse_id=wh.id,
            movement_type='purchase', quantity=Decimal('3'),
        ))
        db.session.commit()

        resp = client.post(f'/warehouse/{wh.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        db.session.expire_all()
        soft_deleted = db.session.get(Warehouse, wh.id)
        assert soft_deleted is not None
        assert soft_deleted.is_active is False

    def test_delete_hard_when_no_movements(self, client, login_owner, db):
        wh = _make_warehouse(name='Temp WH', code='WH-TMP-01', is_main=False)
        resp = client.post(f'/warehouse/{wh.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert db.session.get(Warehouse, wh.id) is None


class TestWarehouseAddStock:
    def test_add_updates_product_and_writes_movement(self, client, login_owner, db, owner_user, test_product):
        other = _make_warehouse(name='Other WH', code='WH-OTHER-01', is_main=False)
        resp = client.post(f'/warehouse/add-stock/{test_product.id}', data={
            'quantity': '12.5', 'notes': 'استلام يدوي', 'warehouse_id': str(other.id),
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['new_stock'] == 112.5

        db.session.expire_all()
        assert db.session.get(Product, test_product.id).current_stock == Decimal('112.5')
        movement = StockMovement.query.filter_by(product_id=test_product.id).one()
        assert movement.warehouse_id == other.id
        assert movement.quantity == Decimal('12.5')
        assert movement.user_id == owner_user.id
        assert movement.notes == 'استلام يدوي'

    def test_add_without_warehouse_falls_back_to_main(self, client, login_owner, db, test_product):
        main = _make_warehouse(is_main=True)
        _make_warehouse(name='Branch WH', code='WH-BR-01', is_main=False)

        resp = client.post(f'/warehouse/add-stock/{test_product.id}', data={'quantity': '6'})
        assert resp.get_json()['success'] is True
        db.session.expire_all()
        movement = StockMovement.query.filter_by(product_id=test_product.id).one()
        assert movement.warehouse_id == main.id
        assert movement.notes == 'إضافة كمية يدوية'

    def test_add_zero_quantity_400_no_changes(self, client, login_owner, db, test_product):
        _make_warehouse()
        resp = client.post(f'/warehouse/add-stock/{test_product.id}', data={'quantity': '0'})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False
        db.session.expire_all()
        assert db.session.get(Product, test_product.id).current_stock == Decimal('100')
        assert StockMovement.query.count() == 0


class TestSuppliersCrud:
    def test_list_renders_and_filters(self, client, login_owner, db):
        s1 = Supplier(name='Alpha Trading', phone='+971501110001',
                      supplier_type='parts', is_active=True)
        s2 = Supplier(name='Beta Equipment', phone='+971501110002',
                      supplier_type='equipment', is_active=True)
        db.session.add_all([s1, s2])
        db.session.commit()

        resp = client.get('/suppliers/')
        assert resp.status_code == 200
        assert b'Alpha Trading' in resp.data

        assert client.get('/suppliers/?search=971501110002').status_code == 200
        assert client.get('/suppliers/?type=equipment').status_code == 200

    def test_requires_login(self, client):
        assert client.get('/suppliers/', follow_redirects=False).status_code == 302

    def test_create_persists_supplier(self, client, login_owner, db, owner_user):
        resp = client.post('/suppliers/create', data=_supplier_form(), follow_redirects=False)
        assert resp.status_code == 302

        supplier = Supplier.query.filter_by(phone='+971509876543').one()
        assert supplier.name == 'Gulf Auto Parts'
        assert supplier.supplier_type == 'parts'
        assert supplier.rating == 4
        assert supplier.credit_limit == Decimal('25000.5')
        assert supplier.total_purchases_aed == Decimal('1500')
        assert supplier.total_paid_aed == Decimal('0')
        assert supplier.is_verified is True
        assert supplier.created_by == owner_user.id
        assert resp.headers['Location'].endswith(f'/suppliers/{supplier.id}')

    def test_create_missing_type_rerenders_without_row(self, client, login_owner, db):
        resp = client.post('/suppliers/create', data=_supplier_form(supplier_type=''))
        assert resp.status_code == 200
        assert Supplier.query.count() == 0

    def test_view_shows_supplier(self, client, login_owner, db):
        supplier = Supplier(name='View Target', phone='+971503330001',
                            total_purchases_aed=Decimal('1500'), total_paid_aed=Decimal('500'))
        db.session.add(supplier)
        db.session.commit()

        resp = client.get(f'/suppliers/{supplier.id}')
        assert resp.status_code == 200
        assert supplier.get_balance_aed() == Decimal('1000')

    def test_edit_persists_changes(self, client, login_owner, db):
        supplier = Supplier(name='Editable Supplier', phone='+971504440001',
                            supplier_type='parts', is_verified=True)
        db.session.add(supplier)
        db.session.commit()

        resp = client.post(f'/suppliers/{supplier.id}/edit', data={
            'name': 'Edited Supplier', 'company_name': 'Edited LLC',
            'phone': '+971555000111', 'city': 'Abu Dhabi', 'country': 'UAE',
            'supplier_type': 'equipment', 'rating': '',
            'credit_limit': '', 'payment_terms_days': '15',
            'preferred_currency': 'USD', 'notes': 'updated',
        }, follow_redirects=False)
        assert resp.status_code == 302

        db.session.expire_all()
        fresh = db.session.get(Supplier, supplier.id)
        assert fresh.phone == '+971555000111'
        assert fresh.city == 'Abu Dhabi'
        assert fresh.supplier_type == 'equipment'
        assert fresh.rating is None
        assert fresh.payment_terms_days == 15
        assert fresh.preferred_currency == 'USD'
        assert fresh.is_verified is False

    def test_statement_renders_purchases_and_payments(self, client, login_owner, db, owner_user):
        supplier = Supplier(name='Statement Supplier', phone='+971506660001')
        db.session.add(supplier)
        db.session.flush()
        db.session.add(Purchase(
            purchase_number='PO-INV-STMT-1', supplier_id=supplier.id,
            supplier_name=supplier.name, total_amount=Decimal('900'),
            currency='AED', exchange_rate=Decimal('1'), amount_base=Decimal('900'),
            status='confirmed', user_id=owner_user.id,
        ))
        db.session.add(Payment(
            payment_number='PAY-INV-STMT-1', payment_type='supplier',
            supplier_id=supplier.id, amount=Decimal('300'),
            currency='AED', amount_base=Decimal('300'),
            payment_method='cash', user_id=owner_user.id,
        ))
        db.session.commit()

        resp = client.get(f'/suppliers/{supplier.id}/statement')
        assert resp.status_code == 200

    def test_delete_soft_when_purchase_exists(self, client, login_owner, db, owner_user):
        supplier = Supplier(name='Purchased From', phone='+971507770001')
        db.session.add(supplier)
        db.session.flush()
        db.session.add(Purchase(
            purchase_number='PO-INV-DEL-1', supplier_id=supplier.id,
            supplier_name=supplier.name, total_amount=Decimal('100'),
            currency='AED', exchange_rate=Decimal('1'), amount_base=Decimal('100'),
            status='confirmed', user_id=owner_user.id,
        ))
        db.session.commit()

        resp = client.post(f'/suppliers/{supplier.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        db.session.expire_all()
        kept = db.session.get(Supplier, supplier.id)
        assert kept is not None
        assert kept.is_active is False

    def test_delete_hard_removes_row(self, client, login_owner, db):
        supplier = Supplier(name='Disposable Supplier', phone='+971508880001')
        db.session.add(supplier)
        db.session.commit()

        resp = client.post(f'/suppliers/{supplier.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert db.session.get(Supplier, supplier.id) is None


class TestSuppliersApiAndPermissions:
    def test_api_search_by_phone_and_balance(self, client, login_owner, db):
        # Q-remediation: /suppliers/api/search now requires login + manage_suppliers
        supplier = Supplier(name='Api Search Co', phone='+971509876599',
                            total_purchases_aed=Decimal('1500'), total_paid_aed=Decimal('500'))
        db.session.add(supplier)
        db.session.commit()

        resp = client.get('/suppliers/api/search?q=97150987659')
        assert resp.status_code == 200
        results = resp.get_json()
        hit = next(r for r in results if r['id'] == supplier.id)
        assert hit['balance'] == 1000.0
        assert hit['text'].startswith('Api Search Co')

        all_results = client.get('/suppliers/api/search').get_json()
        assert supplier.id in [r['id'] for r in all_results]

    def test_seller_forbidden_on_warehouse_and_suppliers(self, client, login_seller):
        assert client.get('/products/').status_code == 200
        assert client.get('/warehouse/').status_code == 403
        assert client.get('/suppliers/').status_code == 403
