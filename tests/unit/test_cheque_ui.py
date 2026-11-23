"""Cheque pages must not duplicate numbers/parties and must be translated."""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_list_no_duplicate_number_party():
    src = open(os.path.join(ROOT, "templates", "cheques", "index.html"), encoding="utf-8").read()
    # bank number shown only when it differs from the system number
    assert "{{ cheque.cheque_number }}" in src
    assert "cheque.cheque_bank_number != cheque.cheque_number" in src
    # party shown once, with a second line only when it actually differs
    assert "cheque.drawer_name or (cheque.customer.name" in src
    assert "cheque.payee_name or (cheque.supplier.name" in src


def test_view_no_duplicate_number():
    src = open(os.path.join(ROOT, "templates", "cheques", "view.html"), encoding="utf-8").read()
    assert "cheque.cheque_bank_number != cheque.cheque_number" in src
    assert "{{ t('Cheque Number (system)') }}" not in src


def test_payment_methods_translated_in_cheque_pages():
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    assert "_PAYMENT_METHOD_LABELS" in src
