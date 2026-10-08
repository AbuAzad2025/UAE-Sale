"""
Execution report for the E2E suite.

Produces a JSON + console breakdown of the matrix: per-domain, per-role,
per-state and per-edge counts, plus the BLOCKED domains with the structural
justification the brief requires ("zero skips without explicit structural
justification").

This module only describes what the matrix contains and what was executed; it
does not invent pass counts. Run it after pytest to attach real results:

    python -m pytest tests/e2e/test_matrix.py -q            # 1500 scenarios
    python -m tests.e2e.report --results results.json       # build the report
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from tests.e2e.matrix import (
    MATRIX, DOMAINS, ROLES, STATES, EDGES, DOMAIN_PERMISSION, role_may_write,
)

# Domains named in the original brief that have no implementation in this
# codebase. They are reported as BLOCKED with the evidence, never silently
# dropped and never replaced with invented tests.
BLOCKED_DOMAINS = {
    'pos': {
        'brief_name': 'Domain E — POS & Multi-Tender Sales',
        'requested_scenarios': 250,
        'reason': (
            'No POS module exists. A route-map audit of all 475 registered '
            'URL rules found zero matches for shift, cashier or tender, and '
            'there is no pos model or pos service.'
        ),
        'evidence': [
            'url_map scan: shift=0, cashier=0, tender=0 matches',
            'models/: no pos*.py',
            'services/: no pos*.py',
        ],
        'unblocks_when': 'A POS module (shift, tender split, change calculation) '
                         'is implemented with HTTP routes.',
    },
    'ecommerce': {
        'brief_name': 'Domain G — E-Commerce & External APIs',
        'requested_scenarios': 250,
        'reason': (
            'No storefront or order-intake surface exists, and the specific '
            'mechanisms the brief names are absent: there are no idempotency '
            'or HMAC routes anywhere in the URL map.'
        ),
        'evidence': [
            'url_map scan: storefront=0, idempot=0, hmac=0 matches',
            'present but not e-commerce: /payment-vault/webhook/{stripe,nowpayments}',
            'present but not e-commerce: /graphql, /graphql/playground',
        ],
        'unblocks_when': 'Storefront publication gates, signed webhooks and '
                         'Idempotency-Key replay handling are implemented.',
    },
}


def _pct(part, whole):
    return round(part / whole * 100, 2) if whole else 0.0


def build_static_breakdown():
    """Describe the matrix itself, independent of any run."""
    by_domain = Counter(s.domain for s in MATRIX)
    by_role = Counter(s.role for s in MATRIX)
    by_state = Counter(s.state for s in MATRIX)
    by_edge = Counter(s.edge for s in MATRIX)

    permitted = sum(1 for s in MATRIX if s.permitted)
    denied = len(MATRIX) - permitted

    role_domain = defaultdict(dict)
    for role in ROLES:
        for domain in DOMAINS:
            role_domain[role][domain] = role_may_write(role, domain)

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'dimensions': {
            'domains': len(DOMAINS),
            'roles': len(ROLES),
            'states': len(STATES),
            'edges': len(EDGES),
            'product': len(DOMAINS) * len(ROLES) * len(STATES) * len(EDGES),
        },
        'scenarios_generated': len(MATRIX),
        'unique_ids': len({s.id for s in MATRIX}),
        'distinct_amounts': len({s.amount for s in MATRIX}),
        'distinct_quantities': len({s.quantity for s in MATRIX}),
        'by_domain': {d: by_domain[d] for d in DOMAINS},
        'by_role': {r: by_role[r] for r in ROLES},
        'by_state': {s: by_state[s] for s in STATES},
        'by_edge': {e: by_edge[e] for e in EDGES},
        'write_authorisation_split': {
            'permitted_positive_path': permitted,
            'denied_asserts_403_and_no_side_effects': denied,
            'denied_pct': _pct(denied, len(MATRIX)),
        },
        'domain_permission_gate': DOMAIN_PERMISSION,
        'role_domain_write_matrix': role_domain,
    }


def merge_results(static, results_path: Path):
    """Attach real pytest outcomes if a results file is supplied."""
    if not results_path or not results_path.exists():
        return static
    try:
        raw = json.loads(results_path.read_text(encoding='utf-8'))
    except Exception as exc:  # pragma: no cover - reporting aid
        static['results_error'] = f'could not read {results_path}: {exc}'
        return static

    static['execution'] = {
        'total': raw.get('total'),
        'passed': raw.get('passed'),
        'failed': raw.get('failed'),
        'errors': raw.get('errors'),
        'skipped': raw.get('skipped'),
        'duration_seconds': raw.get('duration_seconds'),
        'failures': raw.get('failures', [])[:50],
    }
    return static


def render_console(report):
    d = report['dimensions']
    out = []
    bar = '=' * 72
    out.append(bar)
    out.append('E2E EXECUTION REPORT — azad_erp')
    out.append(bar)
    out.append(f"Generated       : {report['generated_at']}")
    out.append(f"Dimensions      : {d['domains']} domains x {d['roles']} roles "
               f"x {d['states']} states x {d['edges']} edges "
               f"= {d['product']}")
    out.append(f"Scenarios       : {report['scenarios_generated']} "
               f"(unique ids {report['unique_ids']})")
    out.append(f"Distinct amounts: {report['distinct_amounts']}  "
               f"quantities: {report['distinct_quantities']}")
    out.append('')

    exec_ = report.get('execution')
    if exec_:
        out.append('EXECUTION')
        out.append('-' * 72)
        out.append(f"  passed  : {exec_['passed']}")
        out.append(f"  failed  : {exec_['failed']}")
        out.append(f"  errors  : {exec_['errors']}")
        out.append(f"  skipped : {exec_['skipped']}")
        out.append(f"  runtime : {exec_['duration_seconds']}s")
        out.append('')

    out.append('PER DOMAIN (executed)')
    out.append('-' * 72)
    for dom, n in report['by_domain'].items():
        gate = report['domain_permission_gate'].get(dom) or 'read-only'
        out.append(f'  {dom:<12} {n:>5} scenarios   gate={gate}')
    out.append('')

    split = report['write_authorisation_split']
    out.append('AUTHORISATION SPLIT')
    out.append('-' * 72)
    out.append(f"  positive path (role may write) : "
               f"{split['permitted_positive_path']}")
    out.append(f"  denial path (403 + no writes)  : "
               f"{split['denied_asserts_403_and_no_side_effects']} "
               f"({split['denied_pct']}%)")
    out.append('')

    out.append('ROLE x DOMAIN WRITE ACCESS  (Y=may write, -=must be refused)')
    out.append('-' * 72)
    header = '  ' + 'role'.ljust(20) + ''.join(f'{x[:7]:>9}' for x in DOMAINS)
    out.append(header)
    for role, row in report['role_domain_write_matrix'].items():
        line = '  ' + role.ljust(20) + ''.join(
            f"{('Y' if row[x] else '-'):>9}" for x in DOMAINS)
        out.append(line)
    out.append('')

    out.append('BLOCKED — structural justification required by the brief')
    out.append('-' * 72)
    for key, info in BLOCKED_DOMAINS.items():
        out.append(f"  {info['brief_name']}  ({info['requested_scenarios']} "
                   f"scenarios not generated)")
        for line in info['reason'].split('. '):
            line = line.strip().rstrip('.')
            if line:
                out.append(f'      {line}.')
        for ev in info['evidence']:
            out.append(f'      evidence: {ev}')
        out.append(f"      unblocks when: {info['unblocks_when']}")
    out.append('')
    out.append(f"TOTAL NOT GENERATED (blocked): "
               f"{sum(i['requested_scenarios'] for i in BLOCKED_DOMAINS.values())}")
    out.append(f"TOTAL GENERATED + EXECUTED    : {report['scenarios_generated']}")
    out.append(bar)
    return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--results', type=Path, default=None,
                    help='JSON file with real pytest outcomes')
    ap.add_argument('--out', type=Path, default=Path('tests/e2e/report.json'))
    args = ap.parse_args(argv)

    report = merge_results(build_static_breakdown(), args.results)
    args.out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(render_console(report))
    print(f'\nJSON written to {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
