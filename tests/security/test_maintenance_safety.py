"""Maintenance safety regressions; never run this module on a real database."""

import importlib
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.engine import make_url


_url = make_url(os.environ["DATABASE_URL"])
if _url.get_backend_name() != "sqlite" or _url.database not in (None, "", ":memory:"):
    pytest.skip(
        "Maintenance safety tests require in-memory SQLite", allow_module_level=True
    )

from flask import g  # noqa: E402
from flask_login import login_user  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402
from models import Customer, Permission, Product, Role, Tenant, User  # noqa: E402
from models.maintenance import (  # noqa: E402
    MaintenanceDeviceRegistry,
    MaintenanceInvoice,
    MaintenanceOrder,
    MaintenanceOrderItem,
    MaintenanceOrderStatusLog,
    MaintenanceReceipt,
    MaintenanceSetting,
    MaintenanceWarrantyAudit,
)
from models.tenant_scope import clear_current_tenant_id, set_current_tenant_id  # noqa: E402
from services import maintenance_service as service  # noqa: E402
from utils.errors import ValidationError  # noqa: E402


@pytest.fixture(scope="session")
def maintenance_test_password_hash():
    # Authentication is exercised, but production PBKDF2 work factors need
    # not be repeated for every short-lived in-memory fixture user.
    return generate_password_hash("Test-password-123!", method="pbkdf2:sha256:1000")


@pytest.fixture
def maintenance_env(db, maintenance_test_password_hash):
    tenants = [
        Tenant(
            name="Tenant A", name_ar="Tenant A", slug="maint-a", enable_maintenance=True
        ),
        Tenant(
            name="Tenant B", name_ar="Tenant B", slug="maint-b", enable_maintenance=True
        ),
    ]
    db.session.add_all(tenants)
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
    by_code = {p.code: p for p in perms}
    engineer = Role(
        name="Maintenance engineer",
        slug="maint-engineer",
        permissions=[by_code["maintenance_view"], by_code["maintenance_work"]],
    )
    reception = Role(
        name="Maintenance reception", slug="maint-reception", permissions=perms
    )
    platform = Role(name="Platform maint test", slug="maint-platform")
    db.session.add_all(perms + [engineer, reception, platform])
    db.session.flush()

    def make_user(name, tenant, role, owner=False):
        user = User(
            username=name,
            email=f"{name}@example.invalid",
            full_name=name,
            tenant_id=tenant.id if tenant else None,
            role_id=role.id,
            is_owner=owner,
            is_active=True,
            password_hash=maintenance_test_password_hash,
        )
        db.session.add(user)
        return user

    users = {
        "engineer": make_user("maint-engineer-a", tenants[0], engineer),
        "reception": make_user("maint-reception-a", tenants[0], reception),
        "other": make_user("maint-reception-b", tenants[1], reception),
        "owner": make_user("maint-platform-owner", None, platform, True),
    }
    customers = [
        Customer(name="Only customer A", tenant_id=tenants[0].id, is_active=True),
        Customer(name="Only customer B", tenant_id=tenants[1].id, is_active=True),
    ]
    db.session.add_all(customers)
    db.session.flush()
    orders = [
        MaintenanceOrder(
            tenant_id=tenants[i].id,
            branch_id=tenants[i].id,
            order_no=f"MAINT-TEST-{i}",
            customer_id=customers[i].id,
            received_by=users["reception" if i == 0 else "other"].id,
            status="ready",
            total_amount=Decimal("105"),
            paid_amount=Decimal("0"),
            balance_due=Decimal("105"),
        )
        for i in (0, 1)
    ]
    db.session.add_all(orders)
    db.session.commit()
    return {
        "tenants": tenants,
        "users": users,
        "customers": customers,
        "orders": orders,
    }


def _login(client, user, tenant_id=None):
    # The shared db fixture holds an app context across requests, so clear
    # Flask-Login's cached proxy as well as the cookie before switching users.
    g.pop("_login_user", None)
    with client.session_transaction() as session:
        session.clear()
    response = client.post(
        "/auth/login",
        data={
            "username": user.username,
            "password": "Test-password-123!",
        },
    )
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session.get("_user_id") == str(user.id)
        if tenant_id is not None:
            session["impersonate_tenant_id"] = tenant_id
    g.pop("_login_user", None)


