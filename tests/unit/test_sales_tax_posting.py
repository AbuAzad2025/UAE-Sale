from decimal import Decimal

import pytest

from models.gl import GLJournalEntry
from services.sale_service import SaleService


@pytest.mark.parametrize(
    "treatment,inclusive,price,total,tax",
    [
        ("standard", False, "100", "105", "5"),
        ("standard", True, "105", "105", "5"),
        ("zero", False, "100", "100", "0"),
        ("exempt", False, "100", "100", "0"),
    ],
)
def test_sale_posting_balances_and_records_tax(
    db, owner_user, test_customer, test_product, treatment, inclusive, price, total, tax
):
    sale = SaleService.create_sale(
        customer=test_customer,
        seller=owner_user,
        lines_data=[{"product": test_product, "quantity": 1, "unit_price": price}],
        currency="ILS",
        tax_rate=Decimal("5"),
        tax_inclusive=inclusive,
        tax_treatment=treatment,
    )
    assert sale.total_amount == Decimal(total)
    assert sale.tax_amount == Decimal(tax)
    entries = GLJournalEntry.query.filter_by(
        reference_type="Sale", reference_id=sale.id
    ).all()
    assert entries
    assert all(e.is_posted and e.total_debit == e.total_credit for e in entries)
    vat_credits = sum(
        (
            line.credit
            for e in entries
            for line in e.lines
            if line.account.code == "2131"
        ),
        Decimal("0"),
    )
    assert vat_credits == Decimal(tax)


def test_inclusive_discount_edit_adjusts_revenue_tax_and_receivable(
    client, db, owner_user, login_owner, test_customer, test_product
):
    sale = SaleService.create_sale(
        customer=test_customer,
        seller=owner_user,
        lines_data=[{"product": test_product, "quantity": 1, "unit_price": "105"}],
        currency="ILS",
        tax_rate=Decimal("5"),
        tax_inclusive=True,
        tax_treatment="standard",
    )
    response = client.post(
        f"/sales/{sale.id}/edit",
        data={
            "discount_amount": "10",
            "notes": "discount adjustment",
        },
    )
    assert response.status_code == 302
    db.session.expire_all()
    assert sale.total_amount == Decimal("95")
    assert sale.tax_amount == Decimal("4.52")
    entries = GLJournalEntry.query.filter_by(
        reference_type="Sale", reference_id=sale.id
    ).all()
    adjustment = next(
        e for e in entries if e.description.startswith("Discount adjustment")
    )
    assert adjustment.total_debit == adjustment.total_credit
    amounts = {
        line.account.code: (line.debit, line.credit) for line in adjustment.lines
    }
    assert amounts["2131"] == (Decimal("0.480"), Decimal("0"))
    assert amounts["4100"] == (Decimal("0"), Decimal("0.480"))
    assert amounts["1130"] == (Decimal("0"), Decimal("10"))


@pytest.mark.parametrize("inclusive", [False, True])
def test_preview_equals_saved_sale_with_fractional_amounts(
    client, db, owner_user, login_owner, test_customer, test_product, inclusive
):
    line = {"quantity": "1.23", "unit_price": "105.325", "discount_percent": "3.5"}
    preview = client.post(
        "/sales/api/calculate-totals",
        json={
            "lines": [line],
            "discount_amount": "5.025",
            "shipping_cost": "2.100",
            "tax_rate": "5",
            "tax_treatment": "standard",
            "tax_inclusive": inclusive,
        },
    )
    assert preview.status_code == 200
    sale = SaleService.create_sale(
        customer=test_customer,
        seller=owner_user,
        lines_data=[dict(line, product=test_product)],
        currency="ILS",
        discount_amount=Decimal("5.025"),
        shipping_cost=Decimal("2.100"),
        tax_rate=Decimal("5"),
        tax_inclusive=inclusive,
    )
    assert Decimal(str(preview.json["subtotal"])) == sale.subtotal
    assert Decimal(str(preview.json["tax_amount"])) == sale.tax_amount
    assert Decimal(str(preview.json["total"])) == sale.total_amount
