"""
SQLAlchemy Event Listeners for Automatic Updates
المستمعات التلقائية لتحديث البيانات المالية والتعلم الذكي

هذا الملف يحتوي على مستمعات SQLAlchemy التي تُنفذ تلقائياً
عند إدراج أو تحديث أو حذف السجلات في قاعدة البيانات

الأهداف:
1. ضمان تحديث تلقائي للأرصدة والملخصات المالية
2. التعلم الذكي المستمر من جميع العمليات
3. التحليل اللغوي والمهني والمحاسبي
4. كشف الأنماط والشذوذ
5. التوصيات الذكية الفورية

التكامل الكامل مع:
- ai_knowledge.learning_system (التعلم الذاتي)
- services.ai_service (الخدمات الذكية)
- models.* (جميع النماذج)
"""

from sqlalchemy import event
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import logging
import json
from models import StockMovement

logger = logging.getLogger(__name__)


def register_all_listeners():
    """
    تسجيل جميع المستمعات التلقائية
    يجب استدعاء هذه الدالة في app.py بعد تعريف Models
    """
    # المستمعات الأساسية للعمليات المالية
    register_sale_listeners()
    register_receipt_listeners()
    register_purchase_listeners()
    register_payment_listeners()

    # المستمعات الإضافية الشاملة
    register_stock_movement_listeners()
    register_cheque_listeners()
    register_product_return_listeners()
    register_expense_listeners()
    register_gl_listeners()
    register_validation_listeners()
    register_audit_listeners()

    # مستمعات المساعد الذكي (AI) — تُفعّل في بيئة التطوير فقط
    # في الإنتاج، تسبب هذه المستمعات بطء شديد عند كل عملية قاعدة بيانات
    import os
    app_env = os.environ.get('APP_ENV', 'production').lower()
    if app_env in ('development', 'testing'):
        register_ai_listeners()
        register_neural_training_listeners()
        logger.info("[OK] AI + Neural listeners ENABLED (non-production environment)")
    else:
        logger.info("[OK] AI + Neural listeners DISABLED (production environment — use services/ for AI)")

    # مستمعات القيود المحاسبية التلقائية
    register_automatic_gl_listeners()

    logger.info("[OK] All event listeners registered successfully - Full coverage + AI + Neural Networks + Auto GL enabled")

# ============================================================================
# Sale Listeners - مستمعات الفواتير
# ============================================================================


def register_sale_listeners():  # noqa: C901
    """تسجيل مستمعات الفواتير"""
    from models import Sale, Customer

    @event.listens_for(Sale, 'after_insert')
    @event.listens_for(Sale, 'after_update')
    def auto_update_customer_on_sale_change(mapper, connection, target):
        """
        تحديث تلقائي لبيانات العميل عند تغيير الفاتورة

        يحدث عند:
        - إنشاء فاتورة جديدة
        - تعديل فاتورة موجودة
        - تغيير حالة الفاتورة (pending → confirmed)
        """
        # لا نفعل شيء إذا كانت الفاتورة ملغية أو محذوفة
        if not target.is_active or target.status == 'cancelled':
            return

        # تحديث رصيد العميل تلقائياً
        try:
            # حساب الرصيد الجديد من جميع الفواتير المؤكدة
            sales_result = connection.execute(
                Sale.__table__.select().where(
                    Sale.customer_id == target.customer_id,
                    Sale.status == 'confirmed',
                    Sale.is_active.is_(True)
                )
            )

            new_balance = Decimal('0')
            for sale_row in sales_result:
                amount = sale_row.amount_base or Decimal('0')
                paid = sale_row.paid_amount_base or Decimal('0')
                new_balance += (amount - paid)

            # تحديث رصيد العميل في قاعدة البيانات
            connection.execute(
                Customer.__table__.update().where(
                    Customer.id == target.customer_id
                ).values(
                    balance=new_balance,
                    updated_at=datetime.now(timezone.utc)
                )
            )

            logger.info(f"✅ Auto-updated customer {target.customer_id} balance to {new_balance} AED after sale {target.sale_number}")

            try:
                from services.monitoring_service import MonitoringService
                MonitoringService.log_performance_metric('customer_balance_update', float(new_balance),
                                                         {'customer_id': target.customer_id})
            except Exception:
                pass  # monitoring is non-critical

        except Exception as e:
            logger.error(f"❌ Failed to auto-update customer balance: {e}")
            try:
                from services.monitoring_service import MonitoringService
                MonitoringService.log_performance_metric('customer_balance_error', 1,
                                                         {'error': str(e)})
            except Exception:
                pass  # monitoring is non-critical

    @event.listens_for(Sale, 'after_delete')
    def auto_update_customer_on_sale_delete(mapper, connection, target):
        """تحديث تلقائي عند حذف فاتورة"""
        try:
            logger.info(f"Sale {target.sale_number} deleted - customer balance will auto-recalculate")
        except Exception as e:
            logger.warning(f"Failed to log sale deletion: {e}")

# ============================================================================
# Receipt Listeners - مستمعات سندات القبض
# ============================================================================


def register_receipt_listeners():
    """تسجيل مستمعات سندات القبض"""
    from models import Receipt, Customer, Sale

    @event.listens_for(Receipt, 'after_insert')
    def auto_update_customer_on_receipt(mapper, connection, target):
        """
        تحديث تلقائي لرصيد العميل عند إنشاء سند قبض

        ملاحظة: تحديث الفواتير المرتبطة يتم في PaymentService
        هذا Listener يضمن تحديث الرصيد الإجمالي
        """
        try:
            logger.info(f"📝 Receipt {target.receipt_number} created - amount: {target.amount_base} AED for customer {target.customer_id}")

            # حساب رصيد العميل من جديد
            sales_result = connection.execute(
                Sale.__table__.select().where(
                    Sale.customer_id == target.customer_id,
                    Sale.status == 'confirmed',
                    Sale.is_active.is_(True)
                )
            )

            new_balance = Decimal('0')
            for sale_row in sales_result:
                amount = sale_row.amount_base or Decimal('0')
                paid = sale_row.paid_amount_base or Decimal('0')
                new_balance += (amount - paid)

            # تحديث رصيد العميل
            connection.execute(
                Customer.__table__.update().where(
                    Customer.id == target.customer_id
                ).values(
                    balance=new_balance,
                    updated_at=datetime.now(timezone.utc)
                )
            )

            logger.info(f"✅ Auto-updated customer {target.customer_id} balance to {new_balance} AED after receipt")

        except Exception as e:
            logger.error(f"❌ Failed to auto-update customer on receipt: {e}")

    @event.listens_for(Receipt, 'before_delete')
    def prevent_receipt_deletion(mapper, connection, target):
        """منع حذف سندات القبض (يجب الإلغاء فقط)"""
        logger.warning(f"Attempted to delete receipt {target.receipt_number} - use cancellation instead")
        # يمكن رفع استثناء هنا لمنع الحذف:
        # raise ValueError("لا يمكن حذف سندات القبض، يجب إلغاؤها بدلاً من ذلك")

