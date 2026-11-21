"""Decorative ::before overlays must not swallow clicks on header buttons.

Regression: .card-header::before (animated shimmer, 200% x 200%) covered the
sales-report print button, so mouse clicks hit the header instead of the button.
"""


def test_card_header_before_has_pointer_events_none():
    import os

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(root, "static", "css", "modern-arabic-style.css")
    src = open(path, encoding="utf-8").read()
    # locate the .card-header::before rule block
    start = src.find(".card-header::before")
    assert start != -1
    block = src[start : src.find("}", start) + 1]
    assert "pointer-events: none" in block, block
