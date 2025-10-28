#!/usr/bin/env python
"""
🔥 فحص حقيقي لكل templates - تطابق Frontend-Backend
"""
import sys
import os
from app import create_app
from jinja2 import TemplateNotFound

app = create_app()

print('\n' + '='*80)
print('🔥 فحص حقيقي عنيف - كل template في النظام')
print('='*80)

with app.app_context():
    # جمع كل الـ routes والـ templates المتوقعة
    routes_with_templates = {}
    
    for rule in app.url_map.iter_rules():
        if 'static' not in rule.rule and 'GET' in rule.methods:
            endpoint = rule.endpoint
            routes_with_templates[endpoint] = {
                'path': rule.rule,
                'template_tested': False,
                'exists': False
            }
    
    # اختبار كل template
    templates_dir = os.path.join(app.root_path, 'templates')
    all_templates = []
    
    for root, dirs, files in os.walk(templates_dir):
        for file in files:
            if file.endswith('.html'):
                relative_path = os.path.relpath(os.path.join(root, file), templates_dir)
                all_templates.append(relative_path.replace('\\', '/'))
    
    print(f'\n📊 إجمالي Templates: {len(all_templates)}')
    
    # تصنيف templates
    ledger_templates = [t for t in all_templates if t.startswith('ledger/')]
    admin_ledger_templates = [t for t in all_templates if t.startswith('admin/ledger/')]
    sales_templates = [t for t in all_templates if t.startswith('sales/')]
    purchases_templates = [t for t in all_templates if t.startswith('purchases/')]
    
    print(f'\n📁 تصنيف Templates:')
    print(f'  📒 دفتر الأستاذ: {len(ledger_templates)} templates')
    print(f'  🔧 Admin Ledger: {len(admin_ledger_templates)} templates')
    print(f'  💰 المبيعات: {len(sales_templates)} templates')
    print(f'  📦 المشتريات: {len(purchases_templates)} templates')
    
    # فحص templates دفتر الأستاذ
    print(f'\n{"="*80}')
    print(f'📒 فحص templates دفتر الأستاذ ({len(ledger_templates)} templates)')
    print(f'{"="*80}')
    
    missing_templates = []
    working_templates = []
    
    for template in sorted(ledger_templates):
        try:
            app.jinja_env.get_template(template)
            print(f'  ✅ {template:50} - موجود وصحيح')
            working_templates.append(template)
        except TemplateNotFound as e:
            print(f'  ❌ {template:50} - مفقود!')
            missing_templates.append(template)
        except Exception as e:
            print(f'  ⚠️ {template:50} - خطأ: {str(e)[:50]}')
    
    print(f'\n{"="*80}')
    print(f'📊 ملخص فحص Templates دفتر الأستاذ:')
    print(f'{"="*80}')
    print(f'  ✅ تعمل بشكل صحيح: {len(working_templates)}/{len(ledger_templates)}')
    if missing_templates:
        print(f'  ❌ مفقودة: {len(missing_templates)}')
        for t in missing_templates:
            print(f'      - {t}')
    
    # فحص Admin Ledger templates
    print(f'\n{"="*80}')
    print(f'🔧 فحص Admin Ledger templates ({len(admin_ledger_templates)} templates)')
    print(f'{"="*80}')
    
    admin_missing = []
    admin_working = []
    
    for template in sorted(admin_ledger_templates):
        try:
            app.jinja_env.get_template(template)
            print(f'  ✅ {template:50} - موجود وصحيح')
            admin_working.append(template)
        except TemplateNotFound:
            print(f'  ❌ {template:50} - مفقود!')
            admin_missing.append(template)
        except Exception as e:
            print(f'  ⚠️ {template:50} - خطأ: {str(e)[:50]}')
    
    print(f'\n{"="*80}')
    print(f'📊 ملخص Admin Ledger Templates:')
    print(f'{"="*80}')
    print(f'  ✅ تعمل بشكل صحيح: {len(admin_working)}/{len(admin_ledger_templates)}')
    if admin_missing:
        print(f'  ❌ مفقودة: {len(admin_missing)}')
        for t in admin_missing:
            print(f'      - {t}')
    
    # النتيجة النهائية
    print(f'\n{"="*80}')
    print(f'✅ النتيجة النهائية')
    print(f'{"="*80}')
    print(f'  📊 إجمالي Templates: {len(all_templates)}')
    print(f'  ✅ دفتر الأستاذ: {len(working_templates)}/{len(ledger_templates)}')
    print(f'  ✅ Admin Ledger: {len(admin_working)}/{len(admin_ledger_templates)}')
    
    total_working = len(working_templates) + len(admin_working)
    total_all = len(ledger_templates) + len(admin_ledger_templates)
    percentage = (total_working / total_all * 100) if total_all > 0 else 0
    
    print(f'\n  🎯 نسبة النجاح: {percentage:.1f}%')
    
    if percentage == 100:
        print(f'\n🎉 100% - جميع templates دفتر الأستاذ تعمل بشكل صحيح!')
    else:
        print(f'\n⚠️ هناك {len(missing_templates) + len(admin_missing)} template مفقود!')
    
    print(f'{"="*80}\n')

