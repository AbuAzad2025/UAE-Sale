
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())

# Note: .env file should be present now, which config.py will load.
# We don't need to force env vars here if .env is set up correctly.

from app import create_app
from extensions import db
from models import Role, Permission

def update_roles():
    app = create_app()
    with app.app_context():
        print(f"🔄 Updating System Roles and Permissions using DB: {app.config['SQLALCHEMY_DATABASE_URI']}")

        
        # 0. Ensure additional permissions exist
        additional_perms = [
            {'code': 'manage_warehouse', 'name': 'Manage Warehouse', 'name_ar': 'إدارة المستودعات', 'category': 'warehouse'},
            {'code': 'view_ledger', 'name': 'View Ledger', 'name_ar': 'عرض دفتر الأستاذ', 'category': 'finance'},
            {'code': 'admin', 'name': 'Admin Dashboard', 'name_ar': 'لوحة التحكم الإدارية', 'category': 'admin'} 
        ]
        
        for p_def in additional_perms:
            if not Permission.query.filter_by(code=p_def['code']).first():
                p = Permission(**p_def)
                db.session.add(p)
                print(f"➕ Created Permission: {p_def['name']}")
        
        db.session.commit() # Commit new perms first

        # 1. Fetch all permissions map
        all_perms = {p.code: p for p in Permission.query.all()}
        
        # Helper to get permission objects list from codes
        def get_perms(codes):
            valid_codes = []
            for c in codes:
                if c in all_perms:
                    valid_codes.append(all_perms[c])
                else:
                    print(f"⚠️ Warning: Permission '{c}' not found in DB.")
            return valid_codes

        # Define Roles and their Permissions
        roles_definitions = [
            {
                'slug': 'super_admin',
                'name': 'Super Admin',
                'name_ar': 'مدير عام',
                'description': 'Full system access (except Owner Panel)',
                'permissions': list(all_perms.keys()) # All permissions
            },
            {
                'slug': 'manager',
                'name': 'Branch Manager',
                'name_ar': 'مدير فرع',
                'description': 'Manage Branch Operations',
                'permissions': [
                    'manage_sales', 'manage_purchases', 'manage_products', 
                    'manage_customers', 'manage_suppliers', 'manage_expenses', 
                    'view_reports', 'manage_warehouse', 'view_ledger'
                ]
            },
            {
                'slug': 'accountant',
                'name': 'Accountant',
                'name_ar': 'محاسب',
                'description': 'Financial Management',
                'permissions': [
                    'manage_payments', 'manage_expenses', 'view_reports',
                    'manage_customers', 'manage_suppliers', 'view_ledger'
                ]
            },
            {
                'slug': 'seller',
                'name': 'Seller',
                'name_ar': 'بائع',
                'description': 'Sales Operations',
                'permissions': [
                    'manage_sales', 'manage_customers', 'manage_products', 'manage_warehouse' # Maybe view stock?
                ]
            },
            {
                'slug': 'storekeeper',
                'name': 'Storekeeper',
                'name_ar': 'أمين مستودع',
                'description': 'Inventory Management',
                'permissions': [
                    'manage_products', 'manage_purchases', 'manage_suppliers', 'manage_warehouse'
                ]
            }
        ]

        created_count = 0
        updated_count = 0

        for role_def in roles_definitions:
            role = Role.query.filter_by(slug=role_def['slug']).first()
            
            if not role:
                # Create new role
                role = Role(
                    name=role_def['name'],
                    name_ar=role_def['name_ar'],
                    slug=role_def['slug'],
                    description=role_def['description']
                )
                db.session.add(role)
                created_count += 1
                print(f"➕ Created Role: {role_def['name']} ({role_def['slug']})")
            else:
                # Update existing role
                role.name = role_def['name']
                role.name_ar = role_def['name_ar']
                role.description = role_def['description']
                updated_count += 1
                print(f"🔄 Updated Role: {role_def['name']} ({role_def['slug']})")
            
            # Update Permissions
            current_perms = get_perms(role_def['permissions'])
            role.permissions = current_perms
            print(f"   Refreshed permissions: {len(current_perms)} assigned.")

        try:
            db.session.commit()
            print(f"\n✅ Success! Created {created_count} roles, Updated {updated_count} roles.")
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Error updating roles: {e}")

if __name__ == '__main__':
    update_roles()
