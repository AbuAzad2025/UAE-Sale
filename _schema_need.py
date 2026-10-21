"""Extract the schema the updated models require, to write the migration."""
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
    from models.erp_modules import FiscalPeriod
    from models.customer import Customer
    from models.supplier import Supplier
    from models.payment import Payment, Receipt
    from models.product import Product
    from models.sale import Sale, SaleLine
    from models.purchase import Purchase, PurchaseLine

    out = []

    def dump(model, cols=None):
        out.append(f'--- {model.__tablename__} ---')
        t = model.__table__
        for c in t.columns:
            if cols and c.name not in cols:
                continue
            fks = [f'{fk.target_fullname}' for fk in c.foreign_keys]
            out.append(f'  {c.name:<28} {c.type} null={c.nullable} '
                       f'idx={c.index} fk={fks}')
        ta = getattr(model, '__table_args__', ())
        if ta:
            for item in ta:
                out.append(f'  CONSTRAINT: {item}')

    dump(GLAccount, {'is_system'})
    dump(FiscalPeriod, {'tenant_id'})
    dump(Customer, {'opening_balance', 'opening_balance_currency',
                    'opening_balance_rate', 'opening_balance_date'})
    dump(Supplier, {'opening_balance', 'opening_balance_currency',
                    'opening_balance_rate', 'opening_balance_date'})
    dump(Payment, {'purchase_id'})
    dump(Receipt, {'allocations_json'})
    for m in (Product, Sale, SaleLine, Purchase, PurchaseLine, Payment, Receipt):
        dump(m)

    out.append('--- GLAccount.CORE_CODES ---')
    out.append(repr(sorted(getattr(GLAccount, 'CORE_CODES', ()))))

    with open(os.path.join(ROOT, '_schema_need.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
print('done')
