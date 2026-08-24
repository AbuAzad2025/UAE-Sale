"""
Extended ERP Module Models
- Quotations
- Purchase Orders (with Goods Receipt)
- Fiscal Periods
- Stock Transfers
- Stock Takes
- Dunning Letters
- Recurring Expenses
- Lot/Serial Number Tracking
- Bin/Location Tracking
- E-Invoicing (FATOORA)
"""

from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from extensions import db


# ==================== QUOTATIONS ====================

class Quotation(db.Model):
    """Sales quotation / proposal"""
    __tablename__ = 'quotations'

    id = db.Column(db.Integer, primary_key=True)
    quotation_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'))

    quotation_date = db.Column(db.Date, nullable=False, index=True)
    valid_until = db.Column(db.Date, nullable=False)
    expiry_date = db.Column(db.Date)

    subtotal = db.Column(db.Numeric(15, 3), default=0)
    discount_amount = db.Column(db.Numeric(15, 3), default=0)
    shipping_cost = db.Column(db.Numeric(15, 3), default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(15, 3), default=0)
    total_amount = db.Column(db.Numeric(15, 3), default=0)

    currency = db.Column(db.String(3), default='AED')
    exchange_rate = db.Column(db.Numeric(15, 6), default=1)
    amount_aed = db.Column(db.Numeric(15, 3), default=0)

    status = db.Column(db.String(20), default='draft', index=True)
    # draft, sent, accepted, rejected, expired, converted

    converted_sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'))
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    customer = db.relationship('Customer')
    seller = db.relationship('User', foreign_keys=[seller_id])
    lines = db.relationship('QuotationLine', back_populates='quotation', cascade='all, delete-orphan')
    converted_sale = db.relationship('Sale', foreign_keys=[converted_sale_id])

    def calculate_totals(self):
        self.subtotal = sum((Decimal(str(l.line_total)) for l in self.lines), Decimal('0'))
        disc = Decimal(str(self.discount_amount)) if self.discount_amount else Decimal('0')
        ship = Decimal(str(self.shipping_cost)) if self.shipping_cost else Decimal('0')
        tax_r = Decimal(str(self.tax_rate)) if self.tax_rate else Decimal('0')
        taxable = self.subtotal - disc + ship
        self.tax_amount = (taxable * (tax_r / Decimal('100'))).quantize(Decimal('0.01'), ROUND_HALF_UP)
        self.total_amount = (taxable + self.tax_amount).quantize(Decimal('0.001'), ROUND_HALF_UP)
        ex = Decimal(str(self.exchange_rate)) if self.exchange_rate else Decimal('1')
        self.amount_aed = (self.total_amount * ex).quantize(Decimal('0.001'), ROUND_HALF_UP)

    @property
    def is_expired(self):
        return self.valid_until and date.today() > self.valid_until

    @property
    def status_ar(self):
        return {'draft': 'مسودة', 'sent': 'مرسلة', 'accepted': 'مقبولة', 'rejected': 'مرفوضة',
                'expired': 'منتهية', 'converted': 'متحويلة'}.get(self.status, self.status)

    def to_dict(self):
        return {
            'id': self.id, 'quotation_number': self.quotation_number,
            'customer': self.customer.name if self.customer else None,
            'total_amount': float(self.total_amount) if self.total_amount else 0,
            'status': self.status, 'status_ar': self.status_ar,
            'valid_until': self.valid_until.isoformat() if self.valid_until else None,
        }


class QuotationLine(db.Model):
    __tablename__ = 'quotation_lines'
    id = db.Column(db.Integer, primary_key=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Numeric(15, 3), nullable=False)
    unit_price = db.Column(db.Numeric(15, 3), nullable=False)
    discount_percent = db.Column(db.Numeric(5, 2), default=0)
    line_total = db.Column(db.Numeric(15, 3), nullable=False)
    notes = db.Column(db.String(255))

    quotation = db.relationship('Quotation', back_populates='lines')
    product = db.relationship('Product')

    def calculate_line_total(self):
        qty = Decimal(str(self.quantity)) if self.quantity else Decimal('0')
        price = Decimal(str(self.unit_price)) if self.unit_price else Decimal('0')
        disc = Decimal(str(self.discount_percent)) if self.discount_percent else Decimal('0')
        self.line_total = (qty * price * (Decimal('100') - disc) / Decimal('100')).quantize(Decimal('0.001'), ROUND_HALF_UP)


