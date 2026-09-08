"""Grant view_costs to cost-privileged roles (permission-driven cost visibility).

can_see_costs() was previously a hardcoded role-slug check (owner /
super_admin / manager). It now consults the ``view_costs`` permission, so
existing manager (and developer) roles must be backfilled with the grant —
otherwise operators' managers would lose cost visibility on upgrade.
super_admin/owner/developer are (re-)granted by system_init on boot too, but
the migration makes the data contract explicit and runs before the app.

Idempotent: skips roles that already hold the permission and creates the
permission row itself if missing (mirrors system_init._ensure_permissions).

Revision ID: 14_cost_permission_grant
Revises: 13_add_gl_line_tenant
Create Date: 2026-09-08
"""
from alembic import op
import sqlalchemy as sa


revision = '14_cost_permission_grant'
down_revision = '13_add_gl_line_tenant'
branch_labels = None
depends_on = None

# Roles that must keep cost visibility under the permission-driven model.
# owner bypasses the permission check in code, but is granted for consistency.
COST_PRIVILEGED_ROLE_SLUGS = ('owner', 'super_admin', 'manager', 'developer')


def _tables_exist(bind):
    inspector = sa.inspect(bind)
    names = set(inspector.get_table_names())
    return {'roles', 'permissions', 'role_permissions'} <= names


def upgrade():
    bind = op.get_bind()
    if not _tables_exist(bind):
        return  # Fresh install: system_init seeds everything on boot.

    roles = sa.table('roles', sa.column('id', sa.Integer),
                     sa.column('slug', sa.String))
    permissions = sa.table('permissions', sa.column('id', sa.Integer),
                           sa.column('code', sa.String))
    role_permissions = sa.table(
        'role_permissions', sa.column('role_id', sa.Integer),
        sa.column('permission_id', sa.Integer),
    )

    # Ensure the permission row exists (fresh DBs get it from system_init,
    # but a DB upgraded before 13 may predate the view_costs seed).
    perm = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.code == 'view_costs')
    ).scalar()
    if perm is None:
        perm = bind.execute(
            permissions.insert().values(
                code='view_costs', name='View Costs',
                name_ar='عرض التكاليف', category='finance',
            )
        ).inserted_primary_key[0]

    for slug in COST_PRIVILEGED_ROLE_SLUGS:
        role_id = bind.execute(
            sa.select(roles.c.id).where(roles.c.slug == slug)
        ).scalar()
        if role_id is None:
            continue
        already = bind.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id == perm,
            )
        ).scalar()
        if already is None:
            bind.execute(role_permissions.insert().values(
                role_id=role_id, permission_id=perm))


def downgrade():
    # Data-only migration: revoking view_costs from operator-created roles is
    # a business decision, so downgrade is a no-op (harmless to keep grants).
    pass
