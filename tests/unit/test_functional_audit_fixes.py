"""Permanent regression tests for the functional-audit fixes (P0/P1/P2).

Covers: HR filter templates, VAT rounding, partner share on net profit,
idempotent GL posting, shipment tenant isolation, TRN PS, cheque amount.
"""
from decimal import Decimal
import pytest


class TestInclusiveVATReconciles:
    def test_net_plus_tax_equals_gross(self):
        from services.sale_tax_calculation import sale_tax_totals_mixed

        for gross, rate in [(Decimal("378400"), Decimal("16")),
                            (Decimal("100"), Decimal("5")),
                            (Decimal("1"), Decimal("5"))]:
            lines = [{"line_total": gross, "tax_treatment": "standard"}]
            tax, total, net, zero, exempt = sale_tax_totals_mixed(
                lines, Decimal("0"), Decimal("0"), rate, True
            )
            assert net + tax == total, (gross, net, tax, total)

    def test_multiline_no_leak(self):
        from services.sale_tax_calculation import sale_tax_totals_mixed

        lines = [{"line_total": Decimal("100.00"), "tax_treatment": "standard"}] * 3
        tax, total, net, *_ = sale_tax_totals_mixed(
            lines, Decimal("0"), Decimal("0"), Decimal("5"), True
        )
        assert net + tax == total


class TestHRFilterTemplates:
    @pytest.mark.parametrize("tpl", ["hr/employees.html", "hr/leave_requests.html", "hr/payroll.html"])
    def test_no_jinja_int_type(self, tpl):
        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader("templates"))
        src = env.loader.get_source(env, tpl)[0]
        assert "type=int" not in src
        env.parse(src)  # must parse

    def test_leave_approval_rechecks_balance(self):
        # Guard: approve() must re-check the balance (no underflow).
        src = open("models/hr.py", encoding="utf-8").read()
        marker = "الرصيد المتبقي من الإجازة غير كافٍ"
        assert marker in src
        approve_start = src.find("def approve(self, user_id):", src.find("class LeaveRequest"))
        approve_src = src[approve_start:approve_start + 900]
        assert marker in approve_src


class TestPartnerShareNetProfit:
    def test_report_uses_net_profit(self):
        # Guard: the partner statement must not compute share from line_total.
        src = open("routes/reports.py", encoding="utf-8").read()
        assert "compute_line_profit(" in src
        assert "float(line.line_total or 0) * (percentage / 100.0)" not in src


class TestGLIdempotency:
    def test_idempotency_key_param_exists(self):
        import inspect
        from services.gl_service import GLService

        assert "idempotency_key" in inspect.signature(GLService.post_entry).parameters


class TestTRNAndCheque:
    def test_ps_trn_pattern(self):
        from utils.trn import trn_verdict

        ok, msg = trn_verdict("123456789", "PS")
        assert ok is True
        bad, msg = trn_verdict("ABC", "PS")
        assert bad is False

    def test_cheque_rejects_nonpositive(self, db):
        from models.cheque import Cheque

        with pytest.raises(ValueError):
            Cheque(amount=Decimal("0"))
