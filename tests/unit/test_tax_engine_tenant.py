"""التينانت/Dولة/الشامل فوق TaxEngine الأساسي (لا يغيّر معاييره)."""
from decimal import Decimal


def test_engine_exclusive_adds_tax():
    from services.tax_engine import calc
    tax, total = calc(Decimal('100'), Decimal('0'), Decimal('0'), Decimal('5'), inclusive=False)
    assert tax == Decimal('5.000')
    assert total == Decimal('105.000')


def test_engine_inclusive_extracts_tax():
    from services.tax_engine import calc
    tax, total = calc(Decimal('105'), Decimal('0'), Decimal('0'), Decimal('5'), inclusive=True)
    assert total == Decimal('105.000')
    assert tax == Decimal('5.000')


def test_engine_country_preset():
    from services.tax_engine import country_rate
    assert country_rate('AE') == Decimal('5.00')
    assert country_rate('SA') == Decimal('15.00')


def test_resolve_tenant_overrides():
    from services.tax_engine import resolve
    tenant = type('T', (), {'enable_tax': True, 'default_tax_rate': Decimal('5'),
                            'tax_country': 'AE', 'tax_inclusive': True})()
    rate, inc = resolve(tenant, explicit_rate=None)
    assert rate == Decimal('5') and inc is True
    rate2, inc2 = resolve(tenant, explicit_rate=Decimal('0'), explicit_inclusive=False)
    assert rate2 == Decimal('0') and inc2 is False


def test_resolve_disabled():
    from services.tax_engine import resolve
    tenant = type('T', (), {'enable_tax': False, 'default_tax_rate': Decimal('5')})()
    rate, inc = resolve(tenant)
    assert rate == Decimal('0')


def test_sale_calculate_totals_inclusive():
    from models.sale import Sale, SaleLine
    import decimal
    s = Sale()
    line = SaleLine()
    line.line_total = decimal.Decimal('105')
    s.lines = [line]
    s.discount_amount = decimal.Decimal('0')
    s.shipping_cost = decimal.Decimal('0')
    s.tax_rate = decimal.Decimal('5')
    s.tax_inclusive = True
    s.exchange_rate = decimal.Decimal('1')
    s.calculate_totals()
    assert s.tax_amount == decimal.Decimal('5.00')
    assert s.total_amount == decimal.Decimal('105.000')


def test_missing_tenant_does_not_silently_use_explicit_tax_rate(db):
    import pytest
    from models.tenant_scope import get_current_tenant_id, set_current_tenant_id
    from services.sale_service import SaleService
    from utils.errors import ValidationError

    previous = get_current_tenant_id()
    try:
        set_current_tenant_id(9999999)
        with pytest.raises(ValidationError):
            SaleService._resolve_tax(Decimal('5'))
    finally:
        set_current_tenant_id(previous)
