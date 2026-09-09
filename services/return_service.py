from decimal import Decimal, ROUND_HALF_UP
from flask import current_app
from extensions import db
from models import Sale, SaleLine, ProductReturn, ProductReturnLine, Product
from services.stock_service import StockService
from services.gl_service import GLService
from services.tax_engine import TaxEngine
from utils.decorators import get_owned_or_404, get_owned_or_raise
from utils.helpers import generate_number


class ReturnService:

    @staticmethod
    def create_return(sale_id, return_lines_data, user_id=None, notes=None):  # noqa: C901
        """
        Create a product return (Sales Return) with financial and stock updates.

        Args:
            sale_id (int): The ID of the sale being returned.
            return_lines_data (list): List of dicts containing:
                - sale_line_id (int)
                - quantity (float/Decimal)
                - condition (str)
                - notes (str)
            user_id (int): ID of the user processing the return.
            notes (str): General notes for the return.

        Returns:
            ProductReturn: The created return record.
        """
        try:
            # 1. Validate Sale
            sale = get_owned_or_raise(Sale, sale_id)
            if not sale:
                raise ValueError(f"Sale with ID {sale_id} not found.")
            if sale.status == 'cancelled':
                raise ValueError("Cannot create return for a cancelled sale.")

            # 2. Prepare Return Record
            return_number = generate_number('R', ProductReturn, 'return_number')

            product_return = ProductReturn(
                return_number=return_number,
                sale_id=sale.id,
                customer_id=sale.customer_id,
                currency=sale.currency,
                exchange_rate=sale.exchange_rate,
                notes=notes,
                processed_by=user_id,
                status='approved'  # Immediate approval for now
            )

            product_return.total_amount = Decimal('0')
            product_return.refund_amount = Decimal('0')
            product_return.amount_base = Decimal('0')

            db.session.add(product_return)
            db.session.flush()  # Get ID

            total_return_amount = Decimal('0')
            return_line_totals = []
            gl_lines = []

            # GL account routing via central TaxEngine/resolver (literal fallbacks
            # keep today's codes until Agent 1's account_resolution module lands).
            routing = TaxEngine.liability_routing()

            # 3. Process Lines
            for line_data in return_lines_data:
                sale_line_id = line_data.get('sale_line_id')
                quantity = Decimal(str(line_data.get('quantity', 0)))

                if quantity <= 0:
                    continue

                sale_line = get_owned_or_raise(SaleLine, sale_line_id)
                if not sale_line:
                    raise ValueError(f"Sale line {sale_line_id} not found.")
                    raise ValueError(f"Sale line {sale_line_id} does not belong to sale {sale.id}.")

                # Validate Quantity (Cannot return more than sold)
                # Note: This checks total sold. Ideally should check remaining returnable quantity if partial returns exist.
                # For now, let's assume simple validation against line quantity.
                # Future improvement: sum previous returns for this line.
                previous_returned = db.session.query(db.func.sum(ProductReturnLine.quantity))\
                    .join(ProductReturn)\
                    .filter(ProductReturnLine.sale_line_id == sale_line.id)\
                    .scalar() or Decimal('0')

                if (previous_returned + quantity) > sale_line.quantity:
                    raise ValueError(f"Cannot return {quantity} of {sale_line.product.name}. Already returned: {previous_returned}, Sold: {sale_line.quantity}.")  # noqa: E501

                # Calculate refund amount for this line
                # Pro-rata calculation: (Line Total / Quantity) * Return Quantity
                # But usually it's Unit Price * Return Quantity
                unit_price = sale_line.unit_price
                line_total = (unit_price * quantity).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)

                total_return_amount += line_total
                return_line_totals.append(line_total)

                # Create Return Line
                return_line = ProductReturnLine(
                    return_id=product_return.id,
                    sale_line_id=sale_line.id,
                    product_id=sale_line.product_id,
                    quantity=quantity,
                    unit_price=unit_price,
                    line_total=line_total,
                    condition=line_data.get('condition'),
                    notes=line_data.get('notes')
                )
                db.session.add(return_line)

                # Stock Update: Return to Inventory
                # Using 'return' movement type
                StockService.create_movement(
                    product_id=sale_line.product_id,
                    quantity=quantity,
                    movement_type='return',
                    reference_type='ProductReturn',
                    reference_id=product_return.id,
                    notes=f"Return for Sale {sale.sale_number}",
                    warehouse_id=sale.warehouse_id  # Return to same warehouse
                )

                # Prepare COGS Reversal GL Data (Credit COGS, Debit Inventory)
                # Cost basis: the HISTORICAL cost captured on the sale line at
                # sell time. Only legacy lines missing cost_price fall back to
                # the product's current cost.
                product = get_owned_or_404(Product, sale_line.product_id)
                cost_price = sale_line.cost_price
                if cost_price is None and product is not None:
                    cost_price = product.cost_price
                cost_value = (quantity * (Decimal(str(cost_price)) if cost_price else Decimal('0'))).quantize(
                    Decimal('0.001'), rounding=ROUND_HALF_UP
                )

                if cost_value > 0:
                    # Inventory (Asset) - Debit (Increase)
                    gl_lines.append({
                        'account': routing['inventory'],
                        'debit': cost_value,
                        'credit': 0,
                        'description': f'Inventory Restock - {product.name}'
                    })
                    # COGS (Expense) - Credit (Decrease)
                    gl_lines.append({
                        'account': routing['cogs'],
                        'debit': 0,
                        'credit': cost_value,
                        'description': f'COGS Reversal - {product.name}'
                    })

            product_return.calculate_totals()

            # 4. Financial GL Entries (Revenue Reversal)
            # TaxEngine policy: tax is computed PER RETURN LINE then summed,
            # so the reversal mirrors how each line's VAT was accrued.
            # For single-line returns this is numerically identical to the
            # legacy aggregate formula ((net * rate/100).quantize(0.001, HALF_UP)).
            tax_rate = sale.tax_rate or Decimal('0')
            breakdown = TaxEngine.compute_invoice(
                [{'amount': t, 'rate': tax_rate} for t in return_line_totals]
            )

            net_return_amount = breakdown['total_net']  # Excluding tax
            tax_amount = breakdown['total_tax']
            gross_return_amount = breakdown['total_gross']

            product_return.refund_amount = gross_return_amount  # Default to full refund of value

            # Debit Sales Returns/Revenue (reducing revenue)
            gl_lines.append({
                'account': routing['sales_returns'],
                'debit': net_return_amount,
                'credit': 0,
                'description': f'Sales Return Revenue Reversal {sale.sale_number}'
            })

            # Debit Output VAT liability (Reducing liability)
            if tax_amount > 0:
                gl_lines.append({
                    'account': routing['output_vat'],
                    'debit': tax_amount,
                    'credit': 0,
                    'description': f'Sales Return Tax Reversal {sale.sale_number}'
                })

            # Credit Accounts Receivable (Reducing customer debt)
            gl_lines.append({
                'account': GLService.get_customer_credit_account(sale.customer),
                'debit': 0,
                'credit': gross_return_amount,
                'description': f'Credit Customer for Return {sale.sale_number}'
            })

            # Post GL Entry
            if gl_lines:
                GLService.post_entry(
                    lines=gl_lines,
                    description=f'Sales Return {product_return.return_number} for Sale {sale.sale_number}',
                    reference_type='ProductReturn',
                    reference_id=product_return.id,
                    currency=sale.currency,
                    exchange_rate=sale.exchange_rate
                )

            # 5. Settlement (LEAK-GUARD): the lines above always credit AR,
            # but when the invoice was already (fully or partially) paid in
            # cash, that credit would sit as negative AR with no recorded
            # cash outflow and no customer-balance movement.  Split the
            # refund into a cash-out part (Dr AR / Cr Cash + an outgoing
            # refund Payment row) and an AR-credit remainder, then keep
            # paid/balance_due/customer.balance consistent.
            from services.currency_service import CurrencyService
            from models import Payment
            _rate = Decimal(str(sale.exchange_rate or 1))
            if _rate <= 0:
                _rate = Decimal('1')
            refund_base = (gross_return_amount * _rate).quantize(
                Decimal('0.001'), rounding=ROUND_HALF_UP)
            paid_base = Decimal(str(sale.paid_amount_base or 0))
            cash_out_base = min(paid_base, refund_base)
            ar_part_base = refund_base - cash_out_base
            if cash_out_base > 0:
                _ar_acct = GLService.get_customer_credit_account(sale.customer)
                _cash_acct = GLService.get_payment_debit_account('cash')
                GLService.post_entry(
                    [{'account': _ar_acct, 'debit': cash_out_base,
                      'description': f'تسوية مرتجع نقدي {product_return.return_number}'},
                     {'account': _cash_acct, 'credit': cash_out_base,
                      'description': f'صرف مسترد {product_return.return_number}'}],
                    description=f'Cash refund {product_return.return_number} for Sale {sale.sale_number}',
                    reference_type='ProductReturn',
                    reference_id=product_return.id,
                    currency=CurrencyService.get_base_currency(),
                    exchange_rate=1)
                cash_out_txn = (cash_out_base / _rate).quantize(
                    Decimal('0.001'), rounding=ROUND_HALF_UP)
                db.session.add(Payment(
                    payment_number=generate_number('PAY', Payment, 'payment_number'),
                    payment_type='refund', direction='outgoing',
                    sale_id=sale.id, customer_id=sale.customer_id,
                    amount=cash_out_txn, currency=sale.currency,
                    exchange_rate=_rate, amount_base=cash_out_base,
                    payment_method='cash',
                    notes=f'استرداد نقدي للمرتجع {product_return.return_number}',
                    user_id=user_id))
                sale.paid_amount_base = max(
                    Decimal('0'), paid_base - cash_out_base)
                sale.paid_amount = max(
                    Decimal('0'), (Decimal(str(sale.paid_amount or 0))
                                   - cash_out_txn).quantize(
                        Decimal('0.001'), rounding=ROUND_HALF_UP))
            # NOTE: customer.balance is NOT touched here on purpose — it is
            # derived by the Sale after_insert/after_update listener as
            # Σ(amount_base − paid_base) − Σ(approved refunds), which this
            # method keeps consistent via paid_amount_base/balance_due above.
            sale.balance_due = max(
                Decimal('0'), (Decimal(str(sale.balance_due or 0))
                               - ar_part_base).quantize(
                    Decimal('0.001'), rounding=ROUND_HALF_UP))
            _paid_now = Decimal(str(sale.paid_amount_base or 0))
            if sale.balance_due <= 0:
                sale.payment_status = 'paid'
            elif _paid_now > 0:
                sale.payment_status = 'partial'
            else:
                sale.payment_status = 'unpaid'

            db.session.commit()
            return product_return

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to create return: {e}")
            raise e
