"""
Finance model extras — advanced accounting, budgets, card payment/vault,
invoice settings, GL account helpers.
"""

import hashlib
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import flask_login
import pytest

from models import (
    AdvancedExpense,
    Budget,
    BudgetLine,
    CardPayment,
    CardVault,
    CustomsTax,
    ExpenseCategory,
    GLAccount,
    GLJournalEntry,
    GLJournalLine,
    InvoiceSettings,
    TaxCalculationRule,
)
from models import card_vault as card_vault_module


class TestCustomsTax:
    def test_tax_type_ar_known_and_fallback(self, db):
        tax = CustomsTax(name='VAT', name_ar='ضريبة', tax_type='vat',
                         rate=Decimal('0.05'), effective_from=date(2026, 1, 1),
                         gl_account_id=1)
        assert tax.tax_type_ar == 'ضريبة القيمة المضافة'
        tax.tax_type = 'mystery'
        assert tax.tax_type_ar == 'mystery'

    def test_repr(self, db):
        tax = CustomsTax(name='Customs', name_ar='جمارك عامة', tax_type='customs',
                         rate=Decimal('0.05'))
        assert 'جمارك عامة' in repr(tax)
        assert '0.05' in repr(tax)


class TestAdvancedExpense:
    def _expense(self, **kw):
        defaults = dict(
            expense_number='AE-T1', expense_date=date(2026, 3, 1),
            description='Rent payment', description_ar='دفعة إيجار',
            category_id=1, amount=Decimal('2000'), amount_base=Decimal('2000'),
            taxable_amount=Decimal('1000'), tax_rate=Decimal('0.05'),
            customs_rate=Decimal('0.02'), created_by=1,
        )
        defaults.update(kw)
        return AdvancedExpense(**defaults)

    def test_payment_method_ar_mapping_and_fallback(self, db):
        exp = self._expense()
        exp.payment_method = 'bank_transfer'
        assert exp.payment_method_ar == 'تحويل بنكي'
        exp.payment_method = 'crypto'
        assert exp.payment_method_ar == 'crypto'

    def test_payment_and_approval_status_ar(self, db):
        exp = self._expense()
        exp.payment_status = 'partial'
        exp.approval_status = 'approved'
        assert exp.payment_status_ar == 'مدفوع جزئياً'
        assert exp.approval_status_ar == 'موافق عليه'
        exp.approval_status = 'unknown-x'
        assert exp.approval_status_ar == 'unknown-x'

    def test_calculate_taxes_applies_rates(self, db):
        exp = self._expense()
        exp.calculate_taxes()
        assert exp.tax_amount == Decimal('50')
        assert exp.customs_amount == Decimal('40')

    def test_calculate_taxes_exempt_zeroes(self, db):
        exp = self._expense(tax_exempt=True, customs_exempt=True)
        exp.calculate_taxes()
        assert exp.tax_amount == 0
        assert exp.customs_amount == 0

    def test_get_total_amount(self, db):
        exp = self._expense()
        exp.calculate_taxes()
        assert exp.get_total_amount() == Decimal('2090')

    def test_reverse_expense_creates_manual_reversal_entry(self, db, owner_user):
        cat = ExpenseCategory(name='Rent Cat', gl_account_code='6200')
        db.session.add(cat)
        db.session.flush()
        exp = AdvancedExpense(
            expense_number='AE-REV-1', expense_date=date(2026, 3, 1),
            description='Rent payment', description_ar='دفعة إيجار',
            category_id=cat.id, amount=Decimal('250'), amount_base=Decimal('250'),
            created_by=owner_user.id,
        )
        db.session.add(exp)
        db.session.commit()

        exp.reverse_expense('خطأ إدخال', owner_user)

        assert exp.is_reversed is True
        assert exp.reversal_reason == 'خطأ إدخال'
        assert exp.reversed_by == owner_user.id
        assert exp.reversed_at is not None

        entries = GLJournalEntry.query.all()
        assert len(entries) == 1
        assert entries[0].description == f'عكس مصروف {exp.expense_number}'
        lines = {ln.account.code: ln for ln in GLJournalLine.query.all()}
        assert lines['6200'].credit == Decimal('250')
        assert lines['1110'].debit == Decimal('250')

    def test_reverse_expense_twice_raises(self, db, owner_user):
        cat = ExpenseCategory(name='Rent Cat 2', gl_account_code='6200')
        db.session.add(cat)
        db.session.flush()
        exp = AdvancedExpense(
            expense_number='AE-REV-2', expense_date=date(2026, 3, 2),
            description='Rent payment', description_ar='دفعة إيجار',
            category_id=cat.id, amount=Decimal('100'), amount_base=Decimal('100'),
            created_by=owner_user.id,
        )
        db.session.add(exp)
        db.session.commit()

        exp.reverse_expense('سبب', owner_user)
        with pytest.raises(ValueError):
            exp.reverse_expense('سبب آخر', owner_user)


