"""
Combinatorial scenario matrix for the six implemented domains.

6 domains x 8 roles x 7 states x 15 edges = 5040 scenarios.

Design constraints (from the brief):
  * Every scenario performs a REAL HTTP request against a REAL endpoint and
    asserts REAL amounts. Nothing is simulated or asserted with `assert True`.
  * A scenario whose role lacks the domain permission is still a real test: it
    asserts 403 AND that no GL entry, stock movement, cheque, sale or purchase
    was created. Denial without side-effect freedom is the actual contract.
  * The expected GL of every permitted scenario is derived from the service
    semantics that were read from the source, not guessed:
      - GLService.create_manual_entry raises unless total_debit == total_credit
      - sale_service posts AR/revenue in transaction ccy + COGS/inventory in base
      - routes/purchases.py posts inventory/AP (+ tax) in ONE entry
      - Cheque.receive_cheque posts 1150 against 1130
  * Numeric parameters vary deterministically with the scenario index so that
    the 250 scenarios in a domain assert 250 different amounts rather than
    repeating one assertion 250 times.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Tuple

from tests.e2e.harness import ACC

# --------------------------------------------------------------------------
# Dimensions
# --------------------------------------------------------------------------

DOMAINS = ['accounting', 'ar', 'ap', 'inventory', 'cheque', 'security',
           'payments', 'hr', 'approvals', 'shipments']

ROLES = ['owner', 'branch_manager', 'senior_accountant', 'pos_cashier',
         'warehouse_keeper', 'manager', 'accountant', 'viewer', 'hr']

STATES = ['happy_path', 'expired_invalid', 'insufficient_boundary',
          'partial_split', 'concurrent_repeat', 'validation_error',
          'cross_tenant_read']

EDGES = ['invalid_permission', 'foreign_currency', 'reversal',
         'rollback_no_partial_write', 'idempotency_replay',
         'negative_boundary', 'split_transaction', 'race_condition',
         'stale_session', 'cross_tenant',
         'insufficient_funds', 'time_based', 'duplicate_submission',
         'approval_pending', 'tax_boundary']

# The five edges and two states introduced by the expansion. They are handled by
# tests/e2e/test_matrix.py::_new_edge_state, which asserts real per-domain
# behaviour for each one instead of falling through to the happy path.
NEW_EDGE_STATES = frozenset({
    'insufficient_funds', 'time_based', 'duplicate_submission',
    'approval_pending', 'tax_boundary', 'validation_error',
    'cross_tenant_read',
})

# The permission each domain's write endpoint actually enforces.
DOMAIN_PERMISSION = {
    'accounting': 'manage_ledger',
    'ar': 'manage_sales',
    'ap': 'manage_purchases',
    'inventory': 'manage_products',
    'cheque': 'manage_payments',
    'payments': 'manage_payments',
    'hr': 'manage_hr',
    # routes/approvals.py splits its gates: the decision endpoints are
    # manage_approvals while /approvals/workflows/* is manage_settings.
    'approvals': 'manage_approvals',
    'shipments': 'manage_warehouse',
    'security': None,          # read/visibility domain, handled per-op
}

# Role -> permissions, mirroring tests/e2e/conftest.py::ROLE_PERMISSIONS.
ROLE_PERMISSIONS = {
    'owner': {
        'manage_ledger', 'manage_sales', 'manage_purchases', 'manage_products',
        'manage_payments', 'manage_customers', 'manage_warehouse',
        'view_ledger', 'view_reports', 'manage_approvals',
        'manage_hr',
    },
    'branch_manager': {
        'manage_sales', 'manage_purchases', 'manage_products', 'manage_payments',
        'manage_customers', 'manage_suppliers', 'view_reports', 'view_products',
    },
    'senior_accountant': {
        'manage_ledger', 'view_ledger', 'view_reports', 'manage_approvals',
    },
    'pos_cashier': {'manage_sales'},
    'warehouse_keeper': {'manage_warehouse', 'view_products'},
    # Mirrors tests/unit/test_erp_role_isolation.py. An earlier draft guessed
    # `accountant` held manage_approvals and did not hold manage_payments; the
    # real role is the opposite, which flipped the expected outcome for every
    # accountant x cheque / accountant x payments cell.
    'manager': {
        'manage_sales', 'manage_customers', 'manage_products', 'manage_purchases',
        'manage_payments', 'view_reports', 'manage_expenses', 'manage_warehouse',
        'view_costs',
    },
    'accountant': {
        'view_ledger', 'manage_ledger', 'manage_expenses', 'view_reports',
        'manage_payments',
    },
    'viewer': {'view_reports'},
    # utils/system_init.py:228 - the 'hr' role holds manage_hr and nothing else.
    'hr': {'manage_hr'},
}


def role_may_write(role: str, domain: str) -> bool:
    """Would this role pass the domain's permission gate?"""
    perm = DOMAIN_PERMISSION.get(domain)
    if perm is None:
        return role == 'owner' or role in ('branch_manager', 'senior_accountant')
    return perm in ROLE_PERMISSIONS[role]


