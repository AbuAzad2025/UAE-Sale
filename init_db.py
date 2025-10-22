"""
Database Initialization Script
===============================
Use this script to initialize the database with owner user.
Run: python init_db.py
"""

from app import create_app
from extensions import db
from models import User, Role, Permission
import os

def init_database():
    """Initialize database with tables and owner user"""
    
    app = create_app()
    
    with app.app_context():
        print('🔨 Creating database tables...')
        db.create_all()
        print('✅ Database tables created')
        
        # Create basic permissions
        print('🔑 Creating permissions...')
        permissions_data = [
            {'code': 'manage_sales', 'name': 'Manage Sales', 'name_ar': 'إدارة المبيعات'},
            {'code': 'manage_purchases', 'name': 'Manage Purchases', 'name_ar': 'إدارة المشتريات'},
            {'code': 'manage_products', 'name': 'Manage Products', 'name_ar': 'إدارة المنتجات'},
            {'code': 'manage_customers', 'name': 'Manage Customers', 'name_ar': 'إدارة العملاء'},
            {'code': 'manage_suppliers', 'name': 'Manage Suppliers', 'name_ar': 'إدارة الموردين'},
            {'code': 'manage_payments', 'name': 'Manage Payments', 'name_ar': 'إدارة المدفوعات'},
            {'code': 'manage_expenses', 'name': 'Manage Expenses', 'name_ar': 'إدارة المصروفات'},
            {'code': 'view_reports', 'name': 'View Reports', 'name_ar': 'عرض التقارير'},
            {'code': 'manage_users', 'name': 'Manage Users', 'name_ar': 'إدارة المستخدمين'},
        ]
        
        permissions = []
        for perm_data in permissions_data:
            perm = Permission(**perm_data)
            db.session.add(perm)
            permissions.append(perm)
        
        db.session.flush()
        print(f'✅ Created {len(permissions)} permissions')
        
        # Create owner role
        print('👑 Creating owner role...')
        owner_role = Role(
            name='Owner',
            name_ar='المالك',
            slug='owner',
            description='Full system access',
            permissions=permissions
        )
        db.session.add(owner_role)
        db.session.flush()
        print('✅ Owner role created')
        
        # Create owner user
        print('👤 Creating owner user...')
        owner_password = os.getenv('OWNER_PASSWORD', 'REDACTED-PASSWORD')
        
        owner = User(
            username='owner',
            email='owner@azadsystems.com',
            role_id=owner_role.id,
            is_owner=True,
            is_active=True,
            can_see_costs=True
        )
        owner.set_password(owner_password)
        
        db.session.add(owner)
        db.session.commit()
        
        print('✅ Owner user created')
        print('')
        print('═══════════════════════════════════════')
        print('✅ Database initialized successfully!')
        print('═══════════════════════════════════════')
        print('')
        print('🔐 Login credentials:')
        print(f'   Username: owner')
        print(f'   Password: {owner_password}')
        print('')
        print('⚠️  IMPORTANT: Change the password after first login!')
        print('')

if __name__ == '__main__':
    init_database()
