#!/usr/bin/env python
"""
🔥 فحص كامل للـ models والجداول - عنيف
"""
from app import create_app
from extensions import db
from sqlalchemy import inspect
import importlib
import os

app = create_app()

print('\n' + '='*80)
print('🔥 فحص Models والجداول - عنيف وشامل')
print('='*80)

with app.app_context():
    inspector = inspect(db.engine)
    db_tables = set(inspector.get_table_names())
    
    print(f'\n📊 إجمالي الجداول في DB: {len(db_tables)}')
    
    # استيراد جميع الـ models
    from models import *
    
    # جمع جميع الـ models
    model_classes = []
    model_tables = set()
    
    globals_copy = dict(globals())
    for name, obj in globals_copy.items():
        if hasattr(obj, '__tablename__') and hasattr(obj, '__table__'):
            model_classes.append(obj)
            model_tables.add(obj.__tablename__)
    
    print(f'📦 إجمالي Models في الكود: {len(model_classes)}')
    
    # فحص الجداول المفقودة
    print(f'\n{"="*80}')
    print('🔍 فحص الجداول المفقودة')
    print('='*80)
    
    missing_tables = model_tables - db_tables
    extra_tables = db_tables - model_tables
    
    if missing_tables:
        print(f'  ❌ جداول مفقودة في DB ({len(missing_tables)}):')
        for table in sorted(missing_tables):
            print(f'    - {table}')
    else:
        print(f'  ✅ جميع جداول الـ Models موجودة في DB')
    
    if extra_tables:
        print(f'\n  ⚠️ جداول إضافية في DB (غير معرفة في Models): {len(extra_tables)}')
        for table in sorted(extra_tables):
            # تجاهل جداول Flask-Migrate و Alembic
            if not table.startswith('alembic') and table != 'migration_log':
                print(f'    - {table}')
    
    # فحص تفصيلي لجداول المحاسبة
    print(f'\n{"="*80}')
    print('📒 فحص تفصيلي لجداول المحاسبة')
    print('='*80)
    
    accounting_tables = {
        'gl_accounts': ['id', 'code', 'name', 'name_ar', 'parent_id', 'type', 'currency', 
                        'is_active', 'is_header', 'level', 'description', 'created_at', 'updated_at'],
        'gl_journal_entries': ['id', 'entry_number', 'entry_date', 'description', 'reference_type', 
                               'reference_id', 'entry_type', 'currency', 'exchange_rate', 'total_debit', 
                               'total_credit', 'is_posted', 'is_reversed', 'reversed_entry_id', 'notes', 
                               'created_by', 'created_at', 'updated_at'],
        'gl_journal_lines': ['id', 'entry_id', 'account_id', 'description', 'debit', 'credit', 
                             'amount_aed', 'cost_center_id'],
        'cheques': ['id', 'cheque_type', 'cheque_bank_number', 'amount', 'currency', 'amount_aed', 
                    'issue_date', 'due_date', 'status', 'customer_id', 'supplier_id', 'sale_id', 
                    'purchase_id', 'payment_id', 'bank_name', 'notes', 'cleared_date', 'bounce_reason', 
                    'created_at', 'updated_at']
    }
    
    for table_name, expected_columns in accounting_tables.items():
        if table_name in db_tables:
            actual_columns = [col['name'] for col in inspector.get_columns(table_name)]
            missing_cols = set(expected_columns) - set(actual_columns)
            extra_cols = set(actual_columns) - set(expected_columns)
            
            print(f'\n  📋 {table_name}:')
            print(f'    ✅ الجدول موجود ({len(actual_columns)} أعمدة)')
            
            if missing_cols:
                print(f'    ❌ أعمدة مفقودة: {list(missing_cols)}')
            
            if extra_cols:
                print(f'    ℹ️ أعمدة إضافية: {list(extra_cols)}')
            
            if not missing_cols:
                print(f'    ✅ جميع الأعمدة المطلوبة موجودة')
        else:
            print(f'\n  ❌ {table_name}: الجدول مفقود تماماً!')
    
    # النتيجة النهائية
    print(f'\n{"="*80}')
    print('✅ النتيجة النهائية')
    print('='*80)
    
    issues = []
    
    if missing_tables:
        issues.append(f'{len(missing_tables)} جدول مفقود في DB')
    
    # فحص أعمدة المحاسبة
    accounting_issues = 0
    for table_name, expected_columns in accounting_tables.items():
        if table_name in db_tables:
            actual_columns = [col['name'] for col in inspector.get_columns(table_name)]
            missing_cols = set(expected_columns) - set(actual_columns)
            if missing_cols:
                accounting_issues += len(missing_cols)
    
    if accounting_issues > 0:
        issues.append(f'{accounting_issues} عمود مفقود في جداول المحاسبة')
    
    if issues:
        print(f'\n  ❌ وجد مشاكل:')
        for issue in issues:
            print(f'    - {issue}')
    else:
        print(f'\n  🎉 100% - لا مشاكل!')
        print(f'  ✅ جميع الجداول موجودة')
        print(f'  ✅ جميع الأعمدة موجودة')
        print(f'  ✅ لا نقص في الـ Models')
    
    print(f'\n{"="*80}\n')

