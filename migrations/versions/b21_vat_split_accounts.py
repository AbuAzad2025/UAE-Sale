"""Split input/output VAT into dedicated GL accounts (1141 / 2131).

TAX_PAYABLE (2130) historically carried both sides of VAT. Posting code
switches to VAT_INPUT / VAT_OUTPUT; the two new accounts are seeded by
`GLService.ensure_core_accounts()` (app boot) — not by this migration —
so a fresh round-trip stays self-contained.

Revision ID: b21_vat_split_accounts
Revises: b20_expense_tax
"""

from alembic import op

revision = "b21_vat_split_accounts"
down_revision = "b20_expense_tax"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schema-neutral revision: the account rows are seeded at app boot by
    # GLService.ensure_core_accounts() so that both fresh and existing
    # tenants get them exactly once.
    op.execute("SELECT 1")


def downgrade() -> None:
    pass
