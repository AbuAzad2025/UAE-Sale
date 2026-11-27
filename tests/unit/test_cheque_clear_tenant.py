"""Cheque clearance GL posting must carry the cheque's tenant_id."""

import os


def test_cheque_clear_passes_tenant_id_to_gl():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(root, "models", "cheque.py")
    src = open(path, encoding="utf-8").read()
    # locate the clearing entry post call
    marker = 'reference_type="cheque_clear"'
    assert marker in src
    block = src[src.find(marker) - 200 : src.find(marker) + 200]
    assert "tenant_id=" in block, block


def test_cheque_clear_gl_has_balanced_entry(db, posting_tenant):
    """Posting a cheque clearance produces a balanced GL entry for its tenant."""
    from decimal import Decimal
    from datetime import date

    from models.cheque import Cheque
    from models.gl import GLJournalEntry, GLJournalLine
    from extensions import db as _db

    ch = Cheque(
        cheque_number="TEST-CLR-1",
        cheque_bank_number="TEST-CLR-1",
        cheque_type="outgoing",
        amount=Decimal("100"),
        currency="ILS",
        exchange_rate=Decimal("1"),
        amount_base=Decimal("100"),
        issue_date=date.today(),
        due_date=date.today(),
        bank_name="test",
        status="pending",
        tenant_id=posting_tenant.id,
    )
    _db.session.add(ch)
    _db.session.flush()
    ch.clear_cheque(clearance_date=date.today())
    _db.session.flush()
    entry = GLJournalEntry.query.get(ch.gl_clearing_entry_id)
    assert entry is not None and entry.tenant_id == posting_tenant.id
    lines = GLJournalLine.query.filter_by(entry_id=entry.id).all()
    assert all(ln.tenant_id == posting_tenant.id for ln in lines)
    dr = sum((ln.debit or Decimal("0")) for ln in lines)
    cr = sum((ln.credit or Decimal("0")) for ln in lines)
    assert dr == cr, (dr, cr)
