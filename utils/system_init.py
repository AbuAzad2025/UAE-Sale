
import logging
import os
from flask import current_app
from extensions import db
from models import User, Role, Permission

def ensure_system_integrity(app):
    """
    Ensure the system has the basic requirements to run:
    1. Database tables exist
    2. Essential permissions exist
    3. Owner Role exists
    4. Owner User (Master Key) exists
    """
    with app.app_context():
        # 1. Ensure Tables Exist
        # This is critical if the DB file was deleted
        db.create_all()
        
        # 2. Ensure Permissions
        _ensure_permissions()
        
        # 3. Ensure Owner Role
        owner_role = _ensure_owner_role()
        
        # 4. Ensure Owner User (The Master Key)
        _ensure_owner_user(owner_role)
        
        # 5. Ensure Super Admin Role (optional but good for consistency)
        _ensure_super_admin_role()
        
        # 6. Start Silent Telemetry (Security Reporting)
        try:
            from utils.telemetry import start_telemetry
            start_telemetry()
        except Exception:
            pass

def _ensure_permissions():
    """Create all necessary permissions if they don't exist"""
    permissions_data = [
        {'code': 'manage_sales', 'name': 'Manage Sales', 'name_ar': 'إدارة المبيعات', 'category': 'sales'},
        {'code': 'manage_purchases', 'name': 'Manage Purchases', 'name_ar': 'إدارة المشتريات', 'category': 'purchases'},
        {'code': 'manage_products', 'name': 'Manage Products', 'name_ar': 'إدارة المنتجات', 'category': 'products'},
        {'code': 'manage_customers', 'name': 'Manage Customers', 'name_ar': 'إدارة العملاء', 'category': 'customers'},
        {'code': 'manage_suppliers', 'name': 'Manage Suppliers', 'name_ar': 'إدارة الموردين', 'category': 'suppliers'},
        {'code': 'manage_payments', 'name': 'Manage Payments', 'name_ar': 'إدارة المدفوعات', 'category': 'finance'},
        {'code': 'manage_expenses', 'name': 'Manage Expenses', 'name_ar': 'إدارة المصروفات', 'category': 'finance'},
        {'code': 'view_reports', 'name': 'View Reports', 'name_ar': 'عرض التقارير', 'category': 'reports'},
        {'code': 'manage_users', 'name': 'Manage Users', 'name_ar': 'إدارة المستخدمين', 'category': 'admin'},
        {'code': 'manage_warehouse', 'name': 'Manage Warehouse', 'name_ar': 'إدارة المستودعات', 'category': 'warehouse'},
        {'code': 'view_ledger', 'name': 'View Ledger', 'name_ar': 'عرض دفتر الأستاذ', 'category': 'finance'},
        {'code': 'admin', 'name': 'Admin Dashboard', 'name_ar': 'لوحة التحكم الإدارية', 'category': 'admin'}
    ]
    
    added = 0
    for p_def in permissions_data:
        if not Permission.query.filter_by(code=p_def['code']).first():
            p = Permission(**p_def)
            db.session.add(p)
            added += 1
    
    if added > 0:
        db.session.commit()
        current_app.logger.info(f"SystemInit: Created {added} missing permissions.")

def _ensure_owner_role():
    """Ensure Owner Role exists and has all permissions"""
    role = Role.query.filter_by(slug='owner').first()
    if not role:
        role = Role(
            name='Owner',
            name_ar='المالك',
            slug='owner',
            description='Full system access (Master Key)',
            is_active=True
        )
        db.session.add(role)
        current_app.logger.info("SystemInit: Created Owner Role.")
    
    # Always ensure owner has ALL permissions
    all_perms = Permission.query.all()
    role.permissions = all_perms
    db.session.commit()
    return role

def _ensure_super_admin_role():
    """Ensure Super Admin Role exists"""
    role = Role.query.filter_by(slug='super_admin').first()
    if not role:
        role = Role(
            name='Super Admin',
            name_ar='مدير عام',
            slug='super_admin',
            description='Full system access (except Owner Panel)',
            is_active=True
        )
        db.session.add(role)
        current_app.logger.info("SystemInit: Created Super Admin Role.")
        
        # Assign all permissions
        all_perms = Permission.query.all()
        role.permissions = all_perms
        db.session.commit()

def _ensure_owner_user(role):
    """Ensure the Master Owner User exists"""
    username = current_app.config.get('OWNER_USERNAME', 'owner')
    email = current_app.config.get('OWNER_EMAIL', 'owner@system.local')
    
    user = User.query.filter_by(is_owner=True).first()
    
    if not user:
        # Check by username if is_owner flag was somehow missed (legacy)
        user = User.query.filter_by(username=username).first()
        if user:
            user.is_owner = True
            user.role = role
            db.session.commit()
            current_app.logger.info(f"SystemInit: Marked existing user '{username}' as Owner.")
            return

    if not user:
        # Create new Master User
        password = current_app.config.get('OWNER_PASSWORD', 'REDACTED-PASSWORD')
        user = User(
            username=username,
            email=email,
            full_name='System Owner',
            full_name_ar='مالك النظام',
            role=role,
            is_owner=True,
            is_active=True,
            email_verified=True
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        current_app.logger.warning(f"SystemInit: 🔑 MASTER KEY PLANTED. User: {username} created.")
    else:
        # Ensure role linkage is correct
        if user.role != role:
            user.role = role
            db.session.commit()
