"""Offline exchange-rate handling for the expense form."""
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_api_reports_rate_source_and_manual_requirement():
    src = _read('routes/api.py')
    assert 'get_rate_provenance' in src
    assert 'manual_input_required' in src
    assert 'source == "fallback"' in src


def test_currency_service_tracks_rate_source():
    src = _read('services/currency_service.py')
    assert '_rates_source' in src
    assert 'get_rate_provenance' in src
    assert '"live"' in src and '"fallback"' in src


def test_expense_form_has_offline_rate_modal():
    src = _read('templates/expenses/create.html')
    assert 'id="manualRateModal"' in src
    assert 'manual_input_required' in src
    assert 'askManualRate' in src
    assert 'removeAttr(\'readonly\')' in src
    assert 'id="manualRateInput"' in src
