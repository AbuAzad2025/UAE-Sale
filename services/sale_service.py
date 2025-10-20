from decimal import Decimal, ROUND_HALF_UP
from flask import current_app
from extensions import db
from models import Sale, SaleLine, Payment
from services.stock_service import StockService
from services.currency_service import CurrencyService
from services.gl_service import GLService
from utils.helpers import generate_number


class SaleService:
    
    @staticmethod
    def create_sale(customer, seller, lines_data, currency='AED', user_exchange_rate=None, 
                    discount_amount=0, shipping_cost=0, tax_rate=0, notes=None, payment_data=None):
        """
        Create a new sale with proper validations and decimal precision
        All financial calculations use Decimal for accuracy
        Uses database transaction with automatic rollback on error
        """
        # Input validations
        if not customer or not customer.is_active:
            raise ValueError('العميل غير صالح أو غير نشط')
        
        if not seller or not seller.is_active:
            raise ValueError('البائع غير صالح أو غير نشط')
        
        if not lines_data or len(lines_data) == 0:
            raise ValueError('يجب إضافة منتج واحد على الأقل')
        
        # Validate discount and tax
        discount_decimal = Decimal(str(discount_amount)) if discount_amount else Decimal('0')
        shipping_decimal = Decimal(str(shipping_cost)) if shipping_cost else Decimal('0')
        tax_rate_decimal = Decimal(str(tax_rate)) if tax_rate else Decimal('0')
        
        if discount_decimal < Decimal('0'):
            raise ValueError('قيمة الخصم لا يمكن أن تكون سالبة')
        
        if shipping_decimal < Decimal('0'):
            raise ValueError('تكلفة الشحن لا يمكن أن تكون سالبة')
        
        if tax_rate_decimal < Decimal('0') or tax_rate_decimal > Decimal('100'):
            raise ValueError('نسبة الضريبة يجب أن تكون بين 0 و 100')
        
        try:
            sale_number = generate_number('S', Sale, 'sale_number')
            
            exchange_rate = CurrencyService.get_exchange_rate(
                currency, 
                'AED', 
                user_rate=user_exchange_rate
            )
            
            # Validate exchange rate
            if exchange_rate <= Decimal('0'):
                raise ValueError('سعر الصرف غير صالح')
            
            sale = Sale(
                sale_number=sale_number,
                customer_id=customer.id,
                seller_id=seller.id,
                currency='AED',  # Always AED for invoice
                exchange_rate=Decimal('1'),  # Always 1 for AED
                discount_amount=discount_decimal,
                shipping_cost=shipping_decimal,
                tax_rate=tax_rate_decimal,
                total_amount=Decimal('0'),  # Temporary - will be calculated
                amount_aed=Decimal('0'),    # Temporary - will be calculated
                notes=notes
            )
            
            db.session.add(sale)
            db.session.flush()
            
            subtotal = Decimal('0')
            
            for line_data in lines_data:
                product = line_data['product']
                quantity = Decimal(str(line_data['quantity']))
                
                # Validate quantity
                if quantity <= Decimal('0'):
                    raise ValueError(f'{product.name}: الكمية يجب أن تكون أكبر من صفر')
                
                # Check stock availability
                available, msg = StockService.check_availability(product.id, quantity)
                if not available:
                    raise ValueError(f'{product.name}: {msg}')
                
                # Get unit price
                if line_data.get('unit_price'):
                    unit_price = Decimal(str(line_data['unit_price']))
                else:
                    unit_price = product.get_price_for_customer(customer.customer_type)
                
                # Validate unit price
                if unit_price <= Decimal('0'):
                    raise ValueError(f'{product.name}: السعر يجب أن يكون أكبر من صفر')
                
                discount_percent = Decimal(str(line_data.get('discount_percent', 0)))
                
                # Validate line discount
                if discount_percent < Decimal('0') or discount_percent > Decimal('100'):
                    raise ValueError(f'{product.name}: نسبة الخصم يجب أن تكون بين 0 و 100')
                
                line = SaleLine(
                    sale_id=sale.id,
                    product_id=product.id,
                    quantity=quantity,
                    unit_price=unit_price,
                    discount_percent=discount_percent,
                    cost_price=product.cost_price
                )
                
                line.calculate_line_total()
                subtotal += line.line_total
                
                db.session.add(line)
            
            sale.subtotal = subtotal
            sale.calculate_totals()
            
            # Handle payment if provided
            if payment_data:
                paid_amount = Decimal(str(payment_data.get('amount', 0)))
                payment_currency = payment_data.get('currency', 'AED')
                payment_exchange_rate = payment_data.get('exchange_rate', 1.0)
                
                # Convert payment to AED
                payment_exchange_decimal = Decimal(str(payment_exchange_rate)) if payment_exchange_rate else Decimal('1')
                paid_amount_aed = (paid_amount * payment_exchange_decimal).quantize(
                    Decimal('0.001'), rounding=ROUND_HALF_UP
                )
                
                # Validate payment amount (in AED)
                if paid_amount_aed < Decimal('0'):
                    raise ValueError('مبلغ الدفع لا يمكن أن يكون سالب')
                
                # Store payment in AED
                sale.paid_amount = paid_amount_aed
                sale.paid_amount_aed = paid_amount_aed
                
                # Handle overpayment (credit to customer)
                if paid_amount_aed > sale.total_amount:
                    overpayment = paid_amount_aed - sale.total_amount
                    customer.balance = (customer.balance or Decimal('0')) + overpayment
                    payment_note = f"\n[دفع زائد] مبلغ {overpayment} AED سُجّل كرصيد للزبون"
                    sale.notes = (sale.notes or '') + payment_note
                
                # Add payment currency info to notes if not AED
                if payment_currency != 'AED':
                    payment_note = f"\n[دفعة] {paid_amount} {payment_currency} = {paid_amount_aed} AED (سعر: {payment_exchange_rate})"
                    sale.notes = (sale.notes or '') + payment_note
            
            sale.calculate_totals()
            
            db.session.flush()
            
            StockService.process_sale_lines(sale)
            
            if payment_data and payment_data.get('amount', 0) > 0:
                payment = SaleService.create_payment_for_sale(
                    sale=sale,
                    amount=payment_data['amount'],
                    payment_method=payment_data['payment_method'],
                    reference_number=payment_data.get('reference_number'),
                    cheque_number=payment_data.get('cheque_number'),
                    cheque_date=payment_data.get('cheque_date'),
                    bank_name=payment_data.get('bank_name'),
                    notes=payment_data.get('notes')
                )
            
            customer.total_purchases += sale.amount_aed
            customer.update_classification()
            
            # Post to General Ledger with proper decimal precision
            try:
                GLService.ensure_core_accounts()
                
                # Calculate COGS with proper decimal precision
                cogs_total = sum(
                    (Decimal(str(line.cost_price)) * Decimal(str(line.quantity)) 
                     for line in sale.lines), 
                    Decimal('0')
                )
                cogs_total_aed = (cogs_total * exchange_rate).quantize(
                    Decimal('0.001'), rounding=ROUND_HALF_UP
                )
                
                # Prepare GL lines with proper decimal precision
                lines = [
                    {
                        'account': '1100', 
                        'debit': sale.amount_aed, 
                        'description': f'فاتورة {sale.sale_number}'
                    },
                    {
                        'account': '4000', 
                        'credit': ((sale.subtotal - sale.discount_amount) * exchange_rate).quantize(
                            Decimal('0.001'), rounding=ROUND_HALF_UP
                        ), 
                        'description': 'إيراد المبيعات'
                    },
                ]
                
                if cogs_total_aed > Decimal('0'):
                    lines.append({
                        'account': '5000', 
                        'debit': cogs_total_aed, 
                        'description': 'تكلفة المبيعات'
                    })
                    lines.append({
                        'account': '1200', 
                        'credit': cogs_total_aed, 
                        'description': 'خصم من المخزون'
                    })
                
                if sale.shipping_cost > Decimal('0'):
                    shipping_aed = (sale.shipping_cost * exchange_rate).quantize(
                        Decimal('0.001'), rounding=ROUND_HALF_UP
                    )
                    lines.append({
                        'account': '4100', 
                        'credit': shipping_aed, 
                        'description': 'إيرادات الشحن'
                    })
                
                if sale.discount_amount > Decimal('0'):
                    discount_aed = (sale.discount_amount * exchange_rate).quantize(
                        Decimal('0.001'), rounding=ROUND_HALF_UP
                    )
                    lines.append({
                        'account': '5200', 
                        'debit': discount_aed, 
                        'description': 'خصومات مبيعات'
                    })
                
                if sale.tax_amount > Decimal('0'):
                    tax_aed = (sale.tax_amount * exchange_rate).quantize(
                        Decimal('0.001'), rounding=ROUND_HALF_UP
                    )
                    lines.append({
                        'account': '2100', 
                        'credit': tax_aed, 
                        'description': 'ضريبة مبيعات مستحقة'
                    })
                
                GLService.post_entry(
                    lines, 
                    description=f'Sale {sale.sale_number}', 
                    reference_type='Sale', 
                    reference_id=sale.id, 
                    currency=sale.currency, 
                    exchange_rate=sale.exchange_rate
                )
            except Exception as e:
                current_app.logger.warning(f'GL posting failed: {e}')

            db.session.commit()
            
            current_app.logger.info(f'Sale created: {sale.sale_number}')
            
            return sale
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Sale creation failed: {e}')
            raise
    
    @staticmethod
    def create_payment_for_sale(sale, amount, payment_method, reference_number=None, 
                                cheque_number=None, cheque_date=None, bank_name=None, notes=None):
        """
        Create a payment for a sale with proper validations
        Uses Decimal for accurate financial calculations
        """
        from utils.helpers import generate_number
        from datetime import datetime, date
        
        # Validate payment amount
        amount_decimal = Decimal(str(amount))
        if amount_decimal <= Decimal('0'):
            raise ValueError('مبلغ الدفع يجب أن يكون أكبر من صفر')
        
        # Validate payment method
        valid_methods = ['cash', 'card', 'bank_transfer', 'cheque', 'e_wallet']
        if payment_method not in valid_methods:
            raise ValueError(f'طريقة الدفع غير صالحة: {payment_method}')
        
        # Validate cheque details if payment method is cheque
        if payment_method == 'cheque':
            if not cheque_number:
                raise ValueError('رقم الشيك مطلوب')
            if not cheque_date:
                raise ValueError('تاريخ الشيك مطلوب')
            if not bank_name:
                raise ValueError('اسم البنك مطلوب')
            
            # Convert cheque_date to date object if it's a string
            if isinstance(cheque_date, str):
                try:
                    cheque_date = datetime.strptime(cheque_date, '%Y-%m-%d').date()
                except ValueError:
                    raise ValueError('تاريخ الشيك غير صالح')
        
        payment_number = generate_number('PAY', Payment, 'payment_number')
        
        # Calculate AED amount with proper rounding
        exchange_rate_decimal = Decimal(str(sale.exchange_rate))
        amount_aed = (amount_decimal * exchange_rate_decimal).quantize(
            Decimal('0.001'), rounding=ROUND_HALF_UP
        )
        
        payment = Payment(
            payment_number=payment_number,
            payment_type='sale',
            sale_id=sale.id,
            customer_id=sale.customer_id,
            amount=amount_decimal,
            currency=sale.currency,
            exchange_rate=exchange_rate_decimal,
            amount_aed=amount_aed,
            payment_method=payment_method,
            reference_number=reference_number,
            cheque_number=cheque_number,
            cheque_date=cheque_date,
            bank_name=bank_name,
            notes=notes,
            user_id=sale.seller_id
        )
        
        db.session.add(payment)
        db.session.flush()
        
        # إنشاء سجل الشيك إذا كانت طريقة الدفع شيك
        if payment_method == 'cheque' and cheque_number:
            from models import Cheque
            cheque = Cheque(
                cheque_number=cheque_number,
                cheque_bank_number=cheque_number,  # نفس رقم الشيك
                cheque_type='incoming',
                customer_id=sale.customer_id,
                amount=amount_decimal,
                currency=sale.currency,
                exchange_rate=exchange_rate_decimal,
                amount_aed=amount_aed,
                issue_date=sale.sale_date.date(),  # تاريخ الإصدار = تاريخ الفاتورة
                due_date=cheque_date,  # تاريخ الاستحقاق
                bank_name=bank_name,
                status='pending',
                notes=notes
            )
            db.session.add(cheque)
            db.session.flush()
            
            # ربط الشيك بالدفعة
            payment.cheque_id = cheque.id
        
        return payment
    
    @staticmethod
    def cancel_sale(sale):
        if sale.status == 'cancelled':
            raise ValueError('الفاتورة ملغاة بالفعل')
        
        sale.status = 'cancelled'
        
        StockService.reverse_sale(sale)
        
        db.session.commit()
        
        current_app.logger.info(f'Sale cancelled: {sale.sale_number}')
    
    @staticmethod
    def update_payment_status(sale):
        """
        Update payment status based on paid amount
        Uses Decimal for accurate comparisons
        """
        paid = Decimal(str(sale.paid_amount)) if sale.paid_amount else Decimal('0')
        total = Decimal(str(sale.total_amount))
        
        balance = (total - paid).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
        
        if balance <= Decimal('0'):
            sale.payment_status = 'paid'
            sale.balance_due = Decimal('0')
        elif paid > Decimal('0'):
            sale.payment_status = 'partial'
            sale.balance_due = balance
        else:
            sale.payment_status = 'unpaid'
            sale.balance_due = total
        
        db.session.commit()

