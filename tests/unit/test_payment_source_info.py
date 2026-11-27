"""Supplier receipts identify the purchase actually linked to the payment."""

from datetime import date
from decimal import Decimal

import pytest
from models import Payment, Purchase


@pytest.fixture
def linked_payment(db, posting_tenant, owner_user):
    purchase = Purchase(
        purchase_number="P-104",
        purchase_date=date(2026, 3, 5),
        user_id=owner_user.id,
        supplier_name="Receipt supplier",
        total_amount=100,
        amount_base=100,
        currency="ILS",
        exchange_rate=1,
        status="confirmed",
    )
    db.session.add(purchase)
    db.session.flush()
    payment = Payment(
        payment_number="PAY-104",
        purchase_id=purchase.id,
        direction="outgoing",
        payment_type="supplier_payment",
        payment_method="cash",
        amount=Decimal("20"),
        amount_base=20,
        exchange_rate=1,
        currency="ILS",
        payment_confirmed=True,
    )
    db.session.add(payment)
    db.session.commit()
    return payment


def test_supplier_payment_shows_purchase_invoice(linked_payment):
    assert linked_payment.get_source_info()["number"] == "P-104"


def test_all_purchase_linked_payments_have_date(linked_payment):
    assert linked_payment.get_source_info()["date"] == "2026-03-05"
