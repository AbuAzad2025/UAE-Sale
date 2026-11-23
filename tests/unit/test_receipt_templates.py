"""Receipt print templates: tenant brand, readability, no platform leaks."""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RCP = os.path.join(ROOT, "templates", "receipts")


def _src(name):
    return open(os.path.join(RCP, f"{name}.html"), encoding="utf-8").read()


def test_standalone_templates_no_receipt_print_class():
    """receipt-print class triggers accessibility.css forced blue theme."""
    for name in ("classic", "gulf", "minimal"):
        assert "receipt-print" not in _src(name), name


def test_source_date_guarded():
    """Supplier payments have no source date; must show '—', not 'None'."""
    for name in ("modern", "classic", "gulf", "minimal", "simple"):
        src = _src(name)
        assert "source_info.date or" in src, name


def test_payment_number_fallback():
    for name in ("modern", "classic", "gulf", "minimal", "simple"):
        src = _src(name)
        assert "receipt.payment_number" in src, name


def test_ewallet_translated():
    src = _src("simple")
    assert "{{ t(\"E-Wallet\") }}" in src
    # The raw 'e_wallet' must not be rendered as output text (only as a comparison)
    assert "{{ receipt.payment_method }}" not in src


def test_no_platform_identity_hardcoded():
    """Templates must not hardcode Azad platform name/email as company identity."""
    for name in ("modern", "classic", "gulf", "minimal", "simple"):
        src = _src(name)
        assert "أزاد للأنظمة" not in src, name
        assert "awladmohd@hotmail.com" not in src, name


def test_print_body_readable_font():
    src = open(os.path.join(ROOT, "templates", "base_print.html"), encoding="utf-8").read()
    assert "font-size: 14px" in src
