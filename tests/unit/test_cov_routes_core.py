"""Core route coverage: receipts/voucher, warehouse alias, expenses, cheques.

Covers combined-coverage gaps in routes/payments.py, routes/warehouse.py,
routes/expenses.py and routes/cheques.py via HTTP POSTs (owner session).
"""
import time
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from extensions import db as _db
from models import (Cheque, Expense, ExpenseCategory, GLJournalEntry, Payment,
                    Receipt, Supplier, Warehouse)


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
        name=_uniq('مصروف-'), name_ar='مصروف', gl_account_code='6200',
        is_active=True,
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


class TestReceiptCreatePostsGL:
    def test_voucher_incoming_creates_receipt_and_gl(
            self, client, login_owner, test_customer):
        before = Receipt.query.count()
        resp = client.post('/payments/voucher/submit', data={
            'direction': 'incoming', 'party_type': 'customer',
            'party_id': str(test_customer.id), 'amount': '90',
            'currency': 'AED', 'exchange_rate': '1',
            'payment_method': 'cash',
            'date': date.today().isoformat(),
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert Receipt.query.count() == before + 1
        rcv = Receipt.query.order_by(Receipt.id.desc()).first()
        assert rcv.direction == 'incoming'
        assert rcv.amount_base == Decimal('90')
        entry = GLJournalEntry.query.filter_by(
            reference_type='Receipt', reference_id=rcv.id).first()
        assert entry is not None
        assert entry.total_debit == entry.total_credit


class TestWarehouseAliasPath:
    def test_create_and_alias_both_render(self, client, login_owner):
        assert client.get('/warehouse/create').status_code == 200
        assert client.get('/warehouse/create-warehouse').status_code == 200

    def test_alias_creates_warehouse(self, client, login_owner, db):
        name = _uniq('مستودع-')
        resp = client.post('/warehouse/create-warehouse', data={
            'name': name, 'location': 'دبي', 'code': _uniq('WH-'),
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert Warehouse.query.filter_by(name=name).count() == 1


class TestExpenseCreatePostsGL:
    def test_cash_expense_persists_with_gl_entry(
            self, client, login_owner, expense_category):
        ref = _uniq('REF-')
        resp = client.post('/expenses/create', data={
            'category_id': str(expense_category.id),
            'description': 'إيجار المعرض الشهري',
            'amount': '500', 'currency': 'AED',
            'payment_method': 'cash', 'reference_number': ref,
        })
        assert resp.status_code == 302
        exp = Expense.query.filter_by(reference_number=ref).one()
        assert exp.amount == Decimal('500')
        entry = GLJournalEntry.query.filter_by(
            reference_type='Expense', reference_id=exp.id).first()
        assert entry is not None
        assert entry.total_debit == entry.total_credit


class TestVoucherPostsLedger:
    def test_outgoing_supplier_payment_posts_ledger(
            self, client, login_owner, supplier):
        resp = client.post('/payments/voucher/submit', data={
            'direction': 'outgoing', 'party_type': 'supplier',
            'party_id': str(supplier.id), 'amount': '300',
            'currency': 'AED', 'exchange_rate': '1',
            'payment_method': 'cash', 'notes': 'دفعة تحت الحساب',
            'date': date.today().isoformat(),
        }, follow_redirects=True)
        assert resp.status_code == 200
        pay = Payment.query.filter_by(supplier_id=supplier.id).one()
        assert pay.direction == 'outgoing'
        assert pay.amount == Decimal('300')
        entry = GLJournalEntry.query.filter_by(
            reference_type='Payment', reference_id=pay.id).first()
        assert entry is not None
        assert entry.total_debit == entry.total_credit


class TestChequeCreatePostsEntryAndLinks:
    def test_incoming_cheque_links_customer_and_posts_gl(
            self, client, login_owner, test_customer):
        bank_no = _uniq('CHQ-B-')
        resp = client.post('/cheques/create', data={
            'cheque_type': 'incoming',
            'amount': '250', 'currency': 'AED', 'exchange_rate': '1',
            'issue_date': date.today().isoformat(),
            'due_date': (date.today() + timedelta(days=10)).isoformat(),
            'bank_name': 'بنك الإمارات',
            'cheque_bank_number': bank_no,
            'drawer_name': 'الساحب',
            'customer_id': str(test_customer.id),
        })
        assert resp.status_code == 302
        chq = Cheque.query.filter_by(cheque_bank_number=bank_no).one()
        assert chq.cheque_type == 'incoming'
        assert chq.customer_id == test_customer.id
        assert chq.status == 'pending'
        entries = GLJournalEntry.query.filter_by(reference_id=chq.id).all()
        assert len(entries) >= 1
        assert any(e.reference_type == 'cheque_receive' for e in entries)
        balanced = [e for e in entries if e.total_debit == e.total_credit]
        assert balanced
