"""Coverage tests for finance services (F5/F37/F38/F41 + contracts)."""
from datetime import datetime
from decimal import Decimal

import pytest

from extensions import db as _db
from models import GLAccount, GLJournalEntry, GLJournalLine, Purchase, Sale, Supplier
from services.account_resolution import AccountResolver, AccountRole
from services.bank_reconciliation_service import BankReconciliationService
from services.fx_revaluation import FXRevaluationService
from services.gl_service import GLService
from services.payment_service import PaymentService
from services.sale_service import SaleService
from services.stock_service import StockService
from services.subledger_reconciliation import SubLedgerReconciliation
from utils.helpers import generate_number


@pytest.fixture
def core(db):
    GLService.ensure_core_accounts()
    return True


def _post(ref_type, ref_id, amount=Decimal("100.000")):
    return GLService.post_entry(
        [
            {"account": "1110", "debit": amount},
            {"account": "1130", "credit": amount},
        ],
        description="cov-post",
        reference_type=ref_type,
        reference_id=ref_id,
        currency="ILS",
        exchange_rate=Decimal("1"),
    )


class TestPurgeByReference:
    def test_purges_entry_and_lines(self, db, core):
        e = _post("COV-PURGE", 91001)
        eid = e.id
        n = GLService.purge_by_reference("COV-PURGE", 91001)
        assert n == 1
        assert _db.session.get(GLJournalEntry, eid) is None
        assert GLJournalLine.query.filter_by(entry_id=eid).count() == 0

    def test_missing_reference_returns_zero(self, db, core):
        assert GLService.purge_by_reference("COV-PURGE", 999999) == 0


class TestReverseEntryBatchForm:
    def test_batch_returns_list_and_single(self, db, core):
        _post("COV-REV", 92001, Decimal("10.000"))
        _post("COV-REV", 92001, Decimal("20.000"))
        _db.session.commit()
        out = GLService.reverse_entry(reference_type="COV-REV", reference_id=92001)
        assert isinstance(out, list)
        assert len(out) == 2

        _post("COV-REV", 92002, Decimal("5.000"))
        _db.session.commit()
        single = GLService.reverse_entry(reference_type="COV-REV", reference_id=92002)
        assert isinstance(single, GLJournalEntry)

    def test_batch_no_entries_returns_empty(self, db, core):
        assert GLService.reverse_entry(reference_type="COV-REV", reference_id=999999) == []


def _ils_sale(db, owner_user, test_customer, number, total, paid):
    s = Sale(
        sale_number=number,
        customer_id=test_customer.id,
        seller_id=owner_user.id,
        total_amount=Decimal(str(total)),
        amount_base=Decimal(str(total)),
        paid_amount=Decimal(str(paid)),
        paid_amount_base=Decimal(str(paid)),
        balance_due=Decimal("0"),
        currency="ILS",
        exchange_rate=Decimal("1"),
        payment_status="unpaid",
        status="confirmed",
        is_active=True,
    )
    db.session.add(s)
    db.session.commit()
    return s


class TestUpdatePaymentStatus:
    def test_ils_partial_and_paid(self, db, owner_user, test_customer):
        s = _ils_sale(db, owner_user, test_customer, "S-COV-ILS-1", "100.000", "40.000")
        SaleService.update_payment_status(s)
        assert s.payment_status == "partial"
        assert s.balance_due == Decimal("60.000")
        s.paid_amount = Decimal("100.000")
        SaleService.update_payment_status(s)
        assert s.payment_status == "paid"
        assert s.balance_due == Decimal("0")

    def test_fx_uses_base_amounts(self, db, owner_user, test_customer):
        s = Sale(
            sale_number="S-COV-FX-1",
            customer_id=test_customer.id,
            seller_id=owner_user.id,
            total_amount=Decimal("100.000"),
            amount_base=Decimal("200.000"),
            paid_amount=Decimal("100.000"),
            paid_amount_base=Decimal("0"),
            balance_due=Decimal("200.000"),
            currency="USD",
            exchange_rate=Decimal("2"),
            payment_status="unpaid",
            status="confirmed",
            is_active=True,
        )
        db.session.add(s)
        db.session.commit()
        # txn legs look "paid" (100 vs 100) but base is unpaid -> must stay unpaid
        SaleService.update_payment_status(s)
        assert s.payment_status == "unpaid"
        assert s.balance_due == Decimal("200.000")
        s.paid_amount_base = Decimal("200.000")
        SaleService.update_payment_status(s)
        assert s.payment_status == "paid"
        assert s.balance_due == Decimal("0")


class TestPostRevaluationGate:
    def test_empty_lines_no_post(self, db, core):
        from models import GLJournalEntry
        before = GLJournalEntry.query.count()
        res = {"lines": [], "balanced": True, "dry_run": True}
        out = FXRevaluationService.post_revaluation(res)
        assert out["dry_run"] is False
        assert "journal_entry_id" not in out
        assert GLJournalEntry.query.count() == before

    def test_unbalanced_refuses(self, db, core):
        res = {
            "lines": [{"account_code": "1130", "debit": Decimal("5"), "credit": Decimal("0")}],
            "balanced": False,
            "dry_run": True,
        }
        with pytest.raises(ValueError, match="unbalanced"):
            FXRevaluationService.post_revaluation(res)

    def test_balanced_posts_live(self, db, core):
        res = {
            "lines": [
                {"account_code": "1130", "debit": Decimal("10"), "credit": Decimal("0")},
                {"account_code": "4100", "debit": Decimal("0"), "credit": Decimal("10")},
            ],
            "balanced": True,
            "dry_run": True,
        }
        out = FXRevaluationService.post_revaluation(res)
        assert out["dry_run"] is False
        assert out["journal_entry_id"] is not None
        assert _db.session.get(GLJournalEntry, out["journal_entry_id"]) is not None


