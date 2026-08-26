from datetime import date, datetime, timezone
from decimal import Decimal
from flask import current_app
from flask_login import current_user
from extensions import db
from models import Receipt, Sale
from services.currency_service import CurrencyService
from services.gl_service import GLService
from utils.decorators import tx
from utils.helpers import generate_number


def resolve_audit_actor():
    """(user_id, actor_label) resolved defensively; headless jobs get 'system'."""
    try:
        from flask_login import current_user
        if current_user and getattr(current_user, 'is_authenticated', False):
            label = getattr(current_user, 'username', None) or f'user-{current_user.id}'
            return current_user.id, label
    except Exception:
        pass
    return None, 'system'


def json_safe_changes(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe_changes(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe_changes(v) for v in value]
    return value


def write_receipt_audit(action, record_id, changes):
    from utils.helpers import create_audit_log

    _, actor = resolve_audit_actor()
    payload = json_safe_changes(changes)
    payload['actor'] = actor
    payload['occurred_at'] = datetime.now(timezone.utc).isoformat()
    create_audit_log(action, table_name='receipts', record_id=record_id, changes=payload)


class PaymentService:

    @staticmethod
    @tx
    def create_receipt(payment_data):  # noqa: C901
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
        currency = payment_data.get('currency', 'ILS')
        payment_method = payment_data.get('payment_method', 'cash')
        notes = payment_data.get('notes')
        user_exchange_rate = payment_data.get('user_exchange_rate')
        reference_number = payment_data.get('reference_number')
        cheque_number = payment_data.get('cheque_number')
        cheque_date = payment_data.get('cheque_date')
        bank_name = payment_data.get('bank_name')
        allocate_to_sales = payment_data.get('allocate_to_sales')

        customer = db.session.get(Customer, customer_id)
        receipt = None
        gl_posted = None
        gl_entry_ref = None
        gl_warning = None
        allocation_summary = []

        try:
            # Convert cheque_date to date object if it's a string
            if cheque_date and isinstance(cheque_date, str):
                try:
                    cheque_date = datetime.strptime(cheque_date, '%Y-%m-%d').date()
                except ValueError:
                    raise ValueError('تاريخ الشيك غير صالح')

            receipt_number = generate_number('RCV', Receipt, 'receipt_number')

            exchange_rate = CurrencyService.get_exchange_rate(
                currency,
                CurrencyService.get_base_currency(),
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
                amount_base=Decimal(str(amount)) * exchange_rate,
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
                    amount_base=Decimal(str(amount)) * exchange_rate,
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
                gl_posted = True

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
                    entry = GLService.post_entry(lines, description=f'Receipt {receipt.receipt_number}', reference_type='Receipt', reference_id=receipt.id, currency=receipt.currency, exchange_rate=receipt.exchange_rate)  # noqa: E501
                    gl_posted = True
                    gl_entry_ref = entry.entry_number
                except Exception as e:
                    # Orphan-prevention contract: a saved receipt must always be
                    # either linked to a GL entry or carry an explicit warning.
                    gl_posted = False
                    gl_warning = str(e)
                    current_app.logger.warning(
                        f'ORPHAN RECEIPT WARNING: receipt {receipt.receipt_number} '
                        f'(id={receipt.id}) saved without GL entry: {e}'
                    )

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
                    sale.paid_amount_base += allocated_amount * exchange_rate
                    sale.balance_due -= allocated_amount

                    if sale.paid_amount >= sale.total_amount:
                        sale.payment_status = 'paid'
                    elif sale.paid_amount > 0:
                        sale.payment_status = 'partial'

                    remaining_amount -= allocated_amount
                    allocation_summary.append({'sale_id': sale.id, 'allocated': allocated_amount})

            db.session.commit()

            current_app.logger.info(f'Receipt created: {receipt.receipt_number}')

            write_receipt_audit('receipt_create', receipt.id, {
                'receipt_number': receipt.receipt_number,
                'customer_id': customer.id,
                'amount': receipt.amount,
                'amount_base': receipt.amount_base,
                'currency': currency,
                'exchange_rate': exchange_rate,
                'payment_method': payment_method,
                'source_type': source_type,
                'source_id': source_id,
                'cheque_id': receipt.cheque_id,
                'gl_posted': gl_posted,
                'gl_entry': gl_entry_ref,
                'gl_warning': gl_warning,
                'allocations': allocation_summary,
            })

            return receipt

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Receipt creation failed: {e}')
            write_receipt_audit('receipt_create_failed', receipt.id if receipt else None, {
                'customer_id': customer_id,
                'amount': amount,
                'payment_method': payment_method,
                'error_type': type(e).__name__,
                'error': str(e),
            })
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
            db.func.sum(Sale.amount_base - Sale.paid_amount_base)
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
    @tx
    def allocate_receipt_to_oldest_sales(receipt, customer):
        allocations = []
        remaining_after = None
        try:
            remaining_amount = receipt.amount

            unpaid_sales = PaymentService.get_unpaid_sales(customer)

            for sale in unpaid_sales:
                if remaining_amount <= 0:
                    break

                allocated = min(remaining_amount, sale.balance_due)

                sale.paid_amount += allocated
                sale.paid_amount_base += allocated * receipt.exchange_rate
                sale.balance_due -= allocated

                if sale.paid_amount >= sale.total_amount:
                    sale.payment_status = 'paid'
                elif sale.paid_amount > 0:
                    sale.payment_status = 'partial'

                remaining_amount -= allocated
                allocations.append({'sale_id': sale.id, 'allocated': allocated})

            remaining_after = remaining_amount

            db.session.commit()

            current_app.logger.info(f'Receipt {receipt.receipt_number} allocated to sales')

            write_receipt_audit('receipt_allocation', receipt.id, {
                'receipt_number': receipt.receipt_number,
                'customer_id': customer.id,
                'amount': receipt.amount,
                'allocations': allocations,
                'unallocated': remaining_after,
            })

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Receipt allocation failed: {e}')
            write_receipt_audit('receipt_allocation_failed', receipt.id if receipt else None, {
                'customer_id': getattr(customer, 'id', None),
                'error_type': type(e).__name__,
                'error': str(e),
            })
            raise