# ==================== PURCHASE ORDERS ====================

class PurchaseOrder(db.Model):
    """Purchase Order - formal procurement document"""
    __tablename__ = 'purchase_orders'

    id = db.Column(db.Integer, primary_key=True)
    po_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'))
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    po_date = db.Column(db.Date, nullable=False, index=True)
    expected_delivery = db.Column(db.Date)

    subtotal = db.Column(db.Numeric(15, 3), default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(15, 3), default=0)
    total_amount = db.Column(db.Numeric(15, 3), default=0)
    currency = db.Column(db.String(3), default='AED')
    exchange_rate = db.Column(db.Numeric(15, 6), default=1)

    status = db.Column(db.String(20), default='draft', index=True)
    # draft, submitted, approved, partially_received, received, cancelled

    # Link to final purchase invoice
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'))

    notes = db.Column(db.Text)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    supplier = db.relationship('Supplier')
    warehouse = db.relationship('Warehouse')
    requested_by = db.relationship('User', foreign_keys=[requested_by_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])
    purchase = db.relationship('Purchase', foreign_keys=[purchase_id])
    lines = db.relationship('PurchaseOrderLine', back_populates='order', cascade='all, delete-orphan')

    def calculate_totals(self):
        self.subtotal = sum((Decimal(str(l.line_total)) for l in self.lines), Decimal('0'))
        tax_r = Decimal(str(self.tax_rate)) if self.tax_rate else Decimal('0')
        self.tax_amount = (self.subtotal * (tax_r / Decimal('100'))).quantize(Decimal('0.01'), ROUND_HALF_UP)
        self.total_amount = (self.subtotal + self.tax_amount).quantize(Decimal('0.001'), ROUND_HALF_UP)

    @property
    def total_received(self):
        return sum((Decimal(str(l.received_quantity or 0)) for l in self.lines), Decimal('0'))

    @property
    def is_fully_received(self):
        return all((l.received_quantity or Decimal('0')) >= l.quantity for l in self.lines)

    @property
    def status_ar(self):
        return {'draft': 'مسودة', 'submitted': 'مقدمة', 'approved': 'معتمدة',
                'partially_received': 'استلام جزئي', 'received': 'مستلمة', 'cancelled': 'ملغاة'}.get(self.status, self.status)


class PurchaseOrderLine(db.Model):
    __tablename__ = 'purchase_order_lines'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Numeric(15, 3), nullable=False)
    unit_cost = db.Column(db.Numeric(15, 3), nullable=False)
    discount_percent = db.Column(db.Numeric(5, 2), default=0)
    line_total = db.Column(db.Numeric(15, 3), nullable=False)
    received_quantity = db.Column(db.Numeric(15, 3), default=0)
    notes = db.Column(db.String(255))

    order = db.relationship('PurchaseOrder', back_populates='lines')
    product = db.relationship('Product')

    def calculate_line_total(self):
        qty = Decimal(str(self.quantity)) if self.quantity else Decimal('0')
        cost = Decimal(str(self.unit_cost)) if self.unit_cost else Decimal('0')
        disc = Decimal(str(self.discount_percent)) if self.discount_percent else Decimal('0')
        self.line_total = (qty * cost * (Decimal('100') - disc) / Decimal('100')).quantize(Decimal('0.001'), ROUND_HALF_UP)


# ==================== FISCAL PERIODS ====================

class FiscalPeriod(db.Model):
    """Fiscal period locking to prevent backdating"""
    __tablename__ = 'fiscal_periods'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    year = db.Column(db.Integer, nullable=False, index=True)
    period_type = db.Column(db.String(20), default='annual')  # annual, quarterly, monthly
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False, index=True)
    is_closed = db.Column(db.Boolean, default=False, index=True)
    closed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    closed_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    closed_by = db.relationship('User', foreign_keys=[closed_by_id])

    def close(self, user_id):
        if self.is_closed:
            raise ValueError('الفترة المالية مقفلة بالفعل')
        self.is_closed = True
        self.closed_by_id = user_id
        self.closed_at = datetime.now(timezone.utc)

    def reopen(self):
        self.is_closed = False
        self.closed_by_id = None
        self.closed_at = None

    def contains_date(self, check_date):
        return self.start_date <= check_date <= self.end_date

    @property
    def status_ar(self):
        return 'مغلقة' if self.is_closed else 'مفتوحة'