class TestTaxCalculationRule:
    def _rule(self, **kw):
        defaults = dict(
            name='Big amounts', name_ar='مبالغ كبيرة', rule_type='expense',
            condition_field='amount', condition_operator='>',
            condition_value='150', is_active=True,
        )
        defaults.update(kw)
        return TaxCalculationRule(**defaults)

    def _expense_stub(self):
        return SimpleNamespace(category_id=7, amount_base=Decimal('200'))

    def test_matches_inactive_rule_false(self, db):
        rule = self._rule(is_active=False)
        assert rule.matches(self._expense_stub()) is False

    def test_matches_non_expense_rule_false(self, db):
        rule = self._rule(rule_type='income')
        assert rule.matches(self._expense_stub()) is False

    def test_matches_category_condition(self, db):
        rule = self._rule(condition_field='category_id', condition_value='7',
                          condition_operator=None)
        assert rule.matches(self._expense_stub()) is True
        rule.condition_value = '8'
        assert rule.matches(self._expense_stub()) is False

    @pytest.mark.parametrize('op,value,expected', [
        ('>', '150', True),
        ('<', '250', True),
        ('>=', '200', True),
        ('<=', '199.5', False),
        ('=', '200', True),
    ])
    def test_matches_amount_operators(self, db, op, value, expected):
        rule = self._rule(condition_field='amount', condition_operator=op,
                          condition_value=value)
        assert rule.matches(self._expense_stub()) is expected

    def test_matches_unknown_field_or_operator_false(self, db):
        unknown_op = self._rule(condition_operator='%')
        assert unknown_op.matches(self._expense_stub()) is False
        unknown_field = self._rule(condition_field='supplier_id')
        assert unknown_field.matches(self._expense_stub()) is False


def _make_budget(number, **kw):
    defaults = dict(
        budget_number=number, name_ar=f'موازنة {number}', fiscal_year=2026,
        period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        total_budgeted=Decimal('1000'),
    )
    defaults.update(kw)
    return Budget(**defaults)