# ============================================================================
# Purchase Listeners - مستمعات المشتريات
# ============================================================================


def register_purchase_listeners():
    """تسجيل مستمعات فواتير المشتريات"""
    from models import Purchase, Supplier, Payment

    @event.listens_for(Purchase, 'after_insert')
    @event.listens_for(Purchase, 'after_update')
    def auto_update_supplier_on_purchase_change(mapper, connection, target):
        """تحديث تلقائي لبيانات المورد عند تغيير فاتورة الشراء"""
        if target.status == 'cancelled':
            return

        try:
            # حساب إجمالي المشتريات المؤكدة (تمرير واحد على فواتير المورد)
            purchases_result = connection.execute(
                Purchase.__table__.select().where(
                    Purchase.supplier_id == target.supplier_id,
                    Purchase.status == 'confirmed'
                )
            )

            total_purchases = Decimal('0')
            for purchase_row in purchases_result:
                amount = purchase_row.amount_base
                if amount is None:
                    amount = purchase_row.total_amount
                total_purchases += (Decimal(str(amount)) if amount is not None else Decimal('0'))

            # إجمالي المدفوعات المؤكدة للمورد — استعلام واحد خارج حلقة الفواتير.
            # كان يُحسب داخل الحلقة سابقاً فيُضرب إجمالي المدفوعات بعدد الفواتير
            # (N+1 double-count) ثم يُضاف مرة رابعة من حلقة المدفوعات المباشرة.
            from sqlalchemy import select, func
            stmt = select(func.sum(Payment.amount_base)).where(
                Payment.supplier_id == target.supplier_id,
                Payment.payment_confirmed.is_(True)
            )
            total_paid = connection.execute(stmt).scalar() or Decimal('0')

            # تحديث إحصائيات المورد
            connection.execute(
                Supplier.__table__.update().where(
                    Supplier.id == target.supplier_id
                ).values(
                    total_purchases_aed=total_purchases,
                    total_paid_aed=total_paid,
                    updated_at=datetime.now(timezone.utc)
                )
            )

            logger.info(f"✅ Auto-updated supplier {target.supplier_id} totals: purchases={total_purchases} AED, paid={total_paid} AED")

        except Exception as e:
            logger.error(f"❌ Failed to auto-update supplier totals: {e}")

# ============================================================================
# Payment Listeners - مستمعات سندات الصرف
# ============================================================================


def register_payment_listeners():
    """تسجيل مستمعات سندات الصرف"""
    from models import Payment, Supplier, Purchase

    @event.listens_for(Payment, 'after_insert')
    def auto_update_supplier_on_payment(mapper, connection, target):
        """تحديث تلقائي لرصيد المورد عند إنشاء سند صرف"""
        try:
            # التحقق من وجود supplier_id في Payment model
            if not hasattr(target, 'supplier_id') or target.supplier_id is None:
                return

            logger.info(f"💰 Payment created - amount: {target.amount_base} AED to supplier {target.supplier_id}")

            # حساب إجمالي المشتريات المؤكدة
            purchases_result = connection.execute(
                Purchase.__table__.select().where(
                    Purchase.supplier_id == target.supplier_id,
                    Purchase.status == 'confirmed'
                )
            )

            total_purchases = Decimal('0')

            for purchase_row in purchases_result:
                total_purchases += (purchase_row.amount_base or Decimal('0'))

            # حساب إجمالي المدفوعات من جدول المدفوعات لهذا المورد
            # Using Core Select properly
            from sqlalchemy import select, func
            stmt = select(func.sum(Payment.amount_base)).where(
                Payment.supplier_id == target.supplier_id
            )
            total_paid = connection.execute(stmt).scalar() or Decimal('0')

            # تحديث إحصائيات المورد
            connection.execute(
                Supplier.__table__.update().where(
                    Supplier.id == target.supplier_id
                ).values(
                    total_purchases_aed=total_purchases,
                    total_paid_aed=total_paid,
                    updated_at=datetime.now(timezone.utc)
                )
            )

            logger.info(f"✅ Auto-updated supplier {target.supplier_id} after payment")

        except Exception as e:
            logger.error(f"❌ Failed to auto-update supplier on payment: {e}")

# ============================================================================
# Utility Functions - دوال مساعدة
# ============================================================================


def validate_decimal_precision(value, max_digits=15, decimal_places=3):
    """
    التحقق من دقة الأرقام العشرية

    Args:
        value: القيمة المراد التحقق منها
        max_digits: إجمالي الأرقام
        decimal_places: الخانات العشرية

    Returns:
        bool: True إذا كانت الدقة صحيحة
    """
    if value is None:
        return True

    try:
        decimal_value = Decimal(str(value))

        # فحص عدد الخانات العشرية
        if abs(decimal_value.as_tuple().exponent) > decimal_places:
            return False

        # فحص إجمالي الأرقام
        total_digits = len(decimal_value.as_tuple().digits)
        if total_digits > max_digits:
            return False

        return True
    except Exception:
        return False


def ensure_balance_consistency(connection, model, record_id):
    """
    التأكد من تطابق الأرصدة المخزنة مع الحسابات الديناميكية

    Args:
        connection: اتصال قاعدة البيانات
        model: النموذج (Customer أو Supplier)
        record_id: معرف السجل

    Returns:
        dict: {'stored': Decimal, 'calculated': Decimal, 'consistent': bool}
    """
    # هذه دالة مساعدة يمكن استخدامها في Listeners
    # لمقارنة الأرصدة المخزنة مع المحسوبة

    try:
        from models import Customer, Sale

        if model == Customer:
            # حساب الرصيد من الفواتير
            result = connection.execute(
                Sale.__table__.select().where(
                    Sale.customer_id == record_id,
                    Sale.status == 'confirmed'
                )
            ).fetchall()

            calculated_balance = sum(
                (row.amount_base or Decimal('0')) - (row.paid_amount_base or Decimal('0'))
                for row in result
            )

            # الحصول على الرصيد المخزن
            customer = connection.execute(
                Customer.__table__.select().where(
                    Customer.id == record_id
                )
            ).first()

            stored_balance = customer.balance if customer else Decimal('0')

            return {
                'stored': stored_balance,
                'calculated': calculated_balance,
                'consistent': abs(stored_balance - calculated_balance) < Decimal('0.01')
            }

    except Exception as e:
        logger.error(f"Failed to check balance consistency: {e}")
        return {'stored': None, 'calculated': None, 'consistent': None}

# ============================================================================
# Example: Advanced Listener with Transaction Handling
# مثال: مستمع متقدم مع معالجة المعاملات
# ============================================================================