# ==================== STOCK TRANSFERS ====================

class StockTransfer(db.Model):
    """Transfer stock between warehouses"""
    __tablename__ = 'stock_transfers'

    id = db.Column(db.Integer, primary_key=True)
    transfer_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    from_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=False)
    to_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=False)
    transfer_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), default='pending', index=True)  # pending, in_transit, received, cancelled
    notes = db.Column(db.Text)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    received_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    received_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    from_warehouse = db.relationship('Warehouse', foreign_keys=[from_warehouse_id])
    to_warehouse = db.relationship('Warehouse', foreign_keys=[to_warehouse_id])
    requested_by = db.relationship('User', foreign_keys=[requested_by_id])
    received_by = db.relationship('User', foreign_keys=[received_by_id])
    lines = db.relationship('StockTransferLine', back_populates='transfer', cascade='all, delete-orphan')

    @property
    def status_ar(self):
        return {'pending': 'قيد الانتظار', 'in_transit': 'في الطريق', 'received': 'تم الاستلام',
                'cancelled': 'ملغي'}.get(self.status, self.status)


class StockTransferLine(db.Model):
    __tablename__ = 'stock_transfer_lines'
    id = db.Column(db.Integer, primary_key=True)
    transfer_id = db.Column(db.Integer, db.ForeignKey('stock_transfers.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Numeric(15, 3), nullable=False)
    notes = db.Column(db.String(255))

    transfer = db.relationship('StockTransfer', back_populates='lines')
    product = db.relationship('Product')


# ==================== STOCK TAKE ====================

class StockTake(db.Model):
    """Physical inventory count"""
    __tablename__ = 'stock_takes'

    id = db.Column(db.Integer, primary_key=True)
    stocktake_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=False)
    stocktake_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), default='in_progress', index=True)  # in_progress, completed, approved
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime)

    warehouse = db.relationship('Warehouse')
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])
    items = db.relationship('StockTakeItem', back_populates='stocktake', cascade='all, delete-orphan')

    @property
    def status_ar(self):
        return {'in_progress': 'جاري الجرد', 'completed': 'مكتمل', 'approved': 'معتمد'}.get(self.status, self.status)

    @property
    def total_variances(self):
        return sum((abs(i.variance or 0) for i in self.items), 0)


