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
  • الشرائح وحدودها: 0-30 / 31-60 / 61-90 / 91-120 / over_120 يوم
    (AGING_BUCKETS في routes/ledger.py، والدالة _aging_bucket هناك).

الأرشفة: الأرشفة تكتب صفاً في ``archived_records`` ولا تقلب
``is_active`` ولا ``status`` — لذلك يجب استبعاد المعرّفات المؤرشفة
صراحةً من كل تقرير مالي (نفس فلتر ``_archived_record_ids`` في
routes/ledger.py).
"""

from decimal import Decimal
from datetime import datetime, date, time

from models import Customer, Supplier, Sale, Purchase


# حدود الشرائح — مطابقة لـ routes/ledger.py::AGING_BUCKETS
AGING_BUCKETS = ('0-30', '31-60', '61-90', '91-120', 'over_120')


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
    def get_receivables_aging(as_of_date=None):  # noqa: C901
        """
        تحليل عمر الذمم المدينة (Accounts Receivable)

        Args:
            as_of_date: التاريخ المرجعي (default: اليوم)

        Returns:
            {
                'customers': [...],
                'totals': {...},
                'buckets': {...},   # Decimal (مطابقة routes/ledger.py)
                'as_of_date': date
            }
        """
        if not as_of_date:
            as_of_date = date.today()
        elif isinstance(as_of_date, str):
            as_of_date = datetime.strptime(as_of_date, '%Y-%m-%d').date()

        cutoff = _day_end(as_of_date)

        results = []
        totals = {bucket: Decimal('0') for bucket in AGING_BUCKETS}
        totals['total'] = Decimal('0')

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
                    # حساب عمر الفاتورة
                    days_old = (as_of_date - sale.sale_date.date()).days
                    age_category = _aging_bucket(days_old)

                    aging[age_category] += balance
                    aging['total'] += balance

                    # إضافة تفاصيل الفاتورة
                    aging['invoices'].append({
                        'sale_number': sale.sale_number,
                        'sale_date': sale.sale_date.date(),
                        'total': float(sale.total_amount),
                        'total_base': float(sale.amount_base or 0),
                        'paid': float(sale.paid_amount or 0),
                        'paid_base': float(sale.paid_amount_base or 0),
                        'balance': float(balance),
                        'currency': sale.currency,
                        'days_old': days_old,
                        'age_category': age_category
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
                    'invoices': aging['invoices']
                }
                results.append(aging_float)

                # إضافة للإجماليات
                for bucket in AGING_BUCKETS:
                    totals[bucket] += aging[bucket]
                totals['total'] += aging['total']

        # تحويل الإجماليات لـ floats
        totals_float = {k: float(v) for k, v in totals.items()}

        return {
            'customers': results,
            'totals': totals_float,
            'buckets': {bucket: totals[bucket] for bucket in AGING_BUCKETS},
            'as_of_date': as_of_date,
            'customer_count': len(results)
        }

    @staticmethod
    def get_payables_aging(as_of_date=None):  # noqa: C901
        """
        تحليل عمر الذمم الدائنة (Accounts Payable)

        نفس سياسة الذمم المدينة (routes/ledger.py::_payables_aging):
        مستندات مؤكدة وغير مؤرشفة، مورد نشط، رصيد موجب فقط، وحدود الشرائح
        نفسها.
        """
        if not as_of_date:
            as_of_date = date.today()
        elif isinstance(as_of_date, str):
            as_of_date = datetime.strptime(as_of_date, '%Y-%m-%d').date()

        cutoff = _day_end(as_of_date)

        results = []
        totals = {bucket: Decimal('0') for bucket in AGING_BUCKETS}
        totals['total'] = Decimal('0')

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
                    # حساب عمر الفاتورة
                    days_old = (as_of_date - purchase.purchase_date.date()).days
                    age_category = _aging_bucket(days_old)

                    aging[age_category] += balance
                    aging['total'] += balance

                    # إضافة تفاصيل الفاتورة
                    aging['invoices'].append({
                        'purchase_number': purchase.purchase_number,
                        'purchase_date': purchase.purchase_date.date(),
                        'total': float(purchase.total_amount),
                        'total_base': float(purchase.amount_base or 0),
                        'paid': float(purchase.paid_amount or 0),
                        'balance': float(balance),
                        'currency': purchase.currency,
                        'days_old': days_old,
                        'age_category': age_category
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
                    'invoices': aging['invoices']
                }
                results.append(aging_float)

                # إضافة للإجماليات
                for bucket in AGING_BUCKETS:
                    totals[bucket] += aging[bucket]
                totals['total'] += aging['total']

        totals_float = {k: float(v) for k, v in totals.items()}

        return {
            'suppliers': results,
            'totals': totals_float,
            'buckets': {bucket: totals[bucket] for bucket in AGING_BUCKETS},
            'as_of_date': as_of_date,
            'supplier_count': len(results)
        }
