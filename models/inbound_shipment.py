"""
Inbound Shipment Model — شحنة البضائع الواردة

Business meaning (verified):
- شحنة من مورد/ناقل برقم تتبع، مرتبطة أو غير مرتبطة بطلب شراء
- تُستقبل (arrived) ثم تُفحص (inspected) ثم تُدخل فعلياً لمخازن/بن محددة (put_away)
- لا تُعتبر مستلمة حتى put_away — عندها تُحدث المخزون عبر StockMovement
"""

from datetime import datetime, timezone
from decimal import Decimal

from extensions import db
from models.tenant_scope import TenantScopedMixin


class InboundShipment(TenantScopedMixin, db.Model):
    __tablename__ = 'inbound_shipments'

    __table_args__ = (
        db.Index('ix_inbound_shipments_tenant_status', 'tenant_id', 'status'),
        db.Index('ix_inbound_shipments_warehouse', 'warehouse_id'),
        db.Index('ix_inbound_shipments_supplier', 'supplier_id'),
        db.Index('ix_inbound_shipments_po', 'purchase_order_id'),
        db.Index('ix_inbound_shipments_tracking', 'tracking_number'),
        db.Index('ix_inbound_shipments_status', 'status'),
        db.CheckConstraint(
            "status IN ('in_transit','arrived','inspected','put_away','closed','cancelled')",
            name='ck_inbound_status_valid'),
        db.CheckConstraint('total_quantity >= 0', name='ck_inbound_qty_non_negative'),
        db.CheckConstraint('total_value >= 0', name='ck_inbound_value_non_negative'),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='SET NULL'), nullable=True)

    shipment_number = db.Column(db.String(50), unique=True, nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id', ondelete='SET NULL'), nullable=True)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id', ondelete='SET NULL'), nullable=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id', ondelete='RESTRICT'), nullable=False)

    carrier = db.Column(db.String(100))
    tracking_number = db.Column(db.String(100))
    expected_at = db.Column(db.Date, nullable=True)
    arrived_at = db.Column(db.DateTime(timezone=True), nullable=True)
    inspected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    put_away_at = db.Column(db.DateTime(timezone=True), nullable=True)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    status = db.Column(db.String(20), nullable=False, default='in_transit')

    total_quantity = db.Column(db.Numeric(15, 3), nullable=False, default=Decimal('0.000'))
    total_value = db.Column(db.Numeric(15, 3), nullable=False, default=Decimal('0.000'))
    notes = db.Column(db.Text)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    tenant = db.relationship('Tenant', foreign_keys=[tenant_id])
    supplier = db.relationship('Supplier', foreign_keys=[supplier_id])
    purchase_order = db.relationship('PurchaseOrder', foreign_keys=[purchase_order_id])
    warehouse = db.relationship('Warehouse', foreign_keys=[warehouse_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_id])
    lines = db.relationship('InboundShipmentLine', back_populates='shipment',
                            cascade='all, delete-orphan', lazy='joined')

    @property
    def status_ar(self):
        return {
            'in_transit': 'في الطريق',
            'arrived': 'وصلت',
            'inspected': 'تم الفحص',
            'put_away': 'تم الإدخال',
            'closed': 'مغلقة',
            'cancelled': 'ملغاة',
        }.get(self.status, self.status)

    def calculate_totals(self):
        qty = sum((Decimal(str(l.quantity_expected or 0)) for l in self.lines), Decimal('0'))
        val = sum((Decimal(str(l.quantity_expected or 0)) * Decimal(str(l.unit_cost or 0)) for l in self.lines), Decimal('0'))
        self.total_quantity = qty
        self.total_value = val

    def __repr__(self):
        return f'<InboundShipment {self.shipment_number} {self.status}>'


class InboundShipmentLine(db.Model):
    __tablename__ = 'inbound_shipment_lines'

    __table_args__ = (
        db.Index('ix_inbound_lines_shipment', 'inbound_shipment_id'),
        db.Index('ix_inbound_lines_product', 'product_id'),
        db.Index('ix_inbound_lines_bin', 'warehouse_bin_id'),
        db.CheckConstraint('quantity_expected > 0', name='ck_inbound_line_expected_positive'),
        db.CheckConstraint('quantity_received >= 0', name='ck_inbound_line_received_non_negative'),
        db.CheckConstraint('quantity_accepted >= 0', name='ck_inbound_line_accepted_non_negative'),
        db.CheckConstraint('unit_cost >= 0', name='ck_inbound_line_cost_non_negative'),
    )

    id = db.Column(db.Integer, primary_key=True)
    inbound_shipment_id = db.Column(db.Integer, db.ForeignKey('inbound_shipments.id', ondelete='CASCADE'),
                                    nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id', ondelete='RESTRICT'), nullable=False)
    quantity_expected = db.Column(db.Numeric(15, 3), nullable=False)
    quantity_received = db.Column(db.Numeric(15, 3), nullable=False, default=Decimal('0.000'))
    quantity_accepted = db.Column(db.Numeric(15, 3), nullable=False, default=Decimal('0.000'))
    unit_cost = db.Column(db.Numeric(15, 3), nullable=False, default=Decimal('0.000'))
    line_total = db.Column(db.Numeric(15, 3), nullable=False, default=Decimal('0.000'))
    warehouse_bin_id = db.Column(db.Integer, db.ForeignKey('warehouse_bins.id', ondelete='SET NULL'), nullable=True)
    lot_id = db.Column(db.Integer, db.ForeignKey('product_lots.id', ondelete='SET NULL'), nullable=True)
    notes = db.Column(db.String(255))

    shipment = db.relationship('InboundShipment', back_populates='lines')
    product = db.relationship('Product')
    warehouse_bin = db.relationship('WarehouseBin', foreign_keys=[warehouse_bin_id])
    lot = db.relationship('ProductLot', foreign_keys=[lot_id])

    def calculate_line_total(self):
        self.line_total = Decimal(str(self.quantity_expected)) * Decimal(str(self.unit_cost))

    def __repr__(self):
        return f'<InboundShipmentLine {self.product_id} exp {self.quantity_expected}>'
