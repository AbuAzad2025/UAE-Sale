"""Financial-domain integrity: every missing domain posts a BALANCED entry.

Covers the four domains not exercised by the core seed test:

* CHEQUES  — receive / clear (with FX + charges) / bounce
* FX       — multi-currency sale + payment (rate != 1), invalid-rate rejection
* MAINTENANCE — invoice + receipt postings
* PAYROLL  — the real POST /hr/payroll/<id>/pay route (posting lives in the route)

Each domain is driven through its REAL posting path. The invariant checked is
the authoritative one: per entry, the signed sum of ``amount_base`` is zero
(amount_base = (debit - credit) * exchange_rate), plus total_debit==total_credit.
This proves the CODE produces correct accounting, not patched data.
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
    signed = sum((D(line.amount_base) for line in entry.lines), D("0"))
    assert abs(signed) <= D("0.01"), (
        f"entry {entry.entry_number} ({entry.reference_type}) "
        f"unbalanced in amount_base: {signed}"
    )
    assert abs(D(entry.total_debit) - D(entry.total_credit)) <= D("0.01"), (
        f"entry {entry.entry_number} unbalanced in transaction currency"
    )
    assert entry.is_posted is True


def test_remaining_domains_produce_balanced_postings(db, app):
    from extensions import db as _db
    from models import (
        Tenant, User, Role, Permission, Customer, Supplier, Product,
        ProductCategory, Warehouse, Purchase, GLJournalEntry,
    )
    from models.tenant_scope import set_current_tenant_id, clear_current_tenant_id
    from utils.system_init import (
        _ensure_permissions, _ensure_operational_roles_for_tenant,
    )
    from services.gl_service import GLService
    from services.fiscal_period_guard import ensure_periods_for_years
    from datetime import date
    from services.stock_service import StockService

    with app.app_context():
        # --- dedicated tenant -------------------------------------------------
        old = Tenant.query.filter_by(slug="fin-domains-tenant").first()
        if old:
            _db.session.delete(old)
            _db.session.commit()

        _ensure_permissions()
        t = Tenant(
            name="Financial Domains Tenant", name_ar="مختبر المجالات المالية",
            slug="fin-domains-tenant", is_active=True, enable_tax=True,
            enable_maintenance=True, default_currency="ILS",
            default_tax_rate=D("18"),
        )
        _db.session.add(t)
        _db.session.commit()
        tid = t.id
        set_current_tenant_id(tid)
        _ensure_operational_roles_for_tenant(tid)
        GLService.ensure_core_accounts()
        ensure_periods_for_years(
            range(date.today().year - 1, date.today().year + 2)
        )

        # --- master data + an actor with HR + maintenance permissions ---------
        hr_perm = Permission.query.filter_by(code="manage_hr").first()
        if hr_perm is None:
            hr_perm = Permission(code="manage_hr", name="Manage HR", category="hr")
            _db.session.add(hr_perm)
            _db.session.flush()
        codes = [
            "maintenance_view", "maintenance_receive", "maintenance_cashier",
            "maintenance_work", "maintenance_close", "maintenance_discount",
            "maintenance_settings", "maintenance_purchase",
        ]
        m_perms = []
        for code in codes:
            p = Permission.query.filter_by(code=code).first()
            if p is None:
                p = Permission(code=code, name=code, category="maintenance")
                _db.session.add(p)
                _db.session.flush()
            m_perms.append(p)
        actor_role = Role(
            name="Fin Domains Actor", slug="fin-domains-actor",
            permissions=[hr_perm] + m_perms,
        )
        _db.session.add(actor_role)
        _db.session.flush()
        actor = User(
            username="fin_domains_actor", email="fin_domains@test.invalid",
            full_name="Fin Domains Actor", tenant_id=tid, role_id=actor_role.id,
            is_active=True, must_change_password=False,
        )
        actor.set_password("Test-password-123!")
        _db.session.add(actor)

        cat = ProductCategory(name="DomainsCat", is_active=True)
        _db.session.add(cat); _db.session.flush()
        prod = Product(
            name="Domains Product", sku="DOM-1", category_id=cat.id, tenant_id=tid,
            cost_price=D("10"), regular_price=D("20"), current_stock=D("0"),
            is_active=True, unit="piece",
        )
        wh = Warehouse(
            name="Domains WH", name_ar="مخزن", code="DOM-WH", tenant_id=tid,
            is_active=True, is_main=True, is_maintenance_warehouse=True,
        )
        cust = Customer(
            name="Domains Customer", tenant_id=tid, is_active=True,
            customer_type="regular", credit_limit=D("100000"),
        )
        sup = Supplier(name="Domains Supplier", tenant_id=tid, is_active=True)
        _db.session.add_all([prod, wh, cust, sup])
        _db.session.commit()
        StockService.create_movement(
            product_id=prod.id, quantity=D("100"), movement_type="purchase",
            reference_type="setup", reference_id=0, notes="domains stock",
            warehouse_id=wh.id, unit_cost_base=prod.cost_price,
        )
        _db.session.commit()

        # =====================================================================
        # 1) CHEQUES — incoming receive / clear (FX + charges) / bounce
        # =====================================================================
        from services.cheque_accounting_integration import ChequeAccountingIntegration
        from models import Cheque
        from datetime import timedelta

        def _cheque(number, rate):
            ch = Cheque(
                cheque_number=number, cheque_bank_number=number,
                cheque_type="incoming", bank_name="Emirates NBD",
                amount=D("100"), currency="USD", exchange_rate=D(rate),
                issue_date=date.today() - timedelta(days=2),
                due_date=date.today() + timedelta(days=30),
                status="pending", customer_id=cust.id, tenant_id=tid,
            )
            ch.calculate_amount_base()
            _db.session.add(ch)
            _db.session.commit()
            return ch

        # clear path (base amount = 100 * 2 = 200), with bank charges + FX loss
        ch1 = _cheque("DOM-CH-CLEAR", "2")
        assert ch1.amount_base == D("200.00")
        e = ChequeAccountingIntegration.receive_cheque(ch1.id, received_by=actor.id)
        _assert_balanced(e)
        e = ChequeAccountingIntegration.clear_cheque(
            ch1.id, cleared_by=actor.id,
            bank_charges=D("5"), exchange_gain_loss=D("-3"),
        )
        _assert_balanced(e)

        # bounce path restores AR
        ch2 = _cheque("DOM-CH-BOUNCE", "2")
        e = ChequeAccountingIntegration.receive_cheque(ch2.id, received_by=actor.id)
        _assert_balanced(e)
        e = ChequeAccountingIntegration.bounce_cheque(
            ch2.id, bounced_by=actor.id, bounce_reason="insufficient funds"
        )
        _assert_balanced(e)

        # =====================================================================
        # 2) FX / MULTI-CURRENCY — foreign sale + payment at rate != 1
        # =====================================================================
        from services.sale_service import SaleService

        fx_sale = SaleService.create_sale(
            customer=cust, seller=actor,
            lines_data=[{
                "product": prod, "quantity": 2,
                "unit_price": 20.0, "discount_percent": 0, "tax_rate": 18,
            }],
            warehouse_id=wh.id, currency="USD", user_exchange_rate=D("3.7"),
            notes="domains FX sale",
        )
        _db.session.commit()
        expected_base = (D(fx_sale.total_amount) * D("3.7")).quantize(D("0.001"))
        assert abs(D(fx_sale.amount_base) - expected_base) <= D("0.01"), (
            f"sale.amount_base {fx_sale.amount_base} != total*rate {expected_base}"
        )
        for entry in GLJournalEntry.query.filter_by(
            reference_type="Sale", reference_id=fx_sale.id
        ).all():
            _assert_balanced(entry)

        paid = SaleService.create_payment_for_sale(
            fx_sale, fx_sale.total_amount, "cash",
            currency="USD", exchange_rate=D("3.7"),
        )
        _db.session.commit()
        if paid:
            assert abs(D(paid.amount_base) -
                       (D(paid.amount) * D("3.7")).quantize(D("0.001"))) <= D("0.01")
            for entry in GLJournalEntry.query.filter_by(
                reference_type="Payment", reference_id=paid.id
            ).all():
                _assert_balanced(entry)

        # FX fail-closed: a zero/negative rate must be rejected by the engine
        with pytest.raises(ValueError):
            GLService.post_entry(
                [
                    {"account": "1110", "debit": D("10")},
                    {"account": "4210", "credit": D("10")},
                ],
                description="bad fx rate", exchange_rate=D("0"),
            )

        # =====================================================================
        # 3) MAINTENANCE — invoice (revenue+VAT) + receipt posting
        # =====================================================================
        from models.maintenance import (
            MaintenanceOrder, MaintenanceInvoice, MaintenanceReceipt,
        )
        from services import maintenance_accounting as ma

        order = MaintenanceOrder(
            order_no="DOM-MNT-1", customer_id=cust.id, tenant_id=tid,
            received_by=actor.id, currency="ILS", exchange_rate=D("1"),
            total_amount_base=D("118"), tax_amount_base=D("18"),
            cost_price_total=D("20"), status="ready",
        )
        _db.session.add(order)
        _db.session.flush()
        invoice = MaintenanceInvoice(
            maintenance_order_id=order.id, invoice_no="DOM-MINV-1",
            tenant_id=tid, currency="ILS", exchange_rate=D("1"),
            total_amount_base=D("118"), tax_amount_base=D("18"),
            amount_base=D("118"),
        )
        _db.session.add(invoice)
        _db.session.flush()
        e = ma.post_maintenance_invoice(order, invoice, created_by=actor.id)
        _assert_balanced(e)
        for entry in GLJournalEntry.query.filter_by(
            reference_type="maintenance_order:labor"
        ).all():
            _assert_balanced(entry)

        receipt = MaintenanceReceipt(
            maintenance_order_id=order.id, receipt_no="DOM-MRCP-1",
            tenant_id=tid, currency="ILS", exchange_rate=D("1"),
            amount=D("118"), amount_base=D("118"), payment_method="cash",
            cashier_id=actor.id,
        )
        _db.session.add(receipt)
        _db.session.flush()
        e = ma.post_maintenance_receipt(receipt, created_by=actor.id)
        _assert_balanced(e)

        # =====================================================================
        # 4) PAYROLL — real POST /hr/payroll/<id>/pay route
        # =====================================================================
        from models.hr import Department, Employee, Payslip
        from services.hr_service import HRService

        dept = Department(
            name="Domains Dept", name_ar="قسم المجالات", code="DOM-DEP",
            tenant_id=tid, is_active=True,
        )
        _db.session.add(dept)
        _db.session.flush()
        emp = HRService.create_employee(
            user_id=actor.id, employee_number="DOM-EMP-1",
            department_id=dept.id, position="Technician",
            hire_date=date(2024, 1, 1), base_salary=D("3000"),
        )
        _db.session.commit()
        today = date.today()
        payslip = HRService.generate_payslip(
            emp.id, date(today.year, today.month, 1), today, today,
            working_days=22, created_by=actor.id,
            bonus=D("200"), other_deductions=D("100"),
        )
        payslip.approve(actor.id)
        _db.session.commit()
        assert payslip.total_earnings > 0 and payslip.net_salary > 0

        client = app.test_client()
        resp = client.post(
            "/auth/login",
            data={"username": "fin_domains_actor", "password": "Test-password-123!"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        resp = client.post(f"/hr/payroll/{payslip.id}/pay", follow_redirects=True)
        assert resp.status_code == 200
        _db.session.expire_all()
        payroll_entries = GLJournalEntry.query.filter_by(
            reference_type="Payslip", reference_id=payslip.id
        ).all()
        assert payroll_entries, "payroll route produced no GL entry"
        for entry in payroll_entries:
            _assert_balanced(entry)
        # Dr salary expense = earnings; Cr payable = deductions + cash = net + deductions
        pe = payroll_entries[0]
        assert D(pe.total_debit) == D("3200.000")
        assert D(pe.total_credit) == D("3200.000")

        # =====================================================================
        # 5) Every entry in the dedicated tenant is balanced & tenant-consistent
        # =====================================================================
        for entry in GLJournalEntry.query.filter_by(tenant_id=tid).all():
            _assert_balanced(entry)
            for line in entry.lines:
                assert line.tenant_id == tid, "cross-tenant GL line in domains seed"

        clear_current_tenant_id()
