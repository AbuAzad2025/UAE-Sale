"""
خدمة قائمة التدفقات النقدية - Cash Flow Statement Service
"""

from decimal import Decimal
from datetime import datetime, date
from sqlalchemy import func, and_, or_
from extensions import db
from models import (
    GLAccount, GLJournalEntry, GLJournalLine,
    Sale, Purchase, Payment, Receipt, Expense
)


class CashFlowService:
    
    @staticmethod
    def generate_cash_flow(period_start, period_end):
        """
        إنشاء قائمة التدفقات النقدية
        
        Args:
            period_start: تاريخ البداية (date أو string)
            period_end: تاريخ النهاية (date أو string)
        
        Returns:
            dict: قائمة التدفقات النقدية الكاملة
        """
        # تحويل التواريخ
        if isinstance(period_start, str):
            period_start = datetime.strptime(period_start, '%Y-%m-%d').date()
        if isinstance(period_end, str):
            period_end = datetime.strptime(period_end, '%Y-%m-%d').date()
        
        # 1. الأنشطة التشغيلية (Operating Activities)
        operating = CashFlowService._get_operating_activities(period_start, period_end)
        
        # 2. الأنشطة الاستثمارية (Investing Activities)
        investing = CashFlowService._get_investing_activities(period_start, period_end)
        
        # 3. الأنشطة التمويلية (Financing Activities)
        financing = CashFlowService._get_financing_activities(period_start, period_end)
        
        # 4. حساب النقدية
        cash_accounts = GLAccount.query.filter(
            GLAccount.code.in_(['1110', '1120'])  # الصندوق والبنك
        ).all()
        
        cash_beginning = CashFlowService._get_cash_balance(cash_accounts, period_start, is_beginning=True)
        
        net_cash_flow = (
            operating['net_cash_from_operating'] +
            investing['net_cash_from_investing'] +
            financing['net_cash_from_financing']
        )
        
        cash_ending = cash_beginning + net_cash_flow
        
        return {
            'period_start': period_start,
            'period_end': period_end,
            'operating_activities': operating,
            'investing_activities': investing,
            'financing_activities': financing,
            'net_change_in_cash': float(net_cash_flow),
            'cash_beginning': float(cash_beginning),
            'cash_ending': float(cash_ending)
        }
    
    @staticmethod
    def _get_operating_activities(period_start, period_end):
        """حساب التدفقات النقدية من الأنشطة التشغيلية"""
        
        # المقبوضات من العملاء
        receipts = db.session.query(
            func.sum(Receipt.amount_aed)
        ).filter(
            and_(
                Receipt.receipt_date >= period_start,
                Receipt.receipt_date <= period_end,
                Receipt.payment_method.in_(['cash', 'bank'])  # نقدي وبنكي فقط
            )
        ).scalar() or Decimal('0')
        
        # المدفوعات للموردين
        supplier_payments = db.session.query(
            func.sum(Payment.amount_aed)
        ).filter(
            and_(
                Payment.payment_date >= period_start,
                Payment.payment_date <= period_end,
                Payment.payment_method.in_(['cash', 'bank']),
                Payment.supplier_id.isnot(None)
            )
        ).scalar() or Decimal('0')
        
        # المدفوعات للمصروفات
        expense_payments = db.session.query(
            func.sum(Expense.amount_aed)
        ).filter(
            and_(
                Expense.expense_date >= period_start,
                Expense.expense_date <= period_end,
                Expense.payment_method.in_(['cash', 'bank'])
            )
        ).scalar() or Decimal('0')
        
        # الرواتب (من حساب الرواتب)
        salary_account = GLAccount.query.filter_by(code='6100').first()
        salaries = Decimal('0')
        if salary_account:
            salaries = db.session.query(
                func.sum(GLJournalLine.debit)
            ).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == salary_account.id,
                    func.date(GLJournalEntry.entry_date) >= period_start,
                    func.date(GLJournalEntry.entry_date) <= period_end
                )
            ).scalar() or Decimal('0')
        
        net_cash_from_operating = receipts - supplier_payments - expense_payments - salaries
        
        return {
            'receipts_from_customers': float(receipts),
            'payments_to_suppliers': float(supplier_payments),
            'payments_for_expenses': float(expense_payments),
            'payments_for_salaries': float(salaries),
            'net_cash_from_operating': float(net_cash_from_operating),
            'items': [
                {
                    'description': 'مقبوضات من العملاء',
                    'amount': float(receipts),
                    'type': 'inflow'
                },
                {
                    'description': 'مدفوعات للموردين',
                    'amount': float(supplier_payments),
                    'type': 'outflow'
                },
                {
                    'description': 'مدفوعات مصروفات',
                    'amount': float(expense_payments),
                    'type': 'outflow'
                },
                {
                    'description': 'رواتب وأجور',
                    'amount': float(salaries),
                    'type': 'outflow'
                }
            ]
        }
    
    @staticmethod
    def _get_investing_activities(period_start, period_end):
        """حساب التدفقات النقدية من الأنشطة الاستثمارية"""
        
        # شراء أصول ثابتة (حساب 1200)
        fixed_assets_account = GLAccount.query.filter(
            GLAccount.code.like('12%')
        ).all()
        
        purchase_of_assets = Decimal('0')
        for account in fixed_assets_account:
            purchases = db.session.query(
                func.sum(GLJournalLine.debit)
            ).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == account.id,
                    func.date(GLJournalEntry.entry_date) >= period_start,
                    func.date(GLJournalEntry.entry_date) <= period_end
                )
            ).scalar() or Decimal('0')
            purchase_of_assets += purchases
        
        # بيع أصول ثابتة (credits في نفس الحسابات)
        sale_of_assets = Decimal('0')
        for account in fixed_assets_account:
            sales = db.session.query(
                func.sum(GLJournalLine.credit)
            ).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == account.id,
                    func.date(GLJournalEntry.entry_date) >= period_start,
                    func.date(GLJournalEntry.entry_date) <= period_end
                )
            ).scalar() or Decimal('0')
            sale_of_assets += sales
        
        net_cash_from_investing = sale_of_assets - purchase_of_assets
        
        return {
            'purchase_of_fixed_assets': float(purchase_of_assets),
            'sale_of_fixed_assets': float(sale_of_assets),
            'net_cash_from_investing': float(net_cash_from_investing),
            'items': [
                {
                    'description': 'شراء أصول ثابتة',
                    'amount': float(purchase_of_assets),
                    'type': 'outflow'
                },
                {
                    'description': 'بيع أصول ثابتة',
                    'amount': float(sale_of_assets),
                    'type': 'inflow'
                }
            ]
        }
    
    @staticmethod
    def _get_financing_activities(period_start, period_end):
        """حساب التدفقات النقدية من الأنشطة التمويلية"""
        
        # رأس المال (حساب 3100)
        capital_account = GLAccount.query.filter_by(code='3100').first()
        capital_contributions = Decimal('0')
        if capital_account:
            capital_contributions = db.session.query(
                func.sum(GLJournalLine.credit)
            ).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == capital_account.id,
                    func.date(GLJournalEntry.entry_date) >= period_start,
                    func.date(GLJournalEntry.entry_date) <= period_end
                )
            ).scalar() or Decimal('0')
        
        # سحوبات المالك (حساب 3300)
        owner_draw_account = GLAccount.query.filter_by(code='3300').first()
        owner_withdrawals = Decimal('0')
        if owner_draw_account:
            owner_withdrawals = db.session.query(
                func.sum(GLJournalLine.debit)
            ).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == owner_draw_account.id,
                    func.date(GLJournalEntry.entry_date) >= period_start,
                    func.date(GLJournalEntry.entry_date) <= period_end
                )
            ).scalar() or Decimal('0')
        
        # القروض (حساب 2210)
        loans_account = GLAccount.query.filter_by(code='2210').first()
        loans_received = Decimal('0')
        loan_repayments = Decimal('0')
        if loans_account:
            loans_received = db.session.query(
                func.sum(GLJournalLine.credit)
            ).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == loans_account.id,
                    func.date(GLJournalEntry.entry_date) >= period_start,
                    func.date(GLJournalEntry.entry_date) <= period_end
                )
            ).scalar() or Decimal('0')
            
            loan_repayments = db.session.query(
                func.sum(GLJournalLine.debit)
            ).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == loans_account.id,
                    func.date(GLJournalEntry.entry_date) >= period_start,
                    func.date(GLJournalEntry.entry_date) <= period_end
                )
            ).scalar() or Decimal('0')
        
        net_cash_from_financing = (
            capital_contributions + loans_received - owner_withdrawals - loan_repayments
        )
        
        return {
            'capital_contributions': float(capital_contributions),
            'owner_withdrawals': float(owner_withdrawals),
            'loans_received': float(loans_received),
            'loan_repayments': float(loan_repayments),
            'net_cash_from_financing': float(net_cash_from_financing),
            'items': [
                {
                    'description': 'إضافات رأس المال',
                    'amount': float(capital_contributions),
                    'type': 'inflow'
                },
                {
                    'description': 'قروض مستلمة',
                    'amount': float(loans_received),
                    'type': 'inflow'
                },
                {
                    'description': 'سحوبات المالك',
                    'amount': float(owner_withdrawals),
                    'type': 'outflow'
                },
                {
                    'description': 'سداد قروض',
                    'amount': float(loan_repayments),
                    'type': 'outflow'
                }
            ]
        }
    
    @staticmethod
    def _get_cash_balance(cash_accounts, target_date, is_beginning=False):
        """حساب رصيد النقدية في تاريخ محدد"""
        total_balance = Decimal('0')
        
        for account in cash_accounts:
            # حساب الرصيد حتى التاريخ المحدد
            debit_sum = db.session.query(
                func.sum(GLJournalLine.debit)
            ).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == account.id,
                    func.date(GLJournalEntry.entry_date) < target_date if is_beginning 
                    else func.date(GLJournalEntry.entry_date) <= target_date
                )
            ).scalar() or Decimal('0')
            
            credit_sum = db.session.query(
                func.sum(GLJournalLine.credit)
            ).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == account.id,
                    func.date(GLJournalEntry.entry_date) < target_date if is_beginning 
                    else func.date(GLJournalEntry.entry_date) <= target_date
                )
            ).scalar() or Decimal('0')
            
            total_balance += (debit_sum - credit_sum)
        
        return total_balance

