from decimal import Decimal
from flask import current_app
from flask_login import current_user
from extensions import db
from models import Receipt, Sale
from services.currency_service import CurrencyService
from services.gl_service import GLService
from utils.helpers import generate_number


class PaymentService:
    
    @staticmethod
    def create_receipt(payment_data):
        """
        Create receipt from payment data dict
        
        Args:
            payment_data (dict): {
                'customer_id': int,
                'amount': Decimal,
                'currency': str,
                'payment_method': str,
                'notes': str (optional),
                ...
            }
        """
        from models import Customer
        
        customer_id = payment_data.get('customer_id')
        amount = payment_data.get('amount')
        currency = payment_data.get('currency', 'AED')
        payment_method = payment_data.get('payment_method', 'cash')
        notes = payment_data.get('notes')
        user_exchange_rate = payment_data.get('user_exchange_rate')
        reference_number = payment_data.get('reference_number')
        cheque_number = payment_data.get('cheque_number')
        cheque_date = payment_data.get('cheque_date')
        bank_name = payment_data.get('bank_name')
        allocate_to_sales = payment_data.get('allocate_to_sales')
        
        # Convert cheque_date to date object if it's a string
        if cheque_date and isinstance(cheque_date, str):
            from datetime import datetime
            try:
                cheque_date = datetime.strptime(cheque_date, '%Y-%m-%d').date()
            except ValueError:
                raise ValueError('تاريخ الشيك غير صالح')
        
        customer = db.session.get(Customer, customer_id)
        try:
            receipt_number = generate_number('RCV', Receipt, 'receipt_number')
            
            exchange_rate = CurrencyService.get_exchange_rate(
                currency,
                'AED',
                user_rate=user_exchange_rate
            )
            
            # تحديد نوع المصدر والاتجاه
            source_type = 'manual'  # افتراضي
            source_id = None
            direction = 'incoming'  # سندات القبض دائماً وارد
            
            if allocate_to_sales:
                # إذا كان مرتبط بفاتورة بيع
                source_type = 'sale'
                source_id = list(allocate_to_sales.keys())[0]  # أول فاتورة
            
            receipt = Receipt(
                receipt_number=receipt_number,
                source_type=source_type,
                source_id=source_id,
                direction=direction,
                customer_id=customer.id,
                amount=Decimal(str(amount)),
                currency=currency,
                exchange_rate=exchange_rate,
                amount_aed=Decimal(str(amount)) * exchange_rate,
                payment_method=payment_method,
                reference_number=reference_number,
                cheque_number=cheque_number,
                cheque_date=cheque_date,
                bank_name=bank_name,
                notes=notes,
                user_id=current_user.id if current_user and current_user.is_authenticated else 1
            )
            
            db.session.add(receipt)
            db.session.flush()
            
            # إنشاء سجل الشيك إذا كانت طريقة الدفع شيك
            if payment_method == 'cheque' and cheque_number:
                from models import Cheque
                cheque = Cheque(
                    cheque_number=cheque_number,
                    cheque_bank_number=cheque_number,  # نفس رقم الشيك
                    cheque_type='incoming',
                    customer_id=customer.id,
                    amount=Decimal(str(amount)),
                    currency=currency,
                    exchange_rate=exchange_rate,
                    amount_aed=Decimal(str(amount)) * exchange_rate,
                    issue_date=receipt.receipt_date.date(),  # تاريخ الإصدار = تاريخ السند
                    due_date=cheque_date,  # تاريخ الاستحقاق
                    bank_name=bank_name,
                    status='pending',
                    notes=notes
                )
                db.session.add(cheque)
                db.session.flush()
                
                # ربط الشيك بالسند
                receipt.cheque_id = cheque.id
                
                # استخدام منطق الشيك المحاسبي (شيكات تحت التحصيل -> ذمم مدينة)
                cheque.receive_cheque()
            
            else:
                # GL Entry for Standard Receipt (Cash/Bank)
                try:
                    GLService.ensure_core_accounts()
                    payment_account = GLService.get_payment_debit_account(receipt.payment_method)
                    credit_account = GLService.get_customer_credit_account(customer)

                    # Create GL entries
                    lines = [
                        {'account': payment_account, 'debit': receipt.amount, 'description': f'قبض من {customer.name}'},
                        {'account': credit_account, 'credit': receipt.amount, 'description': f'سند قبض {receipt.receipt_number}'}
                    ]
                    GLService.post_entry(lines, description=f'Receipt {receipt.receipt_number}', reference_type='Receipt', reference_id=receipt.id, currency=receipt.currency, exchange_rate=receipt.exchange_rate)
                except Exception as e:
                    current_app.logger.warning(f'GL posting failed: {e}')
            
            # Allocation Logic (Restored)
            if allocate_to_sales:
                remaining_amount = Decimal(str(amount))
                
                for sale_id, allocated in allocate_to_sales.items():
                    if remaining_amount <= 0:
                        break
                    
                    sale = db.session.get(Sale, sale_id)
                    
                    if not sale or sale.customer_id != customer.id:
                        continue
                    
                    allocated_amount = min(Decimal(str(allocated)), remaining_amount, sale.balance_due)
                    
                    sale.paid_amount += allocated_amount
                    sale.paid_amount_aed += allocated_amount * exchange_rate
                    sale.balance_due -= allocated_amount
                    
                    if sale.paid_amount >= sale.total_amount:
                        sale.payment_status = 'paid'
                    elif sale.paid_amount > 0:
                        sale.payment_status = 'partial'
                    
                    remaining_amount -= allocated_amount
            
            db.session.commit()
            
            current_app.logger.info(f'Receipt created: {receipt.receipt_number}')
            
            return receipt
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Receipt creation failed: {e}')
            raise
    
    @staticmethod
    def get_customer_balance(customer):
        total_sales = db.session.query(
            db.func.sum(Sale.balance_due)
        ).filter(
            Sale.customer_id == customer.id,
            Sale.status == 'confirmed'
        ).scalar() or Decimal('0')
        
        return total_sales
    
    @staticmethod
    def get_customer_balance_aed(customer):
        total_sales_aed = db.session.query(
            db.func.sum(Sale.amount_aed - Sale.paid_amount_aed)
        ).filter(
            Sale.customer_id == customer.id,
            Sale.status == 'confirmed'
        ).scalar() or Decimal('0')
        
        return total_sales_aed
    
    @staticmethod
    def get_unpaid_sales(customer):
        return Sale.query.filter(
            Sale.customer_id == customer.id,
            Sale.status == 'confirmed',
            Sale.balance_due > 0
        ).order_by(Sale.sale_date.asc()).all()
    
    @staticmethod
    def allocate_receipt_to_oldest_sales(receipt, customer):
        try:
            remaining_amount = receipt.amount
            
            unpaid_sales = PaymentService.get_unpaid_sales(customer)
            
            for sale in unpaid_sales:
                if remaining_amount <= 0:
                    break
                
                allocated = min(remaining_amount, sale.balance_due)
                
                sale.paid_amount += allocated
                sale.paid_amount_aed += allocated * receipt.exchange_rate
                sale.balance_due -= allocated
                
                if sale.paid_amount >= sale.total_amount:
                    sale.payment_status = 'paid'
                elif sale.paid_amount > 0:
                    sale.payment_status = 'partial'
                
                remaining_amount -= allocated
            
            db.session.commit()
            
            current_app.logger.info(f'Receipt {receipt.receipt_number} allocated to sales')
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Receipt allocation failed: {e}')
            raise

