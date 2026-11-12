"""E2E — فاتورة مختلطة عبر النموذج الحقيقي: ضريبة لكل بند ودفتر الأستاذ.

يثبت أن ما يرسله المتصفح (خطوط + معاملة لكل بند + شاملة) ينتهي نفسه في
الفاتورة والقيد — لا تفاوت بين المعاينة, الحفظ, أو الطباعة.
"""

from decimal import Decimal


def test_mixed_invoice_posts_with_per_line_tax(
    client, db, login_as, customer, product, warehouse
):
    from models.product import Product
    from models.gl import GLJournalEntry
    from tests.e2e.harness import sale_form, sale_id_from_redirect

    login_as("owner")

    exempt = Product(
        name="VAT Exempt e2e",
        name_ar="صنف معفى",
        sku="E2E-EXP-1",
        cost_price=Decimal("10"),
        regular_price=Decimal("40"),
        current_stock=Decimal("10"),
        is_active=True,
        tax_treatment="exempt",
        category=product.category,
    )
    db.session.add(exempt)
    db.session.commit()

    data = sale_form(
        customer,
        [
            {"product_id": product.id, "quantity": 1, "unit_price": 50},
            {
                "product_id": exempt.id,
                "quantity": 1,
                "unit_price": 40,
                "tax_treatment": "exempt",
            },
        ],
        warehouse=warehouse,
        tax_rate=5,
    )
    response = client.post("/sales/create", data=data)
    assert response.status_code in (302, 303), response.get_data(as_text=True)[:300]
    sid = sale_id_from_redirect(response)

    from models.sale import Sale

    sale = db.session.get(Sale, sid)
    # Subtotal 90 — VAT 5% على البند القياسي فقط (بند الصنف القياسي = 50)
    assert sale.subtotal == Decimal("90")
    assert sale.tax_amount == Decimal("2.500")
    assert sale.total_amount == Decimal("92.500")

    lines_by_treatment = {l.tax_treatment for l in sale.lines}
    assert lines_by_treatment == {"standard", "exempt"}

    entries = GLJournalEntry.query.filter_by(
        reference_type="Sale", reference_id=sale.id
    ).all()
    assert entries and all(e.total_debit == e.total_credit for e in entries)
    vat_credits = sum(
        (l.credit for e in entries for l in e.lines if l.account.code == "2131"),
        Decimal("0"),
    )
    assert vat_credits == Decimal("2.500")


def test_mixed_invoice_inclusive_posts_balanced(
    client, db, login_as, customer, product, warehouse
):
    from models.product import Product
    from models.gl import GLJournalEntry
    from tests.e2e.harness import sale_form, sale_id_from_redirect

    login_as("owner")

    exempt = Product(
        name="VAT Zero e2e",
        name_ar="صنف صفري",
        sku="E2E-ZERO-1",
        cost_price=Decimal("10"),
        regular_price=Decimal("30"),
        current_stock=Decimal("10"),
        is_active=True,
        tax_treatment="zero",
        category=product.category,
    )
    db.session.add(exempt)
    db.session.commit()

    data = sale_form(
        customer,
        [
            {"product_id": product.id, "quantity": 1, "unit_price": 105},
            {"product_id": exempt.id, "quantity": 1, "unit_price": 30},
        ],
        warehouse=warehouse,
        tax_rate=5,
        tax_inclusive=True,
    )
    response = client.post("/sales/create", data=data)
    assert response.status_code in (302, 303), response.get_data(as_text=True)[:300]
    sid = sale_id_from_redirect(response)

    from models.sale import Sale

    sale = db.session.get(Sale, sid)
    assert sale.total_amount == Decimal("135")
    assert sale.tax_amount == Decimal("5.000")
    net_std = sale.subtotal - sale.tax_amount
    assert net_std == Decimal("130.000")

    entries = GLJournalEntry.query.filter_by(
        reference_type="Sale", reference_id=sale.id
    ).all()
    assert all(e.total_debit == e.total_credit for e in entries)
