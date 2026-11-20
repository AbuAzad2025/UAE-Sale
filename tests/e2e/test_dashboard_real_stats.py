"""Dashboard cards must use real GL codes and real purchase aggregates."""
from decimal import Decimal

from extensions import cache
from utils.transaction import atomic_transaction


def test_dashboard_shows_real_cheque_payment_payables_maintenance_cards(client, login_as):
    login_as("manager")
    body = client.get("/dashboard").get_data(as_text=True)
    for label in ("شيكات معلقة", "دفعات اليوم (صادر / وارد)",
                  "أوامر صيانة مفتوحة", "الذمم الدائنة"):
        assert label in body
    # Payables card is sourced from GL account 2110, not a hardcoded number.
    assert "من الأستاذ (2110)" in body


def test_dashboard_uses_correct_gl_account_codes():
    src = open("routes/main.py", encoding="utf-8").read()
    assert '("1110", "cash_balance")' in src
    assert '("1120", "bank_balance")' in src
    assert '("1140", "inventory_value_gl")' in src
    # The old wrong codes must be gone.
    assert '("1000", "cash_balance")' not in src
    assert '("1200", "inventory_value_gl")' not in src


def test_dashboard_shows_real_purchases_count(client, login_as, app, db):
    from models import Product, Purchase, PurchaseLine

    mgr = login_as("manager")
    cache.clear()
    with app.app_context():
        p = Product(name="DASH-P", sku="DASH-P", regular_price=Decimal("10"),
                    cost_price=Decimal("8"), current_stock=Decimal("0"),
                    tenant_id=mgr.tenant_id, is_active=True)
        db.session.add(p)
        db.session.flush()
        with atomic_transaction():
            pur = Purchase(purchase_number="DASH-INV", supplier_name="X",
                           user_id=mgr.id, tenant_id=mgr.tenant_id, currency="ILS",
                           tax_rate=Decimal("0"), tax_inclusive=False,
                           vat_recoverable=True, exchange_rate=Decimal("1"),
                           subtotal=Decimal("100"), tax_amount=Decimal("0"),
                           total_amount=Decimal("100"), amount_base=Decimal("100"))
            db.session.add(pur)
            db.session.flush()
            db.session.add(PurchaseLine(purchase_id=pur.id, product_id=p.id,
                                        quantity=Decimal("10"), unit_cost=Decimal("10"),
                                        line_total=Decimal("100"),
                                        tax_treatment="standard",
                                        tenant_id=mgr.tenant_id))

    cache.clear()
    body = client.get("/dashboard").get_data(as_text=True)
    assert "مشتريات الشهر" in body
    # The card is shown and reflects the persisted purchase.
    import re

    i = body.find("مشتريات الشهر")
    assert i >= 0
    assert ">1<" in body[max(0, i - 400):i]  # count is rendered before the label
    assert "100" in body[i:i + 400]  # real amount_base of the purchase
