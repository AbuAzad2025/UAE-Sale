"""
Sub-Ledger Reconciliation Service — مطابقة الذمم الفرعية مع الأستاذ العام
=========================================================================

Proves the STRICT MATCH RULE to the cent (0.01):

    Σ(sub-ledger recomputed from source documents)
        == GL control account(s) posted net
        == denormalized entity balance column(s)

  AR:  per active customer, Σ(confirmed+active sales: amount_base − paid_amount_base)
       vs GLAccount(AR_CONTROL, fallback '1130') debit-normal net
       vs Customer.balance column.

  AP:  per active supplier, Σ(confirmed purchases: amount_base − paid_amount|None→0)
       vs GLAccounts('2115' merchants + '2110' AP_CONTROL) credit-normal net
       vs Supplier derived column (total_purchases_aed − total_paid_aed).

Read-only audit service: detects and reports drift; it never mutates ledgers.
Conventions inherited from utils.balance_checker / aging_analysis_service:
active customers/suppliers only; confirmed sales; purchases by status
(Purchase has no is_active column); tolerance |delta| ≤ 0.01 inclusive.

Known structural break sources surfaced by design (see audit findings):
- merchant-type customer invoices are debited to '2115' (sale_service), so AR
  control '1130' alone will not equal the customer sub-ledger when merchants exist;
- unallocated receipts credit AR control without updating sale.paid_*;
- supplier stat listeners derive total_paid_aed from the Payment table while
  this sub-ledger derives paid from Purchase.paid_amount (dual sources of truth).
"""

import logging
from decimal import Decimal

from extensions import db
from utils.balance_checker import TOLERANCE, get_control_account_balance, to_decimal

logger = logging.getLogger(__name__)

# CENTRAL CONTRACT — dynamic CoA resolution (Agent 1's module consumed defensively).
# If services.account_resolution is not importable yet, literal codes are used as
# FALLBACK DEFAULTS so parallel rollout never blocks. Defaults equal today's codes.
try:
    from services.account_resolution import AccountResolver, AccountRole
except ImportError:  # pragma: no cover - resolver ships in Agent 1's turn
    AccountResolver = None  # type: ignore[assignment,misc]
    AccountRole = None  # type: ignore[assignment,misc]

DEFAULT_AR_CONTROL_CODES = ['1130']
DEFAULT_AP_CONTROL_CODES = ['2115', '2110']


def _resolve_role_codes(role_value, fallback_codes):
    """
    Resolve a role to its account code via the central resolver contract,
    keeping any additional fallback control codes that are still distinct.
    """
    if AccountResolver is not None and AccountRole is not None:
        try:
            code = AccountResolver.resolve(AccountRole(role_value))
            if code:
                return [code] + [c for c in fallback_codes if c != code]
        except Exception as exc:
            logger.warning(
                f'AccountResolver failed for role {role_value}: {exc} — using literal fallback'
            )
    return list(fallback_codes)


def _ap_control_codes():
    """AP scope per audit mandate: merchants payable ('2115') + AP control ('2110')."""
    codes = []
    for code in (
        _resolve_role_codes('MERCHANTS_PAYABLE', ['2115'])
        + _resolve_role_codes('AP_CONTROL', ['2110'])
    ):
        if code not in codes:
            codes.append(code)
    return codes


def _q2(value):
    """Quantize reported money to 0.01."""
    return Decimal(value).quantize(Decimal('0.01'))


