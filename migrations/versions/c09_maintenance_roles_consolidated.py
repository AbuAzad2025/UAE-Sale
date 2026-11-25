""" maintenance roles: exactly three, all with full maintenance permissions.

Revision ID: c09_maintenance_roles_consolidated
Revises: c08_hr_tax_daily_wage
Create Date: 2026-11-25
"""

from alembic import op
import sqlalchemy as sa

revision = "c09_maintenance_roles_consolidated"
down_revision = "c08_hr_tax_daily_wage"
branch_labels = None
depends_on = None

MAINTENANCE_CODES = (
    "maintenance_view",
    "maintenance_receive",
    "maintenance_work",
    "maintenance_cashier",
    "maintenance_close",
    "maintenance_discount",
    "maintenance_settings",
    "maintenance_purchase",
)

ACTIVE = {
    "maintenance_reception": ("Maintenance Reception", "استقبال صيانة"),
    "maintenance_engineer": ("Maintenance Engineer", "مهندس صيانة"),
    "maintenance_cashier": ("Maintenance Cashier", "محاسب صيانة"),
}
LEGACY = ("maintenance_closer", "maintenance_discount", "maintenance_settings")


def upgrade():
    conn = op.get_bind()
    perm_ids = {
        code: pid
        for code, pid in conn.execute(
            sa.text("select code, id from permissions")
        ).fetchall()
    }
    roles = conn.execute(
        sa.text("select id, slug, name, name_ar from roles where slug like 'maintenance_%'")
    ).fetchall()

    # 1) Keep only the three operational maintenance roles.
    for rid, slug, _name, _name_ar in roles:
        if slug not in LEGACY:
            continue
        conn.execute(
            sa.text("delete from role_permissions where role_id=:r"), {"r": rid}
        )
        conn.execute(sa.text("delete from roles where id=:r"), {"r": rid})

    # 2) Normalise the three retained roles and give each one the complete
    #    maintenance permission set (the "cashier" role used to have only two).
    for rid, slug, _name, _name_ar in roles:
        if slug not in ACTIVE:
            continue
        en, ar = ACTIVE[slug]
        conn.execute(
            sa.text("update roles set name=:en, name_ar=:ar where id=:r"),
            {"en": en, "ar": ar, "r": rid},
        )
        conn.execute(
            sa.text("delete from role_permissions where role_id=:r"), {"r": rid}
        )
        for code in MAINTENANCE_CODES:
            pid = perm_ids.get(code)
            if pid is not None:
                conn.execute(
                    sa.text(
                        "insert into role_permissions (role_id, permission_id) "
                        "values (:r, :p)"
                    ),
                    {"r": rid, "p": pid},
                )


def downgrade():
    # Role consolidation is intentionally irreversible: re-adding deprecated
    # maintenance roles would restore the confusing labels this removes.
    pass
