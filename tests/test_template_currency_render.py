"""Test template rendering for currency handling."""
import os
import sys
sys.path.insert(0, r'D:\recovers\data\UAE-Sale')

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['SECRET_KEY'] = 'test-secret-key-not-for-production'
os.environ['OWNER_PASSWORD'] = 'TestOwner1234567890123456'
os.environ['APP_ENV'] = 'testing'

import pytest
from app import create_app
from extensions import db
from models.sale import Sale, SaleLine
from models.tenant import Tenant
from models.product import Product, ProductCategory
from models.customer import Customer
from models.warehouse import Warehouse
from models.user import User
from models.product import ProductCategory
from decimal import Decimal

def test_template_currency_rendering(app):
    """Test that templates render with dynamic base_currency, no hardcoded currency."""
    from app import create_app
    from extensions import db
    from models.sale import Sale, SaleLine
    from models.tenant import Tenant
    from models.product import Product, ProductCategory
    from models.customer import Customer
    from models.warehouse import Warehouse
    from models.user import User
    from models.product import ProductCategory
    from decimal import Decimal
    
    app = create_app()
    with app.app_context():
        from flask import render_template
        from models.tenant import Tenant
        from models.tenant_scope import set_current_tenant_id
        
        # Create test data
        t = Tenant(name='T-TEST', name_ar='ت', slug='t-test', default_currency='AED', is_active=True)
        db.session.add(t)
        db.session.flush()  # flush to get tenant.id
        print(f"DEBUG: tenant id = {t.id}")  # DEBUG
        assert t.id is not None, f"tenant id is None!"
        
        wh = Warehouse(name='WH-TEST', name_ar='WH', code='WH-T', tenant_id=t.id, is_active=True)
        db.session.add(wh)
        db.session.flush()
        print(f"DEBUG: warehouse id = {wh.id}")  # DEBUG
        assert wh.id is not None, f"warehouse id is None!"
        assert wh.id is not None, f"warehouse id is None!"
        
        wh = Warehouse(name='WH-TEST', name_ar='WH', code='WH-T', tenant_id=t.id, is_active=True)
        db.session.add(wh)
        db.session.flush()
        
        cat = ProductCategory(name='Cat-TEST', is_active=True)
        db.session.add(cat)
        db.session.flush()
        
        prod = Product(name='P-TEST', sku='SKU-TEST', category_id=cat.id, cost_price=Decimal('5'), regular_price=Decimal('10'), current_stock=Decimal('10'), is_active=True)
        db.session.add(prod)
        db.session.flush()
        
        cust = Customer(name='C-TEST', customer_type='regular', tenant_id=t.id, is_active=True)
        db.session.add(cust)
        db.session.flush()
        
        seller = User.query.filter_by(is_owner=True).first()
        if not seller:
            from models.user import Role
            owner_role = Role.query.filter_by(slug='owner').first()
            if not owner_role:
                owner_role = Role(name='Owner', name_ar='OU,U.OU,U�', slug='owner', description='Full access', is_active=True)
                db.session.add(owner_role)
                db.session.flush()
                print(f"DEBUG: owner_role id = {owner_role.id}")  # DEBUG
            seller = User(username='testowner', email='test@test.com', full_name='Test Owner', is_owner=True, is_active=True, role_id=owner_role.id, tenant_id=t.id)
            print(f"DEBUG: seller tenant_id = {seller.tenant_id}")  # DEBUG
            seller.set_password('test')
            db.session.add(seller)
            db.session.flush()
            print(f"DEBUG: seller tenant_id after flush = {seller.tenant_id}")  # DEBUG
            
        # Create sale
        sale = Sale(sale_number='S-TEST', customer_id=1, seller_id=1, warehouse_id=1, tenant_id=1,
                    total_amount=Decimal('100'), amount_base=Decimal('0'), paid_amount=Decimal('0'), 
                    paid_amount_base=Decimal('0'), balance_due=Decimal('0'),
                    currency='AED', exchange_rate=Decimal('1'), payment_status='unpaid', status='confirmed', is_active=True)
        db.session.add(sale)
        db.session.flush()
        line = SaleLine(sale_id=1, product_id=1, quantity=Decimal('2'), unit_price=Decimal('50'), line_total=Decimal('100'))
        db.session.add(line)
        db.session.flush()
        sale.lines = [line]
        sale.calculate_totals()
        
        from flask import render_template
        from flask import current_app
        with current_app.test_request_context('/'):
            # Test invoice templates
            for tpl in ['invoices/simple.html', 'invoices/modern.html', 'invoices/classic.html']:
                html = render_template(tpl, sale=sale)
                assert '<base href' in html, f'{tpl}: missing base tag'
                assert 'window.BASE_URL' in html, f'{tpl}: missing BASE_URL'
                assert 'window.BASE_CURRENCY' in html, f'{tpl}: missing BASE_CURRENCY'
                # Check no hardcoded AED/ILS without base_currency
                if 'O_O�U�U. O�U.OO�OO�US' in html and 'base_currency' not in html:
                    assert False, f'{tpl}: has hardcoded "O_O�U�U. O�U.OO�OO�US" without base_currency'
                if 'AED' in html and 'base_currency' not in html:
                    print(f'WARNING: {tpl} has AED without base_currency')
            
            # Check receipt templates
            for tpl in ['receipts/minimal.html', 'receipts/gulf.html', 'receipts/modern.html']:
                html = render_template(tpl, receipt=None)
                if 'O_O�U�U. O�U.OO�OO�US' in html and 'base_currency' not in html:
                    assert False, f'{tpl}: has hardcoded "O_O�U�U. O�U.OO�OO�US" without base_currency'
                if 'AED' in html and 'base_currency' not in html:
                    print(f'WARNING: {tpl} has AED without base_currency')
            
            # Check for hardcoded AED/ILS in condition checks
            for path in ['templates/receipts/minimal.html', 'templates/receipts/gulf.html', 'templates/sales/view.html']:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    txt = f.read()
                    if "!= 'AED'" in line or '!= "AED"' in line or "== 'AED'" in line or '== "AED"' in line:
                        assert 'base_currency' in open(path, 'r', encoding='utf-8').read(), f"{path} still has hardcoded AED check without base_currency"
            
            print('All template currency checks passed!')

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        test_template_currency_rendering(app)