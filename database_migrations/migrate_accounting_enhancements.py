#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
تهجير التحسينات المحاسبية
Accounting Enhancements Migration

يضيف:
1. حقول جديدة لجدول gl_accounts (is_header, level, description, updated_at)
2. حقول جديدة لجدول gl_journal_entries (entry_type, is_posted, is_reversed, reversed_entry_id, notes, created_by, updated_at)
3. تحديث الحسابات المحاسبية الجديدة
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

# إضافة مسار الجذر للمشروع
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

DB_PATH = project_root / 'instance' / 'app.db'


def migrate():
    """تنفيذ التهجير"""
    print("=" * 70)
    print("🔧 تهجير التحسينات المحاسبية")
    print("=" * 70)
    print(f"📁 قاعدة البيانات: {DB_PATH}")
    print(f"🕒 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 70)
    
    if not DB_PATH.exists():
        print(f"❌ قاعدة البيانات غير موجودة: {DB_PATH}")
        return False
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        print("🔧 بدء عملية التهجير...")
        
        # =================================================================
        # 1. تحديث جدول gl_accounts
        # =================================================================
        print("\n📋 تحديث جدول gl_accounts...")
        
        # الحصول على الأعمدة الحالية
        cursor.execute("PRAGMA table_info(gl_accounts)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        
        # إضافة الأعمدة الجديدة
        new_columns = [
            ('is_header', 'BOOLEAN DEFAULT 0'),
            ('level', 'INTEGER DEFAULT 0'),
            ('description', 'TEXT'),
            ('updated_at', 'DATETIME')
        ]
        
        for col_name, col_type in new_columns:
            if col_name not in existing_columns:
                try:
                    cursor.execute(f'ALTER TABLE gl_accounts ADD COLUMN {col_name} {col_type}')
                    print(f"   ✅ تم إضافة عمود: {col_name}")
                except sqlite3.OperationalError as e:
                    if 'duplicate column name' not in str(e).lower():
                        raise
                    print(f"   ⚠️ العمود {col_name} موجود مسبقاً")
        
        # =================================================================
        # 2. تحديث جدول gl_journal_entries
        # =================================================================
        print("\n📋 تحديث جدول gl_journal_entries...")
        
        cursor.execute("PRAGMA table_info(gl_journal_entries)")
        existing_je_columns = {row[1] for row in cursor.fetchall()}
        
        new_je_columns = [
            ('entry_type', 'VARCHAR(30) DEFAULT "manual"'),
            ('is_posted', 'BOOLEAN DEFAULT 1'),
            ('is_reversed', 'BOOLEAN DEFAULT 0'),
            ('reversed_entry_id', 'INTEGER'),
            ('notes', 'TEXT'),
            ('created_by', 'INTEGER'),
            ('updated_at', 'DATETIME')
        ]
        
        for col_name, col_type in new_je_columns:
            if col_name not in existing_je_columns:
                try:
                    cursor.execute(f'ALTER TABLE gl_journal_entries ADD COLUMN {col_name} {col_type}')
                    print(f"   ✅ تم إضافة عمود: {col_name}")
                except sqlite3.OperationalError as e:
                    if 'duplicate column name' not in str(e).lower():
                        raise
                    print(f"   ⚠️ العمود {col_name} موجود مسبقاً")
        
        # =================================================================
        # 3. تحديث القيود الموجودة
        # =================================================================
        print("\n📋 تحديث القيود الموجودة...")
        cursor.execute("""
            UPDATE gl_journal_entries 
            SET entry_type = 'auto', is_posted = 1, is_reversed = 0 
            WHERE entry_type IS NULL
        """)
        print(f"   ✅ تم تحديث {cursor.rowcount} قيد")
        
        # =================================================================
        # 4. تحديث الحسابات الموجودة (مستوى وحالة Header)
        # =================================================================
        print("\n📋 تحديث الحسابات الموجودة...")
        
        # حسابات رئيسية (Header accounts)
        header_accounts = [
            '1000',  # الأصول
            '1100',  # الأصول المتداولة
            '1200',  # الأصول الثابتة
            '2000',  # الخصوم
            '2100',  # الخصوم المتداولة
            '2200',  # الخصوم طويلة الأجل
            '3000',  # حقوق الملكية
            '4000',  # الإيرادات
            '5000',  # تكلفة المبيعات
            '6000',  # المصروفات التشغيلية
        ]
        
        for code in header_accounts:
            cursor.execute("""
                UPDATE gl_accounts 
                SET is_header = 1 
                WHERE code = ? AND is_header IS NULL
            """, (code,))
        
        # تحديث المستويات
        cursor.execute("UPDATE gl_accounts SET level = 0 WHERE code LIKE '%000' AND parent_id IS NULL")
        cursor.execute("UPDATE gl_accounts SET level = 1 WHERE code LIKE '%00' AND code NOT LIKE '%000'")
        cursor.execute("UPDATE gl_accounts SET level = 2 WHERE code NOT LIKE '%00'")
        
        print(f"   ✅ تم تحديث مستويات الحسابات")
        
        conn.commit()
        
        # =================================================================
        # 5. التحقق النهائي
        # =================================================================
        print("\n📊 التحقق النهائي...")
        
        cursor.execute("SELECT COUNT(*) FROM gl_accounts")
        total_accounts = cursor.fetchone()[0]
        print(f"   📝 إجمالي الحسابات: {total_accounts}")
        
        cursor.execute("SELECT COUNT(*) FROM gl_accounts WHERE is_header = 1")
        header_count = cursor.fetchone()[0]
        print(f"   📂 حسابات رئيسية: {header_count}")
        
        cursor.execute("SELECT COUNT(*) FROM gl_journal_entries")
        total_entries = cursor.fetchone()[0]
        print(f"   📔 إجمالي القيود: {total_entries}")
        
        print("-" * 70)
        print("✅ اكتمل التهجير بنجاح!")
        print("=" * 70)
        
        return True
    
    except Exception as e:
        conn.rollback()
        print(f"\n❌ خطأ في التهجير: {e}")
        import traceback
        traceback.print_exc()
        print("-" * 70)
        print("❌ فشل التهجير - راجع الأخطاء أعلاه")
        print("=" * 70)
        return False
    
    finally:
        conn.close()


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)

