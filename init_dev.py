"""First-run setup script for UAE-Sale dev environment.

This script:
1. Applies all alembic migrations to create the schema
2. Seeds the master owner account
3. Seeds all default permissions, roles
4. Seeds default chart of accounts (GL accounts)
5. Seeds default system settings
6. Seeds default product categories
7. Seeds default expense categories
8. Seeds default warehouse
9. Seeds demo data (a demo tenant with sample customer/product)

Usage:
    python init_dev.py
"""
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

# Environment setup - all needed before any app import
os.environ['FLASK_ENV'] = 'development'
os.environ['DEBUG'] = '1'
os.environ['SECRET_KEY'] = 'dev-test-secret-key-2026'
os.environ['CARD_ENCRYPTION_KEY'] = 'card-encryption-key-2026'
os.environ['OWNER_PASSWORD'] = 'TestOwner@1983@yyyy!'
os.environ['OWNER_USERNAME'] = 'owner'
os.environ['DATABASE_URL'] = 'postgresql://postgres:123@localhost:5432/uae_sale_dev'
os.environ['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:123@localhost:5432/uae_sale_dev'
os.environ['MASTER_KEY_SEED'] = 'Azad@1983'
os.environ['CACHE_TYPE'] = 'SimpleCache'
os.environ['RATELIMIT_STORAGE_URI'] = 'memory://'
os.environ['RATELIMIT_ENABLED'] = 'false'
os.environ['APP_ENV'] = 'testing'  # so app skips ensure_system_integrity
os.environ['SYSTEM_INTEGRITY_FORCE'] = '0'  # but we seed manually below

sys.path.insert(0, r'D:\recovers\data\UAE-Sale')

# Now import
from app import create_app
app = create_app()


def apply_migrations():
    """Apply all alembic migrations to the database."""
    from alembic.config import Config
    from alembic import command

    cfg = Config(os.path.join(
        os.path.dirname(os.path.abspath('app.py')),
        'migrations', 'alembic.ini',
    ))
    cfg.set_main_option('script_location', 'migrations')
    cfg.set_main_option('sqlalchemy.url',
                       os.environ['SQLALCHEMY_DATABASE_URI'])

    # alembic env.py uses current_app, so we need a Flask app context
    with app.app_context():
        print('[migrations] Running upgrade to head ...')
        command.upgrade(cfg, 'head')
        print('[migrations] OK - schema is at head')


def seed_owner():
    """Seed the master owner account with daily-rotating master key support."""
    from extensions import db
    from models import User, Role
    from werkzeug.security import generate_password_hash

    with app.app_context():
        # Owner role
        owner_role = Role.query.filter_by(slug='owner').first()
        if not owner_role:
            owner_role = Role(name='Owner', name_ar='مالك', slug='owner',
                               description='Platform owner with full access',
                               is_active=True)
            db.session.add(owner_role)
            db.session.commit()
            print('[owner] Created owner role')

        # Owner user
        owner = User.query.filter_by(is_owner=True).first()
        if not owner:
            owner = User(
                username='owner',
                email='owner@uae-sale.local',
                full_name='System Owner',
                full_name_ar='مالك النظام',
                role_id=owner_role.id,
                is_owner=True,
                is_active=True,
                email_verified=True,
            )
            owner.set_password(os.environ['OWNER_PASSWORD'])
            db.session.add(owner)
            db.session.commit()
            print(f'[owner] Created owner user: {owner.username}')
        else:
            print(f'[owner] Owner user already exists: {owner.username}')


def seed_permissions():
    """Seed all default permissions and attach them to roles."""
    from extensions import db
    from models import Permission, Role
    from utils.system_init import _ensure_permissions, _ensure_owner_role, _ensure_super_admin_role, _ensure_developer_role

    with app.app_context():
        _ensure_permissions()
        _ensure_owner_role()
        _ensure_super_admin_role()
        _ensure_developer_role()
        db.session.commit()
        print('[permissions] OK')


def seed_gl_accounts():
    """Seed the default chart of accounts."""
    from extensions import db
    from models import GLAccount

    with app.app_context():
        # Standard chart of accounts for ERP
        # (code, name, name_ar, type)
        default_accounts = [
            # Assets
            ('1000', 'Cash', 'النقدية', 'asset'),
            ('1010', 'Bank', 'البنك', 'asset'),
            ('1100', 'Accounts Receivable', 'المدينون', 'asset'),
            ('1140', 'Inventory', 'المخزون', 'asset'),
            ('1200', 'Prepaid Expenses', 'مصروفات مقدمة', 'asset'),
            ('1500', 'Fixed Assets', 'الأصول الثابتة', 'asset'),
            # Liabilities
            ('2000', 'Accounts Payable', 'الدائنون', 'liability'),
            ('2100', 'VAT Payable', 'ضريبة مستحقة', 'liability'),
            # Equity
            ('3000', 'Owner Equity', 'حقوق الملكية', 'equity'),
            ('3100', 'Retained Earnings', 'أرباح محتجزة', 'equity'),
            ('3200', 'Owner Draws', 'مسحوبات شخصية', 'equity'),
            # Revenue
            ('4000', 'Sales Revenue', 'إيرادات المبيعات', 'revenue'),
            ('4100', 'Service Revenue', 'إيرادات الخدمات', 'revenue'),
            ('4200', 'Sales Returns', 'مردودات المبيعات', 'revenue'),
            ('4900', 'Other Income', 'إيرادات أخرى', 'revenue'),
            # COGS
            ('5000', 'Cost of Goods Sold', 'تكلفة البضاعة المباعة', 'cogs'),
            ('5100', 'COGS Adjustment', 'تعديل تكلفة البضاعة', 'cogs'),
            # Expenses
            ('6000', 'Salaries & Wages', 'الرواتب والأجور', 'expense'),
            ('6100', 'Rent Expense', 'إيجار', 'expense'),
            ('6200', 'Utilities', 'مرافق', 'expense'),
            ('6300', 'Office Supplies', 'لوازم مكتبية', 'expense'),
            ('6400', 'Marketing', 'تسويق', 'expense'),
            ('6500', 'Transportation', 'مواصلات', 'expense'),
            ('6600', 'Communications', 'اتصالات', 'expense'),
            ('6700', 'Depreciation Expense', 'مصروف إهلاك', 'expense'),
            ('6800', 'Insurance', 'تأمين', 'expense'),
            ('6900', 'Bank Fees', 'رسوم بنكية', 'expense'),
            ('6990', 'Miscellaneous Expenses', 'مصروفات متنوعة', 'expense'),
            # FX
            ('7100', 'FX Gain', 'أرباح عملات', 'revenue'),
            ('7200', 'FX Loss', 'خسائر عملات', 'expense'),
        ]

        added = 0
        for code, name, name_ar, acc_type in default_accounts:
            existing = GLAccount.query.filter_by(code=code).first()
            if existing:
                continue
            try:
                acc = GLAccount(
                    code=code,
                    name=name,
                    name_ar=name_ar,
                    type=acc_type,
                    currency='AED',
                    is_active=True,
                )
                db.session.add(acc)
                added += 1
            except Exception as e:
                print(f'[gl] WARN: cannot add {code} - {e}')

        if added:
            try:
                db.session.commit()
                print(f'[gl] Added {added} default accounts')
            except Exception as e:
                db.session.rollback()
                print(f'[gl] WARN: commit failed - {e}')
        else:
            print('[gl] All default accounts already present')


def seed_settings():
    """Seed default system settings."""
    from extensions import db
    from models import SystemSettings, Tenant, Currency

    with app.app_context():
        # Default tenant
        default_tenant = Tenant.query.first()
        if not default_tenant:
            default_tenant = Tenant(
                name='Default Tenant',
                name_ar='المستأجر الافتراضي',
                slug='default',
                is_active=True,
            )
            db.session.add(default_tenant)
            db.session.commit()
            print('[settings] Created default tenant')

        # Default system settings
        settings = SystemSettings.query.first()
        if not settings:
            try:
                settings = SystemSettings(
                    system_name='UAE Sale Co.',
                    system_version='1.0.0',
                    system_mode='production',
                    theme='default',
                    default_language='ar',
                    available_languages='ar,en',
                    rtl_enabled=True,
                    timezone='Asia/Dubai',
                    default_currency='AED',
                    currency_symbol='د.إ',
                    enable_tax=True,
                    tax_name_ar='ضريبة القيمة المضافة',
                    tax_name_en='VAT',
                    enable_sales=True,
                    enable_purchases=True,
                    enable_inventory=True,
                    enable_customers=True,
                    enable_suppliers=True,
                    enable_expenses=True,
                    enable_gl=True,
                    enable_reports=True,
                    enable_ai_assistant=True,
                    enable_pos=True,
                    enable_ecommerce=True,
                    enable_barcode_scanner=True,
                    enable_multi_warehouse=True,
                    enable_multi_currency=True,
                    enable_discounts=True,
                    enable_returns=True,
                    enable_batches=False,
                    enable_serials=False,
                    session_timeout=30,
                    password_min_length=8,
                    items_per_page=20,
                    enable_caching=True,
                    cache_ttl=300,
                    enable_compression=True,
                    auto_backup_enabled=True,
                    backup_frequency='daily',
                    backup_retention_days=30,
                    is_active=True,
                )
                db.session.add(settings)
                db.session.commit()
                print('[settings] Created default system settings')
            except Exception as e:
                db.session.rollback()
                print(f'[settings] WARN: {e}')
        else:
            print('[settings] System settings already exist')


def seed_currencies():
    """Seed default currencies."""
    from extensions import db
    from models import Currency, ExchangeRate

    with app.app_context():
        default_currencies = [
            ('AED', 'UAE Dirham', 'UAE Dirham', 1.0),
            ('SAR', 'Saudi Riyal', 'Saudi Riyal', 1.0),
            ('USD', 'US Dollar', 'US Dollar', 3.6725),
            ('EUR', 'Euro', 'Euro', 4.0),
            ('GBP', 'British Pound', 'British Pound', 4.7),
            ('JOD', 'Jordanian Dinar', 'Jordanian Dinar', 5.18),
            ('ILS', 'Israeli Shekel', 'Israeli Shekel', 1.0),
            ('EGP', 'Egyptian Pound', 'Egyptian Pound', 0.075),
        ]
        added = 0
        for code, name, name_ar, rate_to_aed in default_currencies:
            existing = Currency.query.filter_by(code=code).first()
            if existing:
                continue
            try:
                curr = Currency(
                    code=code, name=name, name_ar=name_ar,
                )
                db.session.add(curr)
                db.session.flush()
                added += 1
            except Exception as e:
                print(f'[currency] WARN: cannot add {code} - {e}')

        if added:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
            print(f'[currencies] Added {added} default currencies')
        else:
            print('[currencies] All default currencies present')


def seed_exchange_rates():
    """Seed default exchange rates for currencies that have been added."""
    from extensions import db
    from models import Currency, ExchangeRate

    with app.app_context():
        # Get all currencies
        currencies = Currency.query.all()
        for curr in currencies:
            if curr.code == 'AED':
                continue
            existing = ExchangeRate.query.filter_by(
                from_currency=curr.code, to_currency='AED').first()
            if existing:
                continue
            try:
                er = ExchangeRate(
                    from_currency=curr.code,
                    to_currency='AED',
                    rate=Decimal('3.6725'),  # default
                    source='manual',
                    is_manual=True,
                )
                db.session.add(er)
            except Exception as e:
                print(f'[exchangerate] WARN: cannot add {curr.code} - {e}')
        try:
            db.session.commit()
            print('[exchangerates] Default rates seeded')
        except Exception:
            db.session.rollback()


def seed_warehouse():
    """Seed a default main warehouse."""
    from extensions import db
    from models import Warehouse

    with app.app_context():
        main_wh = Warehouse.query.filter_by(is_main=True).first()
        if not main_wh:
            try:
                main_wh = Warehouse(
                    name='Main Warehouse',
                    name_ar='المستودع الرئيسي',
                    code='WH-MAIN',
                    location='Dubai, UAE',
                    is_active=True,
                    is_main=True,
                )
                db.session.add(main_wh)
                db.session.commit()
                print('[warehouse] Created main warehouse')
            except Exception as e:
                db.session.rollback()
                print(f'[warehouse] WARN: {e}')


def seed_product_categories():
    """Seed default product categories."""
    from extensions import db
    from models import ProductCategory

    with app.app_context():
        default_categories = [
            ('Electronics', 'إلكترونيات'),
            ('Spare Parts', 'قطع غيار'),
            ('Accessories', 'إكسسوارات'),
            ('Tools', 'أدوات'),
            ('Consumables', 'مواد استهلاكية'),
        ]
        added = 0
        for name, name_ar in default_categories:
            existing = ProductCategory.query.filter_by(name=name).first()
            if existing:
                continue
            try:
                cat = ProductCategory(
                    name=name, name_ar=name_ar,
                    is_active=True,
                )
                db.session.add(cat)
                added += 1
            except Exception as e:
                print(f'[cat] WARN: {e}')

        if added:
            try:
                db.session.commit()
                print(f'[categories] Added {added} default categories')
            except Exception:
                db.session.rollback()
        else:
            print('[categories] All default categories present')


def seed_expense_categories():
    """Seed default expense categories."""
    from extensions import db
    from models import ExpenseCategory

    with app.app_context():
        default_cats = [
            ('Salaries', 'الرواتب', '6000'),
            ('Rent', 'الإيجار', '6100'),
            ('Utilities', 'المرافق', '6200'),
            ('Office Supplies', 'لوازم مكتبية', '6300'),
            ('Marketing', 'تسويق', '6400'),
            ('Transportation', 'مواصلات', '6500'),
            ('Communications', 'اتصالات', '6600'),
            ('Insurance', 'تأمين', '6800'),
            ('Bank Fees', 'رسوم بنكية', '6900'),
            ('Miscellaneous', 'متنوعة', '6990'),
        ]
        added = 0
        for name, name_ar, gl_code in default_cats:
            existing = ExpenseCategory.query.filter_by(name=name).first()
            if existing:
                continue
            try:
                cat = ExpenseCategory(
                    name=name, name_ar=name_ar,
                    gl_account_code=gl_code,
                    is_active=True,
                )
                db.session.add(cat)
                added += 1
            except Exception as e:
                print(f'[exp_cat] WARN: {e}')

        if added:
            db.session.commit()
            print(f'[expense_categories] Added {added} default categories')


def seed_industries():
    """Seed default industries (if Industry model exists)."""
    try:
        from models import Industry
        return  # skip if model doesn't exist
    except ImportError:
        return

    from extensions import db
    with app.app_context():
        defaults = [
            ('Automotive', 'سيارات'),
            ('Electronics', 'إلكترونيات'),
            ('Industrial', 'صناعي'),
            ('Retail', 'تجزئة'),
        ]
        added = 0
        for name, name_ar in defaults:
            existing = Industry.query.filter_by(name=name).first()
            if existing:
                continue
            try:
                ind = Industry(name=name, name_ar=name_ar, is_active=True)
                db.session.add(ind)
                added += 1
            except Exception as e:
                print(f'[industry] WARN: {e}')
        if added:
            db.session.commit()
            print(f'[industries] Added {added} industries')


def seed_demo_data():
    """Seed a demo customer, supplier, and product so the UI has
    something to display on first run."""
    from extensions import db
    from models import Customer, Supplier, Product, Warehouse, ProductCategory, User, Tenant, Role

    with app.app_context():
        # Find a tenant to associate demo data with
        tenant = Tenant.query.first()
        tenant_id = tenant.id if tenant else None

        # Demo customer
        demo_cust = Customer.query.filter_by(name='Demo Customer').first()
        if not demo_cust:
            try:
                demo_cust = Customer(
                    name='Demo Customer',
                    name_ar='عميل تجريبي',
                    customer_type='regular',
                    phone='+971501234567',
                    email='demo@uae-sale.local',
                    is_active=True,
                    tenant_id=tenant_id,
                )
                db.session.add(demo_cust)
                print('[demo] Created demo customer')
            except Exception as e:
                print(f'[demo] WARN: customer - {e}')

        # Demo supplier
        demo_sup = Supplier.query.filter_by(name='Demo Supplier').first()
        if not demo_sup:
            try:
                demo_sup = Supplier(
                    name='Demo Supplier',
                    name_ar='مورد تجريبي',
                    phone='+971509876543',
                    email='supplier@uae-sale.local',
                    is_active=True,
                    tenant_id=tenant_id,
                )
                db.session.add(demo_sup)
                print('[demo] Created demo supplier')
            except Exception as e:
                print(f'[demo] WARN: supplier - {e}')

        # Demo product (linked to first warehouse and category)
        demo_prod = Product.query.filter_by(sku='DEMO-001').first()
        if not demo_prod:
            try:
                cat = ProductCategory.query.first()
                demo_prod = Product(
                    name='Demo Product',
                    name_ar='منتج تجريبي',
                    sku='DEMO-001',
                    category_id=cat.id if cat else None,
                    cost_price=Decimal('50.000'),
                    regular_price=Decimal('100.000'),
                    current_stock=Decimal('100.000'),
                    min_stock_alert=Decimal('10.000'),
                    is_active=True,
                    tenant_id=tenant_id,
                )
                db.session.add(demo_prod)
                print('[demo] Created demo product')
            except Exception as e:
                print(f'[demo] WARN: product - {e}')

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'[demo] WARN: commit - {e}')

        # Demo manager user (optional)
        manager = User.query.filter_by(username='manager').first()
        if not manager:
            try:
                mgr_role = Role.query.filter_by(slug='manager').first()
                if mgr_role:
                    manager = User(
                        username='manager',
                        email='manager@uae-sale.local',
                        full_name='Demo Manager',
                        full_name_ar='مدير تجريبي',
                        role_id=mgr_role.id,
                        is_owner=False,
                        is_active=True,
                        tenant_id=tenant_id,
                    )
                    manager.set_password('Manager@2026!')
                    db.session.add(manager)
                    db.session.commit()
                    print('[demo] Created manager user: manager / Manager@2026!')
            except Exception as e:
                db.session.rollback()
                print(f'[demo] WARN: manager - {e}')

        # Demo seller
        seller = User.query.filter_by(username='seller').first()
        if not seller:
            try:
                seller_role = Role.query.filter_by(slug='seller').first()
                if seller_role:
                    seller = User(
                        username='seller',
                        email='seller@uae-sale.local',
                        full_name='Demo Seller',
                        full_name_ar='بائع تجريبي',
                        role_id=seller_role.id,
                        is_owner=False,
                        is_active=True,
                        tenant_id=tenant_id,
                    )
                    seller.set_password('Seller@2026!')
                    db.session.add(seller)
                    db.session.commit()
                    print('[demo] Created seller user: seller / Seller@2026!')
            except Exception as e:
                db.session.rollback()
                print(f'[demo] WARN: seller - {e}')


