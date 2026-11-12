"""Seed a throwaway SQLite database for the browser smoke test.

This file is created and destroyed by the test run; it never touches the
development PostgreSQL database.
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

DB_PATH = (
    Path(os.environ.get("MAINT_UI_DB", "")) if os.environ.get("MAINT_UI_DB") else None
)
if DB_PATH is None:
    raise SystemExit("MAINT_UI_DB must point to the throwaway SQLite file")

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "scratch-ui-smoke-test-secret-key-32")
os.environ.setdefault("OWNER_PASSWORD", "SmokeTest-Password-123!")
os.environ.setdefault("ENABLE_SCHEDULERS", "0")
os.environ.setdefault("WTF_CSRF_ENABLED", "true")
os.environ.setdefault("RATELIMIT_ENABLED", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402

app = create_app()
with app.app_context():
    db.drop_all()
    db.create_all()
    from models import (
        Customer,
        Permission,
        Product,
        ProductCategory,
        Role,
        Supplier,
        Tenant,
        User,
    )
    from models.warehouse import Warehouse
    from models.tenant_scope import set_current_tenant_id, clear_current_tenant_id
    from services.gl_service import GLService
    from services.stock_service import StockService

    tenant = Tenant(
        name="Smoke Garage",
        name_ar="ورشة الاختبار",
        slug="smoke-garage",
        is_active=True,
        enable_maintenance=True,
    )
    db.session.add(tenant)
    db.session.flush()

    codes = [
        "maintenance_view",
        "maintenance_receive",
        "maintenance_cashier",
        "maintenance_work",
        "maintenance_close",
        "maintenance_discount",
        "maintenance_settings",
        "maintenance_purchase",
    ]
    perms = [Permission(code=code, name=code, category="maintenance") for code in codes]
    role = Role(
        name="Maintenance manager",
        name_ar="مدير صيانة",
        slug="smoke-maint",
        permissions=perms,
    )
    db.session.add_all(perms + [role])
    db.session.flush()

    user = User(
        username="smoke",
        email="smoke@example.invalid",
        full_name="Smoke Tester",
        tenant_id=tenant.id,
        role_id=role.id,
        is_active=True,
    )
    user.set_password("SmokeTest-Password-123!")
    db.session.add(user)

    customer = Customer(
        name="Smoke Customer",
        name_ar="عميل الاختبار",
        tenant_id=tenant.id,
        is_active=True,
        customer_type="regular",
        credit_limit=Decimal("5000"),
        phone="+971500000001",
    )
    db.session.add(customer)

    category = ProductCategory(name="Spare parts", is_active=True)
    db.session.add(category)
    db.session.flush()

    product = Product(
        name="Smoke Brake Pad",
        name_ar="ف pads",
        sku="SMOKE-1",
        category_id=category.id,
        tenant_id=tenant.id,
        cost_price=Decimal("30"),
        regular_price=Decimal("100"),
        current_stock=Decimal("0"),
        is_active=True,
    )
    db.session.add(product)
    db.session.flush()

    warehouse = Warehouse(
        name="Smoke Warehouse",
        name_ar="مستودع الاختبار",
        code="SMOKE-WH",
        tenant_id=tenant.id,
        is_active=True,
        is_maintenance_warehouse=True,
    )
    db.session.add(warehouse)
    db.session.flush()

    db.session.add(
        Supplier(
            name="Smoke Supplier",
            name_ar="مورد الاختبار",
            tenant_id=tenant.id,
            is_active=True,
        )
    )

    GLService.ensure_core_accounts()
    db.session.commit()

    set_current_tenant_id(tenant.id)
    try:
        StockService.create_movement(
            product_id=product.id,
            quantity=Decimal("100"),
            movement_type="purchase",
            reference_type="setup",
            reference_id=0,
            notes="initial stock",
            warehouse_id=warehouse.id,
            unit_cost_base=Decimal("30"),
        )
        db.session.commit()
    finally:
        clear_current_tenant_id()

    print("scratch database ready:", DB_PATH)
