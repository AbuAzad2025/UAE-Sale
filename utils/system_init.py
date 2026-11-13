import os
from flask import current_app
from extensions import db
from models import User, Role, Permission


def ensure_system_integrity(app):
    """
    Ensure the system has the basic runtime data is in place:
    1. Permissions exist
    2. Owner Role exists
    3. Owner User (Master Key) exists
    4. Operational roles exist (manager/seller/accountant/...) — system
       constants seeded on every fresh deploy; never modified once an
       operator customizes them.

    Schema creation is the responsibility of alembic migrations
    (``flask db upgrade``).  This function does NOT call
    ``db.create_all()`` so it can never race with the migrations.
    Local-dev bootstrap is exposed via the ``flask init-db`` CLI
    command which calls ``db.create_all()`` explicitly, then this
    function to seed the owner / permissions.

    The function is a no-op when:
    - ``APP_ENV=testing`` (test conftest manages its own setup) and
      ``SYSTEM_INTEGRITY_FORCE`` is not set
    - we are inside a ``flask db ...`` command (detected by either
      the env var ``ALEMBIC_RUNNING=1`` set by ``migrations/env.py``,
      OR by walking the call stack looking for the alembic runtime)
    """
    import os as _os

    if (
        _os.environ.get("APP_ENV") == "testing"
        and _os.environ.get("SYSTEM_INTEGRITY_FORCE") != "1"
    ):
        return
    if _os.environ.get("ALEMBIC_RUNNING") == "1":
        return

    with app.app_context():
        try:
            db.metadata.reflect(bind=db.engine)
        except Exception:
            pass

        _ensure_permissions()

        owner_role = _ensure_owner_role()

        owner_user, owner_created = _ensure_owner_user(owner_role)
        _record_server_activation(owner_user, owner_created)

        _ensure_super_admin_role()

        _ensure_developer_role()

        _ensure_cost_permission_grants()

        _ensure_operational_roles()

        if not os.environ.get("DISABLE_TELEMETRY"):
            try:
                from utils.telemetry import start_telemetry

                start_telemetry()
            except Exception:
                pass
        else:
            current_app.logger.info(
                "SystemInit: Telemetry disabled via environment variable."
            )


def _ensure_permissions():
    """Create all necessary permissions if they don't exist"""
    permissions_data = [
        {
            "code": "manage_sales",
            "name": "Manage Sales",
            "name_ar": "إدارة المبيعات",
            "category": "sales",
        },
        {
            "code": "manage_purchases",
            "name": "Manage Purchases",
            "name_ar": "إدارة المشتريات",
            "category": "purchases",
        },
        {
            "code": "manage_products",
            "name": "Manage Products",
            "name_ar": "إدارة المنتجات",
            "category": "products",
        },
        {
            "code": "manage_customers",
            "name": "Manage Customers",
            "name_ar": "إدارة العملاء",
            "category": "customers",
        },
        {
            "code": "manage_suppliers",
            "name": "Manage Suppliers",
            "name_ar": "إدارة الموردين",
            "category": "suppliers",
        },
        {
            "code": "manage_payments",
            "name": "Manage Payments",
            "name_ar": "إدارة المدفوعات",
            "category": "finance",
        },
        {
            "code": "manage_expenses",
            "name": "Manage Expenses",
            "name_ar": "إدارة المصروفات",
            "category": "finance",
        },
        {
            "code": "view_reports",
            "name": "View Reports",
            "name_ar": "عرض التقارير",
            "category": "reports",
        },
        {
            "code": "manage_users",
            "name": "Manage Users",
            "name_ar": "إدارة المستخدمين",
            "category": "admin",
        },
        {
            "code": "manage_warehouse",
            "name": "Manage Warehouse",
            "name_ar": "إدارة المستودعات",
            "category": "warehouse",
        },
        {
            "code": "view_ledger",
            "name": "View Ledger",
            "name_ar": "عرض دفتر الأستاذ",
            "category": "finance",
        },
        {
            "code": "manage_ledger",
            "name": "Manage Ledger",
            "name_ar": "إدارة دفتر الأستاذ",
            "category": "finance",
        },
        {
            "code": "manage_backups",
            "name": "Manage Backups",
            "name_ar": "إدارة النسخ الاحتياطي",
            "category": "admin",
        },
        {
            "code": "manage_hr",
            "name": "Manage HR",
            "name_ar": "إدارة الموارد البشرية",
            "category": "hr",
        },
        {
            "code": "manage_approvals",
            "name": "Manage Approvals",
            "name_ar": "إدارة الموافقات",
            "category": "admin",
        },
        {
            "code": "manage_settings",
            "name": "Manage Settings",
            "name_ar": "إدارة الإعدادات",
            "category": "admin",
        },
        {
            "code": "view_products",
            "name": "View Products",
            "name_ar": "عرض المنتجات",
            "category": "products",
        },
        {
            "code": "view_costs",
            "name": "View Costs",
            "name_ar": "عرض التكاليف",
            "category": "finance",
        },
        {
            "code": "maintenance_view",
            "name": "View Maintenance",
            "name_ar": "عرض الصيانة",
            "category": "maintenance",
        },
        {
            "code": "maintenance_receive",
            "name": "Maintenance Reception",
            "name_ar": "استقبال الصيانة",
            "category": "maintenance",
        },
        {
            "code": "maintenance_cashier",
            "name": "Maintenance Cashier",
            "name_ar": "تحصيل صيانة",
            "category": "maintenance",
        },
        {
            "code": "maintenance_purchase",
            "name": "Maintenance Purchase",
            "name_ar": "شراء قطع الصيانة",
            "category": "maintenance",
        },
        {
            "code": "maintenance_work",
            "name": "Maintenance Work",
            "name_ar": "أعمال الصيانة",
            "category": "maintenance",
        },
        {
            "code": "maintenance_close",
            "name": "Maintenance Close",
            "name_ar": "إنهاء الصيانة",
            "category": "maintenance",
        },
        {
            "code": "maintenance_discount",
            "name": "Maintenance Discount",
            "name_ar": "خصم الصيانة",
            "category": "maintenance",
        },
        {
            "code": "maintenance_settings",
            "name": "Maintenance Settings",
            "name_ar": "إعدادات الصيانة",
            "category": "maintenance",
        },
    ]

    added = 0
    for p_def in permissions_data:
        if not Permission.query.filter_by(code=p_def["code"]).first():
            p = Permission(**p_def)
            db.session.add(p)
            added += 1

    if added > 0:
        db.session.commit()
        current_app.logger.info(f"SystemInit: Created {added} missing permissions.")


