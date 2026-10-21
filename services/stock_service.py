from decimal import Decimal
from flask import current_app
from flask_login import current_user
from extensions import db
from models import Product, StockMovement, Warehouse
from utils.decorators import get_owned_or_raise
from utils.errors import ValidationError


class StockService:

    @staticmethod
    def add_stock(product_id, quantity, reference_type=None, reference_id=None, notes=None, warehouse_id=None):
        return StockService.create_movement(
            product_id=product_id,
            quantity=abs(Decimal(str(quantity))),
            movement_type='purchase',
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            warehouse_id=warehouse_id
        )

    @staticmethod
    def remove_stock(product_id, quantity, reference_type=None, reference_id=None, notes=None, warehouse_id=None):
        return StockService.create_movement(
            product_id=product_id,
            quantity=-abs(Decimal(str(quantity))),
            movement_type='sale',
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            warehouse_id=warehouse_id
        )

    @staticmethod
    def post_adjustment_gl(product, delta, movement):
        """Book the GL side of a manual stock adjustment.

        routes/products.py::adjust_stock moves current_stock and writes its own
        StockMovement row, so it never went through adjust_stock() and the
        journal was never touched: inventory value drifted away from cost with
        no entry to explain it. This is the accounting half, factored out so
        the route does not have to restate the pairing.

        A gain debits inventory and credits the adjustment expense; a loss does
        the reverse. A zero delta is not worth an entry.
        """
        from decimal import Decimal
        from services.gl_service import GLService

        delta = Decimal(str(delta))
        cost = Decimal(str(product.cost_price or 0))
        value = abs(delta) * cost
        if value <= 0:
            return None

        if delta < 0:
            lines = [
                {'account': '5150', 'debit': value, 'credit': 0,
                 'description': f'Inventory Adjustment (Loss) - {product.name}'},
                {'account': '1140', 'debit': 0, 'credit': value,
                 'description': f'Stock Decrease - {product.name}'},
            ]
        else:
            lines = [
                {'account': '1140', 'debit': value, 'credit': 0,
                 'description': f'Stock Increase - {product.name}'},
                {'account': '5150', 'debit': 0, 'credit': value,
                 'description': f'Inventory Adjustment (Gain) - {product.name}'},
            ]

        return GLService.post_entry(
            lines=lines,
            description=f'Stock Adjustment - {product.name}',
            reference_type='stock_adjustment',
            reference_id=movement.id if movement else None,
        )

    @staticmethod
    def adjust_stock(product_id, quantity, notes=None, warehouse_id=None, post_gl=True,
                     reference_type=None, reference_id=None):
        """Adjust stock with an optional GL posting (contract C1).

        Args:
            post_gl (bool): When False the adjustment is a pure stock delta +
                movement row — no GL journal entry is posted at all. Callers
                doing pair transfers (e.g. StockTransfer send/receive) use
                this to avoid double-posting.
            reference_type / reference_id: business reference stored on the
                movement row (e.g. 'Manual Adjustment', 'Product Update').

        LEAK-GUARD (fail-closed): the stock movement and its journal entry
        are one economic fact.  If the entry cannot be posted the movement
        must not survive on its own, so the transaction is rolled back and
        the error is re-raised (same contract as
        services/sale_service.py::create_payment_for_sale).
        """
        movement = StockService.create_movement(
            product_id=product_id,
            quantity=Decimal(str(quantity)),
            movement_type='adjustment',
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            warehouse_id=warehouse_id
        )

        if not post_gl:
            return movement

        # GL Integration for Adjustment
        try:
            product = get_owned_or_raise(Product, product_id, missing_message='المنتج غير موجود')
            entry = StockService.post_adjustment_gl(
                product=product,
                delta=Decimal(str(quantity)),
                movement=movement,
            )
            if entry is None and Decimal(str(quantity)) != 0:
                # لا يوجد قيد لأن تكلفة المنتج صفر/فارغة — التحرك بلا قيمة
                # محاسبية. يُسجَّل تحذير صريح بدل تمرير العملية صامتة.
                current_app.logger.warning(
                    'Stock adjustment of %s for product #%s produced no GL '
                    'entry: the product has no cost price.',
                    quantity, product_id)
        except Exception as e:
            # fail-closed: لا يبقى المخزون متحركاً بلا قيد في الأستاذ.
            db.session.rollback()
            current_app.logger.error(
                f'Failed to post GL entry for stock adjustment '
                f'(product #{product_id}): {e}')
            raise

        return movement

    @staticmethod
    def create_movement(product_id, quantity, movement_type, reference_type=None, reference_id=None, notes=None, warehouse_id=None):  # noqa: C901
        product = get_owned_or_raise(Product, product_id,
                                     missing_message=f'⚠️ المنتج غير موجود (ID: {product_id}).\n💡 تأكد من اختيار منتج صحيح من القائمة.')

        if not product:
            raise ValueError(f'⚠️ المنتج غير موجود (ID: {product_id}).\n💡 تأكد من اختيار منتج صحيح من القائمة.')

        # تحديد المستودع
        if warehouse_id:
            # استخدام المستودع المحدد
            warehouse = Warehouse.query.filter_by(id=warehouse_id, is_active=True).first()
            if not warehouse:
                raise ValueError(f'⚠️ المستودع المحدد غير موجود أو غير نشط (ID: {warehouse_id}).')
        else:
            # البحث عن المستودع الرئيسي أولاً، ثم أول مستودع نشط
            warehouse = Warehouse.query.filter_by(is_active=True, is_main=True).first()
            if not warehouse:
                warehouse = Warehouse.query.filter_by(is_active=True).first()

            # إذا لم يوجد أي مستودع، إنشاء واحد افتراضي
            if not warehouse:
                warehouse = Warehouse(name='Main Warehouse', name_ar='المستودع الرئيسي', is_active=True, is_main=True)
                db.session.add(warehouse)
                db.session.flush()

        try:
            user_id = current_user.id if getattr(current_user, 'is_authenticated', False) else None
        except Exception:
            user_id = None

        quantity_decimal = Decimal(str(quantity))
        available_stock = Decimal(str(product.current_stock or 0))
        resulting_stock = available_stock + quantity_decimal

        # التحقق من المخزون الناتج قبل أي تعديل — الرسالة تعرض المتوفر الفعلي
        # (كانت تعرض الرصيد بعد التعديل فتُربك المستخدم برقم سالب خاطئ)
        if resulting_stock < 0:
            raise ValueError(f'❌ المخزون غير كافٍ للمنتج "{product.name}"!\n📦 المتوفر: {available_stock} | المطلوب: {abs(quantity_decimal)}\n💡 قلل الكمية أو اطلب مخزون جديد من المورد.')  # noqa: E501

        movement = StockMovement(
            product_id=product_id,
            warehouse_id=warehouse.id,
            movement_type=movement_type,
            quantity=quantity_decimal,
            reference_type=reference_type,
            reference_id=reference_id,
            user_id=user_id,
            notes=notes
        )

        db.session.add(movement)

        # Savepoint: a failed flush here must NOT poison the caller's outer
        # transaction — only our own work is rolled back.
        nested = db.session.begin_nested()
        try:
            product.current_stock = resulting_stock
            db.session.flush()
            nested.commit()
        except Exception as flush_error:
            nested.rollback()
            product.current_stock = available_stock
            try:
                db.session.expunge(movement)
            except Exception:
                pass
            current_app.logger.error(f'Stock movement failed: {flush_error}')
            raise

        current_app.logger.info(
            f'Stock movement: {movement_type} {quantity} of product #{product_id}'
        )

        return movement

    @staticmethod
    def process_sale_lines(sale, warehouse_id=None):
        """معالجة بيوع مع خصم من مستودع محدد"""
        # استخدام warehouse_id من sale إذا لم يُمرر
        if not warehouse_id and hasattr(sale, 'warehouse_id'):
            warehouse_id = sale.warehouse_id

        for line in sale.lines:
            StockService.remove_stock(
                product_id=line.product_id,
                quantity=line.quantity,
                reference_type='Sale',
                reference_id=sale.id,
                notes=f'بيع: {sale.sale_number}',
                warehouse_id=warehouse_id  # ← تمرير المستودع
            )

    @staticmethod
    def process_purchase_lines(purchase, warehouse_id=None):
        if not warehouse_id and hasattr(purchase, 'warehouse_id'):
            warehouse_id = purchase.warehouse_id

        for line in purchase.lines:
            StockService.add_stock(
                product_id=line.product_id,
                quantity=line.quantity,
                reference_type='Purchase',
                reference_id=purchase.id,
                notes=f'شراء: {purchase.purchase_number}',
                warehouse_id=warehouse_id
            )

            product = get_owned_or_raise(Product, line.product_id, missing_message='المنتج غير موجود')
            if product:
                # Update cost price in base currency (AED)
                # Ensure we use Decimal for precision
                unit_cost_decimal = Decimal(str(line.unit_cost))
                exchange_rate_decimal = Decimal(str(purchase.exchange_rate))
                cost_in_aed = unit_cost_decimal * exchange_rate_decimal
                product.cost_price = cost_in_aed

    @staticmethod
    def reverse_sale(sale):
        """إلغاء بيع - إرجاع للمستودع الأصلي"""
        # استخدام نفس المستودع الذي تم البيع منه
        warehouse_id = getattr(sale, 'warehouse_id', None)

        for line in sale.lines:
            StockService.add_stock(
                product_id=line.product_id,
                quantity=line.quantity,
                reference_type='Sale-Reversed',
                reference_id=sale.id,
                notes=f'إلغاء بيع: {sale.sale_number}',
                warehouse_id=warehouse_id  # ← نفس المستودع
            )

    @staticmethod
    def get_warehouse_quantity(product_id, warehouse_id):
        """رصيد المنتج في مستودع محدد = المجموع البسيط لكميات حركاته.

        Convention (sign): a StockMovement ALWAYS carries the sign of the
        stock change it represents — a purchase/receipt is positive, a
        sale/issue is negative, an adjustment follows its direction.  The
        plain SUM of the movement quantities of a (product, warehouse) pair
        is therefore the physical quantity in that warehouse, whatever the
        movement_type mix is.  Summing "received − issued" is WRONG because
        the issued movements are already negative (it would add them back).
        """
        from sqlalchemy import func

        total = db.session.query(
            func.coalesce(func.sum(StockMovement.quantity), 0)
        ).filter(
            StockMovement.product_id == product_id,
            StockMovement.warehouse_id == warehouse_id,
        ).scalar()
        return Decimal(str(total or 0))

    @staticmethod
    def get_product_quantity_from_movements(product_id):
        """إجمالي رصيد المنتج من الحركات = مجموع بسيط لكل حركاته."""
        from sqlalchemy import func

        total = db.session.query(
            func.coalesce(func.sum(StockMovement.quantity), 0)
        ).filter(StockMovement.product_id == product_id).scalar()
        return Decimal(str(total or 0))

    @staticmethod
    def check_availability(product_id, quantity, warehouse_id=None):
        """هل الكمية المطلوبة متوفرة؟

        When ``warehouse_id`` is given the check is WAREHOUSE-AWARE: the
        comparison uses the quantity physically present in that warehouse
        (plain sum of its movements) instead of the product's global
        ``current_stock``.  Otherwise a seller could ship stock that sits
        in another warehouse.
        """
        product = get_owned_or_raise(Product, product_id, missing_message='المنتج غير موجود')

        if not product:
            return False, 'المنتج غير موجود'

        if not product.is_active:
            return False, 'المنتج غير نشط'

        requested = Decimal(str(quantity))

        if warehouse_id:
            available_qty = StockService.get_warehouse_quantity(product_id, warehouse_id)
            if available_qty < requested:
                return False, (
                    f'المخزون غير كافٍ في هذا المستودع '
                    f'(المتوفر: {available_qty})')
            return True, 'متوفر'

        if Decimal(str(product.current_stock or 0)) < requested:
            return False, f'المخزون غير كافٍ (المتوفر: {product.current_stock})'

        return True, 'متوفر'

    @staticmethod
    def get_cost_basis(product):
        """أساس تكلفة المنتج (.Decimal) أو None إن لم تكن هناك تكلفة موثوقة.

        A product whose ``cost_price`` is 0 (or NULL) has NO reliable cost
        basis: it cannot produce a COGS entry nor a valuation, so it must
        never be sold silently as a revenue-only document.
        """
        if product is None:
            return None
        raw = getattr(product, 'cost_price', None)
        if raw is None:
            return None
        try:
            cost = Decimal(str(raw))
        except Exception:
            return None
        if cost <= 0:
            return None
        return cost

    @staticmethod
    def require_cost_basis(product, quantity=None):
        """يمنع العملية الصامتة بلا تكلفة (فحص التكلفة قبل البيع).

        Raises:
            ValidationError: باسم المنتج، إن كانت تكلفته صفراً/فارغة.
        """
        cost = StockService.get_cost_basis(product)
        if cost is None:
            name = getattr(product, 'name', None) or 'غير معروف'
            sku = getattr(product, 'sku', None)
            suffix = f' (SKU: {sku})' if sku else ''
            raise ValidationError(
                f'⚠️ المنتج "{name}"{suffix} بلا تكلفة مسجّلة (cost_price = 0). '
                f'لا يمكن بيعه لأن قيد الإيراد لن يقابله قيد تكلفة البضاعة '
                f'ولا تسوية للمخزون.\n'
                f'💡 اضبط تكلفة المنتج في بطاقة المنتج ثم أعد المحاولة.')
        if quantity is not None:
            try:
                if Decimal(str(quantity)) <= 0:
                    raise ValidationError('الكمية يجب أن تكون أكبر من صفر')
            except ValidationError:
                raise
            except Exception:
                pass
        return cost

    @staticmethod
    def get_low_stock_products(limit=None):
        from sqlalchemy import func
        # Handle NULL values safely using coalesce
        query = Product.query.filter(
            Product.is_active.is_(True),
            func.coalesce(Product.current_stock, 0) <= func.coalesce(Product.min_stock_alert, 0)
        ).order_by(Product.current_stock.asc())

        if limit:
            query = query.limit(limit)

        return query.all()

    @staticmethod
    def get_out_of_stock_products():
        from sqlalchemy import func
        return Product.query.filter(
            Product.is_active.is_(True),
            func.coalesce(Product.current_stock, 0) <= 0
        ).all()
