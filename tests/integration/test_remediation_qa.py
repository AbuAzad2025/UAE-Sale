"""Agent Q remediation tests — permissions, reports filters, expense GL C5,
ERP service fixes (C1 transfers, warehouse-scoped stocktake, recurring actor),
and models/erp_modules.py text fixes."""
import inspect
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from models import (
    AuditLog, DunningLetter, EInvoice, Expense, ExpenseCategory,
    GLJournalEntry, GLJournalLine, Permission, Product, Quotation, RecurringExpense,
    Role, Sale, SaleLine, StockMovement, User, Warehouse,
)
from services.stock_service import StockService
from services.erp_modules_service import (
    RecurringExpenseService, StockTakeService, StockTransferService,
)
from services.gl_service import GLService


# ---------------------------------------------------------------- helpers

def _make_user(db, perm_codes=(), username=None):
    username = username or f'u{uuid.uuid4().hex[:8]}'
    perms = [Permission.query.filter_by(code=c).first() for c in perm_codes]
    perms = [p for p in perms if p is not None]
    role = Role(name=f'role-{username}', name_ar='دور اختبار',
                slug=f'slug-{username}', permissions=perms)
    db.session.add(role)
    db.session.flush()
    user = User(username=username, email=f'{username}@t.com', full_name=username,
                is_owner=False, is_active=True, role_id=role.id)
    user.set_password('Passw0rd!123')
    db.session.add(user)
    db.session.commit()
    return user


_FIXTURE_PASSWORDS = {
    'testowner': 'OwnerPass123!',
    'testseller': 'SellerPass123!',
    'testmanager': 'ManagerPass123!',
}


def _login(client, user):
    client.get('/auth/logout')  # auth.login ignores POSTs when already authenticated
    password = _FIXTURE_PASSWORDS.get(user.username, 'Passw0rd!123')
    return client.post('/auth/login', data={
        'username': user.username, 'password': password,
    }, follow_redirects=True)


def _has_post_gl_kwarg():
    try:
        sig = inspect.signature(StockService.adjust_stock)
        return 'post_gl' in sig.parameters
    except (TypeError, ValueError):
        return False


HAS_POST_GL = _has_post_gl_kwarg()


def _mk_warehouse(db, name, is_main=False):
    w = Warehouse(name=name, name_ar=name, code=f'WQ-{uuid.uuid4().hex[:6]}',
                  is_active=True, is_main=is_main)
    db.session.add(w)
    db.session.commit()
    return w


def _mk_product(db, name, cost='10', price='20', stock='0'):
    p = Product(name=name, sku=f'SK-{uuid.uuid4().hex[:8]}',
                regular_price=Decimal(price), cost_price=Decimal(cost),
                current_stock=Decimal(stock), min_stock_alert=Decimal('1'),
                is_active=True)
    db.session.add(p)
    db.session.commit()
    return p


def _expense_category(db, name):
    cat = ExpenseCategory(name=name, gl_account_code='6990', is_active=True)
    db.session.add(cat)
    db.session.commit()
    return cat


def _mk_expense_with_gl(db, owner, category, amount='100'):
    exp = Expense(
        expense_number=f'EXP-QA-{uuid.uuid4().hex[:6]}',
        category_id=category.id, description='قلم تجريبي', description_ar='',
        amount=Decimal(amount), currency='AED', exchange_rate=Decimal('1'),
        amount_base=Decimal(amount), expense_date=datetime.now(timezone.utc),
        payment_method='cash', status='confirmed', is_active=True,
        user_id=owner.id,
    )
    db.session.add(exp)
    db.session.flush()
    GLService.ensure_core_accounts()
    entry = GLService.post_entry(
        [
            {'account': '6990', 'debit': Decimal(amount), 'description': 'expense'},
            {'account': '1110', 'credit': Decimal(amount), 'description': 'cash'},
        ],
        description=f'Expense {exp.expense_number}',
        reference_type='Expense', reference_id=exp.id,
        currency='AED', exchange_rate=1,
    )
    db.session.commit()
    return exp, entry