class TestBudget:
    def test_status_and_period_type_ar(self, db):
        b = Budget(status='active', period_type='quarterly')
        assert b.status_ar == 'نشطة'
        assert b.period_type_ar == 'ربع سنوية'
        b.status = 'weird'
        b.period_type = 'weekly'
        assert b.status_ar == 'weird'
        assert b.period_type_ar == 'weekly'

    def test_activate_from_draft(self, db):
        b = _make_budget('BG-ACT-1')
        db.session.add(b)
        db.session.commit()
        assert b.status == 'draft'
        b.activate()
        assert b.status == 'active'

    def test_activate_only_from_draft(self, db):
        b = _make_budget('BG-ACT-2')
        db.session.add(b)
        db.session.commit()
        b.activate()
        with pytest.raises(ValueError):
            b.activate()

    def test_close_requires_active(self, db):
        b = _make_budget('BG-CLO-1')
        db.session.add(b)
        db.session.commit()
        with pytest.raises(ValueError):
            b.close()

    def test_update_actuals_period_and_sign_convention(self, db):
        cash = GLAccount(code='9001', name='Cash B19', type='asset')
        loan = GLAccount(code='9002', name='Loan B19', type='liability')
        db.session.add_all([cash, loan])
        db.session.flush()
        budget = _make_budget('BG-UA-1')
        db.session.add(budget)
        db.session.flush()
        line_cash = BudgetLine(budget_id=budget.id, account_id=cash.id,
                               budgeted_amount=Decimal('400'))
        line_loan = BudgetLine(budget_id=budget.id, account_id=loan.id,
                               budgeted_amount=Decimal('600'))
        db.session.add_all([line_cash, line_loan])

        e_in = GLJournalEntry(entry_number='JE-B19A',
                              entry_date=datetime(2026, 2, 1))
        db.session.add(e_in)
        db.session.flush()
        db.session.add_all([
            GLJournalLine(entry_id=e_in.id, account_id=cash.id,
                          debit=Decimal('500'), credit=Decimal('0'),
                          amount_base=Decimal('500')),
            GLJournalLine(entry_id=e_in.id, account_id=loan.id,
                          debit=Decimal('0'), credit=Decimal('500'),
                          amount_base=Decimal('-500')),
        ])
        e_out = GLJournalEntry(entry_number='JE-B19B',
                               entry_date=datetime(2025, 12, 15))
        db.session.add(e_out)
        db.session.flush()
        db.session.add(GLJournalLine(
            entry_id=e_out.id, account_id=cash.id, debit=Decimal('999'),
            credit=Decimal('0'), amount_base=Decimal('999')))
        db.session.commit()

        budget.update_actuals()

        assert float(line_cash.actual_amount) == pytest.approx(500)
        assert float(line_cash.variance) == pytest.approx(100)
        assert float(line_cash.variance_percentage) == pytest.approx(25)
        assert float(line_loan.actual_amount) == pytest.approx(500)
        assert float(line_loan.variance) == pytest.approx(-100)
        assert float(budget.total_actual) == pytest.approx(1000)
        assert float(budget.total_variance) == pytest.approx(0)
        assert float(budget.variance_percentage) == pytest.approx(0)

    def test_close_updates_actuals_and_sets_closed(self, db):
        acc = GLAccount(code='9003', name='Cash B20', type='asset')
        db.session.add(acc)
        db.session.flush()
        budget = _make_budget('BG-CLO-2', status='active')
        db.session.add(budget)
        db.session.flush()
        line = BudgetLine(budget_id=budget.id, account_id=acc.id,
                          budgeted_amount=Decimal('200'))
        db.session.add(line)
        entry = GLJournalEntry(entry_number='JE-B20A',
                               entry_date=datetime(2026, 5, 1))
        db.session.add(entry)
        db.session.flush()
        db.session.add(GLJournalLine(
            entry_id=entry.id, account_id=acc.id, debit=Decimal('260'),
            credit=Decimal('0'), amount_base=Decimal('260')))
        db.session.commit()

        budget.close()

        assert budget.status == 'closed'
        assert float(line.actual_amount) == pytest.approx(260)


class TestBudgetLineVariance:
    @pytest.mark.parametrize('pct,status,ar', [
        (Decimal('3'), 'good', 'ممتاز'),
        (Decimal('10'), 'warning', 'يحتاج متابعة'),
        (Decimal('-20'), 'danger', 'انحراف كبير'),
    ])
    def test_variance_status_thresholds(self, db, pct, status, ar):
        line = BudgetLine(variance_percentage=pct)
        assert line.variance_status == status
        assert line.variance_status_ar == ar