def test_disabled_feature_denies_reads_and_writes(client, db, maintenance_env):
    env = maintenance_env
    env["tenants"][0].enable_maintenance = False
    db.session.commit()
    _login(client, env["users"]["reception"])
    response = client.get("/maintenance/")
    assert response.status_code == 403, response.location
    assert client.post("/maintenance/create", data={}).status_code == 403
    assert MaintenanceOrder.query.count() == 2


def test_feature_gate_fails_closed_when_tenant_resolution_errors(monkeypatch):
    from flask import Blueprint, Flask
    from models import tenant_scope
    from utils.feature_guards import install_feature_gate

    app = Flask(__name__)
    blueprint = Blueprint("gate_test", __name__)
    install_feature_gate(blueprint, "maintenance")

    @blueprint.route("/")
    def index():
        return "must not be reached"

    app.register_blueprint(blueprint)

    def fail():
        raise RuntimeError("simulated tenant resolution failure")

    monkeypatch.setattr(tenant_scope, "get_current_tenant_id", fail)
    assert app.test_client().get("/").status_code == 503


def test_platform_requires_selected_tenant_and_cannot_cross_it(client, maintenance_env):
    env = maintenance_env
    _login(client, env["users"]["owner"])
    assert client.get("/maintenance/").status_code == 403
    _login(client, env["users"]["owner"], env["tenants"][0].id)
    assert client.get(f"/maintenance/{env['orders'][1].id}").status_code == 404
    response = client.get("/maintenance/")
    assert response.status_code == 200
    assert b"MAINT-TEST-0" in response.data
    assert b"MAINT-TEST-1" not in response.data


def test_reception_lists_only_own_customers_and_rejects_foreign_ids(
    client, db, maintenance_env
):
    env = maintenance_env
    _login(client, env["users"]["reception"])
    response = client.get("/maintenance/create")
    assert response.status_code == 200
    assert b"Only customer A" in response.data
    assert b"Only customer B" not in response.data
    response = client.post(
        "/maintenance/create", data={"customer_id": env["customers"][1].id}
    )
    assert response.status_code == 200
    assert MaintenanceOrder.query.count() == 2
    response = client.post(
        "/maintenance/create",
        data={
            "customer_id": env["customers"][0].id,
            "engineer_id": env["users"]["other"].id,
        },
    )
    assert response.status_code == 200
    assert MaintenanceOrder.query.count() == 2


def test_reception_creates_order_and_status_history(client, db, maintenance_env):
    env = maintenance_env
    _login(client, env["users"]["reception"])
    response = client.post(
        "/maintenance/create",
        data={
            "customer_id": env["customers"][0].id,
            "device_serial": "SERIAL-A",
            "device_problem": "Screen",
            "notes": "Reception notes",
        },
    )
    assert response.status_code == 302
    order = MaintenanceOrder.query.filter_by(device_serial="SERIAL-A").one()
    assert order.tenant_id == env["tenants"][0].id
    assert order.notes == "Reception notes"
    assert order.status == "received"
    assert order.deposit == 0
    assert (
        MaintenanceOrderStatusLog.query.filter_by(maintenance_order_id=order.id).count()
        == 1
    )
    response = client.post(
        f"/maintenance/{order.id}/status", data={"status": "diagnosis"}
    )
    assert response.status_code == 302
    db.session.expire_all()
    assert db.session.get(MaintenanceOrder, order.id).status == "diagnosis"
    assert (
        MaintenanceOrderStatusLog.query.filter_by(maintenance_order_id=order.id).count()
        == 2
    )