def _active_expense_entries(expense_id):
    return GLJournalEntry.query.filter(
        GLJournalEntry.reference_type == 'Expense',
        GLJournalEntry.reference_id == expense_id,
        GLJournalEntry.is_reversed.is_(False),
        GLJournalEntry.entry_type != 'reversing',
    ).all()


# ---------------------------------------------------- 1) routes/returns.py

class TestReturnsPermissions:
    def test_anon_create_return_redirects_to_login(self, client, db):
        resp = client.post('/returns/api/create', json={})
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_user_without_manage_sales_gets_403_on_create(self, client, db, owner_user):
        limited = _make_user(db, ['manage_customers'])
        _login(client, limited)
        resp = client.post('/returns/api/create', json={})
        assert resp.status_code == 403

    def test_anon_view_return_redirects_to_login(self, client, db):
        assert client.get('/returns/view/999999').status_code == 302

    def test_user_without_manage_sales_gets_403_on_view(self, client, db, owner_user):
        limited = _make_user(db, [])
        _login(client, limited)
        assert client.get('/returns/view/999999').status_code == 403

    def test_seller_with_manage_sales_passes_decorator(self, client, db, owner_user, seller_user):
        _login(client, seller_user)
        # Passes the permission gate; missing record yields 404 (not 403).
        assert client.get('/returns/view/999999').status_code == 404


# --------------------------------- 2) sales/customers/products API guards

class TestSalesCustomersProductsPermissions:
    def test_anon_get_price_redirects(self, client, db):
        assert client.get('/sales/api/get-price?product_id=1&customer_id=1').status_code == 302

    def test_no_perm_get_price_403(self, client, db, owner_user):
        limited = _make_user(db, [])
        _login(client, limited)
        assert client.get('/sales/api/get-price?product_id=1&customer_id=1').status_code == 403

    def test_owner_get_price_ok(self, client, db, owner_user, test_customer, test_product):
        _login(client, owner_user)
        resp = client.get(f'/sales/api/get-price?product_id={test_product.id}&customer_id={test_customer.id}')
        assert resp.status_code == 200
        assert resp.get_json()['price'] == 100.0

    def test_anon_customer_search_redirects(self, client, db):
        assert client.get('/customers/api/search?q=x').status_code == 302

    def test_seller_sales_only_can_search_customers_dual_check(self, client, db, owner_user, seller_user, test_customer):
        # seller has manage_sales but NOT manage_customers → must pass dual-check
        _login(client, seller_user)
        resp = client.get('/customers/api/search?q=Test')
        assert resp.status_code == 200
        assert any(r['id'] == test_customer.id for r in resp.get_json())

    def test_customers_only_user_can_search(self, client, db, owner_user, test_customer):
        cust_mgr = _make_user(db, ['manage_customers'])
        _login(client, cust_mgr)
        assert client.get('/customers/api/search').status_code == 200

    def test_no_perm_user_blocked_from_customer_search(self, client, db, owner_user):
        limited = _make_user(db, [])
        _login(client, limited)
        assert client.get('/customers/api/search').status_code == 403

    def test_customer_balance_dual_check_matrix(self, client, db, owner_user, seller_user, test_customer):
        url = f'/customers/{test_customer.id}/balance'
        assert client.get(url).status_code == 302                      # anon → login
        limited = _make_user(db, [])
        _login(client, limited)
        assert client.get(url).status_code == 403                      # no domain perms
        _login(client, seller_user)
        assert client.get(url).status_code == 200                      # manage_sales suffices

    def test_anon_product_search_redirects(self, client, db):
        assert client.get('/products/api/search?q=x').status_code == 302

    def test_no_perm_product_search_403(self, client, db, owner_user):
        limited = _make_user(db, ['manage_sales'])
        _login(client, limited)
        assert client.get('/products/api/search?q=x').status_code == 403

    def test_products_only_user_can_search(self, client, db, owner_user, test_product):
        prod_mgr = _make_user(db, ['manage_products'])
        _login(client, prod_mgr)
        resp = client.get(f'/products/api/search?q={test_product.sku}')
        assert resp.status_code == 200
        assert any(r['id'] == test_product.id for r in resp.get_json())