class StockTakeItem(db.Model):
    __tablename__ = 'stock_take_items'
    id = db.Column(db.Integer, primary_key=True)
    stocktake_id = db.Column(db.Integer, db.ForeignKey('stock_takes.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    system_quantity = db.Column(db.Numeric(15, 3), nullable=False)
    counted_quantity = db.Column(db.Numeric(15, 3))
    variance = db.Column(db.Numeric(15, 3), default=0)
    notes = db.Column(db.String(255))

    stocktake = db.relationship('StockTake', back_populates='items')
    product = db.relationship('Product')

    def calculate_variance(self):
        if self.counted_quantity is not None:
            self.variance = self.counted_quantity - self.system_quantity


# ==================== DUNNING LETTERS ====================

class DunningLetter(db.Model):
    """Automated collection reminder for overdue receivables"""
    __tablename__ = 'dunning_letters'

    id = db.Column(db.Integer, primary_key=True)
    letter_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'))

    level = db.Column(db.Integer, default=1)  # 1=friendly, 2=formal, 3=urgent, 4=legal
    amount_due = db.Column(db.Numeric(15, 3), nullable=False)
    days_overdue = db.Column(db.Integer, nullable=False)
    letter_date = db.Column(db.Date, nullable=False)

    status = db.Column(db.String(20), default='draft')  # draft, sent, paid, escalated
    sent_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    customer = db.relationship('Customer')
    sale = db.relationship('Sale')

    @property
    def level_ar(self):
        return {1: 'تذ friendly', 2: 'تذكير رسمي', 3: 'إنذار عاجل', 4: 'إنذار قانوني'}.get(self.level, str(self.level))


# ==================== RECURRING EXPENSES ====================

class RecurringExpense(db.Model):
    """Template for recurring expenses (rent, salaries, etc.)"""
    __tablename__ = 'recurring_expenses'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('expense_categories.id'), nullable=False)
    amount = db.Column(db.Numeric(15, 3), nullable=False)
    currency = db.Column(db.String(3), default='AED')
    payment_method = db.Column(db.String(20), default='bank_transfer')
    supplier_name = db.Column(db.String(200))
    description = db.Column(db.Text)

    frequency = db.Column(db.String(20), nullable=False)  # monthly, quarterly, annual
    next_due_date = db.Column(db.Date, nullable=False, index=True)
    last_generated_date = db.Column(db.Date)

    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    category = db.relationship('ExpenseCategory')

    def get_next_due(self):
        """Calculate next due date based on frequency"""
        if not self.next_due_date:
            return None
        if self.frequency == 'monthly':
            return self.next_due_date + timedelta(days=30)
        elif self.frequency == 'quarterly':
            return self.next_due_date + timedelta(days=90)
        elif self.frequency == 'annual':
            return self.next_due_date + timedelta(days=365)
        return self.next_due_date


# ==================== LOT/SERIAL TRACKING ====================

class ProductLot(db.Model):
    """Lot/batch tracking for products"""
    __tablename__ = 'product_lots'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    lot_number = db.Column(db.String(50), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), index=True)

    quantity = db.Column(db.Numeric(15, 3), nullable=False, default=0)
    cost_price = db.Column(db.Numeric(15, 3), default=0)
    manufacture_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date, index=True)

    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    product = db.relationship('Product')
    warehouse = db.relationship('Warehouse')
    purchase = db.relationship('Purchase')

    __table_args__ = (
        db.UniqueConstraint('product_id', 'lot_number', 'warehouse_id', name='uq_product_lot_warehouse'),
    )

    @property
    def is_expired(self):
        return self.expiry_date and date.today() > self.expiry_date

    @property
    def days_until_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - date.today()).days


# ==================== BIN/LOCATION TRACKING ====================

class WarehouseBin(db.Model):
    """Physical bin/shelf location within a warehouse"""
    __tablename__ = 'warehouse_bins'

    id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.id'), nullable=False, index=True)
    code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100))
    aisle = db.Column(db.String(20))
    shelf = db.Column(db.String(20))
    position = db.Column(db.String(20))
    capacity = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    warehouse = db.relationship('Warehouse', backref='bins')

    __table_args__ = (
        db.UniqueConstraint('warehouse_id', 'code', name='uq_warehouse_bin_code'),
    )

    @property
    def full_code(self):
        return f"{self.code}" + (f"-{self.aisle}{self.shelf}{self.position}" if self.aisle else "")

    @property
    def current_stock(self):
        from sqlalchemy import func
        result = db.session.query(func.sum(ProductBin.stock_quantity)).filter(
            ProductBin.bin_id == self.id
        ).scalar()
        return result or 0


