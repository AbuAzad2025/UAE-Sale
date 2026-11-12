"""Expense VAT: per-document tax treatment, reverse charge, non-recoverable."""

from decimal import Decimal

from services.expense_gl import (
    build_expense_gl_lines,
    compute_expense_tax,
    expense_payment_amount,
)


def _stub(**kwargs):
    class _S:
        pass

    s = _S()
    defaults = dict(
        tenant_id=None,
        expense_number="EXP-TEST",
        category=None,
        payment_method="cash",
        description="اختبار",
        amount=Decimal("100"),
        tax_rate=Decimal("5"),
        tax_inclusive=False,
        tax_treatment="standard",
        vat_recoverable=True,
        reverse_charge=False,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


class TestExpenseTaxComputation:
    def test_exclusive_tax_added(self):
        net, tax, total = compute_expense_tax("100", "5", False, "standard")
        assert (net, tax, total) == (Decimal("100"), Decimal("5.00"), Decimal("105.00"))

    def test_inclusive_tax_extracted(self):
        net, tax, total = compute_expense_tax("105", "5", True, "standard")
        assert net == Decimal("100.00")
        assert tax == Decimal("5.00")
        assert total == Decimal("105")

    def test_zero_treatment_no_tax(self):
        net, tax, total = compute_expense_tax("100", "5", False, "zero")
        assert (net, tax, total) == (Decimal("100"), Decimal("0"), Decimal("100.00"))

    def test_summary_payment_amount_modes(self):
        s = _stub(amount=Decimal("100"), reverse_charge=False)
        assert expense_payment_amount(s) == Decimal("105.00")
        s = _stub(amount=Decimal("100"), reverse_charge=True)
        assert expense_payment_amount(s) == Decimal("100.00")


class TestExpenseGL:
    def _resolve(self):
        from services.account_resolution import AccountResolver, AccountRole

        return (
            AccountResolver.resolve(AccountRole.CASH),
            AccountResolver.resolve(AccountRole.BANK),
            AccountResolver.resolve(AccountRole.AP_CONTROL),
            AccountResolver.resolve(AccountRole.VAT_INPUT),
            AccountResolver.resolve(AccountRole.VAT_OUTPUT),
        )

    def test_exclusive_recoverable_posts_input_vat_and_gross_cash(self):
        cash, bank, ap, vat_in, vat_out = self._resolve()
        p = _stub(amount=Decimal("100"))
        lines = build_expense_gl_lines(p)
        by_account = {}
        for l in lines:
            by_account[l["account"]] = l
        assert by_account[cash]["credit"] == Decimal("105.00")
        assert by_account[vat_in]["debit"] == Decimal("5.00")
        debits = sum(l.get("debit", Decimal("0")) for l in lines)
        credits = sum(l.get("credit", Decimal("0")) for l in lines)
        assert debits == credits

    def test_non_recoverable_moves_tax_into_cost(self):
        cash, bank, ap, vat_in, vat_out = self._resolve()
        p = _stub(amount=Decimal("100"), vat_recoverable=False)
        lines = build_expense_gl_lines(p)
        accounts = [l["account"] for l in lines]
        assert vat_in not in accounts and vat_out not in accounts
        debits = sum(l.get("debit", Decimal("0")) for l in lines)
        credits = sum(l.get("credit", Decimal("0")) for l in lines)
        assert debits == credits == Decimal("105.00")

    def test_reverse_charge_balanced_vat_pair_and_net_cash(self):
        cash, bank, ap, vat_in, vat_out = self._resolve()
        p = _stub(amount=Decimal("100"), reverse_charge=True)
        lines = build_expense_gl_lines(p)
        by_account = {l["account"]: l for l in lines}
        assert by_account[cash]["credit"] == Decimal("100.00")
        assert by_account[vat_in]["debit"] == Decimal("5.00")
        assert by_account[vat_out]["credit"] == Decimal("5.00")
        debits = sum(l.get("debit", Decimal("0")) for l in lines)
        credits = sum(l.get("credit", Decimal("0")) for l in lines)
        assert debits == credits

    def test_inclusive_extracts_tax_before_posting(self):
        cash, bank, ap, vat_in, vat_out = self._resolve()
        p = _stub(amount=Decimal("105"), tax_inclusive=True)
        lines = build_expense_gl_lines(p)
        debits = sum(l.get("debit", Decimal("0")) for l in lines)
        credits = sum(l.get("credit", Decimal("0")) for l in lines)
        assert debits == credits == Decimal("105.00")
        vat_in_debit = next(l for l in lines if l["account"] == vat_in)["debit"]
        assert vat_in_debit == Decimal("5.00")
