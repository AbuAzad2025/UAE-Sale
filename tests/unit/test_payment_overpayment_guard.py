"""A payment must never exceed a purchase's outstanding balance.

Regression: the pre-insert listener only logged invalid amounts. Now it raises
ValidationError using a fresh DB-computed balance so multiple / multi-currency
split payments on one invoice cannot push it past its total.
"""
from decimal import Decimal
from datetime import date

import pytest


def _purchase(db, total=Decimal("1000")):
    from models import set_current_tenant_id
    from models.purchase import Purchase

    set_current_tenant_id(2)
    p = Purchase(
        purchase_number="TEST-OVERPAY",
        supplier_name="test",
        total_amount=total,
        amount_base=total,
        currency="ILS",
        exchange_rate=Decimal("1"),
        status="confirmed",
        payment_status="unpaid",
        purchase_date=date.today(),
        tax_rate=Decimal("0"),
        user_id=2,
    )
    db.session.add(p)
    db.session.flush()
    return p


def test_overpayment_raises(db):
    from models.payment import Payment
    from utils.errors import ValidationError

    p = _purchase(db)
    with pytest.raises(ValidationError):
        pay = Payment(
            payment_number="TEST-PAY-OVER",
            purchase_id=p.id,
            direction="outgoing",
            payment_type="supplier_payment",
            payment_method="cash",
            amount=Decimal("1200"),
            currency="ILS",
            exchange_rate=Decimal("1"),
            amount_base=Decimal("1200"),
            payment_confirmed=True,
            tenant_id=2,
        )
        db.session.add(pay)
        db.session.flush()


def test_split_payments_within_balance_ok(db):
    from models.payment import Payment

    p = _purchase(db)
    for i, amt in enumerate((Decimal("400"), Decimal("600"))):
        pay = Payment(
            payment_number=f"TEST-PAY-{i}",
            purchase_id=p.id,
            direction="outgoing",
            payment_type="supplier_payment",
            payment_method="cash",
            amount=amt,
            currency="ILS",
            exchange_rate=Decimal("1"),
            amount_base=amt,
            payment_confirmed=True,
            tenant_id=2,
        )
        db.session.add(pay)
        db.session.flush()
    p.recalculate_payment_status()
    assert p.paid_amount == Decimal("1000.000")
    assert p.payment_status == "paid"


def test_uncertified_cheque_does_not_consume_balance(db):
    """An unconfirmed (pending) cheque payment must not count as paid."""
    from models.payment import Payment

    p = _purchase(db)
    pay = Payment(
        payment_number="TEST-CHQ-PENDING",
        purchase_id=p.id,
        direction="outgoing",
        payment_type="supplier_payment",
        payment_method="cheque",
        amount=Decimal("1000"),
        currency="ILS",
        exchange_rate=Decimal("1"),
        amount_base=Decimal("1000"),
        payment_confirmed=False,
        tenant_id=2,
    )
    db.session.add(pay)
    db.session.flush()
    # A confirmed payment of the full amount is still allowed because the
    # pending cheque did not consume the balance.
    pay2 = Payment(
        payment_number="TEST-PAY-OK",
        purchase_id=p.id,
        direction="outgoing",
        payment_type="supplier_payment",
        payment_method="cash",
        amount=Decimal("1000"),
        currency="ILS",
        exchange_rate=Decimal("1"),
        amount_base=Decimal("1000"),
        payment_confirmed=True,
        tenant_id=2,
    )
    db.session.add(pay2)
    db.session.flush()
