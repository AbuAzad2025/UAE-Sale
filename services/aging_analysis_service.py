"""
خدمة تحليل العمر - Aging Analysis Service
"""

from decimal import Decimal
from datetime import datetime, date
from models import Customer, Supplier, Sale, Purchase


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
                'as_of_date': date
            }
        """
        if not as_of_date:
            as_of_date = date.today()
        elif isinstance(as_of_date, str):
            as_of_date = datetime.strptime(as_of_date, '%Y-%m-%d').date()

        results = []
        totals = {
            '0-30': Decimal('0'),
            '31-60': Decimal('0'),
            '61-90': Decimal('0'),
            '91-120': Decimal('0'),
            'over_120': Decimal('0'),
            'total': Decimal('0')
        }

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

            # المبيعات غير المدفوعة بالكامل
            unpaid_sales = Sale.query.filter(
                Sale.customer_id == customer.id,
                Sale.payment_status.in_(['partial', 'pending']),
                Sale.sale_date <= as_of_date
            ).order_by(Sale.sale_date).all()

            for sale in unpaid_sales:
                # حساب الرصيد المتبقي
                balance = sale.total_amount - (sale.paid_amount or Decimal('0'))

                if balance > 0:
                    # حساب عمر الفاتورة
                    days_old = (as_of_date - sale.sale_date.date()).days

                    # تصنيف حسب العمر
                    if days_old <= 30:
                        aging['0-30'] += balance
                        age_category = '0-30'
                    elif days_old <= 60:
                        aging['31-60'] += balance
                        age_category = '31-60'
                    elif days_old <= 90:
                        aging['61-90'] += balance
                        age_category = '61-90'
                    elif days_old <= 120:
                        aging['91-120'] += balance
                        age_category = '91-120'
                    else:
                        aging['over_120'] += balance
                        age_category = '+120'

                    aging['total'] += balance

                    # إضافة تفاصيل الفاتورة
                    aging['invoices'].append({
                        'sale_number': sale.sale_number,
                        'sale_date': sale.sale_date.date(),
                        'total': float(sale.total_amount),
                        'paid': float(sale.paid_amount or 0),
                        'balance': float(balance),
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
                totals['0-30'] += aging['0-30']
                totals['31-60'] += aging['31-60']
                totals['61-90'] += aging['61-90']
                totals['91-120'] += aging['91-120']
                totals['over_120'] += aging['over_120']
                totals['total'] += aging['total']

        # تحويل الإجماليات لـ floats
        totals_float = {k: float(v) for k, v in totals.items()}

        return {
            'customers': results,
            'totals': totals_float,
            'as_of_date': as_of_date,
            'customer_count': len(results)
        }

    @staticmethod
    def get_payables_aging(as_of_date=None):  # noqa: C901
        """
        تحليل عمر الذمم الدائنة (Accounts Payable)
        """
        if not as_of_date:
            as_of_date = date.today()
        elif isinstance(as_of_date, str):
            as_of_date = datetime.strptime(as_of_date, '%Y-%m-%d').date()

        results = []
        totals = {
            '0-30': Decimal('0'),
            '31-60': Decimal('0'),
            '61-90': Decimal('0'),
            '91-120': Decimal('0'),
            'over_120': Decimal('0'),
            'total': Decimal('0')
        }

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

            # المشتريات غير المدفوعة بالكامل
            unpaid_purchases = Purchase.query.filter(
                Purchase.supplier_id == supplier.id,
                Purchase.payment_status.in_(['partial', 'pending']),
                Purchase.purchase_date <= as_of_date
            ).order_by(Purchase.purchase_date).all()

            for purchase in unpaid_purchases:
                # حساب الرصيد المتبقي
                balance = purchase.total_amount - (purchase.paid_amount or Decimal('0'))

                if balance > 0:
                    # حساب عمر الفاتورة
                    days_old = (as_of_date - purchase.purchase_date.date()).days

                    # تصنيف حسب العمر
                    if days_old <= 30:
                        aging['0-30'] += balance
                        age_category = '0-30'
                    elif days_old <= 60:
                        aging['31-60'] += balance
                        age_category = '31-60'
                    elif days_old <= 90:
                        aging['61-90'] += balance
                        age_category = '61-90'
                    elif days_old <= 120:
                        aging['91-120'] += balance
                        age_category = '91-120'
                    else:
                        aging['over_120'] += balance
                        age_category = '+120'

                    aging['total'] += balance

                    # إضافة تفاصيل الفاتورة
                    aging['invoices'].append({
                        'purchase_number': purchase.purchase_number,
                        'purchase_date': purchase.purchase_date.date(),
                        'total': float(purchase.total_amount),
                        'paid': float(purchase.paid_amount or 0),
                        'balance': float(balance),
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
                totals['0-30'] += aging['0-30']
                totals['31-60'] += aging['31-60']
                totals['61-90'] += aging['61-90']
                totals['91-120'] += aging['91-120']
                totals['over_120'] += aging['over_120']
                totals['total'] += aging['total']

        totals_float = {k: float(v) for k, v in totals.items()}

        return {
            'suppliers': results,
            'totals': totals_float,
            'as_of_date': as_of_date,
            'supplier_count': len(results)
        }
