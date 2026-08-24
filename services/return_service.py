from decimal import Decimal, ROUND_HALF_UP
from flask import current_app
from extensions import db
from models import Sale, SaleLine, ProductReturn, ProductReturnLine, Product
from services.stock_service import StockService
from services.gl_service import GLService
from utils.helpers import generate_number

class ReturnService:
    
    @staticmethod
    def create_return(sale_id, return_lines_data, user_id=None, notes=None):
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
            sale = db.session.get(Sale, sale_id)
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
            product_return.amount_aed = Decimal('0')
            
            db.session.add(product_return)
            db.session.flush() # Get ID
            
            total_return_amount = Decimal('0')
            gl_lines = []
            
            # 3. Process Lines
            for line_data in return_lines_data:
                sale_line_id = line_data.get('sale_line_id')
                quantity = Decimal(str(line_data.get('quantity', 0)))
                
                if quantity <= 0:
                    continue
                
                sale_line = db.session.get(SaleLine, sale_line_id)
                if not sale_line:
                    raise ValueError(f"Sale line {sale_line_id} not found.")
                
                if sale_line.sale_id != sale.id:
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
                    raise ValueError(f"Cannot return {quantity} of {sale_line.product.name}. Already returned: {previous_returned}, Sold: {sale_line.quantity}.")

                # Calculate refund amount for this line
                # Pro-rata calculation: (Line Total / Quantity) * Return Quantity
                # But usually it's Unit Price * Return Quantity
                unit_price = sale_line.unit_price
                line_total = (unit_price * quantity).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
                
                total_return_amount += line_total
                
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
                    warehouse_id=sale.warehouse_id # Return to same warehouse
                )
                
                # Prepare COGS Reversal GL Data (Credit COGS, Debit Inventory)
                # Need Cost Price. 
                # Ideally, we track cost at time of sale. If not available, use current cost.
                product = db.session.get(Product, sale_line.product_id)
                cost_price = product.cost_price if product else Decimal('0')
                cost_value = (quantity * cost_price).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
                
                if cost_value > 0:
                     # Inventory (Asset) - Debit (Increase)
                    gl_lines.append({
                        'account': '1140', 
                        'debit': cost_value,
                        'credit': 0,
                        'description': f'Inventory Restock - {product.name}'
                    })
                    # COGS (Expense) - Credit (Decrease)
                    gl_lines.append({
                        'account': '5100', 
                        'debit': 0,
                        'credit': cost_value,
                        'description': f'COGS Reversal - {product.name}'
                    })

            product_return.calculate_totals()
            
            # 4. Financial GL Entries (Revenue Reversal)
            # Total Return Amount includes Tax if sale had tax?
            # SaleLine usually stores unit_price * quantity. Tax is usually on top in Sale model.
            # But wait, SaleLine doesn't store tax info usually. Sale stores tax_rate.
            # We need to reverse Tax proportionally.
            
            tax_rate = sale.tax_rate or Decimal('0')
            # If line_total excludes tax (which is standard), then we calculate tax on top.
            
            net_return_amount = total_return_amount # Excluding tax
            tax_amount = (net_return_amount * (tax_rate / Decimal('100'))).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
            gross_return_amount = net_return_amount + tax_amount
            
            product_return.refund_amount = gross_return_amount # Default to full refund of value
            
            # Debit Sales Revenue (or Sales Returns)
            gl_lines.append({
                'account': '4100', # Sales Revenue (Debiting it reduces revenue)
                'debit': net_return_amount,
                'credit': 0,
                'description': f'Sales Return Revenue Reversal {sale.sale_number}'
            })
            
            # Debit Tax Liability (Reducing liability)
            if tax_amount > 0:
                gl_lines.append({
                    'account': '2130', # Taxes Payable
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
                    reference_id=product_return.id
                )
            
            db.session.commit()
            return product_return
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to create return: {e}")
            raise e