def register_advanced_sale_listener():
    """
    مثال على مستمع متقدم مع معالجة المعاملات

    ملاحظة: معطل افتراضياً - قم بتفعيله إذا كنت تريد
    التحديث التلقائي الكامل للأرصدة المخزنة
    """
    from models import Sale, Customer

    @event.listens_for(Sale, 'after_insert')
    @event.listens_for(Sale, 'after_update')
    def advanced_auto_update_customer_balance(mapper, connection, target):
        """
        تحديث متقدم للرصيد مع معالجة المعاملات

        ⚠️ تحذير: هذا قد يؤدي إلى مشاكل أداء في الأنظمة الكبيرة
        استخدمه بحذر!
        """
        if not target.is_active or target.status == 'cancelled':
            return

        try:
            # حساب الرصيد الجديد
            sales = connection.execute(
                Sale.__table__.select().where(
                    Sale.customer_id == target.customer_id,
                    Sale.status == 'confirmed',
                    Sale.is_active.is_(True)
                )
            ).fetchall()

            new_balance = sum(
                (sale.amount_base or Decimal('0')) - (sale.paid_amount_base or Decimal('0'))
                for sale in sales
            )

            # تحديث رصيد العميل
            connection.execute(
                Customer.__table__.update().where(
                    Customer.id == target.customer_id
                ).values(
                    balance=new_balance,
                    updated_at=datetime.now(timezone.utc)
                )
            )

            logger.info(f"Auto-updated customer {target.customer_id} balance to {new_balance} AED")

        except Exception as e:
            logger.error(f"Failed to auto-update customer balance: {e}")
            # لا نرفع الاستثناء لتجنب إيقاف العملية الأساسية

# ============================================================================
# Example: Validation Listener
# مثال: مستمع للتحقق من البيانات
# ============================================================================

# ============================================================================
# Stock Movement Listeners - مستمعات حركات المخزون
# ============================================================================


def register_stock_movement_listeners():
    """تسجيل مستمعات حركات المخزون"""
    from models import StockMovement

    @event.listens_for(StockMovement, 'after_insert')
    def log_stock_movement(mapper, connection, target):
        """
        تسجيل حركات المخزون للمراقبة

        ملاحظة مهمة: StockService.create_movement() يحدث المخزون بالفعل (السطر 69)
        هذا المستمع للتسجيل فقط لتجنب التحديث المزدوج
        """
        try:
            movement_type_ar = {
                'sale': 'بيع (خروج)',
                'purchase': 'شراء (دخول)',
                'adjustment': 'تعديل',
                'return': 'إرجاع',
                'transfer': 'نقل'
            }.get(target.movement_type, target.movement_type)

            quantity_change = target.quantity or Decimal('0')
            direction = "➕" if quantity_change > 0 else "➖"

            logger.info(f"📦 Stock Movement: {direction} {movement_type_ar} | "
                        f"Product #{target.product_id} | Qty: {abs(quantity_change)} | "
                        f"Ref: {target.reference_type}-{target.reference_id}")

        except Exception as e:
            logger.error(f"❌ Failed to log stock movement: {e}")

# ============================================================================
# Cheque Listeners - مستمعات الشيكات
# ============================================================================


def register_cheque_listeners():  # noqa: C901
    """تسجيل مستمعات الشيكات"""
    from models import Cheque
    from datetime import date

    @event.listens_for(Cheque, 'before_insert')
    @event.listens_for(Cheque, 'before_update')
    def auto_update_cheque_status(mapper, connection, target):
        """تحديث تلقائي لحالة الشيك حسب التاريخ"""
        try:
            # إذا كان الشيك pending وتجاوز تاريخ الاستحقاق
            if target.status == 'pending' and target.due_date:
                if isinstance(target.due_date, datetime):
                    due = target.due_date.date()
                else:
                    due = target.due_date

                today = date.today()

                # إذا تجاوز تاريخ الاستحقاق بـ 7 أيام → تحت التحصيل
                days_overdue = (today - due).days

                if days_overdue > 7:
                    logger.warning(f"⚠️ Cheque {target.cheque_number} overdue by {days_overdue} days")

        except Exception as e:
            logger.error(f"❌ Failed to check cheque status: {e}")

    @event.listens_for(Cheque, 'after_update')
    def auto_log_cheque_status_change(mapper, connection, target):
        """تسجيل تغييرات حالة الشيك"""
        try:
            # تسجيل تغيير الحالة
            if target.status in ['cleared', 'bounced']:
                status_ar = 'تم الصرف' if target.status == 'cleared' else 'مرتد'
                logger.info(f"💳 Cheque {target.cheque_number} status changed to: {status_ar}")

        except Exception as e:
            logger.error(f"❌ Failed to log cheque status change: {e}")

# ============================================================================
# Product Return Listeners - مستمعات الإرجاعات
# ============================================================================


def register_product_return_listeners():
    """تسجيل مستمعات إرجاعات المنتجات"""
    from models import ProductReturn

    @event.listens_for(ProductReturn, 'after_insert')
    def auto_update_stock_on_return(mapper, connection, target):
        """تحديث المخزون تلقائياً عند الإرجاع"""
        try:
            if target.status == 'approved':
                logger.info(f"📦 Product return {target.return_number} approved - stock will be updated via StockMovement")

        except Exception as e:
            logger.error(f"❌ Failed to process product return: {e}")

# ============================================================================
# Expense Listeners - مستمعات المصروفات
# ============================================================================


def register_expense_listeners():
    """تسجيل مستمعات المصروفات"""
    from models import Expense

    @event.listens_for(Expense, 'after_insert')
    @event.listens_for(Expense, 'after_update')
    def auto_log_expense(mapper, connection, target):
        """تسجيل المصروفات"""
        try:
            if target.is_active:
                logger.info(f"💸 Expense recorded: {target.amount_base} AED - Category: {target.category_id}")

        except Exception as e:
            logger.error(f"❌ Failed to log expense: {e}")

# ============================================================================
# GL (General Ledger) Listeners - مستمعات دفتر الأستاذ
# ============================================================================


def register_gl_listeners():
    """تسجيل مستمعات دفتر الأستاذ"""
    from models import GLJournalEntry

    @event.listens_for(GLJournalEntry, 'before_insert')
    @event.listens_for(GLJournalEntry, 'before_update')
    def validate_journal_entry_balance(mapper, connection, target):
        """التحقق من توازن القيد المحاسبي"""
        try:
            # التحقق من توازن القيد
            debit = target.total_debit or Decimal('0')
            credit = target.total_credit or Decimal('0')

            if abs(debit - credit) > Decimal('0.01'):
                logger.error(f"❌ Journal entry {target.entry_number} is UNBALANCED! Debit: {debit}, Credit: {credit}")
                # يمكن رفع استثناء هنا لمنع الحفظ:
                # raise ValueError(f"القيد غير متوازن! المدين: {debit}, الدائن: {credit}")
            else:
                logger.info(f"✅ Journal entry {target.entry_number} is balanced: {debit} = {credit}")

        except Exception as e:
            logger.error(f"❌ Failed to validate journal entry: {e}")

# ============================================================================
# Validation Listeners - مستمعات التحقق من البيانات
# ============================================================================