def _supplier_with_purchase(db, owner_user, total="400", paid="150"):
    sup = Supplier(name="COV Sup", is_active=True)
    db.session.add(sup)
    db.session.flush()
    p = Purchase(
        purchase_number=generate_number("P", Purchase, "purchase_number"),
        supplier_id=sup.id,
        supplier_name=sup.name,
        total_amount=Decimal(total),
        amount_base=Decimal(total),
        paid_amount=Decimal(paid),
        payment_status="partial",
        status="confirmed",
        currency="AED",
        exchange_rate=Decimal("1"),
        user_id=owner_user.id,
    )
    db.session.add(p)
    db.session.commit()
    sup.total_purchases_aed = Decimal(total)
    sup.total_paid_aed = Decimal(paid)
    db.session.commit()
    return sup


class TestSubledgerPayables:
    def test_payables_balanced_and_all(self, db, owner_user, core):
        sup = _supplier_with_purchase(db, owner_user)
        GLService.post_entry(
            [
                {"account": "1140", "debit": Decimal("400")},
                {"account": "2110", "credit": Decimal("400")},
            ],
            description="cov ap invoice",
            currency="AED",
            exchange_rate=1,
        )
        GLService.post_entry(
            [
                {"account": "2110", "debit": Decimal("150")},
                {"account": "1110", "credit": Decimal("150")},
            ],
            description="cov ap pay",
            currency="AED",
            exchange_rate=1,
        )
        db.session.commit()
        rep = SubLedgerReconciliation.reconcile_payables()
        assert rep["section"] == "AP"
        assert rep["subledger_sum"] == Decimal("250.00")
        assert rep["column_sum"] == Decimal("250.00")
        assert rep["balanced"] is True
        assert all(b["entity_id"] != sup.id for b in rep["breaks"])
        reports = SubLedgerReconciliation.reconcile_all()
        assert [r["section"] for r in reports] == ["AR", "AP"]


class TestAccountResolverGetAccount:
    def test_get_account_returns_live(self, db, core):
        acc = AccountResolver.get_account(AccountRole.AR_CONTROL)
        assert isinstance(acc, GLAccount)
        assert acc.code == "1130"


class TestStockAdjustGLFailure:
    def test_adjust_survives_gl_failure(self, db, test_product, monkeypatch):
        before = Decimal(str(test_product.current_stock or 0))

        def _boom(*a, **k):
            raise RuntimeError("GL down")

        monkeypatch.setattr(GLService, "post_entry", staticmethod(_boom))
        mv = StockService.adjust_stock(test_product.id, Decimal("3"), notes="cov-gl-down")
        assert mv is not None
        db.session.refresh(test_product)
        assert Decimal(str(test_product.current_stock)) == before + Decimal("3")


class TestReceiptOrphanContract:
    def test_gl_failure_keeps_receipt_with_no_entry(self, db, test_customer, monkeypatch):
        before = GLJournalEntry.query.filter_by(reference_type="Receipt").count()

        def _boom(*a, **k):
            raise RuntimeError("GL down")

        monkeypatch.setattr(GLService, "post_entry", staticmethod(_boom))
        receipt = PaymentService.create_receipt(
            {
                "customer_id": test_customer.id,
                "amount": Decimal("50"),
                "currency": "ILS",
                "payment_method": "cash",
            }
        )
        assert receipt is not None
        assert receipt.id is not None
        # orphan contract: saved without a GL entry, no crash
        after = GLJournalEntry.query.filter_by(reference_type="Receipt").count()
        assert after == before


class TestBankSummaryIsolation:
    def test_second_account_isolation(self, db, core):
        day = datetime(2026, 1, 10)
        GLService.create_manual_entry(
            "cov bank1120",
            [
                {"account_code": "1120", "debit": Decimal("1000"), "credit": Decimal("0")},
                {"account_code": "1130", "debit": Decimal("0"), "credit": Decimal("1000")},
            ],
            entry_date=day,
        )
        GLService.create_manual_entry(
            "cov bank1121",
            [
                {"account_code": "1121", "debit": Decimal("100"), "credit": Decimal("0")},
                {"account_code": "1130", "debit": Decimal("0"), "credit": Decimal("100")},
            ],
            entry_date=day,
        )
        db.session.commit()
        acc0 = GLAccount.query.filter_by(code="1120").first()
        acc1 = GLAccount.query.filter_by(code="1121").first()
        from datetime import date

        ps, pe = date(2026, 1, 1), date(2026, 1, 31)
        s0 = BankReconciliationService.get_reconciliation_summary(acc0.id, ps, pe)
        s1 = BankReconciliationService.get_reconciliation_summary(acc1.id, ps, pe)
        assert Decimal(str(s0["closing_balance_per_books"])) == Decimal("1000.000")
        assert Decimal(str(s1["closing_balance_per_books"])) == Decimal("100.000")
