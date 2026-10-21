"""
Journal Entry Audit Model — نموذج تدقيق قيود اليومية
Tracks every CREATE/UPDATE/DELETE action performed on GL journal entries,
including old/new values, responsible user, and IP metadata.

Note: This table was created in the very first migration (initial schema)
and its FK cascade rules were hardened in migration 9_audit_cascade.py, but
the corresponding SQLAlchemy model was never authored. This file restores
parity with the live production schema.

P0 (ledger integrity) additions
--------------------------------
* ``JournalEntryAudit.record()`` — a single, reusable writer used by every
  posting path (auto-posted entries included) so an audit row can never be
  forgotten.
* ``JournalEntryAudit.resolve_actor_id()`` — resolves WHO performed the
  action. ``performed_by`` is ``NOT NULL`` in the live schema, so a missing
  actor must never turn into a NULL insert (IntegrityError) nor be faked.
* ``JournalEntryAudit.entry_payload()`` — the standard payload shape: the
  entry header PLUS the account codes and amounts of every line, which is
  what an auditor actually needs to reconstruct the posting.
"""
from datetime import datetime, timezone
from decimal import Decimal

from extensions import db


def _fmt_money(value) -> str:
    """Format a money value as a plain string (never a float repr)."""
    if value is None:
        return '0'
    if isinstance(value, Decimal):
        return f'{value:.3f}'
    try:
        return f'{Decimal(str(value)):.3f}'
    except Exception:
        return str(value)


class JournalEntryAudit(db.Model):
    """Immutable audit trail for mutations on GL journal entries."""

    __tablename__ = 'journal_entry_audits'

    # ---- actions ----------------------------------------------------------
    ACTION_CREATE = 'create'
    ACTION_UPDATE = 'update'
    ACTION_DELETE = 'delete'
    ACTION_APPROVE = 'approve'
    ACTION_REVERSE = 'reverse'
    ACTION_POST = 'post'

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

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_actor_id(explicit=None, fallback_entry=None):
        """Resolve the id of the user responsible for an action.

        ``performed_by`` is ``NOT NULL`` in the live schema, so an audit row
        without an actor is impossible. The resolution order is:

        1. the explicit id passed by the caller (the normal case),
        2. the logged-in user (``flask_login``),
        3. the creator of the audited entry (a reversal is attributed to
           the entry's author when the reversing user is unknown),
        4. a platform owner (last-resort system attribution).

        Returns ``None`` when no actor can be found; the caller then skips
        the audit row instead of writing a broken one.
        """
        if explicit:
            try:
                return int(explicit)
            except (TypeError, ValueError):
                pass

        try:
            from flask_login import current_user

            if getattr(current_user, 'is_authenticated', False):
                uid = getattr(current_user, 'id', None)
                if uid:
                    return int(uid)
        except Exception:
            pass

        creator = getattr(fallback_entry, 'created_by', None)
        if creator:
            try:
                return int(creator)
            except (TypeError, ValueError):
                pass

        # Last resort: a platform owner. The query is column-only on purpose:
        # a column-only query is NOT rewritten by the tenant filter, so the
        # owner can be found even when the caller works inside a tenant
        # scope. Only an id is read — no business data crosses the boundary.
        try:
            from models.user import User

            owner_id = (
                db.session.query(User.id)
                .filter(User.is_owner.is_(True))
                .order_by(User.id)
                .limit(1)
                .scalar()
            )
            if owner_id:
                return int(owner_id)
        except Exception:
            pass

        return None

    @classmethod
    def record(cls, journal_entry_id, action, old_values=None, new_values=None,
               reason=None, performed_by=None, fallback_entry=None):
        """Write one audit row and return it (``None`` when no actor exists).

        The row is added to the session but NOT committed: it shares the
        transaction of the operation it documents, so an operation that
        rolls back does not leave a phantom audit trail behind.
        """
        actor = cls.resolve_actor_id(performed_by, fallback_entry)
        if actor is None:
            # Never fake an actor and never abort a posting for a missing
            # audit actor: log loudly and continue without the row.
            import logging

            logging.getLogger(__name__).warning(
                'JournalEntryAudit skipped: no actor resolvable for entry %s (%s)',
                journal_entry_id, action,
            )
            return None

        audit = cls(
            journal_entry_id=journal_entry_id,
            action=action,
            old_values=str(old_values) if old_values else None,
            new_values=str(new_values) if new_values else None,
            reason=reason,
            performed_by=actor,
            performed_at=datetime.now(timezone.utc),
        )
        db.session.add(audit)
        return audit

    @staticmethod
    def entry_payload(entry, lines=None):
        """Build the standard audit payload for a journal entry.

        Includes the header AND the account codes with their debit/credit
        amounts, so the audit row documents WHAT was posted, not merely that
        something was posted.
        """
        payload = {
            'id': getattr(entry, 'id', None),
            'entry_number': getattr(entry, 'entry_number', None),
            'entry_date': (
                entry.entry_date.isoformat()
                if getattr(entry, 'entry_date', None) is not None else None
            ),
            'description': getattr(entry, 'description', None),
            'entry_type': getattr(entry, 'entry_type', None),
            'reference_type': getattr(entry, 'reference_type', None),
            'reference_id': getattr(entry, 'reference_id', None),
            'currency': getattr(entry, 'currency', None),
            'exchange_rate': _fmt_money(getattr(entry, 'exchange_rate', None)),
            'total_debit': _fmt_money(getattr(entry, 'total_debit', None)),
            'total_credit': _fmt_money(getattr(entry, 'total_credit', None)),
            'is_posted': bool(getattr(entry, 'is_posted', False)),
            'is_reversed': bool(getattr(entry, 'is_reversed', False)),
        }

        line_payloads = []
        if lines is None:
            try:
                lines = list(entry.lines)
            except Exception:
                lines = []
        for line in lines:
            if isinstance(line, dict):
                code = line.get('account_code') or line.get('code')
                debit = line.get('debit')
                credit = line.get('credit')
                amount_base = line.get('amount_base')
                description = line.get('description')
            else:
                code = None
                account = getattr(line, 'account', None)
                if account is not None:
                    code = getattr(account, 'code', None)
                debit = getattr(line, 'debit', None)
                credit = getattr(line, 'credit', None)
                amount_base = getattr(line, 'amount_base', None)
                description = getattr(line, 'description', None)
            line_payloads.append({
                'account_code': code,
                'debit': _fmt_money(debit),
                'credit': _fmt_money(credit),
                'amount_base': _fmt_money(amount_base),
                'description': description,
            })
        payload['lines'] = line_payloads
        return payload