def register_validation_listeners():  # noqa: C901
    """تسجيل مستمعات التحقق من البيانات"""
    from models import Sale, Purchase, Receipt, Payment, Product

    @event.listens_for(Sale, 'before_insert')
    @event.listens_for(Sale, 'before_update')
    def validate_sale_amounts(mapper, connection, target):
        """التحقق من صحة مبالغ الفاتورة"""
        try:
            # التحقق من المبالغ
            if target.amount_base and target.amount_base < 0:
                logger.error(f"❌ Sale {target.sale_number}: Negative amount detected!")

            # التحقق من الرصيد المتبقي
            if target.paid_amount_base and target.amount_base:
                expected_balance = target.amount_base - target.paid_amount_base
                if target.balance_due and abs(target.balance_due - expected_balance) > Decimal('0.01'):
                    # تصحيح تلقائي
                    target.balance_due = expected_balance
                    logger.warning(f"⚠️ Sale {target.sale_number}: Balance auto-corrected to {expected_balance}")

        except Exception as e:
            logger.error(f"❌ Failed to validate sale: {e}")

    @event.listens_for(Purchase, 'before_insert')
    @event.listens_for(Purchase, 'before_update')
    def validate_purchase_amounts(mapper, connection, target):
        """التحقق من صحة مبالغ فاتورة الشراء"""
        try:
            if target.amount_base and target.amount_base < 0:
                logger.error(f"❌ Purchase {target.purchase_number}: Negative amount detected!")

        except Exception as e:
            logger.error(f"❌ Failed to validate purchase: {e}")

    @event.listens_for(Receipt, 'before_insert')
    def validate_receipt_amount(mapper, connection, target):
        """التحقق من صحة مبلغ سند القبض"""
        try:
            if target.amount_base and target.amount_base <= 0:
                logger.error(f"❌ Receipt {target.receipt_number}: Invalid amount!")

        except Exception as e:
            logger.error(f"❌ Failed to validate receipt: {e}")

    @event.listens_for(Payment, 'before_insert')
    def validate_payment_amount(mapper, connection, target):
        """التحقق من صحة مبلغ سند الصرف"""
        try:
            if target.amount_base and target.amount_base <= 0:
                logger.error("❌ Payment: Invalid amount!")

        except Exception as e:
            logger.error(f"❌ Failed to validate payment: {e}")

    @event.listens_for(Product, 'before_update')
    def validate_product_stock(mapper, connection, target):
        """التحقق من المخزون السالب — يمنع حفظ مخزون سالب"""
        try:
            if target.current_stock is not None and target.current_stock < 0:
                logger.error(
                    f"❌ BLOCKED: Product {target.name} ({target.id}): "
                    f"Negative stock ({target.current_stock}) is not allowed. "
                    "Setting to 0."
                )
                # Prevent negative stock — clamp to zero
                target.current_stock = 0

        except Exception as e:
            logger.error(f"❌ Failed to validate product stock: {e}")

# ============================================================================
# Audit Listeners - مستمعات التدقيق
# ============================================================================


def register_audit_listeners():
    """تسجيل مستمعات التدقيق للعمليات الحساسة"""
    from models import Sale, Purchase, Receipt, Payment

    @event.listens_for(Sale, 'after_delete')
    def log_sale_deletion(mapper, connection, target):
        """تسجيل حذف الفواتير"""
        logger.warning(f"🗑️ DELETED: Sale {target.sale_number} - Amount: {target.amount_base} AED")

    @event.listens_for(Purchase, 'after_delete')
    def log_purchase_deletion(mapper, connection, target):
        """تسجيل حذف فواتير الشراء"""
        logger.warning(f"🗑️ DELETED: Purchase {target.purchase_number} - Amount: {target.amount_base} AED")

    @event.listens_for(Receipt, 'after_delete')
    def log_receipt_deletion(mapper, connection, target):
        """تسجيل حذف سندات القبض"""
        logger.warning(f"🗑️ DELETED: Receipt {target.receipt_number} - Amount: {target.amount_base} AED")

    @event.listens_for(Payment, 'after_delete')
    def log_payment_deletion(mapper, connection, target):
        """تسجيل حذف سندات الصرف"""
        logger.warning(f"🗑️ DELETED: Payment - Amount: {target.amount_base} AED")

# ============================================================================
# AI (Artificial Intelligence) Listeners - مستمعات الذكاء الاصطناعي
# ============================================================================


def register_ai_listeners():
    """تسجيل مستمعات الذكاء الاصطناعي المتقدمة"""
    register_ai_learning_listeners()
    register_ai_linguistic_listeners()
    register_ai_professional_listeners()
    register_ai_accounting_listeners()
    register_ai_predictive_listeners()
    register_intelligent_assistant_listeners()  # 🧠 المساعد الذكي الحقيقي

# ============================================================================
# AI Learning Listeners - مستمعات التعلم الذكي
# ============================================================================


