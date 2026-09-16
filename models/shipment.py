"""
Shipment Model — الإرسالية الميدانية

Business meaning (verified):
- إخراج بضاعة من مستودع تابع لشركة/مستأجر إلى موقع بيع ميداني
- كل إرسالية هي دورة: إنشاء → إرسال → وصول → بيع ميداني → إغلاق/تحصيل → فاتورة
- ليست نقلاً مخزنياً داخلياً (stock_transfers)، بل إرسالية بيع حتى استيفاء المبلغ وسند القبض والفاتورة
"""

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import validates

from extensions import db
from models.tenant_scope import TenantScopedMixin


class Shipment(TenantScopedMixin, db.Model):
    """Field sales shipment — van / site expedition."""

    __tablename__ = 'shipments'

    __table_args__ = (
        db.Index('ix_shipments_tenant_status', 'tenant_id', 'status'),
        db.Index('ix_shipments_warehouse', 'from_warehouse_id'),
        db.Index('ix_shipments_destination', 'destination_warehouse_id'),
        db.CheckConstraint("status IN ('draft','in_transit','arrived','selling','closed','cancelled')",
                           name='ck_shipments_status_valid'),
        db.CheckConstraint('total_value >= 0', name='ck_shipments_total_non_negative'),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)

    shipment_number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # Source — from any warehouse of any tenant (company/branch)
    from_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id', ondelete='RESTRICT'),
                                  nullable=False, index=True)

    # Destination — either a warehouse (formal site) or free-text site name
    destination_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id', ondelete='SET NULL'),
                                         nullable=True, index=True)
    destination_name = db.Column(db.String(200), nullable=False)  # موقع البيع الميداني
    destination_type = db.Column(db.String(20), nullable=False, default='site')  # site / warehouse / customer

    status = db.Column(db.String(20), nullable=False, default='draft', index=True)
    # draft → in_transit → arrived → selling → closed
    # draft/cancelled allowed to be cancelled at any step before closed

    total_value = db.Column(db.Numeric(15, 3), nullable=False, default=Decimal('0.000'))
    total_quantity = db.Column(db.Numeric(15, 3), nullable=False, default=Decimal('0.000'))
    notes = db.Column(db.Text)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    shipped_at = db.Column(db.DateTime(timezone=True), nullable=True)
    arrived_at = db.Column(db.DateTime(timezone=True), nullable=True)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    tenant = db.relationship('Tenant', foreign_keys=[tenant_id])
    from_warehouse = db.relationship('Warehouse', foreign_keys=[from_warehouse_id])
    destination_warehouse = db.relationship('Warehouse', foreign_keys=[destination_warehouse_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_id])
    lines = db.relationship('ShipmentLine', back_populates='shipment',
                            cascade='all, delete-orphan', lazy='joined')
    # Sales created from this shipment (optional link — Sale.shipment_id)
    # Defined via backref on Sale (see sale.py)

    @validates('destination_name')
    def _validate_destination(self, key, value):
        if not value or not str(value).strip():
            raise ValueError('destination_name (موقع الإرسالية) مطلوب')
        return str(value).strip()

    @validates('from_warehouse_id', 'destination_warehouse_id')
    def _validate_warehouses(self, key, value):
        if value is None:
            return value
        return value

    @property
    def status_ar(self):
        return {
            'draft': 'مسودة',
            'in_transit': 'في الطريق',
            'arrived': 'وصلت',
            'selling': 'قيد البيع',
            'closed': 'مغلقة',
            'cancelled': 'ملغاة',
        }.get(self.status, self.status)

    @property
    def is_editable(self):
        return self.status in ('draft',)

    @property
    def is_closable(self):
        return self.status in ('arrived', 'selling')

    def calculate_totals(self):
        """Recalculate quantity/value from lines."""
        qty = sum((Decimal(str(l.quantity)) for l in self.lines), Decimal('0'))
        val = sum((Decimal(str(l.line_total)) for l in self.lines), Decimal('0'))
        self.total_quantity = qty
        self.total_value = val

    def to_dict(self):
        return {
            'id': self.id,
            'shipment_number': self.shipment_number,
            'from_warehouse_id': self.from_warehouse_id,
            'destination_name': self.destination_name,
            'status': self.status,
            'status_ar': self.status_ar,
            'total_quantity': float(self.total_quantity or 0),
            'total_value': float(self.total_value or 0),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<Shipment {self.shipment_number} {self.status}>'


class ShipmentLine(db.Model):
    __tablename__ = 'shipment_lines'

    __table_args__ = (
        db.Index('ix_shipment_lines_shipment', 'shipment_id'),
        db.Index('ix_shipment_lines_product', 'product_id'),
        db.CheckConstraint('quantity > 0', name='ck_shipmentline_qty_positive'),
        db.CheckConstraint('unit_cost >= 0', name='ck_shipmentline_cost_non_negative'),
        db.CheckConstraint('line_total >= 0', name='ck_shipmentline_total_non_negative'),
    )

    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey('shipments.id', ondelete='CASCADE'),
                            nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id', ondelete='RESTRICT'),
                           nullable=False, index=True)
    quantity = db.Column(db.Numeric(15, 3), nullable=False)
    unit_cost = db.Column(db.Numeric(15, 3), nullable=False, default=Decimal('0.000'))
    unit_price = db.Column(db.Numeric(15, 3), nullable=False, default=Decimal('0.000'))
    line_total = db.Column(db.Numeric(15, 3), nullable=False, default=Decimal('0.000'))
    notes = db.Column(db.String(255))

    shipment = db.relationship('Shipment', back_populates='lines')
    product = db.relationship('Product')

    def calculate_line_total(self):
        self.line_total = Decimal(str(self.quantity)) * Decimal(str(self.unit_cost))

    def __repr__(self):
        return f'<ShipmentLine {self.product_id} x {self.quantity}>'
