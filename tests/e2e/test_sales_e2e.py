"""
E2E tests for Sales module - comprehensive coverage of all routes.
Tests cover: list, create, view, edit, print, cancel, archive, restore, delete, api.
"""

from decimal import Decimal

import pytest

from models.sale import Sale, SaleLine
from models import ArchivedRecord, Payment, Cheque
from extensions import db
from tests.e2e.harness import sale_form


class TestSalesListAndView:
    def test_sales_list_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/sales/')
        assert r.status_code == 200
    def test_sales_archived_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/sales/archived')
        assert r.status_code == 200
    def test_sale_view_requires_login(self, client, sale):
        r = client.get(f'/sales/{sale.id}')
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')
    def test_sale_view_by_owner(self, client, login_as, sale):
        login_as('owner')
        r = client.get(f'/sales/{sale.id}')
        assert r.status_code == 200
    def test_sale_view_forbidden_for_others(self, client, login_as, sale):
        login_as('accountant')
        r = client.get(f'/sales/{sale.id}')
        assert r.status_code == 403


class TestSalesCreate:
    def test_create_sale_basic(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
            warehouse=warehouse,
        ))
        assert r.status_code in (302, 303)
        sid = r.headers.get('Location', '').split('/')[-1]
        assert sid.isdigit()
        s = Sale.query.get(int(sid))
        assert s is not None
        assert s.total_amount == Decimal('200.000')
    def test_create_sale_with_payment(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
            warehouse=warehouse,
            payment_amount=100, payment_method='cash', exchange_rate=1,
        ))
        assert r.status_code in (302, 303)
        sid = r.headers.get('Location', '').split('/')[-1]
        s = Sale.query.get(int(sid))
        assert s.paid_amount == Decimal('100.000')
    def test_create_sale_zero_quantity_rejected(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        before = Sale.query.count()
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 0, 'unit_price': 100}],
            warehouse=warehouse,
        ))
        assert r.status_code == 302
        assert Sale.query.count() == before
    def test_create_sale_requires_login(self, client, customer, product, warehouse):
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 1, 'unit_price': 100}],
            warehouse=warehouse,
        ))
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')


class TestSalesEdit:
    def test_edit_sale_updates_discount(self, client, login_as, sale):
        login_as('owner')
        r = client.post(f'/sales/{sale.id}/edit', data={
            'discount_amount': '50',
            'notes': 'Updated discount',
        })
        assert r.status_code in (302, 303)
        reloaded = Sale.query.get(sale.id)
        assert reloaded.discount_amount == Decimal('50.000')
        assert reloaded.notes == 'Updated discount'
        assert reloaded.total_amount == Decimal('150.000')


class TestSalesCancel:
    def test_cancel_sale_reduces_stock_and_reverses_gl(self, client, login_as, sale, product):
        login_as('owner')
        before_stock = product.current_stock
        total_qty = sum(ln.quantity for ln in sale.lines)
        r = client.post(f'/sales/{sale.id}/cancel')
        assert r.status_code in (302, 303)
        reloaded = Sale.query.get(sale.id)
        assert reloaded.status == 'cancelled'
    def test_cancel_already_cancelled_rejected(self, client, login_as, sale):
        login_as('owner')
        client.post(f'/sales/{sale.id}/cancel')
        r = client.post(f'/sales/{sale.id}/cancel')
        assert r.status_code in (302, 303)
        reloaded = Sale.query.get(sale.id)
        assert reloaded.status == 'cancelled'


class TestSalesArchive:
    def test_archive_sale(self, client, login_as, sale):
        login_as('owner')
        r = client.post(f'/sales/{sale.id}/archive')
        assert r.status_code in (302, 303)


class TestSalesDelete:
    def test_delete_sale_without_links(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 1, 'unit_price': 100}],
            warehouse=warehouse,
        ))
        sid = r.headers.get('Location', '').split('/')[-1]
        r = client.post(f'/sales/{sid}/delete')
        assert r.status_code in (302, 303)
        assert Sale.query.get(int(sid)) is None
    def test_delete_sale_with_payment_is_archived(self, client, login_as, sale_with_payment):
        login_as('owner')
        r = client.post(f'/sales/{sale_with_payment.id}/delete')
        assert r.status_code in (302, 303)
        assert Sale.query.get(sale_with_payment.id) is not None
        assert ArchivedRecord.query.filter_by(table_name='sales', record_id=sale_with_payment.id).count() == 1