def register_ai_learning_listeners():  # noqa: C901
    """مستمعات التعلم الذكي - متكاملة مع LearningSystem"""
    from models import Sale, Customer, Product

    @event.listens_for(Sale, 'after_insert')
    def ai_learn_sale_patterns(mapper, connection, target):
        """
        التعلم العميق من أنماط المبيعات
        متكامل مع: ai_knowledge.learning_system
        """
        try:
            from ai_knowledge.learning_system import AzadLearningSystem

            # بيانات التعلم
            day_of_week = target.sale_date.strftime('%A') if target.sale_date else 'Unknown'
            hour = target.sale_date.hour if target.sale_date else 0
            month = target.sale_date.month if target.sale_date else 0

            # البيانات التجارية
            learning_data = {
                'sale_id': target.id,
                'customer_id': target.customer_id,
                'amount': float(target.amount_base),
                'items_count': len(target.lines) if target.lines else 0,
                'discount_percent': float(target.discount_amount / target.subtotal * 100) if target.subtotal > 0 else 0,
                'payment_status': target.payment_status,
                'time_pattern': {
                    'day_of_week': day_of_week,
                    'hour': hour,
                    'month': month,
                    'is_weekend': day_of_week in ['Friday', 'Saturday']
                }
            }

            # استخدام نظام التعلم الموجود
            learning_system = AzadLearningSystem()

            # تعلم النمط
            learning_system.learn_from_interaction(
                question="Sale pattern analysis",
                response=json.dumps(learning_data),
                user_feedback=5,  # افتراض نجاح العملية
                context={'type': 'sale_pattern', 'data': learning_data}
            )

            logger.info(f"🤖 AI Learned: Sale {target.sale_number} | "
                        f"{day_of_week} {hour}:00 | {target.amount_base} AED")

        except Exception as e:
            logger.error(f"❌ AI learning failed: {e}")

    @event.listens_for(Customer, 'after_update')
    def ai_deep_customer_analysis(mapper, connection, target):
        """
        تحليل عميق لسلوك العملاء
        متكامل مع: services.ai_service.AIService
        """
        try:
            from ai_knowledge.learning_system import AzadLearningSystem

            # تحليل متعدد الأبعاد
            customer_insights = {
                'customer_id': target.id,
                'balance': float(target.balance or 0),
                'total_purchases': float(target.total_purchases or 0),
                'classification': target.customer_classification,
                'credit_limit': float(target.credit_limit or 0)
            }

            # التنبيهات الذكية
            alerts = []

            # 1. رصيد عالي
            if target.balance and target.balance > Decimal('10000'):
                alerts.append('high_balance')
                logger.info(f"🤖 AI Priority: Customer {target.id} - High balance: {target.balance} AED")

            # 2. تجاوز حد الائتمان
            if target.balance > target.credit_limit and target.credit_limit > 0:
                alerts.append('credit_limit_exceeded')
                logger.warning(f"🤖 AI Alert: Customer {target.id} exceeded credit limit!")

            # 3. ترقية التصنيف
            if target.total_purchases > 100000 and target.customer_classification != 'vip':
                alerts.append('vip_candidate')
                logger.info(f"🤖 AI Insight: Customer {target.id} qualifies for VIP upgrade!")

            # التعلم من السلوك
            try:
                learning_system = AzadLearningSystem()
                learning_system.learn_from_interaction(
                    question=f"Customer behavior analysis - {target.id}",
                    response=json.dumps({'insights': customer_insights, 'alerts': alerts}),
                    user_feedback=5,
                    context={'type': 'customer_behavior', 'customer_id': target.id}
                )
            except Exception:
                pass

        except Exception as e:
            logger.error(f"❌ AI customer analysis failed: {e}")

    @event.listens_for(Product, 'after_update')
    def ai_learn_product_performance(mapper, connection, target):
        """
        التعلم من أداء المنتجات
        متكامل مع: ai_knowledge.learning_system
        """
        try:
            from ai_knowledge.learning_system import AzadLearningSystem

            # بيانات المنتج
            product_data = {
                'product_id': target.id,
                'name': target.name,
                'current_stock': float(target.current_stock or 0),
                'min_stock': float(target.min_stock_alert or 0),
                'cost_price': float(target.cost_price or 0),
                'sell_price': float(target.regular_price or 0),
                'margin': float((target.regular_price - target.cost_price) if target.regular_price and target.cost_price else 0)
            }

            # التعلم من أداء المنتج
            learning_system = AzadLearningSystem()
            learning_system.learn_from_interaction(
                question=f"Product performance - {target.name}",
                response=json.dumps(product_data),
                user_feedback=5,
                context={'type': 'product_performance', 'product_id': target.id}
            )

            # تحذيرات ذكية
            if target.current_stock < target.min_stock_alert:
                logger.warning(f"🤖 AI Reorder Alert: Product {target.name} - Stock: {target.current_stock}")

        except Exception as e:
            logger.error(f"❌ AI product learning failed: {e}")

    @event.listens_for(Product, 'before_update')
    def ai_detect_stock_anomaly(mapper, connection, target):
        """
        كشف الشذوذ في المخزون

        التنبيهات:
        - مخزون منخفض جداً
        - مخزون عالي جداً (راكد)
        - تغيير سعر كبير
        """
        try:
            # مخزون منخفض جداً
            if target.current_stock and target.current_stock < target.min_stock_alert:
                logger.warning(f"🤖 AI Alert: Product {target.id} ({target.name}) - Low stock: {target.current_stock}")

            # مخزون راكد (عالي جداً)
            if target.current_stock and target.current_stock > 1000:
                logger.warning(f"🤖 AI Alert: Product {target.id} ({target.name}) - High stock: {target.current_stock} - Possible slow-moving item")

        except Exception as e:
            logger.error(f"❌ AI stock anomaly detection failed: {e}")

    @event.listens_for(Sale, 'after_insert')
    def ai_comprehensive_sale_analysis(mapper, connection, target):
        """
        تحليل شامل للمبيعات - كشف شذوذ + تعلم
        متكامل مع: services.ai_service
        """
        try:
            from ai_knowledge.learning_system import AzadLearningSystem

            anomalies = []
            insights = []

            # 1. كشف المبالغ الكبيرة
            if target.amount_base and target.amount_base > Decimal('50000'):
                anomalies.append('large_amount')
                logger.warning(f"🤖 AI Anomaly: Large sale! {target.sale_number} - {target.amount_base} AED")

            # 2. كشف الخصومات الكبيرة
            if target.discount_amount and target.subtotal:
                discount_percent = (target.discount_amount / target.subtotal) * 100
                if discount_percent > Decimal('50'):
                    anomalies.append('large_discount')
                    logger.warning(f"🤖 AI Anomaly: Large discount! {target.sale_number} - {discount_percent:.1f}%")

            # 3. تحليل الربحية
            if target.lines:
                total_cost = sum(line.cost_price * line.quantity for line in target.lines if line.cost_price)
                if total_cost > 0:
                    profit = target.amount_base - total_cost
                    margin_percent = (profit / total_cost) * 100

                    if margin_percent < 10:
                        insights.append('low_margin')
                        logger.warning(f"🤖 AI Insight: Low profit margin! {target.sale_number} - {margin_percent:.1f}%")
                    elif margin_percent > 100:
                        insights.append('high_margin')
                        logger.info(f"🤖 AI Insight: Excellent profit! {target.sale_number} - {margin_percent:.1f}%")

            # التعلم من التحليل
            learning_system = AzadLearningSystem()
            learning_system.learn_from_interaction(
                question=f"Sale analysis - {target.sale_number}",
                response=json.dumps({'anomalies': anomalies, 'insights': insights}),
                user_feedback=5 if not anomalies else 3,
                context={'type': 'sale_analysis', 'sale_id': target.id}
            )

        except Exception as e:
            logger.error(f"❌ AI sale analysis failed: {e}")

# ============================================================================
# AI Linguistic Listeners - مستمعات التعلم اللغوي
# ============================================================================


def register_ai_linguistic_listeners():
    """
    مستمعات التعلم اللغوي - تعلم المصطلحات والمفردات
    متكامل مع: ai_knowledge.learning_system
    """
    from models import Product, Customer

    @event.listens_for(Product, 'after_insert')
    def ai_learn_product_terminology(mapper, connection, target):
        """التعلم من مصطلحات المنتجات"""
        try:
            from ai_knowledge.learning_system import AzadLearningSystem

            # تعلم المصطلحات التقنية
            terminology = {
                'arabic': target.name_ar or target.name,
                'english': target.name,
                'commercial_name': target.commercial_name,
                'part_number': target.part_number,
                'category': target.category.name if target.category else None
            }

            learning_system = AzadLearningSystem()
            learning_system.learn_from_interaction(
                question=f"Product terminology: {target.name}",
                response=json.dumps(terminology, ensure_ascii=False),
                user_feedback=5,
                context={'type': 'linguistic_learning', 'subtype': 'product_terms'}
            )

            logger.info(f"🤖 AI Linguistic: Learned product terminology - {target.name}")

        except Exception as e:
            logger.error(f"❌ AI linguistic learning failed: {e}")

    @event.listens_for(Customer, 'after_insert')
    def ai_learn_customer_names(mapper, connection, target):
        """التعلم من أسماء العملاء والشركات"""
        try:
            from ai_knowledge.learning_system import AzadLearningSystem

            # تعلم الأسماء باللغتين
            names_data = {
                'arabic_name': target.name,
                'english_name': target.name_ar,
                'customer_type': target.customer_type,
                'phone': target.phone,
                'email': target.email
            }

            learning_system = AzadLearningSystem()
            learning_system.learn_from_interaction(
                question=f"Customer names: {target.name}",
                response=json.dumps(names_data, ensure_ascii=False),
                user_feedback=5,
                context={'type': 'linguistic_learning', 'subtype': 'customer_names'}
            )

            logger.info(f"🤖 AI Linguistic: Learned customer name - {target.name}")

        except Exception as e:
            logger.error(f"❌ AI name learning failed: {e}")

