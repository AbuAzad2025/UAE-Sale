"""Cancelling a posted outgoing cheque preserves a balanced audit trail."""

from datetime import date
from decimal import Decimal

from models import Cheque, GLJournalEntry


def test_cancel_reverses_issue_entry_when_executed(db, posting_tenant):
    cheque = Cheque(
        cheque_number="out-cancel",
        cheque_bank_number="90001",
        cheque_type="outgoing",
        amount=Decimal("125"),
        amount_base=Decimal("125"),
        currency="ILS",
        exchange_rate=1,
        issue_date=date.today(),
        due_date=date.today(),
        bank_name="Test bank",
        status="pending",
        tenant_id=posting_tenant.id,
    )
    db.session.add(cheque)
    db.session.flush()
    cheque.issue_cheque()
    cheque.cancel_cheque("Cancelled by issuer")
    db.session.commit()
    original = db.session.get(GLJournalEntry, cheque.gl_journal_entry_id)
    reversal = db.session.get(GLJournalEntry, original.reversed_entry_id)
    assert original.tenant_id == reversal.tenant_id == posting_tenant.id
    assert (
        original.total_debit
        == original.total_credit
        == reversal.total_debit
        == reversal.total_credit
        == Decimal("125")
    )
    for line in original.lines:
        counterpart = next(
            item for item in reversal.lines if item.account_id == line.account_id
        )
        assert (line.debit, line.credit) == (counterpart.credit, counterpart.debit)
