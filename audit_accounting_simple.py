"""
==========================================
فحص شامل للنظام المحاسبي  
Comprehensive Accounting System Audit
==========================================
المراجع المحاسبي: نظام فحص دقيق ومتكامل
"""

import sqlite3
from decimal import Decimal
from datetime import datetime
from tabulate import tabulate
import json


class SimpleAccountingAuditor:
    """مراجع محاسبي مبسط يعمل مباشرة على قاعدة البيانات"""
    
    def __init__(self, db_path='instance/app.db'):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.errors = []
        self.warnings = []
        self.report = {}
        
    def add_error(self, category, message, severity='HIGH'):
        """إضافة خطأ محاسبي"""
        self.errors.append({
            'category': category,
            'message': message,
            'severity': severity
        })
    
    def add_warning(self, category, message):
        """إضافة تحذير"""
        self.warnings.append({
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
        self.cursor.execute("SELECT COUNT(*) FROM gl_accounts")
        total_accounts = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM gl_accounts WHERE is_active = 1")
        active_accounts = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM gl_accounts WHERE is_header = 1")
        header_accounts = self.cursor.fetchone()[0]
        
        detail_accounts = total_accounts - header_accounts
        
        print(f"📊 إحصائيات الحسابات:")
        print(f"   • إجمالي الحسابات: {total_accounts}")
        print(f"   • الحسابات النشطة: {active_accounts}")
        print(f"   • الحسابات الرئيسية: {header_accounts}")
        print(f"   • الحسابات التفصيلية: {detail_accounts}")
        
        # فحص الحسابات حسب النوع
        self.cursor.execute("""
            SELECT type, COUNT(*) as count
            FROM gl_accounts
            GROUP BY type
        """)
        account_types = self.cursor.fetchall()
        
        print(f"\n📋 توزيع الحسابات حسب النوع:")
        for row in account_types:
            type_ar = {
                'asset': 'أصول',
                'liability': 'خصوم',
                'equity': 'حقوق ملكية',
                'revenue': 'إيرادات',
                'expense': 'مصروفات'
            }.get(row['type'], row['type'])
            print(f"   • {type_ar}: {row['count']} حساب")
        
        # فحص الحسابات المكررة
        self.cursor.execute("""
            SELECT code, COUNT(*) as count
            FROM gl_accounts
            GROUP BY code
            HAVING COUNT(*) > 1
        """)
        duplicate_codes = self.cursor.fetchall()
        
        if duplicate_codes:
            for row in duplicate_codes:
                self.add_error(
                    'GL_ACCOUNTS',
                    f'❌ الكود "{row["code"]}" مكرر {row["count"]} مرات',
                    'CRITICAL'
                )
        
        self.report['gl_accounts'] = {
            'total': total_accounts,
            'active': active_accounts,
            'header': header_accounts,
            'detail': detail_accounts
        }
        
        print(f"\n✅ تم فحص {total_accounts} حساب")
    
    def audit_journal_entries(self):
        """2️⃣ فحص القيود المحاسبية والتوازن"""
        self.print_section("2️⃣ فحص القيود المحاسبية (Journal Entries)")
        
        # إحصائيات القيود
        self.cursor.execute("SELECT COUNT(*) FROM gl_journal_entries")
        total_entries = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM gl_journal_entries WHERE is_posted = 1")
        posted_entries = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM gl_journal_entries WHERE is_reversed = 1")
        reversed_entries = self.cursor.fetchone()[0]
        
        print(f"📊 إحصائيات القيود:")
        print(f"   • إجمالي القيود: {total_entries}")
        print(f"   • القيود المرحلة: {posted_entries}")
        print(f"   • القيود المعكوسة: {reversed_entries}")
        
        # فحص توازن كل قيد
        print(f"\n🔍 فحص توازن القيود المحاسبية...")
        
        self.cursor.execute("""
            SELECT 
                e.id,
                e.entry_number,
                e.total_debit as stored_debit,
                e.total_credit as stored_credit,
                COALESCE(SUM(l.debit), 0) as actual_debit,
                COALESCE(SUM(l.credit), 0) as actual_credit
            FROM gl_journal_entries e
            LEFT JOIN gl_journal_lines l ON e.id = l.entry_id
            GROUP BY e.id, e.entry_number, e.total_debit, e.total_credit
        """)
        
        unbalanced_count = 0
        for row in self.cursor.fetchall():
            actual_debit = Decimal(str(row['actual_debit'] or 0))
            actual_credit = Decimal(str(row['actual_credit'] or 0))
            stored_debit = Decimal(str(row['stored_debit'] or 0))
            stored_credit = Decimal(str(row['stored_credit'] or 0))
            
            # فحص التوازن
            difference = abs(actual_debit - actual_credit)
            if difference > Decimal('0.01'):
                unbalanced_count += 1
                self.add_error(
                    'JOURNAL_BALANCE',
                    f'❌ القيد {row["entry_number"]} غير متوازن: مدين={actual_debit} ≠ دائن={actual_credit} (فرق={difference})',
                    'CRITICAL'
                )
            
            # فحص تطابق الإجماليات المحفوظة
            if abs(stored_debit - actual_debit) > Decimal('0.01') or abs(stored_credit - actual_credit) > Decimal('0.01'):
                self.add_error(
                    'JOURNAL_TOTALS',
                    f'❌ القيد {row["entry_number"]}: الإجماليات المحفوظة لا تطابق السطور',
                    'HIGH'
                )
        
        if unbalanced_count > 0:
            print(f"\n❌ تم العثور على {unbalanced_count} قيد غير متوازن!")
        else:
            print(f"\n✅ جميع القيود متوازنة ({total_entries} قيد)")
        
        self.report['journal_entries'] = {
            'total': total_entries,
            'posted': posted_entries,
            'reversed': reversed_entries,
            'unbalanced': unbalanced_count
        }
    
    def audit_trial_balance(self):
        """3️⃣ فحص ميزان المراجعة"""
        self.print_section("3️⃣ فحص ميزان المراجعة (Trial Balance)")
        
        print(f"📊 حساب ميزان المراجعة...")
        
        # حساب الأرصدة لكل حساب
        self.cursor.execute("""
            SELECT 
                a.code,
                a.name_ar,
                a.name,
                a.type,
                COALESCE(SUM(l.debit), 0) as total_debit,
                COALESCE(SUM(l.credit), 0) as total_credit
            FROM gl_accounts a
            LEFT JOIN gl_journal_lines l ON a.id = l.account_id
            WHERE a.is_active = 1 AND a.is_header = 0
            GROUP BY a.id, a.code, a.name_ar, a.name, a.type
            HAVING COALESCE(SUM(l.debit), 0) > 0 OR COALESCE(SUM(l.credit), 0) > 0
        """)
        
        trial_balance = []
        total_debit_balance = Decimal('0')
        total_credit_balance = Decimal('0')
        
        for row in self.cursor.fetchall():
            debit_sum = Decimal(str(row['total_debit']))
            credit_sum = Decimal(str(row['total_credit']))
            
            # حساب الرصيد حسب نوع الحساب
            if row['type'] in ['asset', 'expense']:
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
                balance = credit_sum - debit_sum
                if balance > 0:
                    total_credit_balance += balance
                    debit_balance = Decimal('0')
                    credit_balance = balance
                else:
                    total_debit_balance += abs(balance)
                    debit_balance = abs(balance)
                    credit_balance = Decimal('0')
            
            trial_balance.append({
                'code': row['code'],
                'name': row['name_ar'] or row['name'],
                'type': row['type'],
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
        
        # عرض أكبر 10 حسابات
        print(f"\n📋 أكبر 10 حسابات رصيداً:")
        sorted_tb = sorted(trial_balance, key=lambda x: max(x['debit'], x['credit']), reverse=True)[:10]
        
        table_data = []
        for item in sorted_tb:
            type_ar = {
                'asset': 'أصول',
                'liability': 'خصوم',
                'equity': 'حقوق ملكية',
                'revenue': 'إيرادات',
                'expense': 'مصروفات'
            }.get(item['type'], item['type'])
            
            table_data.append([
                item['code'],
                item['name'][:30],
                type_ar,
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
    
    def audit_sales(self):
        """4️⃣ فحص المبيعات"""
        self.print_section("4️⃣ فحص تكامل المبيعات")
        
        self.cursor.execute("SELECT COUNT(*) FROM sales")
        total_sales = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM sales WHERE status = 'confirmed'")
        confirmed_sales = self.cursor.fetchone()[0]
        
        print(f"📊 إحصائيات المبيعات:")
        print(f"   • إجمالي الفواتير: {total_sales}")
        print(f"   • الفواتير المؤكدة: {confirmed_sales}")
        
        # الإجماليات المالية
        self.cursor.execute("""
            SELECT 
                COALESCE(SUM(total_amount), 0) as total_sales,
                COALESCE(SUM(paid_amount_aed), 0) as total_paid,
                COALESCE(SUM(balance_due), 0) as total_balance
            FROM sales
            WHERE status = 'confirmed'
        """)
        row = self.cursor.fetchone()
        
        total_sales_amount = Decimal(str(row['total_sales']))
        total_paid = Decimal(str(row['total_paid']))
        total_balance = Decimal(str(row['total_balance']))
        
        print(f"\n💰 الإجماليات المالية:")
        print(f"   • إجمالي المبيعات: {total_sales_amount:,.2f} درهم")
        print(f"   • المبلغ المدفوع: {total_paid:,.2f} درهم")
        print(f"   • الرصيد المستحق: {total_balance:,.2f} درهم")
        
        # التحقق من المعادلة
        calculated_balance = total_sales_amount - total_paid
        difference = abs(calculated_balance - total_balance)
        
        if difference > Decimal('1'):
            self.add_error(
                'SALES_BALANCE',
                f'❌ عدم توافق في أرصدة المبيعات: فرق={difference}',
                'HIGH'
            )
        
        # توزيع حالات الدفع
        self.cursor.execute("""
            SELECT 
                payment_status,
                COUNT(*) as count,
                COALESCE(SUM(total_amount), 0) as total
            FROM sales
            WHERE status = 'confirmed'
            GROUP BY payment_status
        """)
        
        print(f"\n📋 توزيع حالات الدفع:")
        for row in self.cursor.fetchall():
            status_ar = {
                'paid': 'مدفوع ✅',
                'partial': 'مدفوع جزئياً ⏳',
                'unpaid': 'غير مدفوع ❌'
            }.get(row['payment_status'], row['payment_status'])
            print(f"   • {status_ar}: {row['count']} فاتورة ({row['total']:,.2f} درهم)")
        
        self.report['sales'] = {
            'total_count': total_sales,
            'confirmed_count': confirmed_sales,
            'total_amount': float(total_sales_amount),
            'total_paid': float(total_paid),
            'total_balance': float(total_balance)
        }
    
    def audit_cheques(self):
        """5️⃣ فحص الشيكات"""
        self.print_section("5️⃣ فحص نظام الشيكات")
        
        self.cursor.execute("SELECT COUNT(*) FROM cheques")
        total_cheques = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM cheques WHERE cheque_type = 'incoming'")
        incoming = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM cheques WHERE cheque_type = 'outgoing'")
        outgoing = self.cursor.fetchone()[0]
        
        print(f"📊 إحصائيات الشيكات:")
        print(f"   • إجمالي الشيكات: {total_cheques}")
        print(f"   • الشيكات الواردة: {incoming}")
        print(f"   • الشيكات الصادرة: {outgoing}")
        
        # حسب الحالة
        self.cursor.execute("""
            SELECT 
                status,
                COUNT(*) as count,
                COALESCE(SUM(amount_aed), 0) as total
            FROM cheques
            GROUP BY status
        """)
        
        print(f"\n📋 توزيع الشيكات حسب الحالة:")
        for row in self.cursor.fetchall():
            status_ar = {
                'pending': 'معلق ⏳',
                'deposited': 'مودع 🏦',
                'cleared': 'مصروف ✅',
                'bounced': 'مرتد ❌',
                'cancelled': 'ملغي 🚫'
            }.get(row['status'], row['status'])
            print(f"   • {status_ar}: {row['count']} شيك ({row['total']:,.2f} درهم)")
        
        self.report['cheques'] = {
            'total': total_cheques,
            'incoming': incoming,
            'outgoing': outgoing
        }
    
    def generate_report(self):
        """إنشاء التقرير النهائي"""
        self.print_section("📋 التقرير النهائي للمراجعة المحاسبية")
        
        print(f"\n{'='*80}")
        print(f"  ملخص التدقيق")
        print(f"{'='*80}\n")
        
        critical_errors = [e for e in self.errors if e['severity'] == 'CRITICAL']
        high_errors = [e for e in self.errors if e['severity'] in ['HIGH', 'MEDIUM']]
        
        print(f"🔴 الأخطاء الحرجة: {len(critical_errors)}")
        print(f"🟠 الأخطاء العادية: {len(high_errors)}")
        print(f"🟡 التحذيرات: {len(self.warnings)}")
        
        # عرض الأخطاء
        if critical_errors:
            print(f"\n{'='*80}")
            print(f"  ❌ الأخطاء الحرجة")
            print(f"{'='*80}\n")
            for error in critical_errors:
                print(f"  [{error['category']}] {error['message']}")
        
        if high_errors:
            print(f"\n{'='*80}")
            print(f"  🟠 الأخطاء العادية")
            print(f"{'='*80}\n")
            for error in high_errors[:10]:
                print(f"  [{error['category']}] {error['message']}")
        
        # التقييم
        print(f"\n{'='*80}")
        print(f"  📊 التقييم العام")
        print(f"{'='*80}\n")
        
        if len(critical_errors) == 0 and len(high_errors) == 0:
            grade = "ممتاز ✅"
            score = 95
        elif len(critical_errors) == 0:
            grade = "جيد جداً"
            score = 80
        elif len(critical_errors) <= 3:
            grade = "جيد"
            score = 65
        else:
            grade = "يحتاج تحسين"
            score = 40
        
        print(f"  التقييم: {grade}")
        print(f"  الدرجة: {score}/100")
        
        # حفظ التقرير
        report_data = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'critical_errors': len(critical_errors),
                'high_errors': len(high_errors),
                'warnings': len(self.warnings),
                'grade': grade,
                'score': score
            },
            'details': self.report,
            'errors': self.errors,
            'warnings': self.warnings
        }
        
        filename = f'accounting_audit_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        
        print(f"\n\n📄 تم حفظ التقرير في: {filename}")
        
        return report_data
    
    def close(self):
        """إغلاق الاتصال"""
        self.conn.close()


def main():
    """تشغيل الفحص"""
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
    
    auditor = SimpleAccountingAuditor()
    
    try:
        auditor.audit_gl_accounts()
        auditor.audit_journal_entries()
        auditor.audit_trial_balance()
        auditor.audit_sales()
        auditor.audit_cheques()
        auditor.generate_report()
        
        print(f"\n\n✅ اكتمل الفحص الشامل بنجاح!")
        
    except Exception as e:
        print(f"\n\n❌ خطأ أثناء الفحص: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        auditor.close()


if __name__ == '__main__':
    main()