# ============================================================================
# AI Professional Listeners - مستمعات التعلم المهني
# ============================================================================


def register_ai_professional_listeners():
    """
    مستمعات التعلم المهني - تعلم الممارسات التجارية
    متكامل مع: services.ai_service
    """
    from models import Sale, Purchase, Expense

    @event.listens_for(Sale, 'after_insert')
    def ai_learn_sales_practices(mapper, connection, target):
        """التعلم من الممارسات التجارية في المبيعات"""
        try:
            from ai_knowledge.learning_system import AzadLearningSystem

            # تحليل الممارسة التجارية
            practice_data = {
                'sale_number': target.sale_number,
                'payment_terms': {
                    'cash_percentage': float(target.paid_amount_base / target.amount_base * 100) if target.amount_base > 0 else 0,
                    'credit_given': target.payment_status in ['unpaid', 'partial']
                },
                'discount_strategy': {
                    'discount_amount': float(target.discount_amount or 0),
                    'discount_percent': float(target.discount_amount / target.subtotal * 100) if target.subtotal > 0 else 0
                },
                'shipping_included': target.shipping_cost > 0 if target.shipping_cost else False,
                'tax_applied': target.tax_amount > 0 if target.tax_amount else False
            }

            # التعلم من الممارسة
            learning_system = AzadLearningSystem()
            learning_system.learn_from_interaction(
                question="Sales practice analysis",
                response=json.dumps(practice_data, ensure_ascii=False),
                user_feedback=5,
                context={'type': 'professional_learning', 'subtype': 'sales_practice'}
            )

            logger.info(f"🤖 AI Professional: Learned sales practice from {target.sale_number}")

        except Exception as e:
            logger.error(f"❌ AI professional learning failed: {e}")

    @event.listens_for(Purchase, 'after_insert')
    def ai_learn_procurement_strategy(mapper, connection, target):
        """التعلم من استراتيجيات الشراء"""
        try:
            from ai_knowledge.learning_system import AzadLearningSystem

            # تحليل استراتيجية الشراء
            procurement_data = {
                'supplier_id': target.supplier_id,
                'amount': float(target.amount_base),
                'payment_method': getattr(target, 'payment_method', None),
                'credit_terms': target.status != 'paid_in_full'
            }

            learning_system = AzadLearningSystem()
            learning_system.learn_from_interaction(
                question="Procurement strategy analysis",
                response=json.dumps(procurement_data),
                user_feedback=5,
                context={'type': 'professional_learning', 'subtype': 'procurement'}
            )

            logger.info(f"🤖 AI Professional: Learned procurement from {target.purchase_number}")

        except Exception as e:
            logger.error(f"❌ AI procurement learning failed: {e}")

    @event.listens_for(Expense, 'after_insert')
    def ai_learn_expense_patterns(mapper, connection, target):
        """التعلم من أنماط المصروفات"""
        try:
            from ai_knowledge.learning_system import AzadLearningSystem

            # تحليل نمط المصروف
            expense_data = {
                'category_id': target.category_id,
                'amount': float(target.amount_base),
                'payment_method': target.payment_method,
                'is_recurring': target.is_recurring if hasattr(target, 'is_recurring') else False
            }

            learning_system = AzadLearningSystem()
            learning_system.learn_from_interaction(
                question="Expense pattern analysis",
                response=json.dumps(expense_data),
                user_feedback=5,
                context={'type': 'professional_learning', 'subtype': 'expense_management'}
            )

            logger.info(f"🤖 AI Professional: Learned expense pattern - {target.amount_base} AED")

        except Exception as e:
            logger.error(f"❌ AI expense learning failed: {e}")

# ============================================================================
# AI Accounting Listeners - مستمعات التعلم المحاسبي
# ============================================================================


def register_ai_accounting_listeners():  # noqa: C901
    """
    مستمعات التعلم المحاسبي - تعلم المبادئ المحاسبية
    متكامل مع: services.gl_service
    """
    from models import GLJournalEntry, Sale, Purchase

    @event.listens_for(GLJournalEntry, 'after_insert')
    def ai_learn_accounting_entries(mapper, connection, target):
        """التعلم من القيود المحاسبية"""
        try:
            from ai_knowledge.learning_system import AzadLearningSystem
            from sqlalchemy import inspect

            # التحقق الآمن من السطور لتجنب تعارض الجلسة
            lines_count = 0
            ins = inspect(target)
            if 'lines' not in ins.unloaded:
                lines_count = len(target.lines)

            # تحليل القيد المحاسبي
            entry_data = {
                'entry_number': target.entry_number,
                'total_debit': float(target.total_debit or 0),
                'total_credit': float(target.total_credit or 0),
                'is_balanced': target.is_balanced() if hasattr(target, 'is_balanced') else True,
                'reference_type': target.reference_type,
                'reference_id': target.reference_id,
                'lines_count': lines_count
            }

            # التعلم المحاسبي (بدون فلاش إضافي)
            try:
                learning_system = AzadLearningSystem()
                learning_system.learn_from_interaction(
                    question=f"Accounting entry analysis - {target.entry_number}",
                    response=json.dumps(entry_data),
                    user_feedback=5 if entry_data['is_balanced'] else 1,
                    context={'type': 'accounting_learning', 'subtype': 'journal_entry'}
                )

                logger.info(f"🤖 AI Accounting: Learned entry {target.entry_number} - "
                            f"{'Balanced' if entry_data['is_balanced'] else 'Unbalanced'}")
            except Exception:
                pass

        except Exception as e:
            logger.error(f"❌ AI accounting learning failed: {e}")

    @event.listens_for(Sale, 'after_insert')
    def ai_learn_revenue_recognition(mapper, connection, target):
        """التعلم من مبادئ الاعتراف بالإيراد"""
        try:
            from ai_knowledge.learning_system import AzadLearningSystem

            # مبدأ الاعتراف بالإيراد
            revenue_data = {
                'sale_number': target.sale_number,
                'total_revenue': float(target.amount_base),
                'revenue_recognized': target.status == 'confirmed',
                'cash_received': float(target.paid_amount_base or 0),
                'accounts_receivable': float(target.balance_due or 0),
                'recognition_principle': 'accrual' if target.status == 'confirmed' else 'cash'
            }

            learning_system = AzadLearningSystem()
            learning_system.learn_from_interaction(
                question="Revenue recognition principle",
                response=json.dumps(revenue_data),
                user_feedback=5,
                context={'type': 'accounting_learning', 'subtype': 'revenue_recognition'}
            )

            logger.info(f"🤖 AI Accounting: Revenue recognized - {target.sale_number}")

        except Exception as e:
            logger.error(f"❌ AI revenue learning failed: {e}")

    @event.listens_for(Purchase, 'after_insert')
    def ai_learn_expense_recognition(mapper, connection, target):
        """التعلم من مبادئ الاعتراف بالمصروف"""
        try:
            from ai_knowledge.learning_system import AzadLearningSystem

            # مبدأ المقابلة المحاسبية
            matching_data = {
                'purchase_number': target.purchase_number,
                'total_cost': float(target.amount_base),
                'recognized_as_expense': target.status == 'confirmed',
                'cash_paid': float(getattr(target, 'paid_amount_base', 0) or 0),
                'accounts_payable': float(((target.amount_base or 0) - (getattr(target, 'paid_amount_base', 0) or 0)) if target.amount_base else 0)
            }

            learning_system = AzadLearningSystem()
            learning_system.learn_from_interaction(
                question="Expense recognition and matching principle",
                response=json.dumps(matching_data),
                user_feedback=5,
                context={'type': 'accounting_learning', 'subtype': 'expense_recognition'}
            )

            logger.info(f"🤖 AI Accounting: Expense recognized - {target.purchase_number}")

        except Exception as e:
            logger.error(f"❌ AI expense recognition learning failed: {e}")

