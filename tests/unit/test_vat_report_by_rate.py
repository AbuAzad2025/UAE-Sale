"""VAT report — mixed purchases, reverse charge, non-recoverable, by-rate grouping."""

from datetime import datetime
from decimal import Decimal


from models import Purchase, PurchaseLine, Supplier

BASE_CURRENCY = "ILS"


def _purchase(
    db,
    supplier,
    product,
    user_id,
    number,
    net,
    rate,
    treatment,
    recoverable,
    reverse_charge,
):
    net = Decimal(net)
    rate = Decimal(str(rate))
    tax = (net * rate / Decimal("100")).quantize(Decimal("0.001"))
    total = net + tax
    p = Purchase(
        purchase_number=number,
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        subtotal=net,
        tax_rate=rate,
        tax_amount=tax,
        vat_recoverable=recoverable,
        reverse_charge=reverse_charge,
        total_amount=total,
        currency=BASE_CURRENCY,
        exchange_rate=Decimal("1"),
        amount_base=total,
        status="confirmed",
        user_id=user_id,
        purchase_date=datetime.now(),
        tax_treatment=treatment,
    )
    db.session.add(p)
    db.session.flush()
    db.session.add(
        PurchaseLine(
            purchase_id=p.id,
            product_id=product.id,
            quantity=Decimal("1"),
            unit_cost=net,
            discount_percent=Decimal("0"),
            line_total=net,
            tax_treatment=treatment,
        )
    )
    return p


def _mixed_purchase(
    db, supplier, product, user_id, number, std, zero, rate, recoverable, reverse_charge
):
    std, zero = Decimal(std), Decimal(zero)
    rate = Decimal(str(rate))
    net_total = std + zero
    tax = (std * rate / Decimal("100")).quantize(Decimal("0.001"))
    total = net_total + tax
    p = Purchase(
        purchase_number=number,
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        subtotal=net_total,
        tax_rate=rate,
        tax_amount=tax,
        vat_recoverable=recoverable,
        reverse_charge=reverse_charge,
        total_amount=total,
        currency=BASE_CURRENCY,
        exchange_rate=Decimal("1"),
        amount_base=total,
        status="confirmed",
        user_id=user_id,
        purchase_date=datetime.now(),
        tax_treatment="standard",
    )
    db.session.add(p)
    db.session.flush()
    db.session.add(
        PurchaseLine(
            purchase_id=p.id,
            product_id=product.id,
            quantity=Decimal("1"),
            unit_cost=std,
            discount_percent=Decimal("0"),
            line_total=std,
            tax_treatment="standard",
        )
    )
    db.session.add(
        PurchaseLine(
            purchase_id=p.id,
            product_id=product.id,
            quantity=Decimal("1"),
            unit_cost=zero,
            discount_percent=Decimal("0"),
            line_total=zero,
            tax_treatment="zero",
        )
    )
    return p


class TestVatReportByRate:
    def test_mixed_purchase_splits_buckets(self, db, owner_user, test_product):
        from routes.reports import _vat_report_data

        supplier = Supplier(name="RC Supplier", is_active=True)
        db.session.add(supplier)
        db.session.commit()
        _mixed_purchase(
            db,
            supplier,
            test_product,
            owner_user.id,
            "P-MIX",
            "100",
            "60",
            "5",
            recoverable=True,
            reverse_charge=False,
        )
        db.session.commit()

        data = _vat_report_data()
        summary = data["summary"]
        assert summary["total_taxable_purchases"] == Decimal("100.000")
        assert summary["total_zero_rated_purchases"] == Decimal("60.000")
        assert summary["total_input_vat"] == Decimal("5.000")

        by_rate = {str(r["rate"]): r for r in data["by_rate"]}
        assert "5.00" in by_rate
        assert by_rate["5.00"]["purchases_net"] == Decimal("100.000")

    def test_non_recoverable_excluded_from_input_vat(
        self, db, owner_user, test_product
    ):
        from routes.reports import _vat_report_data

        supplier = Supplier(name="NR Supplier", is_active=True)
        db.session.add(supplier)
        db.session.commit()
        _purchase(
            db,
            supplier,
            test_product,
            owner_user.id,
            "P-NR",
            "200",
            "5",
            "standard",
            recoverable=False,
            reverse_charge=False,
        )
        db.session.commit()

        data = _vat_report_data()
        summary = data["summary"]
        # الضريبة تُحمّل على تكلفة البضاعة — لا مدخل ضريبة مسموح بها
        assert summary["total_input_vat"] == Decimal("0")
        assert summary["total_non_recoverable_vat"] == Decimal("10.000")
        assert summary["total_non_recoverable_base"] == Decimal("200.000")
        assert [r["number"] for r in data["non_recoverable_purchases"]] == ["P-NR"]

    def test_reverse_charge_balances_output_and_input(
        self, db, owner_user, test_product
    ):
        from routes.reports import _vat_report_data

        supplier = Supplier(name="RC Supplier 2", is_active=True)
        db.session.add(supplier)
        db.session.commit()
        _purchase(
            db,
            supplier,
            test_product,
            owner_user.id,
            "P-RC",
            "300",
            "5",
            "standard",
            recoverable=True,
            reverse_charge=True,
        )
        db.session.commit()

        data = _vat_report_data()
        summary = data["summary"]
        # المخرجات واللمدخلات متساويان (الضريبة ذاتية التقييم)
        assert summary["total_reverse_charge_vat"] == Decimal("15.000")
        assert summary["total_reverse_charge_base"] == Decimal("300.000")
        assert summary["total_output_vat"] >= Decimal("15.000")
        assert summary["total_input_vat"] == Decimal("15.000")

    def test_reverse_charge_non_recoverable_increases_net_payable(
        self, db, owner_user, test_product
    ):
        from routes.reports import _vat_report_data

        supplier = Supplier(name="RC Supplier 3", is_active=True)
        db.session.add(supplier)
        db.session.commit()
        _purchase(
            db,
            supplier,
            test_product,
            owner_user.id,
            "P-RCNR",
            "100",
            "5",
            "standard",
            recoverable=False,
            reverse_charge=True,
        )
        db.session.commit()

        data = _vat_report_data()
        summary = data["summary"]
        # المخرجات تُسجَّل لكن لا مدخلات قابلة للاسترداد ⇒ الرصيد = الضريبة
        assert summary["total_input_vat"] == Decimal("0")
        assert summary["total_non_recoverable_vat"] == Decimal("5.000")
        assert summary["total_reverse_charge_vat"] == Decimal("5.000")
        assert summary["total_output_vat"] >= Decimal("5.000")
