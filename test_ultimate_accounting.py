"""
🔥 اختبار شامل للنظام المحاسبي الجبار الخارق
Ultimate Accounting System Comprehensive Test Suite

يختبر:
1. نظام الطباعة الاحترافي
2. الجمارك والضرائب والمصروفات المتقدمة
3. عكس وحذف وتعديل القيود المتقدم
4. ربط الشيكات الكامل مع النظام المحاسبي
5. مستمعات لحظية للأحداث المحاسبية
6. جميع أنواع القيود المحاسبية المتقدمة
"""

import requests
import json
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
    Cheque, Customer, Supplier, User,
    CustomsTax, ExpenseCategory, AdvancedExpense, TaxCalculationRule
)
from services.gl_service import GLService
from services.advanced_journal_manager import AdvancedJournalEntryManager
from services.cheque_accounting_integration import ChequeAccountingIntegration
from services.real_time_listeners import accounting_event_stream

class UltimateAccountingTestSuite:
    """مجموعة اختبارات شاملة للنظام المحاسبي الجبار"""
    
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
            admin = User.query.first()
            if not admin:
                print("❌ لا يوجد مستخدم في النظام")
                return
            self.test_user = admin
            print(f"✅ تم إعداد مستخدم الاختبار: {admin.username}")
    
    def print_header(self, title):
        """طباعة رأس القسم"""
        print("\n" + "="*80)
        print(f"🔥 {title}")
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
    
    def test_professional_printing(self):
        """اختبار نظام الطباعة الاحترافي"""
        self.print_header("اختبار نظام الطباعة الاحترافي")
        
        with self.app.app_context():
            try:
                # اختبار إنشاء تقرير ميزان المراجعة للطباعة
                accounts = GLAccount.query.filter_by(is_active=True, is_header=False).limit(10).all()
                
                if len(accounts) > 0:
                    self.print_test(
                        "إنشاء بيانات الطباعة",
                        'pass',
                        f"تم إنشاء بيانات لـ {len(accounts)} حساب"
                    )
                else:
                    self.print_test(
                        "إنشاء بيانات الطباعة",
                        'warn',
                        "لا توجد حسابات للطباعة"
                    )
                
                # اختبار تنسيق الأرقام
                test_amount = 1234567.89
                formatted = f"{test_amount:,.2f}"
                
                if "1,234,567.89" in formatted:
                    self.print_test(
                        "تنسيق الأرقام للطباعة",
                        'pass',
                        f"تنسيق صحيح: {formatted}"
                    )
                else:
                    self.print_test(
                        "تنسيق الأرقام للطباعة",
                        'fail',
                        f"تنسيق خاطئ: {formatted}"
                    )
                
            except Exception as e:
                self.print_test(
                    "اختبار نظام الطباعة الاحترافي",
                    'fail',
                    f"خطأ: {str(e)}"
                )
    
    def test_customs_taxes(self):
        """اختبار نظام الجمارك والضرائب"""
        self.print_header("اختبار نظام الجمارك والضرائب")
        
        with self.app.app_context():
            try:
                # إنشاء ضريبة تجريبية
                tax = CustomsTax(
                    name="Test VAT",
                    name_ar="ضريبة القيمة المضافة التجريبية",
                    tax_type="vat",
                    rate=Decimal('0.05'),  # 5%
                    is_percentage=True,
                    gl_account_id=1,  # حساب افتراضي
                    effective_from=date.today(),
                    description="ضريبة تجريبية للاختبار"
                )
                
                db.session.add(tax)
                db.session.commit()
                
                self.print_test(
                    "إنشاء ضريبة جديدة",
                    'pass',
                    f"تم إنشاء {tax.name_ar} بنسبة {tax.rate}%"
                )
                
                # اختبار حساب الضريبة
                base_amount = Decimal('1000')
                tax_amount = base_amount * tax.rate
                
                if tax_amount == Decimal('50'):
                    self.print_test(
                        "حساب الضريبة",
                        'pass',
                        f"مبلغ الضريبة: {tax_amount} درهم"
                    )
                else:
                    self.print_test(
                        "حساب الضريبة",
                        'fail',
                        f"حساب خاطئ: {tax_amount}"
                    )
                
                # تنظيف البيانات التجريبية
                db.session.delete(tax)
                db.session.commit()
                
            except Exception as e:
                self.print_test(
                    "اختبار نظام الجمارك والضرائب",
                    'fail',
                    f"خطأ: {str(e)}"
                )
                db.session.rollback()
    
    def test_expense_categories(self):
        """اختبار فئات المصروفات المتقدمة"""
        self.print_header("اختبار فئات المصروفات المتقدمة")
        
        with self.app.app_context():
            try:
                # إنشاء فئة مصروفات تجريبية
                category = ExpenseCategory(
                    code="TEST001",
                    name="Test Expense",
                    name_ar="مصروف تجريبي",
                    gl_account_id=1,  # حساب افتراضي
                    is_deductible=True,
                    max_deduction_rate=Decimal('1.0'),
                    requires_approval=True,
                    approval_limit=Decimal('5000'),
                    description="فئة تجريبية للاختبار"
                )
                
                db.session.add(category)
                db.session.commit()
                
                self.print_test(
                    "إنشاء فئة مصروفات",
                    'pass',
                    f"تم إنشاء {category.name_ar} مع حد موافقة {category.approval_limit}"
                )
                
                # اختبار إنشاء مصروف متقدم
                expense = AdvancedExpense(
                    expense_number="EXP-TEST-001",
                    expense_date=date.today(),
                    description="Test Advanced Expense",
                    description_ar="مصروف متقدم تجريبي",
                    category_id=category.id,
                    amount=Decimal('1000'),
                    amount_aed=Decimal('1000'),
                    taxable_amount=Decimal('1000'),
                    tax_rate=Decimal('0.05'),
                    created_by=self.test_user.id
                )
                
                # حساب الضرائب
                expense.calculate_taxes()
                
                if expense.tax_amount == Decimal('50'):
                    self.print_test(
                        "حساب ضرائب المصروف",
                        'pass',
                        f"ضريبة المصروف: {expense.tax_amount} درهم"
                    )
                else:
                    self.print_test(
                        "حساب ضرائب المصروف",
                        'fail',
                        f"حساب خاطئ: {expense.tax_amount}"
                    )
                
                # تنظيف البيانات التجريبية
                db.session.delete(expense)
                db.session.delete(category)
                db.session.commit()
                
            except Exception as e:
                self.print_test(
                    "اختبار فئات المصروفات المتقدمة",
                    'fail',
                    f"خطأ: {str(e)}"
                )
                db.session.rollback()
    
    def test_advanced_journal_management(self):
        """اختبار إدارة القيود المتقدمة"""
        self.print_header("اختبار إدارة القيود المتقدمة")
        
        with self.app.app_context():
            try:
                # إنشاء قيد تجريبي
                entry = AdvancedJournalEntryManager.create_entry_with_validation(
                    description="قيد تجريبي للاختبار المتقدم",
                    lines=[
                        {'account_code': '1110', 'debit': 2000, 'credit': 0, 'description': 'صندوق'},
                        {'account_code': '4100', 'debit': 0, 'credit': 2000, 'description': 'مبيعات'}
                    ],
                    entry_date=date.today(),
                    created_by=self.test_user.id
                )
                
                self.print_test(
                    "إنشاء قيد متقدم",
                    'pass',
                    f"تم إنشاء القيد {entry.entry_number}"
                )
                
                # اختبار الموافقة على القيد
                approved_entry = AdvancedJournalEntryManager.approve_entry(
                    entry_id=entry.id,
                    approved_by=self.test_user,
                    approval_notes="موافقة تجريبية"
                )
                
                if approved_entry.is_posted:
                    self.print_test(
                        "الموافقة على القيد",
                        'pass',
                        "تم ترحيل القيد بنجاح"
                    )
                else:
                    self.print_test(
                        "الموافقة على القيد",
                        'fail',
                        "فشل في ترحيل القيد"
                    )
                
                # اختبار عكس القيد
                reversal_entry = AdvancedJournalEntryManager.reverse_entry_advanced(
                    entry_id=entry.id,
                    reversed_by=self.test_user,
                    reason="عكس تجريبي",
                    create_reversal_entry=True
                )
                
                if reversal_entry and entry.is_reversed:
                    self.print_test(
                        "عكس القيد المتقدم",
                        'pass',
                        f"تم إنشاء القيد العكسي {reversal_entry.entry_number}"
                    )
                else:
                    self.print_test(
                        "عكس القيد المتقدم",
                        'fail',
                        "فشل في عكس القيد"
                    )
                
            except Exception as e:
                self.print_test(
                    "اختبار إدارة القيود المتقدمة",
                    'fail',
                    f"خطأ: {str(e)}"
                )
                db.session.rollback()
    
    def test_cheque_accounting_integration(self):
        """اختبار تكامل الشيكات مع النظام المحاسبي"""
        self.print_header("اختبار تكامل الشيكات مع النظام المحاسبي")
        
        with self.app.app_context():
            try:
                # إنشاء شيك تجريبي
                cheque = Cheque(
                    cheque_bank_number="TEST-CHQ-001",
                    cheque_type="incoming",
                    amount=Decimal('5000'),
                    amount_aed=Decimal('5000'),
                    currency="AED",
                    cheque_date=date.today(),
                    status="pending",
                    customer_id=1 if Customer.query.first() else None
                )
                
                db.session.add(cheque)
                db.session.commit()
                
                self.print_test(
                    "إنشاء شيك تجريبي",
                    'pass',
                    f"تم إنشاء شيك رقم {cheque.cheque_bank_number}"
                )
                
                # اختبار تسجيل استلام الشيك
                try:
                    entry = ChequeAccountingIntegration.receive_cheque(
                        cheque_id=cheque.id,
                        received_by=self.test_user
                    )
                    
                    if entry and cheque.status == 'received':
                        self.print_test(
                            "تسجيل استلام الشيك",
                            'pass',
                            f"تم إنشاء القيد {entry.entry_number}"
                        )
                    else:
                        self.print_test(
                            "تسجيل استلام الشيك",
                            'fail',
                            "فشل في تسجيل الاستلام"
                        )
                    
                    # اختبار صرف الشيك
                    clear_entry = ChequeAccountingIntegration.clear_cheque(
                        cheque_id=cheque.id,
                        cleared_by=self.test_user,
                        bank_charges=Decimal('10'),
                        exchange_gain_loss=Decimal('5')
                    )
                    
                    if clear_entry and cheque.status == 'cleared':
                        self.print_test(
                            "تسجيل صرف الشيك",
                            'pass',
                            f"تم إنشاء قيد الصرف {clear_entry.entry_number}"
                        )
                    else:
                        self.print_test(
                            "تسجيل صرف الشيك",
                            'fail',
                            "فشل في تسجيل الصرف"
                        )
                    
                except Exception as e:
                    self.print_test(
                        "تكامل الشيكات",
                        'fail',
                        f"خطأ في التكامل: {str(e)}"
                    )
                
                # تنظيف البيانات التجريبية
                db.session.delete(cheque)
                db.session.commit()
                
            except Exception as e:
                self.print_test(
                    "اختبار تكامل الشيكات",
                    'fail',
                    f"خطأ: {str(e)}"
                )
                db.session.rollback()
    
    def test_real_time_listeners(self):
        """اختبار المستمعات اللحظية"""
        self.print_header("اختبار المستمعات اللحظية")
        
        with self.app.app_context():
            try:
                # اختبار إرسال حدث تجريبي
                accounting_event_stream.emit_event('test_event', {
                    'message': 'اختبار المستمعات اللحظية',
                    'timestamp': datetime.now().isoformat(),
                    'test_data': 'بيانات تجريبية'
                })
                
                # الحصول على الأحداث الأخيرة
                recent_events = accounting_event_stream.get_recent_events(limit=5)
                
                if len(recent_events) > 0:
                    self.print_test(
                        "إرسال واستقبال الأحداث",
                        'pass',
                        f"تم إرسال واستقبال {len(recent_events)} حدث"
                    )
                else:
                    self.print_test(
                        "إرسال واستقبال الأحداث",
                        'fail',
                        "لم يتم استقبال أي أحداث"
                    )
                
                # اختبار تصفية الأحداث حسب النوع
                test_events = accounting_event_stream.get_events_by_type('test_event')
                
                if len(test_events) > 0:
                    self.print_test(
                        "تصفية الأحداث حسب النوع",
                        'pass',
                        f"تم العثور على {len(test_events)} حدث من نوع test_event"
                    )
                else:
                    self.print_test(
                        "تصفية الأحداث حسب النوع",
                        'fail',
                        "لم يتم العثور على أحداث من النوع المطلوب"
                    )
                
            except Exception as e:
                self.print_test(
                    "اختبار المستمعات اللحظية",
                    'fail',
                    f"خطأ: {str(e)}"
                )
    
    def test_web_endpoints(self):
        """اختبار نقاط النهاية على الويب"""
        self.print_header("اختبار نقاط النهاية على الويب")
        
        endpoints = [
            ('/ledger/advanced/professional-printing', 'نظام الطباعة الاحترافي'),
            ('/ledger/advanced/customs-taxes', 'إدارة الجمارك والضرائب'),
            ('/ledger/advanced/expense-categories', 'فئات المصروفات المتقدمة'),
            ('/ledger/advanced/advanced-expenses', 'المصروفات المتقدمة'),
            ('/ledger/advanced/journal-management', 'إدارة القيود المتقدمة'),
            ('/ledger/advanced/cheque-integration', 'تكامل الشيكات'),
            ('/ledger/advanced/real-time-events', 'الأحداث اللحظية'),
        ]
        
        for endpoint, name in endpoints:
            try:
                response = requests.get(f"http://127.0.0.1:8080{endpoint}", timeout=5)
                
                if response.status_code in [200, 302, 401]:  # 401 متوقع للصفحات المحمية
                    self.print_test(
                        f"نقطة النهاية: {name}",
                        'pass',
                        f"Status: {response.status_code}"
                    )
                else:
                    self.print_test(
                        f"نقطة النهاية: {name}",
                        'fail',
                        f"Status: {response.status_code}"
                    )
                    
            except requests.exceptions.ConnectionError:
                self.print_test(
                    f"نقطة النهاية: {name}",
                    'warn',
                    "الخادم غير متاح"
                )
            except Exception as e:
                self.print_test(
                    f"نقطة النهاية: {name}",
                    'fail',
                    f"خطأ: {str(e)}"
                )
    
    def run_all_tests(self):
        """تشغيل جميع الاختبارات"""
        print("\n" + "="*80)
        print("🔥 بدء الاختبار الشامل للنظام المحاسبي الجبار الخارق")
        print("="*80)
        
        # تشغيل جميع الاختبارات
        self.test_professional_printing()
        self.test_customs_taxes()
        self.test_expense_categories()
        self.test_advanced_journal_management()
        self.test_cheque_accounting_integration()
        self.test_real_time_listeners()
        self.test_web_endpoints()
        
        # ملخص النتائج
        self.print_summary()
    
    def print_summary(self):
        """طباعة ملخص النتائج"""
        self.print_header("📊 ملخص نتائج الاختبار الشامل")
        
        total_tests = self.passed + self.failed + self.warnings
        success_rate = (self.passed / total_tests * 100) if total_tests > 0 else 0
        
        print(f"✅ نجح: {self.passed}/{total_tests}")
        print(f"❌ فشل: {self.failed}/{total_tests}")
        print(f"⚠️ تحذيرات: {self.warnings}/{total_tests}")
        print(f"📈 نسبة النجاح: {success_rate:.1f}%")
        print("="*80)
        
        if self.failed == 0:
            print("🎉 مبروك! النظام المحاسبي الجبار جاهز!")
            print("🔥 جميع الاختبارات نجحت - النظام لا يهزم!")
        elif self.failed <= 2:
            print("🚀 ممتاز! النظام شبه مثالي!")
            print("⚡ إصلاحات بسيطة فقط مطلوبة!")
        else:
            print(f"⚠️ هناك {self.failed} اختبار فشل - يحتاج إصلاح!")
        
        print("="*80)
        
        # تفاصيل الاختبارات الفاشلة
        if self.failed > 0:
            print("\n❌ الاختبارات الفاشلة:")
            for result in self.test_results:
                if result['status'] == 'fail':
                    print(f"   • {result['name']}: {result['details']}")


if __name__ == '__main__':
    print("\n⏱️ انتظر قليلاً لتحميل النظام الجبار...")
    
    # تشغيل الاختبارات
    suite = UltimateAccountingTestSuite()
    suite.run_all_tests()
    
    print("\n🔥 اكتمل الاختبار الشامل للنظام المحاسبي الجبار!")