class TestCardPayment:
    def _card(self, **kw):
        defaults = dict(customer_name='Ali Hassan', transaction_type='purchase',
                        package='basic', amount=Decimal('99.50'),
                        status='completed')
        defaults.update(kw)
        return CardPayment(**defaults)

    def test_get_card_display(self, db):
        cp = self._card(card_last_4='9999')
        assert cp.get_card_display() == 'Card ****9999'
        cp.card_type = 'Mastercard'
        cp.card_last_4 = '8888'
        assert cp.get_card_display() == 'Mastercard ****8888'

    @pytest.mark.parametrize('number,expected', [
        ('4111111111111111', 'Visa'),
        ('5500000000000004', 'Mastercard'),
        ('378282246310005', 'Amex'),
        ('1234567890123456', 'Unknown'),
    ])
    def test_encrypt_card_type_detection(self, db, number, expected):
        cp = self._card()
        assert cp.encrypt_card_data(number, '123', '12/27') is True
        assert cp.card_type == expected
        assert cp.card_last_4 == number[-4:]
        assert cp.card_bin == number[:6]

    def test_encrypt_short_number(self, db):
        cp = self._card()
        assert cp.encrypt_card_data('123', '9', '01/26') is True
        assert cp.card_last_4 == '123'
        assert cp.card_bin is None
        assert cp.card_type == 'Unknown'

    def test_encrypt_failure_returns_false(self, db):
        cp = self._card()
        assert cp.encrypt_card_data(None, '123', '12/27') is False
        assert cp.card_type is None
        assert cp.card_last_4 is None

    def test_decrypt_roundtrip(self, db):
        cp = self._card()
        cp.encrypt_card_data('4111111111111111', '123', '12/27')
        data = cp.decrypt_card_data()
        assert data['card_number'] == '4111111111111111'
        assert data['cvv'] == '123'
        assert data['expiry'] == '12/27'
        assert data['display'] == 'Visa 4111****1111'

    def test_decrypt_empty_and_corrupt_return_none(self, db):
        cp = self._card()
        assert cp.decrypt_card_data() is None
        cp.encrypted_data = '%%%'
        assert cp.decrypt_card_data() is None

    def test_to_dict_hides_encrypted_unless_allowed(self, db, app):
        cp = self._card()
        cp.encrypt_card_data('4111111111111111', '123', '12/27')
        db.session.add(cp)
        db.session.commit()

        d = cp.to_dict()
        assert d['card_display'] == 'Visa ****1111'
        assert d['amount'] == pytest.approx(99.5)
        assert 'decrypted' not in d
        assert 'decrypted' not in cp.to_dict(include_encrypted=True)

        app.config['ALLOW_CARD_DECRYPTION'] = True
        try:
            d2 = cp.to_dict(include_encrypted=True)
            assert d2['decrypted']['cvv'] == '123'
        finally:
            app.config.pop('ALLOW_CARD_DECRYPTION', None)

    def test_get_total_card_payments_completed_only(self, db):
        db.session.add_all([
            self._card(amount=Decimal('100')),
            self._card(amount=Decimal('200.50')),
            self._card(amount=Decimal('75'), status='pending'),
        ])
        db.session.commit()
        assert CardPayment.get_total_card_payments() == pytest.approx(300.5)

    def test_get_card_stats_by_type(self, db):
        db.session.add_all([
            self._card(card_type='Visa', amount=Decimal('100')),
            self._card(card_type='Visa', amount=Decimal('200.50')),
            self._card(card_type='Visa', amount=Decimal('999'), status='failed'),
            self._card(card_type='Amex', amount=Decimal('75'), status='pending'),
        ])
        db.session.commit()
        stats = CardPayment.get_card_stats()
        assert len(stats) == 1
        assert stats[0]['type'] == 'Visa'
        assert stats[0]['count'] == 2
        assert stats[0]['total'] == pytest.approx(300.5)


