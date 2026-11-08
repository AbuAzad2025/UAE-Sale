"""Route census — استخراج كل مسارات التطبيق وتجميعها حسب الوحدة (module)."""
import io
import sys

sys.path.insert(0, '.')

import os
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret')
os.environ.setdefault('OWNER_PASSWORD', 'TestOwner@1234567890123456!')
os.environ.setdefault('DEBUG', 'true')

from app import create_app  # noqa: E402


def main():
    app = create_app()
    rows = []
    with app.app_context():
        for rule in app.url_map.iter_rules():
            if rule.endpoint == 'static':
                continue
            view_class = app.view_functions.get(rule.endpoint)
            module = getattr(view_class, '__module__', '') if view_class else ''
            rows.append((rule.rule, rule.endpoint, module))
    rows.sort(key=lambda r: (r[2], r[0]))
    by_module = {}
    for rule, endpoint, module in rows:
        by_module.setdefault(module, []).append(rule)
    total = len(rows)
    print(f'TOTAL routes: {total}')
    for module in sorted(by_module):
        print(f'{module}: {len(by_module[module])}')


if __name__ == '__main__':
    main()
