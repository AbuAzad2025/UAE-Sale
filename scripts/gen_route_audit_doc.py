"""تولید docs/ROUTE_ISOLATION_AUDIT.md من المستودع الفعلي."""
import io
import os
import sys

sys.path.insert(0, '.')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret')
os.environ.setdefault('OWNER_PASSWORD', 'TestOwner@1234567890123456!')
os.environ.setdefault('DEBUG', 'true')

from app import create_app  # noqa: E402
from utils import route_scope  # noqa: E402


def main():
    app = create_app()
    audit = route_scope.audit_routes(app)
    audit.sort(key=lambda e: (e['module'], e['path']))

    lines = [
        '# Route Isolation Audit — 499 مسارًا',
        '',
        '**توليد:** `scripts/gen_route_audit_doc.py` — لا يُعدَّل يدويًا؛ أي تغيير يُعاد توليد',
        'الفحص عبر التشغيل: `python -m scripts.gen_route_audit_doc` والالتزام بها في كل',
        'دفعة يمر بها CI (tests/unit/test_route_isolation_census.py يرفض أي مسار جديد',
        'غير مصنَّف أو أي مسار tenant بدون رمز عزل).',
        '',
        '**المعنى:**',
        '',
        '* `public` — لا بيانات مستأجر (صفحة تسويق/دعم/توثيق) — يمكن أن تكون مفتوحة',
        '* `system` — نقاط فحص ورصد (health/version/metrics) — لا بيانات أيضًا',
        '* `platform` — لوحة المالك / بيع باقات المنصة — `is_owner` أو فوقها',
        '* `tenant` — بيانات الشركة حصرًا ويجب أن يحمل رمز تمرير عزل واحدًا على',
        '  الأقل (get_owned_or_404 أو tenant_id أو ما يكافئها)',
        '',
        '**التنفيذ:** المسار `tenant` في حال عدم المطابقة يمنع POST/GET بدون `is_owner`،',
        'وهو شرط CI صارم (route_isolation_census).',
        '',
    ]

    counters = {}
    seen_modules = {}
    for e in audit:
        seen_modules.setdefault(e['module'], []).append(e)
    for module, rows in seen_modules.items():
        scope = rows[0]['scope']
        lines.append(f'## {module} ({scope}) — {len(rows)} مسار')
        lines.append('')
        lines.append('| Path | Endpoint | Scope | Markers |')
        lines.append('|---|---|---|---|')
        for r in rows:
            markers = ', '.join(r['markers']) or '—'
            lines.append(f"| `{r['path']}` | `{r['endpoint']}` | {r['scope']} | {markers} |")
        lines.append('')
        counters[module] = len(rows)

    scope_count = {}
    marker_count = {}
    for e in audit:
        scope_count[e['scope']] = scope_count.get(e['scope'], 0) + 1
        for m in e['markers']:
            marker_count[m] = marker_count.get(m, 0) + 1

    lines.append('## الملخص')
    lines.append('')
    lines.append(f'* **إجمالي المسارات:** {len(audit)}')
    for scope in sorted(scope_count):
        lines.append(f'* **{scope}:** {scope_count[scope]}')
    lines.append('')
    lines.append('### أكثر علامات العزل استخدامًا')
    for marker, count in sorted(marker_count.items(), key=lambda kv: -kv[1]):
        lines.append(f'* `{marker}`: {count}')
    lines.append('')
    lines.append('**ملاحظة قانونية:** هذه المسارد حصرًا على مستوى الكود. لا شرط فيها')
    lines.append('يتعلق بمعايير التدقيق الخارجي أو اعتماد منصات سلطة. الامتثال القانوني')
    lines.append('لكل دولة يتطلب عقدًا وشهادة من السلطة؛ هذا المستند يتتبع العزل التقني')
    lines.append('بين الشركات فقط.')

    io.open('docs/ROUTE_ISOLATION_AUDIT.md', 'w', encoding='utf-8').write(
        '\n'.join(lines))
    print('written docs/ROUTE_ISOLATION_AUDIT.md')


if __name__ == '__main__':
    main()
