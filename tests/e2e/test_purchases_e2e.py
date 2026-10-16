"""
E2E tests for Purchases module - comprehensive coverage of all routes.

Route contract (routes/purchases.py):
  GET     /purchases/                     (login + manage_purchases)
  GET/POST /purchases/create              (login + manage_purchases)
  GET     /purchases/<id>                 (login + manage_purchases)
  GET     /purchases/<id>/print           (login + manage_purchases)
  GET/POST /purchases/<id>/edit           (login + manage_purchases) notes only, unpaid only
  POST    /purchases/<id>/delete          (login + manage_purchases) hard-delete or archive
  POST    /purchases/api/calculate-totals (login + manage_purchases)

Records are seeded straight into the database. Flask-Login binds current_user
for the lifetime of the app context (tests/e2e/test_matrix.py:3495), so a
fixture that created the row over HTTP would leave the shared client
authenticated as owner and every later login_as(other_role) would silently
keep the owner identity.
"""

from datetime import date
from decimal import Decimal

import pytest

from extensions import db
from models.purchase import Purchase, PurchaseLine
from tests.e2e.harness import purchase_form


class TestPurchasesListAndView:
    def test_purchases_list_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/purchases/')
        assert r.status_code == 200

    def test_purchase_view_requires_login(self, client, purchase):
        r = client.get(f'/purchases/{purchase.id}')
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')

    def test_purchase_view_by_owner(self, client, login_as, purchase):
        login_as('owner')
        r = client.get(f'/purchases/{purchase.id}')
        assert r.status_code == 200


class TestPurchasesCreate:
    def test_create_purchase_basic(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 10, 'unit_cost': 50}],
            warehouse=warehouse,
        ))
        assert r.status_code in (302, 303)
        pid = r.headers.get('Location', '').split('/')[-1]
        assert pid.isdigit()
        pur = Purchase.query.get(int(pid))
        assert pur is not None
        assert pur.subtotal == Decimal('500.000')

    def test_create_purchase_with_tax(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 10, 'unit_cost': 50}],
            warehouse=warehouse,
            tax_rate=5,
        ))
        assert r.status_code in (302, 303)
        pid = r.headers.get('Location', '').split('/')[-1]
        pur = Purchase.query.get(int(pid))
        assert pur.tax_amount == Decimal('25.000')
        assert pur.total_amount == Decimal('525.000')

    def test_create_purchase_with_multiple_lines(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [
                {'product_id': product.id, 'quantity': 10, 'unit_cost': 50},
                {'product_id': product.id, 'quantity': 2, 'unit_cost': 25},
            ],
            warehouse=warehouse,
        ))
        assert r.status_code in (302, 303)
        pid = r.headers.get('Location', '').split('/')[-1]
        pur = Purchase.query.get(int(pid))
        assert pur.subtotal == Decimal('550.000')
        assert PurchaseLine.query.filter_by(purchase_id=pur.id).count() == 2

    def test_create_purchase_with_currency(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 1, 'unit_cost': 100}],
            warehouse=warehouse,
            currency='AED',
            exchange_rate=1,
        ))
        assert r.status_code in (302, 303)
        pid = r.headers.get('Location', '').split('/')[-1]
        pur = Purchase.query.get(int(pid))
        assert pur.currency == 'AED'
        assert pur.total_amount == Decimal('100.000')

    def test_create_purchase_ignores_payment_fields(self, client, login_as, supplier, product, warehouse):
        # The create route stores no payment data: paid_amount stays 0.
        login_as('owner')
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 10, 'unit_cost': 50}],
            warehouse=warehouse,
            payment_amount=200,
            payment_method='bank_transfer',
        ))
        assert r.status_code in (302, 303)
        pid = r.headers.get('Location', '').split('/')[-1]
        pur = Purchase.query.get(int(pid))
        assert pur.subtotal == Decimal('500.000')
        assert pur.paid_amount == Decimal('0.000')

    def test_create_purchase_zero_quantity_rejected(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        before = Purchase.query.count()
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 0, 'unit_cost': 50}],
            warehouse=warehouse,
        ))
        assert Purchase.query.count() == before

    def test_create_purchase_requires_warehouse(self, client, login_as, supplier, product):
        login_as('owner')
        before = Purchase.query.count()
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 5, 'unit_cost': 50}],
            warehouse=None,
        ))
        assert r.status_code in (302, 303)
        assert Purchase.query.count() == before

    def test_create_purchase_requires_login(self, client, supplier, product, warehouse):
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 5, 'unit_cost': 50}],
            warehouse=warehouse,
        ))
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')


