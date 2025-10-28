#!/usr/bin/env python
"""
🔥 فحص التكرار والنقص في الـ routes
"""
from app import create_app
from collections import defaultdict

app = create_app()

print('\n' + '='*80)
print('🔥 فحص التكرار والنقص في الـ routes - عنيف')
print('='*80)

with app.app_context():
    # جمع كل الـ routes
    all_routes = []
    paths_count = defaultdict(int)
    endpoints_count = defaultdict(int)
    
    for rule in app.url_map.iter_rules():
        if 'static' not in rule.rule:
            all_routes.append({
                'path': rule.rule,
                'endpoint': rule.endpoint,
                'methods': sorted(rule.methods - {'HEAD', 'OPTIONS'})
            })
            paths_count[rule.rule] += 1
            endpoints_count[rule.endpoint] += 1
    
    print(f'\n📊 إجمالي Routes: {len(all_routes)}')
    
    # فحص التكرار في الـ paths
    print(f'\n{"="*80}')
    print('🔍 فحص تكرار الـ Paths')
    print('='*80)
    
    duplicated_paths = {path: count for path, count in paths_count.items() if count > 1}
    
    if duplicated_paths:
        print(f'  ❌ وجد {len(duplicated_paths)} path مكرر:')
        for path, count in duplicated_paths.items():
            print(f'    {path} - مكرر {count} مرة')
            # عرض الـ endpoints المكررة
            dup_endpoints = [r['endpoint'] for r in all_routes if r['path'] == path]
            for ep in dup_endpoints:
                print(f'      → {ep}')
    else:
        print(f'  ✅ لا يوجد تكرار في الـ paths')
    
    # فحص التكرار في الـ endpoints
    print(f'\n{"="*80}')
    print('🔍 فحص تكرار الـ Endpoints')
    print('='*80)
    
    duplicated_endpoints = {ep: count for ep, count in endpoints_count.items() if count > 1}
    
    if duplicated_endpoints:
        print(f'  ❌ وجد {len(duplicated_endpoints)} endpoint مكرر:')
        for endpoint, count in duplicated_endpoints.items():
            print(f'    {endpoint} - مكرر {count} مرة')
    else:
        print(f'  ✅ لا يوجد تكرار في الـ endpoints')
    
    # فحص الـ routes المتضاربة (نفس الـ path لكن methods مختلفة)
    print(f'\n{"="*80}')
    print('🔍 فحص Routes المتضاربة')
    print('='*80)
    
    path_methods = defaultdict(list)
    for route in all_routes:
        path_methods[route['path']].append({
            'endpoint': route['endpoint'],
            'methods': route['methods']
        })
    
    conflicts = []
    for path, routes in path_methods.items():
        if len(routes) > 1:
            # تحقق إذا كان فيه تضارب في الـ methods
            all_methods = []
            for r in routes:
                all_methods.extend(r['methods'])
            
            if len(all_methods) != len(set(all_methods)):
                conflicts.append(path)
    
    if conflicts:
        print(f'  ❌ وجد {len(conflicts)} route متضارب:')
        for path in conflicts:
            print(f'    {path}')
            for r in path_methods[path]:
                print(f'      → {r["endpoint"]} [{",".join(r["methods"])}]')
    else:
        print(f'  ✅ لا يوجد تضارب في الـ routes')
    
    # فحص دفتر الأستاذ بالتفصيل
    print(f'\n{"="*80}')
    print('📒 فحص دفتر الأستاذ - Routes & Templates')
    print('='*80)
    
    ledger_routes = [r for r in all_routes if r['endpoint'].startswith('ledger.')]
    admin_ledger_routes = [r for r in all_routes if r['endpoint'].startswith('admin_ledger.')]
    advanced_ledger_routes = [r for r in all_routes if r['endpoint'].startswith('advanced_ledger.')]
    
    print(f'\n  📦 Blueprints:')
    print(f'    ✅ ledger: {len(ledger_routes)} routes')
    print(f'    ✅ admin_ledger: {len(admin_ledger_routes)} routes')
    print(f'    ✅ advanced_ledger: {len(advanced_ledger_routes)} routes')
    
    # التحقق من عدم وجود تكرار بين الـ blueprints
    ledger_paths = set(r['path'] for r in ledger_routes)
    admin_ledger_paths = set(r['path'] for r in admin_ledger_routes)
    advanced_ledger_paths = set(r['path'] for r in advanced_ledger_routes)
    
    overlap_ledger_admin = ledger_paths & admin_ledger_paths
    overlap_ledger_advanced = ledger_paths & advanced_ledger_paths
    overlap_admin_advanced = admin_ledger_paths & advanced_ledger_paths
    
    if overlap_ledger_admin or overlap_ledger_advanced or overlap_admin_advanced:
        print(f'\n  ❌ تكرار بين blueprints دفتر الأستاذ:')
        if overlap_ledger_admin:
            print(f'    ledger ∩ admin_ledger: {overlap_ledger_admin}')
        if overlap_ledger_advanced:
            print(f'    ledger ∩ advanced_ledger: {overlap_ledger_advanced}')
        if overlap_admin_advanced:
            print(f'    admin_ledger ∩ advanced_ledger: {overlap_admin_advanced}')
    else:
        print(f'\n  ✅ لا تكرار بين blueprints دفتر الأستاذ')
    
    # النتيجة النهائية
    print(f'\n{"="*80}')
    print('✅ النتيجة النهائية')
    print('='*80)
    
    total_issues = len(duplicated_paths) + len(duplicated_endpoints) + len(conflicts)
    
    if total_issues == 0:
        print(f'\n  🎉 100% - لا توجد مشاكل!')
        print(f'  ✅ لا تكرار في الـ paths')
        print(f'  ✅ لا تكرار في الـ endpoints')
        print(f'  ✅ لا تضارب في الـ routes')
        print(f'  ✅ لا تكرار بين blueprints دفتر الأستاذ')
    else:
        print(f'\n  ❌ وجد {total_issues} مشكلة!')
    
    print(f'\n{"="*80}\n')

