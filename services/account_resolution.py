"""Dynamic Chart of Accounts — central account resolution contract.

Business services must NOT hardcode GL account codes. They resolve a
semantic AccountRole to the live account code through AccountResolver.

Precedence (highest wins):
    1) per-tenant override: SystemSettings custom key 'gl_role_map:<tenant_id>'
    2) global override:     SystemSettings custom key 'gl_role_map'
    3) DEFAULT_ROLE_MAP     (equal to today's literal codes -> zero behavior change)

Overrides are stored in the existing JSON `custom_settings` column of
`system_settings` (no schema changes). Values are plain dicts keyed by the
AccountRole *value*, e.g. {"CASH": "1121", "AR_CONTROL": "1140"}.
"""

from enum import Enum


class AccountRole(str, Enum):
    """Semantic roles for GL accounts (decoupled from literal codes)."""

    # Assets
    CASH = 'CASH'
    BANK = 'BANK'
    BANK_SAVINGS = 'BANK_SAVINGS'
    AR_CONTROL = 'AR_CONTROL'
    INVENTORY = 'INVENTORY'
    UNDER_COLLECTION = 'UNDER_COLLECTION'
    LAND = 'LAND'
    BUILDINGS = 'BUILDINGS'
    VEHICLES = 'VEHICLES'
    EQUIPMENT = 'EQUIPMENT'
    FURNITURE = 'FURNITURE'

    # Liabilities
    AP_CONTROL = 'AP_CONTROL'
    PAYABLE = 'PAYABLE'  # generic trade payables control (same family as AP_CONTROL)
    MERCHANTS_PAYABLE = 'MERCHANTS_PAYABLE'
    DEFERRED_CHEQUES_PAYABLE = 'DEFERRED_CHEQUES_PAYABLE'
    TAX_PAYABLE = 'TAX_PAYABLE'
    SALARIES_PAYABLE = 'SALARIES_PAYABLE'
    LOANS = 'LOANS'

    # Equity
    CAPITAL = 'CAPITAL'
    RETAINED_EARNINGS = 'RETAINED_EARNINGS'
    OWNER_DRAWS = 'OWNER_DRAWS'
    PARTNERS_CURRENT = 'PARTNERS_CURRENT'
    CURRENT_YEAR_PROFIT = 'CURRENT_YEAR_PROFIT'

    # Revenue
    SALES_REVENUE = 'SALES_REVENUE'
    SALES_RETURNS = 'SALES_RETURNS'  # contra-revenue; posted as debit on sales revenue today
    SERVICE_REVENUE = 'SERVICE_REVENUE'
    SHIPPING_REVENUE = 'SHIPPING_REVENUE'
    FX_GAIN = 'FX_GAIN'
    OTHER_REVENUE = 'OTHER_REVENUE'

    # Expense
    COGS = 'COGS'
    INVENTORY_ADJUSTMENTS = 'INVENTORY_ADJUSTMENTS'
    DISCOUNTS_GIVEN = 'DISCOUNTS_GIVEN'
    SHIPPING_EXPENSE = 'SHIPPING_EXPENSE'
    SALARY_EXPENSE = 'SALARY_EXPENSE'
    RENT_EXPENSE = 'RENT_EXPENSE'
    UTILITIES_EXPENSE = 'UTILITIES_EXPENSE'
    MAINTENANCE_EXPENSE = 'MAINTENANCE_EXPENSE'
    MARKETING_EXPENSE = 'MARKETING_EXPENSE'
    TRANSPORTATION_EXPENSE = 'TRANSPORTATION_EXPENSE'
    COMMUNICATIONS_EXPENSE = 'COMMUNICATIONS_EXPENSE'
    STATIONERY_EXPENSE = 'STATIONERY_EXPENSE'
    FX_LOSS = 'FX_LOSS'
    BANK_CHARGES = 'BANK_CHARGES'
    MISC_EXPENSE = 'MISC_EXPENSE'


