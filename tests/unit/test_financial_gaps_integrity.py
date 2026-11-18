"""Close the remaining GL-balance coverage gaps.

Drives REAL posting paths that previously had no balance assertion:

* FIXED ASSETS — depreciation + disposal (gain & scrap loss)
* MAINTENANCE sub-types — parts issue, deposit, warranty reclass, return cost,
  credit note, goods receipt, supplier payment
* PARTNER SHARES — sale shares, return-share reversal, partner draw
* FX DIFFERENCE — loss/gain posting on receipt allocation

Every produced GLJournalEntry is asserted balanced in amount_base AND in
transaction currency. No data patching; the code paths produce the result.
"""
import os
from decimal import Decimal

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgres"),
    reason="PostgreSQL-only: creates a dedicated tenant",
)

D = lambda v: Decimal(str(v or 0))


def _assert_balanced(entry):
    lines = list(entry.lines)
    signed = sum((D(line.amount_base) for line in lines), D("0"))
    d = sum((D(line.debit) for line in lines), D("0"))
    c = sum((D(line.credit) for line in lines), D("0"))
    assert abs(signed) <= D("0.01"), (
        f"entry {entry.entry_number} ({entry.reference_type}) "
        f"unbalanced in amount_base: {signed}"
    )
    assert abs(d - c) <= D("0.01"), (
        f"entry {entry.entry_number} unbalanced in transaction currency: {d} != {c}"
    )
    assert entry.is_posted is True


def _entries(ref_type, ref_id=None):
    from models import GLJournalEntry
    q = GLJournalEntry.query.filter_by(reference_type=ref_type)
    if ref_id is not None:
        q = q.filter_by(reference_id=ref_id)
    return q.all()


