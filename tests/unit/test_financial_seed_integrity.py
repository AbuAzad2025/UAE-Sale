"""Specialized financial seed: exercise every document through the REAL
services and assert each produced journal entry is balanced in amount_base.

This is the code-correctness counterpart of a data seed. It does not patch
balances; it drives the posting services and proves the code produces correct,
balanced accounting for a dedicated tenant.
"""
import os
import pytest
from decimal import Decimal

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgres"),
    reason="PostgreSQL-only: creates a dedicated tenant",
)

D = lambda v: Decimal(str(v or 0))


def _assert_entry_balanced(entry):
    signed = sum(D(l.amount_base) for l in entry.lines)
    assert abs(signed) <= Decimal("0.01"), (
        f"entry {entry.entry_number} unbalanced: {signed}"
    )


def test_financial_documents_produce_balanced_postings(db, app):
    from extensions import db as _db
    from models import (
        Tenant, User, Customer, Supplier, Product, ProductCategory,
        Warehouse, Purchase, GLJournalEntry,
    )
    from models.tenant_scope import set_current_tenant_id, clear_current_tenant_id
    from utils.system_init import _ensure_permissions, _ensure_operational_roles_for_tenant
    from services.gl_service import GLService
    from services.sale_service import SaleService
    from services.purchase_gl import build_purchase_gl_lines
    from services.writeoff_service import WriteOffService
    from datetime import date

    # Dedicated tenant for this test; clean up any prior run.
    with app.app_context():
        old = Tenant.query.filter_by(slug="fin-seed-tenant").first()
        if old:
            _db.session.delete(old)
            _db.session.commit()

        _ensure_permissions()
        t = Tenant(name="Financial Seed Tenant", name_ar="مختبر مالي", slug="fin-seed-tenant",
                   is_active=True, default_currency="ILS", enable_tax=True, default_tax_rate=Decimal("18"))
        _db.session.add(t)
        _db.session.commit()
        tid = t.id
        set_current_tenant_id(tid)
        _ensure_operational_roles_for_tenant(tid)
        GLService.ensure_core_accounts()

        from services.fiscal_period_guard import ensure_periods_for_years
        ensure_periods_for_years(range(date.today().year - 1, date.today().year + 2))

        # Minimal master data through ORM (services post the GL).
        cat = ProductCategory(name="FinSeedCat", is_active=True)
        _db.session.add(cat); _db.session.flush()
        prod = Product(name="FinSeed Product", sku="FINSEED-1", category_id=cat.id,
                       tenant_id=tid, cost_price=Decimal("10"), regular_price=Decimal("20"),
                       current_stock=Decimal("0"), is_active=True, unit="piece")
        _db.session.add(prod)
        wh = Warehouse(name="FinSeed WH", name_ar="مخزن", code="FS-WH", tenant_id=tid,
                       is_active=True, is_main=True)
        _db.session.add(wh)
        cust = Customer(name="FinSeed Customer", tenant_id=tid, is_active=True,
                        customer_type="regular", credit_limit=Decimal("100000"))
        _db.session.add(cust)
        sup = Supplier(name="FinSeed Supplier", tenant_id=tid, is_active=True)
        _db.session.add(sup)
        seller = User.query.filter_by(tenant_id=tid).first()
        _db.session.commit()

        # Seed initial stock through the real stock service (posts no GL, as
        # designed, but creates the warehouse-aware movement the sale needs).
        from services.stock_service import StockService
        StockService.create_movement(
            product_id=prod.id, quantity=Decimal("50"), movement_type="purchase",
            reference_type="fin-seed-setup", reference_id=0, notes="fin seed stock",
            warehouse_id=wh.id, unit_cost_base=prod.cost_price,
        )
        _db.session.commit()

        # 1) SALE -> invoice + COGS entries
        sale = SaleService.create_sale(
            customer=cust, seller=seller,
            lines_data=[{"product": prod, "quantity": 3,
                         "unit_price": 20.0, "discount_percent": 0, "tax_rate": 18}],
            warehouse_id=wh.id, currency="ILS", notes="fin-seed sale",
        )
        _db.session.commit()
        sale_entries = GLJournalEntry.query.filter_by(reference_type="Sale", reference_id=sale.id).all()
        assert sale_entries, "sale produced no GL entry"
        for e in sale_entries:
            _assert_entry_balanced(e)

        # 2) PAYMENT against the sale
        paid = SaleService.create_payment_for_sale(
            sale, Decimal(str(sale.total_amount)), "cash",
            currency="ILS", exchange_rate=Decimal("1"),
        )
        _db.session.commit()
        if paid:
            pe = GLJournalEntry.query.filter_by(reference_type="Payment", reference_id=paid.id).all()
            for e in pe:
                _assert_entry_balanced(e)

        # 3) PURCHASE with VAT (recoverable) -> balanced via purchase_gl builder
        purchase = Purchase(purchase_number="FS-PUR-1", supplier_id=sup.id,
                            supplier_name=sup.name, total_amount=Decimal("118"),
                            amount_base=Decimal("118"), tax_amount=Decimal("18"),
                            currency="ILS", exchange_rate=Decimal("1"),
                            tenant_id=tid, user_id=seller.id, status="confirmed",
                            vat_recoverable=True)
        _db.session.add(purchase); _db.session.commit()
        lines = build_purchase_gl_lines(purchase)
        assert abs(sum(D(l.get("debit", 0)) for l in lines) -
                   sum(D(l.get("credit", 0)) for l in lines)) <= Decimal("0.01"), (
            f"purchase GL lines unbalanced: {lines}"
        )
        entry = GLService.post_entry(lines, description="fin-seed purchase",
                                     reference_type="Purchase", reference_id=purchase.id)
        _db.session.commit()
        _assert_entry_balanced(entry)

        # 4) SALES RETURN -> reversal GL entries (revenue/VAT/cost) balanced
        from services.return_service import ReturnService
        ret_lines = [{"sale_line_id": sale.lines[0].id, "quantity": 1}]
        ret = ReturnService.create_return(sale.id, ret_lines, user_id=seller.id,
                                          notes="fin-seed return")
        _db.session.commit()
        ret_entries = GLJournalEntry.query.filter_by(reference_type="ProductReturn",
                                                     reference_id=ret.id).all()
        assert ret_entries, "return produced no GL entry"
        for e in ret_entries:
            _assert_entry_balanced(e)

        # 5) WRITE-OFF -> bad debt expense / AR, balanced.
        # The first sale was paid in full, so create a dedicated UNPAID sale
        # to produce a genuine outstanding AR balance to write off. This is a
        # test-fixture need; the validation being exercised is correct code.
        wo_cust = Customer(name="FinSeed Writeoff Customer", tenant_id=tid,
                           is_active=True, customer_type="regular",
                           credit_limit=Decimal("100000"))
        _db.session.add(wo_cust)
        _db.session.commit()
        unpaid_sale = SaleService.create_sale(
            customer=wo_cust, seller=seller,
            lines_data=[{"product": prod, "quantity": 2,
                         "unit_price": 20.0, "discount_percent": 0, "tax_rate": 18}],
            warehouse_id=wh.id, currency="ILS", notes="fin-seed unpaid sale",
        )
        _db.session.commit()
        for e in GLJournalEntry.query.filter_by(reference_type="Sale",
                                                reference_id=unpaid_sale.id).all():
            _assert_entry_balanced(e)

        wo = WriteOffService.create_writeoff(
            wo_cust, Decimal("10"), currency="ILS", reason="fin-seed writeoff",
            sale=unpaid_sale, user=seller,
        )
        _db.session.commit()
        wo_entry = GLJournalEntry.query.filter_by(id=wo.gl_entry_id).first()
        assert wo_entry, "write-off produced no GL entry"
        _assert_entry_balanced(wo_entry)

        # 6) All entries in the dedicated tenant are balanced, no cross-tenant mix
        all_entries = GLJournalEntry.query.filter_by(tenant_id=tid).all()
        for e in all_entries:
            _assert_entry_balanced(e)
            for line in e.lines:
                assert line.tenant_id == tid, "cross-tenant GL line in seed"

        clear_current_tenant_id()
