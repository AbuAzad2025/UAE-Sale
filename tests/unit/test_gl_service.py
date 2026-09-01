"""Unit tests for GLService — دفتر الأستاذ العام."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from models import GLAccount
from services.gl_service import GLService


@pytest.fixture
def core_accounts(db):
    GLService.ensure_core_accounts()
    return True


class TestAccountMapping:
    def test_payment_debit_accounts(self, db):
        assert GLService.get_payment_debit_account('cash') == '1110'
        assert GLService.get_payment_debit_account('bank_transfer') == '1120'
        assert GLService.get_payment_debit_account('card') == '1120'
        assert GLService.get_payment_debit_account('cheque') == '1150'
        assert GLService.get_payment_debit_account('unknown_method') == '1110'
        assert GLService.get_payment_debit_account(None) == '1110'

    def test_customer_credit_accounts(self, db, test_customer):
        assert GLService.get_customer_credit_account(test_customer) == '1130'
        assert GLService.get_customer_credit_account(None) == '1130'

        test_customer.customer_type = 'partner'
        assert GLService.get_customer_credit_account(test_customer) == '3350'

        test_customer.customer_type = 'merchant'
        assert GLService.get_customer_credit_account(test_customer) == '1130'


class TestEnsureCoreAccounts:
    def test_creates_core_accounts(self, db, core_accounts):
        cash = GLAccount.query.filter_by(code='1110').first()
        ar = GLAccount.query.filter_by(code='1130').first()
        inventory = GLAccount.query.filter_by(code='1140').first()
        assert cash is not None and cash.type == 'asset'
        assert ar is not None
        assert inventory is not None

    def test_idempotent(self, db, core_accounts):
        count_before = GLAccount.query.count()
        GLService.ensure_core_accounts()
        assert GLAccount.query.count() == count_before


class TestPostEntry:
    def test_balanced_entry_posts(self, db, core_accounts):
        entry = GLService.post_entry(
            lines=[
                {'account': '1110', 'debit': 500, 'credit': 0, 'description': 'إيداع'},
                {'account': '1130', 'debit': 0, 'credit': 500, 'description': 'تحصيل ذمم'},
            ],
            description='تحصيل من عميل',
            reference_type='Receipt', reference_id=1,
        )
        assert entry.id is not None
        assert entry.entry_number.startswith('JE-')
        assert entry.total_debit == Decimal('500')
        assert entry.total_credit == Decimal('500')
        assert entry.lines.count() == 2

    def test_unbalanced_entry_raises(self, db, core_accounts):
        with pytest.raises(ValueError, match='not balanced'):
            GLService.post_entry(lines=[
                {'account': '1110', 'debit': 100, 'credit': 0},
                {'account': '1130', 'debit': 0, 'credit': 90},
            ])

    def test_unknown_account_raises(self, db, core_accounts):
        with pytest.raises(ValueError, match='9999'):
            GLService.post_entry(lines=[
                {'account': '1110', 'debit': 10, 'credit': 0},
                {'account': '9999', 'debit': 0, 'credit': 10},
            ])

    def test_exchange_rate_computes_amount_base(self, db, core_accounts):
        entry = GLService.post_entry(
            lines=[
                {'account': '1110', 'debit': 100, 'credit': 0},
                {'account': '1130', 'debit': 0, 'credit': 100},
            ],
            currency='USD', exchange_rate=Decimal('3.67'),
        )
        assert entry.exchange_rate == Decimal('3.67')
        debit_line = next(ln for ln in entry.lines if ln.debit > 0)
        assert debit_line.amount_base == Decimal('367.00')


class TestCreateManualEntry:
    def test_manual_entry_created(self, db, core_accounts):
        entry = GLService.create_manual_entry(
            description='تسوية يدوية',
            lines=[
                {'account_code': '1110', 'debit': 75, 'credit': 0},
                {'account_code': '1130', 'debit': 0, 'credit': 75},
            ],
            notes='تسوية نهاية شهر',
        )
        assert entry.entry_type == 'manual'
        assert entry.total_debit == Decimal('75')

    def test_header_account_rejected(self, db, core_accounts):
        with pytest.raises(ValueError, match='رئيسي'):
            GLService.create_manual_entry(
                description='خطأ',
                lines=[
                    {'account_code': '1100', 'debit': 10, 'credit': 0},
                    {'account_code': '1110', 'debit': 0, 'credit': 10},
                ],
            )

    def test_unbalanced_rejected_arabic(self, db, core_accounts):
        with pytest.raises(ValueError, match='غير متوازن'):
            GLService.create_manual_entry(
                description='خطأ',
                lines=[
                    {'account_code': '1110', 'debit': 50, 'credit': 0},
                    {'account_code': '1130', 'debit': 0, 'credit': 40},
                ],
            )


class TestCreateJournalEntry:
    def test_typed_entry_created(self, db, core_accounts):
        entry = GLService.create_journal_entry(
            entry_type='sale', description='فاتورة بيع',
            lines=[
                {'account_code': '1130', 'debit': 200, 'credit': 0},
                {'account_code': '4100', 'debit': 0, 'credit': 200},
            ],
            reference_type='Sale', reference_id=9,
        )
        assert entry.reference_type == 'Sale'
        assert entry.reference_id == 9

    def test_unbalanced_raises(self, db, core_accounts):
        with pytest.raises(ValueError, match='not balanced'):
            GLService.create_journal_entry(
                entry_type='sale', description='خاطئ',
                lines=[
                    {'account_code': '1130', 'debit': 10, 'credit': 0},
                    {'account_code': '4100', 'debit': 0, 'credit': 5},
                ],
            )


class TestAccountStatement:
    def test_statement_balances_and_flow(self, db, core_accounts):
        cash = GLAccount.query.filter_by(code='1110').first()

        GLService.create_manual_entry('إيداع أول', [
            {'account_code': '1110', 'debit': 500, 'credit': 0},
            {'account_code': '1130', 'debit': 0, 'credit': 500},
        ])
        GLService.create_manual_entry('سحب', [
            {'account_code': '1110', 'debit': 0, 'credit': 200},
            {'account_code': '1130', 'debit': 200, 'credit': 0},
        ])

        statement = GLService.get_account_statement(cash.id)
        assert statement['opening_balance'] == 0
        assert len(statement['transactions']) == 2
        assert statement['total_debit'] == 500
        assert statement['total_credit'] == 200
        assert statement['closing_balance'] == 300

        tx = statement['transactions'][1]
        assert tx['balance'] == 300
        assert tx['debit'] == 0 and tx['credit'] == 200

    def test_statement_with_date_filter(self, db, core_accounts):
        cash = GLAccount.query.filter_by(code='1110').first()
        GLService.create_manual_entry('قديم', [
            {'account_code': '1110', 'debit': 500, 'credit': 0},
            {'account_code': '1130', 'debit': 0, 'credit': 500},
        ])
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
        statement = GLService.get_account_statement(cash.id, date_from=tomorrow)
        assert statement['transactions'] == []
        assert statement['opening_balance'] == 500
        assert statement['closing_balance'] == 500


class TestAccountsTree:
    def test_tree_built_from_roots(self, db, core_accounts):
        tree = GLService.get_accounts_tree()
        assert len(tree) >= 1
        roots_codes = {node['code'] for node in tree}
        assert '1000' in roots_codes
        assets = next(n for n in tree if n['code'] == '1000')
        child_codes = {c['code'] for c in assets['children']}
        assert '1100' in child_codes
