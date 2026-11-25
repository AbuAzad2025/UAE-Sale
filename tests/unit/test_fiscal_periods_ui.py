"""Fiscal periods UI + global language direction regressions."""
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_english_pages_are_not_forced_to_rtl():
    """Arabic base themes force `body{direction:rtl}`; the last stylesheet
    must restore LTR when <html dir="ltr"> is set by the language switch."""
    css = _read("static/css/accessibility.css")
    assert 'html[dir="ltr"] body' in css
    assert "direction: ltr" in css
    assert "text-align: left" in css


def test_footer_address_follows_ui_language():
    src = _read("templates/base.html")
    assert "current_tenant.address_en if current_language == 'en'" in src
    assert "current_tenant.address_ar or current_tenant.address_en" in src


def test_fiscal_period_table_is_responsive_and_localised():
    src = _read("templates/erp/fiscal_periods.html")
    assert "table-responsive" in src
    assert "('closed' if p.is_closed else 'open')|status_label" in src
    assert "t('Fiscal Year')" in src
    assert "p.status|status_label" not in src