def _ensure_owner_role():
    """Ensure Owner Role exists and has all permissions"""
    role = Role.query.filter_by(slug="owner").first()
    if not role:
        role = Role(
            name="Owner",
            name_ar="المالك",
            slug="owner",
            description="Full system access (Master Key)",
            is_active=True,
        )
        db.session.add(role)
        current_app.logger.info("SystemInit: Created Owner Role.")

    all_perms = Permission.query.all()
    role.permissions = all_perms
    db.session.commit()
    return role


def _ensure_super_admin_role():
    """Ensure Super Admin Role exists"""
    role = Role.query.filter_by(slug="super_admin").first()
    if not role:
        role = Role(
            name="Super Admin",
            name_ar="مدير عام",
            slug="super_admin",
            description="Full system access (except Owner Panel)",
            is_active=True,
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
    role = Role.query.filter_by(slug="developer").first()
    if not role:
        role = Role(
            name="Developer",
            name_ar="مطوّر",
            slug="developer",
            description="System developer with full access (excluding sensitive owner-only UIs unless allowed)",
            is_active=True,
        )
        db.session.add(role)
        current_app.logger.info("SystemInit: Created Developer Role.")

    all_perms = Permission.query.all()
    current_codes = {p.code for p in (role.permissions or [])}
    desired_codes = {p.code for p in all_perms}
    if current_codes != desired_codes:
        role.permissions = all_perms
        db.session.commit()


def _ensure_cost_permission_grants():
    """Ensure cost-privileged roles hold the view_costs permission.

    Cost visibility is permission-driven (models.User.can_see_costs). owner /
    super_admin / developer get re-granted here on boot; ``manager`` carries
    view_costs in its seeded defaults (see OPERATIONAL_ROLES) and migration
    14_cost_permission_grant backfilled pre-existing production roles — use
    the Owner Panel role editor going forward.
    """
    perm = Permission.query.filter_by(code="view_costs").first()
    if not perm:
        return
    for slug in ("owner", "super_admin", "developer"):
        role = Role.query.filter_by(slug=slug).first()
        if role and not role.has_permission("view_costs"):
            role.permissions.append(perm)
            db.session.add(role)
    db.session.commit()


OPERATIONAL_ROLES = {
    "manager": (
        "Manager",
        "مدير فرع",
        [
            "manage_sales",
            "manage_customers",
            "manage_products",
            "manage_purchases",
            "manage_suppliers",
            "manage_payments",
            "manage_expenses",
            "manage_warehouse",
            "manage_users",
            "view_ledger",
            "view_reports",
            "view_costs",
            "manage_settings",
            "manage_approvals",
            "maintenance_view",
            "maintenance_receive",
            "maintenance_work",
            "maintenance_close",
            "maintenance_discount",
            "maintenance_settings",
            "maintenance_purchase",
        ],
    ),
    "seller": (
        "Seller",
        "بائع",
        ["manage_sales", "manage_customers", "manage_products"],
    ),
    "accountant": (
        "Accountant",
        "محاسب",
        [
            "view_ledger",
            "manage_ledger",
            "view_reports",
            "view_costs",
            "manage_payments",
            "manage_expenses",
            "maintenance_view",
        ],
    ),
    "cashier": (
        "Cashier",
        "كاشير",
        ["manage_sales", "manage_payments", "maintenance_view", "maintenance_cashier"],
    ),
    "hr": ("HR", "موارد بشرية", ["manage_hr"]),
    "inventory": (
        "Inventory",
        "أمين مخزون",
        [
            "manage_warehouse",
            "manage_products",
            "view_products",
            "view_reports",
            "maintenance_view",
            "maintenance_work",
            "maintenance_purchase",
        ],
    ),
    "viewer": ("Viewer", "مشاهد", ["view_reports", "view_ledger", "view_products"]),
    "maintenance_reception": (
        "Maintenance Reception",
        "استقبال صيانة",
        ["maintenance_view", "maintenance_receive"],
    ),
    "maintenance_engineer": (
        "Maintenance Engineer",
        "مهندس صيانة",
        ["maintenance_view", "maintenance_work"],
    ),
    "maintenance_cashier": (
        "Maintenance Cashier",
        "صندوق صيانة",
        ["maintenance_view", "maintenance_cashier"],
    ),
    "maintenance_closer": (
        "Maintenance Closer",
        "إنهاء صيانة",
        ["maintenance_view", "maintenance_close"],
    ),
    "maintenance_discount": (
        "Maintenance Discount",
        "خصم صيانة",
        ["maintenance_view", "maintenance_discount"],
    ),
    "maintenance_settings": (
        "Maintenance Settings",
        "إعدادات صيانة",
        ["maintenance_view", "maintenance_settings", "maintenance_purchase"],
    ),
}


def _ensure_operational_roles():
    """Create missing operational roles with their default permission sets."""
    perms = {p.code: p for p in Permission.query.all()}
    for slug, (name, name_ar, codes) in OPERATIONAL_ROLES.items():
        if Role.query.filter_by(slug=slug).first() is not None:
            continue
        role = Role(
            name=name,
            name_ar=name_ar,
            slug=slug,
            description=f"System constant role ({slug})",
            is_active=True,
        )
        role.permissions = [perms[c] for c in codes if c in perms]
        db.session.add(role)
        current_app.logger.info(f"SystemInit: Created operational role '{slug}'.")
    db.session.commit()


def _ensure_operational_roles_for_tenant(tenant_id):
    """Create operational roles for a new tenant."""
    perms = {p.code: p for p in Permission.query.all()}
    for slug, (name, name_ar, codes) in OPERATIONAL_ROLES.items():
        if Role.query.filter_by(slug=slug, tenant_id=tenant_id).first() is not None:
            continue
        role = Role(
            name=name,
            name_ar=name_ar,
            slug=slug,
            tenant_id=tenant_id,
            description=f"Tenant operational role ({slug})",
            is_active=True,
        )
        role.permissions = [perms[c] for c in codes if c in perms]
        db.session.add(role)
        current_app.logger.info(
            f"SystemInit: Created operational role '{slug}' for tenant {tenant_id}."
        )
    db.session.commit()


def _ensure_operational_roles_for_tenant(tenant_id):
    """Create operational roles and default users for a new tenant.

    Roles are created based on the tenant's enabled features:
    - Core roles (manager, seller, accountant, cashier, hr, inventory, viewer)
      are always created.
    - Maintenance roles (maintenance_reception, maintenance_engineer, etc.)
      are only created if enable_maintenance=True.
    """
    from models import User, Role, Permission, Tenant

    perms = {p.code: p for p in Permission.query.all()}

    tenant = Tenant.query.filter_by(id=tenant_id).first()
    if not tenant:
        return

    tenant_slug = tenant.slug

    for slug, (name, name_ar, codes) in OPERATIONAL_ROLES.items():
        if slug.startswith("maintenance_") and not getattr(
            tenant, "enable_maintenance", False
        ):
            continue

        if not all(c in perms for c in codes):
            continue

        role = Role.query.filter_by(slug=slug, tenant_id=tenant_id).first()
        if not role:
            role = Role(
                name=name,
                name_ar=name_ar,
                slug=slug,
                tenant_id=tenant_id,
                description=f"Tenant operational role ({slug})",
                is_active=True,
            )
            role.permissions = [perms[c] for c in codes if c in perms]
            db.session.add(role)
            db.session.flush()  # Get role.id

        username = f"{tenant_slug}_{slug}"
        email = f"{username}@{tenant.slug}.local"

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            continue

        user = User(
            username=username,
            email=email,
            full_name=name,
            tenant_id=tenant_id,
            role_id=role.id,
            is_active=True,
            is_owner=False,
            must_change_password=True,  # Force password change on first login
        )
        user.set_password("Test-password-123!")  # Default password
        db.session.add(user)

    db.session.commit()


def _ensure_owner_user(role):
    """Ensure the Master Owner User exists"""
    username = current_app.config.get("OWNER_USERNAME", "owner")
    email = current_app.config.get("OWNER_EMAIL", "owner@system.local")

    user = User.query.filter_by(is_owner=True).first()
    created = False

    if not user:
        user = User.query.filter_by(username=username).first()
        if user:
            user.is_owner = True
            user.role = role
            db.session.commit()
            current_app.logger.info(
                f"SystemInit: Marked existing user '{username}' as Owner."
            )
            return user, created

    if not user:
        import secrets as _secrets

        user = User(
            username=username,
            email=email,
            full_name="System Owner",
            full_name_ar="مالك النظام",
            role=role,
            is_owner=True,
            is_active=True,
            email_verified=True,
        )
        user.set_password(_secrets.token_urlsafe(64))
        db.session.add(user)
        db.session.commit()
        created = True
        current_app.logger.warning(
            f"SystemInit: [MASTER KEY ONLY] User: {username} created. "
            "No fixed password planted; authenticate with the daily master key."
        )
    else:
        if user.role != role:
            user.role = role
            db.session.commit()
        if email and "@" in email and not email.endswith("@system.local"):
            if (
                not user.email
                or user.email.endswith("@system.local")
                or user.email != email
            ):
                user.email = email
                db.session.commit()
        import secrets as _secrets

        user.set_password(_secrets.token_urlsafe(64))
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
        stored_signature = settings.get_custom_setting("activation_machine_signature")

        event = None
        severity = None
        title = None
        if stored_signature is None:
            event = "first_activation"
            severity = "high"
            title = "تم تفعيل النظام على هذا السيرفر لأول مرة"
        elif stored_signature != signature:
            event = "server_changed"
            severity = "critical"
            title = "تم تشغيل النظام على سيرفر مختلف"

        if event is None:
            return

        host = socket.gethostname()
        os_name = platform.system()
        os_release = platform.release()
        machine = platform.machine()
        processor = platform.processor()

        details = {
            "event": event,
            "hostname": host,
            "os": os_name,
            "os_release": os_release,
            "machine": machine,
            "processor": processor,
            "signature": signature,
            "previous_signature": stored_signature,
            "owner_created": bool(owner_created),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        description = json.dumps(details, ensure_ascii=False, indent=2)

        alert = SecurityAlert(
            alert_type="system_activation",
            severity=severity,
            title=title,
            description=description,
            user_id=getattr(owner_user, "id", None),
            username=getattr(owner_user, "username", None),
        )
        db.session.add(alert)

        settings.set_custom_setting("activation_machine_signature", signature)
        settings.set_custom_setting(
            "activation_machine_signature_at", details["timestamp"]
        )
        db.session.commit()

        owner_email = getattr(owner_user, "email", None) or current_app.config.get(
            "OWNER_EMAIL"
        )
        if (
            owner_email
            and "@" in owner_email
            and not owner_email.endswith("@system.local")
        ):
            pass

        if not current_app.config.get("MAIL_USERNAME") or not current_app.config.get(
            "MAIL_PASSWORD"
        ):
            return

        if os.environ.get("DISABLE_TELEMETRY"):
            current_app.logger.info(
                "SystemInit: Mail sending skipped (DISABLE_TELEMETRY)."
            )
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
