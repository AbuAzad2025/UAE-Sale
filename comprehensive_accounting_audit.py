"""
==========================================
فحص شامل للنظام المحاسبي
Comprehensive Accounting System Audit
==========================================
المراجع المحاسبي: نظام فحص دقيق ومتكامل
"""

import sys
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from sqlalchemy import func, and_, or_
from tabulate import tabulate
import json

# تهيئة التطبيق
from app import create_app
from extensions import db
from models import (
    GLAccount, GLJournalEntry, GLJournalLine,
    Sale, SaleLine, Purchase, PurchaseLine,
    Payment, Receipt, Expense, AdvancedExpense,
    Customer, Supplier, Product,
    FixedAsset, DepreciationSchedule,
    Cheque, BankReconciliation,
    Currency, ExchangeRate,
    CostCenter, Budget, BudgetLine,
    CustomsTax, ExpenseCategory
)


class AccountingAuditor:
    """مراجع محاسبي شامل"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.recommendations = []
        self.report = {}
        
    def add_error(self, category, message, severity='HIGH'):
        """إضافة خطأ محاسبي"""
        self.errors.append({
            'category': category,
            'message': message,
            'severity': severity,
            'timestamp': datetime.now()
        })
    
    def add_warning(self, category, message):
        """إضافة تحذير"""
        self.warnings.append({
            'category': category,
            'message': message,
            'timestamp': datetime.now()
        })
    
    def add_recommendation(self, category, message):
        """إضافة توصية"""
        self.recommendations.append({
            'category': category,
            'message': message
        })
    
    def print_section(self, title):
        """طباعة عنوان قسم"""
        print(f"\n{'='*80}")
        print(f"  {title}")
        print(f"{'='*80}\n")
    
    def audit_gl_accounts(self):
        """1️⃣ فحص حسابات دفتر الأستاذ"""
        self.print_section("1️⃣ فحص حسابات دفتر الأستاذ العام (Chart of Accounts)")
        
        # إحصائيات الحسابات
        total_accounts = GLAccount.query.count()
        active_accounts = GLAccount.query.filter_by(is_active=True).count()
        header_accounts = GLAccount.query.filter_by(is_header=True).count()
        detail_accounts = GLAccount.query.filter_by(is_header=False).count()
        
        print(f"📊 إحصائيات الحسابات:")
        print(f"   • إجمالي الحسابات: {total_accounts}")
        print(f"   • الحسابات النشطة: {active_accounts}")
        print(f"   • الحسابات الرئيسية: {header_accounts}")
        print(f"   • الحسابات التفصيلية: {detail_accounts}")
        
        # فحص الحسابات حسب النوع
        account_types = db.session.query(
            GLAccount.type,
            func.count(GLAccount.id).label('count')
        ).group_by(GLAccount.type).all()
        
        print(f"\n📋 توزيع الحسابات حسب النوع:")
        for acc_type, count in account_types:
            type_ar = {
                'asset': 'أصول',
                'liability': 'خصوم', 
                'equity': 'حقوق ملكية',
                'revenue': 'إيرادات',
                'expense': 'مصروفات'
            }.get(acc_type, acc_type)
            print(f"   • {type_ar}: {count} حساب")
        
        # فحص الحسابات التي لها قيود على حساب رئيسي (خطأ محاسبي)
        header_accounts_with_entries = db.session.query(GLAccount).filter(
            GLAccount.is_header == True,
            GLAccount.id.in_(
                db.session.query(GLJournalLine.account_id).distinct()
            )
        ).all()
        
        if header_accounts_with_entries:
            for acc in header_accounts_with_entries:
                self.add_error(
                    'GL_ACCOUNTS',
                    f'❌ الحساب الرئيسي "{acc.full_name}" يحتوي على قيود مباشرة (يجب أن تكون القيود على الحسابات الفرعية فقط)',
                    'HIGH'
                )
        
        # فحص الحسابات بدون parent_id (يجب أن تكون رئيسية)
        orphan_detail_accounts = GLAccount.query.filter(
            GLAccount.parent_id == None,
            GLAccount.is_header == False,
            GLAccount.level > 0
        ).all()
        
        if orphan_detail_accounts:
            for acc in orphan_detail_accounts:
                self.add_warning(
                    'GL_ACCOUNTS',
                    f'⚠️ الحساب "{acc.full_name}" ليس له حساب أب ولكنه ليس رئيسي'
                )
        
        # فحص الحسابات المكررة (نفس الكود)
        duplicate_codes = db.session.query(
            GLAccount.code,
            func.count(GLAccount.id).label('count')
        ).group_by(GLAccount.code).having(func.count(GLAccount.id) > 1).all()
        
        if duplicate_codes:
            for code, count in duplicate_codes:
                self.add_error(
                    'GL_ACCOUNTS',
                    f'❌ الكود "{code}" مكرر {count} مرات',
                    'CRITICAL'
                )
        
        # التحقق من وجود الحسابات الأساسية الضرورية
        essential_accounts = {
            '1110': 'الصندوق',
            '1120': 'البنك',
            '1130': 'الذمم المدينة',
            '1140': 'المخزون',
            '2110': 'الذمم الدائنة',
            '3100': 'رأس المال',
            '4100': 'إيرادات المبيعات',
            '5100': 'تكلفة المبيعات'
        }
        
        for code, name in essential_accounts.items():
            acc = GLAccount.query.filter_by(code=code).first()
            if not acc:
                self.add_error(
                    'GL_ACCOUNTS',
                    f'❌ الحساب الأساسي "{name}" ({code}) غير موجود',
                    'CRITICAL'
                )
            elif not acc.is_active:
                self.add_warning(
                    'GL_ACCOUNTS',
                    f'⚠️ الحساب الأساسي "{name}" ({code}) غير نشط'
                )
        
        self.report['gl_accounts'] = {
            'total': total_accounts,
            'active': active_accounts,
            'header': header_accounts,
            'detail': detail_accounts,
            'by_type': dict(account_types)
        }
        
        print(f"\n✅ تم فحص {total_accounts} حساب")
    
    def audit_journal_entries(self):
        """2️⃣ فحص القيود المحاسبية والتوازن"""
        self.print_section("2️⃣ فحص القيود المحاسبية (Journal Entries)")
        
        # إحصائيات القيود
        total_entries = GLJournalEntry.query.count()
        posted_entries = GLJournalEntry.query.filter_by(is_posted=True).count()
        reversed_entries = GLJournalEntry.query.filter_by(is_reversed=True).count()
        
        print(f"📊 إحصائيات القيود:")
        print(f"   • إجمالي القيود: {total_entries}")
        print(f"   • القيود المرحلة: {posted_entries}")
        print(f"   • القيود المعكوسة: {reversed_entries}")
        
        # فحص توازن كل قيد (Debits = Credits)
        print(f"\n🔍 فحص توازن القيود المحاسبية...")
        unbalanced_entries = []
        
        for entry in GLJournalEntry.query.all():
            total_debit = Decimal('0')
            total_credit = Decimal('0')
            
            for line in entry.lines:
                total_debit += Decimal(str(line.debit or 0))
                total_credit += Decimal(str(line.credit or 0))
            
            # التحقق من التوازن (مع السماح بفرق بسيط جداً بسبب التقريب)
            difference = abs(total_debit - total_credit)
            
            if difference > Decimal('0.01'):  # أكثر من فلس واحد
                unbalanced_entries.append({
                    'entry': entry,
                    'debit': total_debit,
                    'credit': total_credit,
                    'difference': difference
                })
                
                self.add_error(
                    'JOURNAL_BALANCE',
                    f'❌ القيد {entry.entry_number} غير متوازن: مدين={total_debit} ≠ دائن={total_credit} (فرق={difference})',
                    'CRITICAL'
                )
            
            # التحقق من تطابق الإجماليات المحفوظة
            if entry.total_debit != total_debit or entry.total_credit != total_credit:
                self.add_error(
                    'JOURNAL_TOTALS',
                    f'❌ القيد {entry.entry_number}: الإجماليات المحفوظة لا تطابق السطور (محفوظ: {entry.total_debit}/{entry.total_credit}, فعلي: {total_debit}/{total_credit})',
                    'HIGH'
                )
        
        if unbalanced_entries:
            print(f"\n❌ تم العثور على {len(unbalanced_entries)} قيد غير متوازن!")
            for item in unbalanced_entries[:5]:  # عرض أول 5 فقط
                print(f"   • {item['entry'].entry_number}: فرق {item['difference']} درهم")
        else:
            print(f"\n✅ جميع القيود متوازنة ({total_entries} قيد)")
        
        # فحص القيود بدون سطور
        entries_without_lines = db.session.query(GLJournalEntry).outerjoin(
            GLJournalLine
        ).group_by(GLJournalEntry.id).having(
            func.count(GLJournalLine.id) == 0
        ).all()
        
        if entries_without_lines:
            for entry in entries_without_lines:
                self.add_error(
                    'JOURNAL_LINES',
                    f'❌ القيد {entry.entry_number} لا يحتوي على سطور',
                    'HIGH'
                )
        
        # فحص القيود بسطر واحد فقط (خطأ محاسبي)
        entries_one_line = db.session.query(GLJournalEntry).join(
            GLJournalLine
        ).group_by(GLJournalEntry.id).having(
            func.count(GLJournalLine.id) == 1
        ).all()
        
        if entries_one_line:
            for entry in entries_one_line:
                self.add_error(
                    'JOURNAL_LINES',
                    f'❌ القيد {entry.entry_number} يحتوي على سطر واحد فقط (القيد المحاسبي يجب أن يحتوي على طرفين على الأقل)',
                    'HIGH'
                )
        
        # فحص أنواع القيود
        entry_types = db.session.query(
            GLJournalEntry.entry_type,
            func.count(GLJournalEntry.id).label('count')
        ).group_by(GLJournalEntry.entry_type).all()
        
        print(f"\n📋 توزيع القيود حسب النوع:")
        for entry_type, count in entry_types:
            type_ar = {
                'manual': 'قيد يدوي',
                'auto': 'قيد تلقائي',
                'adjustment': 'قيد تسوية',
                'closing': 'قيد إقفال',
                'reversing': 'قيد عكسي'
            }.get(entry_type, entry_type)
            print(f"   • {type_ar}: {count}")
        
        self.report['journal_entries'] = {
            'total': total_entries,
            'posted': posted_entries,
            'reversed': reversed_entries,
            'unbalanced': len(unbalanced_entries),
            'by_type': dict(entry_types)
        }
    
    def audit_trial_balance(self):
        """3️⃣ فحص ميزان المراجعة"""
        self.print_section("3️⃣ فحص ميزان المراجعة (Trial Balance)")
        
        print(f"📊 حساب ميزان المراجعة...")
        
        # حساب الأرصدة لكل حساب
        trial_balance = []
        total_debit_balance = Decimal('0')
        total_credit_balance = Decimal('0')
        
        accounts = GLAccount.query.filter_by(is_active=True, is_header=False).all()
        
        for account in accounts:
            # حساب مجموع المدين والدائن
            debit_sum = db.session.query(func.sum(GLJournalLine.debit)).filter_by(
                account_id=account.id
            ).scalar() or Decimal('0')
            
            credit_sum = db.session.query(func.sum(GLJournalLine.credit)).filter_by(
                account_id=account.id
            ).scalar() or Decimal('0')
            
            # حساب الرصيد حسب نوع الحساب
            if account.type in ['asset', 'expense']:
                # حسابات مدينة بطبيعتها
                balance = debit_sum - credit_sum
                if balance > 0:
                    total_debit_balance += balance
                    debit_balance = balance
                    credit_balance = Decimal('0')
                else:
                    total_credit_balance += abs(balance)
                    debit_balance = Decimal('0')
                    credit_balance = abs(balance)
            else:
                # حسابات دائنة بطبيعتها (liability, equity, revenue)
                balance = credit_sum - debit_sum
                if balance > 0:
                    total_credit_balance += balance
                    debit_balance = Decimal('0')
                    credit_balance = balance
                else:
                    total_debit_balance += abs(balance)
                    debit_balance = abs(balance)
                    credit_balance = Decimal('0')
            
            if debit_sum > 0 or credit_sum > 0:  # فقط الحسابات التي لها حركة
                trial_balance.append({
                    'code': account.code,
                    'name': account.name_ar or account.name,
                    'type': account.type_ar,
                    'debit': float(debit_balance),
                    'credit': float(credit_balance)
                })
        
        # التحقق من توازن ميزان المراجعة
        difference = abs(total_debit_balance - total_credit_balance)
        
        print(f"\n{'':=<60}")
        print(f"إجمالي المدين:  {total_debit_balance:>20,.2f} درهم")
        print(f"إجمالي الدائن:  {total_credit_balance:>20,.2f} درهم")
        print(f"{'':=<60}")
        print(f"الفرق:          {difference:>20,.2f} درهم")
        print(f"{'':=<60}")
        
        if difference > Decimal('0.01'):
            self.add_error(
                'TRIAL_BALANCE',
                f'❌ ميزان المراجعة غير متوازن: الفرق = {difference} درهم',
                'CRITICAL'
            )
            print(f"\n❌ ميزان المراجعة غير متوازن!")
        else:
            print(f"\n✅ ميزان المراجعة متوازن")
        
        # عرض أكبر 10 حسابات رصيداً
        print(f"\n📋 أكبر 10 حسابات رصيداً:")
        sorted_tb = sorted(
            trial_balance, 
            key=lambda x: max(x['debit'], x['credit']), 
            reverse=True
        )[:10]
        
        table_data = []
        for item in sorted_tb:
            table_data.append([
                item['code'],
                item['name'][:30],
                item['type'],
                f"{item['debit']:,.2f}" if item['debit'] > 0 else "-",
                f"{item['credit']:,.2f}" if item['credit'] > 0 else "-"
            ])
        
        print(tabulate(
            table_data,
            headers=['الكود', 'اسم الحساب', 'النوع', 'مدين', 'دائن'],
            tablefmt='grid'
        ))
        
        self.report['trial_balance'] = {
            'total_debit': float(total_debit_balance),
            'total_credit': float(total_credit_balance),
            'difference': float(difference),
            'is_balanced': difference <= Decimal('0.01'),
            'accounts_count': len(trial_balance)
        }
    
    def audit_sales_integration(self):
        """4️⃣ فحص تكامل المبيعات مع المحاسبة"""
        self.print_section("4️⃣ فحص تكامل المبيعات (Sales Integration)")
        
        total_sales = Sale.query.count()
        confirmed_sales = Sale.query.filter_by(status='confirmed').count()
        
        print(f"📊 إحصائيات المبيعات:")
        print(f"   • إجمالي الفواتير: {total_sales}")
        print(f"   • الفواتير المؤكدة: {confirmed_sales}")
        
        # حساب إجمالي المبيعات
        total_sales_amount = db.session.query(
            func.sum(Sale.total_amount)
        ).filter_by(status='confirmed').scalar() or Decimal('0')
        
        total_paid = db.session.query(
            func.sum(Sale.paid_amount_aed)
        ).filter_by(status='confirmed').scalar() or Decimal('0')
        
        total_balance = db.session.query(
            func.sum(Sale.balance_due)
        ).filter_by(status='confirmed').scalar() or Decimal('0')
        
        print(f"\n💰 الإجماليات المالية:")
        print(f"   • إجمالي المبيعات: {total_sales_amount:,.2f} درهم")
        print(f"   • المبلغ المدفوع: {total_paid:,.2f} درهم")
        print(f"   • الرصيد المستحق: {total_balance:,.2f} درهم")
        
        # التحقق من المعادلة: Total = Paid + Balance
        calculated_balance = total_sales_amount - total_paid
        difference = abs(calculated_balance - total_balance)
        
        if difference > Decimal('1'):  # السماح بفرق درهم بسبب التقريب
            self.add_error(
                'SALES_BALANCE',
                f'❌ عدم توافق في أرصدة المبيعات: محسوب={calculated_balance} ≠ مسجل={total_balance} (فرق={difference})',
                'HIGH'
            )
        
        # فحص حالات الدفع
        payment_status_dist = db.session.query(
            Sale.payment_status,
            func.count(Sale.id).label('count'),
            func.sum(Sale.total_amount).label('total')
        ).filter_by(status='confirmed').group_by(Sale.payment_status).all()
        
        print(f"\n📋 توزيع حالات الدفع:")
        for status, count, total in payment_status_dist:
            status_ar = {
                'paid': 'مدفوع ✅',
                'partial': 'مدفوع جزئياً ⏳',
                'unpaid': 'غير مدفوع ❌'
            }.get(status, status)
            print(f"   • {status_ar}: {count} فاتورة ({total:,.2f} درهم)")
        
        # فحص الفواتير التي لها رصيد سالب (خطأ)
        negative_balance_sales = Sale.query.filter(
            Sale.balance_due < 0,
            Sale.status == 'confirmed'
        ).all()
        
        if negative_balance_sales:
            for sale in negative_balance_sales:
                self.add_error(
                    'SALES_BALANCE',
                    f'❌ الفاتورة {sale.sale_number} لها رصيد سالب: {sale.balance_due}',
                    'HIGH'
                )
        
        # فحص الفواتير المدفوعة ولكن حالتها "غير مدفوع"
        mismatched_status = Sale.query.filter(
            Sale.paid_amount_aed >= Sale.total_amount,
            Sale.payment_status != 'paid',
            Sale.status == 'confirmed'
        ).all()
        
        if mismatched_status:
            for sale in mismatched_status:
                self.add_warning(
                    'SALES_STATUS',
                    f'⚠️ الفاتورة {sale.sale_number} مدفوعة ولكن حالتها {sale.payment_status}'
                )
        
        self.report['sales'] = {
            'total_count': total_sales,
            'confirmed_count': confirmed_sales,
            'total_amount': float(total_sales_amount),
            'total_paid': float(total_paid),
            'total_balance': float(total_balance),
            'issues': len(negative_balance_sales) + len(mismatched_status)
        }
    
    def audit_cheques(self):
        """5️⃣ فحص الشيكات"""
        self.print_section("5️⃣ فحص نظام الشيكات (Cheques)")
        
        total_cheques = Cheque.query.count()
        incoming_cheques = Cheque.query.filter_by(cheque_type='incoming').count()
        outgoing_cheques = Cheque.query.filter_by(cheque_type='outgoing').count()
        
        print(f"📊 إحصائيات الشيكات:")
        print(f"   • إجمالي الشيكات: {total_cheques}")
        print(f"   • الشيكات الواردة: {incoming_cheques}")
        print(f"   • الشيكات الصادرة: {outgoing_cheques}")
        
        # حسب الحالة
        cheque_status_dist = db.session.query(
            Cheque.status,
            func.count(Cheque.id).label('count'),
            func.sum(Cheque.amount_aed).label('total')
        ).group_by(Cheque.status).all()
        
        print(f"\n📋 توزيع الشيكات حسب الحالة:")
        for status, count, total in cheque_status_dist:
            status_ar = {
                'pending': 'معلق ⏳',
                'deposited': 'مودع 🏦',
                'cleared': 'مصروف ✅',
                'bounced': 'مرتد ❌',
                'cancelled': 'ملغي 🚫'
            }.get(status, status)
            print(f"   • {status_ar}: {count} شيك ({total or 0:,.2f} درهم)")
        
        # الشيكات المعلقة (pending)
        pending_cheques_amount = db.session.query(
            func.sum(Cheque.amount_aed)
        ).filter_by(status='pending', is_active=True).scalar() or Decimal('0')
        
        print(f"\n💰 الشيكات المعلقة:")
        print(f"   • المبلغ الإجمالي: {pending_cheques_amount:,.2f} درهم")
        
        # التحقق من المحاسبة الدقيقة للشيكات
        # الشيكات المعلقة يجب ألا تُحسب في الإيرادات الفعلية
        
        # فحص الشيكات بدون تاريخ استحقاق
        cheques_no_due_date = Cheque.query.filter_by(due_date=None).count()
        if cheques_no_due_date > 0:
            self.add_warning(
                'CHEQUES',
                f'⚠️ يوجد {cheques_no_due_date} شيك بدون تاريخ استحقاق'
            )
        
        # فحص فرق العملة
        cheques_with_fx_gain_loss = Cheque.query.filter(
            Cheque.currency_gain_loss != 0,
            Cheque.currency_gain_loss != None
        ).count()
        
        if cheques_with_fx_gain_loss > 0:
            total_fx_gain_loss = db.session.query(
                func.sum(Cheque.currency_gain_loss)
            ).scalar() or Decimal('0')
            
            print(f"\n💱 فرق العملة:")
            print(f"   • عدد الشيكات المتأثرة: {cheques_with_fx_gain_loss}")
            print(f"   • صافي ربح/خسارة العملة: {total_fx_gain_loss:,.2f} درهم")
        
        self.report['cheques'] = {
            'total': total_cheques,
            'incoming': incoming_cheques,
            'outgoing': outgoing_cheques,
            'pending_amount': float(pending_cheques_amount),
            'fx_affected': cheques_with_fx_gain_loss
        }
    
    def audit_fixed_assets(self):
        """6️⃣ فحص الأصول الثابتة"""
        self.print_section("6️⃣ فحص الأصول الثابتة (Fixed Assets)")
        
        total_assets = FixedAsset.query.count()
        active_assets = FixedAsset.query.filter_by(status='active').count()
        fully_depreciated = FixedAsset.query.filter_by(status='fully_depreciated').count()
        
        print(f"📊 إحصائيات الأصول الثابتة:")
        print(f"   • إجمالي الأصول: {total_assets}")
        print(f"   • الأصول النشطة: {active_assets}")
        print(f"   • الأصول المستهلكة بالكامل: {fully_depreciated}")
        
        # حساب القيم
        total_cost = db.session.query(
            func.sum(FixedAsset.purchase_price)
        ).scalar() or Decimal('0')
        
        total_accumulated_dep = db.session.query(
            func.sum(FixedAsset.accumulated_depreciation)
        ).scalar() or Decimal('0')
        
        total_book_value = total_cost - total_accumulated_dep
        
        print(f"\n💰 القيم المالية:")
        print(f"   • التكلفة الأصلية: {total_cost:,.2f} درهم")
        print(f"   • مجمع الاستهلاك: {total_accumulated_dep:,.2f} درهم")
        print(f"   • القيمة الدفترية: {total_book_value:,.2f} درهم")
        
        # فحص الأصول بقيمة دفترية سالبة (خطأ)
        negative_book_value = FixedAsset.query.filter(
            FixedAsset.book_value < 0
        ).all()
        
        if negative_book_value:
            for asset in negative_book_value:
                self.add_error(
                    'FIXED_ASSETS',
                    f'❌ الأصل "{asset.name_ar}" له قيمة دفترية سالبة: {asset.book_value}',
                    'HIGH'
                )
        
        # فحص الأصول المستهلكة بأكثر من التكلفة
        over_depreciated = FixedAsset.query.filter(
            FixedAsset.accumulated_depreciation > FixedAsset.purchase_price
        ).all()
        
        if over_depreciated:
            for asset in over_depreciated:
                self.add_error(
                    'FIXED_ASSETS',
                    f'❌ الأصل "{asset.name_ar}" مستهلك بأكثر من التكلفة',
                    'HIGH'
                )
        
        self.report['fixed_assets'] = {
            'total': total_assets,
            'active': active_assets,
            'total_cost': float(total_cost),
            'accumulated_depreciation': float(total_accumulated_dep),
            'book_value': float(total_book_value)
        }
    
    def audit_cost_centers_budgets(self):
        """7️⃣ فحص مراكز التكلفة والميزانيات"""
        self.print_section("7️⃣ فحص مراكز التكلفة والميزانيات")
        
        total_cost_centers = CostCenter.query.count()
        active_cost_centers = CostCenter.query.filter_by(is_active=True).count()
        
        print(f"📊 إحصائيات مراكز التكلفة:")
        print(f"   • إجمالي المراكز: {total_cost_centers}")
        print(f"   • المراكز النشطة: {active_cost_centers}")
        
        # الميزانيات
        total_budgets = Budget.query.count()
        active_budgets = Budget.query.filter_by(status='active').count()
        
        print(f"\n📋 إحصائيات الميزانيات:")
        print(f"   • إجمالي الميزانيات: {total_budgets}")
        print(f"   • الميزانيات النشطة: {active_budgets}")
        
        if active_budgets > 0:
            total_budgeted = db.session.query(
                func.sum(Budget.total_budgeted)
            ).filter_by(status='active').scalar() or Decimal('0')
            
            total_actual = db.session.query(
                func.sum(Budget.total_actual)
            ).filter_by(status='active').scalar() or Decimal('0')
            
            print(f"\n💰 الميزانيات النشطة:")
            print(f"   • المبلغ المخطط: {total_budgeted:,.2f} درهم")
            print(f"   • المبلغ الفعلي: {total_actual:,.2f} درهم")
            print(f"   • الانحراف: {total_actual - total_budgeted:,.2f} درهم")
        
        self.report['cost_centers'] = {
            'total': total_cost_centers,
            'active': active_cost_centers
        }
        
        self.report['budgets'] = {
            'total': total_budgets,
            'active': active_budgets
        }
    
    def audit_customers_suppliers(self):
        """8️⃣ فحص العملاء والموردين"""
        self.print_section("8️⃣ فحص أرصدة العملاء والموردين")
        
        # العملاء
        total_customers = Customer.query.count()
        active_customers = Customer.query.filter_by(is_active=True).count()
        
        print(f"📊 إحصائيات العملاء:")
        print(f"   • إجمالي العملاء: {total_customers}")
        print(f"   • العملاء النشطين: {active_customers}")
        
        # حساب إجمالي الذمم المدينة
        total_receivables = Decimal('0')
        for customer in Customer.query.filter_by(is_active=True).all():
            balance = customer.get_balance()
            total_receivables += balance
        
        print(f"   • إجمالي الذمم المدينة: {total_receivables:,.2f} درهم")
        
        # الموردين
        total_suppliers = Supplier.query.count()
        active_suppliers = Supplier.query.filter_by(is_active=True).count()
        
        print(f"\n📊 إحصائيات الموردين:")
        print(f"   • إجمالي الموردين: {total_suppliers}")
        print(f"   • الموردين النشطين: {active_suppliers}")
        
        # حساب إجمالي الذمم الدائنة
        total_payables = Decimal('0')
        for supplier in Supplier.query.filter_by(is_active=True).all():
            balance = supplier.get_balance_aed()
            total_payables += balance
        
        print(f"   • إجمالي الذمم الدائنة: {total_payables:,.2f} درهم")
        
        # مقارنة مع حسابات دفتر الأستاذ
        ar_account = GLAccount.query.filter_by(code='1130').first()
        if ar_account:
            ar_balance = ar_account.get_balance()
            ar_diff = abs(ar_balance - total_receivables)
            
            print(f"\n🔍 مطابقة الذمم المدينة:")
            print(f"   • رصيد دفتر الأستاذ: {ar_balance:,.2f} درهم")
            print(f"   • مجموع أرصدة العملاء: {total_receivables:,.2f} درهم")
            print(f"   • الفرق: {ar_diff:,.2f} درهم")
            
            if ar_diff > Decimal('10'):  # السماح بفرق 10 دراهم
                self.add_warning(
                    'RECEIVABLES',
                    f'⚠️ فرق في الذمم المدينة: {ar_diff} درهم'
                )
        
        ap_account = GLAccount.query.filter_by(code='2110').first()
        if ap_account:
            ap_balance = ap_account.get_balance()
            ap_diff = abs(ap_balance - total_payables)
            
            print(f"\n🔍 مطابقة الذمم الدائنة:")
            print(f"   • رصيد دفتر الأستاذ: {ap_balance:,.2f} درهم")
            print(f"   • مجموع أرصدة الموردين: {total_payables:,.2f} درهم")
            print(f"   • الفرق: {ap_diff:,.2f} درهم")
            
            if ap_diff > Decimal('10'):
                self.add_warning(
                    'PAYABLES',
                    f'⚠️ فرق في الذمم الدائنة: {ap_diff} درهم'
                )
        
        self.report['customers'] = {
            'total': total_customers,
            'active': active_customers,
            'total_receivables': float(total_receivables)
        }
        
        self.report['suppliers'] = {
            'total': total_suppliers,
            'active': active_suppliers,
            'total_payables': float(total_payables)
        }
    
    def generate_final_report(self):
        """إنشاء التقرير النهائي"""
        self.print_section("📋 التقرير النهائي للمراجعة المحاسبية")
        
        print(f"\n{'='*80}")
        print(f"  ملخص التدقيق")
        print(f"{'='*80}\n")
        
        # إحصائيات
        print(f"🔴 الأخطاء الحرجة: {len([e for e in self.errors if e['severity'] == 'CRITICAL'])}")
        print(f"🟠 الأخطاء العادية: {len([e for e in self.errors if e['severity'] in ['HIGH', 'MEDIUM']])}")
        print(f"🟡 التحذيرات: {len(self.warnings)}")
        print(f"🔵 التوصيات: {len(self.recommendations)}")
        
        # الأخطاء الحرجة
        critical_errors = [e for e in self.errors if e['severity'] == 'CRITICAL']
        if critical_errors:
            print(f"\n{'='*80}")
            print(f"  ❌ الأخطاء الحرجة التي تحتاج إصلاح فوري")
            print(f"{'='*80}\n")
            for error in critical_errors:
                print(f"  [{error['category']}] {error['message']}")
        
        # الأخطاء العادية
        high_errors = [e for e in self.errors if e['severity'] == 'HIGH']
        if high_errors:
            print(f"\n{'='*80}")
            print(f"  🟠 الأخطاء العادية")
            print(f"{'='*80}\n")
            for error in high_errors[:10]:  # أول 10
                print(f"  [{error['category']}] {error['message']}")
            
            if len(high_errors) > 10:
                print(f"\n  ... و {len(high_errors) - 10} خطأ آخر")
        
        # التحذيرات
        if self.warnings:
            print(f"\n{'='*80}")
            print(f"  ⚠️ التحذيرات")
            print(f"{'='*80}\n")
            for warning in self.warnings[:10]:
                print(f"  [{warning['category']}] {warning['message']}")
            
            if len(self.warnings) > 10:
                print(f"\n  ... و {len(self.warnings) - 10} تحذير آخر")
        
        # التقييم العام
        print(f"\n{'='*80}")
        print(f"  📊 التقييم العام للنظام المحاسبي")
        print(f"{'='*80}\n")
        
        if len(critical_errors) == 0 and len(high_errors) == 0:
            print(f"  ✅ النظام المحاسبي سليم ومتوازن")
            grade = "ممتاز"
            score = 95
        elif len(critical_errors) == 0:
            print(f"  ✓ النظام المحاسبي جيد مع بعض الأخطاء البسيطة")
            grade = "جيد جداً"
            score = 80
        elif len(critical_errors) <= 3:
            print(f"  ⚠️ النظام المحاسبي يحتاج إلى إصلاحات")
            grade = "جيد"
            score = 65
        else:
            print(f"  ❌ النظام المحاسبي يحتاج إلى مراجعة شاملة")
            grade = "يحتاج تحسين"
            score = 40
        
        print(f"\n  التقييم: {grade}")
        print(f"  الدرجة: {score}/100")
        
        # حفظ التقرير
        report_data = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'critical_errors': len(critical_errors),
                'high_errors': len(high_errors),
                'warnings': len(self.warnings),
                'recommendations': len(self.recommendations),
                'grade': grade,
                'score': score
            },
            'details': self.report,
            'errors': [
                {
                    'category': e['category'],
                    'message': e['message'],
                    'severity': e['severity'],
                    'timestamp': e['timestamp'].isoformat()
                } for e in self.errors
            ],
            'warnings': [
                {
                    'category': w['category'],
                    'message': w['message'],
                    'timestamp': w['timestamp'].isoformat()
                } for w in self.warnings
            ]
        }
        
        report_filename = f'accounting_audit_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(report_filename, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        
        print(f"\n\n📄 تم حفظ التقرير الكامل في: {report_filename}")
        
        return report_data


def main():
    """تشغيل الفحص الشامل"""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║         🔍 نظام الفحص الشامل للنظام المحاسبي                                ║
║         Comprehensive Accounting System Audit                                ║
║                                                                              ║
║         المراجع: نظام تدقيق محاسبي محترف                                    ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)
    
    app = create_app()
    with app.app_context():
        auditor = AccountingAuditor()
        
        # تنفيذ الفحوصات
        auditor.audit_gl_accounts()
        auditor.audit_journal_entries()
        auditor.audit_trial_balance()
        auditor.audit_sales_integration()
        auditor.audit_cheques()
        auditor.audit_fixed_assets()
        auditor.audit_cost_centers_budgets()
        auditor.audit_customers_suppliers()
        
        # إنشاء التقرير النهائي
        final_report = auditor.generate_final_report()
        
        print(f"\n\n✅ اكتمل الفحص الشامل بنجاح!")
        
        return final_report


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n\n❌ خطأ أثناء الفحص: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