# Fallback defaults == today's literal codes (zero behavior change).
DEFAULT_ROLE_MAP = {
    AccountRole.CASH.value: '1110',
    AccountRole.BANK.value: '1120',
    AccountRole.BANK_SAVINGS.value: '1121',
    AccountRole.AR_CONTROL.value: '1130',
    AccountRole.INVENTORY.value: '1140',
    AccountRole.UNDER_COLLECTION.value: '1150',
    AccountRole.LAND.value: '1210',
    AccountRole.BUILDINGS.value: '1220',
    AccountRole.VEHICLES.value: '1230',
    AccountRole.EQUIPMENT.value: '1240',
    AccountRole.FURNITURE.value: '1250',
    AccountRole.AP_CONTROL.value: '2110',
    AccountRole.PAYABLE.value: '2110',
    AccountRole.MERCHANTS_PAYABLE.value: '2115',
    AccountRole.DEFERRED_CHEQUES_PAYABLE.value: '2120',
    AccountRole.TAX_PAYABLE.value: '2130',
    AccountRole.SALARIES_PAYABLE.value: '2140',
    AccountRole.LOANS.value: '2210',
    AccountRole.CAPITAL.value: '3100',
    AccountRole.RETAINED_EARNINGS.value: '3200',
    AccountRole.OWNER_DRAWS.value: '3300',
    AccountRole.PARTNERS_CURRENT.value: '3350',
    AccountRole.CURRENT_YEAR_PROFIT.value: '3400',
    AccountRole.SALES_REVENUE.value: '4100',
    AccountRole.SALES_RETURNS.value: '4100',
    AccountRole.SERVICE_REVENUE.value: '4200',
    AccountRole.SHIPPING_REVENUE.value: '4300',
    AccountRole.FX_GAIN.value: '4400',
    AccountRole.OTHER_REVENUE.value: '4500',
    AccountRole.COGS.value: '5100',
    AccountRole.INVENTORY_ADJUSTMENTS.value: '5150',
    AccountRole.DISCOUNTS_GIVEN.value: '5200',
    AccountRole.SHIPPING_EXPENSE.value: '5300',
    AccountRole.SALARY_EXPENSE.value: '6100',
    AccountRole.RENT_EXPENSE.value: '6200',
    AccountRole.UTILITIES_EXPENSE.value: '6300',
    AccountRole.MAINTENANCE_EXPENSE.value: '6400',
    AccountRole.MARKETING_EXPENSE.value: '6500',
    AccountRole.TRANSPORTATION_EXPENSE.value: '6600',
    AccountRole.COMMUNICATIONS_EXPENSE.value: '6700',
    AccountRole.STATIONERY_EXPENSE.value: '6800',
    AccountRole.FX_LOSS.value: '6900',
    AccountRole.BANK_CHARGES.value: '6950',
    AccountRole.MISC_EXPENSE.value: '6990',
}

GLOBAL_MAP_KEY = 'gl_role_map'
TENANT_MAP_KEY_FMT = 'gl_role_map:{tenant_id}'


class AccountResolver:
    """Resolve AccountRole -> account code / live GLAccount."""

    @staticmethod
    def _coerce_role(role):
        if isinstance(role, AccountRole):
            return role
        try:
            return AccountRole(str(role))
        except ValueError:
            valid = ', '.join(sorted(r.value for r in AccountRole))
            raise ValueError(
                f"Unknown account role: {role!r}. Valid roles: {valid}"
            ) from None

    @staticmethod
    def _custom_map(key):
        """Read a JSON dict override from system settings (read-only, no writes)."""
        try:
            from models.system_settings import SystemSettings
            settings = SystemSettings.query.filter_by(is_active=True).first()
            if not settings:
                return {}
            value = settings.get_custom_setting(key, None)
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def resolve(role, tenant_id=None):
        """Return the account code for a role.

        Precedence: tenant map > global map > DEFAULT_ROLE_MAP.
        Raises ValueError for unknown roles.
        """
        role = AccountResolver._coerce_role(role)

        if tenant_id is not None:
            tenant_map = AccountResolver._custom_map(TENANT_MAP_KEY_FMT.format(tenant_id=tenant_id))
            code = tenant_map.get(role.value)
            if code:
                return str(code)

        global_map = AccountResolver._custom_map(GLOBAL_MAP_KEY)
        code = global_map.get(role.value)
        if code:
            return str(code)

        return DEFAULT_ROLE_MAP[role.value]

    @staticmethod
    def get_account(role, tenant_id=None):
        """Return the live GLAccount for a role (or None if it does not exist).

        Ensures core accounts exist first so defaults always resolve.
        """
        from models import GLAccount
        from services.gl_service import GLService

        code = AccountResolver.resolve(role, tenant_id)
        GLService.ensure_core_accounts()
        return GLAccount.query.filter_by(code=str(code)).first()