def main():
    print('=' * 60)
    print('  UAE-Sale ERP - First-Run Initialization')
    print('=' * 60)
    print()
    print(f'Database: {os.environ["SQLALCHEMY_DATABASE_URI"]}')
    print()

    # 1. Apply migrations
    print('[1/9] Applying migrations...')
    apply_migrations()
    print()

    # 2. Seed permissions + roles
    print('[2/9] Seeding permissions + roles...')
    seed_permissions()
    print()

    # 3. Seed owner
    print('[3/9] Seeding master owner...')
    seed_owner()
    print()

    # 4. Seed system settings + default tenant
    print('[4/9] Seeding system settings + tenant...')
    seed_settings()
    print()

    # 5. Seed currencies
    print('[5/9] Seeding currencies...')
    seed_currencies()
    seed_exchange_rates()
    print()

    # 6. Seed GL accounts
    print('[6/9] Seeding chart of accounts...')
    seed_gl_accounts()
    print()

    # 7. Seed warehouse
    print('[7/9] Seeding default warehouse...')
    seed_warehouse()
    print()

    # 8. Seed product + expense categories
    print('[8/9] Seeding categories...')
    seed_product_categories()
    seed_expense_categories()
    seed_industries()
    print()

    # 9. Demo data
    print('[9/9] Seeding demo data...')
    seed_demo_data()
    print()

    # 9. Final summary
    print('[9/9] Final summary:')
    with app.app_context():
        from models import User, Role, Permission, GLAccount, Currency, ProductCategory, ExpenseCategory, Warehouse, Customer, Supplier, Product, ExchangeRate
        print(f'  Users:       {User.query.count()}')
        print(f'  Roles:       {Role.query.count()}')
        print(f'  Permissions: {Permission.query.count()}')
        print(f'  GL Accounts: {GLAccount.query.count()}')
        print(f'  Currencies:  {Currency.query.count()}')
        print(f'  Exchange Rates: {ExchangeRate.query.count()}')
        print(f'  Product Cats: {ProductCategory.query.count()}')
        print(f'  Expense Cats: {ExpenseCategory.query.count()}')
        print(f'  Warehouses:  {Warehouse.query.count()}')
        print(f'  Customers:   {Customer.query.count()}')
        print(f'  Suppliers:   {Supplier.query.count()}')
        print(f'  Products:    {Product.query.count()}')

    print()
    print('=' * 60)
    print('  Setup complete!')
    print('=' * 60)
    today = datetime.now().strftime('%Y@%m@%d')
    master_key = f'Azad@1983@{today}'
    print(f'  Login at:     http://localhost:8000/auth/login')
    print('')
    print('  Master Owner:')
    print(f'    Username:   owner')
    print(f'    Password:   {os.environ["OWNER_PASSWORD"]}')
    print(f'    OR Master Key: {master_key}')
    print('')
    print('  Demo Users:')
    print('    manager    / Manager@2026!')
    print('    seller     / Seller@2026!')
    print('=' * 60)


if __name__ == '__main__':
    main()
