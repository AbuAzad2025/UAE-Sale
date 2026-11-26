"""GL postings must always carry a tenant on BOTH the entry and its lines.

Regression: a reversing entry posted outside a request had tenant_id=None on
its lines, so the tenant filter silently dropped it and the balance sheet
disagreed with the income statement by the reversal amount.
"""

from decimal import Decimal

import pytest


def test_post_entry_tags_entry_and_lines_with_tenant(db, posting_tenant):
    from services.gl_service import GLService
    from models.gl import GLJournalEntry, GLJournalLine

    entry = GLService.post_entry(
        [
            {"account": "1110", "debit": Decimal("10"), "description": "dr"},
            {"account": "3100", "credit": Decimal("10"), "description": "cr"},
        ],
        description="tenant scoping test",
        tenant_id=posting_tenant.id,
    )
    assert entry.tenant_id == posting_tenant.id
    lines = GLJournalLine.query.filter_by(entry_id=entry.id).all()
    assert len(lines) == 2
    assert all(ln.tenant_id == posting_tenant.id for ln in lines)
    assert db.session.get(GLJournalEntry, entry.id).tenant_id == posting_tenant.id


def test_post_entry_without_tenant_context_fails_closed(db):
    from models import clear_current_tenant_id
    from services.gl_service import GLService

    clear_current_tenant_id()
    with pytest.raises(ValueError, match="tenant_id"):
        GLService.post_entry(
            [
                {"account": "1110", "debit": Decimal("1")},
                {"account": "3100", "credit": Decimal("1")},
            ],
            description="should not post",
        )


def test_all_stored_gl_lines_have_a_tenant(db):
    from models.gl import GLJournalLine

    assert GLJournalLine.query.filter(GLJournalLine.tenant_id.is_(None)).count() == 0
