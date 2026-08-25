"""HTTP integration tests for expenses, payments and customers routes."""
import time
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import quote_plus
from uuid import uuid4

import pytest

from extensions import db
from models import (ArchivedRecord, Cheque, Customer, Expense, ExpenseCategory,
                    GLJournalEntry, Payment, Permission, Receipt, Role,
                    Supplier, User)
from utils.helpers import generate_number


@pytest.fixture(autouse=True)
def _offline_exchange_rates():
    from services.currency_service import CurrencyService
    CurrencyService._rates_cache['AED'] = {
        'timestamp': time.time(),
        'rates': {'AED': Decimal('1'), 'ILS': Decimal('1')},
    }
    yield


def _uniq(prefix=''):
    return f'{prefix}{uuid4().hex[:8].upper()}'


@pytest.fixture
def expense_category(db):
    cat = ExpenseCategory(
        name=_uniq('إيجار-'), name_ar='إيجار', gl_account_code='6200', is_active=True,
    )
    db.session.add(cat)
    db.session.commit()
    return cat


@pytest.fixture
def supplier(db):
    sup = Supplier(name=_uniq('مورد-'), is_active=True)
    db.session.add(sup)
    db.session.commit()
    return sup


@pytest.fixture
def partner_customer(db):
    cust = Customer(name=_uniq('شريك-'), customer_type='partner', is_active=True)
    db.session.add(cust)
    db.session.commit()
    return cust


@pytest.fixture
def expense(db, owner_user, expense_category):
    exp = Expense(
        expense_number=generate_number('EXP', Expense, 'expense_number'),
        category_id=expense_category.id,
        description='صيانة مكيفات المعرض',
        amount=Decimal('500'), currency='AED',
        exchange_rate=Decimal('1'), amount_base=Decimal('500'),
        payment_method='cash', user_id=owner_user.id,
    )
    db.session.add(exp)
    db.session.commit()
    return exp


@pytest.fixture
def supplier_payment(db, owner_user, supplier):
    pay = Payment(
        payment_number=_uniq('PAY-MAN-'),
        payment_type='bill_payment', direction='outgoing',
        supplier_id=supplier.id, supplier_name=supplier.name,
        amount=Decimal('300'), currency='AED', exchange_rate=Decimal('1'),
        amount_base=Decimal('300'), payment_method='bank_transfer',
        user_id=owner_user.id,
    )
    db.session.add(pay)
    db.session.commit()
    return pay


@pytest.fixture
def manual_receipt(db, owner_user, test_customer):
    rcv = Receipt(
        receipt_number=_uniq('RCV-MAN-'),
        source_type='manual', direction='incoming',
        customer_id=test_customer.id,
        amount=Decimal('150'), currency='AED', exchange_rate=Decimal('1'),
        amount_base=Decimal('150'), payment_method='cash',
        user_id=owner_user.id,
    )
    db.session.add(rcv)
    db.session.commit()
    return rcv


def _expense_form(category_id=None, **over):
    data = {
        'description': 'إيجار المعرض الشهري',
        'amount': '500',
        'currency': 'AED',
        'payment_method': 'cash',
        'reference_number': _uniq('REF-'),
    }
    if category_id is not None:
        data['category_id'] = str(category_id)
    data.update(over)
    return data


def _voucher_form(**over):
    data = {
        'direction': 'outgoing',
        'party_type': 'supplier',
        'payment_method': 'cash',
        'currency': 'AED',
        'exchange_rate': '1',
        'date': date.today().isoformat(),
    }
    data.update(over)
    return data


def _customer_form(**over):
    tag = uuid4().hex[:8]
    data = {
        'name': f'عميل-{tag}',
        'name_ar': f'عميل-{tag}',
        'customer_type': 'merchant',
        'phone': f'+97150{tag}',
        'email': f'{tag}@example.com',
        'preferred_currency': 'AED',
    }
    data.update(over)
    return data


class TestAccessControl:
    def test_anonymous_payments_redirects_to_login(self, client):
        resp = client.get('/payments/receipts')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_seller_without_expense_permission_gets_403(self, client, login_seller):
        assert client.get('/expenses/').status_code == 403