def test_ambiguous_device_registry_does_not_grant_warranty(client, db, maintenance_env):
    env = maintenance_env
    for under_warranty in (True, False):
        db.session.add(
            MaintenanceDeviceRegistry(
                tenant_id=env["tenants"][0].id,
                customer_id=env["customers"][0].id,
                serial_number="DUPLICATE",
                is_under_warranty=under_warranty,
                warranty_end_date=date.today() + timedelta(days=30),
            )
        )
    db.session.commit()
    _login(client, env["users"]["reception"])
    response = client.post(
        "/maintenance/create",
        data={
            "customer_id": env["customers"][0].id,
            "device_serial": "  DUPLICATE  ",
        },
    )
    assert response.status_code == 302
    order = MaintenanceOrder.query.filter_by(device_serial="DUPLICATE").one()
    assert order.warranty_status == "unknown"
    assert not order.warranty_checked


def test_intake_rejects_oversized_identifier(client, maintenance_env):
    env = maintenance_env
    _login(client, env["users"]["reception"])
    response = client.post(
        "/maintenance/create",
        data={
            "customer_id": env["customers"][0].id,
            "device_serial": "X" * 101,
        },
    )
    assert response.status_code == 200
    assert MaintenanceOrder.query.count() == 2


def test_date_filter_includes_the_entire_last_day(client, db, maintenance_env):
    env = maintenance_env
    order = env["orders"][0]
    order.received_at = datetime(2026, 4, 15, 23, 59, 59)
    db.session.commit()
    _login(client, env["users"]["reception"])
    assert b"MAINT-TEST-0" in client.get("/maintenance/?date_to=2026-04-15").data
    assert b"MAINT-TEST-0" not in client.get("/maintenance/?date_to=2026-04-14").data
    assert client.get("/maintenance/?date_from=bad-date").status_code == 302
    assert (
        client.get("/maintenance/?date_from=2026-04-16&date_to=2026-04-15").status_code
        == 302
    )


def test_deposit_creates_linked_receipt(client, maintenance_env):
    """A deposit at reception creates a linked receipt with a GL posting."""
    env = maintenance_env
    _login(client, env["users"]["reception"])
    response = client.post(
        "/maintenance/create",
        data={
            "customer_id": env["customers"][0].id,
            "deposit": "100",
            "deposit_payment_method": "cash",
        },
    )
    assert response.status_code == 302
    # Find the new order (the one with deposit)
    order = MaintenanceOrder.query.filter_by(deposit=Decimal("100")).one()
    assert MaintenanceReceipt.query.count() == 1
    receipt = MaintenanceReceipt.query.one()
    assert receipt.amount == Decimal("100")
    assert receipt.posted is True
    assert order.paid_amount == Decimal("100")


def test_engineer_cannot_close_or_fabricate_payment(client, db, maintenance_env):
    env = maintenance_env
    order_id = env["orders"][0].id
    _login(client, env["users"]["engineer"])
    response = client.post(f"/maintenance/{order_id}/status", data={"status": "closed"})
    assert response.status_code == 302
    db.session.expire_all()
    order = db.session.get(MaintenanceOrder, order_id)
    assert order.status == "ready"
    assert order.paid_amount == 0
    assert order.balance_due == Decimal("105")
    assert MaintenanceOrderStatusLog.query.count() == 0
    # The engineer has no collection permission, so the request is refused.
    assert (
        client.post(
            f"/maintenance/{order_id}/receive", data={"amount": "105"}
        ).status_code
        == 403
    )
    assert MaintenanceReceipt.query.count() == 0


def test_cancellation_requires_authorization_and_no_financial_effects(
    client, db, maintenance_env
):
    env = maintenance_env
    order = env["orders"][0]
    order.status = "received"
    db.session.commit()
    _login(client, env["users"]["reception"])
    assert (
        client.post(
            f"/maintenance/{order.id}/status", data={"status": "cancelled"}
        ).status_code
        == 302
    )
    db.session.expire_all()
    assert db.session.get(MaintenanceOrder, order.id).status == "received"
    order.total_amount = order.balance_due = Decimal("0")
    db.session.commit()
    _login(client, env["users"]["engineer"])
    assert (
        client.post(
            f"/maintenance/{order.id}/status", data={"status": "cancelled"}
        ).status_code
        == 302
    )
    db.session.expire_all()
    assert db.session.get(MaintenanceOrder, order.id).status == "received"
    _login(client, env["users"]["reception"])
    assert (
        client.post(
            f"/maintenance/{order.id}/status", data={"status": "cancelled"}
        ).status_code
        == 302
    )
    db.session.expire_all()
    assert db.session.get(MaintenanceOrder, order.id).status == "cancelled"


