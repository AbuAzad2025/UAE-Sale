"""
ERP Modules Service - Business logic for all extended modules
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from flask import current_app
from extensions import db
from models.erp_modules import (
    Quotation, QuotationLine, PurchaseOrder, PurchaseOrderLine,
    FiscalPeriod, StockTransfer, StockTransferLine,
    StockTake, StockTakeItem, DunningLetter, RecurringExpense,
    ProductLot, WarehouseBin, ProductBin, EInvoice,
)
from utils.helpers import generate_number


class QuotationService:

    @staticmethod
    def create_quotation(customer_id, seller_id, lines_data, warehouse_id=None,
                         currency='AED', user_exchange_rate=None,
                         discount_amount=0, shipping_cost=0, tax_rate=0,
                         valid_days=30, notes=None):
        from models import Customer, User, Product, Warehouse
        from services.currency_service import CurrencyService

        customer = db.get_or_404(Customer, customer_id)
        seller = db.get_or_404(User, seller_id)

        exchange_rate = CurrencyService.get_exchange_rate(currency, 'AED', user_rate=user_exchange_rate)
        today = date.today()

        q = Quotation(
            quotation_number=generate_number('QT', Quotation, 'quotation_number'),
            customer_id=customer_id,
            seller_id=seller_id,
            warehouse_id=warehouse_id,
            quotation_date=today,
            valid_until=today + timedelta(days=valid_days),
            currency=currency,
            exchange_rate=exchange_rate,
            discount_amount=Decimal(str(discount_amount)),
            shipping_cost=Decimal(str(shipping_cost)),
            tax_rate=Decimal(str(tax_rate)),
            notes=notes,
        )
        db.session.add(q)
        db.session.flush()

        for ld in lines_data:
            product = db.session.get(Product, ld['product_id'])
            if not product:
                continue
            line = QuotationLine(
                quotation_id=q.id,
                product_id=product.id,
                quantity=Decimal(str(ld['quantity'])),
                unit_price=Decimal(str(ld.get('unit_price') or product.get_price_for_customer(customer.customer_type))),
                discount_percent=Decimal(str(ld.get('discount_percent', 0))),
            )
            line.calculate_line_total()
            db.session.add(line)

        q.calculate_totals()
        db.session.commit()
        return q

    @staticmethod
    def convert_to_sale(quotation_id, user_id):
        """Convert accepted quotation to a sale"""
        from models import Sale, SaleLine
        from services.sale_service import SaleService

        q = db.get_or_404(Quotation, quotation_id)
        if q.status not in ('accepted', 'sent', 'draft'):
            raise ValueError('لا يمكن تحويل فاتورة بحالة: ' + q.status_ar)
        if q.is_expired:
            raise ValueError('عرض الأسعار منتهي الصلاحية')

        from models import Customer, User, Product as Prod
        customer = db.session.get(Customer, q.customer_id)
        seller = db.session.get(User, q.seller_id)
        lines_data = []
        for l in q.lines:
            product = db.session.get(Prod, l.product_id)
            if product:
                lines_data.append({
                    'product': product,
                    'quantity': l.quantity,
                    'unit_price': l.unit_price,
                    'discount_percent': l.discount_percent,
                })
        sale = SaleService.create_sale(
            customer=customer,
            seller=seller,
            lines_data=lines_data,
            warehouse_id=q.warehouse_id,
            currency=q.currency,
            user_exchange_rate=float(q.exchange_rate),
            discount_amount=float(q.discount_amount),
            shipping_cost=float(q.shipping_cost),
            tax_rate=float(q.tax_rate),
            notes=f'[محولة من عرض أسعار {q.quotation_number}] {q.notes or ""}',
        )
        q.status = 'converted'
        q.converted_sale_id = sale.id
        db.session.commit()
        return sale


class PurchaseOrderService:

    @staticmethod
    def create_po(supplier_id, warehouse_id, lines_data, user_id,
                  expected_delivery=None, notes=None, tax_rate=0):
        from models import Supplier, Product

        supplier = db.get_or_404(Supplier, supplier_id)

        po = PurchaseOrder(
            po_number=generate_number('PO', PurchaseOrder, 'po_number'),
            supplier_id=supplier_id,
            warehouse_id=warehouse_id,
            requested_by_id=user_id,
            po_date=date.today(),
            expected_delivery=expected_delivery,
            tax_rate=Decimal(str(tax_rate)),
            notes=notes,
        )
        db.session.add(po)
        db.session.flush()

        for ld in lines_data:
            product = db.session.get(Product, ld['product_id'])
            if not product:
                continue
            line = PurchaseOrderLine(
                order_id=po.id,
                product_id=product.id,
                quantity=Decimal(str(ld['quantity'])),
                unit_cost=Decimal(str(ld['unit_cost'])),
                discount_percent=Decimal(str(ld.get('discount_percent', 0))),
            )
            line.calculate_line_total()
            db.session.add(line)

        po.calculate_totals()
        db.session.commit()
        return po

    @staticmethod
    def approve_po(po_id, approver_id):
        po = db.get_or_404(PurchaseOrder, po_id)
        if po.status != 'submitted':
            raise ValueError('يمكن اعتماد أمر شراء في حالة "مقدمة" فقط')
        po.status = 'approved'
        po.approved_by_id = approver_id
        po.approved_at = datetime.now(timezone.utc)
        db.session.commit()
        return po

    @staticmethod
    def receive_po(po_id, user_id):
        """Receive a PO and create a Purchase Invoice"""
        from models import Purchase, PurchaseLine
        from services.gl_service import GLService
        from services.stock_service import StockService
        from decimal import Decimal

        po = db.get_or_404(PurchaseOrder, po_id)
        if po.status not in ('approved', 'partially_received'):
            raise ValueError('يمكن استلام أمر شراء معتمد فقط')

        purchase_number = generate_number('P', Purchase, 'purchase_number')
        purchase = Purchase(
            purchase_number=purchase_number,
            supplier_id=po.supplier_id,
            warehouse_id=po.warehouse_id,
            supplier_name=po.supplier.name if po.supplier else '',
            purchase_date=datetime.now(timezone.utc),
            currency=po.currency,
            exchange_rate=po.exchange_rate,
            user_id=user_id,
            subtotal=Decimal('0'),
            tax_amount=Decimal('0'),
            total_amount=Decimal('0'),
            amount_aed=Decimal('0'),
        )
        db.session.add(purchase)
        db.session.flush()

        for po_line in po.lines:
            received_qty = po_line.quantity - (po_line.received_quantity or Decimal('0'))
            if received_qty <= 0:
                continue
            line = PurchaseLine(
                purchase_id=purchase.id,
                product_id=po_line.product_id,
                quantity=received_qty,
                unit_cost=po_line.unit_cost,
                discount_percent=po_line.discount_percent,
            )
            line.calculate_line_total()
            db.session.add(line)
            po_line.received_quantity = (po_line.received_quantity or Decimal('0')) + received_qty

        purchase.calculate_totals()
        po.purchase_id = purchase.id

        if po.is_fully_received:
            po.status = 'received'
        else:
            po.status = 'partially_received'

        db.session.commit()
        return purchase


class FiscalPeriodService:

    @staticmethod
    def create_annual_period(year):
        existing = FiscalPeriod.query.filter_by(year=year, period_type='annual').first()
        if existing:
            raise ValueError(f'الفترة المالية لسنة {year} موجودة بالفعل')
        fp = FiscalPeriod(
            name=f'السنة المالية {year}',
            year=year,
            period_type='annual',
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31),
        )
        db.session.add(fp)
        db.session.commit()
        return fp

    @staticmethod
    def close_period(period_id, user_id):
        fp = db.get_or_404(FiscalPeriod, period_id)
        fp.close(user_id)
        db.session.commit()
        return fp

    @staticmethod
    def is_period_open(check_date):
        """Check if a date falls within an open fiscal period"""
        fp = FiscalPeriod.query.filter(
            FiscalPeriod.start_date <= check_date,
            FiscalPeriod.end_date >= check_date,
        ).first()
        if fp and fp.is_closed:
            return False
        return True

    @staticmethod
    def get_current_period():
        today = date.today()
        return FiscalPeriod.query.filter(
            FiscalPeriod.start_date <= today,
            FiscalPeriod.end_date >= today,
        ).first()


class StockTransferService:

    @staticmethod
    def create_transfer(from_warehouse_id, to_warehouse_id, lines_data, user_id, notes=None):
        from models import Warehouse, Product

        if from_warehouse_id == to_warehouse_id:
            raise ValueError('لا يمكن النقل لنفس المستودع')

        db.get_or_404(Warehouse, from_warehouse_id)
        db.get_or_404(Warehouse, to_warehouse_id)

        transfer = StockTransfer(
            transfer_number=generate_number('TRF', StockTransfer, 'transfer_number'),
            from_warehouse_id=from_warehouse_id,
            to_warehouse_id=to_warehouse_id,
            transfer_date=date.today(),
            requested_by_id=user_id,
            notes=notes,
        )
        db.session.add(transfer)
        db.session.flush()

        for ld in lines_data:
            line = StockTransferLine(
                transfer_id=transfer.id,
                product_id=ld['product_id'],
                quantity=Decimal(str(ld['quantity'])),
                notes=ld.get('notes'),
            )
            db.session.add(line)

        db.session.commit()
        return transfer

    @staticmethod
    def receive_transfer(transfer_id, user_id):
        """Receive transfer: deduct from source, add to destination"""
        from services.stock_service import StockService

        transfer = db.get_or_404(StockTransfer, transfer_id)
        if transfer.status != 'in_transit':
            raise ValueError('يمكن استلام نقل في حالة "في الطريق" فقط')

        for line in transfer.lines:
            # Deduct from source
            StockService.adjust_stock(
                line.product_id, -line.quantity,
                notes=f'Transfer OUT to {transfer.transfer_number}',
                warehouse_id=transfer.from_warehouse_id
            )
            # Add to destination
            StockService.adjust_stock(
                line.product_id, line.quantity,
                notes=f'Transfer IN from {transfer.transfer_number}',
                warehouse_id=transfer.to_warehouse_id
            )

        transfer.status = 'received'
        transfer.received_by_id = user_id
        transfer.received_at = datetime.now(timezone.utc)
        db.session.commit()
        return transfer


class StockTakeService:

    @staticmethod
    def create_stocktake(warehouse_id, user_id):
        """Create a new stock take snapshot"""
        from models import Product, Warehouse
        from services.stock_service import StockService

        wh = db.get_or_404(Warehouse, warehouse_id)
        st = StockTake(
            stocktake_number=generate_number('STK', StockTake, 'stocktake_number'),
            warehouse_id=warehouse_id,
            stocktake_date=date.today(),
            created_by_id=user_id,
        )
        db.session.add(st)
        db.session.flush()

        # Snapshot all products in this warehouse
        products = Product.query.filter_by(is_active=True).all()
        for product in products:
            current_stock = product.current_stock or Decimal('0')
            if current_stock > 0:
                item = StockTakeItem(
                    stocktake_id=st.id,
                    product_id=product.id,
                    system_quantity=current_stock,
                )
                db.session.add(item)

        db.session.commit()
        return st

    @staticmethod
    def complete_stocktake(stocktake_id):
        st = db.get_or_404(StockTake, stocktake_id)
        st.status = 'completed'
        st.completed_at = datetime.now(timezone.utc)
        for item in st.items:
            item.calculate_variance()
        db.session.commit()
        return st

    @staticmethod
    def approve_stocktake(stocktake_id, approver_id):
        """Apply variances to stock"""
        from services.stock_service import StockService

        st = db.get_or_404(StockTake, stocktake_id)
        if st.status != 'completed':
            raise ValueError('يجب إكمال الجرد أولاً')

        for item in st.items:
            if item.variance and item.variance != 0:
                StockService.adjust_stock(
                    item.product_id, item.variance,
                    notes=f'Stock Take Adjustment: {st.stocktake_number}',
                    warehouse_id=st.warehouse_id
                )

        st.status = 'approved'
        st.approved_by_id = approver_id
        db.session.commit()
        return st


class DunningService:

    @staticmethod
    def check_overdue_accounts():
        """Find overdue sales and generate dunning letters"""
        from models import Sale, Customer

        overdue_sales = Sale.query.filter(
            Sale.status == 'confirmed',
            Sale.payment_status.in_(['unpaid', 'partial']),
            Sale.balance_due > Decimal('0'),
        ).all()

        letters = []
        for sale in overdue_sales:
            sale_date = sale.sale_date
            if hasattr(sale_date, 'date') and callable(sale_date.date):
                sale_date = sale_date.date()
            days_overdue = (date.today() - sale_date).days if sale_date else 0
            if days_overdue < 15:
                continue

            # Determine dunning level
            if days_overdue <= 30:
                level = 1
            elif days_overdue <= 60:
                level = 2
            elif days_overdue <= 90:
                level = 3
            else:
                level = 4

            # Check if letter already sent at this level
            existing = DunningLetter.query.filter_by(
                sale_id=sale.id, level=level, status='sent'
            ).first()
            if existing:
                continue

            letter = DunningLetter(
                letter_number=generate_number('DUN', DunningLetter, 'letter_number'),
                customer_id=sale.customer_id,
                sale_id=sale.id,
                level=level,
                amount_due=sale.balance_due,
                days_overdue=days_overdue,
                letter_date=date.today(),
            )
            db.session.add(letter)
            letters.append(letter)

        db.session.commit()
        return letters

    @staticmethod
    def get_overdue_summary():
        """Get summary of overdue accounts for dashboard"""
        from models import Sale
        from sqlalchemy import func

        result = db.session.query(
            func.count(Sale.id),
            func.sum(Sale.balance_due),
        ).filter(
            Sale.status == 'confirmed',
            Sale.payment_status.in_(['unpaid', 'partial']),
            Sale.balance_due > Decimal('0'),
        ).first()

        return {
            'count': result[0] or 0,
            'total_overdue': float(result[1] or 0),
        }


class RecurringExpenseService:

    @staticmethod
    def process_due_expenses():
        """Generate expenses from recurring templates"""
        from models import Expense, ExpenseCategory

        due = RecurringExpense.query.filter(
            RecurringExpense.is_active == True,
            RecurringExpense.next_due_date <= date.today(),
        ).all()

        created = []
        for re in due:
            expense = Expense(
                expense_number=generate_number('EXP', Expense, 'expense_number'),
                category_id=re.category_id,
                description=f'[دوري] {re.name}',
                amount=re.amount,
                currency=re.currency,
                amount_aed=re.amount,
                payment_method=re.payment_method,
                supplier_name=re.supplier_name,
                expense_date=datetime.now(timezone.utc),
                user_id=1,  # System user
            )
            db.session.add(expense)
            re.last_generated_date = date.today()
            re.next_due_date = re.get_next_due()
            created.append(expense)

        db.session.commit()
        return created


class EInvoiceService:

    @staticmethod
    def create_einvoice(sale_id):
        from models import Sale, Customer

        sale = db.get_or_404(Sale, sale_id)
        customer = db.session.get(Customer, sale.customer_id)

        einv = EInvoice(
            invoice_number=f'EI-{sale.sale_number}',
            sale_id=sale_id,
            uuid=f'{sale.sale_number}-{datetime.now().strftime("%Y%m%d%H%M%S")}',
            invoice_type='standard',
            invoice_date=datetime.now(timezone.utc),
            buyer_name=customer.name if customer else '',
            buyer_trn=customer.tax_number if customer else '',
            total_amount=sale.subtotal,
            tax_amount=sale.tax_amount,
            total_with_tax=sale.total_amount,
            currency=sale.currency,
        )
        einv.generate_xml()
        einv.generate_json()
        db.session.add(einv)
        db.session.commit()
        return einv
