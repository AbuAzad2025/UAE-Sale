"""Real backend coverage for ai_knowledge/azad_responses.py (pure logic tests,
explicit branch measurement — no 100% branch claim)."""
import pytest
from ai_knowledge.azad_responses import AzadResponses


class TestAzadResponsesReal:
    def test_error_response_string(self):
        assert isinstance(AzadResponses.get_error_response(), str)
        assert AzadResponses.get_error_response() == 'عذراً، حدث خطأ. يرجى المحاولة مرة أخرى.'

    def test_smart_response_simple(self):
        # Minimal real call with empty/default context
        result = AzadResponses.smart_response('ما هو أزاد؟', context={})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_smart_response_who_are_you(self):
        for kw in ('من أنت', 'من انت', 'who are you', 'مين انت'):
            result = AzadResponses.smart_response(kw, context={})
            # Real response should contain explanation text (not empty)
            assert isinstance(result, str)
            assert len(result) > 5

    def test_smart_response_sales_context(self):
        result = AzadResponses.smart_response('حالة المبيعات', context={'dialect': 'palestinian'})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_smart_response_unknown_returns_string(self):
        # A totally unknown phrase should still return a non-empty string
        result = AzadResponses.smart_response('xyzunknownphrase987', context={})
        assert isinstance(result, str)
        assert len(result) > 0