def test_remaining_gaps_post_balanced_entries(db, app):
    from extensions import db as _db
    from models import (
        Tenant, User, Role, Permission, Customer, Supplier, Product,
        ProductCategory, Warehouse, GLAccount, GLJournalEntry, ProductPartner,
    )
    from models.fixed_asset import FixedAsset
    from models.maintenance import (
        MaintenanceOrder, MaintenanceOrderItem, MaintenanceReceipt,
        MaintenanceReturn, MaintenanceInvoice, MaintenanceCreditNote,
        MaintenanceSupplierPayment,
    )
    from models.erp_modules import PurchaseOrder
    from models.tenant_scope import set_current_tenant_id, clear_current_tenant_id
    from utils.system_init import (
        _ensure_permissions, _ensure_operational_roles_for_tenant,
    )
    from services.gl_service import GLService
    from services.fiscal_period_guard import ensure_periods_for_years
    from services.stock_service import StockService
    from datetime import date

    with app.app_context():
        old = Tenant.query.filter_by(slug="fin-gaps-tenant").first()
        if old:
            _db.session.delete(old)
            _db.session.commit()

        _ensure_permissions()
        t = Tenant(
            name="Financial Gaps Tenant", name_ar="مختبر الفجوات المالية",
            slug="fin-gaps-tenant", is_active=True, enable_tax=True,
            enable_maintenance=True, default_currency="ILS",
            default_tax_rate=D("18"),
        )
        _db.session.add(t)
        _db.session.commit()
        tid = t.id
        set_current_tenant_id(tid)
        _ensure_operational_roles_for_tenant(tid)
        GLService.ensure_core_accounts()
        ensure_periods_for_years(range(date.today().year - 1, date.today().year + 2))

        # actor
        perm = Permission.query.filter_by(code="manage_hr").first()
        if perm is None:
            perm = Permission(code="manage_hr", name="Manage HR", category="hr")
            _db.session.add(perm); _db.session.flush()
        role = Role(name="Gaps Actor", slug="gaps-actor", permissions=[perm])
        _db.session.add(role); _db.session.flush()
        actor = User(
            username="fin_gaps_actor", email="fin_gaps@test.invalid",
            full_name="Gaps Actor", tenant_id=tid, role_id=role.id,
            is_active=True, must_change_password=False,
        )
        actor.set_password("Test-password-123!")
        _db.session.add(actor)

        cat = ProductCategory(name="GapsCat", is_active=True)
        _db.session.add(cat); _db.session.flush()
        prod = Product(
            name="Gaps Product", sku="GAP-1", category_id=cat.id, tenant_id=tid,
            cost_price=D("10"), regular_price=D("20"), current_stock=D("0"),
            average_cost=D("10"), is_active=True, unit="piece",
        )
        wh = Warehouse(
            name="Gaps WH", name_ar="مخزن", code="GAP-WH", tenant_id=tid,
            is_active=True, is_main=True, is_maintenance_warehouse=True,
        )
        cust = Customer(
            name="Gaps Customer", tenant_id=tid, is_active=True,
            customer_type="regular", credit_limit=D("100000"),
        )
        sup = Supplier(name="Gaps Supplier", tenant_id=tid, is_active=True)
        _db.session.add_all([prod, wh, cust, sup])
        _db.session.commit()
        StockService.create_movement(
            product_id=prod.id, quantity=D("100"), movement_type="purchase",
            reference_type="setup", reference_id=0, notes="gaps stock",
            warehouse_id=wh.id, unit_cost_base=prod.cost_price,
        )
        _db.session.commit()

        # =====================================================================
        # A) FIXED ASSETS — depreciation + disposal (gain & scrap loss)
        # =====================================================================
        def _acc(code, name, atype):
            a = GLAccount.query.filter_by(code=code).first()
            if a is None:
                a = GLAccount(code=code, name=name, name_ar=name, type=atype)
                _db.session.add(a); _db.session.flush()
            return a

        asset_acc = _acc("1500", "Fixed Assets", "asset")
        dep_acc = _acc("1501", "Accumulated Depreciation", "asset")
        exp_acc = GLAccount.query.filter_by(code="6100").first()

        def _asset(number, price):
            a = FixedAsset(
                asset_number=number, name_ar="أصل اختبار", tenant_id=tid,
                asset_account_id=asset_acc.id, depreciation_account_id=dep_acc.id,
                expense_account_id=exp_acc.id, purchase_date=date(2024, 1, 1),
                purchase_price=D(price), salvage_value=D("0"),
                useful_life_years=5, accumulated_depreciation=D("0"),
                book_value=D(price), status="active",
            )
            _db.session.add(a); _db.session.flush()
            return a

        dep_asset = _asset("GAP-FA-DEP", "12000")
        dep_asset.post_depreciation(date.today())
        dep_entries = _entries("depreciation", dep_asset.id)
        assert dep_entries, "depreciation produced no GL entry"
        for e in dep_entries:
            _assert_balanced(e)

        gain_asset = _asset("GAP-FA-GAIN", "12000")
        gain_asset.dispose(date.today(), D("13000"), notes="sale at gain")
        gain_entries = _entries("asset_disposal", gain_asset.id)
        assert gain_entries, "disposal-at-gain produced no GL entry"
        for e in gain_entries:
            _assert_balanced(e)
        assert D(gain_asset.disposal_gain_loss) == D("1000")

        scrap_asset = _asset("GAP-FA-SCRAP", "12000")
        scrap_asset.dispose(date.today(), D("0"), notes="scrap at loss")
        scrap_entries = _entries("asset_disposal", scrap_asset.id)
        assert scrap_entries, "scrap produced no GL entry"
        for e in scrap_entries:
            _assert_balanced(e)
        assert D(scrap_asset.disposal_gain_loss) == D("-12000")

        # =====================================================================
        # B) MAINTENANCE sub-types — every post_* path balanced
        # =====================================================================
        from services import maintenance_accounting as ma

        order = MaintenanceOrder(
            order_no="GAP-MNT-1", customer_id=cust.id, tenant_id=tid,
            received_by=actor.id, currency="ILS", exchange_rate=D("1"),
            total_amount_base=D("118"), tax_amount_base=D("18"),
            cost_price_total=D("20"), status="ready",
        )
        _db.session.add(order); _db.session.flush()

        item = MaintenanceOrderItem(
            maintenance_order_id=order.id, product_id=prod.id,
            quantity=D("2"), returned_quantity=D("0"), cost_price=D("10"),
        )
        _db.session.add(item); _db.session.flush()
        e = ma.post_parts_issue(order, item, unit_cost=D("10"), quantity=D("2"),
                                created_by=actor.id)
        _assert_balanced(e)

        rec = MaintenanceReceipt(
            maintenance_order_id=order.id, receipt_no="GAP-DEP-1", tenant_id=tid,
            currency="ILS", exchange_rate=D("1"), amount=D("50"),
            amount_base=D("50"), payment_method="cash", cashier_id=actor.id,
        )
        _db.session.add(rec); _db.session.flush()
        e = ma.post_deposit_receipt(order, rec, created_by=actor.id)
        _assert_balanced(e)

        e = ma.post_warranty_reclassification(order, created_by=actor.id)
        assert e is not None, "warranty reclass produced no GL entry"
        _assert_balanced(e)

        ret = MaintenanceReturn(
            maintenance_order_id=order.id, return_no="GAP-RET-1", tenant_id=tid,
            returned_by=actor.id, reason="gap test",
        )
        _db.session.add(ret); _db.session.flush()
        e = ma.post_return_cost(order, ret, D("10"), created_by=actor.id)
        _assert_balanced(e)

        inv = MaintenanceInvoice(
            maintenance_order_id=order.id, invoice_no="GAP-INV-1", tenant_id=tid,
            currency="ILS", exchange_rate=D("1"), total_amount_base=D("118"),
            tax_amount_base=D("18"), amount_base=D("118"),
        )
        _db.session.add(inv); _db.session.flush()
        _db.session.expire(order)
        cn = MaintenanceCreditNote(
            maintenance_order_id=order.id, credit_note_no="GAP-CN-1",
            tenant_id=tid, amount_base=D("118"), created_by=actor.id,
        )
        _db.session.add(cn); _db.session.flush()
        e = ma.post_maintenance_credit_note(order, cn, created_by=actor.id)
        _assert_balanced(e)

        po = PurchaseOrder(
            po_number="GAP-PO-1", supplier_id=sup.id, po_date=date.today(),
            tenant_id=tid, subtotal=D("100"), tax_amount=D("18"),
        )
        _db.session.add(po); _db.session.flush()
        e = ma.post_goods_receipt(po, created_by=actor.id)
        _assert_balanced(e)

        smp = MaintenanceSupplierPayment(
            tenant_id=tid, supplier_id=sup.id, created_by=actor.id,
            payment_method="cash", amount_base=D("50"),
        )
        _db.session.add(smp); _db.session.flush()
        e = ma.post_supplier_payment(smp, created_by=actor.id)
        _assert_balanced(e)

        # =====================================================================
        # C) PARTNER SHARES — sale, return reversal, draw
        # =====================================================================
        from services.sale_service import SaleService
        from services.return_service import ReturnService
        from services.partner_profit import (
            post_partner_shares_for_sale, post_partner_shares_for_return,
            post_partner_draw,
        )

        partner = Customer(
            name="Gaps Partner", tenant_id=tid, is_active=True,
            customer_type="partner", partner_scope="company",
            partner_share=D("25"), credit_limit=D("100000"),
        )
        _db.session.add(partner); _db.session.flush()
        _db.session.add(ProductPartner(
            product_id=prod.id, partner_customer_id=partner.id,
            percentage=D("25"),
        ))
        _db.session.commit()

        p_sale = SaleService.create_sale(
            customer=partner, seller=actor,
            lines_data=[{
                "product": prod, "quantity": 4,
                "unit_price": 20.0, "discount_percent": 0, "tax_rate": 18,
            }],
            warehouse_id=wh.id, currency="ILS", notes="gaps partner sale",
        )
        _db.session.commit()
        share_entries = [
            e for e in _entries("Sale", p_sale.id)
            if any(D(ln.debit or 0) > 0 and "6910" in (ln.account.code or "")
                   for ln in e.lines)
        ]
        assert share_entries, "partner sale-share posting missing"
        for e in share_entries:
            _assert_balanced(e)

        p_ret = ReturnService.create_return(
            p_sale.id, [{"sale_line_id": p_sale.lines[0].id, "quantity": 1}],
            user_id=actor.id, notes="gaps partner return",
        )
        _db.session.commit()
        rev_entries = [
            e for e in _entries("ProductReturn", p_ret.id)
            if any(D(ln.credit or 0) > 0 and "6910" in (ln.account.code or "")
                   for ln in e.lines)
        ]
        assert rev_entries, "partner return-share reversal missing"
        for e in rev_entries:
            _assert_balanced(e)

        draw_entry = post_partner_draw(partner.id, D("10"))
        _db.session.commit()
        assert draw_entry is not None
        _assert_balanced(draw_entry)

        # =====================================================================
        # D) FX DIFFERENCE — gain & loss posting on receipt
        # =====================================================================
        from services.payment_service import PaymentService
        from models import Receipt

        fx_receipt = Receipt(
            receipt_number="GAP-RCP-1", customer_id=cust.id, sale_id=p_sale.id,
            amount=D("10"), amount_base=D("10"), currency="ILS",
            payment_method="cash",
        )
        _db.session.add(fx_receipt); _db.session.flush()
        loss = PaymentService.post_fx_difference(p_sale, D("10"), fx_receipt)
        gain = PaymentService.post_fx_difference(p_sale, D("-5"), fx_receipt)
        _db.session.commit()
        assert loss is not None and gain is not None
        _assert_balanced(loss)
        _assert_balanced(gain)

        # =====================================================================
        # E) all entries in the tenant are balanced and tenant-consistent
        # =====================================================================
        for e in GLJournalEntry.query.filter_by(tenant_id=tid).all():
            _assert_balanced(e)
            for line in e.lines:
                assert line.tenant_id == tid, "cross-tenant GL line in gaps seed"

        clear_current_tenant_id()
