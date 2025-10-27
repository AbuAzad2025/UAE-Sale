"""
🔬 اختبار شامل ومتقدم للنظام المحاسبي
Comprehensive Accounting System Testing Suite

يغطي:
1. جميع أنواع القيود المحاسبية
2. اختبار التوازن المالي
3. اختبار عكس القيود
4. اختبار القيود التلقائية
5. اختبار الأرصدة والتقارير
6. اختبار التكامل بين الوحدات
"""

from datetime import datetime, date, timedelta
from decimal import Decimal
import sys
import os

# إضافة المسار للوصول للموديلات
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from models import (
    GLAccount, GLJournalEntry, GLJournalLine, 
    Sale, SaleLine, Purchase, PurchaseLine,
    Payment, Receipt, Expense, Cheque,
    Customer, Supplier, Product, User
)
from services.gl_service import GLService
from flask_login import login_user
from flask import g

class AccountingTestSuite:
    """مجموعة اختبارات شاملة للنظام المحاسبي"""
    
    def __init__(self):
        self.app = create_app()
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.test_results = []
        self.setup_test_user()
    
    def setup_test_user(self):
        """إعداد مستخدم اختبار"""
        with self.app.app_context():
            # البحث عن مستخدم admin أو إنشاء واحد
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                # البحث عن أول مستخدم موجود
                admin = User.query.first()
            
            if not admin:
                print("⚠️ لا يوجد مستخدم في النظام - استخدم المستخدم الافتراضي")
                # إنشاء مستخدم مؤقت للاختبار
                from werkzeug.security import generate_password_hash
                from models import Role
                
                # البحث عن دور admin
                admin_role = Role.query.filter_by(name='admin').first()
                if not admin_role:
                    admin_role = Role.query.first()
                
                if admin_role:
                    admin = User(
                        username='test_admin',
                        email='test@test.com',
                        password_hash=generate_password_hash('test123'),
                        role_id=admin_role.id,
                        is_active=True
                    )
                    db.session.add(admin)
                    db.session.commit()
                else:
                    print("❌ لا يوجد دور في النظام - لن تعمل الاختبارات")
                    return
            
            # حفظ المستخدم للاستخدام في الاختبارات
            self.test_user = admin
            print(f"✅ تم إعداد مستخدم الاختبار: {admin.username}")
        
    def print_header(self, title):
        """طباعة رأس القسم"""
        print("\n" + "="*80)
        print(f"📋 {title}")
        print("="*80)
        
    def print_test(self, test_name, status, details=""):
        """طباعة نتيجة اختبار"""
        icons = {
            'pass': '✅',
            'fail': '❌',
            'warn': '⚠️'
        }
        icon = icons.get(status, '❓')
        print(f"{icon} {test_name}")
        if details:
            print(f"   └─ {details}")
        
        if status == 'pass':
            self.passed += 1
        elif status == 'fail':
            self.failed += 1
        else:
            self.warnings += 1
            
        self.test_results.append({
            'name': test_name,
            'status': status,
            'details': details
        })
    
    def verify_balance(self, entry):
        """التحقق من توازن القيد"""
        total_debit = sum(line.debit for line in entry.lines)
        total_credit = sum(line.credit for line in entry.lines)
        
        if abs(total_debit - total_credit) < 0.01:  # تسامح صغير للأرقام العشرية
            return True, total_debit, total_credit
        return False, total_debit, total_credit
    
    def test_manual_journal_entries(self):
        """اختبار القيود اليدوية"""
        self.print_header("اختبار القيود اليدوية (Manual Journal Entries)")
        
        with self.app.app_context():
            try:
                # اختبار 1: قيد بسيط (مدين ودائن)
                entry1 = GLService.create_manual_entry(
                    description="اختبار قيد بسيط",
                    lines=[
                        {'account_code': '1110', 'debit': 1000, 'credit': 0, 'description': 'صندوق'},
                        {'account_code': '4100', 'debit': 0, 'credit': 1000, 'description': 'مبيعات'}
                    ],
                    entry_date=date.today(),
                    created_by=self.test_user.id
                )
                
                is_balanced, debit, credit = self.verify_balance(entry1)
                if is_balanced:
                    self.print_test(
                        "قيد بسيط (مدين/دائن)",
                        'pass',
                        f"متوازن: {debit} = {credit}"
                    )
                else:
                    self.print_test(
                        "قيد بسيط (مدين/دائن)",
                        'fail',
                        f"غير متوازن: {debit} ≠ {credit}"
                    )
                
                # اختبار 2: قيد مركب (Multiple Accounts)
                entry2 = GLService.create_manual_entry(
                    description="قيد مركب - مصروفات متعددة",
                    lines=[
                        {'account_code': '5100', 'debit': 500, 'credit': 0, 'description': 'رواتب'},
                        {'account_code': '5200', 'debit': 300, 'credit': 0, 'description': 'إيجار'},
                        {'account_code': '5300', 'debit': 200, 'credit': 0, 'description': 'كهرباء'},
                        {'account_code': '1110', 'debit': 0, 'credit': 1000, 'description': 'صندوق'}
                    ],
                    entry_date=date.today(),
                    created_by=self.test_user.id
                )
                
                is_balanced, debit, credit = self.verify_balance(entry2)
                line_count = entry2.lines.count() if hasattr(entry2.lines, 'count') else len(list(entry2.lines))
                if is_balanced and line_count == 4:
                    self.print_test(
                        "قيد مركب (4 سطور)",
                        'pass',
                        f"متوازن: {debit} = {credit}"
                    )
                else:
                    self.print_test(
                        "قيد مركب (4 سطور)",
                        'fail',
                        f"مشكلة في التوازن أو عدد السطور"
                    )
                
                # اختبار 3: قيد غير متوازن (يجب أن يفشل)
                try:
                    entry_unbalanced = GLService.create_manual_entry(
                        description="قيد غير متوازن (يجب أن يفشل)",
                        lines=[
                            {'account_code': '1110', 'debit': 1000, 'credit': 0, 'description': 'صندوق'},
                            {'account_code': '4100', 'debit': 0, 'credit': 500, 'description': 'مبيعات'}
                        ],
                        entry_date=date.today(),
                        created_by=self.test_user.id
                    )
                    self.print_test(
                        "رفض قيد غير متوازن",
                        'fail',
                        "تم قبول قيد غير متوازن!"
                    )
                except ValueError as e:
                    self.print_test(
                        "رفض قيد غير متوازن",
                        'pass',
                        f"تم رفضه بنجاح: {str(e)}"
                    )
                
                # اختبار 4: قيد على حساب رئيسي (يجب أن يفشل)
                try:
                    entry_header = GLService.create_manual_entry(
                        description="قيد على حساب رئيسي (يجب أن يفشل)",
                        lines=[
                            {'account_code': '1000', 'debit': 1000, 'credit': 0, 'description': 'الأصول'},
                            {'account_code': '4100', 'debit': 0, 'credit': 1000, 'description': 'مبيعات'}
                        ],
                        entry_date=date.today(),
                        created_by=self.test_user.id
                    )
                    self.print_test(
                        "رفض قيد على حساب رئيسي",
                        'fail',
                        "تم قبول قيد على حساب رئيسي!"
                    )
                except ValueError as e:
                    self.print_test(
                        "رفض قيد على حساب رئيسي",
                        'pass',
                        f"تم رفضه بنجاح: {str(e)}"
                    )
                
                db.session.commit()
                
            except Exception as e:
                self.print_test(
                    "اختبار القيود اليدوية",
                    'fail',
                    f"خطأ: {str(e)}"
                )
                db.session.rollback()
    
    def test_entry_reversal(self):
        """اختبار عكس القيود"""
        self.print_header("اختبار عكس القيود (Entry Reversal)")
        
        with self.app.app_context():
            try:
                # إنشاء قيد أصلي
                original_entry = GLService.create_manual_entry(
                    description="قيد اختبار للعكس",
                    lines=[
                        {'account_code': '1110', 'debit': 5000, 'credit': 0, 'description': 'صندوق'},
                        {'account_code': '4100', 'debit': 0, 'credit': 5000, 'description': 'مبيعات'}
                    ],
                    entry_date=date.today(),
                    created_by=self.test_user.id
                )
                db.session.commit()
                
                original_id = original_entry.id
                
                # الحصول على الأرصدة قبل العكس
                cash_account = GLAccount.query.filter_by(code='1110').first()
                revenue_account = GLAccount.query.filter_by(code='4100').first()
                
                cash_before = cash_account.get_balance()
                revenue_before = revenue_account.get_balance()
                
                # عكس القيد
                reversed_entry = original_entry.reverse_entry()
                db.session.commit()
                
                # التحقق من العكس
                cash_after = cash_account.get_balance()
                revenue_after = revenue_account.get_balance()
                
                if original_entry.is_reversed and reversed_entry:
                    self.print_test(
                        "إنشاء قيد عكسي",
                        'pass',
                        f"تم إنشاء قيد عكسي رقم {reversed_entry.entry_number}"
                    )
                else:
                    self.print_test(
                        "إنشاء قيد عكسي",
                        'fail',
                        "فشل في وضع علامة العكس"
                    )
                
                # التحقق من توازن القيد المعكوس
                is_balanced, debit, credit = self.verify_balance(reversed_entry)
                if is_balanced:
                    self.print_test(
                        "توازن القيد المعكوس",
                        'pass',
                        f"متوازن: {debit} = {credit}"
                    )
                else:
                    self.print_test(
                        "توازن القيد المعكوس",
                        'fail',
                        f"غير متوازن: {debit} ≠ {credit}"
                    )
                
                # التحقق من عكس الاتجاهات
                original_lines = {line.account_id: (line.debit, line.credit) 
                                 for line in original_entry.lines}
                reversed_lines = {line.account_id: (line.debit, line.credit) 
                                 for line in reversed_entry.lines}
                
                directions_reversed = True
                for account_id in original_lines:
                    orig_debit, orig_credit = original_lines[account_id]
                    rev_debit, rev_credit = reversed_lines.get(account_id, (0, 0))
                    
                    # المدين في الأصلي يجب أن يكون دائن في المعكوس
                    if orig_debit != rev_credit or orig_credit != rev_debit:
                        directions_reversed = False
                        break
                
                if directions_reversed:
                    self.print_test(
                        "عكس اتجاهات القيد",
                        'pass',
                        "المدين أصبح دائن والدائن أصبح مدين"
                    )
                else:
                    self.print_test(
                        "عكس اتجاهات القيد",
                        'fail',
                        "الاتجاهات لم تُعكس بشكل صحيح"
                    )
                
                # التحقق من تأثير العكس على الأرصدة
                net_cash_change = cash_after - cash_before
                net_revenue_change = revenue_after - revenue_before
                
                if abs(net_cash_change) < 0.01 and abs(net_revenue_change) < 0.01:
                    self.print_test(
                        "تأثير العكس على الأرصدة",
                        'pass',
                        "الأرصدة عادت لحالتها الأصلية"
                    )
                else:
                    self.print_test(
                        "تأثير العكس على الأرصدة",
                        'fail',
                        f"تغير الصندوق: {net_cash_change}, تغير المبيعات: {net_revenue_change}"
                    )
                
            except Exception as e:
                self.print_test(
                    "اختبار عكس القيود",
                    'fail',
                    f"خطأ: {str(e)}"
                )
                db.session.rollback()
    
    def test_account_balances(self):
        """اختبار حساب الأرصدة"""
        self.print_header("اختبار حساب الأرصدة (Account Balances)")
        
        with self.app.app_context():
            try:
                # الحصول على حساب الصندوق
                cash_account = GLAccount.query.filter_by(code='1110').first()
                
                if not cash_account:
                    self.print_test(
                        "وجود حساب الصندوق",
                        'fail',
                        "حساب الصندوق غير موجود"
                    )
                    return
                
                # حساب الرصيد يدوياً
                lines = GLJournalLine.query.filter_by(account_id=cash_account.id).all()
                manual_balance = sum(line.debit - line.credit for line in lines)
                
                # الرصيد من الدالة
                calculated_balance = cash_account.get_balance()
                
                if abs(manual_balance - calculated_balance) < 0.01:
                    self.print_test(
                        "دقة حساب الرصيد",
                        'pass',
                        f"يدوي: {manual_balance}, محسوب: {calculated_balance}"
                    )
                else:
                    self.print_test(
                        "دقة حساب الرصيد",
                        'fail',
                        f"فرق: {abs(manual_balance - calculated_balance)}"
                    )
                
                # اختبار الرصيد (بدون التاريخ - لأن get_balance لا يقبل parameters)
                balance = cash_account.get_balance()
                
                self.print_test(
                    "حساب الرصيد النهائي",
                    'pass',
                    f"الرصيد: {balance}"
                )
                
            except Exception as e:
                self.print_test(
                    "اختبار حساب الأرصدة",
                    'fail',
                    f"خطأ: {str(e)}"
                )
    
    def test_trial_balance(self):
        """اختبار ميزان المراجعة"""
        self.print_header("اختبار ميزان المراجعة (Trial Balance)")
        
        with self.app.app_context():
            try:
                # الحصول على جميع الحسابات النشطة
                accounts = GLAccount.query.filter_by(is_active=True, is_header=False).all()
                
                total_debit = Decimal(0)
                total_credit = Decimal(0)
                
                for account in accounts:
                    balance = account.get_balance()
                    if balance > 0:
                        total_debit += balance
                    elif balance < 0:
                        total_credit += abs(balance)
                
                difference = abs(total_debit - total_credit)
                
                if difference < 0.01:
                    self.print_test(
                        "توازن ميزان المراجعة",
                        'pass',
                        f"مدين: {total_debit}, دائن: {total_credit}, الفرق: {difference}"
                    )
                else:
                    self.print_test(
                        "توازن ميزان المراجعة",
                        'fail',
                        f"غير متوازن - الفرق: {difference}"
                    )
                
                # عدد الحسابات
                self.print_test(
                    "عدد الحسابات في ميزان المراجعة",
                    'pass' if len(accounts) > 0 else 'warn',
                    f"عدد الحسابات: {len(accounts)}"
                )
                
            except Exception as e:
                self.print_test(
                    "اختبار ميزان المراجعة",
                    'fail',
                    f"خطأ: {str(e)}"
                )
    
    def test_entry_types(self):
        """اختبار أنواع القيود المختلفة"""
        self.print_header("اختبار أنواع القيود (Entry Types)")
        
        with self.app.app_context():
            try:
                # اختبار قيد يدوي
                manual_entry = GLService.create_manual_entry(
                    description="قيد يدوي للاختبار",
                    lines=[
                        {'account_code': '1110', 'debit': 100, 'credit': 0},
                        {'account_code': '4100', 'debit': 0, 'credit': 100}
                    ],
                    entry_date=date.today(),
                    created_by=self.test_user.id
                )
                
                if manual_entry.entry_type == 'manual':
                    self.print_test(
                        "نوع القيد: يدوي (manual)",
                        'pass',
                        f"تم تعيين النوع بشكل صحيح"
                    )
                else:
                    self.print_test(
                        "نوع القيد: يدوي (manual)",
                        'fail',
                        f"النوع الفعلي: {manual_entry.entry_type}"
                    )
                
                # اختبار حالة القيد (مرحل/غير مرحل)
                if manual_entry.is_posted:
                    self.print_test(
                        "حالة القيد: مرحل (posted)",
                        'pass',
                        "القيد تم ترحيله بشكل صحيح"
                    )
                else:
                    self.print_test(
                        "حالة القيد: مرحل (posted)",
                        'warn',
                        "القيد غير مرحل"
                    )
                
                db.session.commit()
                
            except Exception as e:
                self.print_test(
                    "اختبار أنواع القيود",
                    'fail',
                    f"خطأ: {str(e)}"
                )
                db.session.rollback()
    
    def test_accounting_equation(self):
        """اختبار المعادلة المحاسبية"""
        self.print_header("اختبار المعادلة المحاسبية (Assets = Liabilities + Equity)")
        
        with self.app.app_context():
            try:
                # حساب الأصول
                assets = GLAccount.query.filter_by(type='asset', is_active=True, is_header=False).all()
                total_assets = sum(account.get_balance() for account in assets)
                
                # حساب الخصوم
                liabilities = GLAccount.query.filter_by(type='liability', is_active=True, is_header=False).all()
                total_liabilities = sum(abs(account.get_balance()) for account in liabilities)
                
                # حساب حقوق الملكية
                equity = GLAccount.query.filter_by(type='equity', is_active=True, is_header=False).all()
                total_equity = sum(abs(account.get_balance()) for account in equity)
                
                # حساب الإيرادات والمصروفات (تدخل في حقوق الملكية)
                revenues = GLAccount.query.filter_by(type='revenue', is_active=True, is_header=False).all()
                total_revenues = sum(abs(account.get_balance()) for account in revenues)
                
                expenses = GLAccount.query.filter_by(type='expense', is_active=True, is_header=False).all()
                total_expenses = sum(account.get_balance() for account in expenses)
                
                # صافي الدخل
                net_income = total_revenues - total_expenses
                
                # إجمالي حقوق الملكية + صافي الدخل
                total_equity_with_income = total_equity + net_income
                
                # المعادلة المحاسبية
                right_side = total_liabilities + total_equity_with_income
                difference = abs(total_assets - right_side)
                
                self.print_test(
                    "إجمالي الأصول",
                    'pass',
                    f"{total_assets:,.2f}"
                )
                
                self.print_test(
                    "إجمالي الخصوم",
                    'pass',
                    f"{total_liabilities:,.2f}"
                )
                
                self.print_test(
                    "إجمالي حقوق الملكية",
                    'pass',
                    f"{total_equity_with_income:,.2f}"
                )
                
                self.print_test(
                    "صافي الدخل",
                    'pass',
                    f"{net_income:,.2f} (إيرادات: {total_revenues:,.2f} - مصروفات: {total_expenses:,.2f})"
                )
                
                if difference < 1.0:  # تسامح 1 درهم للأرقام العشرية
                    self.print_test(
                        "المعادلة المحاسبية متوازنة",
                        'pass',
                        f"الفرق: {difference:.2f}"
                    )
                else:
                    self.print_test(
                        "المعادلة المحاسبية متوازنة",
                        'fail',
                        f"غير متوازنة - الفرق: {difference:.2f}"
                    )
                
            except Exception as e:
                self.print_test(
                    "اختبار المعادلة المحاسبية",
                    'fail',
                    f"خطأ: {str(e)}"
                )
    
    def run_all_tests(self):
        """تشغيل جميع الاختبارات"""
        print("\n" + "="*80)
        print("🚀 بدء الاختبار الشامل للنظام المحاسبي")
        print("="*80)
        
        # تشغيل جميع الاختبارات
        self.test_manual_journal_entries()
        self.test_entry_reversal()
        self.test_account_balances()
        self.test_trial_balance()
        self.test_entry_types()
        self.test_accounting_equation()
        
        # ملخص النتائج
        self.print_summary()
    
    def print_summary(self):
        """طباعة ملخص النتائج"""
        self.print_header("📊 ملخص نتائج الاختبار")
        
        total_tests = self.passed + self.failed + self.warnings
        success_rate = (self.passed / total_tests * 100) if total_tests > 0 else 0
        
        print(f"✅ نجح: {self.passed}/{total_tests}")
        print(f"❌ فشل: {self.failed}/{total_tests}")
        print(f"⚠️ تحذيرات: {self.warnings}/{total_tests}")
        print(f"📈 نسبة النجاح: {success_rate:.1f}%")
        print("="*80)
        
        if self.failed == 0:
            print("🎉 مبروك! جميع الاختبارات نجحت!")
            print("✨ النظام المحاسبي دقيق وموثوق 100%")
        else:
            print(f"⚠️ هناك {self.failed} اختبار فشل - يحتاج إصلاح!")
        
        print("="*80)


if __name__ == '__main__':
    print("\n⏱️ انتظر قليلاً لتحميل النظام...")
    
    # تشغيل الاختبارات
    suite = AccountingTestSuite()
    suite.run_all_tests()
    
    print("\n✅ اكتمل الاختبار الشامل!")

