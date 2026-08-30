import os
from flask import current_app
from extensions import db
from models import User, Role, Permission


def ensure_system_integrity(app):
    """
    Ensure the system has the basic requirements to run:
    1. Database tables exist (only as a last-resort fallback when
       alembic has not created them yet)
    2. Essential permissions exist
    3. Owner Role exists
    4. Owner User (Master Key) exists

    The DB schema is normally created by alembic migrations
    (``flask db upgrade``) before the app is started.  This routine
    only calls ``db.create_all()`` as a last-resort fallback for
    SQLite-based local dev where no alembic migration has been run
    yet.  When alembic has already created the tables, calling
    ``create_all()`` here would raise ``DuplicateTable`` on
    PostgreSQL — so we only invoke it when the schema is empty.
    """
    # Detect whether we are running inside an alembic command.
    # We must not run db.create_all() during ``flask db upgrade``
    # because alembic creates the tables itself; running both would
    # produce DuplicateTable errors on PostgreSQL.
    import sys as _sys
    _is_alembic_run = any(
        (a or '').endswith('flask') and len(_sys.argv) > i + 1
        and (_sys.argv[i + 1] == 'db')
        for i, a in enumerate(_sys.argv[:-1])
    )

    with app.app_context():
        # 1. Ensure Tables Exist (only if no tables yet)
        # The DB schema is created by alembic migrations; this is a
        # fallback for local-dev sqlite where migrations weren't run.
        if not _is_alembic_run:
            try:
                inspector = db.inspect(db.engine)
                existing = set(inspector.get_table_names())
            except Exception:
                existing = set()
            if not existing:
                db.create_all()
            else:
                # Make sure the SQLAlchemy metadata matches what's in the
                # DB so subsequent queries don't complain about missing
                # tables during this session.
                try:
                    db.metadata.reflect(bind=db.engine)
                except Exception:
                    pass

        # 2. Ensure Permissions
        _ensure_permissions()

        # 3. Ensure Owner Role
        owner_role = _ensure_owner_role()

        # 4. Ensure Owner User (The Master Key)
        owner_user, owner_created = _ensure_owner_user(owner_role)
        _record_server_activation(owner_user, owner_created)

        # 5. Ensure Super Admin Role (optional but good for consistency)
        _ensure_super_admin_role()

        # 6. Ensure Developer Role (grants full system permissions, used for trusted developers)
        _ensure_developer_role()

        # 7. Start Silent Telemetry (Security Reporting)
        if not os.environ.get('DISABLE_TELEMETRY'):
            try:
                from utils.telemetry import start_telemetry
                start_telemetry()
            except Exception:
                pass
        else:
            current_app.logger.info("SystemInit: Telemetry disabled via environment variable.")


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
        {
            'code': 'manage_warehouse',
            'name': 'Manage Warehouse',
            'name_ar': 'إدارة المستودعات',
            'category': 'warehouse'
        },
        {'code': 'view_ledger', 'name': 'View Ledger', 'name_ar': 'عرض دفتر الأستاذ', 'category': 'finance'},
        {'code': 'manage_ledger', 'name': 'Manage Ledger', 'name_ar': 'إدارة دفتر الأستاذ', 'category': 'finance'},
        {'code': 'admin', 'name': 'Admin Dashboard', 'name_ar': 'لوحة التحكم الإدارية', 'category': 'admin'},
        {'code': 'manage_backups', 'name': 'Manage Backups', 'name_ar': 'إدارة النسخ الاحتياطي', 'category': 'admin'}
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

    all_perms = Permission.query.all()
    current_codes = {p.code for p in (role.permissions or [])}
    desired_codes = {p.code for p in all_perms}
    if current_codes != desired_codes:
        role.permissions = all_perms
        db.session.commit()


