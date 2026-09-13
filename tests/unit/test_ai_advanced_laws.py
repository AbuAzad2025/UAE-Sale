from ai_knowledge.advanced_laws import AdvancedLaws

def test_tax_info_palestine():
    assert '16%' in AdvancedLaws.get_tax_info('palestine', 'vat')

def test_tax_info_uae():
    result = AdvancedLaws.get_tax_info('uae', 'corporate')
    assert '9%' in result

def test_shipping_info_sea():
    result = AdvancedLaws.get_shipping_info('sea')
    assert 'بحر' in result

def test_customs_uae_has_5_percent():
    result = AdvancedLaws.get_customs_info('uae')
    assert '5%' in result

def test_quality_standards_food():
    result = AdvancedLaws.get_quality_standards('food')
    assert 'حلال' in result
