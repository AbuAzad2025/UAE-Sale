#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
تهجير المرحلة الثانية والثالثة
Phase 2 & 3 Migration

يضيف:
1. جداول مطابقة البنك (bank_reconciliations, bank_reconciliation_items)
2. جداول الموازنة (budgets, budget_lines)
3. جدول مراكز التكلفة (cost_centers)
4. جداول الأصول الثابتة (fixed_assets, depreciation_schedules)
5. cost_center_id لـ gl_journal_lines
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

DB_PATH = project_root / 'instance' / 'app.db'


def migrate():
    """تنفيذ التهجير"""
    print("=" * 70)
    print("🔧 تهجير المرحلة الثانية والثالثة - Phase 2 & 3")
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
        # 1. جدول مطابقة البنك
        # =================================================================
        print("\n📋 إنشاء جدول bank_reconciliations...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bank_reconciliations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reconciliation_number VARCHAR(50) UNIQUE NOT NULL,
                bank_account_id INTEGER NOT NULL,
                period_start DATE NOT NULL,
                period_end DATE NOT NULL,
                opening_balance_per_books NUMERIC(18, 3) DEFAULT 0,
                closing_balance_per_books NUMERIC(18, 3) DEFAULT 0,
                closing_balance_per_bank NUMERIC(18, 3) DEFAULT 0,
                outstanding_deposits NUMERIC(18, 3) DEFAULT 0,
                outstanding_withdrawals NUMERIC(18, 3) DEFAULT 0,
                bank_charges NUMERIC(18, 3) DEFAULT 0,
                bank_interest NUMERIC(18, 3) DEFAULT 0,
                errors_in_books NUMERIC(18, 3) DEFAULT 0,
                errors_in_bank NUMERIC(18, 3) DEFAULT 0,
                status VARCHAR(20) DEFAULT 'draft',
                is_balanced BOOLEAN DEFAULT 0,
                difference NUMERIC(18, 3) DEFAULT 0,
                notes TEXT,
                created_by INTEGER,
                approved_by INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME,
                approved_at DATETIME,
                FOREIGN KEY (bank_account_id) REFERENCES gl_accounts(id),
                FOREIGN KEY (created_by) REFERENCES users(id),
                FOREIGN KEY (approved_by) REFERENCES users(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bank_recon_period ON bank_reconciliations(period_end)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bank_recon_status ON bank_reconciliations(status)")
        print("   ✅ جدول bank_reconciliations")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bank_reconciliation_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reconciliation_id INTEGER NOT NULL,
                item_type VARCHAR(30) NOT NULL,
                transaction_date DATE NOT NULL,
                description VARCHAR(255) NOT NULL,
                amount NUMERIC(18, 3) NOT NULL,
                journal_entry_id INTEGER,
                cheque_id INTEGER,
                is_cleared BOOLEAN DEFAULT 0,
                cleared_date DATE,
                notes TEXT,
                FOREIGN KEY (reconciliation_id) REFERENCES bank_reconciliations(id),
                FOREIGN KEY (journal_entry_id) REFERENCES gl_journal_entries(id),
                FOREIGN KEY (cheque_id) REFERENCES cheques(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bank_recon_items ON bank_reconciliation_items(reconciliation_id)")
        print("   ✅ جدول bank_reconciliation_items")
        
        # =================================================================
        # 2. جداول الموازنة
        # =================================================================
        print("\n📋 إنشاء جداول الموازنة...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                budget_number VARCHAR(50) UNIQUE NOT NULL,
                name_ar VARCHAR(200) NOT NULL,
                name_en VARCHAR(200),
                fiscal_year INTEGER NOT NULL,
                period_type VARCHAR(20) DEFAULT 'annual',
                period_start DATE NOT NULL,
                period_end DATE NOT NULL,
                total_budgeted NUMERIC(18, 3) DEFAULT 0,
                total_actual NUMERIC(18, 3) DEFAULT 0,
                total_variance NUMERIC(18, 3) DEFAULT 0,
                variance_percentage NUMERIC(5, 2) DEFAULT 0,
                status VARCHAR(20) DEFAULT 'draft',
                notes TEXT,
                created_by INTEGER,
                approved_by INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME,
                approved_at DATETIME,
                FOREIGN KEY (created_by) REFERENCES users(id),
                FOREIGN KEY (approved_by) REFERENCES users(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_budget_year ON budgets(fiscal_year)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_budget_status ON budgets(status)")
        print("   ✅ جدول budgets")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS budget_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                budget_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                budgeted_amount NUMERIC(18, 3) NOT NULL,
                actual_amount NUMERIC(18, 3) DEFAULT 0,
                variance NUMERIC(18, 3) DEFAULT 0,
                variance_percentage NUMERIC(8, 2) DEFAULT 0,
                notes TEXT,
                FOREIGN KEY (budget_id) REFERENCES budgets(id),
                FOREIGN KEY (account_id) REFERENCES gl_accounts(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_budget_lines ON budget_lines(budget_id)")
        print("   ✅ جدول budget_lines")
        
        # =================================================================
        # 3. جدول مراكز التكلفة
        # =================================================================
        print("\n📋 إنشاء جدول cost_centers...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cost_centers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code VARCHAR(20) UNIQUE NOT NULL,
                name_ar VARCHAR(200) NOT NULL,
                name_en VARCHAR(200),
                parent_id INTEGER,
                level INTEGER DEFAULT 0,
                center_type VARCHAR(30) DEFAULT 'department',
                manager_id INTEGER,
                budget_amount NUMERIC(18, 3) DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                description TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME,
                FOREIGN KEY (parent_id) REFERENCES cost_centers(id),
                FOREIGN KEY (manager_id) REFERENCES users(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cost_center_code ON cost_centers(code)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cost_center_active ON cost_centers(is_active)")
        print("   ✅ جدول cost_centers")
        
        # =================================================================
        # 4. جداول الأصول الثابتة
        # =================================================================
        print("\n📋 إنشاء جداول الأصول الثابتة...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fixed_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_number VARCHAR(50) UNIQUE NOT NULL,
                name_ar VARCHAR(200) NOT NULL,
                name_en VARCHAR(200),
                description TEXT,
                category VARCHAR(50),
                asset_account_id INTEGER NOT NULL,
                depreciation_account_id INTEGER,
                expense_account_id INTEGER,
                purchase_date DATE NOT NULL,
                purchase_price NUMERIC(18, 3) NOT NULL,
                salvage_value NUMERIC(18, 3) DEFAULT 0,
                depreciation_method VARCHAR(30) DEFAULT 'straight_line',
                useful_life_years INTEGER NOT NULL,
                useful_life_months INTEGER,
                accumulated_depreciation NUMERIC(18, 3) DEFAULT 0,
                book_value NUMERIC(18, 3),
                last_depreciation_date DATE,
                location VARCHAR(200),
                cost_center_id INTEGER,
                status VARCHAR(20) DEFAULT 'active',
                disposal_date DATE,
                disposal_price NUMERIC(18, 3),
                disposal_gain_loss NUMERIC(18, 3),
                notes TEXT,
                created_by INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME,
                FOREIGN KEY (asset_account_id) REFERENCES gl_accounts(id),
                FOREIGN KEY (depreciation_account_id) REFERENCES gl_accounts(id),
                FOREIGN KEY (expense_account_id) REFERENCES gl_accounts(id),
                FOREIGN KEY (cost_center_id) REFERENCES cost_centers(id),
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fixed_asset_status ON fixed_assets(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fixed_asset_category ON fixed_assets(category)")
        print("   ✅ جدول fixed_assets")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS depreciation_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER NOT NULL,
                period_date DATE NOT NULL,
                depreciation_amount NUMERIC(18, 3) NOT NULL,
                accumulated_depreciation NUMERIC(18, 3) NOT NULL,
                book_value NUMERIC(18, 3) NOT NULL,
                journal_entry_id INTEGER,
                notes TEXT,
                created_at DATETIME NOT NULL,
                FOREIGN KEY (asset_id) REFERENCES fixed_assets(id),
                FOREIGN KEY (journal_entry_id) REFERENCES gl_journal_entries(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_depreciation_asset ON depreciation_schedules(asset_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_depreciation_period ON depreciation_schedules(period_date)")
        print("   ✅ جدول depreciation_schedules")
        
        # =================================================================
        # 5. إضافة cost_center_id لـ gl_journal_lines
        # =================================================================
        print("\n📋 تحديث gl_journal_lines...")
        cursor.execute("PRAGMA table_info(gl_journal_lines)")
        gl_line_columns = {row[1] for row in cursor.fetchall()}
        
        if 'cost_center_id' not in gl_line_columns:
            cursor.execute("ALTER TABLE gl_journal_lines ADD COLUMN cost_center_id INTEGER")
            print("   ✅ تم إضافة cost_center_id")
        else:
            print("   ⚠️ cost_center_id موجود مسبقاً")
        
        conn.commit()
        
        # =================================================================
        # 6. التحقق النهائي
        # =================================================================
        print("\n📊 التحقق النهائي...")
        
        tables = [
            'bank_reconciliations',
            'bank_reconciliation_items',
            'budgets',
            'budget_lines',
            'cost_centers',
            'fixed_assets',
            'depreciation_schedules'
        ]
        
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{table}'")
            exists = cursor.fetchone()[0]
            if exists:
                print(f"   ✅ {table}")
            else:
                print(f"   ❌ {table} - فشل الإنشاء!")
        
        print("-" * 70)
        print("✅ اكتمل التهجير بنجاح!")
        print("🚀 النظام المحاسبي المتقدم جاهز 100%")
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

