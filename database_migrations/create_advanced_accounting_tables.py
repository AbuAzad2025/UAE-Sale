"""
إنشاء الجداول المفقودة للنظام المحاسبي المتقدم
Migration for Advanced Accounting Tables
"""
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

db_path = 'instance/app.db'

def create_missing_tables():
    """إنشاء الجداول المفقودة فقط"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("="*80)
    print("🔧 إنشاء الجداول المفقودة للنظام المحاسبي المتقدم")
    print("="*80)
    
    try:
        # 1. جدول الجمارك والضرائب
        print("\n1️⃣ إنشاء جدول customs_taxes...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customs_taxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(200) NOT NULL,
                name_ar VARCHAR(200) NOT NULL,
                tax_type VARCHAR(50) NOT NULL,
                rate DECIMAL(5, 4) NOT NULL,
                is_percentage BOOLEAN DEFAULT 1,
                fixed_amount DECIMAL(18, 3) DEFAULT 0,
                gl_account_id INTEGER NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                effective_from DATE NOT NULL,
                effective_to DATE,
                description TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (gl_account_id) REFERENCES gl_accounts(id)
            )
        """)
        print("   ✅ تم إنشاء جدول customs_taxes")
        
        # 2. جدول المصروفات المتقدمة
        print("\n2️⃣ إنشاء جدول advanced_expenses...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS advanced_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expense_number VARCHAR(50) UNIQUE NOT NULL,
                expense_date DATE NOT NULL,
                description VARCHAR(255) NOT NULL,
                description_ar VARCHAR(255) NOT NULL,
                category_id INTEGER NOT NULL,
                supplier_id INTEGER,
                amount DECIMAL(18, 3) NOT NULL,
                currency VARCHAR(3) DEFAULT 'AED',
                exchange_rate DECIMAL(15, 6) DEFAULT 1,
                amount_aed DECIMAL(18, 3) NOT NULL,
                
                taxable_amount DECIMAL(18, 3) DEFAULT 0,
                tax_amount DECIMAL(18, 3) DEFAULT 0,
                tax_rate DECIMAL(5, 4) DEFAULT 0,
                tax_exempt BOOLEAN DEFAULT 0,
                
                customs_amount DECIMAL(18, 3) DEFAULT 0,
                customs_rate DECIMAL(5, 4) DEFAULT 0,
                customs_exempt BOOLEAN DEFAULT 0,
                
                payment_method VARCHAR(50),
                payment_status VARCHAR(50) DEFAULT 'pending',
                paid_amount DECIMAL(18, 3) DEFAULT 0,
                due_date DATE,
                
                requires_approval BOOLEAN DEFAULT 0,
                approval_status VARCHAR(50) DEFAULT 'pending',
                approved_by INTEGER,
                approved_at DATETIME,
                approval_notes TEXT,
                
                attachment_count INTEGER DEFAULT 0,
                has_receipt BOOLEAN DEFAULT 0,
                receipt_number VARCHAR(100),
                
                created_by INTEGER NOT NULL,
                gl_journal_entry_id INTEGER,
                is_reversed BOOLEAN DEFAULT 0,
                reversed_at DATETIME,
                reversed_by INTEGER,
                reversal_reason TEXT,
                
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                
                FOREIGN KEY (category_id) REFERENCES expense_categories(id),
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
                FOREIGN KEY (created_by) REFERENCES users(id),
                FOREIGN KEY (approved_by) REFERENCES users(id),
                FOREIGN KEY (reversed_by) REFERENCES users(id),
                FOREIGN KEY (gl_journal_entry_id) REFERENCES gl_journal_entries(id)
            )
        """)
        print("   ✅ تم إنشاء جدول advanced_expenses")
        
        # 3. جدول قواعد حساب الضرائب
        print("\n3️⃣ إنشاء جدول tax_calculation_rules...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tax_calculation_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(200) NOT NULL,
                name_ar VARCHAR(200) NOT NULL,
                rule_type VARCHAR(50) NOT NULL,
                condition_field VARCHAR(100),
                condition_operator VARCHAR(20),
                condition_value VARCHAR(255),
                tax_id INTEGER NOT NULL,
                priority INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tax_id) REFERENCES customs_taxes(id)
            )
        """)
        print("   ✅ تم إنشاء جدول tax_calculation_rules")
        
        # 4. جدول تدقيق القيود
        print("\n4️⃣ إنشاء جدول journal_entry_audits...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS journal_entry_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                journal_entry_id INTEGER NOT NULL,
                action VARCHAR(50) NOT NULL,
                old_values TEXT,
                new_values TEXT,
                reason TEXT,
                performed_by INTEGER NOT NULL,
                performed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                ip_address VARCHAR(45),
                user_agent TEXT,
                FOREIGN KEY (journal_entry_id) REFERENCES gl_journal_entries(id),
                FOREIGN KEY (performed_by) REFERENCES users(id)
            )
        """)
        print("   ✅ تم إنشاء جدول journal_entry_audits")
        
        # إنشاء الفهارس
        print("\n📊 إنشاء الفهارس...")
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_customs_taxes_type ON customs_taxes(tax_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_customs_taxes_active ON customs_taxes(is_active)")
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_advanced_expenses_date ON advanced_expenses(expense_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_advanced_expenses_status ON advanced_expenses(payment_status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_advanced_expenses_number ON advanced_expenses(expense_number)")
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tax_rules_type ON tax_calculation_rules(rule_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tax_rules_active ON tax_calculation_rules(is_active)")
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audits_entry ON journal_entry_audits(journal_entry_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audits_action ON journal_entry_audits(action)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audits_date ON journal_entry_audits(performed_at)")
        
        print("   ✅ تم إنشاء الفهارس")
        
        conn.commit()
        print("\n" + "="*80)
        print("✅ اكتملت عملية إنشاء الجداول المفقودة بنجاح!")
        print("="*80)
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ خطأ في إنشاء الجداول: {e}")
        return False
    finally:
        conn.close()
    
    return True

if __name__ == '__main__':
    print(f"\n📁 قاعدة البيانات: {db_path}")
    print(f"🕒 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if create_missing_tables():
        print("\n🚀 يمكنك الآن تشغيل النظام!")
    else:
        print("\n❌ فشلت عملية التهجير - راجع الأخطاء أعلاه")

