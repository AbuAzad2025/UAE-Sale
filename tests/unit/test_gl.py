"""
General Ledger Tests — Journal entries, balancing, reversal.

Tests the double-entry accounting system.
"""

import pytest
from decimal import Decimal


class TestJournalEntry:
    """Test GL journal entry creation and balancing."""

    def test_create_journal_entry(self, db, owner_user):
        """Can create a balanced journal entry."""
        from models import GLAccount, GLJournalEntry, GLJournalLine

        # Create accounts
        cash = GLAccount(code='1000', name='Cash', name_ar='صندوق', type='asset')
        revenue = GLAccount(code='4000', name='Revenue', name_ar='إيرادات', type='revenue')
        db.session.add_all([cash, revenue])
        db.session.flush()

        # Create balanced entry
        entry = GLJournalEntry(
            entry_number='JE-TEST-001',
            description='Test entry',
            reference_type='manual',
            entry_type='manual',
            total_debit=Decimal('100.000'),
            total_credit=Decimal('100.000'),
            created_by=owner_user.id,
        )
        db.session.add(entry)
        db.session.flush()

        # Add lines
        debit_line = GLJournalLine(
            entry_id=entry.id,
            account_id=cash.id,
            debit=Decimal('100.000'),
            credit=Decimal('0'),
            amount_base=Decimal('100.000'),
        )
        credit_line = GLJournalLine(
            entry_id=entry.id,
            account_id=revenue.id,
            debit=Decimal('0'),
            credit=Decimal('100.000'),
            amount_base=Decimal('-100.000'),
        )
        db.session.add_all([debit_line, credit_line])
        db.session.commit()

        assert entry.is_balanced()

    def test_unbalanced_entry_detected(self, db, owner_user):
        """Unbalanced entry is detected."""
        from models import GLJournalEntry

        entry = GLJournalEntry(
            entry_number='JE-TEST-002',
            description='Unbalanced test entry',
            reference_type='manual',
            entry_type='manual',
            total_debit=Decimal('100.000'),
            total_credit=Decimal('50.000'),  # Unbalanced!
            created_by=owner_user.id,
        )
        db.session.add(entry)
        db.session.commit()

        assert not entry.is_balanced()

    def test_reverse_entry(self, db, owner_user):
        """Journal entry reversal creates opposite entry."""
        from models import GLAccount, GLJournalEntry, GLJournalLine

        cash = GLAccount(code='1000', name='Cash', name_ar='صندوق', type='asset')
        revenue = GLAccount(code='4000', name='Revenue', name_ar='إيرادات', type='revenue')
        db.session.add_all([cash, revenue])
        db.session.flush()

        # Create original entry
        entry = GLJournalEntry(
            entry_number='JE-TEST-003',
            description='Original entry',
            reference_type='manual',
            entry_type='manual',
            total_debit=Decimal('100.000'),
            total_credit=Decimal('100.000'),
            created_by=owner_user.id,
        )
        db.session.add(entry)
        db.session.flush()

        debit_line = GLJournalLine(
            entry_id=entry.id,
            account_id=cash.id,
            debit=Decimal('100.000'),
            credit=Decimal('0'),
            amount_base=Decimal('100.000'),
        )
        credit_line = GLJournalLine(
            entry_id=entry.id,
            account_id=revenue.id,
            debit=Decimal('0'),
            credit=Decimal('100.000'),
            amount_base=Decimal('-100.000'),
        )
        db.session.add_all([debit_line, credit_line])
        db.session.commit()

        # Reverse it
        reversed_entry = entry.reverse_entry(description='Test reversal')
        db.session.commit()

        # Verify reversal
        assert entry.is_reversed
        assert reversed_entry.total_debit == entry.total_credit
        assert reversed_entry.total_credit == entry.total_debit
        assert reversed_entry.entry_type == 'reversing'

    def test_cannot_reverse_twice(self, db, owner_user):
        """Cannot reverse an already reversed entry."""
        from models import GLJournalEntry

        entry = GLJournalEntry(
            entry_number='JE-TEST-004',
            description='Double reverse test',
            reference_type='manual',
            entry_type='manual',
            total_debit=Decimal('100.000'),
            total_credit=Decimal('100.000'),
            created_by=owner_user.id,
        )
        db.session.add(entry)
        db.session.commit()

        entry.reverse_entry()
        db.session.commit()

        with pytest.raises(ValueError):
            entry.reverse_entry()
