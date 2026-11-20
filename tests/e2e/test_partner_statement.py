"""Customer statement shows product-level shares and their posted GL entries."""
import uuid
from decimal import Decimal


def test_partner_shares_visible_in_customer_statement(client, login_as, app, db):
    from models import Customer, Product, ProductPartner
    from services.gl_service import GLService

    mgr = login_as("manager")
    tag = uuid.uuid4().hex[:8]
    with app.app_context():
        from models.tenant_scope import set_current_tenant_id
        set_current_tenant_id(mgr.tenant_id)
        partner = Customer(name=f"PS-{tag}", customer_type="partner",
                           tenant_id=mgr.tenant_id, is_active=True)
        product = Product(name=f"PSC-{tag}", sku=f"PSC-{tag}",
                          regular_price=Decimal("10"), cost_price=Decimal("8"),
                          current_stock=Decimal("0"), tenant_id=mgr.tenant_id,
                          is_active=True)
        db.session.add_all([partner, product])
        db.session.flush()
        db.session.add(ProductPartner(product_id=product.id,
                                      partner_customer_id=partner.id,
                                      percentage=Decimal("30")))
        GLService.ensure_core_accounts()
        entry = GLService.post_entry(
            [
                {"account": "6910", "debit": Decimal("30"), "party_id": partner.id,
                 "description": "حصة الشريك في ربح الفاتورة"},
                {"account": "3350", "credit": Decimal("30"), "party_id": partner.id,
                 "description": "حصة الشريك في ربح الفاتورة"},
            ],
            description="Partner profit shares for Sale TEST",
            reference_type="Sale", reference_id=1,
            currency="ILS", exchange_rate=Decimal("1"),
        )
        db.session.commit()
        pid, entry_number = partner.id, entry.entry_number

    body = client.get(f"/customers/{pid}/statement").get_data(as_text=True)
    assert "حصص الشركاء" in body
    assert f"PSC-{tag}" in body
    assert "30.00%" in body
    assert entry_number in body
    assert "صافي ما يستحقه الشريك" in body
    assert "30.00" in body
