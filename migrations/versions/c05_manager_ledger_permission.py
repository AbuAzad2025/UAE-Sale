"""Grant manage_ledger to every existing manager role.

Revision ID: c05_manager_ledger_permission
Revises: c04_manager_hr_permission

Completes the tenant-administrator permission set: the manager may administer
all tenant modules (ledger included). Owner/platform screens stay exclusive to
is_owner / is_super_admin via @admin_required and the owner blueprint gate.
"""
from alembic import op
import sqlalchemy as sa

revision = "c05_manager_ledger_permission"
down_revision = "c04_manager_hr_permission"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    perm_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'manage_ledger'")
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
        sa.text("SELECT id FROM permissions WHERE code = 'manage_ledger'")
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
