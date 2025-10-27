"""
فحص الجداول الموجودة في قاعدة البيانات
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

db_path = 'instance/app.db'

def check_existing_tables():
    """فحص جميع الجداول الموجودة"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # الحصول على جميع الجداول
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = cursor.fetchall()
    
    print("="*80)
    print("📊 الجداول الموجودة في قاعدة البيانات")
    print("="*80)
    
    for idx, table in enumerate(tables, 1):
        table_name = table[0]
        
        # الحصول على معلومات الجدول
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = cursor.fetchall()
        
        print(f"\n{idx}. 📋 {table_name}")
        print(f"   عدد الأعمدة: {len(columns)}")
        print(f"   الأعمدة: {', '.join([col[1] for col in columns[:5]])}")
        if len(columns) > 5:
            print(f"   ... و {len(columns) - 5} عمود آخر")
    
    print("\n" + "="*80)
    print(f"✅ إجمالي الجداول: {len(tables)}")
    print("="*80)
    
    conn.close()
    
    return [table[0] for table in tables]

def check_specific_tables():
    """فحص الجداول المطلوبة للنظام الجديد"""
    print("\n" + "="*80)
    print("🔍 فحص الجداول المطلوبة للنظام المتقدم")
    print("="*80)
    
    existing_tables = check_existing_tables()
    
    required_tables = {
        'customs_taxes': 'جدول الجمارك والضرائب',
        'advanced_expenses': 'جدول المصروفات المتقدمة',
        'tax_calculation_rules': 'جدول قواعد حساب الضرائب',
        'journal_entry_audits': 'جدول تدقيق القيود',
        'expense_categories': 'جدول فئات المصروفات',
        'cheques': 'جدول الشيكات',
        'gl_journal_entries': 'جدول القيود المحاسبية',
        'gl_journal_lines': 'جدول سطور القيود',
        'gl_accounts': 'جدول الحسابات المحاسبية'
    }
    
    print("\n📋 حالة الجداول المطلوبة:")
    missing_tables = []
    
    for table_name, table_desc in required_tables.items():
        if table_name in existing_tables:
            print(f"✅ {table_desc} ({table_name}) - موجود")
        else:
            print(f"❌ {table_desc} ({table_name}) - مفقود")
            missing_tables.append(table_name)
    
    print("\n" + "="*80)
    if missing_tables:
        print(f"⚠️ يوجد {len(missing_tables)} جدول مفقود:")
        for table in missing_tables:
            print(f"   • {table}")
    else:
        print("✅ جميع الجداول المطلوبة موجودة!")
    print("="*80)
    
    return missing_tables

if __name__ == '__main__':
    print("\n🔍 جاري فحص قاعدة البيانات...")
    missing = check_specific_tables()
    
    if missing:
        print(f"\n⚠️ يجب إنشاء {len(missing)} جدول")
    else:
        print("\n✅ قاعدة البيانات جاهزة!")

