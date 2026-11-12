"""ضريبة مختلطة على مستوى الأسطر: حساب + إرجاع + تقرير VAT."""

from decimal import Decimal


from models import Product
from services.sale_service import SaleService


def _mixed_products(db, test_category):
    zero = Product(
        name="Medical Export Item",
        name_ar="صنف تصدير معفى",
        sku="MIX-ZERO-001",
        category_id=test_category.id,
        cost_price=Decimal("10.000"),
        regular_price=Decimal("30.000"),
        current_stock=Decimal("50"),
        min_stock_alert=Decimal("1"),
        is_active=True,
        tax_treatment="zero",
    )
    exempt = Product(
        name="Exempt Service Item",
        name_ar="صنف معفى",
        sku="MIX-EXEMPT-001",
        category_id=test_category.id,
        cost_price=Decimal("5.000"),
        regular_price=Decimal("40.000"),
        current_stock=Decimal("50"),
        min_stock_alert=Decimal("1"),
        is_active=True,
        tax_treatment="exempt",
    )
    db.session.add_all([zero, exempt])
    db.session.commit()
    return zero, exempt


def _create_mixed_sale(
    db, test_customer, seller, test_product, test_category, *, tax_inclusive=False
):
    zero, exempt = _mixed_products(db, test_category)
    return SaleService.create_sale(
        customer=test_customer,
        seller=seller,
        lines_data=[
            {"product": test_product, "quantity": 2, "unit_price": "50"},
            {"product": zero, "quantity": 1, "unit_price": "30"},
            {"product": exempt, "quantity": 1, "unit_price": "40"},
        ],
        currency="ILS",
        tax_rate=Decimal("5"),
        tax_inclusive=tax_inclusive,
        tax_treatment="standard",
    )


def test_mixed_invoice_computes_vat_only_on_standard_lines(
    db, owner_user, test_customer, test_product, test_category
):
    sale = _create_mixed_sale(
        db, test_customer, owner_user, test_product, test_category
    )
    assert sale.subtotal == Decimal("170")
    # الضريبة على 100 فقط (سطران قياسيان) — لا على المعفى ولا الصفري
    assert sale.tax_amount == Decimal("5.000")
    assert sale.total_amount == Decimal("175")
    # لكل سطر لقطة معاملته
    treatments = sorted(line.tax_treatment for line in sale.lines)
    assert treatments == ["exempt", "standard", "zero"]


def test_mixed_inclusive_invoice_extracts_vat_only_on_standard_lines(
    db, owner_user, test_customer, test_product, test_category
):
    sale = _create_mixed_sale(
        db, test_customer, owner_user, test_product, test_category, tax_inclusive=True
    )
    # الإجمالي لا يتغير شامل/غير شامل؛ الضريبة تُستخرج من سطر المعاملة القياسي
    assert sale.total_amount == Decimal("170")
    assert sale.tax_amount == Decimal(
        "4.76"
    )  # 100/1.05 → 95.238، استخراج بمنزلتين كباقي النظام
    assert sale.subtotal == Decimal("170")


def test_mixed_credit_note_deducts_only_returned_bucket(
    db, owner_user, test_customer, test_product, test_category
):
    from services.return_service import ReturnService
    from routes.reports import _vat_report_data

    sale = _create_mixed_sale(
        db, test_customer, owner_user, test_product, test_category
    )
    exempt_line = next(l for l in sale.lines if l.tax_treatment == "exempt")
    zero_line = next(l for l in sale.lines if l.tax_treatment == "zero")

    ReturnService.create_return(
        sale.id,
        [{"sale_line_id": exempt_line.id, "quantity": 1}],
        user_id=owner_user.id,
    )
    ReturnService.create_return(
        sale.id, [{"sale_line_id": zero_line.id, "quantity": 1}], user_id=owner_user.id
    )

    data = _vat_report_data()
    summary = data["summary"]
    # المرتجع المعفى خصم من سلة المعفى، والصفري من صفريها — لا من الخاضع
    assert summary["total_taxable_sales"] == Decimal("100")
    assert summary["total_exempt_sales"] == Decimal("0")
    assert summary["total_zero_rated_sales"] == Decimal("0")
    assert summary["total_output_vat"] == Decimal("5.000")


def test_mixed_partial_standard_return_reverses_only_std_tax(
    db, owner_user, test_customer, test_product, test_category
):
    from services.return_service import ReturnService

    sale = _create_mixed_sale(
        db, test_customer, owner_user, test_product, test_category
    )
    std_line = next(l for l in sale.lines if l.tax_treatment == "standard")
    ret = ReturnService.create_return(
        sale.id, [{"sale_line_id": std_line.id, "quantity": 1}], user_id=owner_user.id
    )
    # فُسخ نصف السطر القياسي: 50 صافية + ضريبة 5% = 2.5
    assert ret.refund_amount == Decimal("52.500")
    assert ret.status == "approved"
