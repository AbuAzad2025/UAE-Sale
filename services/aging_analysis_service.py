"""
خدمة تحليل العمر - Aging Analysis Service
===========================================

F2 — سياسة واحدة مع صفحة دفتر الأستاذ (routes/ledger.py)
--------------------------------------------------------
كانت هذه الخدمة تشتقّ أعمار الذمم بصيغة خاصة بها (فلتر على
``payment_status`` + مبلغ الفاتورة بعملة المعاملة) بينما صفحة دفتر الأستاذ
(``routes/ledger.py::_receivables_aging`` / ``_payables_aging``) تستعمل
سياسة أخرى — فكان الرقمان مختلفين في نفس اللحظة.

**هذه الخدمة ت mirroring لـ routes/ledger.py — يجب أن يبقى الاثنان متطابقين.**
(لا يمكن استيراد دوال المسار من الخدمة دون دورة استيراد، فمستوى النسخ
يدوياً مع توثيق واضح هنا.)

السياسة الموحّدة (مطابقة لـ routes/ledger.py):

  • العملة: عملة الأساس دائماً —
    الذمم المدينة: amount_base − paid_amount_base
    الذمم الدائنة: amount_base − paid_amount (المسجَّل بعملة الأساس).
  • النطاق: مستندات مؤكدة ونشطة وغير مؤرشفة، تاريخها ≤ تاريخ التقرير،
    والطرف المقابل (عميل/مورد) نشط.
  • الرصيد: الفرق بين الإجمالي والمستحق، ويشمل فقط ما هو أكبر من صفر.

الأعمار (b1) — من **مستحق** لا من **عمر**
------------------------------------------
كان المقياس هو عمر الفاتورة (الفرق بين تاريخها وتاريخ التقرير) وهو ليس
مقياس التأخير: فاتورة عمرها 30 يوماً لم تستحق بعد وفاتورة عمرها 30 يوماً
متأخرة 30 يوماً كانتا في الشريحة نفسها. الآن تُحسب الشرائح من **تاريخ
الاستحقاق** (`sales.due_date` / `purchases.due_date`):

    not_due | 1-30 | 31-60 | 61-90 | 90+   (أيام التأخير)

وفاتورة بلا تاريخ استحقاق تُعامل كأنها مستحقّة في تاريخها — وهو ما
ترجّبه ترحيل البيانات `b1_due_dates`.

الشرائح القديمة (عمر الفاتورة: 0-30 … over_120) بقيت في المخرجات لأنها
مرجع صفحة دفتر الأستاذ (``routes/ledger.py::AGING_BUCKETS``) وتُقارَن
معها في ``tests/unit/test_reconciliation_p0.py``؛ والشرائح الجديدة
(التأخير) في ``overdue_buckets``، ومجموعها = الإجمالي المستحق.

الأرشفة: الأرشفة تكتب صفاً في ``archived_records`` ولا تقلب
``is_active`` ولا ``status`` — لذلك يجب استبعاد المعرّفات المؤرشفة
صراحةً من كل تقرير مالي (نفس فلتر ``_archived_record_ids`` في
routes/ledger.py).
"""

from decimal import Decimal
from datetime import datetime, date, time

from models import Customer, Supplier, Sale, Purchase
from services.due_date_service import (
    OVERDUE_BUCKETS,
    bucket_for_overdue,
    effective_due_date,
    overdue_days,
)


# حدود شرائح **العمر** — مطابقة لـ routes/ledger.py::AGING_BUCKETS
AGING_BUCKETS = ('0-30', '31-60', '61-90', '91-120', 'over_120')

# حدود شرائح **التأخير** — المصدر الوحيد في services/due_date_service.py
__all__ = [
    'AGING_BUCKETS',
    'OVERDUE_BUCKETS',
    'AgingAnalysisService',
    'bucket_for_overdue',
    'overdue_days',
]


def _day_end(d):
    """نهاية اليوم لعمود DateTime — يمنع استبعاد حركات اليوم نفسه
    (مقارنة timestamp <= تاريخ تُسقط كل ما بعد منتصف الليل)."""
    if isinstance(d, datetime):
        return d
    return datetime.combine(d, time.max)


