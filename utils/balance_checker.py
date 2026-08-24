"""
Balance Consistency Checker — Detects and repairs drifted denormalized balances.

Run periodically or on-demand to ensure Customer.balance matches
the calculated sum of confirmed sale balances.
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def check_customer_balance(customer_id=None):
    """
    Check if a customer's stored balance matches calculated balance.

    Args:
        customer_id: Specific customer to check. If None, checks all.

    Returns:
        list of dicts with drift details
    """
    from models import Customer, Sale

    drifts = []

    query = Customer.query.filter_by(is_active=True)
    if customer_id:
        query = query.filter_by(id=customer_id)

    for customer in query.all():
        # Calculate balance from confirmed sales
        sales = Sale.query.filter_by(
            customer_id=customer.id,
            status='confirmed',
            is_active=True
        ).all()

        calculated = Decimal('0')
        for sale in sales:
            amount = Decimal(str(sale.amount_aed or 0))
            paid = Decimal(str(sale.paid_amount_aed or 0))
            calculated += (amount - paid)

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