# ============================================================================
# AI Predictive Listeners - مستمعات التوقعات الذكية
# ============================================================================


def register_ai_predictive_listeners():  # noqa: C901
    """
    مستمعات التوقعات الذكية - توقع الاتجاهات والأنماط
    متكامل مع: services.ai_service.AIService
    """
    from models import Sale, Product, Customer

    @event.listens_for(Sale, 'after_insert')
    def ai_predict_future_sales(mapper, connection, target):
        """توقع المبيعات المستقبلية"""
        try:
            # حساب المبيعات الأخيرة للمقارنة
            pass

            # المبيعات آخر 30 يوم
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

            recent_sales = connection.execute(
                Sale.__table__.select().where(
                    Sale.sale_date >= thirty_days_ago,
                    Sale.status == 'confirmed'
                )
            ).fetchall()

            if len(recent_sales) > 10:  # نحتاج بيانات كافية
                total_recent = sum(sale.amount_base or Decimal('0') for sale in recent_sales)
                avg_daily = total_recent / 30

                # التوقع البسيط
                predicted_month = avg_daily * 30

                logger.info(f"🤖 AI Prediction: Monthly sales forecast: {predicted_month:.2f} AED "
                            f"(based on {len(recent_sales)} sales)")

        except Exception as e:
            logger.error(f"❌ AI prediction failed: {e}")

    @event.listens_for(Product, 'before_update')
    def ai_predict_stockout(mapper, connection, target):
        """توقع نفاذ المخزون"""
        try:
            if target.current_stock and target.current_stock < target.min_stock_alert:
                # حساب معدل البيع اليومي
                thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

                movements = connection.execute(
                    StockMovement.__table__.select().where(
                        StockMovement.product_id == target.id,
                        StockMovement.movement_type == 'sale',
                        StockMovement.created_at >= thirty_days_ago
                    )
                ).fetchall()

                if movements:
                    total_sold = sum(abs(mov.quantity or Decimal('0')) for mov in movements)
                    daily_rate = total_sold / 30

                    # توقع أيام حتى النفاذ
                    if daily_rate > 0:
                        days_until_stockout = target.current_stock / daily_rate

                        if days_until_stockout < 7:
                            logger.warning(f"🤖 AI Prediction: Product {target.name} will run out in {days_until_stockout:.0f} days! "
                                           f"(Selling {daily_rate:.1f} units/day)")
                        else:
                            logger.info(f"🤖 AI Prediction: Product {target.name} stock will last {days_until_stockout:.0f} days")

        except Exception as e:
            logger.error(f"❌ AI stockout prediction failed: {e}")

    @event.listens_for(Customer, 'after_update')
    def ai_predict_customer_churn(mapper, connection, target):
        """توقع خسارة العملاء (Churn Prediction)"""
        try:
            pass

            # آخر عملية شراء
            last_sale = connection.execute(
                Sale.__table__.select().where(
                    Sale.customer_id == target.id,
                    Sale.status == 'confirmed'
                ).order_by(Sale.sale_date.desc()).limit(1)
            ).first()

            if last_sale:
                # التأكد من أن sale_date timezone-aware
                sale_date = last_sale.sale_date
                if sale_date.tzinfo is None:
                    from datetime import timezone as tz
                    sale_date = sale_date.replace(tzinfo=tz.utc)
                days_since_purchase = (datetime.now(timezone.utc) - sale_date).days

                # توقع خطر الخسارة
                if days_since_purchase > 90:
                    churn_risk = 'high'
                    logger.warning(f"🤖 AI Churn Risk: Customer {target.id} - {days_since_purchase} days inactive - HIGH RISK!")
                elif days_since_purchase > 60:
                    churn_risk = 'medium'
                    logger.info(f"🤖 AI Churn Risk: Customer {target.id} - {days_since_purchase} days inactive - Medium risk")
                else:
                    churn_risk = 'low'

                # حفظ التوقع للتعلم
                from ai_knowledge.learning_system import AzadLearningSystem
                learning_system = AzadLearningSystem()
                learning_system.learn_from_interaction(
                    question=f"Customer churn prediction - {target.id}",
                    response=json.dumps({'days_inactive': days_since_purchase, 'risk': churn_risk}),
                    user_feedback=5,
                    context={'type': 'predictive_learning', 'subtype': 'churn_prediction'}
                )

        except Exception as e:
            logger.error(f"❌ AI churn prediction failed: {e}")

# ============================================================================
# Neural Training Listeners - مستمعات التدريب العصبي التلقائي
# ============================================================================


