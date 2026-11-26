"""Payment receipts must show the supplier (not an empty customer box),
and amount-in-words must contrast with the coloured amount panel."""

import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RCP = os.path.join(ROOT, "templates", "receipts")


def _src(name):
    return open(os.path.join(RCP, f"{name}.html"), encoding="utf-8").read()


def test_templates_use_party_not_customer():
    for name in ("modern", "classic", "gulf", "minimal", "simple"):
        src = _src(name)
        assert "receipt.customer" not in src, name
        assert "party.name" in src, name
        assert "party.label" in src, name


def test_route_passes_party_for_payment_and_receipt():
    src = open(os.path.join(ROOT, "routes", "payments.py"), encoding="utf-8").read()
    assert "def _receipt_party(doc, is_payment)" in src
    # both print routes pass party
    assert src.count("party=_receipt_party(") >= 3


def test_supplier_details_translation_keys():
    from utils.i18n import TRANSLATIONS

    assert TRANSLATIONS["Supplier Details"]["ar"] == "بيانات المورد"


def test_green_amount_panels_use_white_words():
    for name in ("modern", "minimal"):
        src = _src(name)
        assert 'class="amount-words"' in src
        assert "color:#ffffff" in src, name
