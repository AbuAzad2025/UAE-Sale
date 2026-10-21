"""
Balance Consistency Checker — Detects and repairs drifted denormalized balances.

Run periodically or on-demand to ensure Customer.balance matches
the calculated sum of confirmed sale balances.
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# Strict-match tolerance: deltas up to 0.01 (inclusive) are considered balanced;
# anything strictly greater is reported as a break (matches legacy drift rule).
TOLERANCE = Decimal('0.01')


def to_decimal(value):
    """Coerce any numeric boundary value to Decimal (never float arithmetic).

    Total-safe: None, garbage strings, and non-finite values (NaN/Infinity)
    coerce to Decimal('0') instead of raising, so reconciliation totals can
    never crash on dirty boundary data.
    """
    if value is None:
        return Decimal('0')
    try:
        d = Decimal(str(value).strip().replace(',', ''))
    except Exception:
        return Decimal('0')
    if not d.is_finite():
        return Decimal('0')
    return d


def get_control_account_balance(account_codes):
    """
    Signed net balance (base currency) for the given GL control account codes.

    Sign convention mirrors GLAccount.get_balance():
      asset/expense     -> Σ(debit − credit)
      liability/equity/revenue -> Σ(credit − debit)

    Reversing entries are included naturally: posted entries are immutable and
    corrections are posted as new offsetting lines, so the net already reflects them.
    Missing codes are logged (not fatal) so reconciliation can still run.
    """
    from sqlalchemy import func

    from extensions import db
    from models import GLAccount, GLJournalLine

    codes = [str(c) for c in (account_codes or []) if c]
    if not codes:
        return Decimal('0')

    accounts = GLAccount.query.filter(GLAccount.code.in_(codes)).all()
    found = {acc.code for acc in accounts}
    missing = [c for c in codes if c not in found]
    if missing:
        logger.warning(f'Control account(s) missing from CoA: {missing}')

    total = Decimal('0')
    for acc in accounts:
        raw_net = db.session.query(
            func.coalesce(func.sum(GLJournalLine.amount_base), 0)
        ).filter(GLJournalLine.account_id == acc.id).scalar()
        net = to_decimal(raw_net)
        total += net if acc.type in ('asset', 'expense') else -net

    return total


def check_customer_balance(customer_id=None):
    """
    Check if a customer's stored balance matches calculated balance.

    F1/F10/F12: الحساب يستعمل نفس المصدر الوحيد لرصيد العميل
    (models/customer.derive_customer_balance) — الذي يشمل الرصيد
    الافتتاحي والمرتجعات المعتمدة والاستردادات — فلم تعد هناك أربع صيغ
    مختلفة لنفس الرقم.

    Args:
        customer_id: Specific customer to check. If None, checks all.

    Returns:
        list of dicts with drift details
    """
    from models import Customer
    from models.customer import derive_customer_balance

    drifts = []

    query = Customer.query.filter_by(is_active=True)
    if customer_id:
        query = query.filter_by(id=customer_id)

    for customer in query.all():
        # المصدر الواحد: models/customer.derive_customer_balance
        calculated = derive_customer_balance(customer.id)

        stored = Decimal(str(customer.balance or 0))
        drift = abs(stored - calculated)

        if drift > Decimal('0.01'):
            drifts.append({
                'customer_id': customer.id,
                'customer_name': customer.name,
                'stored': float(stored),
                'calculated': float(calculated),
                'drift': float(drift),
            })

            logger.warning(
                f"Balance drift detected for customer {customer.id} "
                f"({customer.name}): stored={stored}, calculated={calculated}, "
                f"drift={drift}"
            )

    return drifts


def repair_customer_balance(customer_id=None):
    """
    Repair drifted customer balances by recalculating from sales.
    Uses distributed lock to prevent races with live transactions.

    Args:
        customer_id: Specific customer to repair. If None, repairs all drifts.

    Returns:
        int: number of records repaired
    """

    lock_name = f'balance_repair:{customer_id or "all"}'
    repaired = 0

    try:
        from utils.distributed_lock import repair_distributed_lock
        with repair_distributed_lock(lock_name, timeout=30, blocking_timeout=10):
            repaired = _do_repair(customer_id)
    except ImportError:
        repaired = _do_repair(customer_id)
    except Exception as e:
        logger.warning(f'Distributed lock failed for {lock_name}: {e} — proceeding without lock')
        repaired = _do_repair(customer_id)

    return repaired


def _do_repair(customer_id=None):
    """Inner repair logic (no locking — caller is responsible)."""
    from extensions import db
    from models import Customer

    repaired = 0
    drifts = check_customer_balance(customer_id)

    for drift_info in drifts:
        customer = db.session.get(Customer, drift_info['customer_id'])
        if customer:
            # F10: القيمة المحسوبة تشمل الرصيد الافتتاحي — فالإصلاح لا
            # يحذف الرصيد الافتتاحي (كان يُمحى سابقاً).
            customer.balance = Decimal(str(drift_info['calculated']))
            repaired += 1
            logger.info(
                f"Repaired balance for customer {customer.id} "
                f"({customer.name}): {drift_info['stored']} → {drift_info['calculated']}"
            )

    if repaired:
        db.session.commit()
        logger.info(f"Repaired {repaired} customer balance(s)")

    return repaired
