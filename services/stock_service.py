from decimal import Decimal
from flask import current_app
from flask_login import current_user
from extensions import db
from models import Product, StockMovement, Warehouse


class StockService:
    
    @staticmethod
    def add_stock(product_id, quantity, reference_type=None, reference_id=None, notes=None):
        return StockService.create_movement(
            product_id=product_id,
            quantity=abs(Decimal(str(quantity))),
            movement_type='purchase',
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes
        )
    
    @staticmethod
    def remove_stock(product_id, quantity, reference_type=None, reference_id=None, notes=None):
        return StockService.create_movement(
            product_id=product_id,
            quantity=-abs(Decimal(str(quantity))),
            movement_type='sale',
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes
        )
    
    @staticmethod
    def adjust_stock(product_id, quantity, notes=None):
        return StockService.create_movement(
            product_id=product_id,
            quantity=Decimal(str(quantity)),
            movement_type='adjustment',
            notes=notes
        )
    
    @staticmethod
    def create_movement(product_id, quantity, movement_type, reference_type=None, reference_id=None, notes=None):
        try:
            product = Product.query.get(product_id)
            
            if not product:
                raise ValueError(f'⚠️ المنتج غير موجود (ID: {product_id}).\n💡 تأكد من اختيار منتج صحيح من القائمة.')
            
            warehouse = Warehouse.query.filter_by(is_active=True).first()
            
            if not warehouse:
                warehouse = Warehouse(name='Main Warehouse', name_ar='المستودع الرئيسي', is_active=True)
                db.session.add(warehouse)
                db.session.flush()
            
            movement = StockMovement(
                product_id=product_id,
                warehouse_id=warehouse.id,
                movement_type=movement_type,
                quantity=Decimal(str(quantity)),
                reference_type=reference_type,
                reference_id=reference_id,
                user_id=current_user.id if current_user.is_authenticated else None,
                notes=notes
            )
            
            db.session.add(movement)
            
            product.current_stock += Decimal(str(quantity))
            
            if product.current_stock < 0:
                raise ValueError(f'❌ المخزون غير كافٍ للمنتج "{product.name}"!\n📦 المتوفر: {product.current_stock} | المطلوب: {quantity}\n💡 قلل الكمية أو اطلب مخزون جديد من المورد.')
            
            db.session.flush()
            
            current_app.logger.info(
                f'Stock movement: {movement_type} {quantity} of product #{product_id}'
            )
            
            return movement
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Stock movement failed: {e}')
            raise
    
    @staticmethod
    def process_sale_lines(sale):
        for line in sale.lines:
            StockService.remove_stock(
                product_id=line.product_id,
                quantity=line.quantity,
                reference_type='Sale',
                reference_id=sale.id,
                notes=f'بيع: {sale.sale_number}'
            )
    
    @staticmethod
    def process_purchase_lines(purchase):
        for line in purchase.lines:
            StockService.add_stock(
                product_id=line.product_id,
                quantity=line.quantity,
                reference_type='Purchase',
                reference_id=purchase.id,
                notes=f'شراء: {purchase.purchase_number}'
            )
            
            product = Product.query.get(line.product_id)
            if product:
                product.cost_price = line.unit_cost
    
    @staticmethod
    def reverse_sale(sale):
        for line in sale.lines:
            StockService.add_stock(
                product_id=line.product_id,
                quantity=line.quantity,
                reference_type='Sale-Reversed',
                reference_id=sale.id,
                notes=f'إلغاء بيع: {sale.sale_number}'
            )
    
    @staticmethod
    def check_availability(product_id, quantity):
        product = Product.query.get(product_id)
        
        if not product:
            return False, 'المنتج غير موجود'
        
        if not product.is_active:
            return False, 'المنتج غير نشط'
        
        if product.current_stock < Decimal(str(quantity)):
            return False, f'المخزون غير كافٍ (المتوفر: {product.current_stock})'
        
        return True, 'متوفر'
    
    @staticmethod
    def get_low_stock_products(limit=None):
        query = Product.query.filter(
            Product.is_active == True,
            Product.current_stock <= Product.min_stock_alert
        ).order_by(Product.current_stock.asc())
        
        if limit:
            query = query.limit(limit)
        
        return query.all()
    
    @staticmethod
    def get_out_of_stock_products():
        return Product.query.filter(
            Product.is_active == True,
            Product.current_stock <= 0
        ).all()

