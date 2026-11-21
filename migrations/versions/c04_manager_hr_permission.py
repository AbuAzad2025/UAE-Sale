"""Grant manage_hr to every existing manager role.

Revision ID: c04_manager_hr_permission
Revises: c03_payslip_tax

The manager is the tenant administrator: it must reach every tenant-level
module (including HR) and only be excluded from owner/platform screens.
New tenants get manage_hr from OPERATIONAL_ROLES; existing roles need this
one-time backfill.
"""
from alembic import op
import sqlalchemy as sa

revision = "c04_manager_hr_permission"
down_revision = "c03_payslip_tax"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    perm_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'manage_hr'")
    ).scalar()
    if perm_id is None:
        return
    role_ids = [
        r[0]
        for r in bind.execute(
            sa.text("SELECT id FROM roles WHERE slug = 'manager'")
        ).fetchall()
    ]
    for rid in role_ids:
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM role_permissions WHERE role_id = :r AND permission_id = :p"
            ),
            {"r": rid, "p": perm_id},
        ).first()
        if not exists:
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) VALUES (:r, :p)"
                ),
                {"r": rid, "p": perm_id},
            )


def downgrade():
    bind = op.get_bind()
    perm_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'manage_hr'")
    ).scalar()
    if perm_id is None:
        return
    role_ids = [
        r[0]
        for r in bind.execute(
            sa.text("SELECT id FROM roles WHERE slug = 'manager'")
        ).fetchall()
    ]
    for rid in role_ids:
        bind.execute(
            sa.text(
                "DELETE FROM role_permissions WHERE role_id = :r AND permission_id = :p"
            ),
            {"r": rid, "p": perm_id},
        )
