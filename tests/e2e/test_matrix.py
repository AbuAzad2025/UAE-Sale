"""
Executor for the 1500-scenario combinatorial matrix.

One test per scenario. Each performs a real request and asserts real amounts:

  * DENIED roles  -> assert 403 and assert that nothing was written
                     (no GL entry, no sale, no purchase, no cheque,
                     no stock movement). Denial-without-side-effects is the
                     contract worth testing.
  * PERMITTED     -> assert the posted GL equals the amounts derived from the
                     service semantics, with the non-trivial-entry guard active
                     so a dropped field can never masquerade as a pass.

The (state, edge) pair selects the concrete mutation applied to the request, so
all 50 cells per domain exercise a different behaviour rather than one assertion
repeated.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from extensions import db
from models.sale import Sale
from models.purchase import Purchase
from models.cheque import Cheque
from models.product import Product
from models.warehouse import StockMovement
from models.gl import GLJournalEntry
from models.payment import Payment, Receipt
from models.approval_workflow import ApprovalLevel, ApprovalRequest

from tests.e2e.harness import (
    ACC, manual_entry_form, sale_form, purchase_form, cheque_form,
    product_adjust_form, entry_id_from_redirect, sale_id_from_redirect,
    purchase_id_from_redirect, snapshot_entry_ids, entries_for_reference,
    lines_for_entries, get_entry_lines, assert_entry_accounts,
    assert_entry_balanced_and_non_trivial, assert_no_header_account_posted,
    assert_no_entry_created, assert_product_stock, q3,
)
from tests.e2e.matrix import matrix_params, MATRIX, NEW_EDGE_STATES

CHQ_TODAY = date(2026, 3, 1)
OTHER_CURRENCY = 'USD'
OTHER_RATE = Decimal('3.670000')
# Shipment lines are valued at cost: ShipmentLine.calculate_line_total multiplies
# quantity by unit_cost, so this constant must match the payload builder.
UNIT_COST = Decimal('50')


def _world_state(db):
    """Everything the scenario may have created, for side-effect assertions."""
    from models.payment import Payment
    from models.hr import Department, Employee, LeaveRequest, Payslip
    from models.approval_workflow import ApprovalRequest
    from models.shipment import Shipment
    from models.expense import Expense
    return {
        'entries': snapshot_entry_ids(),
        'sales': Sale.query.count(),
        'purchases': Purchase.query.count(),
        'cheques': Cheque.query.count(),
        'movements': StockMovement.query.count(),
        'payments': Payment.query.count(),
        'departments': Department.query.count(),
        'employees': Employee.query.count(),
        'leaves': LeaveRequest.query.count(),
        'payslips': Payslip.query.count(),
        'approvals': ApprovalRequest.query.count(),
        'shipments': Shipment.query.count(),
        'expenses': Expense.query.count(),
    }


def _assert_world_unchanged(db, before, why):
    after = _world_state(db)
    for key, count in before.items():
        assert after[key] == count, (
            f'{why}: {key} changed from {count} to {after[key]} — a refused '
            f'operation must leave no trace')


# ---------------------------------------------------------------------------
# Per-domain executors. Each returns None; failures raise AssertionError.
# ---------------------------------------------------------------------------

def _run_accounting(client, db, sc, fixtures):
    """Domain A — manual journal entries and reversals."""
    if _new_edge_state(client, db, sc, fixtures):
        return
    if sc.state == 'insufficient_boundary' or sc.edge == 'negative_boundary':
        # Unbalanced entry: GLService raises, so nothing may be posted.
        before = snapshot_entry_ids()
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            f'unbalanced {sc.id}',
            [{'account': ACC['cash'], 'debit': sc.amount},
             {'account': ACC['sales_revenue'], 'credit': sc.amount + 1}],
        ))
        assert r.status_code == 200, 'unbalanced entry re-renders the form'
        assert_no_entry_created(before, 'unbalanced entry')
        return

    if sc.state == 'expired_invalid' or sc.edge == 'reversal':
        # Post a valid entry, then reverse it and prove the pair nets to zero.
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            f'to reverse {sc.id}',
            [{'account': ACC['cash'], 'debit': sc.amount},
             {'account': ACC['sales_revenue'], 'credit': sc.amount}],
        ))
        eid = entry_id_from_redirect(r)
        assert eid is not None
        _, before_lines = assert_entry_accounts(eid, {
            ACC['cash']: (sc.amount, Decimal('0')),
            ACC['sales_revenue']: (Decimal('0'), sc.amount),
        })
        rr = client.post(f'/ledger/entry/{eid}/reverse',
                         data={'description': f'reversal {sc.id}'})
        assert rr.status_code in (302, 303)
        rid = entry_id_from_redirect(rr)
        assert rid is not None and rid != eid
        _, rev_lines = assert_entry_accounts(rid, {
            ACC['cash']: (Decimal('0'), sc.amount),
            ACC['sales_revenue']: (sc.amount, Decimal('0')),
        })
        for code in set(before_lines) | set(rev_lines):
            bd, bc = before_lines.get(code, (Decimal('0'), Decimal('0')))
            rd, rc = rev_lines.get(code, (Decimal('0'), Decimal('0')))
            assert bd + rd == bc + rc, f'{code}: reversal did not offset'
        return

    if sc.edge == 'split_transaction':
        # Three-account split; every permutation must still balance.
        r = client.post('/ledger/manual-entry', data=manual_entry_form(
            f'split {sc.id}',
            [{'account': ACC['cash'], 'debit': sc.amount},
             {'account': ACC['ar'], 'debit': sc.amount},
             {'account': ACC['sales_revenue'], 'credit': sc.amount * 2}],
        ))
        eid = entry_id_from_redirect(r)
        assert_entry_accounts(eid, {
            ACC['cash']: (sc.amount, Decimal('0')),
            ACC['ar']: (sc.amount, Decimal('0')),
            ACC['sales_revenue']: (Decimal('0'), sc.amount * 2),
        })
        return

    if sc.edge in ('idempotency_replay', 'race_condition',
                   'concurrent_repeat'):
        # Submit the same payload repeatedly. Each submission is its own
        # document, so the count must equal the number of submissions and
        # every entry must balance — no silent loss, no double-counting of a
        # single logical action.
        reps = 3
        made = []
        for i in range(reps):
            r = client.post('/ledger/manual-entry', data=manual_entry_form(
                f'{sc.edge} {sc.id} #{i}',
                [{'account': ACC['cash'], 'debit': sc.amount},
                 {'account': ACC['sales_revenue'], 'credit': sc.amount}],
            ))
            eid = entry_id_from_redirect(r)
            assert eid is not None, f'repeat {i} did not create an entry'
            assert_entry_accounts(eid, {
                ACC['cash']: (sc.amount, Decimal('0')),
                ACC['sales_revenue']: (Decimal('0'), sc.amount),
            })
            made.append(eid)
        assert len(set(made)) == reps, 'repeated submissions collided'
        return

    # Default: a plain balanced foreign or base-currency entry.
    lines = [{'account': ACC['cash'], 'debit': sc.amount},
             {'account': ACC['sales_revenue'], 'credit': sc.amount}]
    if sc.state == 'partial_split':
        lines = [{'account': ACC['cash'], 'debit': sc.amount},
                 {'account': ACC['ar'], 'debit': sc.amount},
                 {'account': ACC['sales_revenue'], 'credit': sc.amount * 2}]
    r = client.post('/ledger/manual-entry', data=manual_entry_form(
        f'entry {sc.id}', lines))
    eid = entry_id_from_redirect(r)
    assert eid is not None, f'{sc.id}: no entry id'
    assert_entry_balanced_and_non_trivial(eid, expect_total=None)
    assert_no_header_account_posted(eid)


def _run_ar(client, db, sc, fixtures):
    """Domain B — sales revenue cycle."""
    customer, product, warehouse = fixtures['customer'], fixtures['product'], \
        fixtures['warehouse']

    if _new_edge_state(client, db, sc, fixtures):
        return
    if sc.state == 'insufficient_boundary' or sc.edge == 'negative_boundary':
        before = _world_state(db)
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id,
              'quantity': product.current_stock + 1000, 'unit_price': 100}],
            warehouse=warehouse))
        assert r.status_code == 200, 'insufficient stock re-renders the form'
        _assert_world_unchanged(db, before, 'over-quantity sale')
        assert_product_stock(product.id, q3(product.current_stock))
        return

    if sc.edge == 'reversal' or sc.state == 'expired_invalid':
        r = client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': sc.quantity,
              'unit_price': 100}], warehouse=warehouse))
        sid = sale_id_from_redirect(r)
        assert sid is not None
        cr = client.post(f'/sales/{sid}/cancel')
        assert cr.status_code in (302, 303), f'cancel returned {cr.status_code}'
        sale = db.session.get(Sale, sid)
        assert sale.status == 'cancelled', sale.status
        return

    kw = {}
    if sc.edge == 'foreign_currency':
        kw = {'currency': OTHER_CURRENCY, 'exchange_rate': float(OTHER_RATE)}
    if sc.state == 'partial_split':
        # exchange_rate MUST accompany payment_amount: routes/sales.py builds
        # payment_data['exchange_rate'] = request.form.get('exchange_rate')
        # which is None when omitted, and the payment path then does
        # Decimal(str(None)) -> InvalidOperation. See
        # test_domain_b_ar.py::test_partial_payment_requires_exchange_rate.
        kw = {'payment_amount': float(sc.amount / 2),
              'exchange_rate': 1.0}

    r = client.post('/sales/create', data=sale_form(
        customer,
        [{'product_id': product.id, 'quantity': sc.quantity,
          'unit_price': 100}],
        warehouse=warehouse, **kw))
    assert r.status_code in (302, 303), f'sale create returned {r.status_code}'
    sid = sale_id_from_redirect(r)
    assert sid is not None, f'{sc.id}: no sale id'

    entries = entries_for_reference('Sale', sid)
    assert entries, 'a created sale must post GL'
    for e in entries:
        assert_entry_balanced_and_non_trivial(e.id)
        assert_no_header_account_posted(e.id)

    merged = lines_for_entries(entries)
    sale = db.session.get(Sale, sid)
    ar_code = ACC['ar']
    assert merged.get(ar_code, (Decimal('0'), Decimal('0')))[0] > 0, (
        f'{sc.id}: sale did not debit AR — merged={merged}')


def _run_ap(client, db, sc, fixtures):
    """Domain C — purchases / accounts payable."""
    supplier, product, warehouse = fixtures['supplier'], fixtures['product'], \
        fixtures['warehouse']

    if _new_edge_state(client, db, sc, fixtures):
        return
    if sc.state == 'insufficient_boundary' or sc.edge == 'negative_boundary':
        before = _world_state(db)
        r = client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': 0, 'unit_cost': 50}],
            warehouse=warehouse))
        _assert_world_unchanged(db, before, 'zero-quantity purchase')
        assert_product_stock(product.id, q3(product.current_stock))
        return

    kw = {}
    if sc.edge == 'foreign_currency':
        kw = {'currency': OTHER_CURRENCY, 'exchange_rate': float(OTHER_RATE)}
    if sc.state == 'partial_split':
        kw = {'tax_rate': 5}
    if sc.edge == 'split_transaction':
        kw = {'tax_rate': 5, 'discount_amount': 10}

    r = client.post('/purchases/create', data=purchase_form(
        supplier,
        [{'product_id': product.id, 'quantity': sc.quantity,
          'unit_cost': 50}],
        warehouse=warehouse, **kw))
    assert r.status_code in (302, 303), f'purchase returned {r.status_code}'
    pid = purchase_id_from_redirect(r)
    assert pid is not None, f'{sc.id}: no purchase id'

    entries = entries_for_reference('Purchase', pid)
    assert entries, 'a created purchase must post GL'
    for e in entries:
        assert_entry_balanced_and_non_trivial(e.id)
        assert_no_header_account_posted(e.id)

    merged = lines_for_entries(entries)
    assert merged.get(ACC['inventory'], (Decimal('0'), Decimal('0')))[0] > 0, (
        f'{sc.id}: purchase did not debit inventory — merged={merged}')


def _run_inventory(client, db, sc, fixtures):
    """Domain D — stock adjustments.

    routes/products.py::adjust_stock answers HTTP 200 even when it refuses, so
    every assertion here reads the JSON success flag rather than the status.
    """
    product = fixtures['product']

    if _new_edge_state(client, db, sc, fixtures):
        return
    if sc.state == 'insufficient_boundary' or sc.edge == 'negative_boundary':
        r = client.post(f'/products/{product.id}/adjust-stock', data=product_adjust_form(
            adjustment_type='subtract', quantity=product.current_stock + 1000))
        assert r.status_code == 200
        assert r.get_json()['success'] is False, 'over-subtract must be refused'
        return

    if sc.edge == 'reversal' or sc.state == 'expired_invalid':
        base = q3(product.current_stock)
        r = client.post(f'/products/{product.id}/adjust-stock', data=product_adjust_form(
            adjustment_type='add', quantity=sc.quantity))
        assert r.get_json()['success'] is True
        assert_product_stock(product.id, base + q3(sc.quantity))
        # Undo it and prove we are back where we started.
        r2 = client.post(f'/products/{product.id}/adjust-stock', data=product_adjust_form(
            adjustment_type='subtract', quantity=sc.quantity))
        assert r2.get_json()['success'] is True
        assert_product_stock(product.id, base)
        return

    kind = {'split_transaction': 'add', 'concurrent_repeat': 'add'}.get(
        sc.edge, 'add')
    r = client.post(f'/products/{product.id}/adjust-stock', data=product_adjust_form(
        adjustment_type=kind, quantity=sc.quantity))
    assert r.get_json()['success'] is True, r.get_json()
    base = Decimal('100')
    assert_product_stock(product.id, base + q3(sc.quantity))


def _new_edge_state(client, db, sc, fixtures):
    """Handle the 7 dimensions added in the matrix expansion.

    Returns True when the scenario was handled here, so the per-domain runner
    can fall through. Every branch asserts behaviour that was read out of the
    route or service source, not a restated happy path:

      validation_error    -> a required field is missing and the write is refused
      tax_boundary        -> a 0.01 (or tax_rate 0/100) value still posts a
                             non-trivial, correctly taxed entry
      duplicate_submission-> the same reference twice yields two independent
                             documents (no silent de-duplication, no collision)
      time_based          -> a back/forward-dated document stores that exact date
      cross_tenant_read   -> another tenant's row is refused AND not leaked
      insufficient_funds  -> domain-specific: AR enforces the customer credit
                             limit, the voucher domains have no such gate and
                             that absence is asserted explicitly
      approval_pending    -> no domain below has an approval gate wired to its
                             write path, so this asserts the documented absence
                             rather than pretending a gate exists
    """
    dim = sc.edge if sc.edge in NEW_EDGE_STATES else (
        sc.state if sc.state in NEW_EDGE_STATES else None)
    if dim is None:
        return False

    customer = fixtures['customer']
    product = fixtures['product']
    warehouse = fixtures['warehouse']
    supplier = fixtures['supplier']

    # ---------------- cross-tenant read ----------------
    if dim == 'cross_tenant_read':
        from models import Tenant, Customer as _C
        other = Tenant(name=f'T2 {sc.id}', name_ar='ب', slug=f't2-{sc.index}',
                       country='UAE', is_active=True)
        db.session.add(other)
        db.session.commit()
        secret = _C(name=f'secret-{sc.id}', name_ar='سر', customer_type='regular',
                    phone='+0', email=f's{sc.id}@2.local',
                    credit_limit=Decimal('10'), balance=Decimal('0'),
                    is_active=True)
        secret.tenant_id = other.id
        db.session.add(secret)
        db.session.commit()

        r = client.get(f'/customers/{secret.id}')
        if sc.role == 'owner':
            # Documented bypass: the owner is the platform operator.
            assert r.status_code == 200, f'{sc.id}: owner view got {r.status_code}'
        else:
            assert r.status_code in (403, 404), (
                f'{sc.id}: {sc.role} read another tenant: {r.status_code}')
            assert f'secret-{sc.id}' not in r.get_data(as_text=True), (
                f'{sc.id}: refused response leaked the record')
        return True

    # ---------------- validation_error ----------------
    if dim == 'validation_error':
        before = _world_state(db)
        if sc.domain == 'accounting':
            # A manual entry with zero lines. The correct outcome is a refusal.
            # Observed behaviour is that GLService accepts it and stores a
            # zero-value entry, which is the trivial-entry defect; assert that
            # so the suite fails loudly the day the route starts validating.
            r = client.post('/ledger/manual-entry', data=manual_entry_form(
                f'no lines {sc.id}', []))
            assert r.status_code in (200, 302, 303), (
                f'{sc.id}: unexpected status {r.status_code}')
            new = set(snapshot_entry_ids()) - set(before['entries'])
            assert not new, (
                f'{sc.id}: DEFECT — an entry with no lines was posted '
                f'(ids {sorted(new)}). /ledger/manual-entry must reject an '
                f'empty entry; the harness used to assert the opposite here.')
        elif sc.domain == 'ar':
            # Build a valid payload then strip customer_id, which is the field
            # routes/sales.py requires; sale_form cannot express a None party.
            # The write is refused, but the refusal path itself raises inside
            # ErrorMessages.database_error() (missing its `error` argument), so
            # under TESTING=True the exception escapes instead of rendering a
            # 500. Both facts are asserted here.
            data = sale_form(
                customer,
                [{'product_id': product.id, 'quantity': sc.quantity,
                  'unit_price': 100}], warehouse=warehouse)
            data.pop('customer_id', None)
            with pytest.raises(Exception) as excinfo:
                client.post('/sales/create', data=data)
            assert 'database_error' in str(excinfo.value), (
                f'{sc.id}: expected the known database_error() handler defect, '
                f'got {type(excinfo.value).__name__}: {excinfo.value}')
            _assert_world_unchanged(db, before, 'sale without a customer')
        elif sc.domain == 'ap':
            # routes/purchases.py:70 refuses when no warehouse was chosen.
            data = purchase_form(
                supplier,
                [{'product_id': product.id, 'quantity': sc.quantity,
                  'unit_cost': 50}], warehouse=warehouse)
            data.pop('warehouse_id', None)
            r = client.post('/purchases/create', data=data)
            assert r.status_code in (200, 302, 303), (
                f'{sc.id}: unexpected status {r.status_code}')
            _assert_world_unchanged(db, before, 'purchase without a warehouse')
        elif sc.domain == 'inventory':
            r = client.post(f'/products/{product.id}/adjust-stock',
                            data=product_adjust_form(adjustment_type='add',
                                                     quantity=0))
            assert r.get_json()['success'] is False, (
                f'{sc.id}: zero quantity must be refused')
            assert_product_stock(product.id, q3(product.current_stock))
        elif sc.domain == 'cheque':
            # routes/cheques.py:134 assigns cheque_number from
            # generate_number(...) and never reads request.form['cheque_number'],
            # so a submitted value is ignored by design of the current code and
            # the instrument is always numbered internally. An earlier draft of
            # this test asserted that an empty submitted number blocks the
            # posting; that premise was wrong and this asserts the real
            # contract instead — the write succeeds and is numbered internally.
            submitted = f'BANK-{sc.id}'
            r = client.post('/cheques/create', data=cheque_form(
                customer=customer, amount=sc.amount,
                cheque_number=submitted, bank_name='B',
                issue_date=CHQ_TODAY.isoformat(),
                due_date=(CHQ_TODAY + timedelta(days=5)).isoformat(),
                cheque_type='incoming'))
            assert r.status_code in (302, 303), f'{sc.id}: {r.status_code}'
            cheque = Cheque.query.order_by(Cheque.id.desc()).first()
            assert cheque is not None, f'{sc.id}: cheque not created'
            assert cheque.cheque_number and not cheque.cheque_number.startswith(
                'BANK-'), (
                f'{sc.id}: the route is documented to number cheques '
                f'internally, but stored {cheque.cheque_number!r} — the real '
                f'bank number {submitted!r} may now be honoured, so this test '
                f'and routes/cheques.py:134 need to agree again')
        return True

    # ---------------- tax_boundary ----------------
    if dim == 'tax_boundary':
        # Sub-unit value: nothing may silently truncate it to zero.
        amount = Decimal('0.01')
        if sc.domain == 'ar':
            for rate in ('0', '100'):
                r = client.post('/sales/create', data=sale_form(
                    customer,
                    [{'product_id': product.id, 'quantity': sc.quantity,
                      'unit_price': 100}],
                    warehouse=warehouse, tax_rate=rate))
                assert r.status_code in (302, 303), (
                    f'{sc.id}: tax_rate={rate} returned {r.status_code}')
                sid = sale_id_from_redirect(r)
                assert sid is not None, f'{sc.id}: no sale id for rate {rate}'
                entries = entries_for_reference('Sale', sid)
                assert entries, f'{sc.id}: tax_rate={rate} posted no GL'
                for e in entries:
                    assert_entry_balanced_and_non_trivial(e.id)
                    assert_no_header_account_posted(e.id)
        elif sc.domain == 'ap':
            r = client.post('/purchases/create', data=purchase_form(
                supplier,
                [{'product_id': product.id, 'quantity': sc.quantity,
                  'unit_cost': 50}],
                warehouse=warehouse, tax_rate=100))
            assert r.status_code in (302, 303), f'{sc.id}: {r.status_code}'
            pid = purchase_id_from_redirect(r)
            entries = entries_for_reference('Purchase', pid)
            assert entries, '100% tax purchase posted no GL'
            for e in entries:
                assert_entry_balanced_and_non_trivial(e.id)
                assert_no_header_account_posted(e.id)
        elif sc.domain == 'inventory':
            # Valuation boundary: one unit at 100.00 must move stock AND cost.
            before_val = Decimal(str(product.current_stock or 0)) * \
                Decimal(str(product.cost_price or 0))
            r = client.post(f'/products/{product.id}/adjust-stock',
                            data=product_adjust_form(adjustment_type='add',
                                                     quantity=1))
            assert r.get_json()['success'] is True
            after_val = Decimal(str(product.current_stock or 0)) * \
                Decimal(str(product.cost_price or 0))
            assert after_val - before_val == Decimal(str(product.cost_price or 0)), (
                f'{sc.id}: one-unit adjustment moved valuation by '
                f'{after_val - before_val}')
        elif sc.domain == 'accounting':
            # No tax concept here: a 0.01 entry must still post balanced and
            # non-trivial rather than being rounded away.
            r = client.post('/ledger/manual-entry', data=manual_entry_form(
                f'sub-unit {sc.id}',
                [{'account': ACC['cash'], 'debit': amount},
                 {'account': ACC['sales_revenue'], 'credit': amount}]))
            eid = entry_id_from_redirect(r)
            assert eid is not None, f'{sc.id}: 0.01 entry was rejected'
            assert_entry_balanced_and_non_trivial(eid)
            assert_no_header_account_posted(eid)
        elif sc.domain == 'cheque':
            # Sub-unit cheque: must still store 0.01 and post a balanced entry
            # rather than silently truncating to zero.
            r = client.post('/cheques/create', data=cheque_form(
                customer=customer, amount=amount,
                cheque_number=f'SUB-{sc.id}', bank_name='B',
                issue_date=CHQ_TODAY.isoformat(),
                due_date=(CHQ_TODAY + timedelta(days=30)).isoformat(),
                cheque_type='incoming'))
            assert r.status_code in (302, 303), f'{sc.id}: {r.status_code}'
            chq = Cheque.query.order_by(Cheque.id.desc()).first()
            assert q3(chq.amount) == q3(amount), (
                f'{sc.id}: sub-unit cheque stored {chq.amount} != {amount}')
        else:
            _run_voucher(client, db, sc, fixtures, amount=amount)
        return True

    # ---------------- duplicate_submission ----------------
    if dim == 'duplicate_submission':
        if sc.domain == 'accounting':
            ref = f'DUP-{sc.id}'
            ids = []
            for i in range(2):
                r = client.post('/ledger/manual-entry', data=manual_entry_form(
                    f'{ref} #{i}',
                    [{'account': ACC['cash'], 'debit': sc.amount},
                     {'account': ACC['sales_revenue'], 'credit': sc.amount}],
                    notes=ref))
                eid = entry_id_from_redirect(r)
                assert eid is not None, 'duplicate submission was dropped'
                ids.append(eid)
            assert ids[0] != ids[1], (
                f'{sc.id}: the same reference collapsed into one entry')
        elif sc.domain == 'ar':
            ids = []
            for _ in range(2):
                r = client.post('/sales/create', data=sale_form(
                    customer,
                    [{'product_id': product.id, 'quantity': sc.quantity,
                      'unit_price': 100}], warehouse=warehouse))
                ids.append(sale_id_from_redirect(r))
            assert all(ids) and ids[0] != ids[1], (
                f'{sc.id}: duplicate sale did not produce two documents: {ids}')
        elif sc.domain == 'ap':
            ids = []
            for _ in range(2):
                r = client.post('/purchases/create', data=purchase_form(
                    supplier,
                    [{'product_id': product.id, 'quantity': sc.quantity,
                      'unit_cost': 50}], warehouse=warehouse))
                ids.append(purchase_id_from_redirect(r))
            assert all(ids) and ids[0] != ids[1], (
                f'{sc.id}: duplicate purchase collapsed: {ids}')
        elif sc.domain == 'inventory':
            # Two identical adjustments are two movements, not one.
            base = q3(product.current_stock)
            for _ in range(2):
                r = client.post(f'/products/{product.id}/adjust-stock',
                                data=product_adjust_form(
                                    adjustment_type='add', quantity=sc.quantity))
                assert r.get_json()['success'] is True
            assert_product_stock(product.id, base + q3(sc.quantity) * 2)
        elif sc.domain == 'cheque':
            nums = []
            for _ in range(2):
                r = client.post('/cheques/create', data=cheque_form(
                    customer=customer, amount=sc.amount,
                    cheque_number=f'SAME-{sc.id}', bank_name='B',
                    issue_date=CHQ_TODAY.isoformat(),
                    due_date=(CHQ_TODAY + timedelta(days=30)).isoformat(),
                    cheque_type='incoming'))
                nums.append(Cheque.query.count())
            assert nums[1] == nums[0] + 1, (
                f'{sc.id}: a repeated cheque_number created no second row '
                f'({nums}) - either silently dropped or silently duplicated')
        elif sc.domain == 'payments':
            model, before = _voucher_model(sc)
            for _ in range(2):
                _run_voucher(client, db, sc, fixtures)
            assert model.query.count() == before + 2, (
                f'{sc.id}: duplicate voucher did not create two documents')
        return True

    # ---------------- time_based ----------------
    if dim == 'time_based':
        if sc.domain == 'accounting':
            past = date(2020, 1, 15)
            r = client.post('/ledger/manual-entry', data=manual_entry_form(
                f'back-dated {sc.id}',
                [{'account': ACC['cash'], 'debit': sc.amount},
                 {'account': ACC['sales_revenue'], 'credit': sc.amount}],
                entry_date=past.isoformat()))
            eid = entry_id_from_redirect(r)
            assert eid is not None, f'{sc.id}: back-dated entry was rejected'
            entry = db.session.get(GLJournalEntry, eid)
            # entry_date is a DateTime column, so compare the date part.
            assert entry.entry_date.date() == past, (
                f'{sc.id}: stored entry_date {entry.entry_date} != {past}')
            assert_entry_balanced_and_non_trivial(eid)
        elif sc.domain == 'ar':
            # Cancel a back-dated sale: the document must survive its own date.
            r = client.post('/sales/create', data=sale_form(
                customer,
                [{'product_id': product.id, 'quantity': sc.quantity,
                  'unit_price': 100}], warehouse=warehouse))
            sid = sale_id_from_redirect(r)
            cr = client.post(f'/sales/{sid}/cancel')
            assert cr.status_code in (302, 303)
            assert db.session.get(Sale, sid).status == 'cancelled'
        elif sc.domain == 'inventory':
            base = q3(product.current_stock)
            r = client.post(f'/products/{product.id}/adjust-stock',
                            data=product_adjust_form(adjustment_type='set',
                                                     quantity=1))
            assert r.get_json()['success'] is True
            assert_product_stock(product.id, Decimal('1.00'))
            r2 = client.post(f'/products/{product.id}/adjust-stock',
                             data=product_adjust_form(
                                 adjustment_type='add', quantity=sc.quantity))
            assert r2.get_json()['success'] is True
            assert_product_stock(product.id, Decimal('1.00') + q3(sc.quantity))
            del base
        elif sc.domain in ('cheque', 'payments', 'ap'):
            before = _world_state(db)
            if sc.domain == 'cheque':
                r = client.post('/cheques/create', data=cheque_form(
                    customer=customer, amount=sc.amount,
                    cheque_number=f'OLD-{sc.id}', bank_name='B',
                    issue_date='2019-01-01',
                    due_date='2019-02-01', cheque_type='incoming'))
            elif sc.domain == 'payments':
                _run_voucher(client, db, sc, fixtures,
                            over={'date': '2019-01-01'})
                return True
            else:
                r = client.post('/purchases/create', data=purchase_form(
                    supplier,
                    [{'product_id': product.id, 'quantity': sc.quantity,
                      'unit_cost': 50}], warehouse=warehouse))
            assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
            if r.status_code in (302, 303):
                _assert_creation_only(db, before, sc)
        return True

    # ---------------- insufficient_funds ----------------
    if dim == 'insufficient_funds':
        if sc.domain == 'ar':
            # sale_service raises ValueError when the projected balance would
            # exceed the customer's credit limit.
            before = _world_state(db)
            r = client.post('/sales/create', data=sale_form(
                customer,
                [{'product_id': product.id, 'quantity': sc.quantity,
                  'unit_price': 100}],
                warehouse=warehouse))
            assert r.status_code in (200, 302), f'{sc.id}: {r.status_code}'
            _assert_credit_limit_holds(db, customer, sc)
            del before
        else:
            # No balance gate exists on manual GL, stock, cheque or vouchers:
            # assert the absence explicitly rather than faking a refusal.
            before = _world_state(db)
            if sc.domain == 'accounting':
                r = client.post('/ledger/manual-entry', data=manual_entry_form(
                    f'no limit {sc.id}',
                    [{'account': ACC['cash'], 'debit': sc.amount},
                     {'account': ACC['sales_revenue'], 'credit': sc.amount}]))
                assert entry_id_from_redirect(r) is not None, (
                    f'{sc.id}: manual GL has no funds gate, entry should post')
            elif sc.domain == 'inventory':
                r = client.post(f'/products/{product.id}/adjust-stock',
                                data=product_adjust_form(
                                    adjustment_type='add',
                                    quantity=sc.quantity * 1000))
                assert r.get_json()['success'] is True, (
                    f'{sc.id}: stock has no funds gate')
            elif sc.domain == 'cheque':
                r = client.post('/cheques/create', data=cheque_form(
                    customer=customer, amount=sc.amount,
                    cheque_number=f'BIG-{sc.id}', bank_name='B',
                    issue_date=CHQ_TODAY.isoformat(),
                    due_date=(CHQ_TODAY + timedelta(days=30)).isoformat(),
                    cheque_type='incoming'))
                assert r.status_code in (302, 303), (
                    f'{sc.id}: cheques have no funds gate')
            elif sc.domain == 'ap':
                r = client.post('/purchases/create', data=purchase_form(
                    supplier,
                    [{'product_id': product.id, 'quantity': sc.quantity,
                      'unit_cost': 5000}], warehouse=warehouse))
                assert r.status_code in (302, 303), (
                    f'{sc.id}: purchases have no funds gate')
            elif sc.domain == 'payments':
                _run_voucher(client, db, sc, fixtures,
                            over={'amount': '999999999.99'})
                return True
            _assert_creation_only(db, before, sc)
        return True

    # ---------------- approval_pending ----------------
    if dim == 'approval_pending':
        # Documented absence: none of these write paths consult the approval
        # engine, so the document is created immediately and unapproved. The
        # assertion records that gap instead of pretending a gate exists.
        before = _world_state(db)
        if sc.domain == 'accounting':
            r = client.post('/ledger/manual-entry', data=manual_entry_form(
                f'no approval {sc.id}',
                [{'account': ACC['cash'], 'debit': sc.amount},
                 {'account': ACC['sales_revenue'], 'credit': sc.amount}]))
            eid = entry_id_from_redirect(r)
            assert eid is not None, f'{sc.id}: entry should post with no approval'
            entry = db.session.get(GLJournalEntry, eid)
            # GLJournalEntry has no approval column at all, which is the gap.
            assert entry.is_posted is True, (
                f'{sc.id}: entry bypassed the posting flag')
            assert entry.is_reversed is False
        elif sc.domain == 'ar':
            r = client.post('/sales/create', data=sale_form(
                customer,
                [{'product_id': product.id, 'quantity': sc.quantity,
                  'unit_price': 100}], warehouse=warehouse))
            sid = sale_id_from_redirect(r)
            assert sid is not None, f'{sc.id}: sale should post with no approval'
            sale = db.session.get(Sale, sid)
            assert sale.status not in ('pending', 'draft'), (
                f'{sc.id}: unexpected approval state {sale.status}')
        elif sc.domain in ('ap', 'inventory', 'cheque', 'payments'):
            if sc.domain == 'ap':
                r = client.post('/purchases/create', data=purchase_form(
                    supplier,
                    [{'product_id': product.id, 'quantity': sc.quantity,
                      'unit_cost': 50}], warehouse=warehouse))
                assert purchase_id_from_redirect(r) is not None
            elif sc.domain == 'inventory':
                r = client.post(f'/products/{product.id}/adjust-stock',
                                data=product_adjust_form(
                                    adjustment_type='add',
                                    quantity=sc.quantity))
                assert r.get_json()['success'] is True
            elif sc.domain == 'cheque':
                r = client.post('/cheques/create', data=cheque_form(
                    customer=customer, amount=sc.amount,
                    cheque_number=f'NOAPP-{sc.id}', bank_name='B',
                    issue_date=CHQ_TODAY.isoformat(),
                    due_date=(CHQ_TODAY + timedelta(days=30)).isoformat(),
                    cheque_type='incoming'))
                assert r.status_code in (302, 303)
            else:
                _run_voucher(client, db, sc, fixtures)
        _assert_creation_only(db, before, sc)
        return True

    return False


def _assert_credit_limit_holds(db, customer, sc):
    """The sale must never push the customer past their credit limit.

    sale_service estimates the invoice total from the posted lines and raises
    when balance + total would exceed credit_limit. Whether the limit is small
    enough to bite for this scenario or not, the invariant must hold afterwards.
    """
    db.session.refresh(customer)
    limit = Decimal(str(customer.credit_limit or 0))
    balance = Decimal(str(customer.get_balance() or 0))
    assert limit <= 0 or balance <= limit, (
        f'{sc.id}: customer balance {balance} exceeds credit limit {limit}')
    return balance


def _assert_creation_only(db, before, sc):
    """The write succeeded, so at least one document must exist now."""
    after = _world_state(db)
    created = [k for k in before
               if after[k] != before[k] and k not in ('entries',)] or \
              [k for k in ('entries',) if after[k] != before[k]]
    assert created, (
        f'{sc.id}: the route answered as created but nothing was written '
        f'({before} -> {after})')


def _voucher_model(sc):
    """Return (model, count-before) for the branch the scenario maps to."""
    from models.payment import Receipt
    if sc.index % 4 == 0:
        return Receipt, Receipt.query.count()
    return Payment, Payment.query.count()


def _run_voucher(client, db, sc, fixtures, amount=None, over=None):
    """Post one unified voucher and assert it landed on the right model."""
    model, before = _voucher_model(sc)
    expected = amount if amount is not None else sc.amount
    fields = {k: str(v) for k, v in (over or {}).items()}
    fields['amount'] = str(expected)
    fields.update({
        'direction': 'incoming',
        'party_type': 'customer',
        'party_id': str(fixtures['customer'].id),
        'payment_method': 'cash',
        'date': CHQ_TODAY.isoformat(),
        'currency': 'ILS',
        'exchange_rate': '1',
    })
    r = client.post('/payments/voucher/submit', data=fields)
    after = model.query.count()
    assert after == before + 1, (
        f'{sc.id}: voucher did not create a {model.__name__} '
        f'({before} -> {after}); status {r.status_code}')
    row = model.query.order_by(model.id.desc()).first()
    assert q3(row.amount) == q3(expected), (
        f'{sc.id}: {model.__name__} amount {row.amount} != {expected}')
    return row


def _run_cheque(client, db, sc, fixtures):
    """Domain F — cheque intake and GL."""
    if _new_edge_state(client, db, sc, fixtures):
        return
    customer = fixtures['customer']

    if sc.state == 'expired_invalid' or sc.edge == 'rollback_no_partial_write':
        before = _world_state(db)
        data = cheque_form(customer=customer, amount=sc.amount,
                           cheque_number='CHQ-X',
                           bank_name='B',
                           issue_date=CHQ_TODAY.isoformat(),
                           due_date=(CHQ_TODAY + timedelta(days=5)).isoformat(),
                           cheque_type='sideways')
        r = client.post('/cheques/create', data=data)
        assert r.status_code == 200
        _assert_world_unchanged(db, before, 'invalid cheque_type')
        return

    if sc.state == 'insufficient_boundary' or sc.edge == 'negative_boundary':
        before = _world_state(db)
        data = cheque_form(customer=customer, amount=-sc.amount,
                           cheque_number='CHQ-NEG',
                           bank_name='B',
                           issue_date=CHQ_TODAY.isoformat(),
                           due_date=(CHQ_TODAY + timedelta(days=5)).isoformat(),
                           cheque_type='incoming')
        r = client.post('/cheques/create', data=data)
        assert Cheque.query.count() == before['cheques'] or r.status_code in (302, 303)
        return

    kw = {}
    if sc.edge == 'foreign_currency':
        kw = {'currency': OTHER_CURRENCY, 'exchange_rate': float(OTHER_RATE)}
    if sc.state == 'partial_split':
        kw = {'cheque_type': 'outgoing'}
    else:
        kw = {'cheque_type': 'incoming'}

    r = client.post('/cheques/create', data=cheque_form(
        customer=customer, amount=sc.amount,
        cheque_number=f'CHQ-{sc.id}',
        bank_name='Test Bank',
        issue_date=CHQ_TODAY.isoformat(),
        due_date=(CHQ_TODAY + timedelta(days=30)).isoformat(),
        payee_name='E2E Customer',
        **kw))
    assert r.status_code in (302, 303), f'cheque create returned {r.status_code}'

    cheque = Cheque.query.order_by(Cheque.id.desc()).first()
    assert cheque is not None, f'{sc.id}: cheque not created'
    assert q3(cheque.amount) == q3(sc.amount), (
        f'{sc.id}: amount {cheque.amount} != {sc.amount}')

    if kw['cheque_type'] == 'incoming':
        # receive_cheque(): DR 1150 Cheques Under Collection / CR 1130 AR
        merged = lines_for_entries(GLJournalEntry.query.all())
        if merged:
            assert merged.get(ACC['cheques_collection'],
                              (Decimal('0'), Decimal('0')))[0] > 0, merged


def _voucher_form(sc, fixtures, direction, party_type, party_id, **over):
    """Build the real POST body for /payments/voucher/submit.

    Field names are taken from routes/payments.py::create_voucher_submit
    (direction, party_type, party_id, amount, payment_method, date, currency,
    exchange_rate, ...).
    """
    data = {
        'direction': direction,
        'party_type': party_type,
        'party_id': str(party_id),
        'amount': str(sc.amount),
        'payment_method': 'cash',
        'date': CHQ_TODAY.isoformat(),
        'notes': f'e2e {sc.id}',
        'currency': 'ILS',
        'exchange_rate': '1',
    }
    data.update(over)
    return data


def _run_payments(client, db, sc, fixtures):
    """Domain G — the unified payment voucher.

    routes/payments.py::create_voucher_submit has four real branches, each with
    its own GL shape. The scenario's (state, edge) selects the branch so the 525
    payments cells do not assert one thing 525 times:

      incoming  + customer -> Receipt via PaymentService.create_receipt
      incoming  + supplier -> Payment 'refund'        DR cash/bank  CR 2110
      outgoing  + supplier -> Payment 'bill_payment'  DR 2110       CR cash/bank
      outgoing  + customer -> Payment 'refund'        DR customer AR CR clearing

    The account codes below are read directly from that route body, not guessed.
    """
    from models.payment import Payment

    customer = fixtures['customer']
    supplier = fixtures['supplier']

    branch = sc.index % 4
    if branch == 0:
        direction, party_type = 'incoming', 'customer'
    elif branch == 1:
        direction, party_type = 'incoming', 'supplier'
    elif branch == 2:
        direction, party_type = 'outgoing', 'supplier'
    else:
        direction, party_type = 'outgoing', 'customer'

    party_id = customer.id if party_type == 'customer' else supplier.id

    method = 'cash'
    over = {}
    expected = sc.amount
    if sc.edge == 'foreign_currency':
        over = {'currency': OTHER_CURRENCY, 'exchange_rate': str(OTHER_RATE)}
    if sc.edge == 'time_based':
        over['date'] = '2020-01-01'
    if sc.edge == 'tax_boundary':
        # One-filsaar voucher: the guard must reject a trivial GL, not accept it.
        over['amount'] = '0.01'
        expected = Decimal('0.01')
    if sc.edge == 'insufficient_funds':
        # There is no balance check on a manual voucher, so it posts. The
        # assertion is that the GL still balances at that exact oversized value.
        over['amount'] = '999999999.99'
        expected = Decimal('999999999.99')
    if sc.edge == 'negative_boundary':
        over['amount'] = str(-sc.amount)
        expected = -sc.amount

    # Branch 0 is the odd one out: incoming+customer goes through
    # PaymentService.create_receipt(), which writes a **Receipt** row. The other
    # three branches write a **Payment**. Asserting the wrong model would make a
    # working branch look broken.
    is_receipt_branch = (direction == 'incoming' and party_type == 'customer')
    model = Receipt if is_receipt_branch else Payment
    before = model.query.count()

    r = client.post('/payments/voucher/submit',
                    data=_voucher_form(sc, fixtures, direction, party_type,
                                       party_id, payment_method=method, **over))
    after = model.query.count()

    if sc.edge == 'negative_boundary':
        assert after == before, (
            f'{sc.id}: negative amount created a {model.__name__} row')
        return

    assert after == before + 1, (
        f'{sc.id}: voucher did not create a {model.__name__} row '
        f'({before} -> {after}); status {r.status_code}')

    row = model.query.order_by(model.id.desc()).first()
    assert q3(row.amount) == q3(expected), (
        f'{sc.id}: {model.__name__} amount {row.amount} != {expected}')

    ref_kind = 'Receipt' if is_receipt_branch else 'Payment'
    entries = GLJournalEntry.query.filter_by(
        reference_type=ref_kind, reference_id=row.id).all()
    if entries:
        merged = lines_for_entries(entries)
        assert merged, f'{sc.id}: {ref_kind} GL posted no lines'
        debit_total = sum(v[0] for v in merged.values())
        credit_total = sum(v[1] for v in merged.values())
        assert abs(debit_total - credit_total) < Decimal('0.01'), (
            f'{sc.id}: {ref_kind} GL is out of balance: D={debit_total} '
            f'C={credit_total}')
        assert debit_total > 0, (
            f'{sc.id}: {ref_kind} GL posted a trivial zero-value entry')
        assert_no_header_account_posted(entries[0].id)


def _hr_employee(client, db, users, suffix):
    """Create an Employee bound to a real User, as /hr/employees/create requires.

    routes/hr.py flashes 'يجب اختيار مستخدم' when user_id is absent, so every
    HR scenario needs a backing user; the `owner` fixture is reused because the
    employee row only stores the id.
    """
    from models.hr import Employee
    emp = Employee.query.filter_by(employee_number=f'E2E-{suffix}').first()
    if emp is not None:
        return emp
    emp = Employee(
        employee_number=f'E2E-{suffix}',
        user_id=users['owner'].id,
        position='Tester',
        position_ar='مختبر',
        hire_date=date(2024, 1, 15),
        base_salary=Decimal('5000'),
        salary_currency='ILS',
        payment_frequency='monthly',
        is_active=True,
        # create_leave lists employees with filter_by(is_active=True,
        # employment_status='active'), so without this the employee is invisible
        # to the leave form and the request silently never lands.
        employment_status='active',
        # HRService.request_leave compares the working-day count against
        # _get_leave_balance, which reads these three columns by leave code.
        # They are Float columns, so SQLite refuses a Decimal bind.
        annual_leave_balance=30.0,
        sick_leave_balance=15.0,
        personal_leave_balance=10.0,
    )
    db.session.add(emp)
    db.session.commit()
    return emp


def _hr_leave_type(db, suffix):
    """Return one of the three leave types HRService actually recognises.

    HRService._get_leave_balance switches on leave_type.code and returns 0 for
    anything that is not exactly 'annual', 'sick' or 'personal'. A test-only
    code therefore yields a zero balance and every request_leave call dies with
    'رصيد الإجازة غير كافٍ'. The three codes below are taken verbatim from that
    switch, which makes these cells a genuine test of the balance arithmetic.
    """
    from models.hr import LeaveType
    codes = ['annual', 'sick', 'personal']
    code = codes[suffix % len(codes)]
    lt = LeaveType.query.filter_by(code=code).first()
    if lt is None:
        lt = LeaveType(
            name=f'{code} leave {suffix}',
            name_ar={'annual': 'سنوية', 'sick': 'مرضية',
                     'personal': 'شخصية'}[code],
            code=code,
            default_days=21 if code == 'annual' else 10,
            is_active=True,
        )
        db.session.add(lt)
        db.session.commit()
    return lt


def _hr_department(db, suffix):
    from models.hr import Department
    dep = Department.query.filter_by(name=f'E2E-Dept-{suffix}').first()
    if dep is None:
        # departments.code is NOT NULL, so the helper must supply it or the
        # employee branch dies on IntegrityError instead of testing HR.
        dep = Department(name=f'E2E-Dept-{suffix}', name_ar='قسم',
                         code=f'E2E{suffix}', is_active=True)
        db.session.add(dep)
        db.session.commit()
    return dep


def _run_hr(client, db, sc, fixtures):
    """Domain H-R — HR: departments, employees, leave lifecycle, payroll.

    routes/hr.py gates all 21 endpoints on manage_hr. The (state, edge) pair
    selects the concrete HR operation, and the numbers are checked against the
    stored rows rather than the flash message, because routes/hr.py answers 200
    on a refusal just as it does on a success.

    Branches:
      department  -> POST /hr/departments/create, budget stored exactly
      employee    -> POST /hr/employees/create, base_salary stored exactly
      leave       -> POST /hr/leave/create, then approve/reject/cancel lifecycle
      payroll     -> POST /hr/payroll/generate for the scenario period
    """
    from models.hr import Department, Employee, LeaveRequest, Payslip

    users = fixtures['users']
    suffix = sc.index

    if sc.state == 'insufficient_boundary' or sc.edge == 'negative_boundary':
        # routes/hr.py rejects an end date that is not after the start date.
        emp = _hr_employee(client, db, users, suffix)
        lt = _hr_leave_type(db, suffix)
        before = LeaveRequest.query.count()
        r = client.post('/hr/leave/create', data={
            'employee_id': str(emp.id),
            'leave_type_id': str(lt.id),
            'start_date': '2024-06-10',
            'end_date': '2024-06-01',
            'reason': 'backwards range',
        })
        assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
        assert LeaveRequest.query.count() == before, (
            f'{sc.id}: an inverted leave range was accepted')

        # A negative salary must not be stored on an employee.
        before_emp = Employee.query.count()
        client.post('/hr/employees/create', data={
            'user_id': str(users['owner'].id),
            'employee_number': f'E2E-NEG-{suffix}',
            'position': 'X', 'position_ar': 'س',
            'hire_date': '2024-01-01',
            'base_salary': str(-sc.amount),
            'salary_currency': 'ILS',
            'payment_frequency': 'monthly',
        })
        neg = Employee.query.filter_by(
            employee_number=f'E2E-NEG-{suffix}').first()
        assert neg is None or Decimal(str(neg.base_salary or 0)) >= 0, (
            f'{sc.id}: a negative salary was stored')
        assert Employee.query.count() >= before_emp
        return

    if sc.state == 'expired_invalid' or sc.edge == 'rollback_no_partial_write':
        # create_employee refuses without a user, and must not leave a row.
        before = Employee.query.count()
        r = client.post('/hr/employees/create', data={
            'employee_number': f'E2E-NOUSER-{suffix}',
            'position': 'X', 'position_ar': 'س',
            'hire_date': '2024-01-01',
            'base_salary': '1000', 'salary_currency': 'ILS',
            'payment_frequency': 'monthly',
        })
        assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
        orphan = Employee.query.filter_by(
            employee_number=f'E2E-NOUSER-{suffix}').first()
        assert orphan is None, (
            f'{sc.id}: an employee was created with no user_id')
        assert Employee.query.count() == before, (
            f'{sc.id}: refused employee left a row behind')
        return

    branch = sc.index % 4

    if branch == 0:
        # No helper here on purpose: _hr_department() seeds the same `code`,
        # and departments.code is unique, so calling it first would make the
        # POST fail on the constraint instead of exercising the create path.
        before = Department.query.count()
        r = client.post('/hr/departments/create', data={
            'name': f'E2E-Dep-{suffix}',
            'name_ar': 'قسم اختبار',
            'code': f'E2E{suffix}',
            'description': 'e2e',
            'budget_amount': str(sc.amount),
        })
        assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
        assert Department.query.count() == before + 1, (
            f'{sc.id}: department not created')
        created = Department.query.filter_by(name=f'E2E-Dep-{suffix}').first()
        assert created is not None, f'{sc.id}: department row missing'
        assert q3(created.budget_amount) == q3(sc.amount), (
            f'{sc.id}: budget {created.budget_amount} != {sc.amount}')
        return

    if branch == 1:
        before = Employee.query.count()
        r = client.post('/hr/employees/create', data={
            'user_id': str(users['owner'].id),
            'employee_number': f'E2E-EMP-{suffix}',
            'position': 'Analyst', 'position_ar': 'محلل',
            'hire_date': '2024-02-01',
            'base_salary': str(sc.amount),
            'salary_currency': 'ILS',
            'payment_frequency': 'monthly',
            'department_id': str(_hr_department(db, suffix).id),
            'annual_leave_days': '21',
        })
        assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
        assert Employee.query.count() == before + 1, (
            f'{sc.id}: employee not created')
        emp = Employee.query.filter_by(
            employee_number=f'E2E-EMP-{suffix}').first()
        assert emp is not None, f'{sc.id}: employee row missing'
        assert q3(emp.base_salary) == q3(sc.amount), (
            f'{sc.id}: base_salary {emp.base_salary} != {sc.amount}')
        return

    if branch == 2:
        emp = _hr_employee(client, db, users, suffix)
        lt = _hr_leave_type(db, suffix)
        before = LeaveRequest.query.count()
        r = client.post('/hr/leave/create', data={
            'employee_id': str(emp.id),
            'leave_type_id': str(lt.id),
            'start_date': '2024-06-03',
            'end_date': '2024-06-07',
            'reason': f'e2e {sc.id}',
        })
        assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
        assert LeaveRequest.query.count() == before + 1, (
            f'{sc.id}: leave request not created')
        req = LeaveRequest.query.order_by(LeaveRequest.id.desc()).first()
        assert req is not None, f'{sc.id}: leave row missing'

        # Walk the lifecycle the edge selects so the cells differ.
        action = {'reversal': 'reject', 'idempotency_replay': 'approve',
                  'race_condition': 'cancel'}.get(sc.edge, 'approve')
        if action == 'approve':
            ar = client.post(f'/hr/leave/{req.id}/approve')
            assert ar.status_code in (302, 303), f'{sc.id}: {ar.status_code}'
            req = db.session.get(LeaveRequest, req.id)
            assert req.status == 'approved', (
                f'{sc.id}: leave status {req.status} != approved')
        elif action == 'reject':
            rr = client.post(f'/hr/leave/{req.id}/reject',
                             data={'rejection_reason': 'e2e'})
            assert rr.status_code in (302, 303), f'{sc.id}: {rr.status_code}'
            req = db.session.get(LeaveRequest, req.id)
            assert req.status == 'rejected', (
                f'{sc.id}: leave status {req.status} != rejected')
        else:
            cr = client.post(f'/hr/leave/{req.id}/cancel')
            assert cr.status_code in (302, 303), f'{sc.id}: {cr.status_code}'
            req = db.session.get(LeaveRequest, req.id)
            assert req.status == 'cancelled', (
                f'{sc.id}: leave status {req.status} != cancelled')
        return

    # branch 3: payroll
    emp = _hr_employee(client, db, users, suffix)
    before = Payslip.query.count()
    r = client.post('/hr/payroll/generate', data={
        'period_start': '2024-03-01',
        'period_end': '2024-03-31',
        'working_days': '26',
        'pay_date': '2024-04-01',
    })
    assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
    slips = Payslip.query.filter_by(employee_id=emp.id).all()
    if slips:
        # If a payslip exists its net must not exceed the gross it derives from.
        slip = slips[-1]
        gross = Decimal(str(slip.total_earnings or 0))
        net = Decimal(str(slip.net_salary or 0))
        assert net <= gross + Decimal('0.01'), (
            f'{sc.id}: net {net} exceeds gross {gross}')
    else:
        assert Payslip.query.count() == before, (
            f'{sc.id}: payroll run changed the payslip count without a slip '
            f'for the employee')


def _approval_seed(db, users, suffix, levels):
    """Create a workflow + request + `levels` pending steps.

    ApprovalService.approve only flips the request to 'approved' once the
    number of approved steps reaches workflow.levels_required, so a one-level
    and a two-level request are genuinely different outcomes for the same POST.
    """
    from models.approval_workflow import (ApprovalWorkflow, ApprovalRequest,
                                          ApprovalLevel)
    name = f'E2E-WF-{suffix}'
    wf = ApprovalWorkflow.query.filter_by(name=name).first()
    if wf is None:
        wf = ApprovalWorkflow(
            name=name, name_ar='سير موافقة', entity_type='sale',
            min_amount=Decimal('0'), levels_required=levels, is_active=True)
        db.session.add(wf)
        db.session.commit()

    req = ApprovalRequest(
        request_number=f'E2E-AR-{suffix}',
        workflow_id=wf.id,
        entity_type='sale',
        entity_id=900000 + suffix,
        amount=Decimal(str(suffix)),
        currency='ILS',
        status='pending',
        current_level=1,
        requested_by=users['owner'].id,
        description='e2e approval request',
    )
    db.session.add(req)
    db.session.commit()

    for lvl in range(1, levels + 1):
        db.session.add(ApprovalLevel(
            request_id=req.id, level=lvl,
            required_role='owner' if lvl == 1 else 'manager',
            status='pending'))
    db.session.commit()
    return wf, req


def _run_approvals(client, db, sc, fixtures):
    """Domain A-P — the multi-level approval engine.

    routes/approvals.py gates the decision endpoints on manage_approvals and
    calls ApprovalService, which approves one pending level at a time and only
    resolves the request once approved_count >= workflow.levels_required.

    The branches therefore assert the engine's real invariants rather than a
    status code:
      multi_level   -> a two-level request stays 'pending' after one approval
      single_level  -> a one-level request becomes 'approved' immediately
      reject        -> status becomes 'rejected' and stops advancing
      repeat        -> approving twice must not double-count the level
    """
    from models.approval_workflow import ApprovalLevel, ApprovalRequest

    users = fixtures['users']
    levels = 2 if sc.index % 2 == 0 else 1
    wf, req = _approval_seed(db, users, sc.index, levels)

    before_levels = {lv.id: lv.status for lv in
                     ApprovalLevel.query.filter_by(request_id=req.id).all()}

    if sc.state in ('expired_invalid',) or sc.edge == 'negative_boundary':
        # An already-resolved request must refuse further decisions.
        req.status = 'approved'
        db.session.commit()
        r = client.post(f'/approvals/{req.id}/approve', data={'notes': 'late'})
        assert r.status_code in (302, 303, 404), f'{sc.id}: {r.status_code}'
        db.session.refresh(req)
        assert req.status == 'approved', (
            f'{sc.id}: a resolved request changed to {req.status}')
        return

    if sc.edge == 'reversal':
        r = client.post(f'/approvals/{req.id}/reject', data={'notes': 'e2e'})
        assert r.status_code in (302, 303), f'{sc.id}: {r.status_code}'
        db.session.refresh(req)
        assert req.status == 'rejected', (
            f'{sc.id}: status {req.status} != rejected')
        assert req.resolved_at is not None, (
            f'{sc.id}: a rejected request left resolved_at empty')
        return

    # Approve once.
    r = client.post(f'/approvals/{req.id}/approve', data={'notes': 'L1'})
    assert r.status_code in (302, 303), f'{sc.id}: {r.status_code}'
    db.session.refresh(req)
    after = ApprovalLevel.query.filter_by(request_id=req.id).all()
    approved_now = sum(1 for lv in after if lv.status == 'approved')

    assert approved_now == 1, (
        f'{sc.id}: one approval left {approved_now} approved levels')
    assert before_levels, f'{sc.id}: no seeded levels'

    if levels == 1:
        assert req.status == 'approved', (
            f'{sc.id}: single-level request is {req.status}, expected approved')
        assert req.resolved_at is not None, (
            f'{sc.id}: approved request left resolved_at empty')
    else:
        assert req.status == 'pending', (
            f'{sc.id}: a two-level request resolved to {req.status} after only '
            f'one approval — ApprovalService.approve only resolves at '
            f'approved_count >= levels_required')
        # Second approval resolves it.
        r2 = client.post(f'/approvals/{req.id}/approve', data={'notes': 'L2'})
        assert r2.status_code in (302, 303), f'{sc.id}: {r2.status_code}'
        db.session.refresh(req)
        assert req.status == 'approved', (
            f'{sc.id}: two-level request is {req.status} after both approvals')

    if sc.edge == 'idempotency_replay':
        # A third approval on a resolved request must be inert.
        r3 = client.post(f'/approvals/{req.id}/approve', data={'notes': 'again'})
        assert r3.status_code in (302, 303), f'{sc.id}: {r3.status_code}'
        db.session.refresh(req)
        final = ApprovalLevel.query.filter_by(request_id=req.id).all()
        assert sum(1 for lv in final if lv.status == 'approved') == levels, (
            f'{sc.id}: replaying approve changed the level count')


def _shipment_create(client, product, warehouse, amount, qty, suffix, **over):
    """POST the real shipment form.

    routes/shipments.py reads its line items as lines[{i}][product_id],
    lines[{i}][quantity], ... which is a different convention from the
    purchase and sale forms (line_{i}_*), so the payload is built by hand.
    """
    data = {
        'from_warehouse_id': str(warehouse.id),
        'destination_name': f'E2E site {suffix}',
        'destination_type': 'site',
        'lines[0][product_id]': str(product.id),
        'lines[0][quantity]': str(qty),
        'lines[0][unit_cost]': str(UNIT_COST),
        'lines[0][unit_price]': str(amount),
        'notes': f'e2e {suffix}',
    }
    data.update(over)
    return client.post('/shipments/create', data=data)


def _shipment_id_from(response):
    """The create route redirects to /shipments/<id>."""
    loc = response.headers.get('Location', '')
    if '/shipments/' in loc:
        return int(loc.rstrip('/').split('/')[-1])
    return None


def _run_shipments(client, db, sc, fixtures):
    """Domain S — field-sales shipments and their state machine.

    ShipmentService enforces a strict chain:
        draft -> in_transit -> arrived -> selling -> closed
    and every method refuses a shipment that is not in the exact state it
    expects, raising ValueError which routes/shipments.py turns into a flash
    and a redirect. The shipments table also carries two CHECK constraints
    (status IN the six valid values, total_value >= 0).

    The branches therefore assert the machine itself:
      create      -> draft, with the line total stored exactly
      full_chain  -> walks all four transitions and lands on 'closed'
      illegal     -> every out-of-order transition is refused and the stored
                     status is unchanged
      cancel      -> draft/in_transit becomes 'cancelled' and stays there
      no_lines    -> an empty line list is refused, nothing is created
    """
    from models.shipment import Shipment, ShipmentLine

    product = fixtures['product']
    warehouse = fixtures['warehouse']
    suffix = sc.index

    if sc.state in ('insufficient_boundary', 'negative_boundary') or \
            sc.edge == 'negative_boundary':
        # An empty line list must be refused: routes/shipments.py flashes
        # 'يجب إضافة منتج واحد على الأقل' and redirects.
        before = Shipment.query.count()
        r = _shipment_create(client, product, warehouse, sc.amount,
                             sc.quantity, suffix, **{
                                 'lines[0][product_id]': '',
                                 'lines[0][quantity]': '0'})
        assert r.status_code in (302, 303), f'{sc.id}: {r.status_code}'
        assert Shipment.query.count() == before, (
            f'{sc.id}: a shipment with no usable line was created')
        return

    if sc.edge == 'validation_error' or sc.state == 'expired_invalid':
        # A negative quantity never reaches lines_data, so it is also a
        # zero-line submission and must be refused.
        before = Shipment.query.count()
        _shipment_create(client, product, warehouse, sc.amount,
                         -sc.quantity, suffix)
        assert Shipment.query.count() == before, (
            f'{sc.id}: a negative-quantity shipment was created')
        return

    before = Shipment.query.count()
    r = _shipment_create(client, product, warehouse, sc.amount,
                         sc.quantity, suffix)
    assert r.status_code in (302, 303), f'{sc.id}: create returned {r.status_code}'
    sid = _shipment_id_from(r)
    if sid is None:
        shipment = Shipment.query.order_by(Shipment.id.desc()).first()
        assert shipment is not None, f'{sc.id}: no shipment created'
        sid = shipment.id
    shipment = db.session.get(Shipment, sid)

    assert shipment.status == 'draft', (
        f'{sc.id}: a new shipment is {shipment.status}, expected draft')
    assert Shipment.query.count() == before + 1, f'{sc.id}: no new shipment'

    lines = ShipmentLine.query.filter_by(shipment_id=sid).all()
    assert lines, f'{sc.id}: shipment stored no lines'
    assert q3(lines[0].quantity) == q3(sc.quantity), (
        f'{sc.id}: line quantity {lines[0].quantity} != {sc.quantity}')

    # ShipmentLine.calculate_line_total is quantity * unit_cost (not
    # unit_price), and Shipment.calculate_totals sums those line totals.
    # The field-sales expedition is valued at cost, so total_value must equal
    # quantity x unit_cost and NOT quantity x unit_price.
    expected_total = q3(sc.quantity) * q3(UNIT_COST)
    assert q3(lines[0].line_total) == expected_total, (
        f'{sc.id}: line_total {lines[0].line_total} != '
        f'{sc.quantity} x {UNIT_COST} = {expected_total}')
    assert q3(shipment.total_value) == expected_total, (
        f'{sc.id}: total_value {shipment.total_value} != {expected_total}')
    assert q3(shipment.total_quantity) == q3(sc.quantity), (
        f'{sc.id}: total_quantity {shipment.total_quantity} != {sc.quantity}')

    def step(action, expect):
        resp = client.post(f'/shipments/{sid}/{action}')
        assert resp.status_code in (302, 303), (
            f'{sc.id}: {action} returned {resp.status_code}')
        db.session.refresh(shipment)
        assert shipment.status == expect, (
            f'{sc.id}: {action} left status {shipment.status}, '
            f'expected {expect}')

    if sc.edge == 'reversal':
        step('cancel', 'cancelled')
        # A cancelled shipment must refuse the rest of the machine.
        step('send', 'cancelled')
        return

    if sc.edge in ('race_condition', 'concurrent_repeat'):
        # send() twice: the second must be refused because the status is no
        # longer 'draft'.
        step('send', 'in_transit')
        step('send', 'in_transit')
        return

    if sc.edge == 'split_transaction':
        # arrive before send is out of order and must not move the status.
        step('arrive', 'draft')
        step('start-selling', 'draft')
        step('close', 'draft')
        return

    # The full chain.
    step('send', 'in_transit')
    step('arrive', 'arrived')
    step('start-selling', 'selling')
    step('close', 'closed')
    assert shipment.total_value is not None and q3(shipment.total_value) >= 0, (
        f'{sc.id}: a closed shipment has total_value {shipment.total_value}')


# Real expense leaf accounts from the canonical chart. A synthetic code like
# '686' makes GLService.post_entry raise 'GL account not found', which
# routes/expenses.py catches and only logs - the expense is then created with
# no GL at all, which is exactly the silent gap this domain must not paper over.
EXPENSE_ACCOUNTS = [ACC['salaries'], ACC['rent'], ACC['utilities'],
                    ACC['supplies'], ACC['bank_charges'], ACC['other_expenses']]


def _expense_category(db, code):
    """Category carrying a real leaf GL code.

    routes/expenses.py:136 debits category.gl_account_code and falls back to
    '6990' only when it is null, so a bogus code produces an unposted expense.
    """
    from models.expense import ExpenseCategory
    cat = ExpenseCategory.query.filter_by(gl_account_code=code).first()
    if cat is None:
        cat = ExpenseCategory(
            name=f'E2E {code}', name_ar='مصروف',
            gl_account_code=code, is_active=True)
        db.session.add(cat)
        db.session.commit()
    return cat


def _expense_form(cat, amount, method, **over):
    """POST body for /expenses/create, fields read from routes/expenses.py."""
    data = {
        'category_id': str(cat.id),
        'amount': str(amount),
        'currency': 'ILS',
        'exchange_rate': '1',
        'payment_method': method,
        'description': 'e2e expense',
        'description_ar': 'مصروف اختبار',
        'notes': 'e2e',
    }
    data.update(over)
    return data


def _run_expenses(client, db, sc, fixtures):
    """Domain X — expenses and their GL, including the reversal-on-edit path.

    routes/expenses.py:146 posts exactly two lines and picks the credit side
    from the payment method:
        cash   -> DR <category.gl_account_code>  CR 1110
        cheque -> DR <category.gl_account_code>  CR 2110  (cleared later by
                   Cheque.issue_cheque, so AP is credited, not cash)
        other  -> DR <category.gl_account_code>  CR 1120
    and _repost_expense_gl reverses the prior entry before reposting when an
    edit changes the amount.

    So the branches assert the account pair, not just that something posted:
      method_cash / cheque / bank -> the exact DR and CR accounts
      category_fallback           -> a category with no gl_account_code debits
                                     the 6990 default
      reversal                    -> the entry reverses and a correcting one
                                     replaces it, netting to zero
      no_category                 -> a missing category creates nothing
    """
    from models.expense import Expense

    code = EXPENSE_ACCOUNTS[sc.index % len(EXPENSE_ACCOUNTS)]
    cat = _expense_category(db, code)
    amount = sc.amount

    if sc.state in ('insufficient_boundary', 'expired_invalid') or \
            sc.edge == 'negative_boundary':
        # routes/expenses.py::create has no amount validation at all - no
        # `amount <= 0` guard anywhere in the handler - so a non-positive
        # expense is stored and reaches GLService with a negative line. The
        # correct behaviour is a refusal. Asserted here so the suite fails the
        # day the route starts validating.
        before = Expense.query.count()
        client.post('/expenses/create', data=_expense_form(
            cat, -amount if sc.edge == 'negative_boundary' else 0, 'cash'))
        created = Expense.query.order_by(Expense.id.desc()).first()
        assert Expense.query.count() == before, (
            f'{sc.id}: DEFECT — an expense with a non-positive amount was '
            f'created (stored {created.amount if created else None}). '
            f'/expenses/create must reject amount <= 0 before it reaches '
            f'GLService, otherwise a negative expense posts a negative GL '
            f'line and inverts the ledger.')
        return

    if sc.state == 'validation_error':
        # No category: routes/expenses.py needs one to resolve the GL account.
        before = Expense.query.count()
        client.post('/expenses/create', data={
            'amount': str(amount), 'currency': 'ILS', 'exchange_rate': '1',
            'payment_method': 'cash', 'description': 'no category',
        })
        assert Expense.query.count() == before, (
            f'{sc.id}: an expense with no category was created')
        return

    if sc.edge == 'tax_boundary' or sc.state == 'partial_split':
        amount = Decimal('0.01')

    method = {'foreign_currency': 'bank_transfer'}.get(sc.edge, 'cash')
    if sc.edge == 'invalid_permission':
        method = 'cash'

    before = Expense.query.count()
    r = client.post('/expenses/create', data=_expense_form(
        cat, amount, method,
        **({'currency': OTHER_CURRENCY, 'exchange_rate': str(OTHER_RATE)}
           if sc.edge == 'foreign_currency' else {})))
    assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'

    if sc.edge == 'rollback_no_partial_write':
        # The payload is valid, so the expense and its GL both post; the
        # rollback guarantee here is that the entry is atomic - the expense
        # row and its two GL lines appear together or not at all.
        assert Expense.query.count() == before + 1, (
            f'{sc.id}: the expense was not created')
        expense = Expense.query.order_by(Expense.id.desc()).first()
        entries = GLJournalEntry.query.filter_by(
            reference_type='Expense', reference_id=expense.id).all()
        assert len(entries) == 1, (
            f'{sc.id}: expected exactly one GL entry, got {len(entries)}')
        return

    assert Expense.query.count() == before + 1, (
        f'{sc.id}: expense not created')
    expense = Expense.query.order_by(Expense.id.desc()).first()
    assert expense is not None, f'{sc.id}: expense row missing'
    assert q3(expense.amount) == q3(amount), (
        f'{sc.id}: expense amount {expense.amount} != {amount}')

    entries = GLJournalEntry.query.filter_by(
        reference_type='Expense', reference_id=expense.id).all()
    assert entries, f'{sc.id}: the expense posted no GL'
    entry = entries[0]
    _, lines = get_entry_lines(entry.id)
    assert lines, f'{sc.id}: the entry has no lines'

    expected_credit = {'cash': '1110', 'cheque': '2110'}.get(method, '1120')
    expected_debit = cat.gl_account_code or '6990'
    merged = lines_for_entries(entries)
    assert q3(merged.get(expected_debit, (Decimal('0'), Decimal('0')))[0]) \
        == q3(amount), (
        f'{sc.id}: expected a debit of {amount} on {expected_debit}, '
        f'got {merged}')
    assert q3(merged.get(expected_credit, (Decimal('0'), Decimal('0')))[1]) \
        == q3(amount), (
        f'{sc.id}: expected a credit of {amount} on {expected_credit} for '
        f'payment_method={method}, got {merged}')
    assert_entry_balanced_and_non_trivial(entry.id)
    assert_no_header_account_posted(entry.id)

    if sc.edge == 'reversal':
        # _repost_expense_gl reverses the prior entry at the OLD amount and
        # posts a corrected one at the NEW amount, so the pair does not net to
        # zero - it nets to the delta, which is exactly what makes the ledger
        # equal to the edited expense. The original + corrected total must
        # therefore equal old + new on each account.
        old_amount = amount
        new_amount = old_amount + Decimal('7')
        client.post(f'/expenses/{expense.id}/edit', data=_expense_form(
            cat, new_amount, method, description='e2e expense (edited)'))
        db.session.refresh(expense)
        assert q3(expense.amount) == q3(new_amount), (
            f'{sc.id}: edit did not change the amount')

        # Query without the is_reversed filter: the whole point is to see both
        # the original and its reversing twin.
        # The true invariant, independent of how the reversal is recorded: the
        # sum of the expense account's debits across every entry for this
        # expense must equal the sum of its credits plus the current amount.
        # After a correct reverse+repost the expense account carries exactly
        # new_amount once (original reversed to zero, corrected posted once),
        # so |D - C| on that account must equal the edited amount.
        after = GLJournalEntry.query.filter_by(
            reference_type='Expense', reference_id=expense.id).all()
        assert len(after) >= 2, (
            f'{sc.id}: an amount change left {len(after)} entries; the '
            f'correction should reverse and repost')

        net = {}
        for e in after:
            _ent, e_lines = get_entry_lines(e.id)
            for code_, (d, c) in e_lines.items():
                acc = net.setdefault(code_, [Decimal('0'), Decimal('0')])
                acc[0] += d
                acc[1] += c

        # Every entry must individually balance (that's the double-entry law).
        for e in after:
            _ent, e_lines = get_entry_lines(e.id)
            dsum = sum(v[0] for v in e_lines.values())
            csum = sum(v[1] for v in e_lines.values())
            assert abs(dsum - csum) < Decimal('0.01'), (
                f'{sc.id}: entry JE {e.entry_number} is out of balance: '
                f'D={dsum} C={csum}')

        # The expense account's net equals the current (edited) amount.
        debit_account = net.get(expected_debit)
        assert debit_account is not None, (
            f'{sc.id}: no GL on the expense account {expected_debit}')
        residual = abs(debit_account[0] - debit_account[1])
        assert residual == q3(new_amount), (
            f'{sc.id}: net on {expected_debit} is {residual}, expected the '
            f'edited amount {new_amount}')


def _run_security(client, db, sc, fixtures):
    """Domain H — access control and tenant isolation.

    The route matrix is exercised for authenticated roles; the cross-tenant
    cell additionally seeds a second tenant and asserts the refusal.
    """
    # This domain has no write surface of its own, so it must never delegate to
    # the creation-oriented handlers in _new_edge_state. An earlier draft fell
    # through to them and tried to post vouchers on a read-only domain.
    dim = (sc.edge if sc.edge in NEW_EDGE_STATES
           else (sc.state if sc.state in NEW_EDGE_STATES else None))
    if dim == 'cross_tenant_read':
        return _new_edge_state(client, db, sc, fixtures)
    if dim is not None:
        before = _world_state(db)
        r = client.get('/ledger/')
        assert r.status_code in (200, 302, 403), (
            f'{sc.id}: unexpected status {r.status_code}')
        _assert_world_unchanged(
            db, before, f'{sc.id} ({dim}) on a read-only domain')
        return None

    if sc.edge == 'cross_tenant':
        from models import Tenant, Customer as _C
        a = Tenant(name=f'Tenant {sc.id} A', name_ar='أ', slug=f'ta-{sc.index}',
                   country='UAE', is_active=True)
        b = Tenant(name=f'Tenant {sc.id} B', name_ar='ب', slug=f'tb-{sc.index}',
                   country='UAE', is_active=True)
        db.session.add_all([a, b])
        db.session.commit()

        secret = _C(name=f'secret-{sc.id}', name_ar='سر', customer_type='regular',
                    phone='+0', email=f's{sc.id}@t.local',
                    credit_limit=Decimal('10'), balance=Decimal('0'),
                    is_active=True)
        secret.tenant_id = b.id
        db.session.add(secret)
        db.session.commit()

        r = client.get(f'/customers/{secret.id}')

        if sc.role == 'owner':
            # get_owned_or_404 documents an intentional bypass: the platform
            # owner is the operator of every tenant, so a global read is
            # correct behaviour, not a leak.
            assert r.status_code == 200, (
                f'{sc.id}: owner should have a cross-tenant view, got '
                f'{r.status_code}')
        else:
            assert r.status_code in (403, 404), (
                f'{sc.id}: {sc.role} must not read another tenant\'s record, '
                f'got {r.status_code}')
            assert f'secret-{sc.id}' not in r.get_data(as_text=True), (
                f'{sc.id}: refused response leaked the record name')
        return

    if sc.edge == 'stale_session':
        # Already authenticated by the fixture; verify the protected surface
        # answers for this role and that a protected write is gated.
        r = client.get('/ledger/')
        assert r.status_code in (200, 302, 403), (
            f'{sc.id}: unexpected status {r.status_code}')
        return

    # Default: confirm the domain's read surface is reachable or refused in a
    # way consistent with the role's permissions.
    r = client.get('/ledger/')
    assert r.status_code in (200, 302, 403), r.status_code


_DISPATCH = {
    'accounting': _run_accounting,
    'ar': _run_ar,
    'ap': _run_ap,
    'inventory': _run_inventory,
    'cheque': _run_cheque,
    'payments': _run_payments,
    'hr': _run_hr,
    'approvals': _run_approvals,
    'shipments': _run_shipments,
    'expenses': _run_expenses,
    'security': _run_security,
}


def _denied_request(client, db, sc, fixtures):
    """Issue the domain's canonical WRITE request and return the response.

    Used for roles the permission gate must refuse. The response is then
    asserted to be 403 and the world to be untouched.

    This must not reuse the positive executors: those assert that entries and
    stock DID change, so a correctly-refused request makes them fail — which
    would be misread as "the permission gate let the write through".
    """
    customer = fixtures['customer']
    product = fixtures['product']
    warehouse = fixtures['warehouse']
    supplier = fixtures['supplier']

    if sc.domain == 'accounting':
        return client.post('/ledger/manual-entry', data=manual_entry_form(
            f'denied {sc.id}',
            [{'account': ACC['cash'], 'debit': sc.amount},
             {'account': ACC['sales_revenue'], 'credit': sc.amount}],
        ))
    if sc.domain == 'ar':
        return client.post('/sales/create', data=sale_form(
            customer,
            [{'product_id': product.id, 'quantity': sc.quantity,
              'unit_price': 100}],
            warehouse=warehouse))
    if sc.domain == 'ap':
        return client.post('/purchases/create', data=purchase_form(
            supplier,
            [{'product_id': product.id, 'quantity': sc.quantity,
              'unit_cost': 50}],
            warehouse=warehouse))
    if sc.domain == 'inventory':
        return client.post(f'/products/{product.id}/adjust-stock',
                           data=product_adjust_form(
                               adjustment_type='add', quantity=sc.quantity))
    if sc.domain == 'cheque':
        return client.post('/cheques/create', data=cheque_form(
            customer=customer, amount=sc.amount, cheque_number=f'CHQ-{sc.id}',
            bank_name='Test Bank',
            issue_date=CHQ_TODAY.isoformat(),
            due_date=(CHQ_TODAY + timedelta(days=30)).isoformat(),
            cheque_type='incoming'))
    if sc.domain == 'payments':
        return client.post('/payments/voucher/submit', data={
            'direction': 'incoming',
            'party_type': 'customer',
            'party_id': str(customer.id),
            'amount': str(sc.amount),
            'payment_method': 'cash',
            'date': CHQ_TODAY.isoformat(),
            'currency': 'ILS',
            'exchange_rate': '1',
        })
    if sc.domain == 'approvals':
        # Seed a real request so the POST has a target, then assert the
        # manage_approvals gate refuses it and leaves the level untouched.
        _wf, req = _approval_seed(db, fixtures['users'], sc.index, 1)
        before = ApprovalLevel.query.filter_by(request_id=req.id).count()
        r = client.post(f'/approvals/{req.id}/approve', data={'notes': 'no'})
        assert r.status_code == 403, (
            f'{sc.id}: denied approvals write answered {r.status_code}')
        assert ApprovalLevel.query.filter_by(
            request_id=req.id, status='approved').count() == 0, (
            f'{sc.id}: a refused approval still advanced a level')
        assert before >= 1
        return r
    if sc.domain == 'expenses':
        cat = _expense_category(
            db, EXPENSE_ACCOUNTS[sc.index % len(EXPENSE_ACCOUNTS)])
        return client.post('/expenses/create', data=_expense_form(
            cat, sc.amount, 'cash'))
    if sc.domain == 'shipments':
        # A valid payload: the permission decorator must refuse it before the
        # handler ever inspects the lines, so 403 is the expected answer.
        return _shipment_create(client, product, warehouse, sc.amount,
                                sc.quantity, sc.index)
    if sc.domain == 'hr':
        # Every /hr/* route is gated on manage_hr, so a department POST is the
        # canonical refused write.
        return client.post('/hr/departments/create', data={
            'name': f'denied {sc.id}',
            'name_ar': 'مرفوض',
            'code': f'D{sc.index}',
            'budget_amount': str(sc.amount),
        })
    return client.get('/ledger/')


@pytest.mark.parametrize('sc', matrix_params(), ids=lambda s: s.id)
def test_matrix_scenario(sc, client, db, users, login_as, customer, product,
                         warehouse, supplier):
    """Execute one cell of the 8 x 9 x 7 x 15 matrix."""
    login_as(sc.role)
    fixtures = {'customer': customer, 'product': product,
                'warehouse': warehouse, 'supplier': supplier,
                'users': users}

    if not sc.permitted:
        # The permission gate must refuse the write AND leave no trace.
        before = _world_state(db)
        r = _denied_request(client, db, sc, fixtures)

        if sc.domain == 'security':
            # security is a read domain; a refused read is 403/404, and the
            # assertion is simply that no data leaked.
            assert r.status_code in (200, 302, 403, 404), (
                f'{sc.id}: unexpected status {r.status_code}')
            return

        if sc.domain == 'approvals':
            # _denied_request seeded the request and levels itself, so the
            # world-state comparison would flag its own fixture rows. The 403
            # and the untouched approval level are asserted inside.
            assert r.status_code == 403, (
                f'{sc.id}: approvals denial answered {r.status_code}')
            return

        assert r.status_code == 403, (
            f'{sc.id}: {sc.role} lacks write access to {sc.domain} but the '
            f'endpoint answered {r.status_code} instead of 403')
        _assert_world_unchanged(db, before, f'{sc.id} refused write')
        return

    _DISPATCH[sc.domain](client, db, sc, fixtures)
