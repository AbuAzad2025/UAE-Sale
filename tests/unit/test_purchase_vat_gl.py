"""Purchase mixed VAT: per-line treatments + reverse charge + non-recoverable."""
from decimal import Decimal
from datetime import datetime

import pytest

from models import Purchase, PurchaseLine, Product, ProductCategory, Warehouse
from services.sale_tax_calculation import sale_tax_totals_mixed
from services.purchase_gl import build_purchase_gl_lines


def _line(total, treatment='standard'):
    return PurchaseLine(line_total=Decimal(str(total)),
                        tax_treatment=treatment,
                        quantity=Decimal('1'), unit_cost=Decimal(str(total)))


class TestPurchaseMixedTax:
    def test_exclusive_mixed_buckets(self):
        lines = [_line(100, 'standard'), _line(50, 'zero'), _line(80, 'exempt')]
        p = Purchase(lines=lines, discount_amount=Decimal('0'),
                     tax_rate=Decimal('5'), tax_inclusive=False,
                     tax_treatment='standard', subtotal=Decimal('230'),
                     total_amount=Decimal('0'), amount_base=Decimal('0'),
                     currency='AED', exchange_rate=Decimal('1'))
        p.calculate_totals()
        assert p.tax_amount == Decimal('5.00')
        assert p.total_amount == Decimal('235.000')

    def test_inclusive_standard_bucket(self):
        lines = [_line(105, 'standard'), _line(0, 'zero')]
        p = Purchase(lines=lines, discount_amount=Decimal('0'),
                     tax_rate=Decimal('5'), tax_inclusive=True,
                     tax_treatment='standard', subtotal=Decimal('105'),
                     total_amount=Decimal('0'), amount_base=Decimal('0'),
                     currency='AED', exchange_rate=Decimal('1'))
        p.calculate_totals()
        assert p.tax_amount == Decimal('5.00')
        assert p.total_amount == Decimal('105.000')

    def test_invoice_exempt_overrides_standard_lines(self):
        lines = [_line(200, 'standard')]
        p = Purchase(lines=lines, discount_amount=Decimal('0'),
                     tax_rate=Decimal('15'), tax_inclusive=False,
                     tax_treatment='exempt', subtotal=Decimal('200'),
                     total_amount=Decimal('0'), amount_base=Decimal('0'),
                     currency='AED', exchange_rate=Decimal('1'))
        p.calculate_totals()
        assert p.tax_amount == Decimal('0')
        assert p.total_amount == Decimal('200.000')

    def test_zero_lines_no_vat_with_inclusive(self):
        lines = [_line(100, 'zero'), _line(100, 'exempt')]
        p = Purchase(lines=lines, discount_amount=Decimal('0'),
                     tax_rate=Decimal('5'), tax_inclusive=True,
                     tax_treatment='standard', subtotal=Decimal('200'),
                     total_amount=Decimal('0'), amount_base=Decimal('0'),
                     currency='AED', exchange_rate=Decimal('1'))
        p.calculate_totals()
        assert p.tax_amount == Decimal('0')
        assert p.total_amount == Decimal('200.000')


class _StubPurchase:
    def __init__(self, **kwargs):
        defaults = dict(
            tenant_id=None, purchase_number='P-TEST', supplier_name='Supplier X',
            total_amount=Decimal('105'), tax_amount=Decimal('5'),
            vat_recoverable=True, reverse_charge=False,
        )
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


def _sum(lines, side, key):
    return sum(line[key] for line in lines if side in line)


class TestPurchaseGL:
    def test_standard_recoverable_posts_input_vat(self):
        from services.account_resolution import AccountResolver, AccountRole
        p = _StubPurchase()
        lines = build_purchase_gl_lines(p)
        inv = AccountResolver.resolve(AccountRole.INVENTORY)
        ap = AccountResolver.resolve(AccountRole.AP_CONTROL)
        vat = AccountResolver.resolve(AccountRole.TAX_PAYABLE)
        debits = sum(l.get('debit', Decimal('0')) for l in lines)
        credits = sum(l.get('credit', Decimal('0')) for l in lines)
        assert debits == credits
        by_account = {}
        for l in lines:
            by_account.setdefault(l['account'], {})[l.get('side', 'x')] = l
        ap_line = next(l for l in lines if l['account'] == ap)
        assert ap_line['credit'] == Decimal('105')
        vat_line = next(l for l in lines if l['account'] == vat)
        assert vat_line['debit'] == Decimal('5')

    def test_non_recoverable_no_vat_account_in_entry(self):
        p = _StubPurchase(vat_recoverable=False)
        lines = build_purchase_gl_lines(p)
        from services.account_resolution import AccountResolver, AccountRole
        inv = AccountResolver.resolve(AccountRole.INVENTORY)
        ap = AccountResolver.resolve(AccountRole.AP_CONTROL)
        vat = AccountResolver.resolve(AccountRole.TAX_PAYABLE)
        accounts = [l['account'] for l in lines]
        assert vat not in accounts
        inv_line = next(l for l in lines if l['account'] == inv)
        ap_line = next(l for l in lines if l['account'] == ap)
        assert inv_line['debit'] == Decimal('105')
        assert ap_line['credit'] == Decimal('105')

    def test_reverse_charge_balanced_vat_pair_and_net_ap(self):
        p = _StubPurchase(reverse_charge=True)
        lines = build_purchase_gl_lines(p)
        from services.account_resolution import AccountResolver, AccountRole
        ap = AccountResolver.resolve(AccountRole.AP_CONTROL)
        ap_line = next(l for l in lines if l['account'] == ap)
        # المورد: بالمبلغ الصافي فقط — لا دائن بالضريبة
        assert ap_line['credit'] == Decimal('100')
        vat_lines = [l for l in lines if l['account'] == AccountResolver.resolve(AccountRole.TAX_PAYABLE)]
        assert len(vat_lines) == 2
        debits = sum(l.get('debit', Decimal('0')) for l in lines)
        credits = sum(l.get('credit', Decimal('0')) for l in lines)
        assert debits == credits == Decimal('105')

    def test_reverse_charge_non_recoverable_charges_tax_to_cost(self):
        p = _StubPurchase(reverse_charge=True, vat_recoverable=False)
        lines = build_purchase_gl_lines(p)
        from services.account_resolution import AccountResolver, AccountRole
        inv = AccountResolver.resolve(AccountRole.INVENTORY)
        ap = AccountResolver.resolve(AccountRole.AP_CONTROL)
        vat = AccountResolver.resolve(AccountRole.TAX_PAYABLE)
        accounts = [l['account'] for l in lines]
        # الضريبة تكاليف: تحمّل على المخزون (debit gross) + output vat دائن
        inv_line = next(l for l in lines if l['account'] == inv)
        assert inv_line['debit'] == Decimal('105')
        ap_line = next(l for l in lines if l['account'] == ap)
        assert ap_line['credit'] == Decimal('100')
        vat_lines = [l for l in lines if l['account'] == vat]
        assert len(vat_lines) == 1 and vat_lines[0]['credit'] == Decimal('5')
        debits = sum(l.get('debit', Decimal('0')) for l in lines)
        credits = sum(l.get('credit', Decimal('0')) for l in lines)
        assert debits == credits