def test_foreign_order_is_not_visible_or_modified(client, db, maintenance_env):
    env = maintenance_env
    order_id = env["orders"][1].id
    _login(client, env["users"]["engineer"])
    assert client.get(f"/maintenance/{order_id}").status_code == 404
    assert (
        client.post(
            f"/maintenance/{order_id}/status", data={"status": "on_hold"}
        ).status_code
        == 302
    )
    db.session.expire_all()
    assert db.session.get(MaintenanceOrder, order_id).status == "ready"
    assert MaintenanceOrderStatusLog.query.count() == 0


def test_direct_status_service_rejects_spoofed_actor(app, db, maintenance_env):
    env = maintenance_env
    with app.test_request_context("/"):
        login_user(env["users"]["engineer"])
        set_current_tenant_id(env["tenants"][0].id)
        try:
            with pytest.raises(ValidationError):
                service.change_status(
                    env["orders"][0].id, "on_hold", env["users"]["reception"].id
                )
            assert env["orders"][0].status == "ready"
        finally:
            clear_current_tenant_id()


def test_intake_rolls_back_if_status_audit_fails(app, db, maintenance_env, monkeypatch):
    env = maintenance_env
    user = env["users"]["reception"]

    def fail_audit(*args, **kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(service, "_log_status", fail_audit)
    with app.test_request_context("/"):
        login_user(user)
        set_current_tenant_id(env["tenants"][0].id)
        try:
            with pytest.raises(RuntimeError, match="simulated audit failure"):
                service.create_maintenance_order(
                    env["tenants"][0].id,
                    env["customers"][0].id,
                    user.id,
                    device_serial="ROLLBACK-TEST",
                )
            assert (
                MaintenanceOrder.query.filter_by(device_serial="ROLLBACK-TEST").count()
                == 0
            )
            assert MaintenanceOrderStatusLog.query.count() == 0
        finally:
            clear_current_tenant_id()


def test_status_change_rolls_back_if_audit_fails(app, db, maintenance_env, monkeypatch):
    env = maintenance_env
    user = env["users"]["engineer"]
    order_id = env["orders"][0].id

    def fail_audit(*args, **kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(service, "_log_status", fail_audit)
    with app.test_request_context("/"):
        login_user(user)
        set_current_tenant_id(env["tenants"][0].id)
        try:
            with pytest.raises(RuntimeError, match="simulated audit failure"):
                service.change_status(order_id, "on_hold", user.id)
            assert db.session.get(MaintenanceOrder, order_id).status == "ready"
            assert MaintenanceOrderStatusLog.query.count() == 0
        finally:
            clear_current_tenant_id()


def test_intake_participates_in_outer_transaction(app, db, maintenance_env):
    from utils.decorators import tx

    env = maintenance_env
    user = env["users"]["reception"]

    @tx
    def outer():
        service.create_maintenance_order(
            env["tenants"][0].id,
            env["customers"][0].id,
            user.id,
            device_serial="NESTED-ROLLBACK",
        )
        raise RuntimeError("outer failure")

    with app.test_request_context("/"):
        login_user(user)
        set_current_tenant_id(env["tenants"][0].id)
        try:
            with pytest.raises(RuntimeError, match="outer failure"):
                outer()
            assert (
                MaintenanceOrder.query.filter_by(
                    device_serial="NESTED-ROLLBACK"
                ).count()
                == 0
            )
            assert MaintenanceOrderStatusLog.query.count() == 0
        finally:
            clear_current_tenant_id()


def test_audit_records_cannot_be_changed_via_orm_or_sql(db, maintenance_env):
    env = maintenance_env
    order, user = env["orders"][0], env["users"]["reception"]
    status = MaintenanceOrderStatusLog(
        maintenance_order_id=order.id,
        to_status="ready",
        changed_by=user.id,
        note="original",
    )
    warranty = MaintenanceWarrantyAudit(
        tenant_id=env["tenants"][0].id,
        maintenance_order_id=order.id,
        action="checked",
        performed_by=user.id,
        reason="original",
    )
    db.session.add_all([status, warranty])
    db.session.commit()
    status_id, warranty_id = status.id, warranty.id
    status.note = "changed"
    with pytest.raises(ValueError, match="append-only"):
        db.session.flush()
    db.session.rollback()
    db.session.delete(db.session.get(MaintenanceWarrantyAudit, warranty_id))
    with pytest.raises(ValueError, match="append-only"):
        db.session.flush()
    db.session.rollback()

    for table, row_id in (
        ("maintenance_order_status_log", status_id),
        ("maintenance_warranty_audit", warranty_id),
    ):
        for statement in (
            f"UPDATE {table} SET id = id WHERE id = :id",
            f"DELETE FROM {table} WHERE id = :id",
        ):
            with pytest.raises(DBAPIError, match="append-only"):
                db.session.execute(text(statement), {"id": row_id})
            db.session.rollback()
        assert (
            db.session.execute(
                text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": row_id}
            ).scalar_one()
            == 1
        )


def test_notification_reports_the_real_provider_outcome(
    app, db, maintenance_env, monkeypatch
):
    """A missing provider must be reported, never presented as "sent"."""
    env = maintenance_env
    order = env["orders"][0]
    order.customer.phone = "+971500000000"

    from services import whatsapp_service

    monkeypatch.setattr(
        whatsapp_service.WhatsAppService, "is_enabled", staticmethod(lambda: False)
    )

    with app.test_request_context("/"):
        login_user(env["users"]["reception"])
        set_current_tenant_id(env["tenants"][0].id)
        try:
            result = service.send_customer_notification(
                order.id, channel="whatsapp", actor_id=env["users"]["reception"].id
            )
            assert result["sent"] is False
            assert result["error"]
            assert (
                "WhatsApp" in result["error"]
                or "WhatsApp" in result["error"]
                or result["error"]
            )
        finally:
            clear_current_tenant_id()


@pytest.mark.parametrize(
    "path",
    [
        "/maintenance/1/gl-post",
    ],
)
def test_direct_posts_to_unverified_routes_are_blocked(client, maintenance_env, path):
    # The GL posting endpoint is not published: the invoice posting owns it.
    _login(client, maintenance_env["users"]["reception"])
    assert client.post(path, data={}).status_code in (404, 503)


def test_settings_get_does_not_write(client, maintenance_env):
    _login(client, maintenance_env["users"]["reception"])
    assert client.get("/maintenance/settings").status_code == 200
    assert MaintenanceSetting.query.count() == 0


def test_scoped_pages_render(client, maintenance_env):
    env = maintenance_env
    _login(client, env["users"]["reception"])
    for path in (
        f"/maintenance/{env['orders'][0].id}",
        "/maintenance/services",
        "/maintenance/devices",
        "/maintenance/cost-report",
    ):
        response = client.get(path)
        assert response.status_code == 200, path


def test_status_history_is_scoped_and_escapes_notes(client, db, maintenance_env):
    env = maintenance_env
    order_a, order_b = env["orders"]
    db.session.add_all(
        [
            MaintenanceOrderStatusLog(
                maintenance_order_id=order_a.id,
                to_status="ready",
                changed_by=env["users"]["other"].id,
                note="<script>own history</script>",
            ),
            MaintenanceOrderStatusLog(
                maintenance_order_id=order_b.id,
                to_status="ready",
                changed_by=env["users"]["other"].id,
                note="FOREIGN-HISTORY-SECRET",
            ),
        ]
    )
    db.session.commit()
    _login(client, env["users"]["reception"])
    response = client.get(f"/maintenance/{order_a.id}")
    assert response.status_code == 200
    assert b"&lt;script&gt;own history&lt;/script&gt;" in response.data
    assert b"<script>own history</script>" not in response.data
    assert b"FOREIGN-HISTORY-SECRET" not in response.data
    assert b"maint-reception-b" not in response.data


def test_intake_print_is_scoped_escaped_and_not_a_payment_document(
    client, db, maintenance_env
):
    env = maintenance_env
    order_a, order_b = env["orders"]
    order_a.device_problem = "<script>device issue</script>"
    order_a.notes = "PRIVATE-INTERNAL-NOTE"
    order_a.received_by = env["users"]["other"].id  # simulate a bad legacy reference
    db.session.commit()
    _login(client, env["users"]["reception"])
    response = client.get(f"/maintenance/{order_a.id}/print-intake")
    assert response.status_code == 200
    assert b"Only customer A" in response.data
    assert b"Only customer B" not in response.data
    assert b"&lt;script&gt;device issue&lt;/script&gt;" in response.data
    assert b"<script>device issue</script>" not in response.data
    assert b"PRIVATE-INTERNAL-NOTE" not in response.data
    assert b"maint-reception-b" not in response.data
    assert "ليس فاتورة ولا سند قبض ولا إثبات ضمان" in response.get_data(as_text=True)
    assert client.get(f"/maintenance/{order_b.id}/print-intake").status_code == 404


def test_receipt_printing_selects_only_receipts_of_the_order(
    client, db, maintenance_env
):
    env = maintenance_env
    order_a, order_b = env["orders"]
    db.session.add_all(
        [
            MaintenanceReceipt(
                maintenance_order_id=order_a.id,
                receipt_no="TEST-RECEIPT-A1",
                amount=10,
                payment_method="cash",
                cashier_id=env["users"]["reception"].id,
            ),
            MaintenanceReceipt(
                maintenance_order_id=order_a.id,
                receipt_no="TEST-RECEIPT-A2",
                amount=20,
                payment_method="cash",
                cashier_id=env["users"]["reception"].id,
            ),
            MaintenanceReceipt(
                maintenance_order_id=order_b.id,
                receipt_no="TEST-RECEIPT-B",
                amount=30,
                payment_method="cash",
                cashier_id=env["users"]["other"].id,
            ),
        ]
    )
    db.session.commit()
    receipt_a = MaintenanceReceipt.query.filter_by(receipt_no="TEST-RECEIPT-A2").one()
    receipt_b = MaintenanceReceipt.query.filter_by(receipt_no="TEST-RECEIPT-B").one()
    _login(client, env["users"]["reception"])
    assert client.get(f"/maintenance/{order_a.id}/print-receipt").status_code == 404
    response = client.get(
        f"/maintenance/{order_a.id}/print-receipt?receipt_id={receipt_a.id}"
    )
    assert response.status_code == 200
    assert b"TEST-RECEIPT-A2" in response.data
    assert b"TEST-RECEIPT-B" not in response.data
    assert (
        client.get(
            f"/maintenance/{order_a.id}/print-receipt?receipt_id={receipt_b.id}"
        ).status_code
        == 404
    )


def test_legacy_cross_tenant_product_is_not_disclosed(client, db, maintenance_env):
    env = maintenance_env
    order = env["orders"][0]
    product = Product(
        name="Foreign private product",
        sku="FOREIGN-MAINT-PRODUCT",
        tenant_id=env["tenants"][1].id,
        regular_price=10,
        is_active=True,
    )
    db.session.add(product)
    db.session.flush()
    db.session.add_all(
        [
            MaintenanceOrderItem(
                maintenance_order_id=order.id,
                product_id=product.id,
                quantity=1,
                unit_price=10,
                line_total=10,
            ),
            MaintenanceInvoice(
                maintenance_order_id=order.id, invoice_no="LEGACY-TEST-INVOICE"
            ),
        ]
    )
    db.session.commit()
    _login(client, env["users"]["reception"])
    for path in (f"/maintenance/{order.id}", f"/maintenance/{order.id}/print-invoice"):
        response = client.get(path)
        assert response.status_code == 200
        assert b"Foreign private product" not in response.data


def test_warranty_lookup_never_selects_an_unidentified_device(app, db, maintenance_env):
    env = maintenance_env
    db.session.add(
        MaintenanceDeviceRegistry(
            tenant_id=env["tenants"][0].id,
            customer_id=env["customers"][0].id,
            serial_number="REGISTERED",
            is_under_warranty=True,
            warranty_end_date=date.today() + timedelta(days=30),
        )
    )
    db.session.commit()
    with app.test_request_context("/"):
        login_user(env["users"]["reception"])
        set_current_tenant_id(env["tenants"][0].id)
        try:
            assert (
                service.auto_check_warranty_from_sales(env["tenants"][0].id)[
                    "warranty_status"
                ]
                == "unknown"
            )
            assert service.auto_check_warranty_from_sales(
                env["tenants"][0].id, serial_number="REGISTERED"
            )["is_under_warranty"]
            assert (
                service.auto_check_warranty_from_sales(
                    env["tenants"][0].id,
                    serial_number="REGISTERED",
                    customer_id=env["customers"][1].id,
                )["warranty_status"]
                == "unknown"
            )
        finally:
            clear_current_tenant_id()


def test_csrf_required_for_reception(client, app, maintenance_env):
    env = maintenance_env
    _login(client, env["users"]["reception"])
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        response = client.post(
            "/maintenance/create", data={"customer_id": env["customers"][0].id}
        )
        assert response.status_code == 400
        # The session-scoped app context is shared by this project's fixture;
        g.pop("csrf_token", None)
        page = client.get("/maintenance/create")
        assert page.status_code == 200
        import re

        match = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)
        assert match
        response = client.post(
            "/maintenance/create",
            data={
                "csrf_token": match.group(1).decode(),
                "customer_id": env["customers"][0].id,
            },
            headers={"Referer": "https://localhost/maintenance/create"},
        )
        assert response.status_code == 302, response.get_data(as_text=True)[:500]
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_csrf_required_for_status_changes(client, app, db, maintenance_env):
    env = maintenance_env
    order_id = env["orders"][0].id
    _login(client, env["users"]["engineer"])
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        response = client.post(
            f"/maintenance/{order_id}/status", data={"status": "on_hold"}
        )
        assert response.status_code == 400
        g.pop("csrf_token", None)
        page = client.get(f"/maintenance/{order_id}")
        import re

        match = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)
        assert match
        response = client.post(
            f"/maintenance/{order_id}/status",
            data={
                "csrf_token": match.group(1).decode(),
                "status": "on_hold",
            },
            headers={"Referer": f"https://localhost/maintenance/{order_id}"},
        )
        assert response.status_code == 302
        db.session.expire_all()
        assert db.session.get(MaintenanceOrder, order_id).status == "on_hold"
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_notes_migration_upgrade_and_downgrade_in_memory():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    migration = importlib.import_module(
        "migrations.versions.b32_maintenance_order_notes"
    )
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE maintenance_orders (id INTEGER PRIMARY KEY)")
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert "notes" in {
                c["name"] for c in inspect(connection).get_columns("maintenance_orders")
            }
            migration.downgrade()
            assert "notes" not in {
                c["name"] for c in inspect(connection).get_columns("maintenance_orders")
            }


def test_audit_guard_migration_upgrade_and_downgrade_in_memory():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine

    migration = importlib.import_module(
        "migrations.versions.b33_maintenance_audit_guard"
    )
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for table in migration.TABLES:
            connection.execute(
                text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, value TEXT)")
            )
            connection.execute(text(f"INSERT INTO {table} VALUES (1, 'original')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            for table in migration.TABLES:
                for statement in (
                    f"UPDATE {table} SET value='changed' WHERE id=1",
                    f"DELETE FROM {table} WHERE id=1",
                ):
                    with pytest.raises(DBAPIError, match="append-only"):
                        connection.execute(text(statement))
                assert (
                    connection.execute(text(f"SELECT value FROM {table}")).scalar_one()
                    == "original"
                )
            migration.downgrade()
            for table in migration.TABLES:
                connection.execute(
                    text(f"UPDATE {table} SET value='changed' WHERE id=1")
                )
                assert (
                    connection.execute(text(f"SELECT value FROM {table}")).scalar_one()
                    == "changed"
                )
