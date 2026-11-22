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
        # no font-size below 11px in print documents
        import re
        small = [m for m in re.findall(r"font-size:\s*(\d+)px", src) if int(m) < 10]
        assert not small, (p, small)
