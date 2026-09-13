def test_advanced_analytics_class_has_get_tax_info():
    from ai_knowledge.advanced_laws import AdvancedLaws
    assert AdvancedLaws.get_tax_info('uae', 'corporate') is not None

def test_advanced_analytics_service_class_exists():
    from services.advanced_analytics import AdvancedFinancialAnalytics
    # Minimal smoke test: method exists and returns dict structure
    result = AdvancedFinancialAnalytics.get_financial_ratios()
    assert isinstance(result, dict)
    assert 'profitability' in result
