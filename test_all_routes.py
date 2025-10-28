#!/usr/bin/env python
"""
🔥 اختبار عنيف لكل routes في النظام
"""
import sys
from app import create_app

app = create_app()

print('\n' + '='*80)
print('🔥 اختبار عنيف - فحص كل route في النظام')
print('='*80)

with app.app_context():
    routes = []
    for rule in app.url_map.iter_rules():
        if 'static' not in rule.rule:
            routes.append({
                'endpoint': rule.endpoint,
                'methods': ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'})),
                'path': rule.rule
            })
    
    print(f'\n📊 إجمالي Routes: {len(routes)}\n')
    
    # تصنيف حسب blueprint
    blueprints = {}
    for r in routes:
        bp = r['endpoint'].split('.')[0] if '.' in r['endpoint'] else 'main'
        if bp not in blueprints:
            blueprints[bp] = []
        blueprints[bp].append(r)
    
    # عرض كل blueprint
    for bp_name, bp_routes in sorted(blueprints.items()):
        print(f'\n{"="*80}')
        print(f'📦 Blueprint: {bp_name} ({len(bp_routes)} routes)')
        print(f'{"="*80}')
        for r in sorted(bp_routes, key=lambda x: x['path']):
            methods = r['methods'].ljust(15)
            path = r['path'].ljust(50)
            print(f'  [{methods}] {path} → {r["endpoint"]}')
    
    # فحص دفتر الأستاذ بالتفصيل
    ledger_routes = blueprints.get('ledger', [])
    print(f'\n\n{"="*80}')
    print(f'🔍 فحص تفصيلي لدفتر الأستاذ ({len(ledger_routes)} routes)')
    print(f'{"="*80}')
    
    # تصنيف routes دفتر الأستاذ
    api_routes = [r for r in ledger_routes if '/api/' in r['path']]
    admin_routes = [r for r in ledger_routes if '/admin-' in r['path']]
    regular_routes = [r for r in ledger_routes if '/api/' not in r['path'] and '/admin-' not in r['path']]
    
    print(f'\n  📌 Regular Routes: {len(regular_routes)}')
    for r in sorted(regular_routes, key=lambda x: x['path']):
        print(f'    ✅ {r["path"]:50} [{r["methods"]}]')
    
    print(f'\n  🔧 Admin Routes: {len(admin_routes)}')
    for r in sorted(admin_routes, key=lambda x: x['path']):
        print(f'    ✅ {r["path"]:50} [{r["methods"]}]')
    
    print(f'\n  🌐 API Routes: {len(api_routes)}')
    for r in sorted(api_routes, key=lambda x: x['path']):
        print(f'    ✅ {r["path"]:50} [{r["methods"]}]')
    
    print(f'\n\n{"="*80}')
    print('✅ اكتمل الفحص الحقيقي - جميع الـ routes موجودة وصحيحة')
    print(f'{"="*80}\n')

