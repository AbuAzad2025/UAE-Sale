"""Unit tests — Dynamic Chart of Accounts resolver & GL hierarchy math.

Covers:
- AccountRole/AccountResolver precedence chain (tenant > global > DEFAULT_ROLE_MAP)
- Defaults equal today's literal codes (zero behavior change)
- Invalid role rejection
- get_account returns live GLAccount
- Balance sign conventions for all 5 account types (seeded manual entries)
- Header accounts excluded from posting (existing guard)
- Aggregation: parent = sum(children)
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from models import GLAccount, SystemSettings
from services.account_resolution import (
    DEFAULT_ROLE_MAP,
    AccountResolver,
    AccountRole,
)
from services.gl_service import GLService


@pytest.fixture
def core(db):
    GLService.ensure_core_accounts()
    return True


@pytest.fixture
def settings_row(db):
    return SystemSettings.get_current()


def _set_global_map(db, row, mapping):
    row.set_custom_setting('gl_role_map', mapping)
    db.session.commit()


class TestDefaultsAreTodaysCodes:
    def test_spot_check_literal_defaults(self):
        expected = {
            'CASH': '1110', 'BANK': '1120', 'AR_CONTROL': '1130',
            'INVENTORY': '1140', 'UNDER_COLLECTION': '1150',
            'AP_CONTROL': '2110', 'MERCHANTS_PAYABLE': '2115',
            'DEFERRED_CHEQUES_PAYABLE': '2120', 'TAX_PAYABLE': '2130',
            'LOANS': '2210', 'CAPITAL': '3100', 'OWNER_DRAWS': '3300',
            'PARTNERS_CURRENT': '3350', 'SALES_REVENUE': '4100',
            'COGS': '5100', 'SALARY_EXPENSE': '6100',
            'FX_GAIN': '4400', 'FX_LOSS': '6900', 'BANK_CHARGES': '6950',
        }
        for role_value, code in expected.items():
            assert DEFAULT_ROLE_MAP[role_value] == code

    def test_sales_returns_maps_to_contra_revenue_today(self):
        """مرتجعات البيع تُقيّد اليوم على حساب إيرادات المبيعات (مدين)."""
        assert DEFAULT_ROLE_MAP['SALES_RETURNS'] == '4100'

    def test_every_default_code_exists_after_ensure(self, db, core):
        for code in set(DEFAULT_ROLE_MAP.values()):
            assert GLAccount.query.filter_by(code=code).first() is not None, code

    def test_default_map_covers_all_non_header_chart_codes(self, db, core):
        leaf_codes = {
            acc.code for acc in GLAccount.query.filter_by(is_header=False).all()
        }
        assert set(DEFAULT_ROLE_MAP.values()) == leaf_codes


class TestResolverPrecedence:
    def test_default_when_no_settings(self, db, core):
        assert AccountResolver.resolve(AccountRole.CASH) == '1110'
        assert AccountResolver.resolve(AccountRole.AR_CONTROL) == '1130'

    def test_accepts_role_by_string_value(self, db, core):
        assert AccountResolver.resolve('CASH') == '1110'

    def test_invalid_role_raises(self, db, core):
        with pytest.raises(ValueError, match='Unknown account role'):
            AccountResolver.resolve('NOT_A_REAL_ROLE')

    def test_invalid_role_type_raises(self, db, core):
        with pytest.raises(ValueError):
            AccountResolver.resolve(12345)

    def test_global_override_applies(self, db, core, settings_row):
        _set_global_map(db, settings_row, {'CASH': '1121'})
        assert AccountResolver.resolve(AccountRole.CASH) == '1121'
        assert AccountResolver.resolve(AccountRole.BANK) == '1120'  # untouched

    def test_tenant_override_beats_global(self, db, core, settings_row):
        _set_global_map(db, settings_row, {'CASH': '1121'})
        settings_row.set_custom_setting('gl_role_map:7', {'CASH': '1120'})
        db.session.commit()
        assert AccountResolver.resolve(AccountRole.CASH, tenant_id=7) == '1120'
        assert AccountResolver.resolve(AccountRole.CASH) == '1121'

    def test_tenant_falls_back_to_global_for_missing_role(self, db, core, settings_row):
        _set_global_map(db, settings_row, {'CASH': '1121'})
        settings_row.set_custom_setting('gl_role_map:7', {'BANK': '1110'})
        db.session.commit()
        assert AccountResolver.resolve(AccountRole.CASH, tenant_id=7) == '1121'
        assert AccountResolver.resolve(AccountRole.BANK, tenant_id=7) == '1110'

    def test_malformed_custom_settings_json_ignored(self, db, core, settings_row):
        settings_row.custom_settings = '{definitely-not-json'
        db.session.commit()
        assert AccountResolver.resolve(AccountRole.CASH) == '1110'

    def test_non_dict_override_value_ignored(self, db, core, settings_row):
        settings_row.set_custom_setting('gl_role_map', ['CASH'])
        db.session.commit()
        assert AccountResolver.resolve(AccountRole.CASH) == '1110'

    def test_empty_override_string_falls_back(self, db, core, settings_row):
        _set_global_map(db, settings_row, {'CASH': ''})
        assert AccountResolver.resolve(AccountRole.CASH) == '1110'

    def test_resolve_has_no_write_side_effects(self, db, core, settings_row):
        before = settings_row.custom_settings
        AccountResolver.resolve(AccountRole.CASH, tenant_id=9)
        db.session.expire(settings_row)
        assert settings_row.custom_settings == before


class TestGetAccount:
    def test_returns_live_gl_account(self, db, core):
        acc = AccountResolver.get_account(AccountRole.AR_CONTROL)
        assert isinstance(acc, GLAccount)
        assert acc.code == '1130'
        assert acc.type == 'asset'

    def test_returns_none_for_missing_overridden_code(self, db, core, settings_row):
        _set_global_map(db, settings_row, {'CASH': '9999'})
        assert AccountResolver.get_account(AccountRole.CASH) is None

    def test_get_account_with_tenant_scope(self, db, core, settings_row):
        settings_row.set_custom_setting('gl_role_map:3', {'INVENTORY': '1121'})
        db.session.commit()
        acc = AccountResolver.get_account(AccountRole.INVENTORY, tenant_id=3)
        assert acc is not None and acc.code == '1121'


class TestGLServiceMigratedMappings:
    def test_payment_debit_mapping_unchanged(self, db):
        assert GLService.get_payment_debit_account('cash') == '1110'
        assert GLService.get_payment_debit_account('bank_transfer') == '1120'
        assert GLService.get_payment_debit_account('card') == '1120'
        assert GLService.get_payment_debit_account('cheque') == '1150'
        assert GLService.get_payment_debit_account('unknown') == '1110'
        assert GLService.get_payment_debit_account(None) == '1110'

    def test_payment_debit_respects_global_override(self, db, settings_row):
        _set_global_map(db, settings_row, {'BANK': '1121'})
        assert GLService.get_payment_debit_account('card') == '1121'

    def test_customer_credit_mapping_unchanged(self, db, test_customer):
        assert GLService.get_customer_credit_account(test_customer) == '1130'
        assert GLService.get_customer_credit_account(None) == '1130'
        test_customer.customer_type = 'partner'
        assert GLService.get_customer_credit_account(test_customer) == '3350'
        test_customer.customer_type = 'merchant'
        assert GLService.get_customer_credit_account(test_customer) == '2115'

    def test_customer_credit_respects_tenant_override(self, db, test_customer, settings_row):
        settings_row.set_custom_setting('gl_role_map:5', {'PARTNERS_CURRENT': '3100'})
        db.session.commit()
        test_customer.customer_type = 'partner'
        assert GLService.get_customer_credit_account(test_customer) != '3100'  # no tenant scope passed
        assert AccountResolver.resolve(AccountRole.PARTNERS_CURRENT, tenant_id=5) == '3100'


class TestBalanceSignConventions:
    def _entry(self, lines):
        return GLService.create_manual_entry(description='اختبار أرصدة', lines=lines)

    def test_asset_is_debit_nature(self, db, core):
        self._entry([
            {'account_code': '1110', 'debit': 500, 'credit': 0},
            {'account_code': '3100', 'debit': 0, 'credit': 500},
        ])
        cash = GLAccount.query.filter_by(code='1110').first()
        assert cash.get_balance() == Decimal('500')
        self._entry([
            {'account_code': '1110', 'debit': 0, 'credit': 200},
            {'account_code': '6990', 'debit': 200, 'credit': 0},
        ])
        assert cash.get_balance() == Decimal('300')

    def test_expense_is_debit_nature(self, db, core):
        self._entry([
            {'account_code': '6100', 'debit': 300, 'credit': 0},
            {'account_code': '1110', 'debit': 0, 'credit': 300},
        ])
        salaries = GLAccount.query.filter_by(code='6100').first()
        assert salaries.is_debit_nature
        assert salaries.get_balance() == Decimal('300')

    def test_liability_is_credit_nature(self, db, core):
        self._entry([
            {'account_code': '1110', 'debit': 700, 'credit': 0},
            {'account_code': '2210', 'debit': 0, 'credit': 700},
        ])
        loans = GLAccount.query.filter_by(code='2210').first()
        assert loans.get_balance() == Decimal('700')
        self._entry([
            {'account_code': '2210', 'debit': 100, 'credit': 0},
            {'account_code': '1110', 'debit': 0, 'credit': 100},
        ])
        assert loans.get_balance() == Decimal('600')

    def test_equity_is_credit_nature(self, db, core):
        self._entry([
            {'account_code': '1110', 'debit': 1000, 'credit': 0},
            {'account_code': '3100', 'debit': 0, 'credit': 1000},
        ])
        capital = GLAccount.query.filter_by(code='3100').first()
        assert capital.get_balance() == Decimal('1000')

    def test_revenue_is_credit_nature(self, db, core):
        self._entry([
            {'account_code': '1130', 'debit': 400, 'credit': 0},
            {'account_code': '4100', 'debit': 0, 'credit': 400},
        ])
        sales = GLAccount.query.filter_by(code='4100').first()
        assert not sales.is_debit_nature
        assert sales.get_balance() == Decimal('400')
        ar = GLAccount.query.filter_by(code='1130').first()
        assert ar.get_balance() == Decimal('400')

    def test_empty_account_balance_is_zero(self, db, core):
        land = GLAccount.query.filter_by(code='1210').first()
        assert land.get_balance() == 0


class TestHeaderGuardAndAggregation:
    def test_header_accounts_excluded_from_posting(self, db, core):
        with pytest.raises(ValueError, match='رئيسي'):
            GLService.create_manual_entry(
                description='ممنوع',
                lines=[
                    {'account_code': '1100', 'debit': 10, 'credit': 0},
                    {'account_code': '1110', 'debit': 0, 'credit': 10},
                ],
            )

    def test_aggregate_parent_equals_sum_children(self, db, core):
        GLService.create_manual_entry('إيداعات', [
            {'account_code': '1110', 'debit': 500, 'credit': 0},
            {'account_code': '3100', 'debit': 0, 'credit': 500},
        ])
        GLService.create_manual_entry('تحويل بنكي', [
            {'account_code': '1120', 'debit': 250, 'credit': 0},
            {'account_code': '3100', 'debit': 0, 'credit': 250},
        ])
        parent = GLAccount.query.filter_by(code='1100').first()
        children = parent.get_descendants(active_only=False)
        children_sum = sum(
            (c.get_balance() for c in children if c.code in ('1110', '1120')),
            Decimal('0'),
        )
        assert parent.get_aggregate_balance() == children_sum == Decimal('750')
        root = GLAccount.query.filter_by(code='1000').first()
        assert root.get_aggregate_balance() == Decimal('750')

    def test_aggregate_applies_sign_per_child_type(self, db, core):
        GLService.create_manual_entry('قيد مختلط', [
            {'account_code': '1110', 'debit': 400, 'credit': 0},
            {'account_code': '6100', 'debit': 150, 'credit': 0},
            {'account_code': '3100', 'debit': 0, 'credit': 550},
        ])
        opex = GLAccount.query.filter_by(code='6000').first()
        assert opex.get_aggregate_balance() == Decimal('150')
        assets_root = GLAccount.query.filter_by(code='1000').first()
        assert assets_root.get_aggregate_balance() == Decimal('400')

    def test_aggregate_excludes_inactive_branch(self, db, core):
        GLService.create_manual_entry('إيداع', [
            {'account_code': '1110', 'debit': 500, 'credit': 0},
            {'account_code': '1121', 'debit': 250, 'credit': 0},
            {'account_code': '3100', 'debit': 0, 'credit': 750},
        ])
        savings = GLAccount.query.filter_by(code='1121').first()
        savings.is_active = False
        db.session.commit()
        current = GLAccount.query.filter_by(code='1100').first()
        assert current.get_aggregate_balance(active_only=True) == Decimal('500')
        assert current.get_aggregate_balance(active_only=False) == Decimal('750')
        assert current.get_balance() == 0  # header itself never posted to

    def test_get_balance_date_filters(self, db, core):
        """حدود تواريخ الرصيد — قيد مؤرخ مستقبلًا لإزالة الغموض الزمني."""
        entry_date = datetime.now(timezone.utc) + timedelta(days=2)
        GLService.create_manual_entry('إيراد مؤجل', [
            {'account_code': '4100', 'debit': 0, 'credit': 120},
            {'account_code': '1110', 'debit': 120, 'credit': 0},
        ], entry_date=entry_date)
        sales = GLAccount.query.filter_by(code='4100').first()
        today = date.today()
        assert sales.get_balance(as_of_date=today - timedelta(days=1)) == 0
        assert sales.get_balance(as_of_date=today + timedelta(days=1)) == Decimal('120')
        assert sales.get_balance(date_from=today) == Decimal('120')
        assert sales.get_balance(date_from=today + timedelta(days=1)) == Decimal('120')
        assert sales.get_balance(date_to=today - timedelta(days=1)) == 0

    def test_descendants_all_levels_and_cycle_safe(self, db, core):
        current = GLAccount.query.filter_by(code='1100').first()
        descendants = current.get_descendants()
        codes = {a.code for a in descendants}
        assert {'1110', '1120', '1121', '1130', '1140', '1150'} <= codes
        assert '1000' not in codes  # لا يصعد للأعلى

    def test_full_name_format_preserved_and_full_path(self, db, core):
        cash = GLAccount.query.filter_by(code='1110').first()
        assert cash.full_name == '1110 - الصندوق'
        parts = cash.full_path.split(' / ')
        assert parts == ['1000', '1100', '1110']

    def test_reverse_then_aggregate_returns_to_zero_net(self, db, core):
        entry = GLService.create_manual_entry('أصل', [
            {'account_code': '1110', 'debit': 90, 'credit': 0},
            {'account_code': '3100', 'debit': 0, 'credit': 90},
        ])
        reversal = entry.reverse_entry()
        db.session.commit()
        current = GLAccount.query.filter_by(code='1100').first()
        assert current.get_aggregate_balance() == 0
        assert reversal.entry_type == 'reversing'
