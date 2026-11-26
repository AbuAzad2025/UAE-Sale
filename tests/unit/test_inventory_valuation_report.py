from decimal import Decimal

from models import Product, StockMovement, Warehouse
from services.inventory_reconciliation import reconcile_inventory


def test_independent_valuation_bases(db, posting_tenant, test_product):
    test_product.current_stock = 2
    test_product.average_cost = Decimal("4.125")
    test_product.cost_price = Decimal("5.00")
    warehouse = Warehouse(name="Valuation", code="VAL")
    db.session.add(warehouse)
    db.session.flush()
    db.session.add(
        StockMovement(
            warehouse_id=warehouse.id,
            product_id=test_product.id,
            quantity=2,
            movement_type="purchase",
        )
    )
    db.session.flush()
    result = reconcile_inventory(tenant_id=posting_tenant.id)
    row = result["products"][0]
    assert (
        row["valuation_at_average_cost"]
        == result["total_valuation_at_average_cost"]
        == Decimal("8.25")
    )
    assert (
        row["valuation_at_cost_price"]
        == result["total_valuation_at_cost_price"]
        == Decimal("10.00")
    )
    assert result["balanced"] is False


def test_offsetting_quantity_errors_are_detected(db, posting_tenant, test_product):
    test_product.current_stock = 1
    other = Product(name="Second", sku="OFFSET", current_stock=0, regular_price=1)
    warehouse = Warehouse(name="Offset", code="OFF")
    db.session.add_all([warehouse, other])
    db.session.flush()
    db.session.add(
        StockMovement(
            warehouse_id=warehouse.id,
            product_id=other.id,
            quantity=1,
            movement_type="purchase",
        )
    )
    db.session.flush()
    result = reconcile_inventory(tenant_id=posting_tenant.id)
    assert result["difference"] == 0
    assert {row["difference"] for row in result["products"]} == {-1, 1}
    assert result["balanced"] is False
