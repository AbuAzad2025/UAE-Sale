"""
Journal Entry Audit Model — نموذج تدقيق قيود اليومية
Tracks every CREATE/UPDATE/DELETE action performed on GL journal entries,
including old/new values, responsible user, and IP metadata.

Note: This table was created in the very first migration (initial schema)
and its FK cascade rules were hardened in migration 9_audit_cascade.py, but
the corresponding SQLAlchemy model was never authored. This file restores
parity with the live production schema.
"""
from datetime import datetime, timezone
from extensions import db


class JournalEntryAudit(db.Model):
    """Immutable audit trail for mutations on GL journal entries."""

    __tablename__ = 'journal_entry_audits'

    id = db.Column(db.Integer, primary_key=True)

    journal_entry_id = db.Column(
        db.Integer,
        # Intentionally NO ForeignKey: the audit trail must survive its
        # entry's deletion (migration 9 states this intent; the delete
        # unit test pins it). Enforcing the FK either blocks draft deletes
        # (restrictive) or silently destroys the history it exists to keep
        # (CASCADE). The id is a historical reference, not a live link.
        nullable=False,
        index=True,
    )

    action = db.Column(db.String(50), nullable=False)

    old_values = db.Column(db.Text)
    new_values = db.Column(db.Text)
    reason = db.Column(db.Text)

    performed_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=False,
    )

    performed_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)

    journal_entry = db.relationship(
        'GLJournalEntry',
        # No database FK backs this link (see journal_entry_id above), so
        # the join and the delete behavior must be spelled out explicitly:
        # passive_deletes stops session.delete(entry) from nulling/touching
        # dependent audit rows (their NOT NULL historical reference stays
        # intact); the database enforces nothing.
        primaryjoin='JournalEntryAudit.journal_entry_id == GLJournalEntry.id',
        foreign_keys=[journal_entry_id],
        backref=db.backref('audits', passive_deletes=True),
        lazy='joined',
    )
    performer = db.relationship('User', foreign_keys=[performed_by])

    def __repr__(self):
        return f'<JournalEntryAudit #{self.id} on entry {self.journal_entry_id} by user {self.performed_by}>'
