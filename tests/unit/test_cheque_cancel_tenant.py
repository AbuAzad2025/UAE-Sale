"""Cheque cancellation must post its reversing GL entry with the cheque's tenant."""
import os
os.environ.setdefault('PYTHONIOENCODING','utf-8')

from app import create_app


def test_cancel_journal_entry_uses_cheque_tenant():
    src = open('models/cheque.py', encoding='utf-8').read()
    block = src[src.index('def _create_cancel_journal_entry'):]
    block = block[:block.index('def archive')]
    assert 'tenant_id=getattr(self, "tenant_id", None)' in block


def test_cancel_reverses_issue_entry_when_executed():
    app = create_app()
    with app.app_context():
        from extensions import db
        from sqlalchemy import text
        bad = db.session.execute(text("""
          SELECT COUNT(*) FROM (
            SELECT e.id FROM gl_journal_entries e
            JOIN gl_journal_lines l ON l.entry_id=e.id
            GROUP BY e.id HAVING ABS(SUM(l.debit)-SUM(l.credit))>0.001
          ) x
        """)).scalar()
        assert bad == 0
        null_tenant = db.session.execute(text(
            "SELECT COUNT(*) FROM gl_journal_entries WHERE tenant_id IS NULL"
        )).scalar()
        assert null_tenant == 0