class TestExpensesPages:
    def test_anonymous_redirects_to_login(self, client):
        resp = client.get('/expenses/')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_lists_confirmed_expense(self, client, login_owner, expense):
        resp = client.get('/expenses/')
        assert resp.status_code == 200
        assert expense.expense_number in resp.get_data(as_text=True)

    def test_index_category_filter(self, client, login_owner, db, owner_user):
        cat_a = ExpenseCategory(name=_uniq('فئة-أ-'))
        cat_b = ExpenseCategory(name=_uniq('فئة-ب-'))
        db.session.add_all([cat_a, cat_b])
        db.session.flush()
        e1 = Expense(
            expense_number=_uniq('EXP-FLT-A-'),
            category_id=cat_a.id, description='مصروف الفئة الأولى',
            amount=Decimal('10'), amount_base=Decimal('10'),
            currency='AED', payment_method='cash', user_id=owner_user.id,
        )
        e2 = Expense(
            expense_number=_uniq('EXP-FLT-B-'),
            category_id=cat_b.id, description='مصروف الفئة الثانية',
            amount=Decimal('20'), amount_base=Decimal('20'),
            currency='AED', payment_method='cash', user_id=owner_user.id,
        )
        db.session.add_all([e1, e2])
        db.session.commit()

        body = client.get(f'/expenses/?category={cat_a.id}').get_data(as_text=True)
        assert 'مصروف الفئة الأولى' in body
        assert 'مصروف الفئة الثانية' not in body

    def test_create_categories_archived_pages_render(self, client, login_owner):
        for url in ('/expenses/create', '/expenses/categories', '/expenses/archived'):
            assert client.get(url).status_code == 200


class TestExpenseCreate:
    def test_post_cash_expense_persists_with_gl_entry(self, client, login_owner, expense_category):
        resp = client.post('/expenses/create', data=_expense_form(expense_category.id))
        assert resp.status_code == 302

        exp = Expense.query.filter_by(description='إيجار المعرض الشهري').first()
        assert exp is not None
        assert exp.amount == Decimal('500')
        assert exp.amount_base == Decimal('500')
        assert exp.status == 'confirmed'

        entry = GLJournalEntry.query.filter_by(
            reference_type='Expense', reference_id=exp.id).first()
        assert entry is not None
        assert entry.total_debit == entry.total_credit

        view = client.get(f'/expenses/{exp.id}')
        assert exp.expense_number in view.get_data(as_text=True)

    def test_post_cheque_expense_creates_pending_outgoing_cheque(self, client, login_owner, expense_category):
        chq_num = _uniq('CHQ-X-')
        form = _expense_form(
            expense_category.id, payment_method='cheque', cheque_number=chq_num,
            cheque_date=(date.today() + timedelta(days=10)).isoformat(),
            bank_name='بنك أبوظبي الأول', supplier_name='مؤسسة النور',
        )
        resp = client.post('/expenses/create', data=form)
        assert resp.status_code == 302

        exp = Expense.query.filter_by(reference_number=form['reference_number']).first()
        assert exp is not None
        cheque = Cheque.query.filter_by(expense_id=exp.id).first()
        assert cheque is not None
        assert cheque.cheque_number == chq_num
        assert cheque.cheque_type == 'outgoing'
        assert cheque.status == 'pending'

    def test_post_without_category_rerenders_with_error_flash(self, client, login_owner):
        resp = client.post('/expenses/create', data=_expense_form())
        assert resp.status_code == 200
        assert 'حدث خطأ' in resp.get_data(as_text=True)
        assert Expense.query.count() == 0


class TestExpenseCategoriesApi:
    def test_create_category_via_form_redirects(self, client, login_owner):
        name = _uniq('مواد تنظيف-')
        resp = client.post('/expenses/categories/create', data={'name': name, 'name_ar': 'تنظيف'})
        assert resp.status_code == 302
        cat = ExpenseCategory.query.filter_by(name=name).first()
        assert cat is not None
        assert cat.is_active
        assert name in client.get('/expenses/categories').get_data(as_text=True)

    def test_create_category_json_returns_payload(self, client, login_owner):
        name = _uniq('فئة-JSON-')
        resp = client.post('/expenses/categories/create', json={'name': name, 'name_ar': 'فئة'})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert ExpenseCategory.query.filter_by(name=name).first().id == body['category']['id']

    def test_duplicate_category_name_json_returns_400(self, client, login_owner, db):
        name = _uniq('مكررة-')
        db.session.add(ExpenseCategory(name=name))
        db.session.commit()
        resp = client.post('/expenses/categories/create', json={'name': name})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False


