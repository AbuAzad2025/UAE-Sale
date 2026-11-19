"""Permanent guard: VAT-inclusive purchase prices must value inventory at the
NET of recoverable VAT, exactly matching the posted GL inventory debit.
"""
import pytest
from decimal import Decimal


def test_net_unit_cost_strips_recoverable_vat(app, db):
    from models import Product, Purchase, PurchaseLine, Supplier, User
    from services.costing_service import CostingService

    with app.app_context():
        product = Product(name="COS-TEST", sku="COS-TEST-1", cost_price=Decimal("1200"),
                          regular_price=Decimal("1500"), current_stock=Decimal("0"),
                          is_active=True)
        supplier = Supplier(name="COS-TEST-SUP", supplier_type="materials")
        db.session.add_all([product, supplier])
        db.session.commit()

        actor = User.query.first()
        p = Purchase(purchase_number="COS-TEST-P1", supplier_name="COS-TEST-SUP",
                     user_id=actor.id if actor else 1,
                     currency="ILS", tax_rate=Decimal("16"), tax_inclusive=True,
                     vat_recoverable=True, tax_treatment="standard",
                     exchange_rate=Decimal("1"), subtotal=Decimal("0"),
                     tax_amount=Decimal("0"), total_amount=Decimal("0"),
                     amount_base=Decimal("0"))
        db.session.add(p)
        db.session.flush()
        line = PurchaseLine(purchase_id=p.id, product_id=product.id,
                            quantity=Decimal("1"), unit_cost=Decimal("1200"),
                            line_total=Decimal("1200"), tax_treatment="standard")
        db.session.add(line)
        db.session.flush()
        p.calculate_totals()
        db.session.commit()

        assert p.tax_amount == Decimal("165.52")
        assert p.total_amount == Decimal("1200.000")
        # Inventory net = gross - VAT, matching build_purchase_gl_lines.
        net = p.total_amount - p.tax_amount
        assert net == Decimal("1034.48")
        assert CostingService.net_unit_cost(line, p) == net