class ProductBin(db.Model):
    """Product-to-bin assignment with stock quantities"""
    __tablename__ = 'product_bins'

    id = db.Column(db.Integer, primary_key=True)
    bin_id = db.Column(db.Integer, db.ForeignKey('warehouse_bins.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    stock_quantity = db.Column(db.Numeric(15, 3), default=0)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    bin = db.relationship('WarehouseBin')
    product = db.relationship('Product')

    __table_args__ = (
        db.UniqueConstraint('bin_id', 'product_id', name='uq_bin_product'),
    )


# ==================== E-INVOICING (FATOORA) ====================

class EInvoice(db.Model):
    """UAE FATOORA e-invoice record"""
    __tablename__ = 'e_invoices'

    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False, index=True)

    # FATOORA fields
    uuid = db.Column(db.String(100), unique=True)
    invoice_type = db.Column(db.String(30), default='standard')  # standard, simplified, credit, debit
    invoice_date = db.Column(db.DateTime, nullable=False)

    # Buyer info
    buyer_name = db.Column(db.String(200), nullable=False)
    buyer_trn = db.Column(db.String(50))  # Tax Registration Number
    buyer_address = db.Column(db.Text)

    # Amounts
    total_amount = db.Column(db.Numeric(15, 3), nullable=False)
    tax_amount = db.Column(db.Numeric(15, 3), default=0)
    total_with_tax = db.Column(db.Numeric(15, 3), nullable=False)
    currency = db.Column(db.String(3), default='AED')

    # Status
    status = db.Column(db.String(20), default='draft', index=True)
    # draft, submitted, accepted, rejected, cancelled
    submitted_at = db.Column(db.DateTime)
    accepted_at = db.Column(db.DateTime)

    # XML/JSON payload
    xml_payload = db.Column(db.Text)
    json_payload = db.Column(db.Text)
    fta_response = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    sale = db.relationship('Sale')

    @property
    def status_ar(self):
        return {'draft': 'مسودة', 'submitted': 'مقدمة', 'accepted': 'مقبولة',
                'rejected': 'مرفوضة', 'cancelled': 'ملغاة'}.get(self.status, self.status)

    def generate_xml(self):
        """Generate FATOORA-compliant XML"""
        from xml.etree.ElementTree import Element, SubElement, tostring
        root = Element('Invoice')
        root.set('xmlns', 'urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0')
        root.set('xmlns:udt', 'urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100')
        root.set('xmlns:crt', 'urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0')

        # Header
        h = SubElement(root, 'ExchangedDocumentContext')
        SubElement(h, 'BusinessProcessSpecifiedDocumentContextParameter', {'ID': 'urn:fdc:peppol.eu:2017:poacc:billing:01:1.0'})
        SubElement(h, 'GuidelineSpecifiedDocumentContextParameter', {'ID': 'urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0'})

        hdr = SubElement(root, 'ExchangedDocument')
        SubElement(hdr, 'ID').text = self.invoice_number
        SubElement(hdr, 'IssueDateTime').text = self.invoice_date.strftime('%Y-%m-%dT%H:%M:%S') if self.invoice_date else ''
        SubElement(hdr, 'TypeCode').text = '380'  # Invoice

        # SupplyChainTradeTransaction
        sct = SubElement(root, 'SupplyChainTradeTransaction')
        ApplicableHeaderTradeAgreement = SubElement(sct, 'ApplicableHeaderTradeAgreement')

        # Seller
        seller = SubElement(ApplicableHeaderTradeAgreement, 'SellerTradeParty')
        SubElement(seller, 'Name').text = 'Seller'
        SubElement(seller, 'DefinedTradeContact').append(SubElement(seller.find('DefinedTradeContact') if seller.find('DefinedTradeContact') is not None else seller, 'TelephoneUniversalCommunication'))
        seller.find('.//TelephoneUniversalCommunication') if seller.find('.//TelephoneUniversalCommunication') is not None else None

        # Buyer
        buyer = SubElement(ApplicableHeaderTradeAgreement, 'BuyerTradeParty')
        SubElement(buyer, 'Name').text = self.buyer_name or ''
        if self.buyer_trn:
            SubElement(buyer, 'ID').text = self.buyer_trn

        # Delivery
        SubElement(sct, 'ApplicableHeaderTradeDelivery')

        # Payment
        SubElement(sct, 'ApplicableHeaderTradeSettlement')

        xml_str = tostring(root, encoding='unicode')
        self.xml_payload = xml_str
        return xml_str

    def generate_json(self):
        """Generate FATOORA-compliant JSON"""
        import json
        from models import Sale, SaleLine
        sale = db.session.get(Sale, self.sale_id)
        lines_data = []
        if sale:
            for line in sale.lines:
                lines_data.append({
                    'item_name': line.product.name if line.product else '',
                    'quantity': float(line.quantity),
                    'unit_price': float(line.unit_price),
                    'total': float(line.line_total),
                    'vat_rate': float(line.unit_price * Decimal('0.05')),
                })

        payload = {
            'invoice_number': self.invoice_number,
            'invoice_date': self.invoice_date.strftime('%Y-%m-%d') if self.invoice_date else '',
            'invoice_type': self.invoice_type,
            'buyer_name': self.buyer_name or '',
            'buyer_trn': self.buyer_trn or '',
            'total_amount': float(self.total_amount),
            'tax_amount': float(self.tax_amount),
            'total_with_tax': float(self.total_with_tax),
            'currency': self.currency,
            'lines': lines_data,
        }
        self.json_payload = json.dumps(payload, ensure_ascii=False)
        return payload