class TestCardVault:
    pytest.importorskip('cryptography', reason='CardVault encryption requires cryptography pkg')

    def test_detect_card_type_variants(self, db):
        cases = [
            ('4111111111111111', 'visa'),
            ('55-00 123456789012', 'mastercard'),
            ('349745654321098', 'amex'),
            ('6011111111111117', 'discover'),
            ('1234567890123456', 'unknown'),
        ]
        for number, expected in cases:
            assert CardVault._detect_card_type(number) == expected

    def test_hash_card_deterministic(self, db):
        expected = hashlib.sha256(b'4539148803436467').hexdigest()
        assert CardVault._hash_card('4539148803436467') == expected
        assert CardVault._hash_card(4539148803436467) == expected

    def test_cipher_requires_key(self, db, app, monkeypatch):
        monkeypatch.delitem(app.config, 'CARD_ENCRYPTION_KEY', raising=False)
        with pytest.raises(ValueError):
            CardVault._get_cipher()

    def test_cipher_requires_crypto_lib(self, monkeypatch):
        monkeypatch.setattr(card_vault_module, 'HAS_CRYPTO', False)
        with pytest.raises(RuntimeError):
            CardVault._get_cipher()

    def test_encrypt_decrypt_none_helpers(self, db, app, monkeypatch):
        monkeypatch.setitem(app.config, 'CARD_ENCRYPTION_KEY', 'unit-key-1')
        assert CardVault._encrypt(None) is None
        assert CardVault._decrypt(None) is None
        token = CardVault._encrypt(42)
        assert CardVault._decrypt(token) == '42'

    def test_set_card_data_and_masked_display(self, db, app, test_customer,
                                              monkeypatch):
        monkeypatch.setitem(app.config, 'CARD_ENCRYPTION_KEY', 'unit-key-2')
        vault = CardVault(customer_id=test_customer.id)
        vault.set_card_data('4539 1488 0343 6467', 'John Doe', '12', '2027',
                            cvv='123')
        db.session.add(vault)
        db.session.commit()

        assert vault.last_four == '6467'
        assert vault.card_type == 'visa'
        assert vault.card_hash == CardVault._hash_card('4539148803436467')
        assert vault.get_card_number() == '****-****-****-6467'
        assert vault.get_expiry() == '12/2027'

    def test_owner_can_decrypt_number_and_cvv(self, db, app, owner_user,
                                              test_customer, monkeypatch):
        monkeypatch.setitem(app.config, 'CARD_ENCRYPTION_KEY', 'unit-key-3')
        monkeypatch.setitem(app.config, 'ALLOW_CARD_DECRYPTION', True)
        monkeypatch.setattr(flask_login, 'current_user', owner_user)
        vault = CardVault(customer_id=test_customer.id)
        vault.set_card_data('4539148803436467', 'John Doe', '12', '2027',
                            cvv='123')
        db.session.add(vault)
        db.session.commit()

        assert vault.get_card_number() == '4539-1488-0343-6467'
        assert vault.get_cvv() == '123'
        assert vault.get_cardholder_name() == 'John Doe'
        data = vault.to_dict(include_sensitive=True)
        assert data['card_number'] == '4539-1488-0343-6467'
        assert data['cvv'] == '123'
        assert data['expiry'] == '12/2027'

    def test_sensitive_fields_hidden_for_non_owner(self, db, seller_user,
                                                   test_customer, app,
                                                   monkeypatch):
        monkeypatch.setitem(app.config, 'CARD_ENCRYPTION_KEY', 'unit-key-4')
        monkeypatch.setattr(flask_login, 'current_user', seller_user)
        vault = CardVault(customer_id=test_customer.id)
        vault.set_card_data('4539148803436467', 'John Doe', cvv='123')
        db.session.add(vault)
        db.session.commit()

        assert vault.get_cvv() == '***'
        data = vault.to_dict(include_sensitive=True)
        assert 'card_number' not in data
        assert 'cvv' not in data

    def test_owner_without_cvv_and_partial_expiry(self, db, app, owner_user,
                                                  test_customer, monkeypatch):
        monkeypatch.setitem(app.config, 'CARD_ENCRYPTION_KEY', 'unit-key-5')
        monkeypatch.setattr(flask_login, 'current_user', owner_user)
        vault = CardVault(customer_id=test_customer.id)
        vault.set_card_data('4539148803436467', 'John Doe', expiry_month='08')
        db.session.add(vault)
        db.session.commit()

        assert vault.get_cvv() is None
        assert vault.get_expiry() is None

    def test_mark_used(self, db, app, test_customer, monkeypatch):
        monkeypatch.setitem(app.config, 'CARD_ENCRYPTION_KEY', 'unit-key-6')
        vault = CardVault(customer_id=test_customer.id)
        vault.set_card_data('4539148803436467', 'John Doe')
        db.session.add(vault)
        db.session.commit()
        before = vault.usage_count or 0

        vault.mark_used()

        assert vault.usage_count == before + 1
        assert vault.last_used is not None


