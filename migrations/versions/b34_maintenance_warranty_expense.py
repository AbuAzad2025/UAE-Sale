"""Add the warranty expense account used for warranty-covered maintenance work.

Warranty-covered work is expensed against 6401 (Warranty Expense) instead of
being recognised as maintenance revenue, per the operating policy recorded in
docs/maintenance_status.md.

Revision ID: b34_maintenance_warranty_expense
Revises: b33_maintenance_audit_guard
"""
from alembic import op
import sqlalchemy as sa


revision = 'b34_maintenance_warranty_expense'
down_revision = 'b33_maintenance_audit_guard'
branch_labels = None
depends_on = None


def _base_currency(bind):
    try:
        from services.currency_service import CurrencyService
        return CurrencyService.get_base_currency()
    except Exception:
        return 'AED'


def upgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM gl_accounts WHERE code = '6401'")).first():
        return
    parent_id = bind.execute(sa.text(
        "SELECT id FROM gl_accounts WHERE code = '6400'"
    )).scalar()
    bind.execute(sa.text(
        """
        INSERT INTO gl_accounts (code, name, name_ar, type, currency, is_active,
                                is_header, level, parent_id, is_system,
                                created_at, updated_at)
        VALUES ('6401', 'Warranty Expense', 'مصروف الضمان', 'expense', :currency,
                true, false, 2, :parent_id, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    ), {'currency': _base_currency(bind), 'parent_id': parent_id})


def downgrade():
    op.execute("DELETE FROM gl_accounts WHERE code = '6401'")
