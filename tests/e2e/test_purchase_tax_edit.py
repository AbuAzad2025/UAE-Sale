"""A tenant manager may correct a purchase invoice's VAT through the UI; the
edit reverses/reposts the journal and never touches another tenant's invoice.
"""
import uuid
from decimal import Decimal

from sqlalchemy import text


def _make_purchase(db, tenant_id, user_id, tag):
    from models import Product, Purchase, PurchaseLine

    p = Product(name=f"PTX-{tag}", sku=f"PTX-{tag}", regular_price=Decimal("1500"),
                cost_price=Decimal("1200"), current_stock=Decimal("10"),
                average_cost=Decimal("1200"), tenant_id=tenant_id, is_active=True)
    db.session.add(p)
    db.session.flush()
    pur = Purchase(purchase_number=f"PTX-{tag}", supplier_name="PTX SUP",
                   user_id=user_id, tenant_id=tenant_id, currency="ILS",
                   tax_rate=Decimal("0"), tax_inclusive=False, vat_recoverable=True,
                   tax_treatment="standard", exchange_rate=Decimal("1"),
                   subtotal=Decimal("1200"), tax_amount=Decimal("0"),
                   total_amount=Decimal("1200"), amount_base=Decimal("1200"))
    db.session.add(pur)
    db.session.flush()
    line = PurchaseLine(purchase_id=pur.id, product_id=p.id, quantity=Decimal("1"),
                        unit_cost=Decimal("1200"), line_total=Decimal("1200"),
                        tax_treatment="standard", tenant_id=tenant_id)
    db.session.add(line)
    db.session.commit()
    return pur.id, p.id


def _post_tax(client, pid, rate="16", inclusive="on"):
    return client.post(
        f"/purchases/{pid}/edit",
        data={"tax_rate": rate, "tax_treatment": "standard", "tax_inclusive": inclusive,
              "vat_recoverable": "on", "notes": "VAT corrected", "due_date": ""},
        follow_redirects=False,
    )


def test_manager_can_correct_purchase_vat(client, login_as, app, db):
    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        pid, product_id = _make_purchase(db, mgr.tenant_id, mgr.id, tag)

    resp = _post_tax(client, pid)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)[:300]

    with app.app_context():
        row = db.session.execute(
            text("SELECT tax_rate, tax_inclusive, tax_amount, total_amount "
                 "FROM purchases WHERE id=:i"), {"i": pid}).first()
        assert row.tax_rate == 16
        assert bool(row.tax_inclusive) is True
        assert row.tax_amount > 0
        assert row.total_amount == Decimal("1200.000")
        prod = db.session.execute(
            text("SELECT average_cost FROM products WHERE id=:i"), {"i": product_id}).first()
        assert Decimal(str(prod.average_cost)) < Decimal("1200"), \
            "inventory cost must drop to net of VAT"


def test_manager_cannot_edit_foreign_purchase(client, login_as, app, db):
    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        from models import Tenant

        other = db.session.execute(
            text("SELECT id FROM tenants WHERE id != :t ORDER BY id LIMIT 1"),
            {"t": mgr.tenant_id}).first()
        if other is None:
            t = Tenant(name=f"O {tag}", name_ar=f"O {tag}", slug=f"o-{tag}", is_active=True)
            db.session.add(t)
            db.session.commit()
            other_tid = t.id
        else:
            other_tid = other.id
        foreign_id, _ = _make_purchase(db, other_tid, mgr.id, tag)

    resp = _post_tax(client, foreign_id)
    assert resp.status_code == 404