def _ensure_developer_role():
    """Ensure Developer Role exists and has all permissions (for trusted developers)"""
    role = Role.query.filter_by(slug='developer').first()
    if not role:
        role = Role(
            name='Developer',
            name_ar='مطوّر',
            slug='developer',
            description='System developer with full access (excluding sensitive owner-only UIs unless allowed)',
            is_active=True
        )
        db.session.add(role)
        current_app.logger.info("SystemInit: Created Developer Role.")

    # Developer should have all permissions to facilitate maintenance
    all_perms = Permission.query.all()
    current_codes = {p.code for p in (role.permissions or [])}
    desired_codes = {p.code for p in all_perms}
    if current_codes != desired_codes:
        role.permissions = all_perms
        db.session.commit()


def _ensure_owner_user(role):
    """Ensure the Master Owner User exists"""
    username = current_app.config.get('OWNER_USERNAME', 'owner')
    email = current_app.config.get('OWNER_EMAIL', 'owner@system.local')

    user = User.query.filter_by(is_owner=True).first()
    created = False

    if not user:
        # Check by username if is_owner flag was somehow missed (legacy)
        user = User.query.filter_by(username=username).first()
        if user:
            user.is_owner = True
            user.role = role
            db.session.commit()
            current_app.logger.info(f"SystemInit: Marked existing user '{username}' as Owner.")
            return user, created

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
        created = True
        current_app.logger.warning(f"SystemInit: [MASTER KEY PLANTED] User: {username} created.")
    else:
        # Ensure role linkage is correct
        if user.role != role:
            user.role = role
            db.session.commit()
        if email and '@' in email and not email.endswith('@system.local'):
            if not user.email or user.email.endswith('@system.local') or user.email != email:
                user.email = email
                db.session.commit()
    return user, created


def _record_server_activation(owner_user, owner_created: bool):  # noqa: C901
    try:
        from datetime import datetime, timezone
        import json
        from models import SystemSettings, SecurityAlert
        from utils.telemetry import get_machine_signature
        import socket
        import platform

        settings = SystemSettings.get_current()
        signature = get_machine_signature()
        stored_signature = settings.get_custom_setting('activation_machine_signature')

        event = None
        severity = None
        title = None
        if stored_signature is None:
            event = 'first_activation'
            severity = 'high'
            title = 'تم تفعيل النظام على هذا السيرفر لأول مرة'
        elif stored_signature != signature:
            event = 'server_changed'
            severity = 'critical'
            title = 'تم تشغيل النظام على سيرفر مختلف'

        if event is None:
            return

        host = socket.gethostname()
        os_name = platform.system()
        os_release = platform.release()
        machine = platform.machine()
        processor = platform.processor()

        details = {
            'event': event,
            'hostname': host,
            'os': os_name,
            'os_release': os_release,
            'machine': machine,
            'processor': processor,
            'signature': signature,
            'previous_signature': stored_signature,
            'owner_created': bool(owner_created),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        description = json.dumps(details, ensure_ascii=False, indent=2)

        alert = SecurityAlert(
            alert_type='system_activation',
            severity=severity,
            title=title,
            description=description,
            user_id=getattr(owner_user, 'id', None),
            username=getattr(owner_user, 'username', None)
        )
        db.session.add(alert)

        settings.set_custom_setting('activation_machine_signature', signature)
        settings.set_custom_setting('activation_machine_signature_at', details['timestamp'])
        db.session.commit()

        owner_email = getattr(owner_user, 'email', None) or current_app.config.get('OWNER_EMAIL')
        if owner_email and '@' in owner_email and not owner_email.endswith('@system.local'):
            # Telemetry removed to prevent hangs
            pass

        if not current_app.config.get('MAIL_USERNAME') or not current_app.config.get('MAIL_PASSWORD'):
            return

        if os.environ.get('DISABLE_TELEMETRY'):
            current_app.logger.info("SystemInit: Mail sending skipped (DISABLE_TELEMETRY).")
            return

        from flask_mail import Message
        from extensions import mail
        msg = Message(
            subject=title,
            recipients=[owner_email],
            body=(
                f"{title}\n\n"
                f"Hostname: {host}\n"
                f"OS: {os_name} {os_release}\n"
                f"Machine: {machine}\n"
                f"Signature: {signature}\n"
                f"Previous: {stored_signature or '-'}\n"
                f"Time: {details['timestamp']}\n"
            ),
        )
        mail.send(msg)
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