def _aging_bucket(days_old):
    """تصنيف عمر المستند إلى شريحة — مطابق لـ routes/ledger.py::_aging_bucket."""
    if days_old <= 30:
        return '0-30'
    if days_old <= 60:
        return '31-60'
    if days_old <= 90:
        return '61-90'
    if days_old <= 120:
        return '91-120'
    return 'over_120'


def _resolve_as_of(as_of_date=None, as_of=None):
    """تاريخ المرجع — `as_of` الاسم الجديد و`as_of_date` الاسم القديم."""
    reference = as_of if as_of is not None else as_of_date
    if reference is None:
        return date.today()
    if isinstance(reference, datetime):
        return reference.date()
    if isinstance(reference, str):
        return datetime.strptime(reference.strip()[:10], '%Y-%m-%d').date()
    return reference


def _archived_record_ids(table_name):
    """معرّفات السجلات المؤرشفة — نفس الفلتر في routes/ledger.py.

    الأرشفة تعكس القيود المحاسبية وتترك حالة المستند 'confirmed'، لذلك
    يجب استبعادها صراحةً من كل تقرير مالي.
    """
    from models import ArchivedRecord
    from sqlalchemy import select
    return select(ArchivedRecord.record_id).where(
        ArchivedRecord.table_name == table_name)