# ------------------------------- 3) ledger / purchases / suppliers guards

class TestCalcAndSearchGuards:
    def test_journal_balance_anon_redirects(self, client, db):
        assert client.post('/ledger/api/calculate-journal-balance', json={'lines': []}).status_code == 302

    def test_journal_balance_without_ledger_perms_403(self, client, db, owner_user):
        limited = _make_user(db, ['manage_sales'])
        _login(client, limited)
        assert client.post('/ledger/api/calculate-journal-balance', json={'lines': []}).status_code == 403

    def test_journal_balance_view_ledger_only_ok(self, client, db, owner_user):
        viewer = _make_user(db, ['view_ledger'])   # has view_ledger, NOT manage_ledger
        _login(client, viewer)
        resp = client.post('/ledger/api/calculate-journal-balance', json={
            'lines': [{'debit': 100}, {'credit': 100}],
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True and body['is_balanced'] is True

    def test_purchase_totals_anon_redirects(self, client, db):
        assert client.post('/purchases/api/calculate-totals', json={}).status_code == 302

    def test_purchase_totals_seller_403(self, client, db, owner_user, seller_user):
        _login(client, seller_user)  # seller lacks manage_purchases
        assert client.post('/purchases/api/calculate-totals', json={'lines': []}).status_code == 403

    def test_purchase_totals_manager_ok(self, client, db, owner_user, manager_user):
        _login(client, manager_user)  # manager has manage_purchases
        resp = client.post('/purchases/api/calculate-totals', json={
            'lines': [{'quantity': 2, 'unit_cost': 50}], 'tax_rate': 5,
        })
        assert resp.status_code == 200
        assert resp.get_json()['total'] == 105.0

    def test_supplier_search_anon_redirects(self, client, db):
        assert client.get('/suppliers/api/search?q=x').status_code == 302

    def test_supplier_search_manager_403(self, client, db, owner_user, manager_user):
        _login(client, manager_user)  # manager lacks manage_suppliers
        assert client.get('/suppliers/api/search?q=x').status_code == 403

    def test_supplier_search_owner_ok(self, client, db, owner_user):
        _login(client, owner_user)
        assert client.get('/suppliers/api/search?q=x').status_code == 200


# --------------------------------------------------- 4) routes/reports.py

class TestReportsFixes:
    def test_purchases_report_counts_only_supplier_payments(self, client, db, owner_user, test_customer):
        from models import Payment, Supplier
        sup = Supplier(name=f'S-{uuid.uuid4().hex[:6]}', is_active=True)
        db.session.add_all([sup, test_customer])
        db.session.flush()
        supplier_pay = Payment(payment_number=f'PAY-QA-SUP-{uuid.uuid4().hex[:6]}',
                               payment_type='supplier_payment', direction='outgoing',
                               supplier_id=sup.id, amount=Decimal('317.25'),
                               currency='AED', exchange_rate=Decimal('1'),
                               amount_base=Decimal('317.25'), payment_method='cash')
        customer_pay = Payment(payment_number=f'PAY-QA-CX-{uuid.uuid4().hex[:6]}',
                               payment_type='refund', direction='outgoing',
                               customer_id=test_customer.id, amount=Decimal('913.75'),
                               currency='AED', exchange_rate=Decimal('1'),
                               amount_base=Decimal('913.75'), payment_method='cash')
        db.session.add_all([supplier_pay, customer_pay])
        db.session.commit()

        _login(client, owner_user)
        html = client.get('/reports/purchases').get_data(as_text=True)
        # Supplier outgoing payments ARE counted (broken python-comparison yielded 0 before).
        assert '317.25' in html
        # Customer-only outgoing payments are excluded from supplier paid totals.
        assert '913.75' not in html

    def test_inventory_valuation_unfiltered_uses_global_stock(self, client, db, owner_user, test_product):
        _login(client, owner_user)
        wh = _mk_warehouse(db, 'WH-GLOBAL')
        StockService.add_stock(test_product.id, Decimal('7'), notes='qa', warehouse_id=wh.id)
        db.session.commit()
        # global current_stock now 107 (fixture 100 + movement 7); value 107 × 50
        html = client.get('/reports/inventory-valuation').get_data(as_text=True)
        assert '5,350.000' in html

    def test_inventory_valuation_warehouse_filter_aggregates_movements(self, client, db, owner_user, test_product):
        wh_a = _mk_warehouse(db, 'WH-A')
        wh_b = _mk_warehouse(db, 'WH-B')
        StockService.add_stock(test_product.id, Decimal('4'), notes='a', warehouse_id=wh_a.id)
        StockService.add_stock(test_product.id, Decimal('6'), notes='b', warehouse_id=wh_b.id)
        db.session.commit()

        _login(client, owner_user)
        html_a = client.get(f'/reports/inventory-valuation?warehouse_id={wh_a.id}').get_data(as_text=True)
        # only wh_a qty (4) × cost 50 — global stock (104) must NOT be used
        assert '200.000' in html_a
        assert '5,200.000' not in html_a

        html_b = client.get(f'/reports/inventory-valuation?warehouse_id={wh_b.id}').get_data(as_text=True)
        assert '300.000' in html_b

    def test_inventory_valuation_excludes_other_warehouse_products(self, client, db, owner_user, test_product):
        wh_a = _mk_warehouse(db, 'WH-A2')
        wh_b = _mk_warehouse(db, 'WH-B2')
        other = _mk_product(db, 'Other WH Product', stock='0')
        StockService.add_stock(test_product.id, Decimal('5'), notes='a', warehouse_id=wh_a.id)
        StockService.add_stock(other.id, Decimal('9'), notes='b', warehouse_id=wh_b.id)
        db.session.commit()

        _login(client, owner_user)
        html = client.get(f'/reports/inventory-valuation?warehouse_id={wh_a.id}').get_data(as_text=True)
        # template prefers the Arabic display name
        assert test_product.name_ar in html
        assert other.name not in html


# ------------------------------------------- 5) expenses edit (contract C5)

class TestExpenseEditGlRepost:
    def test_amount_change_reverses_and_reposts_netting_correctly(self, client, db, owner_user, test_sale=None):
        cat = _expense_category(db, f'Cat-{uuid.uuid4().hex[:6]}')
        exp, original = _mk_expense_with_gl(db, owner_user, cat, '100')

        _login(client, owner_user)
        resp = client.post(f'/expenses/{exp.id}/edit', data={
            'category_id': str(cat.id), 'description': exp.description,
            'description_ar': '', 'amount': '250', 'currency': 'AED',
            'supplier_name': '', 'notes': '',
        }, follow_redirects=True)
        assert resp.status_code == 200

        db.session.expire_all()
        old = db.session.get(GLJournalEntry, original.id)
        assert old.is_reversed is True

        reversal = GLJournalEntry.query.filter_by(reversed_entry_id=old.id).first()
        assert reversal is not None and reversal.entry_type == 'reversing'

        active = _active_expense_entries(exp.id)
        assert len(active) == 1
        corrected = active[0]
        assert corrected.total_debit == Decimal('250')

        # Netting across ALL entries of this expense: old + reversal cancel out
        # per account, leaving exactly the corrected amount as the net balance.
        lines = GLJournalLine.query.join(GLJournalEntry).filter(
            GLJournalEntry.reference_type == 'Expense',
            GLJournalEntry.reference_id == exp.id,
        ).all()
        net_by_code = {}
        for ln in lines:
            code = ln.account.code
            net_by_code[code] = net_by_code.get(code, Decimal('0')) + \
                ((ln.debit or Decimal('0')) - (ln.credit or Decimal('0')))
        assert net_by_code['6990'] == Decimal('250')
        assert net_by_code['1110'] == Decimal('-250')

        audit = AuditLog.query.filter_by(action='update', table_name='expenses',
                                         record_id=exp.id).first()
        assert audit is not None
        assert (audit.changes or {}).get('gl_reversed') == old.entry_number

    def test_description_only_edit_leaves_gl_untouched(self, client, db, owner_user):
        cat = _expense_category(db, f'Cat-{uuid.uuid4().hex[:6]}')
        exp, original = _mk_expense_with_gl(db, owner_user, cat, '100')
        entries_before = GLJournalEntry.query.filter_by(
            reference_type='Expense', reference_id=exp.id).count()

        _login(client, owner_user)
        client.post(f'/expenses/{exp.id}/edit', data={
            'category_id': str(cat.id), 'description': 'وصف جديد فقط',
            'description_ar': '', 'amount': '100', 'currency': 'AED',
            'supplier_name': '', 'notes': '',
        }, follow_redirects=True)

        db.session.expire_all()
        entries_after = GLJournalEntry.query.filter_by(
            reference_type='Expense', reference_id=exp.id).count()
        assert entries_after == entries_before
        assert db.session.get(GLJournalEntry, original.id).is_reversed is False

    def test_failed_repost_is_loud_not_silent(self, client, db, owner_user, monkeypatch, caplog):
        cat = _expense_category(db, f'Cat-{uuid.uuid4().hex[:6]}')
        exp, original = _mk_expense_with_gl(db, owner_user, cat, '100')

        def boom(*args, **kwargs):
            raise RuntimeError('boom')

        monkeypatch.setattr(GLService, 'post_entry', boom)

        _login(client, owner_user)
        with caplog.at_level('ERROR'):
            resp = client.post(f'/expenses/{exp.id}/edit', data={
                'category_id': str(cat.id), 'description': exp.description,
                'description_ar': '', 'amount': '300', 'currency': 'AED',
                'supplier_name': '', 'notes': '',
            }, follow_redirects=True)

        assert '⚠️' in resp.get_data(as_text=True)
        assert any('ORPHAN EXPENSE WARNING' in rec.getMessage() for rec in caplog.records)

        db.session.expire_all()
        # Reversal committed even though repost failed: no wrong active entry remains.
        assert db.session.get(GLJournalEntry, original.id).is_reversed is True
        assert _active_expense_entries(exp.id) == []

    def test_missing_prior_entry_warns_orphan(self, client, db, owner_user, caplog):
        cat = _expense_category(db, f'Cat-{uuid.uuid4().hex[:6]}')
        exp = Expense(
            expense_number=f'EXP-QA-{uuid.uuid4().hex[:6]}',
            category_id=cat.id, description='بلا قيد', description_ar='',
            amount=Decimal('50'), currency='AED', exchange_rate=Decimal('1'),
            amount_base=Decimal('50'), expense_date=datetime.now(timezone.utc),
            payment_method='cash', status='confirmed', is_active=True,
            user_id=owner_user.id,
        )
        db.session.add(exp)
        db.session.commit()

        _login(client, owner_user)
        with caplog.at_level('WARNING'):
            resp = client.post(f'/expenses/{exp.id}/edit', data={
                'category_id': str(cat.id), 'description': exp.description,
                'description_ar': '', 'amount': '60', 'currency': 'AED',
                'supplier_name': '', 'notes': '',
            }, follow_redirects=True)

        assert '⚠️' in resp.get_data(as_text=True)
        assert any('ORPHAN EXPENSE WARNING' in rec.getMessage() for rec in caplog.records)


# ------------------------------------- 6) erp_modules_service behaviors

@pytest.fixture
def gl_ready(db):
    GLService.ensure_core_accounts()


class TestStockTransferNoGl:
    @pytest.mark.skipif(not HAS_POST_GL, reason='C1 post_gl kwarg not landed by L yet')
    def test_receive_transfer_posts_no_pl_rows(self, db, gl_ready, owner_user):
        src = _mk_warehouse(db, 'TRF-SRC', is_main=True)
        dst = _mk_warehouse(db, 'TRF-DST')
        product = _mk_product(db, 'Trf Product', cost='40', stock='0')
        StockService.add_stock(product.id, Decimal('10'), notes='seed', warehouse_id=src.id)
        db.session.commit()

        def pl_line_count(code):
            return GLJournalLine.query.join(GLJournalLine.account).filter(
                GLJournalLine.account.has(code=code)).count()

        assert pl_line_count('5150') == 0
        assert pl_line_count('5200') == 0
        adj_entries_before = GLJournalEntry.query.filter_by(
            reference_type='stock_adjustment').count()

        transfer = StockTransferService.create_transfer(
            src.id, dst.id, [{'product_id': product.id, 'quantity': 6}],
            owner_user.id)
        transfer.status = 'in_transit'
        db.session.commit()
        StockTransferService.receive_transfer(transfer.id, owner_user.id)

        db.session.expire_all()
        # No P&L rows appeared for a pure stock relocation (contract C1)
        assert GLJournalLine.query.join(GLJournalLine.account).filter(
            GLJournalLine.account.has(code='5150')).count() == 0
        assert GLJournalLine.query.join(GLJournalLine.account).filter(
            GLJournalLine.account.has(code='5200')).count() == 0
        assert GLJournalEntry.query.filter_by(reference_type='stock_adjustment').count() \
            == adj_entries_before

        adjustments = StockMovement.query.filter_by(
            product_id=product.id, movement_type='adjustment').all()
        assert {(m.warehouse_id, m.quantity) for m in adjustments} == {
            (src.id, Decimal('-6')), (dst.id, Decimal('6')),
        }

    def test_receive_transfer_moves_stock_legacy_signature(self, db, gl_ready, owner_user):
        """Behavior holds regardless of whether post_gl exists (fallback safe)."""
        src = _mk_warehouse(db, 'TRF-SRC2', is_main=True)
        dst = _mk_warehouse(db, 'TRF-DST2')
        product = _mk_product(db, 'Trf Product 2', stock='0')
        StockService.add_stock(product.id, Decimal('8'), notes='seed', warehouse_id=src.id)

        transfer = StockTransferService.create_transfer(
            src.id, dst.id, [{'product_id': product.id, 'quantity': 8}],
            owner_user.id)
        transfer.status = 'in_transit'
        db.session.commit()
        received = StockTransferService.receive_transfer(transfer.id, owner_user.id)
        assert received.status == 'received'
        adjustments = StockMovement.query.filter_by(
            product_id=product.id, movement_type='adjustment').all()
        assert {m.quantity for m in adjustments} == {Decimal('-8'), Decimal('8')}


class TestStockTakeWarehouseScope:
    def test_stocktake_honors_warehouse(self, db, owner_user):
        wh_a = _mk_warehouse(db, 'STK-A', is_main=True)
        wh_b = _mk_warehouse(db, 'STK-B')
        p_here = _mk_product(db, 'Here Product', stock='0')
        p_there = _mk_product(db, 'There Product', stock='0')
        p_never_moved = _mk_product(db, 'Never Moved', stock='4')

        StockService.add_stock(p_here.id, Decimal('10'), notes='a', warehouse_id=wh_a.id)
        StockService.add_stock(p_there.id, Decimal('7'), notes='b', warehouse_id=wh_b.id)
        db.session.commit()

        st_a = StockTakeService.create_stocktake(wh_a.id, owner_user.id)
        items_a = {i.product_id: i.system_quantity for i in st_a.items}
        assert items_a == {p_here.id: Decimal('10'), p_never_moved.id: Decimal('4')}
        assert st_a.warehouse_id == wh_a.id

        st_b = StockTakeService.create_stocktake(wh_b.id, owner_user.id)
        items_b = {i.product_id: i.system_quantity for i in st_b.items}
        assert items_b == {p_there.id: Decimal('7'), p_never_moved.id: Decimal('4')}


class TestRecurringExpenseActor:
    def test_authenticated_actor_used(self, db, app, owner_user, seller_user):
        cat = _expense_category(db, f'RecCat-{uuid.uuid4().hex[:6]}')
        db.session.add(RecurringExpense(
            name='إيجار', category_id=cat.id, amount=Decimal('500'),
            currency='AED', payment_method='cash', frequency='monthly',
            next_due_date=date.today(), is_active=True))
        db.session.commit()

        with app.test_request_context():
            from flask_login import login_user
            assert login_user(seller_user)
            created = RecurringExpenseService.process_due_expenses()
        assert len(created) == 1
        assert created[0].user_id == seller_user.id

    def test_anonymous_context_never_fabricates_literal_one(self, db, app, owner_user):
        """Deactivate the first account so fallback must resolve a DIFFERENT
        real user — proving resolution isn't a hardcoded constant."""
        second = _make_user(db, [], username='secondreal')
        owner_user.is_active = False
        db.session.commit()
        cat = _expense_category(db, f'RecCat2-{uuid.uuid4().hex[:6]}')
        db.session.add(RecurringExpense(
            name='كهرباء', category_id=cat.id, amount=Decimal('90'),
            currency='AED', payment_method='cash', frequency='monthly',
            next_due_date=date.today(), is_active=True))
        db.session.commit()

        created = RecurringExpenseService.process_due_expenses()  # app ctx only, no request/login
        assert len(created) == 1
        assert created[0].user_id == second.id


# --------------------------------------- 7) models/erp_modules.py text fixes

class TestErpModulesTextFixes:
    def test_dunning_level_ar_typo_fixed(self, db):
        letter = DunningLetter(level=1)
        assert letter.level_ar == 'تذكير ودّي'
        assert 'friendly' not in letter.level_ar
        assert DunningLetter(level=3).level_ar == 'إنذار عاجل'

    def test_einvoice_json_honest_vat_naming(self, db, owner_user, test_customer, test_product):
        sale_number = f'S-QA-EI-{uuid.uuid4().hex[:6]}'
        sale = Sale(sale_number=sale_number, customer_id=test_customer.id,
                    seller_id=owner_user.id, total_amount=Decimal('100'),
                    amount_base=Decimal('100'), paid_amount=Decimal('0'),
                    paid_amount_base=Decimal('0'), balance_due=Decimal('100'),
                    currency='AED', exchange_rate=Decimal('1'),
                    payment_status='unpaid', status='confirmed', is_active=True)
        db.session.add(sale)
        db.session.flush()
        db.session.add(SaleLine(sale_id=sale.id, product_id=test_product.id,
                                quantity=Decimal('1'), unit_price=Decimal('100'),
                                discount_percent=Decimal('0'),
                                line_total=Decimal('100'), cost_price=Decimal('25')))
        db.session.commit()

        einv = EInvoice(invoice_number=f'EI-{sale_number}', sale_id=sale.id,
                        invoice_date=datetime.now(timezone.utc), buyer_name='x',
                        total_amount=Decimal('100'), tax_amount=Decimal('0'),
                        total_with_tax=Decimal('100'), currency='AED')
        payload = einv.generate_json()
        for line in payload['lines']:
            assert 'vat_rate' not in line
            assert line['vat_amount_per_unit'] == pytest.approx(5.0)

    def test_quotation_expiry_alias_and_column_kept(self, db, owner_user, test_customer):
        q = Quotation(quotation_number=f'QT-QA-{uuid.uuid4().hex[:6]}',
                      customer_id=test_customer.id, seller_id=owner_user.id,
                      quotation_date=date.today(), valid_until=date(2026, 12, 31))
        assert q.expiry_date == q.valid_until == date(2026, 12, 31)
        q.expiry_date = date(2027, 3, 1)
        assert q.valid_until == date(2027, 3, 1)
        cols = [c.name for c in Quotation.__table__.columns]
        assert 'expiry_date' in cols and 'valid_until' in cols
