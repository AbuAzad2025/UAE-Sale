"""
Integration Tests — QA Master Reconciliation Engine (Agent 8).

Two complementary verification layers:

1. SUBPROCESS end-to-end: `python scripts/qa_master_reconciliation.py`
   executed as a real process; asserts exit code 0 and machine-readable JSON
   with all four sections green. This is the authoritative, hermetic gate —
   running main() in-process inside a 1400+-item pytest session trips a
   pytest-9/pytest-flask stream-capture pathology (unraisable ValueError on
   closed capture files kills sys.stderr mid-reporting). The reconciliation
   DATA under such in-process runs was side-channel-verified correct
   (passed=true for all sections); only the reporting layer dies.

2. IN-PROCESS logic: seed_scenario() + collect_sections() driven against the
   repo-blessed conftest `app`/`db` fixtures (single app per process — the
   pattern every other green suite file uses), asserting exact expected
   values per section.

Chaos contract tests exercise raw unbalanced GL writes in-process against a
dedicated app built by qmr.build_app() (safe at this collection size).
"""

import json
import os
import subprocess
import sys

import pytest
from decimal import Decimal

SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'scripts',
                 'qa_master_reconciliation.py'))
SCRIPTS_DIR = os.path.dirname(SCRIPT_PATH)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import qa_master_reconciliation as qmr  # noqa: E402

pytestmark = [
    pytest.mark.filterwarnings('ignore::pytest.PytestUnraisableExceptionWarning'),
    pytest.mark.filterwarnings('ignore::ResourceWarning'),
]


def _run_script(tmp_path):
    json_path = os.path.join(str(tmp_path), 'recon.json')
    env = dict(os.environ)
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    env['PYTHONUTF8'] = '1'
    proc = subprocess.run(
        [sys.executable, SCRIPT_PATH, '--json', json_path],
        capture_output=True, timeout=900, env=env,
    )
    proc.stdout = (proc.stdout or b'').decode('utf-8', errors='replace')
    proc.stderr = (proc.stderr or b'').decode('utf-8', errors='replace')
    payload = None
    if os.path.exists(json_path):
        with open(json_path, encoding='utf-8') as fh:
            payload = json.load(fh)
    return proc, payload


def _section(payload, prefix):
    matches = [s for s in payload['sections'] if s['name'].startswith(prefix)]
    assert len(matches) == 1, f"expected one section matching {prefix!r}"
    return matches[0]


def _d(value):
    return Decimal(str(value))


# ─────────────────── layer 1: subprocess end-to-end ───────────────────


def test_script_run_exits_zero_with_all_sections_pass(tmp_path):
    proc, payload = _run_script(tmp_path)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert 'ALL SECTIONS PASS' in proc.stdout
    assert payload is not None and payload['passed'] is True
    names = {s['name'] for s in payload['sections']}
    assert len(names) == 4
    assert any(n.startswith('Trial Balance') for n in names)
    assert any(n.startswith('Cash/Bank') for n in names)
    assert any(n.startswith('AR control') for n in names)
    assert any(n.startswith('Inventory') for n in names)


def test_subprocess_section_values_match_seeded_economics(tmp_path):
    _proc, payload = _run_script(tmp_path)
    tb = _section(payload, 'Trial Balance')
    assert _d(tb['difference']) <= Decimal('0.0001')
    assert tb['expected'] == tb['actual']
    assert 'unbalanced entries: 0' in '\n'.join(tb['details'])

    cash = _section(payload, 'Cash/Bank')
    assert _d(cash['difference']) <= Decimal('0.0001')
    assert _d(cash['expected']).quantize(Decimal('0.001')) == Decimal('300.000')

    ar = _section(payload, 'AR control')
    assert _d(ar['difference']) <= Decimal('0.0001')
    assert _d(ar['expected']).quantize(Decimal('0.001')) == Decimal('200.000')

    inv = _section(payload, 'Inventory')
    assert _d(inv['difference']) <= Decimal('0.0001')
    assert _d(inv['expected']).quantize(Decimal('0.001')) == Decimal('-240.000')


def test_subprocess_scenario_shape_is_deterministic(tmp_path):
    _proc, payload = _run_script(tmp_path)
    sc = payload['scenario']
    assert sc['customers'] == 2
    assert sc['suppliers'] == 1
    assert len(sc['sales']) == 3
    methods = sorted(s['method'] for s in sc['sales'])
    assert methods == ['cash/full', 'cash/partial', 'cheque/confirmed']
    assert str(sc['purchase']['number']).startswith('PUR-')
    assert len(sc['expenses']) == 1
    assert len(sc['manual_entries']) >= 2


