"""Bad debt write-offs — models/write_off.py.

A receivable that will never be collected could not be written off: there was
no entity for it, so the balance simply stayed on the books forever as if it
were still collectible. Bad debt is a real, expected operating cost and it has
to reach the general ledger.

`write_offs` records the decision - who wrote it off, why, against which
customer and which invoice - and links the journal entry it created, so the
document and its accounting cannot drift apart.

The amount is stored twice: in the transaction currency (`amount`) and in the
base currency (`amount_base`), so the entry can be reversed at the original
rate and the receivable it settles can be compared with the customer's
balance, which is expressed in base currency only.

The table is created in production by the Alembic migration
`b3_write_offs`; this model mirrors it column for column (same names, same
types, same nullability, same CHECK constraint names), because the test
schema is built from the model metadata while the production schema is built
by Alembic.
"""
from datetime import datetime, timezone

from extensions import db
from models.tenant_scope import TenantScopedMixin


class WriteOff(TenantScopedMixin, db.Model):
    """مديونية مشطوبة — a receivable written off as uncollectible."""

    __tablename__ = 'write_offs'

    STATUS_DRAFT = 'draft'
    STATUS_POSTED = 'posted'
    STATUS_VOID = 'void'

    __table_args__ = (
        db.CheckConstraint('amount > 0', name='ck_writeoff_amount_positive'),
        db.CheckConstraint('amount_base > 0', name='ck_writeoff_amount_base_positive'),
        db.CheckConstraint(
            "status IN ('draft', 'posted', 'void')",
            name='ck_writeoff_status_valid',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey(
        'tenants.id', name='fk_write_offs_tenant_id_tenants'), nullable=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey(
        'customers.id', name='fk_write_offs_customer_id_customers'),
        nullable=False, index=True)
    sale_id = db.Column(db.Integer, db.ForeignKey(
        'sales.id', name='fk_write_offs_sale_id_sales'), nullable=True, index=True)
    amount = db.Column(db.Numeric(15, 3), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='ILS')
    amount_base = db.Column(db.Numeric(15, 3), nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_POSTED,
                       server_default=STATUS_POSTED, index=True)
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer)
    gl_entry_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    posted_at = db.Column(db.DateTime, nullable=True)
    voided_at = db.Column(db.DateTime, nullable=True)

    customer = db.relationship('Customer')
    sale = db.relationship('Sale')

    def __repr__(self):
        return (f'<WriteOff {self.id} customer={self.customer_id} '
                f'{self.amount} {self.currency}>')

    @property
    def is_void(self):
        """True إذا كانت المشطوبة ملغاة."""
        return self.status == self.STATUS_VOID

    @property
    def status_ar(self):
        """حالة المشطوبة بالعربي."""
        return {
            self.STATUS_DRAFT: 'مسودة',
            self.STATUS_POSTED: 'مُرحَّلة',
            self.STATUS_VOID: 'ملغاة',
        }.get(self.status, self.status)

    def to_dict(self):
        """التمثيل النصي للمشطوبة (JSON)."""
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'customer_name': self.customer.name if self.customer else None,
            'sale_id': self.sale_id,
            'amount': float(self.amount or 0),
            'currency': self.currency,
            'amount_base': float(self.amount_base or 0),
            'reason': self.reason,
            'status': self.status,
            'status_ar': self.status_ar,
            'notes': self.notes,
            'created_by': self.created_by,
            'gl_entry_id': self.gl_entry_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'posted_at': self.posted_at.isoformat() if self.posted_at else None,
            'voided_at': self.voided_at.isoformat() if self.voided_at else None,
        }