class TestGLAccountExtras:
    def test_full_name_prefers_arabic(self, db):
        acc = GLAccount(code='7001', name='Cash X', name_ar='نقدية')
        assert acc.full_name == '7001 - نقدية'

    def test_full_name_english_fallback(self, db):
        acc = GLAccount(code='7002', name='Bank X')
        assert acc.full_name == '7002 - Bank X'

    def test_type_ar_mapping_and_fallback(self, db):
        assert GLAccount(type='asset').type_ar == 'أصول'
        assert GLAccount(type='revenue').type_ar == 'إيرادات'
        assert GLAccount(type='odd').type_ar == 'odd'

    def _seed_entry(self, db, number, lines_spec, when=datetime(2026, 4, 1)):
        entry = GLJournalEntry(
            entry_number=number, entry_date=when,
            total_debit=sum(a for _, a in lines_spec if a > 0),
            total_credit=sum(-a for _, a in lines_spec if a < 0))
        db.session.add(entry)
        db.session.flush()
        for account, amount in lines_spec:
            if amount >= 0:
                debit, credit = amount, Decimal('0')
            else:
                debit, credit = Decimal('0'), -amount
            db.session.add(GLJournalLine(
                entry_id=entry.id, account_id=account.id, debit=debit,
                credit=credit, amount_base=amount))
        db.session.commit()
        return entry

    def test_get_balance_asset_debit_minus_credit(self, db):
        cash = GLAccount(code='8001', name='Cash G', type='asset')
        revenue = GLAccount(code='8002', name='Rev G', type='revenue')
        db.session.add_all([cash, revenue])
        db.session.flush()
        self._seed_entry(db, 'JE-GA-1', [(cash, Decimal('500')),
                                         (revenue, Decimal('-500'))])
        assert cash.get_balance() == Decimal('500')

    def test_get_balance_liability_reversed(self, db):
        cash = GLAccount(code='8003', name='Cash G2', type='asset')
        loan = GLAccount(code='8004', name='Loan G', type='liability')
        db.session.add_all([cash, loan])
        db.session.flush()
        self._seed_entry(db, 'JE-GA-2', [(cash, Decimal('750')),
                                         (loan, Decimal('-750'))])
        assert loan.get_balance() == Decimal('750')

    def test_get_balance_empty_account(self, db):
        acc = GLAccount(code='8005', name='Empty', type='expense')
        db.session.add(acc)
        db.session.commit()
        assert acc.get_balance() == 0

    def test_get_children_recursive(self, db):
        parent = GLAccount(code='8100', name='Assets R', type='asset')
        child = GLAccount(code='8101', name='Current', type='asset',
                          parent=parent)
        grandchild = GLAccount(code='8102', name='Cash RC', type='asset',
                               parent=child)
        db.session.add_all([parent, child, grandchild])
        db.session.commit()

        result = parent.get_children_recursive()
        assert [a.code for a in result] == ['8101', '8102']


class TestGLJournalEntryExtras:
    def test_entry_type_ar_mapping_and_fallback(self, db):
        entry = GLJournalEntry(entry_number='JE-X1', entry_type='manual')
        assert entry.entry_type_ar == 'قيد يدوي'
        entry.entry_type = 'zzz'
        assert entry.entry_type_ar == 'zzz'


class TestInvoiceSettingsModel:
    def test_column_defaults(self, db):
        settings = InvoiceSettings()
        db.session.add(settings)
        db.session.commit()

        assert settings.company_name_ar == 'شركة أزاد'
        assert settings.company_name_en == 'Azad Company'
        assert settings.header_color == '#667eea'
        assert settings.accent_color == '#764ba2'
        assert settings.paper_size == 'A4'
        assert settings.orientation == 'portrait'
        assert settings.default_language == 'ar'
        assert settings.active_template == 'modern'
        assert settings.show_logo is True
        assert settings.enable_qr_code is True
        assert settings.enable_watermark is False
        assert settings.watermark_opacity == Decimal('0.10')
        assert settings.is_active is True

    def test_get_active_creates_default(self, db):
        assert InvoiceSettings.query.count() == 0
        settings = InvoiceSettings.get_active()
        db.session.commit()
        assert settings.id is not None
        assert settings.company_name_en == 'Azad Company'
        assert InvoiceSettings.query.count() == 1

    def test_get_active_reuses_existing_row(self, db):
        first = InvoiceSettings(company_name_en='Custom Name')
        db.session.add(first)
        db.session.commit()
        again = InvoiceSettings.get_active()
        assert again.id == first.id
        assert again.company_name_en == 'Custom Name'

    def test_get_active_recreates_after_deactivation(self, db):
        old = InvoiceSettings.get_active()
        db.session.commit()
        old.is_active = False
        db.session.commit()

        fresh = InvoiceSettings.get_active()
        db.session.commit()
        assert fresh.id != old.id
        assert fresh.is_active is True
        assert fresh.company_name_ar == 'شركة أزاد'

    def test_to_dict_shape(self, db):
        settings = InvoiceSettings(email='info@azad.com', tax_number='TRN-1')
        db.session.add(settings)
        db.session.commit()
        data = settings.to_dict()
        assert data['company_name_ar'] == 'شركة أزاد'
        assert data['email'] == 'info@azad.com'
        assert data['tax_number'] == 'TRN-1'
        assert data['enable_qr_code'] is True
        assert data['show_barcode'] is True