class SubLedgerReconciliation:
    """Three-way sub-ledger ↔ GL control ↔ balance-column proof (AR & AP)."""

    # ------------------------------------------------------------------ AR

    @staticmethod
    def reconcile_receivables(tenant_id=None):
        """
        Reconcile customer receivables.

        Returns dict: {section:'AR', control_accounts, control_balance,
        subledger_sum, column_sum, breaks:[{entity, entity_id, expected,
        stored, delta}], balanced}
        """
        from models import Customer, Sale

        codes = _resolve_role_codes('AR_CONTROL', DEFAULT_AR_CONTROL_CODES)

        query = (
            db.session.query(Sale.customer_id, Sale.amount_base, Sale.paid_amount_base)
            .join(Customer, Customer.id == Sale.customer_id)
            .filter(
                Sale.status == 'confirmed',
                Sale.is_active.is_(True),
                Customer.is_active.is_(True),
                Sale.customer_id.isnot(None),
            )
        )
        if tenant_id is not None:
            query = query.filter(Sale.tenant_id == tenant_id)

        recomputed = {}
        for customer_id, amount, paid in query.all():
            balance = to_decimal(amount) - to_decimal(paid)
            recomputed[customer_id] = recomputed.get(customer_id, Decimal('0')) + balance

        # populate_existing: model listeners mutate balances via raw SQL outside
        # the identity map — force a fresh read so stored columns are current.
        customers = (
            Customer.query
            .filter_by(is_active=True)
            .order_by(Customer.id)
            .populate_existing()
            .all()
        )
        if tenant_id is not None:
            customers = [c for c in customers if c.tenant_id == tenant_id]

        subledger_sum = Decimal('0')
        column_sum = Decimal('0')
        breaks = []
        for customer in customers:
            expected = recomputed.get(customer.id, Decimal('0'))
            stored = to_decimal(customer.balance)
            subledger_sum += expected
            column_sum += stored

            delta = stored - expected
            if abs(delta) > TOLERANCE:
                breaks.append({
                    'entity': customer.name,
                    'entity_id': customer.id,
                    'expected': _q2(expected),
                    'stored': _q2(stored),
                    'delta': _q2(delta),
                })
                logger.warning(
                    f'AR break: customer#{customer.id} ({customer.name}) '
                    f'expected={expected} stored={stored} delta={delta}'
                )

        control_balance = get_control_account_balance(codes)

        balanced = (
            not breaks
            and abs(control_balance - subledger_sum) <= TOLERANCE
            and abs(column_sum - subledger_sum) <= TOLERANCE
        )

        return {
            'section': 'AR',
            'control_accounts': codes,
            'control_balance': _q2(control_balance),
            'subledger_sum': _q2(subledger_sum),
            'column_sum': _q2(column_sum),
            'breaks': breaks,
            'balanced': balanced,
        }

    # ------------------------------------------------------------------ AP

    @staticmethod
    def reconcile_payables(tenant_id=None):
        """
        Mirror reconciliation for suppliers/AP.

        Purchase.paid_amount was added recently: None is treated as 0.
        Supplier has no single balance column — its denormalized state is
        (total_purchases_aed − total_paid_aed), kept fresh by model events.
        """
        from models import Purchase, Supplier

        codes = _ap_control_codes()

        query = (
            db.session.query(Purchase.supplier_id, Purchase.amount_base, Purchase.paid_amount)
            .join(Supplier, Supplier.id == Purchase.supplier_id)
            .filter(
                Purchase.status == 'confirmed',
                Supplier.is_active.is_(True),
                Purchase.supplier_id.isnot(None),
            )
        )
        if tenant_id is not None:
            query = query.filter(Purchase.tenant_id == tenant_id)

        recomputed = {}
        for supplier_id, amount, paid in query.all():
            balance = to_decimal(amount) - to_decimal(paid)
            recomputed[supplier_id] = recomputed.get(supplier_id, Decimal('0')) + balance

        # populate_existing: see reconcile_receivables (raw-SQL listener writes).
        suppliers = (
            Supplier.query
            .filter_by(is_active=True)
            .order_by(Supplier.id)
            .populate_existing()
            .all()
        )
        if tenant_id is not None:
            suppliers = [s for s in suppliers if s.tenant_id == tenant_id]

        subledger_sum = Decimal('0')
        column_sum = Decimal('0')
        breaks = []
        for supplier in suppliers:
            expected = recomputed.get(supplier.id, Decimal('0'))
            stored = to_decimal(supplier.total_purchases_aed) - to_decimal(supplier.total_paid_aed)
            subledger_sum += expected
            column_sum += stored

            delta = stored - expected
            if abs(delta) > TOLERANCE:
                breaks.append({
                    'entity': supplier.name,
                    'entity_id': supplier.id,
                    'expected': _q2(expected),
                    'stored': _q2(stored),
                    'delta': _q2(delta),
                })
                logger.warning(
                    f'AP break: supplier#{supplier.id} ({supplier.name}) '
                    f'expected={expected} stored={stored} delta={delta}'
                )

        control_balance = get_control_account_balance(codes)

        balanced = (
            not breaks
            and abs(control_balance - subledger_sum) <= TOLERANCE
            and abs(column_sum - subledger_sum) <= TOLERANCE
        )

        return {
            'section': 'AP',
            'control_accounts': codes,
            'control_balance': _q2(control_balance),
            'subledger_sum': _q2(subledger_sum),
            'column_sum': _q2(column_sum),
            'breaks': breaks,
            'balanced': balanced,
        }

    # ----------------------------------------------------------------- All

    @staticmethod
    def reconcile_all(tenant_id=None):
        """Run both sections; returns [AR report, AP report]."""
        return [
            SubLedgerReconciliation.reconcile_receivables(tenant_id=tenant_id),
            SubLedgerReconciliation.reconcile_payables(tenant_id=tenant_id),
        ]