@dataclass(frozen=True)
class Scenario:
    id: str
    domain: str
    role: str
    state: str
    edge: str
    index: int
    amount: Decimal
    quantity: Decimal
    currency: str
    rate: Decimal
    permitted: bool

    @property
    def tag(self) -> str:
        return f'{self.domain}/{self.state}/{self.edge}'


def _amount_for(index: int) -> Decimal:
    """Deterministic and distinct across the whole matrix.

    An earlier draft used `index % 37`, which collapsed 1500 scenarios onto 37
    distinct amounts — the same assertion repeated 40 times is not coverage.
    This strides by a coprime step so every scenario carries its own amount.
    """
    return Decimal(100 + index * 13)


def _quantity_for(index: int) -> Decimal:
    return Decimal(1 + (index * 7) % 23)


def build_matrix() -> List[Scenario]:
    """Enumerate the full 6 x 8 x 7 x 15 = 5040 matrix, deterministically."""
    scenarios: List[Scenario] = []
    index = 0
    for domain in DOMAINS:
        dcount = 0
        for role in ROLES:
            for state in STATES:
                for edge in EDGES:
                    index += 1
                    dcount += 1
                    currency = 'USD' if edge == 'foreign_currency' else 'ILS'
                    rate = Decimal('3.670000') if edge == 'foreign_currency' \
                        else Decimal('1.000000')
                    scenarios.append(Scenario(
                        id=f'E2E-{domain[:3].upper()}-{dcount:04d}',
                        domain=domain,
                        role=role,
                        state=state,
                        edge=edge,
                        index=index,
                        amount=_amount_for(index),
                        quantity=_quantity_for(index),
                        currency=currency,
                        rate=rate,
                        permitted=role_may_write(role, domain),
                    ))
    return scenarios


MATRIX: List[Scenario] = build_matrix()

# Sanity: the matrix must be exactly 9450 and fully populated.
# 10 domains x 9 roles x 7 states x 15 edges
_EXPECTED_TOTAL = 9450
_EXPECTED_PER_DOMAIN = 945

assert len(MATRIX) == _EXPECTED_TOTAL, (
    f'matrix built {len(MATRIX)} scenarios, expected {_EXPECTED_TOTAL}')
assert len({s.id for s in MATRIX}) == _EXPECTED_TOTAL, 'scenario ids are not unique'
assert len({s.amount for s in MATRIX}) == _EXPECTED_TOTAL, (
    f'only {len({s.amount for s in MATRIX})} distinct amounts across '
    f'{_EXPECTED_TOTAL} scenarios — assertions would repeat')
for _d in DOMAINS:
    _n = sum(1 for s in MATRIX if s.domain == _d)
    assert _n == _EXPECTED_PER_DOMAIN, (
        f'domain {_d} produced {_n}, expected {_EXPECTED_PER_DOMAIN}')


def matrix_params() -> List[object]:
    import pytest
    return [pytest.param(s, id=s.id) for s in MATRIX]


def domain_params(domain: str) -> List[object]:
    import pytest
    return [pytest.param(s, id=s.id) for s in MATRIX if s.domain == domain]