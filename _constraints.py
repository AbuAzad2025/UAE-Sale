"""Extract the exact CHECK constraint SQL from the updated models."""
import os
import sys

ROOT = r'D:\recovers\data\UAE-Sale'
sys.path.insert(0, ROOT)
os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'a')
os.environ.setdefault('OWNER_PASSWORD', 'E2eOwner@1234567890123456!')
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import create_app  # noqa: E402
from config import Config  # noqa: E402


class C(Config):
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ENGINE_OPTIONS = {'connect_args': {'check_same_thread': False}}
    RATELIMIT_ENABLED = False


app = create_app(C)

with app.app_context():
    from models.gl import GLAccount
    from models.product import Product
    from models.sale import Sale, SaleLine
    from models.purchase import Purchase, PurchaseLine
    from models.payment import Payment, Receipt

    out = []
    for m in (Product, Sale, SaleLine, Purchase, PurchaseLine, Payment, Receipt):
        out.append(f'--- {m.__tablename__} ---')
        for item in (getattr(m, '__table_args__', ()) or ()):
            name = getattr(item, 'name', None)
            if name and name.startswith('ck_'):
                txt = item.sqltext
                out.append(f'  {name}: {txt}')

    with open(os.path.join(ROOT, '_constraints.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
print('done')
