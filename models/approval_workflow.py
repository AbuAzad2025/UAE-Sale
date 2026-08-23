"""
Approval Workflow Models — نماذج سير عمل الموافقة
Configurable multi-level approval chains for sales/payments.
"""
from datetime import datetime, timezone
from extensions import db


class ApprovalWorkflow(db.Model):
    """
    Defines an approval chain: e.g., "Sales > 10,000 AED requires manager then owner."
    """
    __tablename__ = 'approval_workflows'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    name_ar = db.Column(db.String(100))
    description = db.Column(db.Text)

    # Which entity type this applies to: 'sale', 'payment', 'purchase'
    entity_type = db.Column(db.String(20), nullable=False, index=True)

    # Amount threshold: workflow triggers when amount >= threshold
    min_amount = db.Column(db.Numeric(15, 3), default=0, nullable=False)
    max_amount = db.Column(db.Numeric(15, 3))  # NULL = no upper limit

    # Number of approval levels required (1 = single approver, 2 = manager + owner, etc.)
    levels_required = db.Column(db.Integer, default=1, nullable=False)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    requests = db.relationship('ApprovalRequest', back_populates='workflow', lazy='dynamic')

    def __repr__(self):
        return f'<ApprovalWorkflow {self.name}>'

    def matches(self, entity_type, amount):
        """Check if a given entity+amount triggers this workflow."""
        if self.entity_type != entity_type or not self.is_active:
            return False
        amount = amount or 0
        if amount < self.min_amount:
            return False
        if self.max_amount is not None and amount > self.max_amount:
            return False
        return True

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'name_ar': self.name_ar,
            'entity_type': self.entity_type,
            'min_amount': float(self.min_amount or 0),
            'max_amount': float(self.max_amount) if self.max_amount else None,
            'levels_required': self.levels_required,
            'is_active': self.is_active,
        }


class ApprovalRequest(db.Model):
    """
    An individual approval request linked to a specific entity.
    Tracks multi-level approval progress.
    """
    __tablename__ = 'approval_requests'

    __table_args__ = (
        db.Index('idx_approval_entity', 'entity_type', 'entity_id'),
        db.Index('idx_approval_status', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    request_number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    workflow_id = db.Column(db.Integer, db.ForeignKey('approval_workflows.id'), nullable=False)

    # The entity being approved
    entity_type = db.Column(db.String(20), nullable=False, index=True)  # sale, payment, purchase
    entity_id = db.Column(db.Integer, nullable=False)

    amount = db.Column(db.Numeric(15, 3), nullable=False)
    currency = db.Column(db.String(3), default='AED', nullable=False)

    # Status: pending → approved | rejected | cancelled
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)

    # Current approval level (1-based)
    current_level = db.Column(db.Integer, default=1, nullable=False)

    # Who requested
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Description / reason
    description = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime)

    # Relationships
    workflow = db.relationship('ApprovalWorkflow', back_populates='requests')
    requester = db.relationship('User', foreign_keys=[requested_by])
    approvals = db.relationship('ApprovalLevel', back_populates='request',
                                order_by='ApprovalLevel.level', lazy='joined')

    def __repr__(self):
        return f'<ApprovalRequest {self.request_number} [{self.status}]>'

    @property
    def status_ar(self):
        return {'pending': 'معلق', 'approved': 'موافق عليه',
                'rejected': 'مرفوض', 'cancelled': 'ملغي'}.get(self.status, self.status)

    def is_fully_approved(self):
        """Check if all required levels have been approved."""
        workflow = self.workflow
        required = workflow.levels_required if workflow else 1
        approved_count = sum(1 for a in self.approvals if a.status == 'approved')
        return approved_count >= required

    def to_dict(self):
        return {
            'id': self.id,
            'request_number': self.request_number,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'amount': float(self.amount),
            'status': self.status,
            'current_level': self.current_level,
            'requester': self.requester.username if self.requester else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ApprovalLevel(db.Model):
    """
    A single approval step within a request.
    Tracks who approved/rejected at each level.
    """
    __tablename__ = 'approval_levels'

    id = db.Column(db.Integer, primary_key=True)

    request_id = db.Column(db.Integer, db.ForeignKey('approval_requests.id'), nullable=False, index=True)
    level = db.Column(db.Integer, nullable=False)  # 1, 2, 3, ...

    # Who can approve at this level (role names: 'owner', 'admin', 'manager')
    required_role = db.Column(db.String(20), nullable=False)

    # Who actually approved/rejected
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Status: pending → approved | rejected | skipped
    status = db.Column(db.String(20), default='pending', nullable=False)

    notes = db.Column(db.Text)

    approved_at = db.Column(db.DateTime)

    # Relationships
    request = db.relationship('ApprovalRequest', back_populates='approvals')
    approver = db.relationship('User', foreign_keys=[approved_by])

    def __repr__(self):
        return f'<ApprovalLevel L{self.level} [{self.status}]>'
