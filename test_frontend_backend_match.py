#!/usr/bin/env python
"""
🔥 اختبار تطابق Frontend-Backend - فحص عنيف
"""
import sys
import re
from app import create_app
from extensions import db
from models import Sale, Purchase, GLJournalEntry, Expense, Payment
from sqlalchemy import inspect

app = create_app()

print('\n' + '='*80)
print('🔥 فحص تطابق Frontend-Backend - عنيف وشامل')
print('='*80)

with app.app_context():
    inspector = inspect(db.engine)
    
    # فحص 1: Sales - تطابق الحقول
    print(f'\n{"="*80}')
    print('💰 فحص المبيعات (Sales)')
    print('='*80)
    
    sales_columns = [col['name'] for col in inspector.get_columns('sales')]
    print(f'  📊 أعمدة sales في DB: {len(sales_columns)}')
    print(f'    {", ".join(sales_columns[:10])}...')
    
    # قراءة sales/create.html
    with open('templates/sales/create.html', 'r', encoding='utf-8') as f:
        sales_template = f.read()
    
    # البحث عن name= attributes
    form_fields = re.findall(r'name=["\']([^"\']+)["\']', sales_template)
    unique_fields = set([f.split('[')[0] for f in form_fields])
    
    print(f'  📝 حقول في sales/create.html: {len(unique_fields)}')
    print(f'    {", ".join(list(unique_fields)[:10])}...')
    
    # التحقق من التطابق
    sales_model_fields = ['customer_id', 'currency', 'discount_amount', 'shipping_cost', 'tax_rate', 'notes']
    missing_in_template = []
    for field in sales_model_fields:
        if field not in str(form_fields):
            missing_in_template.append(field)
    
    if missing_in_template:
        print(f'  ⚠️ حقول مفقودة في Template: {missing_in_template}')
    else:
        print(f'  ✅ جميع الحقول موجودة في Template')
    
    # فحص 2: Purchases
    print(f'\n{"="*80}')
    print('📦 فحص المشتريات (Purchases)')
    print('='*80)
    
    purchases_columns = [col['name'] for col in inspector.get_columns('purchases')]
    print(f'  📊 أعمدة purchases في DB: {len(purchases_columns)}')
    
    with open('templates/purchases/create.html', 'r', encoding='utf-8') as f:
        purchases_template = f.read()
    
    purchases_fields = re.findall(r'name=["\']([^"\']+)["\']', purchases_template)
    unique_purchases = set([f.split('[')[0] for f in purchases_fields])
    
    print(f'  📝 حقول في purchases/create.html: {len(unique_purchases)}')
    
    purchases_model_fields = ['supplier_id', 'currency', 'tax_rate', 'notes']
    purchases_missing = []
    for field in purchases_model_fields:
        if field not in str(purchases_fields):
            purchases_missing.append(field)
    
    if purchases_missing:
        print(f'  ⚠️ حقول مفقودة: {purchases_missing}')
    else:
        print(f'  ✅ جميع الحقول موجودة')
    
    # فحص 3: Ledger Manual Entry
    print(f'\n{"="*80}')
    print('📒 فحص القيد اليدوي (Manual Entry)')
    print('='*80)
    
    gl_lines_columns = [col['name'] for col in inspector.get_columns('gl_journal_lines')]
    print(f'  📊 أعمدة gl_journal_lines في DB: {len(gl_lines_columns)}')
    print(f'    {", ".join(gl_lines_columns)}')
    
    with open('templates/ledger/manual_entry.html', 'r', encoding='utf-8') as f:
        manual_entry_template = f.read()
    
    # التحقق من وجود حقول debit, credit, account
    has_debit = 'line_' in manual_entry_template and '_debit' in manual_entry_template
    has_credit = 'line_' in manual_entry_template and '_credit' in manual_entry_template
    has_account = 'line_' in manual_entry_template and '_account' in manual_entry_template
    has_description = 'line_' in manual_entry_template and '_description' in manual_entry_template
    
    print(f'  ✅ حقل account: {"موجود" if has_account else "مفقود"}')
    print(f'  ✅ حقل debit: {"موجود" if has_debit else "مفقود"}')
    print(f'  ✅ حقل credit: {"موجود" if has_credit else "مفقود"}')
    print(f'  ✅ حقل description: {"موجود" if has_description else "مفقود"}')
    
    # فحص وجود calculateJournalTotals
    has_calc_function = 'calculateJournalTotals' in manual_entry_template
    print(f'  ✅ دالة calculateJournalTotals: {"موجودة" if has_calc_function else "مفقودة"}')
    
    # النتيجة النهائية
    print(f'\n{"="*80}')
    print('✅ النتيجة: تطابق Frontend-Backend')
    print('='*80)
    
    all_checks = [
        ('Sales Fields', not missing_in_template),
        ('Purchases Fields', not purchases_missing),
        ('Manual Entry - Account', has_account),
        ('Manual Entry - Debit', has_debit),
        ('Manual Entry - Credit', has_credit),
        ('Manual Entry - Description', has_description),
        ('Manual Entry - Calculate Function', has_calc_function)
    ]
    
    passed = sum(1 for _, result in all_checks if result)
    total = len(all_checks)
    
    for check_name, result in all_checks:
        status = "✅" if result else "❌"
        print(f'  {status} {check_name:40} {"نجح" if result else "فشل"}')
    
    print(f'\n  🎯 النتيجة: {passed}/{total} ({passed/total*100:.0f}%)')
    
    if passed == total:
        print(f'\n🎉 100% - جميع الفحوصات نجحت!')
        print('='*80)
    else:
        print(f'\n⚠️ هناك {total - passed} فحص فشل!')
        print('='*80)

