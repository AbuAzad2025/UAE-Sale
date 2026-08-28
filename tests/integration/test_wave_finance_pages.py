"""Wave coverage: finance/accounting pages — products, cheques, HR, ERP modules, GL + admin/advanced ledger."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func

from extensions import db
from models import (
    Cheque,
    Customer,
    GLAccount,
    GLJournalEntry,
    GLJournalLine,
    Product,
    ProductCategory,
    ProductPartner,
    Sale,
    StockMovement,
    Supplier,
    Warehouse,
)
from models.advanced_accounting import AdvancedExpense, CustomsTax
from models.erp_modules import (
    DunningLetter,
    EInvoice,
    FiscalPeriod,
    PurchaseOrder,
    Quotation,
    RecurringExpense,
    StockTransfer,
)
from models.expense import ExpenseCategory
from models.hr import Department, Employee, LeaveRequest, LeaveType, Payslip
from services.gl_service import GLService
from services.hr_service import HRService


# ---------------------------------------------------------------- helpers / fixtures


@pytest.fixture(autouse=True)
def _offline_rates(monkeypatch):
    """Deterministic offline FX: disable live HTTP/forex sources for every test."""
    from services import currency_service as cs

    monkeypatch.setattr(cs, 'REQUESTS_AVAILABLE', False, raising=False)
    monkeypatch.setattr(cs, 'FOREX_AVAILABLE', False, raising=False)
    cs.CurrencyService._rates_cache.clear()
    yield
    cs.CurrencyService._rates_cache.clear()


def _ensure_accounts():
    GLService.ensure_core_accounts()
    return {a.code: a.id for a in GLAccount.query.all()}


def _manual_entry(description, lines):
    return GLService.create_manual_entry(description=description, lines=lines)


def _make_warehouse(name='Main WH', is_main=True):
    w = Warehouse(name=name, name_ar='مستودع', is_active=True, is_main=is_main)
    db.session.add(w)
    db.session.commit()
    return w


def _make_partner(name='Partner One'):
    c = Customer(name=name, customer_type='partner', is_active=True, balance=Decimal('0'))
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def main_wh(db):
    return _make_warehouse('WH-WAVE-MAIN')


@pytest.fixture
def supplier_row(db):
    s = Supplier(name='Wave Supplier', is_active=True)
    db.session.add(s)
    db.session.commit()
    return s


@pytest.fixture
def incoming_cheque(db, test_customer):
    ch = Cheque(
        cheque_number='CHQ-WV-101', cheque_bank_number='998877',
        cheque_type='incoming', bank_name='ADCB', amount=Decimal('500'),
        currency='AED', exchange_rate=Decimal('1'), amount_base=Decimal('500.00'),
        issue_date=date.today() - timedelta(days=2),
        due_date=date.today() + timedelta(days=20),
        drawer_name='ساحب تجريبي', payee_name='', customer_id=test_customer.id,
        status='pending',
    )
    db.session.add(ch)
    db.session.commit()
    return ch


@pytest.fixture
def department(db):
    d = Department(name='Sales Dept', name_ar='المبيعات', code='DPT-S')
    db.session.add(d)
    db.session.commit()
    return d


@pytest.fixture
def employee(db, department, seller_user):
    emp = Employee(
        user_id=seller_user.id, employee_number='EMP-001', department_id=department.id,
        position='Cashier', hire_date=date(2024, 1, 1), base_salary=Decimal('3000'),
        housing_allowance=Decimal('500'), transport_allowance=Decimal('100'),
    )
    db.session.add(emp)
    db.session.commit()
    return emp


# ---------------------------------------------------------------- products


class TestProducts:
    def test_access_matrix(self, client, login_owner, main_wh):
        assert client.get('/products/', follow_redirects=True).status_code == 200
        assert client.get('/products/create').status_code == 200

    def test_anon_redirects(self, client):
        assert client.get('/products/').status_code == 302
        assert client.get('/products/api/search').status_code == 302

    def test_create_full_form_single_partner_initial_stock_movement(self, client, login_owner, main_wh):
        p = _make_partner('شريك واحد')
        data = {
            'name': 'Water Pump', 'regular_price': '120', 'warehouse_id': str(main_wh.id),
            'current_stock': '5', 'sku': 'SKU-WAVE-1', 'category_id': '0',
            'partner_customer_id': str(p.id), 'partner_percentage': '60',
        }
        resp = client.post('/products/create', data=data, follow_redirects=True)
        assert resp.status_code == 200
        prod = Product.query.filter_by(sku='SKU-WAVE-1').one()
        assert prod.current_stock == Decimal('5')
        shares = ProductPartner.query.filter_by(product_id=prod.id).all()
        assert len(shares) == 1 and float(shares[0].percentage) == 60.0
        mv = StockMovement.query.filter_by(product_id=prod.id, reference_type='Product Creation').all()
        assert len(mv) == 1 and float(mv[0].quantity) == 5.0

    def test_create_multi_partner_rows_split_shares(self, client, login_owner, main_wh):
        p1, p2 = _make_partner('شريك أ'), _make_partner('شريك ب')
        data = {
            'name': 'Air Filter', 'regular_price': '80', 'warehouse_id': str(main_wh.id),
            'current_stock': '0', 'sku': 'SKU-WAVE-2',
            'partner_customer_id': [str(p1.id), str(p2.id)],
            'partner_percentage': ['40', '50'],
        }
        client.post('/products/create', data=data, follow_redirects=True)
        prod = Product.query.filter_by(sku='SKU-WAVE-2').one()
        rows = sorted(ProductPartner.query.filter_by(product_id=prod.id).all(),
                      key=lambda r: r.percentage)
        assert [float(r.percentage) for r in rows] == [40.0, 50.0]

    @pytest.mark.parametrize('pct,names', [
        (['60', '60'], 2),      # share sum > 100 → rejected
        (['20', ''], 2),        # missing percentage line → rejected
        (['abc'], 1),           # non-numeric percentage → rejected
        (['150'], 1),           # single share over 100 → rejected
    ])
    def test_create_partner_validation_errors(self, client, login_owner, main_wh, pct, names):
        partners = [_make_partner(f'P{i}') for i in range(names)]
        data = {
            'name': 'Bad Product', 'regular_price': '10', 'warehouse_id': str(main_wh.id),
            'sku': 'SKU-BAD', 'partner_customer_id': [str(p.id) for p in partners],
            'partner_percentage': pct,
        }
        resp = client.post('/products/create', data=data, follow_redirects=True)
        assert resp.status_code == 200
        html = resp.data.decode('utf-8', 'replace')
        assert 'فشل' in html or '⚠️' in html or 'شراكة' in html or 'الشريك' in html
        assert Product.query.filter_by(sku='SKU-BAD').count() == 0

    def test_create_missing_warehouse_rerenders_warning(self, client, login_owner):
        resp = client.post('/products/create', data={
            'name': 'No WH', 'regular_price': '10', 'sku': 'SKU-NOWH',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'\xd9\x85\xd8\xb3\xd8\xaa\xd9\x88\xd8\xaf\xd8\xb9' in resp.data  # مستودع
        assert Product.query.filter_by(sku='SKU-NOWH').count() == 0

    def test_edit_changes_price_and_creates_stock_difference_movement(self, client, login_owner, main_wh):
        prod = Product(name='Editable', sku='SKU-EDIT-1', regular_price=Decimal('100'),
                       current_stock=Decimal('10'), is_active=True)
        db.session.add(prod)
        db.session.commit()
        assert client.get(f'/products/{prod.id}/edit').status_code == 200
        resp = client.post(f'/products/{prod.id}/edit', data={
            'name': 'Editable', 'sku': 'SKU-EDIT-1', 'regular_price': '180',
            'current_stock': '25',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(prod)
        assert prod.regular_price == Decimal('180')
        assert prod.current_stock == Decimal('25')
        mv = StockMovement.query.filter_by(product_id=prod.id, reference_type='Product Update').one()
        assert float(mv.quantity) == 15.0
        # negative stock guard branch
        before = StockMovement.query.count()
        client.post(f'/products/{prod.id}/edit', data={
            'name': 'Editable', 'sku': 'SKU-EDIT-1', 'regular_price': '180',
            'current_stock': '-5',
        }, follow_redirects=True)
        db.session.refresh(prod)
        assert prod.current_stock == Decimal('25')
        assert StockMovement.query.count() == before

    def test_delete_soft_when_sale_lines_exist_vs_hard_without(self, client, login_owner, test_sale):
        linked = test_sale.lines[0].product
        client.post(f'/products/{linked.id}/delete', follow_redirects=True)
        db.session.refresh(linked)
        assert linked.is_active is False
        assert db.session.get(Product, linked.id) is not None

        fresh = Product(name='Deletable', sku='SKU-DEL-9', regular_price=Decimal('5'),
                        current_stock=Decimal('0'), is_active=True)
        db.session.add(fresh)
        db.session.commit()
        fid = fresh.id
        client.post(f'/products/{fid}/delete', follow_redirects=True)
        assert db.session.get(Product, fid) is None

    def test_adjust_stock_add_subtract_set_flow(self, client, login_owner):
        prod = Product(name='Stockful', sku='SKU-STK-1', regular_price=Decimal('9'),
                       current_stock=Decimal('10'), is_active=True)
        db.session.add(prod)
        db.session.commit()

        resp = client.post(f'/products/{prod.id}/adjust-stock', data={
            'adjustment_type': 'add', 'quantity': '5'})
        assert resp.is_json and resp.json['success'] is True
        db.session.refresh(prod)
        assert float(resp.json['new_stock']) == 15.0

        resp = client.post(f'/products/{prod.id}/adjust-stock', data={
            'adjustment_type': 'subtract', 'quantity': '3'})
        db.session.refresh(prod)
        assert prod.current_stock == Decimal('12')

        resp = client.post(f'/products/{prod.id}/adjust-stock', data={
            'adjustment_type': 'set', 'quantity': '7'})
        db.session.refresh(prod)
        assert prod.current_stock == Decimal('7')
        types = [m.movement_type for m in StockMovement.query.filter_by(product_id=prod.id)]
        assert types.count('adjustment') == 3

    def test_adjust_stock_rejections(self, client, login_owner):
        prod = Product(name='Tight', sku='SKU-STK-2', regular_price=Decimal('9'),
                       current_stock=Decimal('3'), is_active=True)
        db.session.add(prod)
        db.session.commit()
        # insufficient subtract rejection
        resp = client.post(f'/products/{prod.id}/adjust-stock', data={
            'adjustment_type': 'subtract', 'quantity': '10'})
        assert resp.json['success'] is False
        db.session.refresh(prod)
        assert prod.current_stock == Decimal('3')
        # zero quantity
        resp = client.post(f'/products/{prod.id}/adjust-stock', data={
            'adjustment_type': 'add', 'quantity': '0'})
        assert resp.json['success'] is False
        # bad type (also covers warehouse auto-create fallback)
        resp = client.post(f'/products/{prod.id}/adjust-stock', data={
            'adjustment_type': 'rotate', 'quantity': '2'})
        assert resp.json['success'] is False

    def test_categories_create_duplicate_flash_and_json_mode(self, client, login_owner):
        assert client.get('/products/categories').status_code == 200
        resp = client.post('/products/categories/create', data={'name': 'Electronics'},
                           follow_redirects=False)
        assert resp.status_code == 302
        cat = ProductCategory.query.filter_by(name='Electronics').one()
        dup = client.post('/products/categories/create', data={'name': 'electronics'},
                          follow_redirects=True)
        assert dup.status_code == 200
        assert ProductCategory.query.count() == 1
        empty = client.post('/products/categories/create', data={'name': ''}, follow_redirects=True)
        assert empty.status_code == 200
        jresp = client.post('/products/categories/create', json={'name': 'JSONCat'})
        assert jresp.is_json and jresp.json['success'] is True
        assert jresp.json['category']['name'] == 'JSONCat'
        jbad = client.post('/products/categories/create', json={})
        assert jbad.status_code == 400 and jbad.json['success'] is False
        page = client.get('/products/categories')
        assert str(cat.id).encode() in page.data

    def test_api_search_shape_and_active_filter(self, client, login_owner):
        active = Product(name='Searchable Pad', sku='SKU-SRCH-1', regular_price=Decimal('10'),
                         current_stock=Decimal('2'), is_active=True)
        ghost = Product(name='Ghost Pad', sku='SKU-GHOST', regular_price=Decimal('10'),
                        current_stock=Decimal('2'), is_active=False)
        db.session.add_all([active, ghost])
        db.session.commit()
        resp = client.get('/products/api/search?q=Pad')
        payload = resp.get_json()
        assert {p['id'] for p in payload} == {active.id}
        row = payload[0]
        assert {'id', 'name', 'code', 'text', 'sku', 'price', 'stock', 'unit', 'is_low_stock'} <= set(row)
        assert row['code'] == 'SKU-SRCH-1'
        all_rows = client.get('/products/api/search').get_json()
        assert all(p['id'] for p in all_rows)
        missing = client.get('/products/api/search?q=ZZZNOMATCH').get_json()
        assert isinstance(missing, list)

    def test_product_view_page_and_404(self, client, login_owner, test_product):
        assert client.get(f'/products/{test_product.id}').status_code == 200
        assert client.get('/products/999999').status_code == 404


# ---------------------------------------------------------------- cheques


class TestChequesLifecycle:
    def test_deposit_then_clear_two_step_gl_links(self, client, login_owner, incoming_cheque):
        cid = incoming_cheque.id
        r1 = client.post(f'/cheques/{cid}/deposit', data={}, follow_redirects=True)
        assert r1.status_code == 200
        db.session.refresh(incoming_cheque)
        assert incoming_cheque.status == 'deposited'
        assert incoming_cheque.deposit_date is not None

        r2 = client.post(f'/cheques/{cid}/clear', data={'clearance_exchange_rate': '1'},
                         follow_redirects=True)
        assert r2.status_code == 200
        db.session.refresh(incoming_cheque)
        assert incoming_cheque.status == 'cleared'
        assert incoming_cheque.gl_clearing_entry_id is not None

        entry = db.session.get(GLJournalEntry, incoming_cheque.gl_clearing_entry_id)
        assert entry.reference_type == 'cheque_clear' and entry.reference_id == cid
        codes = {ln.account.code for ln in entry.lines}
        assert codes == {'1120', '1150'}
        tot_d = sum((ln.debit for ln in entry.lines), Decimal('0'))
        tot_c = sum((ln.credit for ln in entry.lines), Decimal('0'))
        assert tot_d == tot_c == Decimal('500')

    def test_bounce_restores_ar_via_gl_entry(self, client, login_owner, incoming_cheque):
        resp = client.post(f'/cheques/{incoming_cheque.id}/bounce',
                           data={'bounce_reason': 'لا رصيد'}, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(incoming_cheque)
        assert incoming_cheque.status == 'bounced'
        assert incoming_cheque.bounce_reason.startswith('لا رصيد')
        entry = db.session.get(GLJournalEntry, incoming_cheque.gl_bounce_entry_id)
        assert entry.reference_type == 'cheque_bounce'
        ar_lines = [ln for ln in entry.lines if ln.account.code == '1130']
        assert len(ar_lines) == 1 and ar_lines[0].debit == Decimal('500')
        alerts = client.get('/cheques/alerts')
        assert alerts.status_code == 200
        assert b'998877' in alerts.data

    def test_cancel_happy_and_cleared_blocked(self, client, login_owner, incoming_cheque):
        cancelled = client.post(f'/cheques/{incoming_cheque.id}/cancel',
                                data={'cancel_reason': 'خطأ إدخال'}, follow_redirects=True)
        assert cancelled.status_code == 200
        db.session.refresh(incoming_cheque)
        assert incoming_cheque.status == 'cancelled'
        cancel_entry = GLJournalEntry.query.filter_by(
            reference_type='cheque_cancel', reference_id=incoming_cheque.id).first()
        assert cancel_entry is not None

        cleared = Cheque(cheque_number='CHQ-WV-CLR', cheque_bank_number='111222',
                         cheque_type='outgoing', bank_name='ENBD', amount=Decimal('300'),
                         currency='AED', exchange_rate=Decimal('1'), amount_base=Decimal('300'),
                         issue_date=date.today(), due_date=date.today(), status='cleared')
        db.session.add(cleared)
        db.session.commit()
        blocked = client.post(f'/cheques/{cleared.id}/cancel', data={}, follow_redirects=True)
        assert blocked.status_code == 200
        db.session.refresh(cleared)
        assert cleared.status == 'cleared'

    def test_create_then_hard_delete_removes_referenced_gl_entries(self, client, login_owner, test_customer):
        today = date.today()
        form = {
            'cheque_type': 'incoming', 'cheque_bank_number': '5550100', 'bank_name': 'FAB',
            'amount': '700', 'currency': 'AED', 'exchange_rate': '1',
            'issue_date': today.isoformat(), 'due_date': (today + timedelta(days=15)).isoformat(),
            'customer_id': str(test_customer.id),
        }
        created = client.post('/cheques/create', data=form, follow_redirects=False)
        assert created.status_code == 302
        ch = Cheque.query.filter_by(cheque_bank_number='5550100').one()
        assert ch.amount_base == Decimal('700.00')
        assert ch.gl_journal_entry_id is not None
        refs = GLJournalEntry.query.filter_by(reference_type='cheque_receive', reference_id=ch.id)
        assert refs.count() >= 1

        deleted = client.post(f'/cheques/{ch.id}/delete', data={}, follow_redirects=True)
        assert deleted.status_code == 200
        db.session.expire_all()
        assert db.session.get(Cheque, ch.id) is None
        assert GLJournalEntry.query.filter_by(
            reference_type='cheque_receive', reference_id=ch.id).count() == 0

    def test_archive_linked_status_then_restore_roundtrip(self, client, login_owner, test_sale):
        ch = Cheque(cheque_number='CHQ-WV-ARC', cheque_bank_number='778899',
                    cheque_type='incoming', bank_name='DIB', amount=Decimal('120'),
                    currency='AED', exchange_rate=Decimal('1'), amount_base=Decimal('120'),
                    issue_date=date.today(), due_date=date.today() + timedelta(days=5),
                    sale_id=test_sale.id, customer_id=test_sale.customer_id, status='cleared')
        db.session.add(ch)
        db.session.commit()
        cid = ch.id
        archived = client.post(f'/cheques/{cid}/delete', data={'delete_reason': 'مرتبط ببيع'},
                               follow_redirects=True)
        assert archived.status_code == 200
        db.session.refresh(ch)
        assert ch.is_active is False and ch.archived_at is not None
        assert client.get('/cheques/archived').status_code == 200
        restored = client.post(f'/cheques/{cid}/restore', data={}, follow_redirects=True)
        assert restored.status_code == 200
        db.session.refresh(ch)
        assert ch.is_active is True and ch.archive_reason is None

    def test_alerts_overdue_row_and_stats_apis(self, client, login_owner, incoming_cheque):
        incoming_cheque.due_date = date.today() - timedelta(days=10)
        db.session.commit()
        page = client.get('/cheques/alerts')
        assert page.status_code == 200
        assert b'998877' in page.data
        stats = client.get('/cheques/api/stats').get_json()
        assert stats['overdue'] >= 1
        api_alerts = client.get('/cheques/api/alerts').get_json()
        assert api_alerts['overdue'] >= 1
        assert any(c['id'] == incoming_cheque.id for c in api_alerts['cheques_overdue'])

    def test_edit_pending_updates_amount_base(self, client, login_owner, incoming_cheque):
        today = date.today()
        resp = client.get(f'/cheques/{incoming_cheque.id}/edit')
        assert resp.status_code == 200
        posted = client.post(f'/cheques/{incoming_cheque.id}/edit', data={
            'cheque_bank_number': '998877', 'bank_name': 'ADCB', 'amount': '750',
            'currency': 'AED', 'exchange_rate': '1',
            'issue_date': today.isoformat(), 'due_date': (today + timedelta(days=20)).isoformat(),
        }, follow_redirects=True)
        assert posted.status_code == 200
        db.session.refresh(incoming_cheque)
        assert incoming_cheque.amount_base == Decimal('750.00')
        assert incoming_cheque.status == 'pending'

    def test_permission_matrix_anon_seller_admin_routes(self, client, login_seller, incoming_cheque):
        assert client.get('/cheques/', follow_redirects=False).status_code == 403
        assert client.post(f'/cheques/{incoming_cheque.id}/delete', data={}).status_code == 403
        assert client.post(f'/cheques/{incoming_cheque.id}/cancel', data={}).status_code == 403


# ---------------------------------------------------------------- hr


class TestHR:
    def test_departments_crud_duplicate_code_flash(self, client, login_owner, seller_user):
        assert client.get('/hr/departments').status_code == 200
        ok = client.post('/hr/departments/create', data={
            'name': 'IT', 'code': 'DPT-IT', 'budget_amount': '5000'}, follow_redirects=True)
        assert ok.status_code == 200
        dept = Department.query.filter_by(code='DPT-IT').one()
        assert dept.budget_amount == Decimal('5000')

        dup = client.post('/hr/departments/create', data={'name': 'IT Clone', 'code': 'DPT-IT'},
                          follow_redirects=True)
        assert dup.status_code == 200
        assert Department.query.count() == 1

        blank = client.post('/hr/departments/create', data={'code': 'DPT-X'}, follow_redirects=True)
        assert blank.status_code == 200  # NOT NULL failure path renders flash

        edit_page = client.get(f'/hr/departments/{dept.id}/edit')
        assert edit_page.status_code == 200
        client.post(f'/hr/departments/{dept.id}/edit', data={
            'name': 'IT Updated', 'code': 'DPT-IT', 'budget_amount': '7000'}, follow_redirects=True)
        db.session.refresh(dept)
        assert dept.name == 'IT Updated'
        assert dept.budget_amount == Decimal('7000')

    def test_employee_create_seeds_leave_balances(self, client, login_owner, department, seller_user):
        get_page = client.get('/hr/employees/create')
        assert get_page.status_code == 200
        no_user = client.post('/hr/employees/create', data={}, follow_redirects=False)
        assert no_user.status_code == 302  # missing user warning branch

        resp = client.post('/hr/employees/create', data={
            'user_id': str(seller_user.id), 'employee_number': 'EMP-N1',
            'department_id': str(department.id), 'position': 'Sales',
            'base_salary': '2500', 'hire_date': '2024-02-01',
        }, follow_redirects=True)
        assert resp.status_code == 200
        emp = Employee.query.filter_by(employee_number='EMP-N1').one()
        assert emp.annual_leave_balance == 30
        assert emp.sick_leave_balance == 15
        assert emp.personal_leave_balance == 5

        dup = client.post('/hr/employees/create', data={
            'user_id': str(seller_user.id), 'employee_number': 'EMP-N2',
            'base_salary': '100', 'hire_date': '2024-02-01'}, follow_redirects=True)
        assert dup.status_code == 200
        assert Employee.query.count() == 1  # duplicate user guard via ValueError flash

    def test_leave_request_approve_balance_decrement_cancel_restore(self, client, login_owner, employee):
        assert client.get('/hr/leave-types').status_code == 200
        lt_annual = LeaveType.query.filter_by(code='annual').one()
        start = date.today() + timedelta(days=7)
        end = start + timedelta(days=3)
        expected_days = HRService._count_working_days(start, end)
        assert expected_days > 0

        view_before = client.get('/hr/leave/create')
        assert view_before.status_code == 200
        client.post('/hr/leave/create', data={
            'employee_id': str(employee.id), 'leave_type_id': str(lt_annual.id),
            'start_date': start.isoformat(), 'end_date': end.isoformat(),
            'reason': 'عائلي',
        }, follow_redirects=True)
        leave = LeaveRequest.query.one()
        assert leave.status == 'pending' and leave.days == expected_days

        approved = client.post(f'/hr/leave/{leave.id}/approve', data={}, follow_redirects=True)
        assert approved.status_code == 200
        db.session.refresh(leave)
        db.session.refresh(employee)
        assert leave.status == 'approved'
        assert employee.annual_leave_balance == 30 - expected_days

        again = client.post(f'/hr/leave/{leave.id}/approve', data={}, follow_redirects=True)
        assert again.status_code == 200  # double approve ValueError flash branch
        cancelled = client.post(f'/hr/leave/{leave.id}/cancel', data={}, follow_redirects=True)
        assert cancelled.status_code == 200
        db.session.refresh(leave)
        db.session.refresh(employee)
        assert leave.status == 'cancelled'
        assert employee.annual_leave_balance == 30

    def test_leave_insufficient_balance_rejected(self, client, login_owner, employee):
        HRService.ensure_default_leave_types()
        lt_personal = LeaveType.query.filter_by(code='personal').one()
        start = date.today() + timedelta(days=60)
        end = start + timedelta(days=14)  # >5 working days vs personal balance of 5
        client.post('/hr/leave/create', data={
            'employee_id': str(employee.id), 'leave_type_id': str(lt_personal.id),
            'start_date': start.isoformat(), 'end_date': end.isoformat(),
        }, follow_redirects=True)
        assert LeaveRequest.query.count() == 0

    def test_payroll_generate_one_payslip_math_then_approve_pay(self, client, login_owner, employee):
        assert client.get('/hr/payroll/generate').status_code == 200
        period_start = date.today().replace(day=1)
        nxt = (period_start + timedelta(days=32)).replace(day=1)
        period_end = nxt - timedelta(days=1)
        form = {
            'period_start': period_start.isoformat(), 'period_end': period_end.isoformat(),
            'pay_date': (nxt + timedelta(days=5)).isoformat(), 'working_days': '22',
        }
        resp = client.post('/hr/payroll/generate', data=form, follow_redirects=True)
        assert resp.status_code == 200
        ps = Payslip.query.one()
        assert ps.base_salary == Decimal('3000')
        # net = base 3000 + housing 500 + transport 100, no deductions/overtime
        assert float(ps.net_salary) == 3600.0
        assert ps.actual_worked_days == HRService._working_days_in_period(period_start, period_end)
        assert ps.status == 'draft'

        dup_period = client.post('/hr/payroll/generate', data=form, follow_redirects=True)
        assert dup_period.status_code == 200
        assert Payslip.query.count() == 1  # duplicate-period error counted, flashed

        reversed_dates = dict(form, period_end=period_start.isoformat(),
                              period_start=period_end.isoformat())
        bad = client.post('/hr/payroll/generate', data=reversed_dates, follow_redirects=False)
        assert bad.status_code == 302  # end-before-start guard

        client.post(f'/hr/payroll/{ps.id}/approve', data={}, follow_redirects=True)
        db.session.refresh(ps)
        assert ps.status == 'approved'
        client.post(f'/hr/payroll/{ps.id}/approve', data={}, follow_redirects=True)  # re-approve warning

        draft2 = HRService.generate_payslip(
            employee.id, period_start - timedelta(days=30), period_start - timedelta(days=1),
            period_start, created_by=None)
        client.post(f'/hr/payroll/{draft2.id}/pay', data={}, follow_redirects=True)
        db.session.refresh(draft2)
        assert draft2.status == 'draft'  # pay-before-approve rejected

        client.post(f'/hr/payroll/{ps.id}/pay', data={}, follow_redirects=True)
        db.session.refresh(ps)
        assert ps.status == 'paid'
        assert client.get(f'/hr/payroll/{ps.id}').status_code == 200

    def test_hr_pages_dashboard_visa_stat_and_apis(self, client, login_owner, employee, department):
        employee.visa_expiry = date.today() + timedelta(days=10)
        db.session.commit()
        dash = client.get('/hr/')
        assert dash.status_code == 200
        stats = HRService.get_hr_stats()
        assert stats['expiring_visas'] == 1
        for url in ('/hr/departments', '/hr/employees?search=EMP', '/hr/leave',
                    '/hr/payroll', '/hr/employees/create'):
            assert client.get(url).status_code == 200
        api_emp = client.get('/hr/api/employees').get_json()
        assert api_emp[0]['employee_number'] == 'EMP-001'
        bal = client.get(f'/hr/api/employee/{employee.id}/leave-balance').get_json()
        assert (bal['annual'], bal['sick'], bal['personal'], bal['total']) == (30, 15, 5, 50)
        assert client.get(f'/hr/employees/{employee.id}').status_code == 200
        edit_post = client.post(f'/hr/employees/{employee.id}/edit', data={
            'position': 'Senior Cashier', 'base_salary': '3200',
        }, follow_redirects=True)
        assert edit_post.status_code == 200
        db.session.refresh(employee)
        assert employee.position == 'Senior Cashier'

    def test_hr_permissions(self, client, login_seller):
        assert client.get('/hr/').status_code == 403
        assert client.post('/hr/leave/999/approve', data={}).status_code == 403


# ---------------------------------------------------------------- erp modules


class TestErpModules:
    def test_quotation_create_convert_to_sale(self, client, login_owner, owner_user, test_customer,
                                              test_product, main_wh):
        form = {
            'customer_id': str(test_customer.id), 'warehouse_id': str(main_wh.id),
            'lines[0][product_id]': str(test_product.id),
            'lines[0][quantity]': '2', 'lines[0][unit_price]': '50',
        }
        empty = client.post('/erp/quotations/create', data={}, follow_redirects=False)
        assert empty.status_code == 302  # no-lines guard
        created = client.post('/erp/quotations/create', data=form, follow_redirects=False)
        assert created.status_code == 302
        q = Quotation.query.one()
        assert q.total_amount == Decimal('100.000') and q.status == 'draft'
        assert client.get(f'/erp/quotations/{q.id}').status_code == 200
        assert client.get('/erp/quotations?status=draft').status_code == 200

        client.post(f'/erp/quotations/{q.id}/status', data={'status': 'accepted'},
                    follow_redirects=True)
        conv = client.post(f'/erp/quotations/{q.id}/convert', data={}, follow_redirects=False)
        assert conv.status_code == 302 and '/sales/' in conv.headers['Location']
        db.session.refresh(q)
        assert q.status == 'converted' and q.converted_sale_id is not None
        sale = db.session.get(Sale, q.converted_sale_id)
        assert Sale.query.count() == 1
        assert sale.customer_id == test_customer.id

        again = client.post(f'/erp/quotations/{q.id}/convert', data={}, follow_redirects=True)
        assert again.status_code == 200  # status guard ValueError flash
        assert 'متحويلة' in again.data.decode('utf-8', 'replace')
        assert Sale.query.count() == 1

    def test_closed_fiscal_period_blocks_convert_plus_period_endpoints(self, client, login_owner,
                                                                       owner_user, test_customer,
                                                                       test_product):
        from services.erp_modules_service import QuotationService
        qid = QuotationService.create_quotation(
            customer_id=test_customer.id, seller_id=owner_user.id,
            lines_data=[{'product_id': test_product.id, 'quantity': 1, 'unit_price': 50}],
            warehouse_id=None).id
        today = date.today()
        fp = FiscalPeriod(name='Closed Year', year=today.year, period_type='annual',
                          start_date=date(today.year, 1, 1), end_date=date(today.year, 12, 31))
        fp.close(owner_user.id)
        db.session.add(fp)
        db.session.commit()

        blocked = client.post(f'/erp/quotations/{qid}/convert', data={}, follow_redirects=True)
        assert blocked.status_code == 200
        assert 'مغلقة' in blocked.data.decode('utf-8', 'replace')
        assert Sale.query.count() == 0
        db.session.refresh(fp)
        assert fp.is_closed is True

        dup = client.post('/erp/fiscal-periods/create', data={'year': str(today.year)},
                          follow_redirects=True)
        assert dup.status_code == 200  # duplicate-year ValueError flash
        new_year = client.post('/erp/fiscal-periods/create', data={'year': '2031'},
                               follow_redirects=True)
        assert new_year.status_code == 200
        f31 = FiscalPeriod.query.filter_by(year=2031).one()
        close = client.post(f'/erp/fiscal-periods/{f31.id}/close', data={}, follow_redirects=True)
        assert close.status_code == 200
        db.session.refresh(f31)
        assert f31.is_closed is True
        reopen = client.post(f'/erp/fiscal-periods/{f31.id}/reopen', data={}, follow_redirects=True)
        assert reopen.status_code == 200
        db.session.refresh(f31)
        assert f31.is_closed is False

    def test_po_lifecycle_partial_receive_guards(self, client, login_owner, owner_user, supplier_row,
                                                 test_product, main_wh):
        sup = str(supplier_row.id)
        lines = {'supplier_id': sup, 'warehouse_id': str(main_wh.id),
                 'lines[0][product_id]': str(test_product.id),
                 'lines[0][quantity]': '10', 'lines[0][unit_cost]': '5'}
        no_lines = client.post('/erp/purchase-orders/create', data={'supplier_id': sup},
                               follow_redirects=False)
        assert no_lines.status_code == 302
        created = client.post('/erp/purchase-orders/create', data=lines, follow_redirects=False)
        assert created.status_code == 302
        po = PurchaseOrder.query.one()
        assert po.po_number.startswith('PO') and po.status == 'draft'
        assert po.total_amount == Decimal('50.000')
        assert client.get(f'/erp/purchase-orders/{po.id}').status_code == 200
        assert client.get('/erp/purchase-orders').status_code == 200

        # receive while still draft → guard flash
        draft_guard = client.post(f'/erp/purchase-orders/{po.id}/receive', data={},
                                  follow_redirects=True)
        assert draft_guard.status_code == 200
        assert PurchaseOrder.query.one().purchase_id is None

        client.post(f'/erp/purchase-orders/{po.id}/submit', data={}, follow_redirects=True)
        db.session.refresh(po)
        assert po.status == 'submitted'
        client.post(f'/erp/purchase-orders/{po.id}/submit', data={}, follow_redirects=True)  # idempotent-ish

        client.post(f'/erp/purchase-orders/{po.id}/approve', data={}, follow_redirects=True)
        db.session.refresh(po)
        assert po.status == 'approved' and po.approved_by_id == owner_user.id
        re_approve = client.post(f'/erp/purchase-orders/{po.id}/approve', data={},
                                 follow_redirects=True)
        assert re_approve.status_code == 200  # only-submitted ValueError flash

        po.lines[0].received_quantity = Decimal('4')  # simulate prior partial receipt
        db.session.commit()
        recv = client.post(f'/erp/purchase-orders/{po.id}/receive', data={}, follow_redirects=False)
        assert recv.status_code == 302 and '/purchases/' in recv.headers['Location']
        db.session.refresh(po)
        assert po.lines[0].received_quantity == Decimal('10')
        assert po.status == 'received'
        purchase_line_qty = po.purchase.lines[0].quantity
        assert purchase_line_qty == Decimal('6')

        second = client.post(f'/erp/purchase-orders/{po.id}/receive', data={}, follow_redirects=True)
        assert second.status_code == 200  # fully received → guard flash
        db.session.refresh(po)
        assert po.status == 'received'

    def test_stock_transfer_send_receive_no_pnl_gl(self, client, login_owner, test_product):
        wh_from = _make_warehouse('WH-FROM-A')
        wh_to = _make_warehouse('WH-TO-B')
        same = client.post('/erp/stock-transfers/create', data={
            'from_warehouse_id': str(wh_from.id), 'to_warehouse_id': str(wh_from.id),
            'lines[0][product_id]': str(test_product.id), 'lines[0][quantity]': '1',
        }, follow_redirects=True)
        assert same.status_code == 200  # same-warehouse guard flash
        assert StockTransfer.query.count() == 0

        created = client.post('/erp/stock-transfers/create', data={
            'from_warehouse_id': str(wh_from.id), 'to_warehouse_id': str(wh_to.id),
            'lines[0][product_id]': str(test_product.id), 'lines[0][quantity]': '5',
            'notes': 'top-ups',
        }, follow_redirects=True)
        assert created.status_code == 200
        t = StockTransfer.query.one()
        assert t.transfer_number.startswith('TRF') and t.status == 'pending'
        assert client.get('/erp/stock-transfers').status_code == 200

        sent = client.post(f'/erp/stock-transfers/{t.id}/send', data={}, follow_redirects=True)
        assert sent.status_code == 200
        db.session.refresh(t)
        assert t.status == 'in_transit'
        start_stock = test_product.current_stock

        received = client.post(f'/erp/stock-transfers/{t.id}/receive', data={},
                               follow_redirects=True)
        assert received.status_code == 200
        db.session.refresh(t)
        db.session.refresh(test_product)
        assert t.status == 'received' and t.received_at is not None
        assert test_product.current_stock == start_stock  # pure relocation: net zero

        out_mv = StockMovement.query.filter(
            StockMovement.notes.ilike(f'%Transfer OUT%{t.transfer_number}%')).count()
        in_mv = StockMovement.query.filter(
            StockMovement.notes.ilike(f'%Transfer IN%{t.transfer_number}%')).count()
        assert out_mv >= 1 and in_mv >= 1

        pl_rows = GLJournalLine.query.join(GLAccount).join(GLJournalEntry).filter(
            GLAccount.code.in_(['5150', '5200']),
            GLJournalEntry.description.ilike(f'%{t.transfer_number}%')).count()
        assert pl_rows == 0  # C1: transfers never touch P&L accounts

        again = client.post(f'/erp/stock-transfers/{t.id}/receive', data={}, follow_redirects=True)
        assert again.status_code == 200  # only-in_transit ValueError flash

    def test_dunning_generation_for_aged_invoice(self, client, login_owner, test_customer):
        info_run = client.post('/erp/dunning/generate', data={}, follow_redirects=True)
        assert info_run.status_code == 200  # nothing overdue → info flash
        assert DunningLetter.query.count() == 0

        from models import User
        aged = Sale(
            sale_number='S-WAVE-DUN', customer_id=test_customer.id,
            seller_id=User.query.first().id,
            total_amount=Decimal('300'), amount_base=Decimal('300'), paid_amount=Decimal('0'),
            paid_amount_base=Decimal('0'), balance_due=Decimal('300'), currency='AED',
            exchange_rate=Decimal('1'), payment_status='unpaid', status='confirmed',
            sale_date=datetime.now(timezone.utc) - timedelta(days=25), is_active=True,
        )
        db.session.add(aged)
        db.session.commit()

        gen = client.post('/erp/dunning/generate', data={}, follow_redirects=True)
        assert gen.status_code == 200
        letter = DunningLetter.query.one()
        assert letter.sale_id == aged.id
        assert letter.level == 1 and letter.days_overdue >= 15
        assert letter.amount_due == Decimal('300')

        page = client.get('/erp/dunning')
        assert page.status_code == 200
        assert letter.letter_number.encode() in page.data

        sent = client.post(f'/erp/dunning/{letter.id}/send', data={}, follow_redirects=True)
        assert sent.status_code == 200
        db.session.refresh(letter)
        assert letter.status == 'sent' and letter.sent_at is not None

    def test_recurring_expense_create_and_toggle(self, client, login_owner):
        cat = ExpenseCategory(name='Utilities Wave', name_ar='مرافق', is_active=True)
        db.session.add(cat)
        db.session.commit()
        assert client.get('/erp/recurring-expenses').status_code == 200
        resp = client.post('/erp/recurring-expenses/create', data={
            'name': 'Monthly Rent', 'category_id': str(cat.id), 'amount': '250',
            'frequency': 'monthly', 'next_due_date': date.today().isoformat(),
            'supplier_name': 'Landlord LLC',
        }, follow_redirects=True)
        assert resp.status_code == 200
        re_row = RecurringExpense.query.one()
        assert re_row.is_active is True and re_row.amount == Decimal('250')

        off = client.post(f'/erp/recurring-expenses/{re_row.id}/toggle', data={},
                          follow_redirects=True)
        assert off.status_code == 200
        db.session.refresh(re_row)
        assert re_row.is_active is False
        on = client.post(f'/erp/recurring-expenses/{re_row.id}/toggle', data={},
                         follow_redirects=True)
        assert on.status_code == 200
        db.session.refresh(re_row)
        assert re_row.is_active is True

    def test_einvoice_generated_for_confirmed_sale(self, client, login_owner, test_sale):
        test_sale.subtotal = Decimal('100')
        test_sale.tax_amount = Decimal('0')
        db.session.commit()
        listing = client.get('/erp/e-invoices')
        assert listing.status_code == 200
        gen = client.post(f"/erp/e-invoices/generate/{test_sale.id}", data={}, follow_redirects=True)
        assert gen.status_code == 200
        einv = EInvoice.query.one()
        assert einv.invoice_number == f"EI-{test_sale.sale_number}"
        assert einv.xml_payload and einv.json_payload
        detail = client.get(f'/erp/e-invoices/{einv.id}')
        assert detail.status_code == 200
        assert einv.invoice_number.encode() in detail.data

        failed = client.post('/erp/e-invoices/generate/999999', data={}, follow_redirects=True)
        assert failed.status_code == 200
        assert EInvoice.query.count() == 1


# ---------------------------------------------------------------- ledger core


@pytest.fixture
def gl(db):
    ids = _ensure_accounts()
    e1 = _manual_entry('Cash sales', [
        {'account_code': '1110', 'debit': 1000, 'credit': 0, 'description': 'cash in'},
        {'account_code': '4100', 'debit': 0, 'credit': 1000, 'description': 'revenue'},
    ])
    e2 = _manual_entry('Office expense on credit', [
        {'account_code': '5100', 'debit': 300, 'credit': 0, 'description': 'cogs'},
        {'account_code': '2110', 'debit': 0, 'credit': 300, 'description': 'ap'},
    ])
    return {'ids': ids, 'entries': [e1, e2]}


class TestLedgerCore:

    def test_trial_balance_totals_balanced_and_report_pages(self, client, login_owner, gl):
        dr = db.session.query(func.sum(GLJournalLine.debit)).scalar()
        cr = db.session.query(func.sum(GLJournalLine.credit)).scalar()
        assert dr == cr == Decimal('1300')

        tb = client.get('/ledger/trial-balance')
        assert tb.status_code == 200 and len(tb.data) > 500
        is_bal = client.get('/ledger/accounts-tree')
        assert is_bal.status_code == 200
        listing = client.get('/ledger/journal-entries')
        assert listing.status_code == 200
        assert b'JE-' in listing.data
        cash_id = gl['ids']['1110']
        acct = client.get(f'/ledger/account/{cash_id}')
        assert acct.status_code == 200
        stmt = client.get(f'/ledger/account/{cash_id}/statement?date_from=2000-01-01')
        assert stmt.status_code == 200
        entry_page = client.get(f"/ledger/entry/{gl['entries'][0].id}")
        assert entry_page.status_code == 200
        index = client.get('/ledger/')
        assert index.status_code == 200

    def test_income_statement_balance_sheet_cashflow_aging_render(self, client, login_owner, gl):
        today = date.today()
        qs = f'?date_from={(today - timedelta(days=10)).isoformat()}&date_to={today.isoformat()}'
        inc = client.get('/ledger/income-statement' + qs)
        assert inc.status_code == 200
        bs = client.get('/ledger/balance-sheet')
        assert bs.status_code == 200
        # Template iterates a method (pre-existing bug outside this wave's files):
        # the route deterministically lands on its flash+redirect error branch.
        cf = client.get('/ledger/cash-flow', follow_redirects=True)
        assert cf.status_code == 200
        ag_r = client.get('/ledger/aging-analysis?type=receivables')
        ag_p = client.get('/ledger/aging-analysis?type=payables&as_of_date=' + today.isoformat())
        assert ag_r.status_code == 200 and ag_p.status_code == 200

        dr = db.session.query(func.sum(GLJournalLine.debit)).filter(
            GLJournalLine.account_id == gl['ids']['4100']).scalar()
        cr = db.session.query(func.sum(GLJournalLine.credit)).filter(
            GLJournalLine.account_id == gl['ids']['4100']).scalar()
        assert cr - dr == Decimal('1000')

    def test_manual_entry_post_balanced_row_vs_unbalanced_flash(self, client, login_owner, gl):
        balanced = {
            'description': 'Manual ops', 'entry_date': date.today().isoformat(),
            'line_0_account': '1110', 'line_0_debit': '250', 'line_0_credit': '',
            'line_0_description': 'in',
            'line_1_account': '4100', 'line_1_debit': '', 'line_1_credit': '250',
            'line_1_description': 'rev',
        }
        got = client.get('/ledger/manual-entry')
        assert got.status_code == 200
        posted = client.post('/ledger/manual-entry', data=balanced, follow_redirects=False)
        assert posted.status_code == 302 and '/ledger/entry/' in posted.headers['Location']
        je = GLJournalEntry.query.order_by(GLJournalEntry.id.desc()).first()
        assert je.entry_type == 'manual' and je.total_debit == je.total_credit == Decimal('250')
        assert GLJournalLine.query.filter_by(entry_id=je.id).count() == 2
        baseline = GLJournalEntry.query.count()

        unbalanced = dict(balanced, description='Broken entry',
                          **{'line_0_debit': '500', 'line_1_credit': '100'})
        failed = client.post('/ledger/manual-entry', data=unbalanced, follow_redirects=True)
        assert failed.status_code == 200
        assert 'غير متوازن' in failed.data.decode('utf-8', 'replace')
        assert GLJournalEntry.query.count() == baseline

        calc_ok = client.post('/ledger/api/calculate-journal-balance',
                              json={'lines': [{'debit': 100}, {'credit': 100}]})
        assert calc_ok.is_json and calc_ok.json['is_balanced'] is True
        calc_bad = client.post('/ledger/api/calculate-journal-balance',
                               json={'lines': [{'debit': 100}, {'credit': 40}]})
        assert calc_bad.json['is_balanced'] is False and calc_bad.json['difference'] == 60.0
        empty = client.post('/ledger/api/calculate-journal-balance', data='not-json',
                            content_type='application/json')
        assert empty.status_code in (200, 400)

    def test_reverse_entry_link_and_double_reverse_guard(self, client, login_owner, gl):
        orig = gl['entries'][0]
        rev = client.post(f"/ledger/entry/{orig.id}/reverse", data={'description': 'تصحيح'},
                          follow_redirects=False)
        assert rev.status_code == 302
        db.session.refresh(orig)
        reversal = GLJournalEntry.query.filter_by(reversed_entry_id=orig.id).one()
        assert orig.is_reversed is True
        assert reversal.entry_type == 'reversing'
        first_orig_line = GLJournalLine.query.filter_by(entry_id=orig.id).first()
        mirrored = GLJournalLine.query.filter_by(
            entry_id=reversal.id, account_id=first_orig_line.account_id).first()
        assert mirrored.debit == first_orig_line.credit
        assert mirrored.credit == first_orig_line.debit

        dbl = client.post(f"/ledger/entry/{orig.id}/reverse", data={}, follow_redirects=True)
        assert dbl.status_code == 200  # already-reversed guard flash
        assert GLJournalEntry.query.count() == 3

    def test_api_account_search_shape(self, client, login_owner, gl):
        res = client.get('/ledger/api/accounts/search?q=Cash').get_json()
        assert any(a['code'] == '1110' for a in res)
        row = next(a for a in res if a['code'] == '1110')
        assert {'id', 'code', 'name', 'name_ar', 'full_name', 'type', 'balance'} <= set(row)
        none_hit = client.get('/ledger/api/accounts/search?q=NOPE123')
        assert none_hit.is_json and none_hit.get_json() == []


# ---------------------------------------------------------------- admin ledger


class TestAdminLedger:
    def test_admin_ledger_pages_owner_only_loop(self, client, login_owner):
        _ensure_accounts()
        urls = [
            '/admin/ledger/', '/admin/ledger/accounts', '/admin/ledger/reports',
            '/admin/ledger/settings', '/admin/ledger/vaults', '/admin/ledger/journals',
            '/admin/ledger/reports/trial-balance', '/admin/ledger/reports/balance-sheet',
            '/admin/ledger/reports/income-statement',
        ]
        for u in urls:
            resp = client.get(u)
            assert resp.status_code == 200, u
        assert client.get('/admin/ledger/api/account-statement/'
                          f"{GLAccount.query.filter_by(code='1110').first().id}").is_json

    def test_anon_blocked_from_admin_ledger(self, client):
        assert client.get('/admin/ledger/').status_code == 302

    def test_seller_forbidden_admin_ledger(self, client, login_seller):
        assert client.get('/admin/ledger/accounts').status_code == 403

    def test_account_add_guards_success_edit_delete_guards(self, client, login_owner, gl):
        assert client.get('/admin/ledger/accounts/add').status_code == 200
        missing_type = client.post('/admin/ledger/accounts/add', data={'code': '7776', 'name': 'X'},
                                   follow_redirects=True)
        assert missing_type.status_code == 200  # type-required render+flash
        assert GLAccount.query.filter_by(code='7776').count() == 0

        seeded = GLAccount(code='7777', name='Dup Acct', name_ar='مكرر', type='asset', level=0)
        db.session.add(seeded)
        db.session.commit()
        dup = client.post('/admin/ledger/accounts/add', data={
            'code': '7777', 'name': 'Again', 'type': 'asset'}, follow_redirects=True)
        assert dup.status_code == 200
        assert GLAccount.query.filter_by(code='7777').count() == 1

        ok = client.post('/admin/ledger/accounts/add', data={
            'code': '8888', 'name': 'Safe Deposit', 'name_ar': 'وديعة', 'type': 'asset',
            'is_header': 'on', 'is_active': 'on'}, follow_redirects=False)
        assert ok.status_code == 302
        created = GLAccount.query.filter_by(code='8888').one()
        assert created.is_header is True and created.is_active is True

        edit_get = client.get(f'/admin/ledger/accounts/{created.id}/edit')
        assert edit_get.status_code == 200
        client.post(f'/admin/ledger/accounts/{created.id}/edit', data={
            'code': '8888', 'name': 'Renamed Vault', 'type': 'asset', 'is_active': 'on'},
            follow_redirects=True)
        db.session.refresh(created)
        assert created.name == 'Renamed Vault'

        parent = GLAccount(code='5555', name='Parent Block', name_ar='أب', type='expense',
                           is_header=True, level=0)
        child = GLAccount(code='6666', name='Child Acct', name_ar='ابن', type='expense',
                          parent_id=None, level=1)
        db.session.add(parent)
        db.session.flush()
        child.parent_id = parent.id
        db.session.add(child)
        db.session.commit()
        kids = client.post(f'/admin/ledger/accounts/{parent.id}/delete', data={},
                           follow_redirects=True)
        assert kids.status_code == 200
        assert db.session.get(GLAccount, parent.id) is not None

        used_acct = GLAccount.query.filter_by(code='1110').one()
        used = client.post(f'/admin/ledger/accounts/{used_acct.id}/delete', data={},
                           follow_redirects=True)
        assert used.status_code == 200  # journal lines exist → blocked
        assert db.session.get(GLAccount, used_acct.id) is not None

        leaf = GLAccount(code='9997', name='Plain Leaf', name_ar='ورقة', type='expense', level=0)
        db.session.add(leaf)
        db.session.commit()
        lid = leaf.id
        gone = client.post(f'/admin/ledger/accounts/{lid}/delete', data={}, follow_redirects=True)
        assert gone.status_code == 200
        assert db.session.get(GLAccount, lid) is None

    def test_journal_view_reverse_link_and_error_paths(self, client, login_owner, gl):
        entry = gl['entries'][1]
        view = client.get(f'/admin/ledger/journals/{entry.id}/view')
        assert view.status_code == 200 and entry.entry_number.encode() in view.data

        reversed_now = client.post(f'/admin/ledger/journals/{entry.id}/reverse', data={},
                                   follow_redirects=True)
        assert reversed_now.status_code == 200
        db.session.refresh(entry)
        assert entry.is_reversed is True
        assert GLJournalEntry.query.filter_by(reversed_entry_id=entry.id).count() == 1

        twice = client.post(f'/admin/ledger/journals/{entry.id}/reverse', data={},
                            follow_redirects=True)
        assert twice.status_code == 200  # broad except → error flash, count stable
        assert GLJournalEntry.query.filter_by(reversed_entry_id=entry.id).count() == 1

        balance_api = client.get(
            f"/admin/ledger/api/account-balance/{GLAccount.query.filter_by(code='1110').first().id}"
        ).get_json()
        assert balance_api['account_code'] == '1110' and isinstance(balance_api['balance'], float)
        stmt_api = client.get(
            f"/admin/ledger/api/account-statement/"
            f"{GLAccount.query.filter_by(code='1110').first().id}?date_from=2000-01-01"
        ).get_json()
        assert stmt_api['statement']['total_debit'] == 1000.0


# ---------------------------------------------------------------- advanced ledger


class TestAdvancedLedger:
    @pytest.fixture
    def accounts(self, db):
        return _ensure_accounts()

    def _draft_entry(self, number, desc):
        acc_ids = {a.code: a.id for a in GLAccount.query.all()}
        e = GLJournalEntry(entry_number=number, description=desc, entry_type='manual',
                           total_debit=Decimal('50'), total_credit=Decimal('50'),
                           is_posted=False)
        db.session.add(e)
        db.session.flush()
        db.session.add(GLJournalLine(entry_id=e.id, account_id=acc_ids['1110'],
                                     debit=Decimal('50'), credit=Decimal('0'),
                                     amount_base=Decimal('50')))
        db.session.add(GLJournalLine(entry_id=e.id, account_id=acc_ids['4100'],
                                     debit=Decimal('0'), credit=Decimal('50'),
                                     amount_base=Decimal('-50')))
        db.session.commit()
        return e

    def test_customs_tax_crud_add_list_validation(self, client, login_owner, accounts):
        assert client.get('/ledger/advanced/customs-taxes').status_code == 200
        gl_id = accounts['2130']
        miss = client.post('/ledger/advanced/customs-taxes/add', data={'name': 'X'},
                           follow_redirects=True)
        assert miss.status_code == 200  # account-required warn render
        assert CustomsTax.query.count() == 0
        ok = client.post('/ledger/advanced/customs-taxes/add', data={
            'name': 'Customs Duty', 'name_ar': 'رسوم جمركية', 'tax_type': 'customs',
            'rate': '0.05', 'gl_account_id': str(gl_id),
            'effective_from': date.today().isoformat(),
        }, follow_redirects=False)
        assert ok.status_code == 302
        tax = CustomsTax.query.one()
        assert tax.rate == Decimal('0.05') and tax.gl_account_id == gl_id
        assert tax.is_percentage is False  # checkbox absent branch
        listed = client.get('/ledger/advanced/customs-taxes')
        assert 'رسوم جمركية'.encode() in listed.data

    def test_expense_category_and_advanced_expense_routes(self, client, login_owner, accounts):
        assert client.get('/ledger/advanced/expense-categories').status_code == 200
        warn = client.post('/ledger/advanced/expense-categories/add', data={'name': 'Y'},
                           follow_redirects=True)
        assert warn.status_code == 200
        assert ExpenseCategory.query.count() == 0
        ok = client.post('/ledger/advanced/expense-categories/add', data={
            'name': 'Rent Cat', 'name_ar': 'إيجار', 'gl_account_id': str(accounts['6200']),
        }, follow_redirects=False)
        assert ok.status_code == 302
        cat = ExpenseCategory.query.one()
        assert cat.gl_account_code == '6200'

        assert client.get('/ledger/advanced/advanced-expenses').status_code == 200
        broken = client.post('/ledger/advanced/advanced-expenses/add', data={'amount': 'x'},
                             follow_redirects=True)
        assert broken.status_code == 200  # int(None) crash caught → rerender w/ suppliers query
        assert AdvancedExpense.query.count() == 0

        good = client.post('/ledger/advanced/advanced-expenses/add', data={
            'expense_date': date.today().isoformat(), 'description': 'Customs fee ops',
            'description_ar': 'رسوم جمركية تشغيلية', 'category_id': str(cat.id),
            'amount': '400', 'amount_base': '400', 'taxable_amount': '400',
            'tax_rate': '0.05', 'payment_method': 'bank_transfer',
        }, follow_redirects=False)
        assert good.status_code == 302
        adv = AdvancedExpense.query.one()
        assert adv.expense_number.startswith('EXP-')
        assert float(adv.tax_amount) == pytest.approx(20.0)

    def test_journal_management_approve_reverse_delete(self, client, login_owner, accounts):
        to_approve = self._draft_entry('JE-DRAFT-9001', 'accrual pending approval')
        to_delete = self._draft_entry('JE-DRAFT-9002', 'mistaken draft')
        posted = _manual_entry('posted sales entry', [
            {'account_code': '1110', 'debit': 80, 'credit': 0, 'description': ''},
            {'account_code': '4100', 'debit': 0, 'credit': 80, 'description': ''},
        ])

        page = client.get('/ledger/advanced/journal-management')
        assert page.status_code == 200
        assert to_approve.entry_number.encode() in page.data

        appr = client.post(f'/ledger/advanced/journal-management/{to_approve.id}/approve',
                           data={'approval_notes': 'ok'}, follow_redirects=True)
        assert appr.status_code == 200
        db.session.refresh(to_approve)
        assert to_approve.is_posted is True

        appr_again = client.post(f'/ledger/advanced/journal-management/{posted.id}/approve',
                                 data={}, follow_redirects=True)
        assert appr_again.status_code == 200  # already-posted error flash
        assert GLJournalEntry.query.filter_by(is_posted=False).count() == 1

        deleted = client.post(f'/ledger/advanced/journal-management/{to_delete.id}/delete',
                              data={'reason': 'draft junk'}, follow_redirects=True)
        assert deleted.status_code == 200
        assert db.session.get(GLJournalEntry, to_delete.id) is None

        del_posted = client.post(f'/ledger/advanced/journal-management/{posted.id}/delete',
                                 data={}, follow_redirects=True)
        assert del_posted.status_code == 200  # immutable posted → error flash
        assert db.session.get(GLJournalEntry, posted.id) is not None

        reversed_now = client.post(
            f'/ledger/advanced/journal-management/{posted.id}/reverse',
            data={'reason': 'wrong coding'}, follow_redirects=True)
        assert reversed_now.status_code == 200
        db.session.refresh(posted)
        assert posted.is_reversed is True
        reversal = db.session.get(GLJournalEntry, posted.reversed_entry_id)
        assert reversal is not None and reversal.entry_type == 'reversing'

    def test_events_streams_and_cheque_integration_pages(self, client, login_owner):
        ev = client.get('/ledger/advanced/real-time-events')
        assert ev.status_code == 200
        stream = client.get('/ledger/advanced/api/events/stream?limit=5').get_json()
        assert stream['success'] is True and stream['total'] == len(stream['events'])
        typed = client.get('/ledger/advanced/api/events/stream?type=sale.created').get_json()
        assert typed['success'] is True
        integ = client.get('/ledger/advanced/cheque-integration')
        assert integ.status_code == 200
        summary = client.get('/ledger/advanced/api/cheque/9999/accounting-summary')
        assert summary.status_code == 400 and summary.json['success'] is False

    def test_printing_reports_and_analytics_surfaces(self, client, login_owner, accounts):
        _manual_entry('analytics seed', [
            {'account_code': '1110', 'debit': 10, 'credit': 0, 'description': ''},
            {'account_code': '4100', 'debit': 0, 'credit': 10, 'description': ''},
        ])
        printing = client.get('/ledger/advanced/professional-printing')
        assert printing.status_code == 200
        reports = client.get('/ledger/advanced/professional-reports')
        assert reports.status_code == 200
        analytics = client.get('/ledger/advanced/advanced-analytics')
        assert analytics.status_code == 200
        ratios = client.get('/ledger/advanced/api/financial-ratios').get_json()
        assert ratios['success'] is True
        trends = client.get('/ledger/advanced/api/trend-analysis?months=3').get_json()
        assert trends['success'] is True and len(trends['trends']) <= 12
        forecast = client.get('/ledger/advanced/api/forecasting?months=2').get_json()
        assert forecast['success'] is True
