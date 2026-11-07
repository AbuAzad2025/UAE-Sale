from decimal import Decimal


def test_ct_disabled_zero():
    from services.corporate_tax import compute_ct
    t = type('T', (), {'corp_tax_enabled': False})()
    assert compute_ct(Decimal('500000'), t) == Decimal('0')


def test_ct_uae_9_above_threshold():
    from services.corporate_tax import compute_ct
    t = type('T', (), {'corp_tax_enabled': True, 'corp_tax_threshold': Decimal('375000'),
                       'corp_tax_rate': Decimal('9')})()
    assert compute_ct(Decimal('375000'), t) == Decimal('0')
    assert compute_ct(Decimal('475000'), t) == Decimal('9000.00')


def test_allowed_currencies_parse():
    from services.corporate_tax import allowed_currency_list
    t = type('T', (), {'allowed_currencies': 'AED, usd, SAR '})()
    assert allowed_currency_list(t) == ['AED', 'USD', 'SAR']
    t2 = type('T', (), {'allowed_currencies': None})()
    assert allowed_currency_list(t2) == []