class AgingAnalysisService:

    @staticmethod
    def get_receivables_aging(as_of_date=None, as_of=None):  # noqa: C901
        """
        تحليل الذمم المدينة (Accounts Receivable) — بالاستحقاق لا بالعمر

        Args:
            as_of_date: التاريخ المرجعي (default: اليوم)
            as_of: الاسم البديل للتاريخ المرجعي (يُقدَّم على as_of_date)

        Returns:
            {
                'customers': [...],
                'totals': {...},          # شرائح العمر (مرجع دفتر الأستاذ) + total
                'buckets': {...},         # شرائح العمر (Decimal)
                'overdue_buckets': {...}, # شرائح التأخير (Decimal)
                'total_outstanding': float,
                'overdue_total': float,
                'as_of_date': date,
                'as_of': date,
                'customer_count': int
            }
        """
        as_of_date = _resolve_as_of(as_of_date, as_of)
        cutoff = _day_end(as_of_date)

        results = []
        totals = {bucket: Decimal('0') for bucket in AGING_BUCKETS}
        totals['total'] = Decimal('0')
        overdue_totals = {bucket: Decimal('0') for bucket in OVERDUE_BUCKETS}

        # جميع العملاء النشطين
        customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

        for customer in customers:
            aging = {
                'customer': customer,
                '0-30': Decimal('0'),
                '31-60': Decimal('0'),
                '61-90': Decimal('0'),
                '91-120': Decimal('0'),
                'over_120': Decimal('0'),
                'total': Decimal('0'),
                'overdue': {bucket: Decimal('0') for bucket in OVERDUE_BUCKETS},
                'invoices': []
            }

            # المبيعات غير المدفوعة بالكامل — نفس فلتر routes/ledger.py:
            # مؤكّدة + نشطة + غير مؤرشفة + تاريخها ≤ تاريخ التقرير.
            unpaid_sales = (
                Sale.query
                .filter(
                    Sale.customer_id == customer.id,
                    Sale.status == 'confirmed',
                    Sale.is_active.is_(True),
                    Sale.sale_date <= cutoff,
                )
                .filter(~Sale.id.in_(_archived_record_ids('sales')))
                .order_by(Sale.sale_date).all()
            )

            for sale in unpaid_sales:
                # حساب الرصيد المتبقي — بعملة الأساس (amount_base -
                # paid_amount_base) لأن كل أرقام الذمم الأخرى بالأساس.
                balance = (sale.amount_base or Decimal('0')) - (sale.paid_amount_base or Decimal('0'))

                if balance > 0:
                    # حساب عمر الفاتورة (شرائح العمر — مرجع دفتر الأستاذ)
                    days_old = (as_of_date - sale.sale_date.date()).days
                    age_category = _aging_bucket(days_old)

                    # حساب التأخير عن تاريخ الاستحقاق (الشرائح الحقيقية)
                    due = effective_due_date(sale.due_date, sale.sale_date)
                    days_late = overdue_days(due, as_of=as_of_date)
                    overdue_category = bucket_for_overdue(days_late)

                    aging[age_category] += balance
                    aging['total'] += balance
                    aging['overdue'][overdue_category] += balance

                    # إضافة تفاصيل الفاتورة
                    aging['invoices'].append({
                        'sale_number': sale.sale_number,
                        'sale_date': sale.sale_date.date(),
                        'due_date': due,
                        'total': float(sale.total_amount),
                        'total_base': float(sale.amount_base or 0),
                        'paid': float(sale.paid_amount or 0),
                        'paid_base': float(sale.paid_amount_base or 0),
                        'balance': float(balance),
                        'currency': sale.currency,
                        'days_old': days_old,
                        'age_category': age_category,
                        'days_overdue': days_late,
                        'overdue_bucket': overdue_category
                    })

            # إضافة العميل إذا كان لديه رصيد
            if aging['total'] > 0:
                # تحويل Decimals لـ floats
                aging_float = {
                    'customer': customer,
                    '0-30': float(aging['0-30']),
                    '31-60': float(aging['31-60']),
                    '61-90': float(aging['61-90']),
                    '91-120': float(aging['91-120']),
                    'over_120': float(aging['over_120']),
                    'total': float(aging['total']),
                    'overdue_buckets': {
                        bucket: float(aging['overdue'][bucket])
                        for bucket in OVERDUE_BUCKETS
                    },
                    'total_outstanding': float(aging['total']),
                    'overdue_total': float(
                        aging['total'] - aging['overdue']['not_due']),
                    'invoices': aging['invoices']
                }
                results.append(aging_float)

                # إضافة للإجماليات
                for bucket in AGING_BUCKETS:
                    totals[bucket] += aging[bucket]
                totals['total'] += aging['total']
                for bucket in OVERDUE_BUCKETS:
                    overdue_totals[bucket] += aging['overdue'][bucket]

        # تحويل الإجماليات لـ floats
        totals_float = {k: float(v) for k, v in totals.items()}

        total_outstanding = sum(
            (overdue_totals[bucket] for bucket in OVERDUE_BUCKETS), Decimal('0'))
        overdue_total = total_outstanding - overdue_totals['not_due']

        return {
            'customers': results,
            'totals': totals_float,
            'buckets': {bucket: totals[bucket] for bucket in AGING_BUCKETS},
            'overdue_buckets': {
                bucket: overdue_totals[bucket] for bucket in OVERDUE_BUCKETS
            },
            'total_outstanding': float(total_outstanding),
            'overdue_total': float(overdue_total),
            'as_of_date': as_of_date,
            'as_of': as_of_date,
            'customer_count': len(results)
        }

    @staticmethod
    def get_payables_aging(as_of_date=None, as_of=None):  # noqa: C901
        """
        تحليل الذمم الدائنة (Accounts Payable) — بالاستحقاق لا بالعمر

        نفس سياسة الذمم المدينة (routes/ledger.py::_payables_aging):
        مستندات مؤكدة وغير مؤرشفة، مورد نشط، رصيد موجب فقط، وحدود الشرائح
        نفسها.
        """
        as_of_date = _resolve_as_of(as_of_date, as_of)
        cutoff = _day_end(as_of_date)

        results = []
        totals = {bucket: Decimal('0') for bucket in AGING_BUCKETS}
        totals['total'] = Decimal('0')
        overdue_totals = {bucket: Decimal('0') for bucket in OVERDUE_BUCKETS}

        # جميع الموردين النشطين
        suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()

        for supplier in suppliers:
            aging = {
                'supplier': supplier,
                '0-30': Decimal('0'),
                '31-60': Decimal('0'),
                '61-90': Decimal('0'),
                '91-120': Decimal('0'),
                'over_120': Decimal('0'),
                'total': Decimal('0'),
                'overdue': {bucket: Decimal('0') for bucket in OVERDUE_BUCKETS},
                'invoices': []
            }

            # المشتريات غير المدفوعة بالكامل — نفس فلتر routes/ledger.py:
            # مؤكّدة + غير مؤرشفة + تاريخها ≤ تاريخ التقرير + مورد نشط.
            unpaid_purchases = (
                Purchase.query
                .filter(
                    Purchase.supplier_id == supplier.id,
                    Purchase.status == 'confirmed',
                    Purchase.purchase_date <= cutoff,
                )
                .filter(~Purchase.id.in_(_archived_record_ids('purchases')))
                .order_by(Purchase.purchase_date).all()
            )

            for purchase in unpaid_purchases:
                # حساب الرصيد المتبقي — بعملة الأساس (amount_base −
                # paid_amount) لأن paid_amount يُسجَّل بعملة الأساس.
                balance = (purchase.amount_base or Decimal('0')) - (purchase.paid_amount or Decimal('0'))

                if balance > 0:
                    # حساب عمر الفاتورة (شرائح العمر — مرجع دفتر الأستاذ)
                    days_old = (as_of_date - purchase.purchase_date.date()).days
                    age_category = _aging_bucket(days_old)

                    # حساب التأخير عن تاريخ الاستحقاق (الشرائح الحقيقية)
                    due = effective_due_date(purchase.due_date, purchase.purchase_date)
                    days_late = overdue_days(due, as_of=as_of_date)
                    overdue_category = bucket_for_overdue(days_late)

                    aging[age_category] += balance
                    aging['total'] += balance
                    aging['overdue'][overdue_category] += balance

                    # إضافة تفاصيل الفاتورة
                    aging['invoices'].append({
                        'purchase_number': purchase.purchase_number,
                        'purchase_date': purchase.purchase_date.date(),
                        'due_date': due,
                        'total': float(purchase.total_amount),
                        'total_base': float(purchase.amount_base or 0),
                        'paid': float(purchase.paid_amount or 0),
                        'balance': float(balance),
                        'currency': purchase.currency,
                        'days_old': days_old,
                        'age_category': age_category,
                        'days_overdue': days_late,
                        'overdue_bucket': overdue_category
                    })

            # إضافة المورد إذا كان لديه رصيد
            if aging['total'] > 0:
                aging_float = {
                    'supplier': supplier,
                    '0-30': float(aging['0-30']),
                    '31-60': float(aging['31-60']),
                    '61-90': float(aging['61-90']),
                    '91-120': float(aging['91-120']),
                    'over_120': float(aging['over_120']),
                    'total': float(aging['total']),
                    'overdue_buckets': {
                        bucket: float(aging['overdue'][bucket])
                        for bucket in OVERDUE_BUCKETS
                    },
                    'total_outstanding': float(aging['total']),
                    'overdue_total': float(
                        aging['total'] - aging['overdue']['not_due']),
                    'invoices': aging['invoices']
                }
                results.append(aging_float)

                # إضافة للإجماليات
                for bucket in AGING_BUCKETS:
                    totals[bucket] += aging[bucket]
                totals['total'] += aging['total']
                for bucket in OVERDUE_BUCKETS:
                    overdue_totals[bucket] += aging['overdue'][bucket]

        totals_float = {k: float(v) for k, v in totals.items()}

        total_outstanding = sum(
            (overdue_totals[bucket] for bucket in OVERDUE_BUCKETS), Decimal('0'))
        overdue_total = total_outstanding - overdue_totals['not_due']

        return {
            'suppliers': results,
            'totals': totals_float,
            'buckets': {bucket: totals[bucket] for bucket in AGING_BUCKETS},
            'overdue_buckets': {
                bucket: overdue_totals[bucket] for bucket in OVERDUE_BUCKETS
            },
            'total_outstanding': float(total_outstanding),
            'overdue_total': float(overdue_total),
            'as_of_date': as_of_date,
            'as_of': as_of_date,
            'supplier_count': len(results)
        }
