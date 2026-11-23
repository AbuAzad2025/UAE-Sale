"""Print templates must show amount-in-words in the current language only.

Regression: all 10 receipt/invoice templates rendered both amount_words_ar and
amount_words_en unconditionally, violating the "no Arabic in EN / no English
in AR" rule.
"""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _files():
    for d in ("receipts", "invoices"):
        folder = os.path.join(ROOT, "templates", d)
        for f in os.listdir(folder):
            if f.endswith(".html") and not f.startswith("_"):
                yield os.path.join(folder, f)


def test_single_language_amount_words():
    for p in _files():
        src = open(p, encoding="utf-8").read()
        assert "amount_words_ar if current_language ==" in src, p
        # both rendered unconditionally must be gone
        assert "{% if amount_words_en %}" not in src, p
        assert "{% if amount_words_ar %}" not in src, p


def test_no_minuscule_fonts():
    for p in _files():
        src = open(p, encoding="utf-8").read()
        # no font-size below 11px in print documents (incl. decimals like 8.5px)
        import re
        small = [m for m in re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", src) if float(m) < 10]
        assert not small, (p, small)


def test_toolbar_buttons_readable():
    src = open(os.path.join(ROOT, "templates", "base_print.html"), encoding="utf-8").read()
    assert "font-size: 13px" in src
    assert "min-height: 40px" in src
    assert "min-width: 86px" in src


def test_real_print_preview_button():
    src = open(os.path.join(ROOT, "templates", "base_print.html"), encoding="utf-8").read()
    assert "openPrintPreview()" in src
    assert "print-preview-modal" in src
    assert "printFromPreview()" in src
    assert "preview-mode" in src
    assert "print-color-adjust: exact" in src


def test_header_footer_repeat_across_pages():
    src = open(os.path.join(ROOT, "templates", "base_print.html"), encoding="utf-8").read()
    # CSS: fixed header/footer repeat on every printed page
    assert ".document .receipt-header" in src
    assert "position: fixed !important" in src
    assert "bottom: var(--repeat-azad-h" in src
    # JS: height measurement so content never overlaps repeated parts
    assert "prepareRepeatingHeaderFooter" in src
    assert "--repeat-head-h" in src and "--repeat-foot-h" in src
    assert "beforeprint" in src
