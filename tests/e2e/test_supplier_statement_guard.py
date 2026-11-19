"""The supplier statement uses manage_suppliers, not owner-only admin.
A manager sees their own tenant's supplier statement and gets 404 on another
tenant's supplier.
"""
import uuid

from sqlalchemy import text


def _supplier(db, tenant_id, tag):
    from models import Supplier

    s = Supplier(name=f"ST-{tag}", supplier_type="materials",
                 tenant_id=tenant_id, is_active=True)
    db.session.add(s)
    db.session.commit()
    return s.id


def test_manager_can_open_own_supplier_statement(client, login_as, app, db):
    mgr = login_as("manager")
    with app.app_context():
        sid = _supplier(db, mgr.tenant_id, uuid.uuid4().hex[:8])

    resp = client.get(f"/suppliers/{sid}/statement")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    body = resp.get_data(as_text=True)
    assert "معاينة الطباعة" in body
    assert "حركة الحساب" in body

    # Dedicated clean print preview (A4 document, no app chrome).
    printed = client.get(f"/suppliers/{sid}/statement/print")
    assert printed.status_code == 200, printed.get_data(as_text=True)[:300]
    pbody = printed.get_data(as_text=True)
    assert "كشف حساب المورد" in pbody
    assert "AzadERP" in pbody
    assert "main-sidebar" not in pbody  # base_print, not the app shell
    assert "رجوع للكشف" in pbody
    assert f'/suppliers/{sid}/statement"' in pbody  # back link target


def test_statement_rows_have_expandable_details_and_doc_links(client, login_as, app, db):
    from models import Payment, Product, Purchase, PurchaseLine
    from decimal import Decimal

    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        sid = _supplier(db, mgr.tenant_id, tag)
        product = Product(name=f"DET-{tag}", sku=f"DET-{tag}",
                          regular_price=Decimal("10"), cost_price=Decimal("8"),
                          current_stock=Decimal("0"), tenant_id=mgr.tenant_id,
                          is_active=True)
        db.session.add(product)
        db.session.flush()
        pur = Purchase(purchase_number=f"DET-P-{tag}", supplier_name="DET",
                       supplier_id=sid,
                       user_id=mgr.id, tenant_id=mgr.tenant_id, currency="ILS",
                       tax_rate=Decimal("0"), tax_inclusive=False, vat_recoverable=True,
                       exchange_rate=Decimal("1"), subtotal=Decimal("100"),
                       tax_amount=Decimal("0"), total_amount=Decimal("100"),
                       amount_base=Decimal("100"))
        db.session.add(pur)
        db.session.flush()
        db.session.add(PurchaseLine(purchase_id=pur.id, product_id=product.id,
                                    quantity=Decimal("10"), unit_cost=Decimal("10"),
                                    line_total=Decimal("100"), tax_treatment="standard",
                                    tenant_id=mgr.tenant_id))
        db.session.add(Payment(payment_number=f"DET-PAY-{tag}", supplier_id=sid,
                               user_id=mgr.id, tenant_id=mgr.tenant_id,
                               amount=Decimal("40"), amount_base=Decimal("40"),
                               currency="ILS", exchange_rate=Decimal("1"),
                               payment_method="cash", direction="outgoing",
                               payment_type="supplier_payment", payment_confirmed=True))
        db.session.commit()

    body = client.get(f"/suppliers/{sid}/statement").get_data(as_text=True)
    assert "st-toggle" in body
    assert "فتح الفاتورة الأصلية" in body
    assert "فتح السند الأصلي" in body
    assert f"DET-{tag}" in body

    printed = client.get(f"/suppliers/{sid}/statement/print").get_data(as_text=True)
    assert "منتجات:" in printed
    assert "الشيك:" in printed


def test_print_pages_get_auto_back_link(client, login_as, app, db):
    """Any /.../<id>/print preview gets a back link to /.../<id>."""
    from models import Product, Purchase, PurchaseLine
    from decimal import Decimal

    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        product = Product(name=f"PB-{tag}", sku=f"PB-{tag}",
                          regular_price=Decimal("10"), cost_price=Decimal("8"),
                          current_stock=Decimal("0"), tenant_id=mgr.tenant_id,
                          is_active=True)
        db.session.add(product)
        db.session.flush()
        pur = Purchase(purchase_number=f"PB-{tag}", supplier_name="PB",
                       user_id=mgr.id, tenant_id=mgr.tenant_id, currency="ILS",
                       tax_rate=Decimal("0"), tax_inclusive=False, vat_recoverable=True,
                       exchange_rate=Decimal("1"), subtotal=Decimal("100"),
                       tax_amount=Decimal("0"), total_amount=Decimal("100"),
                       amount_base=Decimal("100"))
        db.session.add(pur)
        db.session.flush()
        db.session.add(PurchaseLine(purchase_id=pur.id, product_id=product.id,
                                    quantity=Decimal("10"), unit_cost=Decimal("10"),
                                    line_total=Decimal("100"), tax_treatment="standard",
                                    tenant_id=mgr.tenant_id))
        db.session.commit()
        pid = pur.id

    resp = client.get(f"/purchases/{pid}/print")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    body = resp.get_data(as_text=True)
    assert "رجوع" in body
    assert f'href="/purchases/{pid}"' in body


def test_manager_cannot_open_foreign_supplier_statement(client, login_as, app, db):
    mgr = login_as("manager")
    with app.app_context():
        from models import Tenant

        other = db.session.execute(
            text("SELECT id FROM tenants WHERE id != :t ORDER BY id LIMIT 1"),
            {"t": mgr.tenant_id}).first()
        if other is None:
            tag = uuid.uuid4().hex[:8]
            t = Tenant(name=f"O {tag}", name_ar=f"O {tag}", slug=f"o-{tag}", is_active=True)
            db.session.add(t)
            db.session.commit()
            other_tid = t.id
        else:
            other_tid = other.id
        sid = _supplier(db, other_tid, uuid.uuid4().hex[:8])

    resp = client.get(f"/suppliers/{sid}/statement")
    assert resp.status_code == 404
