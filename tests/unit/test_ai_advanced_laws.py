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

def test_tax_info_israel_vat():
    assert '17%' in AdvancedLaws.get_tax_info('israel', 'vat')

def test_tax_info_israel_corporate():
    assert '23%' in AdvancedLaws.get_tax_info('israel', 'corporate')

def test_tax_info_uae_vat():
    assert '5%' in AdvancedLaws.get_tax_info('uae', 'vat')

def test_tax_info_unknown_country():
    assert AdvancedLaws.get_tax_info('france', 'vat') == "معلومات ضريبية غير متاحة لهذه الدولة"

def test_shipping_info_air():
    assert 'أسرع طريقة' in AdvancedLaws.get_shipping_info('air')

def test_shipping_info_land():
    assert 'متوسط السرعة' in AdvancedLaws.get_shipping_info('land')

def test_shipping_info_unknown():
    assert AdvancedLaws.get_shipping_info('space') == "نوع الشحن غير محدد"

def test_customs_info_saudi():
    assert '15%' in AdvancedLaws.get_customs_info('saudi')

def test_customs_info_unknown():
    assert AdvancedLaws.get_customs_info('france') == "معلومات جمركية غير متاحة لهذا البلد"

def test_quality_standards_electronics():
    assert 'CE' in AdvancedLaws.get_quality_standards('electronics')

def test_quality_standards_textiles():
    assert 'معايير الألوان' in AdvancedLaws.get_quality_standards('textiles')

def test_quality_standards_unknown():
    assert 'ISO 9001' in AdvancedLaws.get_quality_standards('machinery')