class TestPurchasesEdit:
    def test_edit_purchase_updates_notes(self, client, login_as, purchase):
        login_as('owner')
        r = client.post(f'/purchases/{purchase.id}/edit', data={
            'notes': 'Updated notes',
        })
        assert r.status_code in (302, 303)
        reloaded = db.session.get(Purchase, purchase.id)
        assert reloaded.notes == 'Updated notes'

    def test_edit_purchase_blocked_when_paid(self, client, login_as, purchase):
        login_as('owner')
        purchase.paid_amount = Decimal('100.000')
        db.session.commit()
        assert purchase.get_paid_amount() > 0

        r = client.post(f'/purchases/{purchase.id}/edit', data={'notes': 'should not stick'})
        assert r.status_code in (302, 303)
        reloaded = db.session.get(Purchase, purchase.id)
        assert reloaded.notes != 'should not stick'

    def test_edit_purchase_not_found(self, client, login_as):
        login_as('owner')
        r = client.post('/purchases/999999/edit', data={'notes': 'x'})
        assert r.status_code == 404


class TestPurchasesPrint:
    def test_print_purchase_renders(self, client, login_as, purchase):
        login_as('owner')
        r = client.get(f'/purchases/{purchase.id}/print')
        assert r.status_code == 200


class TestPurchasesDelete:
    def test_delete_purchase_without_links(self, client, login_as, purchase):
        login_as('owner')
        pid = purchase.id
        r = client.post(f'/purchases/{pid}/delete')
        assert r.status_code in (302, 303)
        assert Purchase.query.get(pid) is None

    def test_delete_purchase_with_cheque_is_archived(self, client, login_as, purchase):
        from models import Cheque, ArchivedRecord
        login_as('owner')
        cheque = Cheque(
            cheque_number='CHQ-DEL-1', cheque_bank_number='CHQ-DEL-1',
            cheque_type='outgoing', bank_name='Bank', amount=Decimal('100'),
            currency='ILS', exchange_rate=Decimal('1'), amount_base=Decimal('100'),
            issue_date=date(2026, 1, 1), due_date=date(2026, 2, 1), status='pending',
            payee_name='Supplier', purchase_id=purchase.id,
        )
        db.session.add(cheque)
        db.session.commit()

        pid = purchase.id
        r = client.post(f'/purchases/{pid}/delete')
        assert r.status_code in (302, 303)
        # archived, not hard-deleted
        assert Purchase.query.get(pid) is not None
        assert ArchivedRecord.query.filter_by(
            table_name='purchases', record_id=pid).count() == 1


class TestPurchasesApi:
    def test_calculate_totals_endpoint(self, client, login_as, supplier, product, warehouse):
        login_as('owner')
        r = client.post('/purchases/api/calculate-totals', json={
            'supplier_id': supplier.id,
            'lines': [{'product_id': product.id, 'quantity': 5, 'unit_cost': 100}],
            'discount_amount': 0,
            'tax_rate': 5,
            'currency': 'AED',
            'exchange_rate': 1,
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['subtotal'] == 500
        assert data['tax_amount'] == 25
        assert data['total'] == 525


class TestPurchasesRbac:
    @pytest.mark.parametrize('role,allowed', [
        ('owner', True),
        ('branch_manager', True),
        ('manager', True),
        ('senior_accountant', False),
        ('accountant', False),
        ('pos_cashier', False),
        ('warehouse_keeper', False),
        ('viewer', False),
        ('hr', False),
    ])
    def test_manage_purchases_gates_purchase_creation(
            self, client, login_as, supplier, product, warehouse, role, allowed):
        login_as(role)
        before = Purchase.query.count()
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 5, 'unit_cost': 50}],
            warehouse=warehouse,
        ))
        if allowed:
            assert r.status_code in (302, 303)
        else:
            assert r.status_code == 403
            assert Purchase.query.count() == before


# Fixtures for this test module
@pytest.fixture
def purchase(db, owner, supplier, product, warehouse):
    """Seed a purchase row directly (see module docstring)."""
    pur = Purchase(
        purchase_number='P-E2E-FIX',
        supplier_id=supplier.id,
        warehouse_id=warehouse.id,
        supplier_name=supplier.name,
        currency='ILS',
        exchange_rate=Decimal('1'),
        subtotal=Decimal('500.000'),
        tax_amount=Decimal('0.000'),
        total_amount=Decimal('500.000'),
        amount_base=Decimal('500.000'),
        status='confirmed',
        user_id=owner.id,
    )
    db.session.add(pur)
    db.session.flush()
    db.session.add(PurchaseLine(
        purchase_id=pur.id,
        product_id=product.id,
        quantity=Decimal('10'),
        unit_cost=Decimal('50.000'),
        line_total=Decimal('500.000'),
    ))
    db.session.commit()
    return pur