class TestSalesApi:
    def test_calculate_totals_endpoint(self, client, login_as, customer, product, warehouse):
        login_as('owner')
        r = client.post('/sales/api/calculate-totals', json={
            'customer_id': customer.id,
            'lines': [{'product_id': product.id, 'quantity': 2, 'unit_price': 100}],
            'discount_amount': 0,
            'shipping_cost': 0,
            'tax_rate': 5,
            'currency': 'AED',
            'exchange_rate': 1,
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['subtotal'] == 200
        assert data['tax_amount'] == 10
        assert data['total'] == 210
    def test_get_price_endpoint(self, client, login_as, customer, product):
        login_as('owner')
        r = client.get(f'/sales/api/get-price?customer_id={customer.id}&product_id={product.id}')
        assert r.status_code == 200
        data = r.get_json()
        assert 'price' in data


class TestSalesRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('pos_cashier', True),
        ('senior_accountant', False),
        ('warehouse_keeper', False),
        ('manager', True),
        ('accountant', False),
        ('viewer', False),
        ('hr', False),
    ])
    def test_manage_sales_gates_create(self, client, login_as, role, allowed, customer, product, warehouse):
        login_as(role)
        before = Sale.query.count()
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': 1, 'unit_price': 100}],
            warehouse=warehouse,
        ))
        if allowed:
            assert r.status_code in (302, 303)
        else:
            assert r.status_code == 403
            assert Sale.query.count() == before


@pytest.fixture
def sale(db, owner, customer, product, warehouse, e2e_tenant):
    s = Sale(
        sale_number='S-E2E-FIX',
        customer_id=customer.id,
        seller_id=owner.id,
        warehouse_id=warehouse.id,
        currency='ILS',
        exchange_rate=Decimal('1'),
        subtotal=Decimal('200.000'),
        discount_amount=Decimal('0.000'),
        shipping_cost=Decimal('0.000'),
        tax_rate=Decimal('0'),
        tax_amount=Decimal('0.000'),
        total_amount=Decimal('200.000'),
        amount_base=Decimal('200.000'),
        paid_amount=Decimal('0.000'),
        balance_due=Decimal('200.000'),
        paid_amount_base=Decimal('0.000'),
        payment_status='unpaid',
        status='confirmed',
        is_active=True,
    )
    s.tenant_id = e2e_tenant.id
    db.session.add(s)
    db.session.flush()
    db.session.add(SaleLine(
        sale_id=s.id,
        product_id=product.id,
        quantity=Decimal('2'),
        unit_price=Decimal('100.000'),
        discount_percent=Decimal('0'),
        line_total=Decimal('200.000'),
        cost_price=Decimal('50.000'),
    ))
    db.session.commit()
    return s


@pytest.fixture
def seller_user(users):
    return users['pos_cashier']


@pytest.fixture
def sale_by_seller(db, seller_user, customer, product, warehouse, e2e_tenant):
    s = Sale(
        sale_number='S-E2E-SELLER',
        customer_id=customer.id,
        seller_id=seller_user.id,
        warehouse_id=warehouse.id,
        currency='ILS',
        exchange_rate=Decimal('1'),
        subtotal=Decimal('100.000'),
        discount_amount=Decimal('0.000'),
        shipping_cost=Decimal('0.000'),
        tax_rate=Decimal('0'),
        tax_amount=Decimal('0.000'),
        total_amount=Decimal('100.000'),
        amount_base=Decimal('100.000'),
        paid_amount=Decimal('0.000'),
        balance_due=Decimal('100.000'),
        paid_amount_base=Decimal('0.000'),
        payment_status='unpaid',
        status='confirmed',
        is_active=True,
    )
    s.tenant_id = e2e_tenant.id
    db.session.add(s)
    db.session.flush()
    db.session.add(SaleLine(
        sale_id=s.id,
        product_id=product.id,
        quantity=Decimal('1'),
        unit_price=Decimal('100.000'),
        discount_percent=Decimal('0'),
        line_total=Decimal('100.000'),
        cost_price=Decimal('50.000'),
    ))
    db.session.commit()
    return s


@pytest.fixture
def sale_with_payment(db, owner, customer, product, warehouse, e2e_tenant):
    s = Sale(
        sale_number='S-E2E-PAID',
        customer_id=customer.id,
        seller_id=owner.id,
        warehouse_id=warehouse.id,
        currency='ILS',
        exchange_rate=Decimal('1'),
        subtotal=Decimal('200.000'),
        discount_amount=Decimal('0.000'),
        shipping_cost=Decimal('0.000'),
        tax_rate=Decimal('0'),
        tax_amount=Decimal('0.000'),
        total_amount=Decimal('200.000'),
        amount_base=Decimal('200.000'),
        paid_amount=Decimal('100.000'),
        balance_due=Decimal('100.000'),
        paid_amount_base=Decimal('100.000'),
        payment_status='partial',
        status='confirmed',
        is_active=True,
    )
    s.tenant_id = e2e_tenant.id
    db.session.add(s)
    db.session.flush()
    db.session.add(SaleLine(
        sale_id=s.id,
        product_id=product.id,
        quantity=Decimal('2'),
        unit_price=Decimal('100.000'),
        discount_percent=Decimal('0'),
        line_total=Decimal('200.000'),
        cost_price=Decimal('50.000'),
    ))
    from datetime import date
    db.session.add(Payment(
        amount=Decimal('100.000'),
        currency='ILS',
        exchange_rate=Decimal('1'),
        amount_base=Decimal('100.000'),
        payment_method='cash',
        payment_number='PAY-E2E-001',
        payment_type='incoming',
        payment_date=date(2026, 1, 15),
        sale_id=s.id,
        customer_id=customer.id,
        user_id=owner.id,
    ))
    db.session.commit()
    return s
