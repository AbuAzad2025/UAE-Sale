"""Print toolbar template buttons must lay out horizontally, not stacked.

Regression: .template-buttons had no CSS rule, so the template switcher
buttons stacked vertically and overflowed the print header bar.
"""
import os


def test_template_buttons_rule_exists():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(root, "templates", "base_print.html")
    src = open(path, encoding="utf-8").read()
    start = src.find(".template-buttons {")
    assert start != -1
    block = src[start : src.find("}", start) + 1]
    assert "display: flex" in block
    assert "flex-direction: row" in block


def test_print_templates_use_translation():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    src = open(os.path.join(root, "routes", "payments.py"), encoding="utf-8").read()
    # No hardcoded Arabic template labels should remain
    for word in ('"مودرن"', '"كلاسيك"', '"خليجي"', '"بسيط"', '"مبسط"'):
        assert word not in src, word