class TestExpenseLifecycle:
    def test_view_and_print_pages(self, client, login_owner, expense):
        view = client.get(f'/expenses/{expense.id}')
        printed = client.get(f'/expenses/{expense.id}/print')
        assert view.status_code == 200
        assert expense.description in view.get_data(as_text=True)
        assert printed.status_code == 200
        assert expense.expense_number in printed.get_data(as_text=True)

    def test_edit_updates_amount_and_base(self, client, login_owner, expense):
        resp = client.post(f'/expenses/{expense.id}/edit', data={
            'category_id': str(expense.category_id),
            'description': 'إيجار معدّل',
            'amount': '750',
            'currency': 'AED',
            'supplier_name': 'مالك العقار',
            'notes': 'تم التعديل',
        })
        assert resp.status_code == 302
        db.session.refresh(expense)
        assert expense.description == 'إيجار معدّل'
        assert expense.amount == Decimal('750')
        assert expense.amount_base == Decimal('750')

    def test_delete_unlinked_expense_hard_deletes(self, client, login_owner, expense):
        eid = expense.id
        resp = client.post(f'/expenses/{eid}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(Expense, eid) is None
        assert GLJournalEntry.query.filter_by(
            reference_type='Expense', reference_id=eid).count() == 0

    def test_archive_hides_from_index_listed_in_archived_then_restore(self, client, login_owner, expense):
        number = expense.expense_number
        assert client.post(f'/expenses/{expense.id}/archive', follow_redirects=True).status_code == 200
        assert ArchivedRecord.query.filter_by(
            table_name='expenses', record_id=expense.id).count() == 1
        assert number not in client.get('/expenses/').get_data(as_text=True)
        assert number in client.get('/expenses/archived').get_data(as_text=True)

        client.post(f'/expenses/{expense.id}/restore', follow_redirects=True)
        assert ArchivedRecord.query.filter_by(
            table_name='expenses', record_id=expense.id).count() == 0


class TestPaymentsVoucher:
    def test_voucher_form_renders_with_party_data(self, client, login_owner, supplier, test_customer):
        resp = client.get('/payments/voucher/create')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'suppliers-data' in body
        assert 'customers-data' in body

    def test_legacy_receipts_create_redirects_to_voucher(self, client, login_owner):
        assert client.get('/payments/receipts/create').status_code == 302

    def test_outgoing_supplier_payment_cash_persists_with_gl(self, client, login_owner, supplier):
        resp = client.post('/payments/voucher/submit', data=_voucher_form(
            party_id=supplier.id, amount='300', notes='دفعة تحت الحساب'), follow_redirects=True)
        assert resp.status_code == 200

        pay = Payment.query.filter_by(supplier_id=supplier.id).first()
        assert pay is not None
        assert pay.direction == 'outgoing'
        assert pay.payment_type == 'bill_payment'
        assert pay.amount == Decimal('300')
        assert pay.amount_base == Decimal('300')
        entry = GLJournalEntry.query.filter_by(
            reference_type='Payment', reference_id=pay.id).first()
        assert entry is not None
        assert entry.total_debit == entry.total_credit

    def test_incoming_refund_from_supplier(self, client, login_owner, supplier):
        client.post('/payments/voucher/submit', data=_voucher_form(
            direction='incoming', party_type='supplier', party_id=supplier.id,
            amount='120', payment_method='bank_transfer'))
        pay = Payment.query.filter_by(supplier_id=supplier.id, direction='incoming').first()
        assert pay is not None
        assert pay.payment_type == 'refund'
        assert pay.amount_base == Decimal('120')

    def test_outgoing_refund_to_partner_customer_posts_partner_account(self, client, login_owner, partner_customer):
        client.post('/payments/voucher/submit', data=_voucher_form(
            direction='outgoing', party_type='customer', party_id=partner_customer.id,
            amount='80', payment_method='card'))
        pay = Payment.query.filter_by(customer_id=partner_customer.id).first()
        assert pay is not None
        assert pay.payment_type == 'refund'

        entry = GLJournalEntry.query.filter_by(
            reference_type='Payment', reference_id=pay.id).first()
        assert entry is not None
        codes = {line.account.code for line in entry.lines}
        assert '3350' in codes

    def test_missing_party_redirects_with_warning_and_skips(self, client, login_owner):
        before = Payment.query.count()
        resp = client.post('/payments/voucher/submit', data={
            'direction': 'outgoing', 'party_type': 'supplier'}, follow_redirects=True)
        assert resp.status_code == 200
        assert 'يرجى تعبئة جميع الحقول الإلزامية' in resp.get_data(as_text=True)
        assert Payment.query.count() == before

    def test_negative_amount_rejected_and_rolled_back(self, client, login_owner, test_customer):
        before = Receipt.query.count()
        resp = client.post('/payments/voucher/submit', data=_voucher_form(
            direction='incoming', party_type='customer', party_id=test_customer.id,
            amount='-5'), follow_redirects=True)
        assert resp.status_code == 200
        assert 'حدث خطأ أثناء حفظ السند' in resp.get_data(as_text=True)
        assert Receipt.query.count() == before


class TestReceiptsListing:
    @pytest.fixture
    def ledger_rows(self, client, login_owner, supplier, test_customer):
        client.post('/payments/voucher/submit', data=_voucher_form(
            direction='incoming', party_type='customer', party_id=test_customer.id,
            amount='200', payment_method='cash'), follow_redirects=True)
        client.post('/payments/voucher/submit', data=_voucher_form(
            party_id=supplier.id, amount='300'), follow_redirects=True)

    def test_listing_shows_both_document_types(self, client, login_owner, ledger_rows):
        body = client.get('/payments/receipts').get_data(as_text=True)
        assert Receipt.query.first().receipt_number in body
        assert Payment.query.filter_by(direction='outgoing').first().payment_number in body

    def test_search_matches_supplier_payment_only(self, client, login_owner, ledger_rows, supplier):
        body = client.get(f'/payments/receipts?search={supplier.name}').get_data(as_text=True)
        pay = Payment.query.filter_by(supplier_id=supplier.id).first()
        rcv = Receipt.query.first()
        assert pay.payment_number in body
        assert rcv.receipt_number not in body

    def test_direction_incoming_hides_outgoing_payment(self, client, login_owner, ledger_rows):
        body = client.get('/payments/receipts?direction=incoming').get_data(as_text=True)
        rcv = Receipt.query.first()
        pay = Payment.query.filter_by(direction='outgoing').first()
        assert rcv.receipt_number in body
        assert pay.payment_number not in body

    def test_seller_sees_only_own_documents(self, client, db, owner_user, test_customer):
        perm = Permission.query.filter_by(code='manage_payments').first()
        role = Role(name=_uniq('دور-'), slug='seller', permissions=[perm])
        db.session.add(role)
        db.session.flush()
        user = User(
            username=_uniq('payuser'), email=f'{_uniq("pay")}@test.com',
            full_name='Pay Seller', is_active=True, role_id=role.id,
        )
        user.set_password('PaySeller123!')
        db.session.add(user)
        db.session.flush()
        own = Receipt(
            receipt_number=_uniq('RCV-OWN-'), customer_id=test_customer.id,
            amount=Decimal('10'), amount_base=Decimal('10'),
            currency='AED', payment_method='cash', user_id=user.id,
        )
        other = Receipt(
            receipt_number=_uniq('RCV-OTH-'), customer_id=test_customer.id,
            amount=Decimal('11'), amount_base=Decimal('11'),
            currency='AED', payment_method='cash', user_id=owner_user.id,
        )
        db.session.add_all([own, other])
        db.session.commit()

        client.post('/auth/login', data={
            'username': user.username, 'password': 'PaySeller123!'}, follow_redirects=True)
        body = client.get('/payments/receipts').get_data(as_text=True)
        assert own.receipt_number in body
        assert other.receipt_number not in body


class TestSupplierPaymentDocs:
    def test_view_payment_page(self, client, login_owner, supplier_payment):
        resp = client.get(f'/payments/payments/{supplier_payment.id}')
        assert resp.status_code == 200
        assert supplier_payment.supplier_name in resp.get_data(as_text=True)

    def test_print_payment_page(self, client, login_owner, supplier_payment):
        assert client.get(f'/payments/payments/{supplier_payment.id}/print').status_code == 200

    def test_delete_unlinked_payment_hard_deletes(self, client, login_owner, supplier_payment):
        pid = supplier_payment.id
        assert client.post(f'/payments/payments/{pid}/delete', follow_redirects=True).status_code == 200
        assert db.session.get(Payment, pid) is None

    def test_archive_payment_reverses_gl_and_hides_from_listing(self, client, login_owner, supplier):
        client.post('/payments/voucher/submit', data=_voucher_form(party_id=supplier.id, amount='300'))
        pay = Payment.query.filter_by(supplier_id=supplier.id).one()
        assert client.post(f'/payments/payments/{pay.id}/archive', follow_redirects=True).status_code == 200

        assert ArchivedRecord.query.filter_by(
            table_name='payments', record_id=pay.id).count() == 1
        entries = GLJournalEntry.query.filter_by(
            reference_type='Payment', reference_id=pay.id).all()
        assert any(entry.is_reversed for entry in entries)
        assert pay.payment_number not in client.get('/payments/receipts').get_data(as_text=True)

    def test_restore_archived_payment(self, client, login_owner, supplier_payment):
        client.post(f'/payments/payments/{supplier_payment.id}/archive')
        resp = client.post(f'/payments/payments/{supplier_payment.id}/restore', follow_redirects=True)
        assert resp.status_code == 200
        assert ArchivedRecord.query.filter_by(
            table_name='payments', record_id=supplier_payment.id).count() == 0


class TestReceiptDocsAndAllocation:
    def test_view_receipt_page(self, client, login_owner, manual_receipt, test_customer):
        resp = client.get(f'/payments/receipts/{manual_receipt.id}')
        assert resp.status_code == 200
        assert test_customer.name in resp.get_data(as_text=True)

    def test_print_receipt_page(self, client, login_owner, manual_receipt):
        assert client.get(f'/payments/receipts/{manual_receipt.id}/print').status_code == 200

    def test_manual_receipt_hard_delete(self, client, login_owner, manual_receipt):
        rid = manual_receipt.id
        assert client.post(f'/payments/receipts/{rid}/delete', follow_redirects=True).status_code == 200
        assert db.session.get(Receipt, rid) is None

    def test_voucher_incoming_creates_manual_receipt(self, client, login_owner, test_customer):
        before = Receipt.query.count()
        client.post('/payments/voucher/submit', data=_voucher_form(
            direction='incoming', party_type='customer', party_id=test_customer.id, amount='90'))
        assert Receipt.query.count() == before + 1
        rcv = Receipt.query.order_by(Receipt.id.desc()).first()
        assert rcv.source_type == 'manual'
        assert rcv.direction == 'incoming'
        assert rcv.amount_base == Decimal('90')

    def test_create_from_sale_requires_method_then_allocates(self, client, login_owner, test_sale):
        page = client.get(f'/payments/create_from_sale/{test_sale.id}')
        assert page.status_code == 200

        missing = client.post(
            f'/payments/create_from_sale/{test_sale.id}',
            data={'amount': '40'}, follow_redirects=True)
        assert missing.status_code == 200
        assert 'يرجى اختيار طريقة الدفع' in missing.get_data(as_text=True)
        assert Receipt.query.count() == 0

        resp = client.post(f'/payments/create_from_sale/{test_sale.id}', data={
            'customer_id': test_sale.customer_id, 'amount': '40',
            'currency': 'AED', 'exchange_rate': '1', 'payment_method': 'cash'})
        assert resp.status_code == 302

        rcv = Receipt.query.one()
        assert rcv.source_type == 'sale'
        db.session.refresh(test_sale)
        assert test_sale.paid_amount == Decimal('40')
        assert test_sale.balance_due == Decimal('60')
        assert test_sale.payment_status == 'partial'
        assert client.get(f'/payments/receipts/{rcv.id}').status_code == 200

    def test_archive_receipt_hides_from_listing_shows_in_archived(self, client, login_owner, manual_receipt):
        number = manual_receipt.receipt_number
        assert client.post(
            f'/payments/receipts/{manual_receipt.id}/archive', follow_redirects=True).status_code == 200
        assert ArchivedRecord.query.filter_by(
            table_name='receipts', record_id=manual_receipt.id).count() == 1
        assert number not in client.get('/payments/receipts').get_data(as_text=True)
        assert number in client.get('/payments/archived').get_data(as_text=True)

    def test_restore_archived_receipt(self, client, login_owner, manual_receipt):
        client.post(f'/payments/receipts/{manual_receipt.id}/archive')
        assert client.post(
            f'/payments/receipts/{manual_receipt.id}/restore', follow_redirects=True).status_code == 200
        assert ArchivedRecord.query.filter_by(
            table_name='receipts', record_id=manual_receipt.id).count() == 0

    def test_api_customer_balance(self, client, login_owner, test_customer, test_sale):
        resp = client.get(f'/payments/api/customer-balance/{test_customer.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert abs(data['balance_aed'] - 100.0) < 0.001
        assert data['unpaid_sales'][0]['sale_number'] == test_sale.sale_number


class TestCustomersHttp:
    def test_index_search_and_type_filters(self, client, login_owner, db):
        merchant = Customer(
            name=_uniq('تاجر-'), customer_type='merchant',
            phone=_uniq('+97155'), is_active=True,
        )
        db.session.add(merchant)
        db.session.commit()

        assert merchant.name in client.get(
            f'/customers/?search={quote_plus(merchant.phone)}').get_data(as_text=True)
        assert merchant.name in client.get('/customers/?type=merchant').get_data(as_text=True)
        assert merchant.name not in client.get('/customers/?type=regular').get_data(as_text=True)

    def test_create_form_renders(self, client, login_owner):
        assert client.get('/customers/create').status_code == 200

    def test_create_post_persists_customer(self, client, login_owner):
        form = _customer_form()
        resp = client.post('/customers/create', data=form, follow_redirects=True)
        assert resp.status_code == 200
        cust = Customer.query.filter_by(email=form['email']).first()
        assert cust is not None
        assert cust.customer_type == 'merchant'
        assert cust.preferred_currency == 'AED'
        assert cust.is_active is True

    def test_create_post_invalid_email_rerenders_without_save(self, client, login_owner):
        form = _customer_form(email='not-an-email')
        resp = client.post('/customers/create', data=form)
        assert resp.status_code == 200
        assert Customer.query.filter_by(phone=form['phone']).count() == 0

    def test_view_page_shows_outstanding_balance(self, client, login_owner, test_customer, test_sale):
        resp = client.get(f'/customers/{test_customer.id}')
        assert resp.status_code == 200
        assert '100.00' in resp.get_data(as_text=True)

    def test_edit_updates_name(self, client, login_owner, test_customer):
        resp = client.post(f'/customers/{test_customer.id}/edit', data={
            'name': 'اسم محدث', 'name_ar': 'اسم محدث', 'customer_type': 'regular',
            'phone': test_customer.phone or '', 'email': '', 'address': '',
            'tax_number': '', 'preferred_currency': 'AED', 'notes': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(test_customer)
        assert test_customer.name == 'اسم محدث'

    def test_statement_shows_sale_and_refund_payment(self, client, login_owner, test_customer, test_sale):
        client.post('/payments/voucher/submit', data=_voucher_form(
            direction='outgoing', party_type='customer', party_id=test_customer.id,
            amount='25', payment_method='cash'))

        body = client.get(f'/customers/{test_customer.id}/statement').get_data(as_text=True)
        assert test_sale.sale_number in body
        assert '125.00' in body

        pay_only = client.get(
            f'/customers/{test_customer.id}/statement?transaction_type=payment').get_data(as_text=True)
        assert test_sale.sale_number not in pay_only
        assert '25.00' in pay_only

    def test_delete_fresh_customer_removes_row(self, client, login_owner, db):
        cust = Customer(name=_uniq('نظيف-'), is_active=True)
        db.session.add(cust)
        db.session.commit()
        cid = cust.id
        assert client.post(f'/customers/{cid}/delete', follow_redirects=True).status_code == 200
        assert db.session.get(Customer, cid) is None

    def test_delete_customer_with_sales_deactivates_instead(self, client, login_owner, test_customer, test_sale):
        assert client.post(
            f'/customers/{test_customer.id}/delete', follow_redirects=True).status_code == 200
        db.session.refresh(test_customer)
        assert test_customer.is_active is False
        assert test_customer.name not in client.get('/customers/').get_data(as_text=True)

    def test_api_search_finds_by_phone_and_lists_all(self, client, login_owner, test_customer):
        results = client.get(f'/customers/api/search?q={quote_plus(test_customer.phone)}').get_json()
        assert any(row['id'] == test_customer.id for row in results)
        all_rows = client.get('/customers/api/search').get_json()
        assert len(all_rows) >= 1

    def test_balance_api_lists_unpaid_sales(self, client, login_owner, test_customer, test_sale):
        data = client.get(f'/customers/{test_customer.id}/balance').get_json()
        assert abs(data['balance'] - 100.0) < 0.001
        assert data['unpaid_sales'][0]['balance_due'] == 100.0

    def test_sales_api_returns_open_invoices(self, client, login_owner, test_customer, test_sale):
        data = client.get(f'/customers/{test_customer.id}/sales').get_json()
        assert data['sales'][0]['invoice_number'] == test_sale.sale_number
        assert abs(data['sales'][0]['balance'] - 100.0) < 0.001
