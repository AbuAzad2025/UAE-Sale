"""Quotation pages: localised tax treatment, compact branded print."""
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_tax_treatment_filter_registered():
    app_src = _read('app.py')
    assert 'def _tax_treatment_label' in app_src
    assert 'app.template_filter("tax_treatment_label")' in app_src


def test_quotation_templates_use_filter():
    src = _read('templates/erp/view_quotation.html')
    assert 'tax_treatment|tax_treatment_label' in src
    assert 'text-left' not in src
    assert 'name_ar' in src


def test_quotation_print_compact():
    src = _read('templates/erp/print_quotation.html')
    assert '.logo' in src and 'height: 48px' in src
    assert 'text-align: right' not in src
    assert 'border-inline-start' in src
    assert 'amount-words' in src or 'total-row' in src
