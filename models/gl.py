from datetime import datetime, timezone
from extensions import db


class GLAccount(db.Model):
    __tablename__ = 'gl_accounts'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)  # English name
    name_ar = db.Column(db.String(200))  # Arabic name
    parent_id = db.Column(db.Integer, db.ForeignKey('gl_accounts.id'))
    type = db.Column(db.String(20), nullable=False, index=True)  # asset, liability, equity, revenue, expense
    currency = db.Column(db.String(3), default='AED', nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    parent = db.relationship('GLAccount', remote_side=[id], backref='children')

    def __repr__(self):
        return f'<GLAccount {self.code} {self.name}>'


class GLJournalEntry(db.Model):
    __tablename__ = 'gl_journal_entries'

    id = db.Column(db.Integer, primary_key=True)
    entry_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    entry_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    description = db.Column(db.String(255))
    reference_type = db.Column(db.String(50))
    reference_id = db.Column(db.Integer)
    currency = db.Column(db.String(3), default='AED', nullable=False)
    exchange_rate = db.Column(db.Numeric(15, 6), default=1)
    total_debit = db.Column(db.Numeric(18, 3), default=0)
    total_credit = db.Column(db.Numeric(18, 3), default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    lines = db.relationship('GLJournalLine', back_populates='entry', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<GLEntry {self.entry_number}>'
    
    def is_balanced(self):
        """Check if entry is balanced"""
        return self.total_debit == self.total_credit


class GLJournalLine(db.Model):
    __tablename__ = 'gl_journal_lines'

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('gl_journal_entries.id'), nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey('gl_accounts.id'), nullable=False, index=True)
    description = db.Column(db.String(255))
    debit = db.Column(db.Numeric(18, 3), default=0)
    credit = db.Column(db.Numeric(18, 3), default=0)
    amount_aed = db.Column(db.Numeric(18, 3), default=0)

    entry = db.relationship('GLJournalEntry', back_populates='lines')
    account = db.relationship('GLAccount')

    def __repr__(self):
        return f'<GLLine acc={self.account_id} d={self.debit} c={self.credit}>'


