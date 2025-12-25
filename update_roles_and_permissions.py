
import logging
from app import create_app
from extensions import db
from models import Role, Permission, User

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def update_roles_and_permissions():
    app = create_app()
    with app.app_context():
        # 1. Define Permissions
        permissions_data = [
            {'code': 'manage_sales', 'name': 'Manage Sales', 'category': 'sales'},
            {'code': 'manage_purchases', 'name': 'Manage Purchases', 'category': 'purchases'},
            {'code': 'manage_products', 'name': 'Manage Products', 'category': 'inventory'},
            {'code': 'manage_customers', 'name': 'Manage Customers', 'category': 'crm'},
            {'code': 'manage_suppliers', 'name': 'Manage Suppliers', 'category': 'crm'},
            {'code': 'manage_payments', 'name': 'Manage Payments', 'category': 'finance'},
            {'code': 'manage_expenses', 'name': 'Manage Expenses', 'category': 'finance'},
            {'code': 'view_reports', 'name': 'View Reports', 'category': 'reports'},
            {'code': 'manage_users', 'name': 'Manage Users', 'category': 'admin'},
            {'code': 'manage_warehouse', 'name': 'Manage Warehouse', 'category': 'inventory'},
            {'code': 'view_ledger', 'name': 'View Ledger', 'category': 'finance'},
            {'code': 'admin', 'name': 'Admin Dashboard', 'category': 'admin'},
            {'code': 'view_cost_price', 'name': 'View Cost Price', 'category': 'finance'},
            {'code': 'manage_settings', 'name': 'Manage Settings', 'category': 'admin'},
        ]

        logger.info("--- Updating Permissions ---")
        permissions_map = {}
        for p_data in permissions_data:
            perm = Permission.query.filter_by(code=p_data['code']).first()
            if not perm:
                perm = Permission(
                    code=p_data['code'],
                    name=p_data['name'],
                    category=p_data['category']
                )
                db.session.add(perm)
                logger.info(f"Created permission: {p_data['code']}")
            else:
                perm.name = p_data['name']
                perm.category = p_data['category']
            
            permissions_map[p_data['code']] = perm
        
        db.session.commit()

        # 2. Define Roles and their Permissions
        roles_data = [
            {
                'name': 'Owner',
                'slug': 'owner',
                'description': 'Full system access (Master Key)',
                'permissions': list(permissions_map.keys()) # All permissions
            },
            {
                'name': 'Super Admin',
                'slug': 'super_admin',
                'description': 'Full system access (except Owner Panel)',
                'permissions': [p for p in permissions_map.keys()] # Almost all
            },
            {
                'name': 'Manager',
                'slug': 'manager',
                'description': 'Store manager access',
                'permissions': [
                    'manage_sales', 'manage_purchases', 'manage_products', 
                    'manage_customers', 'manage_suppliers', 'manage_payments', 
                    'manage_expenses', 'view_reports', 'manage_warehouse', 'view_cost_price'
                ]
            },
            {
                'name': 'Accountant',
                'slug': 'accountant',
                'description': 'Financial access',
                'permissions': [
                    'manage_payments', 'manage_expenses', 'view_reports', 
                    'view_cost_price', 'view_ledger', 'manage_sales', 'manage_purchases'
                ]
            },
            {
                'name': 'Seller',
                'slug': 'seller',
                'description': 'Sales access only',
                'permissions': [
                    'manage_sales', 'manage_customers', 'manage_payments'
                ]
            },
            {
                'name': 'Worker',
                'slug': 'worker',
                'description': 'Warehouse and Task access',
                'permissions': [
                    'manage_warehouse'
                ]
            }
        ]

        logger.info("--- Updating Roles ---")
        for r_data in roles_data:
            role = Role.query.filter_by(slug=r_data['slug']).first()
            if not role:
                role = Role(
                    name=r_data['name'],
                    slug=r_data['slug'],
                    description=r_data['description']
                )
                db.session.add(role)
                logger.info(f"Created role: {r_data['name']}")
            else:
                role.name = r_data['name']
                role.description = r_data['description']
            
            # Update permissions
            current_perms = []
            for p_code in r_data['permissions']:
                if p_code in permissions_map:
                    current_perms.append(permissions_map[p_code])
            
            role.permissions = current_perms
            db.session.add(role)
        
        db.session.commit()
        logger.info("✅ Roles and Permissions updated successfully.")

        # 3. Ensure Owner User Exists
        logger.info("--- Verifying Owner Account ---")
        owner_role = Role.query.filter_by(slug='owner').first()
        owner_user = User.query.filter_by(is_owner=True).first()
        
        if not owner_user:
            logger.warning("⚠️ Owner account missing! Creating one...")
            # This requires a username/password or some logic.
            # Assuming we can create a placeholder or use the dynamic auth logic.
            # For now, let's just log it. The system relies on dynamic key, so maybe we need a dummy user record?
            # Based on previous context, 'admin' might be the owner user.
            
            # Let's try to find 'admin' user and make them owner if no owner exists
            admin_user = User.query.filter_by(username='admin').first()
            if admin_user:
                admin_user.is_owner = True
                admin_user.role = owner_role
                db.session.commit()
                logger.info("✅ Promoted 'admin' user to Owner.")
            else:
                 # Create admin user
                new_owner = User(
                    username='admin',
                    email='admin@system.local',
                    role=owner_role,
                    is_owner=True,
                    is_active=True
                )
                # Password will be set to something random, as they login with dynamic key
                new_owner.set_password('ChangeMe123!') 
                db.session.add(new_owner)
                db.session.commit()
                logger.info("✅ Created 'admin' user as Owner.")
        else:
            logger.info(f"✅ Owner account exists: {owner_user.username}")
            if owner_user.role != owner_role:
                owner_user.role = owner_role
                db.session.commit()
                logger.info("✅ Fixed Owner role assignment.")

if __name__ == '__main__':
    update_roles_and_permissions()