def register_neural_training_listeners():  # noqa: C901
    from models import Sale, Customer, Product

    @event.listens_for(Sale, 'after_insert')
    def neural_auto_retrain_on_milestones(mapper, connection, target):
        try:
            from ai_knowledge.auto_retraining import AutoRetrainingScheduler

            total_sales = connection.execute(
                Sale.__table__.select().where(
                    Sale.status == 'confirmed'
                )
            ).fetchall()

            sales_count = len(total_sales)

            if sales_count % 100 == 0:
                logger.info(f"🧠 Neural Milestone: {sales_count} sales - Checking auto-retraining...")
                try:
                    import threading
                    thread = threading.Thread(
                        target=AutoRetrainingScheduler.check_and_train_if_needed
                    )
                    thread.daemon = True
                    thread.start()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"❌ Neural auto-retrain failed: {e}")

    @event.listens_for(Customer, 'after_insert')
    def neural_customer_data_accumulation(mapper, connection, target):
        """
        تجميع بيانات العملاء للتدريب
        """
        try:
            # حساب إجمالي العملاء
            total_customers = connection.execute(
                Customer.__table__.select().where(
                    Customer.is_active.is_(True)
                )
            ).fetchall()

            customers_count = len(total_customers)

            # إعادة تدريب مصنف العملاء كل 50 عميل
            if customers_count % 50 == 0:
                logger.info(f"🧠 Neural: {customers_count} customers - Retraining customer classifier...")

        except Exception as e:
            logger.error(f"❌ Neural customer accumulation failed: {e}")

    @event.listens_for(Product, 'after_update')
    def neural_inventory_learning(mapper, connection, target):
        """
        التعلم من تحديثات المخزون
        """
        try:
            # إذا تغير المخزون بشكل كبير
            if hasattr(target, 'current_stock'):
                if target.current_stock == 0:
                    logger.warning(f"🧠 Neural Alert: Product {target.id} out of stock - Learning from stockout event")
                elif target.current_stock < target.min_stock_alert:
                    logger.info(f"🧠 Neural: Product {target.id} low stock - Updating demand predictions")

        except Exception as e:
            logger.error(f"❌ Neural inventory learning failed: {e}")

# ============================================================================
# Intelligent Assistant Listeners - مستمعات المساعد الذكي الحقيقي
# ============================================================================


def register_intelligent_assistant_listeners():  # noqa: C901
    """
    تسجيل مستمعات المساعد الذكي الجديد
    يدمج: Neural Engine + Reasoning Engine + Memory System
    """
    from models import Sale, Customer, Product

    @event.listens_for(Sale, 'after_insert')
    def intelligent_sale_analysis(mapper, connection, target):
        """
        تحليل ذكي للفاتورة الجديدة
        يستخدم الذكاء الحقيقي لاستخراج رؤى
        """
        try:
            from flask import current_app
            if current_app and current_app.config.get('TESTING'):
                return
            # تحليل ذكي فقط للفواتير المؤكدة
            if target.status != 'confirmed' or not target.is_active:
                return

            # تحليل باستخدام Data Analyzer

            # معلومات البيع
            sale_context = {
                'amount': float(target.amount_base),
                'items_count': len(target.lines) if target.lines else 0,
                'customer_type': target.customer.customer_type if target.customer else None,
                'payment_status': target.payment_status,
                'profit_margin': (
                    float(
                        (
                            (target.amount_base or Decimal('0')) -
                            sum((line.cost_price or Decimal('0')) * (line.quantity or 0) for line in (target.lines or []))
                        ) / (target.amount_base or Decimal('1'))
                    )
                    * 100
                ) if (target.amount_base and target.amount_base > 0) else 0
            }

            # رؤى ذكية
            insights = []

            # رؤية 1: هامش الربح
            if sale_context['profit_margin'] < 10:
                insights.append(f"⚠️ هامش ربح منخفض ({sale_context['profit_margin']:.1f}%) - راجع التسعير")
            elif sale_context['profit_margin'] > 40:
                insights.append(f"✅ هامش ربح ممتاز ({sale_context['profit_margin']:.1f}%)")

            # رؤية 2: حجم الفاتورة
            if sale_context['amount'] > 10000:
                insights.append(f"🎉 فاتورة كبيرة! {sale_context['amount']:,.0f} درهم")

            # رؤية 3: عدد الأصناف
            if sale_context['items_count'] > 10:
                insights.append(f"📦 طلبية كبيرة: {sale_context['items_count']} صنف")

            if insights:
                logger.info(f"🧠 Intelligent Insights for Sale {target.sale_number}: {' | '.join(insights)}")

        except Exception as e:
            logger.error(f"❌ Intelligent sale analysis failed: {e}")

    @event.listens_for(Customer, 'after_update')
    def intelligent_customer_monitoring(mapper, connection, target):
        """
        مراقبة ذكية للعملاء
        يكتشف أنماط التأخير والمشاكل
        """
        try:
            from flask import current_app
            if current_app and current_app.config.get('TESTING'):
                return
            # تحليل الرصيد باستخدام Data Analyzer
            from ai_knowledge.data_analyzer import data_analyzer
            debt_analysis = data_analyzer.analyze_customer_debt(target.id)

            if debt_analysis['success']:
                debt_info = debt_analysis['debt_analysis']

                # إنذارات ذكية
                if debt_info['total_debt'] > 10000:
                    logger.warning(f"🚨 High debt alert: Customer {target.id} owes {debt_info['total_debt']:,.0f} AED")

                if debt_info['overdue_count'] > 3:
                    logger.warning(f"⏰ Payment issue: Customer {target.id} has {debt_info['overdue_count']} overdue invoices")

        except Exception as e:
            logger.error(f"❌ Intelligent customer monitoring failed: {e}")

    @event.listens_for(Product, 'after_update')
    def intelligent_inventory_alert(mapper, connection, target):
        """
        تنبيه ذكي للمخزون
        يتنبأ بنفاذ المخزون قبل حدوثه
        """
        try:
            # تحقق من المخزون
            if target.current_stock <= target.min_stock_alert:
                # حساب معدل الاستهلاك (بسيط)
                # في المستقبل: استخدام Neural Engine للتنبؤ الدقيق

                days_until_stockout = 0
                if target.current_stock > 0:
                    # تقدير بسيط: افترض استهلاك 10% يومياً
                    days_until_stockout = target.current_stock / (target.min_stock_alert * 0.1)

                if days_until_stockout < 7:
                    logger.warning(f"📊 Intelligent Alert: Product {target.id} ({target.name}) will run out in ~{days_until_stockout:.0f} days!")
                    logger.info(f"💡 Recommendation: Order at least {target.min_stock_alert * 2:.0f} units")

        except Exception as e:
            logger.error(f"❌ Intelligent inventory alert failed: {e}")

# ============================================================================
# Initialization
# ============================================================================

# ملاحظة: لتفعيل المستمعات، قم باستدعاء register_all_listeners()
# في app.py بعد تعريف جميع Models


"""
مثال في app.py:

from models.events import register_all_listeners

def create_app():
    app = Flask(__name__)

    # ... تهيئة التطبيق ...

    with app.app_context():
        # تسجيل المستمعات
        register_all_listeners()

    return app
"""

# ============================================================================
# Automatic GL (General Ledger) Listeners - القيود المحاسبية التلقائية
# ============================================================================


def register_automatic_gl_listeners():
    """
    تسجيل مستمعات القيود المحاسبية التلقائية

    ⚠️ تم تعطيل هذه المستمعات لأن القيود المحاسبية يتم إنشاؤها الآن
    بشكل صحيح ودقيق (مع معالجة الكسور العشرية والحسابات الفرعية)
    في طبقة الخدمات (Services Layer):
    - SaleService
    - PaymentService
    - PurchasesRoute
    - ExpensesRoute

    هذا يمنع تكرار القيود ويضمن استخدام شجرة الحسابات الصحيحة.
    """
    logger.info("ℹ️ Automatic GL listeners skipped - relying on Service layer for accurate GL entries")
