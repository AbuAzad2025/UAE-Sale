"""Advanced-modules UI regressions: localised codes, no raw English in AR."""
import json
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_frequency_and_category_filters_registered():
    src = _read("app.py")
    assert 'app.template_filter("frequency_label")' in src
    assert 'app.template_filter("expense_category_label")' in src
    assert '"monthly": {"ar": "شهري", "en": "Monthly"}' in src
    assert '"rent": {"ar": "إيجار", "en": "Rent"}' in src


def test_recurring_expenses_use_localised_filters():
    src = _read("templates/erp/recurring_expenses.html")
    assert "re.frequency|frequency_label" in src
    assert "expense_category_label" in src
    assert ">{{ re.frequency }}<" not in src
    assert "table-responsive" in src


def test_lots_localise_product_and_warehouse():
    src = _read("templates/erp/lots.html")
    assert "l.product.name_ar" in src
    assert "l.warehouse.name_ar" in src
    assert "l.product.name }}" not in src
    assert "table-responsive" in src


def test_stock_transfer_loop_uses_row_alias():
    """The loop variable is `tr`; `t` is the translation function and used to
    crash the whole page with UndefinedError on transfer_date."""
    src = _read("templates/erp/stock_transfers.html")
    assert "{% for tr in transfers %}" in src
    assert "tr.transfer_date" in src
    assert "t.transfer_date" not in src
    assert "t.transfer_number" not in src
    assert "table-responsive" in src


def test_letterheads_helper_text_is_localised():
    src = _read("templates/owner/invoice_settings.html")
    for key in (
        "Company official name in English",
        "Complete company address in English",
        "e.g: Azad Smart Systems",
        "e.g: Abu Dhabi - UAE",
    ):
        assert f"{{{{ t('{key}') }}}}" in src
    assert " - Tax Registration Number" not in src


def test_purchase_delete_reverses_stock_movements():
    src = _read("routes/purchases.py")
    assert "def _reverse_purchase_stock" in src
    assert src.count("_reverse_purchase_stock(purchase)") >= 2
    assert 'reference_type="Purchase"' in src


def test_ledger_account_types_are_localised():
    app_src = _read("app.py")
    for code, ar in (
        ("asset", "أصل"),
        ("liability", "خصم"),
        ("equity", "حقوق الملكية"),
        ("revenue", "إيراد"),
        ("expense", "مصروف"),
    ):
        assert f'"{code}": "{ar}"' in app_src
    for rel in ("templates/ledger/index.html", "templates/ledger/account_ledger.html"):
        assert "{{ account.type }}" not in _read(rel)


def test_expense_category_options_are_language_aware():
    for rel in ("templates/expenses/create.html", "templates/expenses/edit.html"):
        src = _read(rel)
        assert "name_ar }} - {{ category.name }}" not in src
        assert "expense_category_label" in src
        assert "current_language" in src


def test_flash_translation_prefers_specific_key():
    src = _read("app.py")
    assert "sorted(_map.items(), key=lambda kv: len(kv[0]), reverse=True)" in src
    translations = json.load(
        open(os.path.join(ROOT, "utils", "flash_translations.json"), encoding="utf-8")
    )
    assert translations["✅ تم إضافة الشيك {cheque.cheque_bank_number} بنجاح"] == (
        "✅ Cheque {cheque.cheque_bank_number} was added successfully"
    )


def test_lot_creation_flash_is_not_payment_flash():
    """The lot route reuses the Arabic phrase 'دفعة'; its EN flash must not
    say 'Payment created' (a copy/paste error in the translation map)."""
    translations = json.load(
        open(os.path.join(ROOT, "utils", "flash_translations.json"), encoding="utf-8")
    )
    assert translations["✅ تم إنشاء الدفعة"] == "✅ Lot created"
    assert "✅ تم إنشاء الدفعة" in _read("routes/erp_modules.py")


def test_common_status_codes_are_translated():
    src = _read("app.py")
    for code in ("received", "in_transit", "partially_received", "submitted"):
        assert f'"{code}"' in src
    assert '"received": "مستلم"' in src
    assert '"in_transit": "في الطريق"' in src