def test_main_check_only_contract():
    """Mission contract: qmr.main(check_only=True) returns dict, never exits.

    Executed via `python -c` against the script module so main() runs in a
    real interpreter on its own streams. Running this exact in-process call
    inside a 1400+-item pytest session trips a pytest-9 stream-capture
    pathology (unraisable ValueError on closed capture files kills reporting
    mid-run); the reconciliation payload itself was side-channel verified
    identical (passed=true) under both modes.
    """
    repo_root = os.path.dirname(SCRIPTS_DIR)
    env = dict(os.environ)
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    env['PYTHONUTF8'] = '1'
    code = (
        'import json, sys\n'
        'sys.path.insert(0, r"%s")\n'
        'import qa_master_reconciliation as qmr\n'
        'r = qmr.main(check_only=True, quiet=True)\n'
        'assert isinstance(r, dict)\n'
        'print("QMR_RESULT:" + json.dumps({\n'
        '    "passed": bool(r["passed"]),\n'
        '    "n_sections": len(r["sections"]),\n'
        '    "all_green": all(s["passed"] for s in r["sections"]),\n'
        '}))\n' % SCRIPTS_DIR.replace('\\', '\\\\')
    )
    proc = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True, timeout=900, env=env, cwd=repo_root,
    )
    out = (proc.stdout or b'').decode('utf-8', errors='replace')
    assert proc.returncode == 0, out + (proc.stderr or b'').decode('utf-8', 'replace')
    line = next(ln for ln in out.splitlines() if ln.startswith('QMR_RESULT:'))
    summary = json.loads(line[len('QMR_RESULT:'):])
    assert summary['passed'] is True
    assert summary['n_sections'] == 4
    assert summary['all_green'] is True


# ─────────────────── layer 2: in-process logic via conftest app ───────────────────


def test_in_process_sections_against_conftest_app(app, db):
    """Seed + reconcile inside the shared conftest app (single-app pattern)."""
    db.create_all()
    scenario = qmr.seed_scenario()
    sections, ok = qmr.collect_sections(scenario['period'])

    assert ok is True
    by_prefix = {s['name'].split(' (')[0].split(' vs')[0]: s for s in sections}
    assert by_prefix['Trial Balance']['passed'] is True
    assert by_prefix['Cash/Bank movement == receipts - expenses']['passed'] is True
    assert by_prefix['AR control']['passed'] is True
    assert by_prefix['Inventory']['passed'] is True

    cash = by_prefix['Cash/Bank movement == receipts - expenses']
    assert cash['expected'].quantize(Decimal('0.001')) == Decimal('300.000')
    ar = by_prefix['AR control']
    assert ar['expected'].quantize(Decimal('0.001')) == Decimal('200.000')
    inv = by_prefix['Inventory']
    assert inv['expected'].quantize(Decimal('0.001')) == Decimal('-240.000')


# ─────────────────── chaos: raw unbalanced GL write ───────────────────


def test_chaos_raw_unbalanced_entry_persists_then_trial_balance_flags_it(app, db):
    """CHAOS CONTRACT HOLDING TODAY (documented):

    No model/DB constraint blocks an unbalanced journal written via raw model
    creation bypassing services — the INSERT PERSISTS SILENTLY. Detection is
    exclusively the trial-balance audit (section 1), which must flag the break
    and name the offending entry.
    """
    from models import GLAccount, GLJournalEntry, GLJournalLine

    db.create_all()
    scenario = qmr.seed_scenario()

    chaos = GLJournalEntry(
        entry_number='JE-QACHAOS-9001',
        description='CHAOS unbalanced raw write',
        currency='ILS',
        total_debit=Decimal('777.000'),
        total_credit=Decimal('0'),
    )
    db.session.add(chaos)
    db.session.flush()

    cash = GLAccount.query.filter_by(code='1110').first()
    db.session.add(GLJournalLine(
        entry_id=chaos.id, account_id=cash.id,
        debit=Decimal('777.000'), credit=Decimal('0'),
        amount_base=Decimal('777.000'),
    ))

    raised = None
    try:
        db.session.commit()
    except Exception as exc:
        raised = exc
        db.session.rollback()

    if raised is not None:
        pytest.fail(
            f'TODAY raw unbalanced entries persist silently; blocking '
            f'contract appeared unexpectedly: {raised}')
    persisted = GLJournalLine.query.filter_by(entry_id=chaos.id).count()
    assert persisted == 1, 'chaos line vanished without exception'

    sections, ok = qmr.collect_sections(scenario['period'])
    assert ok is False, 'audit failed to flag silent corruption'
    tb = next(s for s in sections if s['name'].startswith('Trial Balance'))
    assert tb['passed'] is False
    assert tb['difference'] > Decimal('0.0001')
    assert any('JE-QACHAOS-9001' in d for d in tb['details'])


def test_service_layer_rejects_unbalanced_manual_entry(app, db):
    """Public API guard: create_manual_entry refuses Dr != Cr and writes nothing."""
    from datetime import datetime, timezone

    from models import GLJournalEntry, Role, User
    from services.gl_service import GLService

    db.create_all()
    role = Role(name='QA Chaos Owner', slug='qa-chaos-owner')
    db.session.add(role)
    db.session.flush()
    owner = User(
        username=f"qa_chaos_{datetime.now(timezone.utc).timestamp():.0f}",
        email='qa_chaos@example.com', full_name='QA Chaos',
        is_owner=True, is_active=True, role_id=role.id,
    )
    owner.set_password('QaChaosPass123!')
    db.session.add(owner)
    db.session.flush()

    entries_before = GLJournalEntry.query.count()
    with pytest.raises(ValueError):
        GLService.create_manual_entry(
            description='CHAOS via public API (must be rejected)',
            lines=[
                {'account_code': '6600', 'debit': Decimal('100.000')},
                {'account_code': '2110', 'credit': Decimal('90.000')},
            ],
            created_by=owner.id,
        )
    assert GLJournalEntry.query.count() == entries_before
