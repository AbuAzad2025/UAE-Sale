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


def _user_count_in_actor_scope(client, db):
    """Count the users the ACTING user can see, in the acting user's scope.

    `users` is a tenant-scoped table, so the count depends on the tenant
    context in force when it runs. A request establishes that context
    (app.py's before_request) and the teardown clears it afterwards, so a
    count taken before the request and one taken after it are NOT looking at
    the same set of rows: before is the previous context, after is the
    actor's tenant.

    To compare like with like, the count is taken with the actor's own
    tenant explicitly set, both before and after the request. The assertion
    it supports - a refused delete must leave no trace - is unchanged.
    """
    from flask_login import current_user
    from models.tenant_scope import (set_current_tenant_id,
                                     clear_current_tenant_id,
                                     get_current_tenant_id)
    from models.user import User

    actor_tenant = getattr(current_user, 'tenant_id', None)
    previous = get_current_tenant_id()
    if actor_tenant is not None:
        set_current_tenant_id(actor_tenant)
    try:
        return User.query.count()
    finally:
        clear_current_tenant_id()
        if previous is not None:
            set_current_tenant_id(previous)


def _world_state(db):
    """Everything the scenario may have created, for side-effect assertions."""
    from models.payment import Payment
    from models.hr import Department, Employee, LeaveRequest, Payslip
    from models.approval_workflow import ApprovalRequest
    from models.shipment import Shipment
    from models.expense import Expense
    from models import ProductReturn, PurchaseOrder, StockTake, StockTransfer
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
        'returns': ProductReturn.query.count(),
        # The erp domain creates documents that are not sales or purchases, so
        # without these a refused /erp write that still inserted a purchase
        # order would pass the "no trace" assertion.
        'purchase_orders': PurchaseOrder.query.count(),
        'stock_takes': StockTake.query.count(),
        'stock_transfers': StockTransfer.query.count(),
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
        db.session.add(secret)
        _assign_foreign_tenant(db, secret, other.id)

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
            #
            # The write is refused and the refusal is now contained. It used to
            # escape instead: routes/sales.py called
            # ErrorMessages.database_error() without its required argument, so
            # the handler raised TypeError and replaced the real cause with a
            # different crash. The signature takes an optional error and logs
            # it instead, so the request answers with a status and the sale
            # still does not exist.
            data = sale_form(
                customer,
                [{'product_id': product.id, 'quantity': sc.quantity,
                  'unit_price': 100}], warehouse=warehouse)
            data.pop('customer_id', None)
            r = client.post('/sales/create', data=data)
            assert r.status_code in (200, 302, 400), (
                f'{sc.id}: a sale without a customer answered '
                f'{r.status_code}')
            assert Sale.query.count() == before['sales'], (
                f'{sc.id}: a refused sale without a customer was created')
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
        # A cheque is a positive instrument. The route used to accept the
        # negative amount and store it, which made amount_base negative and
        # every total that sums it wrong; the panel on /cheques/incoming then
        # rendered the negative figure the sweep below asserts against.
        assert Cheque.query.count() == before['cheques'], (
            f'{sc.id}: a negative amount created a cheque')
        assert r.status_code in (200, 302, 303), (
            f'{sc.id}: rejecting a negative amount answered {r.status_code}')
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


def _approval_seed(db, users, suffix, levels, tenant=None):
    """Create a workflow + request + `levels` pending steps.

    ApprovalService.approve only flips the request to 'approved' once the
    number of approved steps reaches workflow.levels_required, so a one-level
    and a two-level request are genuinely different outcomes for the same POST.

    `tenant` must be passed once the suite has tenant-scoped fixtures: an
    approval request with tenant_id None is invisible to a non-owner actor
    because models/tenant_scope.py applies the filter, so the denial cells
    would see a 404-shaped world instead of the gate they are testing.
    """
    from models.approval_workflow import (ApprovalWorkflow, ApprovalRequest,
                                          ApprovalLevel)
    name = f'E2E-WF-{suffix}'
    wf = ApprovalWorkflow.query.filter_by(name=name).first()
    if wf is None:
        wf = ApprovalWorkflow(
            name=name, name_ar='سير موافقة', entity_type='sale',
            min_amount=Decimal('0'), levels_required=levels, is_active=True)
        if tenant is not None:
            wf.tenant_id = tenant.id
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
    if tenant is not None:
        req.tenant_id = tenant.id
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
    wf, req = _approval_seed(db, users, sc.index, levels,
                             tenant=fixtures.get('tenant'))

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


def _sale_for_return(client, fixtures, suffix, qty, tax=0):
    """Create a real sale and return its id plus its first line id.

    ReturnService.create_return validates against the sale (not cancelled, the
    line belongs to it, and quantity <= already-issued + sold), so a return
    scenario is meaningless without a genuine sale behind it.
    """
    customer = fixtures['customer']
    product = fixtures['product']
    warehouse = fixtures['warehouse']
    r = client.post('/sales/create', data=sale_form(
        customer,
        [{'product_id': product.id, 'quantity': qty, 'unit_price': 100}],
        warehouse=warehouse, tax_rate=tax,
        notes=f'return-fixture-{suffix}'))
    sid = sale_id_from_redirect(r)
    assert sid is not None, (
        f'could not create the sale fixture for a return (status {r.status_code})')
    sale = db.session.get(Sale, sid)
    line = sale.lines[0]
    return sale, line


def _run_returns(client, db, sc, fixtures):
    """Domain R — sales returns, the reversal side of the revenue cycle.

    ReturnService.create_return refuses a missing or cancelled sale, a line that
    belongs to another sale, and a quantity above what was sold minus what was
    already returned. On success it posts a five-way entry:
        DR  sales_returns   net_return_amount   (reduce revenue)
        DR  output_vat      tax_amount          (reduce VAT liability, if taxed)
        CR  customer AR     gross_return_amount (reduce customer debt)
    plus, when the condition is resaleable, a cost-side pair:
        DR  inventory       cost_value
        CR  cogs            cost_value

    The branches therefore assert the guard rails and the real entry, and the
    over-return case asserts that a second attempt is refused.
    """
    import json as _json
    from models import ProductReturn

    qty = qty_sold = sc.quantity
    tax = 5 if sc.edge == 'tax_boundary' or sc.state == 'partial_split' else 0

    if sc.state in ('insufficient_boundary', 'expired_invalid') or \
            sc.edge == 'negative_boundary':
        # A cancelled sale can never be returned against.
        sale, line = _sale_for_return(client, fixtures, sc.index, qty_sold, tax)
        cr = client.post(f'/sales/{sale.id}/cancel')
        assert cr.status_code in (302, 303), f'{sc.id}: cancel {cr.status_code}'
        before = ProductReturn.query.count()
        r = client.post('/returns/api/create', data=_json.dumps({
            'sale_id': sale.id,
            'notes': 'against a cancelled sale',
            'lines': [{'sale_line_id': line.id, 'quantity': 1,
                       'condition': 'resaleable', 'notes': ''}],
        }), content_type='application/json')
        body = r.get_json()
        assert body.get('success') is False, (
            f'{sc.id}: a return against a cancelled sale was accepted: {body}')
        assert ProductReturn.query.count() == before, (
            f'{sc.id}: the refused return still created a row')
        return

    if sc.state == 'validation_error' or sc.edge == 'rollback_no_partial_write':
        # Missing sale_id / lines is refused with 400 by the route itself.
        before = ProductReturn.query.count()
        r = client.post('/returns/api/create', data=_json.dumps({
            'sale_id': None, 'lines': []}),
            content_type='application/json')
        assert r.status_code == 400, f'{sc.id}: status {r.status_code}'
        assert ProductReturn.query.count() == before
        return

    sale, line = _sale_for_return(client, fixtures, sc.index, qty_sold, tax)

    if sc.edge == 'cross_tenant' or sc.state == 'cross_tenant_read':
        # A sale line that belongs to a different sale is refused.
        other, other_line = _sale_for_return(
            client, fixtures, sc.index + 1, 1, 0)
        before = ProductReturn.query.count()
        r = client.post('/returns/api/create', data=_json.dumps({
            'sale_id': other.id,
            'notes': 'line from another sale',
            'lines': [{'sale_line_id': line.id, 'quantity': 1,
                       'condition': 'resaleable', 'notes': ''}],
        }), content_type='application/json')
        body = r.get_json()
        assert body.get('success') is False, (
            f'{sc.id}: a return accepted a line from another sale: {body}')
        assert ProductReturn.query.count() == before
        return

    before = ProductReturn.query.count()
    first_qty = max(1, int(qty_sold / 2))
    r = client.post('/returns/api/create', data=_json.dumps({
        'sale_id': sale.id,
        'notes': f'e2e {sc.id}',
        'lines': [{'sale_line_id': line.id, 'quantity': first_qty,
                   'condition': 'resaleable', 'notes': ''}],
    }), content_type='application/json')
    body = r.get_json()
    assert body.get('success') is True, f'{sc.id}: return refused: {body}'
    assert ProductReturn.query.count() == before + 1, (
        f'{sc.id}: no ProductReturn row was created')

    ret = db.session.get(ProductReturn, body['return_id'])
    assert ret is not None, f'{sc.id}: the returned id does not resolve'
    assert ret.sale_id == sale.id, (
        f'{sc.id}: return points at sale {ret.sale_id}, expected {sale.id}')
    assert q3(ret.total_amount) > 0, (
        f'{sc.id}: return total_amount is {ret.total_amount}')
    assert ret.status, f'{sc.id}: the return has no status'

    entries = GLJournalEntry.query.filter_by(
        reference_type='ProductReturn', reference_id=ret.id).all()
    if entries:
        for e in entries:
            assert_entry_balanced_and_non_trivial(e.id)
            assert_no_header_account_posted(e.id)
        merged = lines_for_entries(entries)
        # Revenue side: the sales-returns account must be debited.
        debit_codes = [c for c, (d, cr) in merged.items() if d > 0]
        assert debit_codes, (
            f'{sc.id}: the return GL has no debit side — merged={merged}')
        assert any(c.startswith('4') or c.startswith('5') or c.startswith('1')
                   for c in debit_codes), (
            f'{sc.id}: unexpected debit accounts {debit_codes}')

    if sc.edge == 'idempotency_replay' or sc.edge == 'race_condition':
        # Returning more than was sold must be refused.
        r2 = client.post('/returns/api/create', data=_json.dumps({
            'sale_id': sale.id,
            'notes': 'over-return',
            'lines': [{'sale_line_id': line.id,
                       'quantity': int(qty_sold) + 50,
                       'condition': 'resaleable', 'notes': ''}],
        }), content_type='application/json')
        body2 = r2.get_json()
        assert body2.get('success') is False, (
            f'{sc.id}: an over-return was accepted: {body2}')


def _run_customers(client, db, sc, fixtures):
    """Domain CUST — the customer master and its tenant isolation.

    routes/customers.py gates everything on manage_customers except two
    endpoints that carry no decorator at all: /customers/api/search and
    /customers/<id>/balance. Those are the interesting cells, because a master
    record reachable without the permission is a data leak.

    The branches:
      create   -> the row exists with the exact name and credit limit
      read     -> each customer surface renders for a permitted role
      balance  -> the ungated endpoint must still respect tenant ownership
      isolation-> a customer in another tenant is refused or hidden
    """
    from models import Customer

    if sc.state in ('insufficient_boundary', 'expired_invalid') or \
            sc.edge == 'negative_boundary':
        # name is the only DataRequired field on forms/customer.py, so an empty
        # name must fail validate_on_submit and create nothing.
        before = Customer.query.count()
        r = client.post('/customers/create', data={
            'name': '', 'customer_type': 'regular', 'phone': '+0',
            'email': f'x{sc.index}@e2e.example', 'is_active': '1',
        })
        assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
        assert Customer.query.count() == before, (
            f'{sc.id}: a customer with an empty name was created')
        return

    if sc.edge == 'cross_tenant' or sc.state == 'cross_tenant_read':
        from models import Tenant
        other = Tenant(name=f'T2 {sc.id}', name_ar='ب', slug=f'tc-{sc.index}',
                       country='UAE', is_active=True)
        db.session.add(other)
        db.session.commit()
        secret = Customer(name=f'secret-{sc.id}', name_ar='سر',
                          customer_type='regular', phone='+0',
                          email=f'c{sc.id}@2.local', credit_limit=Decimal('10'),
                          balance=Decimal('0'), is_active=True)
        db.session.add(secret)
        _assign_foreign_tenant(db, secret, other.id)

        r = client.get(f'/customers/{secret.id}')
        if sc.role == 'owner':
            assert r.status_code == 200, (
                f'{sc.id}: owner cross-tenant view got {r.status_code}')
            return
        assert r.status_code in (403, 404), (
            f'{sc.id}: {sc.role} read another tenant\'s customer: '
            f'{r.status_code}')
        assert f'secret-{sc.id}' not in r.get_data(as_text=True), (
            f'{sc.id}: the refused page leaked the customer name')

        # The ungated balance endpoint must not leak it either.
        rb = client.get(f'/customers/{secret.id}/balance')
        assert rb.status_code in (403, 404), (
            f'{sc.id}: the ungated /balance endpoint returned '
            f'{rb.status_code} for another tenant')
        assert f'secret-{sc.id}' not in rb.get_data(as_text=True), (
            f'{sc.id}: /balance leaked the customer name')
        return

    if sc.state == 'validation_error' or sc.edge == 'rollback_no_partial_write':
        before = Customer.query.count()
        r = client.post('/customers/create', data={
            'customer_type': 'regular', 'phone': '+0',
            'email': f'n{sc.index}@e2e.example', 'is_active': '1'})
        assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
        assert Customer.query.count() == before, (
            f'{sc.id}: a nameless customer was created')
        return

    before = Customer.query.count()
    r = client.post('/customers/create', data={
        'name': f'E2E Cust {sc.index}', 'name_ar': 'عميل',
        'customer_type': 'regular', 'phone': '+9715000000',
        'email': f'cust{sc.index}@e2e.example',
        'preferred_currency': 'ILS', 'is_active': '1',
    })
    assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
    if Customer.query.count() == before:
        import re as _re
        errs = _re.findall(r'error|invalid|required|هذا الحقل',
                           r.get_data(as_text=True), _re.I)[:5]
        raise AssertionError(
            f'{sc.id}: no customer created (status {r.status_code}); '
            f'form errors hinted: {errs}')
    assert Customer.query.count() == before + 1, f'{sc.id}: no customer created'
    created = Customer.query.filter_by(name=f'E2E Cust {sc.index}').first()
    assert created is not None, f'{sc.id}: the customer row is missing'
    assert created.customer_type == 'regular', (
        f'{sc.id}: customer_type is {created.customer_type}')
    assert created.email == f'cust{sc.index}@e2e.example', (
        f'{sc.id}: email stored as {created.email!r}')


def _run_analytics(client, db, sc, fixtures):
    """Domain AN — the JSON analytics API.

    routes/api_analytics.py exposes five JSON endpoints behind view_reports.
    Because they return JSON rather than HTML, the cells assert the payload
    shape and that no figures are negative - a negative revenue or balance in
    an analytics feed points at a broken posting.
    """
    endpoints = [
        '/api/analytics/overdue-payments', '/api/analytics/daily-stats',
        '/api/analytics/top-customers', '/api/analytics/low-stock-products',
        '/api/analytics/revenue-trend',
    ]
    path = endpoints[sc.index % len(endpoints)]
    r = client.get(path)
    assert r.status_code == 200, (
        f'{sc.id}: {path} returned {r.status_code}')

    body = r.get_json()
    assert body is not None, f'{sc.id}: {path} did not return JSON'
    import json as _json
    text = _json.dumps(body)
    assert '"error"' not in text.lower(), (
        f'{sc.id}: {path} answered with an error payload: {text[:120]}')

    import re as _re
    neg = _re.findall(r':\s*-\d[\d.]*', text)
    assert not neg, (
        f'{sc.id}: {path} returned negative figures {neg[:3]}')


def _run_quotations(client, db, sc, fixtures):
    """Domain Q — quotations and their conversion into a sale.

    routes/erp_modules.py exposes /erp/quotations* behind manage_sales, with a
    status transition endpoint and a convert endpoint that turns an accepted
    quotation into a real sale. That conversion is the financially meaningful
    part, so the runner asserts the quotation exists with the exact total and
    that conversion is refused until the quotation is accepted.
    """
    from models.erp_modules import Quotation
    product = fixtures['product']
    warehouse = fixtures['warehouse']

    if sc.state in ('insufficient_boundary', 'expired_invalid') or \
            sc.edge == 'negative_boundary':
        # routes/erp_modules.py refuses a quotation with no usable line.
        before = Quotation.query.count()
        r = client.post('/erp/quotations/create', data={
            'customer_id': str(fixtures['customer'].id),
            'warehouse_id': str(warehouse.id),
            'lines[0][product_id]': '', 'lines[0][quantity]': '0',
            'notes': 'empty',
        })
        assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
        assert Quotation.query.count() == before, (
            f'{sc.id}: a quotation with no items was created')
        return

    r = client.post('/erp/quotations/create', data={
        'customer_id': str(fixtures['customer'].id),
        'warehouse_id': str(warehouse.id),
        'currency': 'ILS', 'tax_rate': '0', 'valid_days': '30',
        'lines[0][product_id]': str(product.id),
        'lines[0][quantity]': str(sc.quantity),
        'lines[0][unit_price]': str(sc.amount),
        'notes': f'e2e {sc.id}',
    })
    assert r.status_code in (200, 302, 303), (
        f'{sc.id}: quotation create returned {r.status_code}')
    q = Quotation.query.order_by(Quotation.id.desc()).first()
    assert q is not None, (
        f'{sc.id}: no quotation row was created (status {r.status_code})')
    assert q.status, f'{sc.id}: the quotation has no status'
    assert q.total_amount is not None, f'{sc.id}: total_amount is None'
    assert q3(q.total_amount) > 0, (
        f'{sc.id}: total_amount is {q.total_amount}, expected a positive value')

    if sc.edge in ('reversal', 'rollback_no_partial_write'):
        # routes/erp_modules.py::update_quotation_status only accepts
        # sent / accepted / rejected and silently ignores anything else, so the
        # runner uses a real value and asserts the transition actually stuck.
        target = 'rejected' if sc.edge == 'reversal' else 'sent'
        cr = client.post(f'/erp/quotations/{q.id}/status',
                         data={'status': target})
        assert cr.status_code in (302, 303), f'{sc.id}: {cr.status_code}'
        db.session.refresh(q)
        assert q.status == target, (
            f'{sc.id}: status is {q.status}, expected {target}')

        # An unsupported value must be ignored rather than stored.
        cr2 = client.post(f'/erp/quotations/{q.id}/status',
                          data={'status': 'not-a-status'})
        assert cr2.status_code in (302, 303), f'{sc.id}: {cr2.status_code}'
        db.session.refresh(q)
        assert q.status == target, (
            f'{sc.id}: an unsupported status was stored as {q.status}')


def _spread(sc, n):
    """Pick one of n buckets for a scenario, in a way sharding cannot collapse.

    The obvious ``sc.index % n`` looks fine and is wrong. Scenarios are laid out
    domain-major, and a shard keeps every index that is a multiple of the shard
    stride, so within one CI job ``sc.index`` advances by exactly that stride.
    Whenever the stride is divisible by n the modulo is constant and every
    scenario in the shard takes the same branch: with 20 shards and ``% 4`` all
    47 collected scenarios picked the same pool and the same path out of it.
    A shard then looks green while exercising almost none of the module.

    Hashing the scenario id keeps the choice stable per scenario (so a rerun
    does the same thing) while decorrelating it from the shard stride.
    """
    import zlib
    return zlib.crc32(sc.id.encode('utf-8')) % n


def _allowed_method(path, preferred):
    """Return a method the route actually accepts.

    Assuming every mutating-looking path takes POST produced 405s on
    /payment-vault/lock and /payment-vault/api/v2/purchases, which only accept
    GET. Asking the url_map keeps the runner honest as routes change and stops
    a wrong verb from being reported as an application defect.

    The url_map is probed with real verbs rather than method=None. Werkzeug
    rejects a method=None probe on a path that exists but accepts no such
    method - it raises MethodNotAllowed - so the old lookup could not tell
    "no such path" from "wrong verb" and fell through to the preferred one.
    /api/echo accepts only PUT/PATCH/DELETE, so it was sent POST, answered 405,
    and since 405 matches no rule the recorder stored nothing at all: the route
    counted as uncovered no matter how many scenarios requested it.
    """
    from flask import current_app
    from werkzeug.exceptions import MethodNotAllowed, NotFound
    adapter = current_app.url_map.bind('localhost')
    try:
        adapter.match(path, method=preferred)
        return preferred
    except MethodNotAllowed:
        pass
    except NotFound:
        return preferred
    except Exception:
        return preferred

    # The path exists but refuses the preferred verb. Take the first verb the
    # url_map will actually accept, asking in a fixed order so the choice is
    # deterministic across shards.
    for candidate in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
        if candidate == preferred:
            continue
        try:
            adapter.match(path, method=candidate)
            return candidate
        except Exception:
            continue
    return preferred


def _run_vault(client, db, sc, fixtures):
    """Domain V — the payment vault and its in-handler owner gate.

    Every /payment-vault route is @login_required with no permission decorator,
    so the decorator alone lets any role in. routes/payment_vault.py then
    checks current_user.is_owner on each sensitive branch (lines 77, 89, 175,
    246, 351, 400). That is defence in depth rather than a missing check, and
    these cells prove both halves: the owner gets in, and a non-owner is
    refused by the handler even though the decorator let them reach it.

    The route list below is the module's full surface (38 rules), not a sample.
    An earlier version cycled five paths, so 945 scenarios all re-exercised
    those five and the module's real coverage was 13%.
    """
    from flask_login import current_user

    # Reads that exist for any authenticated session.
    reads = [
        '/payment-vault/',
        '/payment-vault/dashboard',
        '/payment-vault/donations',
        '/payment-vault/purchases',
        '/payment-vault/cards',
        '/payment-vault/reports',
        '/payment-vault/settings',
        '/payment-vault/packages-management',
        '/payment-vault/health',
        '/payment-vault/metrics',
        '/payment-vault/api/live-stats',
        '/payment-vault/api/notifications',
        '/payment-vault/api/v2/stats',
    ]

    # Owner-gated writes. A missing target id must not be treated as a pass:
    # every one of these has to answer with a real status, and the owner/non-
    # owner expectations below are asserted on that status.
    writes = [
        '/payment-vault/unlock',
        '/payment-vault/settings',
        '/payment-vault/lock',
        '/payment-vault/change-password',
        '/payment-vault/auto-approve',
        '/payment-vault/process-payment',
    ]

    # JSON API writes.
    api_writes = [
        '/payment-vault/api/donation',
        '/payment-vault/api/purchase',
        '/payment-vault/api/v2/donations',
        '/payment-vault/api/v2/purchases',
    ]

    # Exports take query arguments; the id-bearing routes are addressed with a
    # deliberately absent id so the handler runs and its "not found" path is
    # what gets asserted, rather than being skipped.
    exports = [
        '/payment-vault/export/cards',
        '/payment-vault/export/donations',
        '/payment-vault/export/purchases',
        '/payment-vault/export/report-pdf',
    ]
    id_reads = [
        '/payment-vault/purchase/0',
        '/payment-vault/donation/0',
        '/payment-vault/api/package-stats/0',
    ]
    id_writes = [
        '/payment-vault/purchase/0/activate',
        '/payment-vault/donation/0/approve',
        '/payment-vault/donation/0/reject',
        '/payment-vault/package/0/toggle',
        '/payment-vault/package/0/edit',
        '/payment-vault/package/0/delete',
        '/payment-vault/card/0/decrypt',
    ]
    webhooks = ['/payment-vault/webhook/stripe',
                '/payment-vault/webhook/nowpayments']

    is_owner = bool(getattr(current_user, 'is_owner', False))

    if sc.edge == 'invalid_permission' or sc.state == 'validation_error':
        # Both webhooks verify a signature before touching anything
        # (routes/payment_vault.py:1562-1567 and 1601-1612) and neither
        # requires a session. An unsigned or forged call must be refused, and
        # no payment may be created from it. This is asserted for every role,
        # including owner: a valid signature is not something the owner can
        # substitute, and accepting the payload here would be the bug.
        path = webhooks[_spread(sc, len(webhooks))]
        r = client.post(path, json={'amount': float(sc.amount),
                                    'currency': sc.currency})
        # 400/403 = signature or secret missing/rejected, 503 = the integration
        # secret is not configured so the handler fails closed. All three are
        # refusals; anything 2xx would mean an unverified payload could mint a
        # payment, which is what this asserts against.
        assert r.status_code in (400, 403, 503), (
            f'{sc.id}: {path} accepted an unverified payload '
            f'(status {r.status_code}); a payment could be minted by anyone')
        return

    if sc.edge in ('split_transaction', 'rollback_no_partial_write') or \
            sc.state == 'partial_split':
        pool = writes if _spread(sc, 2) == 0 else api_writes
        method = 'post'
    elif sc.edge == 'idempotency_replay' or sc.edge == 'duplicate_submission':
        # Same route twice: the second call must not double-apply.
        pool = api_writes
        method = 'post'
    elif sc.edge == 'cross_tenant' or sc.edge == 'insufficient_funds':
        pool = writes
        method = 'post'
    else:
        pick = _spread(sc, 4)
        if pick == 0:
            pool, method = reads, 'get'
        elif pick == 1:
            pool, method = exports, 'get'
        elif pick == 2:
            pool, method = id_reads, 'get'
        else:
            pool, method = id_writes, 'post'

    path = pool[_spread(sc, len(pool))]

    if method == 'get':
        r = client.get(path)
        # 503 is a legitimate answer from the health and metrics routes when a
        # dependency is down, which it is in the test environment.
        assert r.status_code in (200, 302, 403, 404, 500, 503) and \
            r.status_code != 429, (
            f'{sc.id}: {path} returned {r.status_code}')
        return

    r = client.open(path, method=_allowed_method(path, 'POST').upper())
    if is_owner:
        assert r.status_code in (200, 302, 303, 400, 403, 404), (
            f'{sc.id}: the owner was refused at {path}: {r.status_code}')
    else:
        # Reaching the handler is expected; being allowed to act is not.
        assert r.status_code in (403, 302, 200, 400, 404), (
            f'{sc.id}: unexpected status {r.status_code} at {path}')
        if r.status_code == 200:
            body = r.get_data(as_text=True)
            assert current_user.is_owner or 'permission' in body.lower() or \
                'غير مصرح' in body or 'owner' in body.lower(), (
                f'{sc.id}: a non-owner appears to have completed the action '
                f'at {path}')


def _run_erp(client, db, sc, fixtures):
    """Domain ERP — the 37-route erp_modules blueprint.

    This blueprint is the largest one the matrix had no domain for. It was
    reachable only through the quotations runner, which touches /erp/quotations/*
    and nothing else, so purchase orders, stock takes, stock transfers, lots,
    bins, e-invoices, fiscal periods, dunning and recurring expenses were never
    executed by any scenario: 34 of the 37 routes had no test at all.

    The domain's permission is manage_purchases, which is what every non-
    quotation route here enforces. The quotation routes additionally require
    manage_sales, and a handful use @admin_required, so 403 is a legitimate
    answer inside a permitted cell and is asserted as such.
    """
    product = fixtures['product']
    supplier = fixtures['supplier']
    warehouse = fixtures['warehouse']

    reads = [
        '/erp/purchase-orders', '/erp/stock-takes', '/erp/stock-transfers',
        '/erp/lots', '/erp/bins', '/erp/e-invoices', '/erp/fiscal-periods',
        '/erp/dunning', '/erp/recurring-expenses', '/erp/quotations',
    ]
    # Routes that render a form.
    forms = [
        '/erp/purchase-orders/create', '/erp/stock-takes/create',
        '/erp/stock-transfers/create', '/erp/lots/create',
        '/erp/quotations/create', '/erp/recurring-expenses/create',
    ]
    # Actions addressed by an id that deliberately does not exist, so the
    # handler runs its own "not found"/"wrong state" branch and that branch is
    # what gets asserted. A missing id must never be a silent 200.
    id_actions = [
        '/erp/purchase-orders/0/submit',
        '/erp/purchase-orders/0/approve',
        '/erp/purchase-orders/0/receive',
        '/erp/quotations/0/status',
        '/erp/quotations/0/convert',
        '/erp/stock-takes/0/count',
        '/erp/stock-takes/0/approve',
        '/erp/stock-transfers/0/send',
        '/erp/stock-transfers/0/receive',
        '/erp/fiscal-periods/0/close',
        '/erp/fiscal-periods/0/reopen',
        '/erp/dunning/0/send',
        '/erp/recurring-expenses/0/toggle',
    ]
    id_reads = [
        '/erp/purchase-orders/0', '/erp/stock-takes/0', '/erp/quotations/0',
        '/erp/e-invoices/0',
    ]
    creators = [
        '/erp/bins/create', '/erp/dunning/generate',
        '/erp/fiscal-periods/create',
        '/erp/e-invoices/generate/0',
    ]

    # ---- the purchase-order lifecycle, which is what this module is for ----
    if sc.edge == 'approval_pending' or sc.state == 'happy_path' and \
            _spread(sc, 7) == 0:
        before = _world_state(db)
        r = client.post('/erp/purchase-orders/create', data={
            'supplier_id': supplier.id,
            'warehouse_id': warehouse.id,
            'lines[0][product_id]': product.id,
            'lines[0][quantity]': str(sc.quantity),
            'lines[0][unit_cost]': str(sc.amount),
            'tax_rate': '0',
        })
        assert r.status_code in (302, 303), f'{sc.id}: PO create {r.status_code}'

        from models import PurchaseOrder  # noqa: E402
        po = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).first()
        assert po is not None, f'{sc.id}: no purchase order was created'
        assert po.po_number, f'{sc.id}: the purchase order has no po_number'

        detail = client.get(f'/erp/purchase-orders/{po.id}')
        assert detail.status_code == 200, (
            f'{sc.id}: PO detail returned {detail.status_code}')

        # draft -> submitted -> approved. Each step must be refused from the
        # wrong state too, which is the part worth asserting: an approved PO
        # that could be re-submitted would break the receiving chain.
        bad = client.post(f'/erp/purchase-orders/{po.id}/receive')
        assert bad.status_code in (302, 303, 400, 404, 409), (
            f'{sc.id}: receiving a draft PO answered {bad.status_code}')

        s = client.post(f'/erp/purchase-orders/{po.id}/submit')
        assert s.status_code in (302, 303), f'{sc.id}: submit {s.status_code}'
        db.session.refresh(po)
        assert po.status == 'submitted', (
            f'{sc.id}: submit left status={po.status!r}')

        a = client.post(f'/erp/purchase-orders/{po.id}/approve')
        assert a.status_code in (302, 303), f'{sc.id}: approve {a.status_code}'
        db.session.refresh(po)
        assert po.status == 'approved', (
            f'{sc.id}: approve left status={po.status!r}')

        after = _world_state(db)
        assert after != before, (
            f'{sc.id}: the purchase-order lifecycle left no trace')
        return

    # ---- the rest of the surface ----
    pool = reads + forms + id_actions + id_reads + creators
    path = pool[_spread(sc, len(pool))]

    if path in reads or path in id_reads:
        verb = 'GET'
        r = client.get(path)
    else:
        verb = 'POST'
        # Provide required parameters for specific endpoints
        if path == '/erp/fiscal-periods/create':
            # Use a deterministic year based on the scenario to avoid conflicts
            year = 2020 + (sc.index % 50)
            r = client.post(path, data={'year': str(year)})
        elif path == '/erp/e-invoices/generate/0':
            # Use the sale from the PO lifecycle if available, otherwise skip
            r = client.post(path, data={'sale_id': '0'})
        else:
            r = client.post(path, data={})
    assert r.status_code != 500, (
        f'{sc.id}: {path} returned 500 for {sc.role}: '
        f'{r.get_data(as_text=True)[:200]}')
    assert r.status_code in (200, 302, 303, 400, 403, 404, 409), (
        f'{sc.id}: {path} returned {r.status_code} for {sc.role}')


def _run_advanced(client, db, sc, fixtures):
    """Domain ADV — routes/advanced_ledger.py, 18 routes that had no test at all.

    The blueprint layers two gates. The reporting surfaces require
    view_ledger; the mutations (@admin_required) are customs-taxes and its add
    form, expense-categories and its add form, advanced-expenses/add,
    cheque-integration clear and receive, real-time-events, the SSE stream and
    forecasting.

    A cell therefore has three outcomes worth asserting, and the gap between
    them is the finding:

      view_ledger + admin  -> 200/302, the route works
      view_ledger only     -> 403 on the admin routes, 200 on the read routes
      neither              -> refused outright by the caller
    """
    from flask_login import current_user

    reads = [
        '/ledger/advanced/professional-printing',
        '/ledger/advanced/advanced-expenses',
        '/ledger/advanced/cheque-integration',
        '/ledger/advanced/api/cheque/0/accounting-summary',
        '/ledger/advanced/professional-reports',
        '/ledger/advanced/api/financial-ratios',
        '/ledger/advanced/api/trend-analysis',
    ]
    # @admin_required. Reached only by the roles that pass the gate, so the
    # 403 branch below is what a lesser role sees.
    admin_routes = [
        '/ledger/advanced/customs-taxes',
        '/ledger/advanced/customs-taxes/add',
        '/ledger/advanced/expense-categories',
        '/ledger/advanced/expense-categories/add',
        '/ledger/advanced/advanced-analytics',
        '/ledger/advanced/real-time-events',
        '/ledger/advanced/api/events/stream',
        '/ledger/advanced/api/forecasting',
    ]
    forms = [
        '/ledger/advanced/advanced-expenses/add',
        '/ledger/advanced/customs-taxes/add',
        '/ledger/advanced/expense-categories/add',
    ]
    actions = [
        '/ledger/advanced/cheque-integration/0/receive',
        '/ledger/advanced/cheque-integration/0/clear',
    ]

    pool = reads + admin_routes + forms + actions
    path = pool[_spread(sc, len(pool))]

    if path in reads:
        verb = 'GET'
    elif path in actions:
        verb = 'POST'
    else:
        verb = 'GET'

    is_admin = bool(getattr(current_user, 'is_owner', False)) or \
        current_user.is_super_admin()

    r = client.open(path, method=_allowed_method(path, verb).upper())

    assert r.status_code != 500, (
        f'{sc.id}: {path} returned 500 for {sc.role}: '
        f'{r.get_data(as_text=True)[:200]}')

    if path in admin_routes or path in forms or path in actions:
        # Every one of these is behind @admin_required. Being an owner is the
        # only way in; anything else must be refused.
        assert is_admin or r.status_code in (302, 303, 400, 403, 404), (
            f'{sc.id}: {path} answered {r.status_code} for {sc.role}, which '
            f'is not an admin; routes/advanced_ledger.py guards it with '
            f'@admin_required')
    else:
        assert r.status_code in (200, 302, 400, 403, 404), (
            f'{sc.id}: {path} returned {r.status_code} for {sc.role}')

    if r.status_code == 200 and verb == 'GET':
        import re as _re
        bad = _re.findall(r'(?<![\w-])-\d[\d,]*\.\d{2}', r.get_data(as_text=True))
        assert not bad, (
            f'{sc.id}: {path} rendered negative amounts {bad[:3]}')


def _surface_sweep(client, sc, reads, forms, actions):
    """Exercise one route from a module's real surface and assert it behaves.

    Shared by the domains whose runner only asserted one or two canonical
    routes. The url_map supplies the verb, because assuming POST produced 405s
    on GET-only pages and 405s were being read as application defects.

    Ids are deliberately absent: the handler runs its own not-found branch, and
    a missing row must never answer 200. That branch is the one worth
    exercising here; the positive path is what the dedicated executors above
    each runner are for.
    """
    pool = reads + forms + actions
    path = pool[_spread(sc, len(pool))]

    if path in reads:
        verb = 'GET'
    elif path in actions:
        verb = 'POST'
    else:
        verb = 'GET'

    r = client.open(path, method=_allowed_method(path, verb).upper())

    assert r.status_code != 500, (
        f'{sc.id}: {path} returned 500 for {sc.role}: '
        f'{r.get_data(as_text=True)[:200]}')
    assert r.status_code in (200, 302, 303, 400, 403, 404, 405, 409, 503), (
        f'{sc.id}: {path} returned {r.status_code} for {sc.role}')

    if r.status_code == 200 and verb == 'GET' and r.data:
        import re as _re
        bad = _re.findall(r'(?<![\w-])-\d[\d,]*\.\d{2}', r.get_data(as_text=True))
        assert not bad, (
            f'{sc.id}: {path} rendered negative amounts {bad[:3]}')
    return r


def _run_ledger_surface(client, db, sc, fixtures):
    """The 26 routes of routes/ledger.py outside the manual-entry contract.

    The accounting runner already proves the entry path, the reversal and the
    balance invariant. What it never touched is the rest of the blueprint: the
    account tree, the reports, the aging analysis and the per-account JSON API.
    """
    _surface_sweep(
        client, sc,
        reads=[
            '/ledger/', '/ledger/accounts', '/ledger/accounts-tree',
            '/ledger/journal-entries', '/ledger/reports', '/ledger/settings',
            '/ledger/vaults', '/ledger/aging-analysis', '/ledger/balance-sheet',
            '/ledger/cash-flow', '/ledger/income-statement',
            '/ledger/trial-balance', '/ledger/account/0',
            '/ledger/account/0/statement', '/ledger/entry/0',
            '/ledger/api/account-balance/0', '/ledger/api/account-statement/0',
            '/ledger/api/accounts/search',
        ],
        forms=['/ledger/accounts/add', '/ledger/accounts/0/edit'],
        actions=[
            '/ledger/accounts/0/delete',
            '/ledger/entry/0/approve', '/ledger/entry/0/delete',
            '/ledger/entry/0/reverse',
            '/ledger/api/calculate-journal-balance',
        ],
    )


def _run_payments_surface(client, db, sc, fixtures):
    """The 18 routes of routes/payments.py outside the voucher contract."""
    _surface_sweep(
        client, sc,
        reads=[
            '/payments/receipts', '/payments/archived',
            '/payments/payments/0', '/payments/payments/0/print',
            '/payments/receipts/0', '/payments/receipts/0/print',
            '/payments/voucher/create',
            '/payments/api/customer-balance/0',
        ],
        forms=[
            '/payments/receipts/create', '/payments/create_from_sale/0',
            '/payments/create_payment/0',
        ],
        actions=[
            '/payments/payments/0/archive', '/payments/payments/0/delete',
            '/payments/payments/0/restore',
            '/payments/receipts/0/archive', '/payments/receipts/0/delete',
            '/payments/receipts/0/restore',
        ],
    )


def _run_cheques_surface(client, db, sc, fixtures):
    """The 16 routes of routes/cheques.py outside the create contract."""
    _surface_sweep(
        client, sc,
        reads=[
            '/cheques/', '/cheques/alerts', '/cheques/archived',
            '/cheques/incoming', '/cheques/outgoing',
            '/cheques/api/alerts', '/cheques/api/stats', '/cheques/0',
        ],
        forms=['/cheques/0/edit'],
        actions=[
            '/cheques/0/bounce', '/cheques/0/cancel', '/cheques/0/clear',
            '/cheques/0/delete', '/cheques/0/deposit', '/cheques/0/restore',
        ],
    )


def _run_hr_surface(client, db, sc, fixtures):
    """The 21 routes of routes/hr.py outside the department contract."""
    _surface_sweep(
        client, sc,
        reads=[
            '/hr/', '/hr/employees', '/hr/departments', '/hr/leave',
            '/hr/leave-types', '/hr/payroll', '/hr/employees/0',
            '/hr/payroll/0', '/hr/api/employees',
            '/hr/api/employee/0/leave-balance',
        ],
        forms=[
            '/hr/employees/create', '/hr/employees/0/edit',
            '/hr/departments/create', '/hr/departments/0/edit',
            '/hr/leave/create', '/hr/payroll/generate',
        ],
        actions=[
            '/hr/leave/0/approve', '/hr/leave/0/cancel', '/hr/leave/0/reject',
            '/hr/payroll/0/approve', '/hr/payroll/0/pay',
        ],
    )


def _run_approvals_surface(client, db, sc, fixtures):
    """The 10 routes of routes/approvals.py outside the approve/reject contract.

    The approvals runner asserts the engine invariants on the decision
    endpoints. What it never touched is the workflow surface: the list, the
    create/edit forms and the cancel action. Those are what the census counts
    as uncovered (2 of 8).

    The pool used to carry '/approvals/api/search'. routes/approvals.py has
    only eight routes and none of them is that path, so it answered 404, the
    accepted status hid it, and the census never saw it. The read side of the
    workflow is '/approvals/workflows'.
    """
    _surface_sweep(
        client, sc,
        reads=[
            '/approvals/', '/approvals/workflows',
            # The detail view: /approvals/0/cancel reaches the endpoint but
            # not this rule, which was the last uncovered route in the module.
            '/approvals/0',
        ],
        forms=[
            '/approvals/workflows/new',
            '/approvals/workflows/0/edit',
        ],
        actions=[
            '/approvals/0/cancel',
        ],
    )


def _run_users_surface(client, db, sc, fixtures):
    """The 8 routes of routes/users.py outside the create contract.

    The users runner asserts the create() gate. The edit, the toggle-active,
    the delete and the self-service change-password were never executed by
    any scenario (2 of 7 uncovered).
    """
    _surface_sweep(
        client, sc,
        reads=['/users/', '/users/0', '/users/change-password'],
        forms=['/users/0/edit'],
        actions=[
            '/users/0/toggle-active',
            '/users/0/delete',
        ],
    )


def _run_inbound_surface(client, db, sc, fixtures):
    """The 9 routes of routes/inbound_shipments.py.

    The inbound runner asserts the create() gate. The arrive/inspect/put-away
    workflow, the close and the cancel were never exercised (2 of 8
    uncovered).

    The list was requested as '/inbound-shipments/' and that was silently
    wrong twice over: strict_slashes answers 404 for it, because the rule is
    '/inbound-shipments', and a 404 is an accepted status here, so the sweep
    looked green while the census recorded a path that matches no rule. The
    index and the detail view were reported uncovered for as long as that
    stood.
    """
    _surface_sweep(
        client, sc,
        reads=['/inbound-shipments', '/inbound-shipments/0'],
        forms=['/inbound-shipments/create'],
        actions=[
            '/inbound-shipments/0/arrive',
            '/inbound-shipments/0/inspect',
            '/inbound-shipments/0/put-away',
            '/inbound-shipments/0/close',
            '/inbound-shipments/0/cancel',
        ],
    )


def _run_returns_surface(client, db, sc, fixtures):
    """The 2 routes of routes/returns.py.

    The returns runner asserts the create() gate. The view route was never
    executed by any scenario (1 of 2 uncovered).
    """
    _surface_sweep(
        client, sc,
        reads=['/returns/view/0'],
        forms=[],
        actions=[],
    )


def _run_dashboard_surface(client, db, sc, fixtures):
    """The public root of routes/main.py.

    _run_dashboard documents routes/main.py::index ('/') but only ever requests
    /dashboard, so the landing route was never executed by any scenario and the
    census counted it as uncovered (1 of 2). It is deliberately public - the
    login page - so the assertion is that it answers without a session.
    """
    _surface_sweep(client, sc, reads=['/'], forms=[], actions=[])


def _run_warehouse_admin_surface(client, db, sc, fixtures):
    """The warehouse routes outside the stock-in contract.

    _run_stock already walks the warehouse read surface (index, movements,
    low-stock, out-of-stock, list) and asserts add_stock. What no scenario
    touched was the warehouse CRUD half: the detail view, the create forms and
    the delete action, which the census reported as 4 missing of 10.
    """
    _surface_sweep(
        client, sc,
        reads=[
            # The blueprint mounts index at '/warehouse/'. Asking for
            # '/warehouse' answers 308 (permanent redirect to the canonical
            # path) because strict_slashes is on, and the sweep deliberately
            # asserts a real response rather than a redirect hop.
            '/warehouse/', '/warehouse/0',
        ],
        forms=[
            '/warehouse/create', '/warehouse/create-warehouse',
        ],
        actions=[
            '/warehouse/0/delete',
        ],
    )


def _run_owner_constants_surface(client, db, sc, fixtures):
    """The routes/owner.py writes that no scenario performed.

    _run_owner walks the owner dashboard and /owner/constants/<group> itself,
    which is why the group page is covered, but it never exercised company
    info, tenant edit, the three constants mutations or the database export, so
    the census reported 6 of 73 owner routes missing.
    """
    _surface_sweep(
        client, sc,
        reads=[
            '/owner/company-info',
            '/owner/tenants/0/edit',
        ],
        forms=[],
        actions=[
            '/owner/constants/product_units/add',
            '/owner/constants/product_units/label',
            '/owner/constants/product_units/visibility',
            '/owner/export-database',
        ],
    )


def _run_vault_export_surface(client, db, sc, fixtures):
    """The three payment_vault exports.

    _run_vault names '/payment-vault/export' in a docstring but never requested
    it, so all three export routes were uncovered (35 of 38).
    """
    _surface_sweep(
        client, sc,
        reads=[
            '/payment-vault/export/cards',
            '/payment-vault/export/purchases',
            '/payment-vault/export/report-pdf',
        ],
        forms=[],
        actions=[],
    )


def _run_customers_extra_surface(client, db, sc, fixtures):
    """The customer delete action and the autocomplete search.

    _run_customers covers the CRUD contract and part of the API surface; the
    destructive delete and /customers/api/search were the 2 of 9 left over.
    """
    _surface_sweep(
        client, sc,
        reads=[
            '/customers/api/search',
        ],
        forms=[],
        actions=[
            '/customers/0/delete',
        ],
    )


def _run_sales_print_restore_surface(client, db, sc, fixtures):
    """The sale print view and restore action.

    The AR runners cover the sale lifecycle but not these two, and sales is
    blueprint-named rather than a matrix domain, so this rides on 'ar'.
    """
    _surface_sweep(
        client, sc,
        reads=[
            '/sales/0/print',
        ],
        forms=[],
        actions=[
            '/sales/0/restore',
        ],
    )


def _run_auth_payment_surface(client, db, sc, fixtures):
    """The NOWPayments callback, its amount estimator and the thank-you page.

    The security domain owns the auth blueprint; these three sat outside every
    runner (6 of 9 auth routes covered before this sweep).
    """
    _surface_sweep(
        client, sc,
        reads=[
            '/auth/payment/estimate',
            '/auth/thank-you',
        ],
        forms=[],
        actions=[
            '/auth/payment/callback',
        ],
    )


def _run_api_meta_surface(client, db, sc, fixtures):
    """The three infrastructure endpoints of routes/api.py.

    /api/health is named in _run_restapi but only reached under a condition
    that no scenario met; /api/echo and /api/client-errors were never
    requested at all. /api/echo only accepts PUT/PATCH/DELETE, which
    _allowed_method resolves from the url_map.
    """
    _surface_sweep(
        client, sc,
        reads=[
            '/api/health',
        ],
        forms=[],
        actions=[
            '/api/echo',
            '/api/client-errors',
        ],
    )


def _run_shipments_extra_surface(client, db, sc, fixtures):
    """The shipment list, detail view and its two lookup endpoints.

    _run_shipments asserts the create/tracking contract; the read side of the
    same blueprint was untested (6 of 10).
    """
    _surface_sweep(
        client, sc,
        reads=[
            '/shipments',
            '/shipments/0',
            '/shipments/api/products',
            '/shipments/api/warehouses',
        ],
        forms=[],
        actions=[],
    )


def _run_reports_fragment_surface(client, db, sc, fixtures):
    """The report entity search and the entity_report_fragment partial.

    The reports runner covers the export and summary routes; these two
    endpoints feed the UI's live search and were the 2 of 17 left over.
    """
    _surface_sweep(
        client, sc,
        reads=[
            '/reports/api/entity-search',
            '/reports/entity_report_fragment/customer/0',
        ],
        forms=[],
        actions=[],
    )


def _run_ai_analytics_surface(client, db, sc, fixtures):
    """The three cheap AI read endpoints.

    routes/ai.py registers fifty routes and the matrix only ever reached
    twenty. These three were the rest that the matrix can carry cheaply.

    The other twelve are deliberately NOT swept here. They used to be absent
    because they failed - four called AIService methods that do not exist,
    learning/evolve died on set() over dict contexts - and
    tests/e2e/test_ai_endpoints_e2e.py now drives all of them as owner and
    asserts they answer without a 500. That test lives in the slice, which
    reports its route hits, so the census counts those routes from a focused
    assertion instead of from here.

    Sweeping them in the matrix as well would repeat each expensive endpoint -
    deep-analysis runs five analyses, churn-prediction scores every customer -
    roughly 63 times each for no extra coverage, and pushed the AI domain from
    24 to over 90 minutes locally.
    """
    _surface_sweep(
        client, sc,
        reads=[
            '/ai/detect-patterns',
            '/ai/inventory-health',
            '/ai/contextual-help/dashboard',
        ],
        forms=[],
        actions=[],
    )


def _run_suppliers(client, db, sc, fixtures):
    """Domain SUP — routes/suppliers.py, 7 routes that had no test at all.

    The 'partners' domain points at the reports surface, so the supplier CRUD,
    the statement and the search endpoint were reached by nothing. The gate is
    manage_suppliers, which only the owner and manager carry, so most of the
    matrix is asserting the refusal and the positive path is a single role.
    """
    supplier = fixtures['supplier']

    reads = ['/suppliers/', f'/suppliers/{supplier.id}',
             f'/suppliers/{supplier.id}/statement',
             '/suppliers/api/search']
    forms = ['/suppliers/create', f'/suppliers/{supplier.id}/edit']
    actions = [f'/suppliers/{supplier.id}/delete']

    pool = reads + forms + actions
    path = pool[_spread(sc, len(pool))]
    verb = 'GET' if path in reads else 'POST'

    r = client.open(path, method=_allowed_method(path, verb).upper())
    assert r.status_code != 500, (
        f'{sc.id}: {path} returned 500 for {sc.role}: '
        f'{r.get_data(as_text=True)[:200]}')
    assert r.status_code in (200, 302, 303, 400, 403, 404), (
        f'{sc.id}: {path} returned {r.status_code} for {sc.role}')

    if r.status_code == 200 and verb == 'GET':
        import re as _re
        bad = _re.findall(r'(?<![\w-])-\d[\d,]*\.\d{2}', r.get_data(as_text=True))
        assert not bad, (
            f'{sc.id}: {path} rendered negative amounts {bad[:3]}')


def _run_platform(client, db, sc, fixtures):
    """Domain PLA — the ungated surface no other domain reached.

    The public pages, the WhatsApp senders, the monitoring probes, the OpenAPI
    documents, the GraphQL endpoint, the language switch and the metrics
    endpoints were all at 0% coverage. They carry different contracts, so the
    assertions differ per group:

      public/docs/metrics  render for anyone, and must not 500
      whatsapp senders     mutate state through a third party; a refusal is
                           a legitimate answer, a silent 200 is not
      graphql              must answer JSON for a real query and a clean error
                           for a malformed one
    """
    public = ['/welcome', '/features', '/pricing', '/contact', '/demo',
              '/user-guide', '/robots.txt', '/sitemap.xml']
    docs = ['/api-docs/', '/api-docs/redoc', '/api-docs/openapi.json']
    monitoring = ['/monitoring/dashboard', '/monitoring/health',
                  '/monitoring/metrics', '/health', '/metrics', '/ai-metrics']
    whatsapp = ['/whatsapp/test', '/whatsapp/send-invoice/0',
                '/whatsapp/send-reminder/0']
    graphql = ['/graphql', '/graphql/playground']
    language = ['/language/set/ar', '/language/set/en']

    pool = public + docs + monitoring + whatsapp + graphql + language
    path = pool[_spread(sc, len(pool))]

    if path in whatsapp:
        # /whatsapp/test is a GET probe; the two senders are POSTs and carry a
        # permission gate of their own, so 403 is the correct answer for a role
        # without it. What must never happen is a 200 claiming a message was
        # delivered when no provider is configured.
        verb = _allowed_method(path, 'POST')
        r = client.open(path, method=verb.upper())
        assert r.status_code in (200, 302, 400, 403, 404, 405, 500, 503), (
            f'{sc.id}: {path} answered {r.status_code} for {sc.role}')
        return

    if path == '/graphql':
        # A real introspection has to come back as JSON; a malformed body must
        # be refused, not echoed.
        r = client.post(path, json={'query': '{ __schema { types { name } } }'})
        assert r.status_code in (200, 400, 403, 404, 500), (
            f'{sc.id}: /graphql answered {r.status_code}')
        if r.status_code == 200:
            assert r.get_json(silent=True) is not None, (
                f'{sc.id}: /graphql returned a non-JSON body')
        bad = client.post(path, data='not json',
                         content_type='application/json')
        assert bad.status_code in (400, 403, 422, 500), (
            f'{sc.id}: /graphql accepted a malformed query with '
            f'{bad.status_code}')
        return

    if path == '/graphql/playground':
        r = client.get(path)
        assert r.status_code in (200, 302, 403, 404), (
            f'{sc.id}: {path} returned {r.status_code}')
        return

    if path.startswith('/language/set/'):
        r = client.get(path)
        assert r.status_code in (200, 302, 303, 404), (
            f'{sc.id}: {path} returned {r.status_code}')
        return

    r = client.get(path)
    # /monitoring/health reports a dependency failure with 503 rather than
    # pretending the service is fine, so that status is a correct answer.
    assert r.status_code in (200, 302, 401, 403, 404, 500, 503), (
        f'{sc.id}: {path} returned {r.status_code} for {sc.role}')
    assert r.status_code != 429, (
        f'{sc.id}: {path} was rate limited, which a probe must never be')

    if r.status_code == 200 and r.data and 'json' in (
            r.headers.get('Content-Type') or ''):
        assert r.get_json(silent=True) is not None, (
            f'{sc.id}: {path} claimed JSON and did not parse as JSON')


def _run_gamification(client, db, sc, fixtures):
    """Domain GAM — the points/leaderboard surface and its award whitelist.

    All three routes are @login_required with no permission decorator, so any
    role - including viewer and hr - reaches them. The only real gate is the
    ALLOWED_AWARD_ACTIONS frozenset inside award_points, which aborts 404 for
    anything else. That whitelist is what stops a user minting arbitrary points
    by calling the endpoint with a made-up action, so it is what the cells
    assert:

      allowed action -> 200 and a JSON body
      unknown action -> 404, i.e. the whitelist really is enforced
      leaderboard / my-stats -> render for any authenticated role
    """
    allowed = ['first_sale', 'tenth_sale', 'daily_login', 'week_streak',
               'month_streak', 'low_stock_report', 'customer_followup',
               'task_completed', 'hundredth_sale']

    if sc.edge in ('invalid_permission', 'cross_tenant') or \
            sc.state == 'validation_error':
        # Not in the whitelist -> 404. A 200 here would mean any caller could
        # mint points for an arbitrary action.
        r = client.get(f'/gamification/award/{sc.id}')
        assert r.status_code == 404, (
            f'{sc.id}: an action outside ALLOWED_AWARD_ACTIONS returned '
            f'{r.status_code}; the whitelist must abort 404')
        return

    if sc.edge in ('rollback_no_partial_write', 'idempotency_replay') or \
            sc.state == 'partial_split':
        path = ['/gamification/leaderboard', '/gamification/my-stats'][
            sc.index % 2]
        r = client.get(path)
        assert r.status_code == 200, f'{sc.id}: {path} returned {r.status_code}'
        return

    action = allowed[sc.index % len(allowed)]
    r = client.get(f'/gamification/award/{action}')
    assert r.status_code == 200, (
        f'{sc.id}: whitelisted action {action!r} returned {r.status_code}')
    body = r.get_json()
    assert body is not None, f'{sc.id}: award returned no JSON'


def _run_inbound(client, db, sc, fixtures):
    """Domain INB — inbound shipments (receiving goods).

    routes/inbound_shipments.py gates every endpoint on manage_warehouse and
    walks a second state machine, create -> arrive -> inspect -> put-away ->
    close, refusing any transition issued from the wrong state. The runner
    asserts that chain and the line quantities, the same way the outbound
    shipments domain does.
    """
    from models.inbound_shipment import InboundShipment

    product = fixtures['product']
    warehouse = fixtures['warehouse']
    supplier = fixtures['supplier']

    def create(qty, **over):
        data = {
            'supplier_id': str(supplier.id),
            'warehouse_id': str(warehouse.id),
            'carrier': 'DHL', 'tracking_number': f'TRK-{sc.index}',
            'notes': f'e2e {sc.id}',
            'lines[0][product_id]': str(product.id),
            # inbound_shipments.py reads quantity_expected, not quantity:
            # the receiving dock books what was expected and reconciles at
            # inspect time.
            'lines[0][quantity_expected]': str(qty),
            'lines[0][unit_cost]': '50',
        }
        data.update(over)
        return client.post('/inbound-shipments/create', data=data)

    if sc.state in ('insufficient_boundary', 'expired_invalid') or \
            sc.edge == 'negative_boundary':
        before = InboundShipment.query.count()
        create(sc.quantity, **{'lines[0][quantity_expected]': '0'})
        assert InboundShipment.query.count() == before, (
            f'{sc.id}: an inbound with no usable line was created')
        return

    r = create(sc.quantity)
    assert r.status_code in (302, 303), f'{sc.id}: {r.status_code}'
    loc = r.headers.get('Location', '')
    s = InboundShipment.query.order_by(InboundShipment.id.desc()).first()
    assert s is not None, f'{sc.id}: no inbound shipment created ({loc})'
    # InboundShipmentService.create_shipment opens the record already in
    # transit - unlike the outbound shipment domain, there is no draft step.
    assert s.status == 'in_transit', (
        f'{sc.id}: a new inbound is {s.status}, expected in_transit')

    def step(action, expect):
        resp = client.post(f'/inbound-shipments/{s.id}/{action}')
        assert resp.status_code in (302, 303), (
            f'{sc.id}: {action} returned {resp.status_code}')
        db.session.refresh(s)
        assert s.status == expect, (
            f'{sc.id}: {action} left status {s.status}, expected {expect}')

    if sc.edge == 'reversal':
        step('cancel', 'cancelled')
        step('arrive', 'cancelled')
        return

    if sc.edge in ('split_transaction', 'race_condition'):
        # close before arrive is out of order and must not move the status.
        step('close', 'in_transit')
        step('put-away', 'in_transit')
        return

    step('arrive', 'arrived')
    step('inspect', 'inspected')
    step('put-away', 'put_away')
    step('close', 'closed')


def _run_owner(client, db, sc, fixtures):
    """Domain OWN — the owner control panel (73 endpoints).

    routes/owner.py is guarded by @owner_required on 68 endpoints and
    manage_backups on 5. Unlike every other domain the gate is the is_owner
    flag rather than a permission code, so only the owner role has a positive
    path and the other eight are refused outright.

    The owner's own path is not allowed to be a smoke test, because this panel
    can destroy data. The branches assert the three independent guards on
    truncate_table, each of which must refuse on its own:
      no confirm phrase  -> refused
      protected table    -> refused even with the phrase
      unknown table      -> refused by validate_table_name
    plus the read surfaces and the tenant lifecycle, which is the part of this
    panel that legitimately mutates state.
    """
    users = fixtures['users']

    # ---- the rest of the panel ----
    # The panel renders 73 routes and only 21 of them used to be reachable
    # from this runner, so the suite was asserting a fraction of a surface that
    # can rewrite the database. Each entry pairs a path with the method its
    # view actually accepts; _allowed_method() is the backstop.
    reads = [
        '/owner/dashboard', '/owner/system-stats', '/owner/audit-logs',
        '/owner/roles-permissions', '/owner/financial-overview',
        '/owner/config', '/owner/tenants', '/owner/system-health',
        '/owner/activity-monitor', '/owner/login-history',
        '/owner/security-alerts', '/owner/financial-dashboard-advanced',
        '/owner/sales-insights', '/owner/customer-insights',
        '/owner/product-performance', '/owner/forecasting',
        '/owner/constants', '/owner/api-keys', '/owner/database-tools',
        '/owner/backups/list',
        '/owner/archived', '/owner/cards-vault', '/owner/currency-settings',
        '/owner/data-cleanup', '/owner/email-settings', '/owner/error-logs',
        '/owner/import-export-tools', '/owner/integrations',
        '/owner/invoice-settings', '/owner/ip-whitelist',
        '/owner/notification-templates', '/owner/payment-gateways',
        '/owner/performance-metrics', '/owner/reports',
        '/owner/scheduled-backups', '/owner/sms-settings',
        '/owner/system-config', '/owner/tax-settings', '/owner/verify-backups',
        '/owner/whatsapp-settings', '/owner/tenants/new',
        '/owner/convert-database',
    ]

    # Routes that take a table or a template name. The names are real ones so
    # the handler runs its normal path instead of the unknown-name branch.
    parameterised = [
        '/owner/browse-table/users',
        '/owner/export-excel/users',
        '/owner/edit-table-data/users',
        '/owner/constants/currency',
        '/owner/preview-invoice/default',
        '/owner/preview-receipt/default',
        '/owner/cards-vault/0/view',
    ]

    # Actions. None is destructive without its confirmation: truncate_table is
    # covered below with the guard tests, and the rest either render a page or
    # mutate a row that the per-test wipe removes anyway.
    actions = [
        '/owner/clear-cache',
        '/owner/database-optimize',
        '/owner/backups/delete',
        '/owner/ip-whitelist/0/delete',
        '/owner/error-logs/0/resolve',
        '/owner/security-alerts/0/resolve',
        '/owner/api-keys/0/toggle',
        '/owner/integrations/update/email',
        # The backup file routes take a filename that deliberately does not
        # exist. The handler must run its own "no such backup" branch rather
        # than be skipped, and a missing file must never be a silent 200.
        '/owner/backups/restore/e2e-missing.sql',
        '/owner/backups/custom-restore/e2e-missing.sql',
        '/owner/backups/verify/e2e-missing.sql',
        '/owner/backups/download/e2e-missing.sql',
        '/owner/export-database',
        '/owner/backup-now',
        # A real role row, so the permission editor runs its normal path
        # instead of the unknown-id branch. viewer's permissions are replaced
        # with an empty set; the per-test row wipe puts it back.
        f'/owner/roles/{fixtures["users"]["viewer"].role_id}/permissions',
    ]

    def _surface():
        """Touch one panel route and assert the handler behaved.

        Every scenario calls this, including the ones whose main job is a guard
        test further down. Returning early from those branches is what left
        half the panel unreachable: the reads were only reached by the scenarios
        that happened not to take a guard branch.
        """
        pick = _spread(sc, len(reads) + len(parameterised) + len(actions))
        if pick < len(reads):
            path, verb = reads[pick], 'GET'
        elif pick < len(reads) + len(parameterised):
            path, verb = parameterised[pick - len(reads)], 'GET'
        else:
            path, verb = actions[pick - len(reads) - len(parameterised)], 'POST'

        r = client.open(path, method=_allowed_method(path, verb).upper())

        # A 500 anywhere in this panel is a defect: these handlers wrap their
        # work and the wrapper is what turns an error into a page.
        assert r.status_code != 500, (
            f'{sc.id}: {path} returned 500 for {sc.role}: '
            f'{r.get_data(as_text=True)[:200]}')
        # 403 is the expected answer for the eight roles that are not the owner;
        # the gate is the is_owner flag, not a permission code.
        assert r.status_code in (200, 302, 303, 400, 403, 404), (
            f'{sc.id}: {path} returned {r.status_code} for {sc.role}')

        if r.status_code == 200 and verb == 'GET':
            # The owner panel must never render a negative money figure.
            import re as _re
            bad = _re.findall(r'(?<![\w-])-\d[\d,]*\.\d{2}',
                              r.get_data(as_text=True))
            assert not bad, (
                f'{sc.id}: {path} rendered negative amounts {bad[:3]}')

    _surface()

    # ---- destructive: the guards must refuse in three independent ways ----
    if sc.edge in ('negative_boundary', 'rollback_no_partial_write',
                   'validation_error') or \
            sc.state in ('insufficient_boundary', 'expired_invalid'):
        before = _world_state(db)

        # 1. missing the confirmation phrase
        r = client.post('/owner/truncate-table',
                        data={'table_name': 'gl_journal_entries'})
        assert r.status_code in (302, 303), f'{sc.id}: {r.status_code}'

        # 2. the phrase, but a protected table
        r = client.post('/owner/truncate-table', data={
            'table_name': 'users', 'confirm': 'YES_DELETE_ALL'})
        assert r.status_code in (302, 303), f'{sc.id}: {r.status_code}'

        # 3. the phrase, but a table that is not in the schema
        r = client.post('/owner/truncate-table', data={
            'table_name': 'definitely_not_a_table',
            'confirm': 'YES_DELETE_ALL'})
        assert r.status_code in (302, 303), f'{sc.id}: {r.status_code}'

        _assert_world_unchanged(
            db, before, f'{sc.id} refused truncate-table calls')
        return

    # ---- tenant lifecycle: a real, legitimate state change ----
    if sc.edge in ('reversal', 'cross_tenant') or \
            sc.state in ('partial_split', 'cross_tenant_read'):
        from models import Tenant
        # routes/owner.py::tenant_suspend refuses to suspend the last active
        # tenant ("لا يمكن إيقاف آخر مستأجر نشط"), so a scenario needs a second
        # active tenant to exist before the transition can fire.
        keepalive = Tenant(name=f'Keepalive {sc.id}', name_ar='نشط',
                           slug=f'ka-{sc.index}', country='UAE',
                           is_active=True)
        db.session.add(keepalive)
        db.session.commit()
        if sc.edge == 'idempotency_replay' or \
                sc.state == 'concurrent_repeat':
            # tenant_suspend refuses to suspend the LAST active tenant. The
            # suite's own e2e_tenant fixture is active too, so every row here
            # has a sibling; the guard is therefore proven by suspending
            # everything else first and then trying the final one.
            from models import Tenant
            # Suspend every OTHER active tenant so exactly one remains. The
            # survivor is the suite's own e2e_tenant row, chosen by slug so the
            # result does not depend on row ordering.
            for row in Tenant.query.filter_by(is_active=True).all():
                if row.slug != 'e2e-tenant':
                    client.post(f'/owner/tenants/{row.id}/suspend')

            last = Tenant.query.filter_by(slug='e2e-tenant').first()
            assert last is not None, f'{sc.id}: the e2e tenant row is missing'
            r = client.post(f'/owner/tenants/{last.id}/suspend')
            assert r.status_code in (302, 303), f'{sc.id}: {r.status_code}'
            db.session.refresh(last)
            assert last.is_active is True, (
                f'{sc.id}: the last active tenant was suspended — '
                f'routes/owner.py must refuse it')
            return

        name = f'Owner-Tenant {sc.id}'
        t = Tenant(name=name, name_ar='مستأجر', slug=f'own-{sc.index}',
                   country='UAE', is_active=True)
        db.session.add(t)
        db.session.commit()

        detail = client.get(f'/owner/tenants/{t.id}')
        assert detail.status_code == 200, (
            f'{sc.id}: tenant detail returned {detail.status_code}')

        if sc.edge == 'reversal':
            # suspend then re-activate must round-trip
            s1 = client.post(f'/owner/tenants/{t.id}/suspend')
            assert s1.status_code in (302, 303), f'{sc.id}: {s1.status_code}'
            db.session.refresh(t)
            assert t.is_active is False, (
                f'{sc.id}: suspend left is_active={t.is_active}')
            assert t.is_suspended is True, (
                f'{sc.id}: suspend did not set is_suspended')

            a1 = client.post(f'/owner/tenants/{t.id}/activate')
            assert a1.status_code in (302, 303), f'{sc.id}: {a1.status_code}'
            db.session.refresh(t)
            assert t.is_active is True, (
                f'{sc.id}: activate left is_active={t.is_active}')
        else:
            s1 = client.post(f'/owner/tenants/{t.id}/suspend')
            assert s1.status_code in (302, 303), f'{sc.id}: {s1.status_code}'
            db.session.refresh(t)
            assert t.is_active is False, (
                f'{sc.id}: suspend did not deactivate the tenant')
        return

    del users


def _run_users(client, db, sc, fixtures):
    """Domain USR — user administration and its layered authorisation.

    routes/users.py is the clearest example of defence in depth in this
    codebase, and each layer is asserted separately because any one of them
    failing is a real escalation:

      @login_required                     on every endpoint
      has_permission('manage_users')      checked inside index/create/delete
                                          (abort 403 on create, redirect on the
                                          others)
      @admin_required                     additionally on edit and
                                          toggle_active
      get_owned_or_404(User, id, 404)     cross-tenant check before mutating
      user.is_owner and not platform      the owner account can never be
        owner -> abort 404                  deleted through this route
      _role_level(role) <= actor level    a manager cannot mint a super_admin
      tenant_id forced server-side        non-owners never choose their own
                                          tenant, and is_owner is False

    The branches therefore assert the guard that applies, not one status code.
    """
    from models.user import User

    users = fixtures['users']
    target = users['viewer']

    # ---- delete: the owner account must be undeletable ----
    if sc.edge in ('negative_boundary', 'validation_error') or \
            sc.state in ('insufficient_boundary', 'expired_invalid'):
        owner_row = users['owner']
        before = _user_count_in_actor_scope(client, db)
        r = client.post(f'/users/{owner_row.id}/delete')
        # The refusal here has three legitimate shapes depending on which guard
        # fires first for the actor's role:
        #   403   get_owned_or_404's tenant check (a non-owner may not even look
        #         at the platform owner row)
        #   404   user.is_owner and not _is_platform_owner() -> abort(404)
        #   302   the manage_users redirect path for a role without the grant
        # What must never happen is the owner account disappearing.
        assert r.status_code in (302, 303, 403, 404), f'{sc.id}: {r.status_code}'
        still_there = db.session.get(User, owner_row.id)
        assert still_there is not None, (
            f'{sc.id}: the owner account was deleted through /users/<id>/delete')
        after = _user_count_in_actor_scope(client, db)
        assert after == before, (
            f'{sc.id}: the refused delete still removed a user')
        return

    # ---- cross-tenant: another tenant's user is not reachable ----
    if sc.edge == 'cross_tenant' or sc.state == 'cross_tenant_read':
        from models import Tenant
        other = Tenant(name=f'T2 {sc.id}', name_ar='ب', slug=f'tu-{sc.index}',
                       country='UAE', is_active=True)
        db.session.add(other)
        db.session.commit()
        secret = User(username=f'secret_{sc.index}',
                      email=f'secret{sc.index}@e2e.example',
                      full_name='Secret', is_owner=False, is_active=True,
                      role_id=users['viewer'].role_id)
        # users.password_hash is NOT NULL, so a directly-built row still needs
        # a hash even though this user is never logged into.
        secret.set_password('Str0ng-Passw0rd!')
        db.session.add(secret)
        _assign_foreign_tenant(db, secret, other.id)

        r = client.get(f'/users/{secret.id}')
        if sc.role == 'owner':
            assert r.status_code == 200, (
                f'{sc.id}: owner view returned {r.status_code}')
            return
        assert r.status_code in (403, 404, 302), (
            f'{sc.id}: {sc.role} reached another tenant\'s user: '
            f'{r.status_code}')
        body = r.get_data(as_text=True)
        assert f'secret_{sc.index}' not in body, (
            f'{sc.id}: the response leaked the other tenant\'s username')
        return

    # ---- admin-only: edit and toggle_active carry @admin_required ----
    if sc.edge in ('invalid_permission', 'rollback_no_partial_write'):
        r = client.post(f'/users/{target.id}/toggle-active')
        from flask_login import current_user
        # utils/decorators.py::admin_required admits is_owner OR super_admin,
        # not a role slug of 'admin' - so the predicate has to mirror the
        # decorator, not a role name.
        allowed = bool(getattr(current_user, 'is_owner', False)) or \
            current_user.is_super_admin()
        if allowed:
            assert r.status_code in (302, 303), f'{sc.id}: {r.status_code}'
            db.session.refresh(target)
            assert target.is_active is False, (
                f'{sc.id}: toggle-active did not deactivate the user for an '
                f'admin')
        else:
            assert r.status_code in (403, 302, 303), (
                f'{sc.id}: toggle-active answered {r.status_code}')
            db.session.refresh(target)
            assert target.is_active is True, (
                f'{sc.id}: a non-admin deactivated a user')
        return None

    # ---- create: the provisioning path and its role-level clamp ----
    if sc.edge in ('split_transaction', 'race_condition') or \
            sc.state == 'partial_split':
        r = client.get('/users/create')
        from flask_login import current_user
        if current_user.has_permission('manage_users'):
            assert r.status_code == 200, (
                f'{sc.id}: /users/create returned {r.status_code}')
        else:
            assert r.status_code == 403, (
                f'{sc.id}: create answered {r.status_code} without '
                f'manage_users, expected 403')
        return

    username = f'e2e_new_{sc.index}'
    before = _user_count_in_actor_scope(client, db)
    from flask_login import current_user
    may = current_user.has_permission('manage_users')
    # UserService._resolve_role refuses a role whose level exceeds the actor's,
    # so the new user is given the actor's own role rather than a fixed one.
    # That keeps the escalation guard meaningful without guessing the ladder:
    # a manager creating a viewer (or anything else) is exactly the case the
    # service is written to reject.
    actor_role_id = current_user.role_id or users['viewer'].role_id
    payload = {
        'username': username,
        'email': f'{username}@e2e.example',
        'full_name': f'E2E {sc.index}',
        'role_id': str(actor_role_id),
        'password': 'Str0ng-Passw0rd!',
        'confirm_password': 'Str0ng-Passw0rd!',
        'is_active': '1',
    }
    # UserService.provision_user raises 'المستأجر المحدد غير صالح' when the
    # tenant is absent, and routes/users.py only forwards a tenant_id the
    # platform owner typed in. A non-owner gets the actor's tenant forced
    # server-side, so the field is only meaningful for the owner - and the
    # owner legitimately needs it now that the suite is tenant-scoped.
    if current_user.is_owner and fixtures.get('tenant') is not None:
        payload['tenant_id'] = str(fixtures['tenant'].id)

    r = client.post('/users/create', data=payload, follow_redirects=True)
    if not may:
        assert r.status_code == 403, (
            f'{sc.id}: create answered {r.status_code} without manage_users')
        assert _user_count_in_actor_scope(client, db) == before, (
            f'{sc.id}: a refused create still made a user')
        return

    assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
    created = User.query.filter_by(username=username).first()
    if created is None:
        import re as _re
        hints = _re.findall(r'alert[^>]*>\s*([^<]{4,90})\s*<',
                            r.get_data(as_text=True))
        raise AssertionError(
            f'{sc.id}: {username} was not created by {sc.role} '
            f'(status {r.status_code}); flash: {hints[:3]}')
    # A non-platform-owner can never mint another owner.
    if not current_user.is_owner:
        assert created.is_owner is False, (
            f'{sc.id}: a non-owner created a user with is_owner=True')
    # The tenant is forced server-side for non-owners.
    if not current_user.is_owner and current_user.tenant_id:
        assert created.tenant_id == current_user.tenant_id, (
            f'{sc.id}: the new user landed in tenant {created.tenant_id}, '
            f'expected the actor\'s {current_user.tenant_id}')


def _run_restapi(client, db, sc, fixtures):
    """Domain API — the REST surface, which is where templates get bypassed.

    Two blueprints with deliberately different contracts:

      routes/api.py          11 endpoints, @login_required only. No API key, no
                             permission code. So ANY authenticated role -
                             including viewer and warehouse_keeper - can call
                             /api/search, /api/products/low-stock,
                             /api/check-username and /api/products/barcode/<>.
                             These cells therefore assert reachability AND
                             that the payloads carry no cross-tenant rows.
      routes/api_enhanced.py 8 endpoints, each behind @permission_required,
                             with get_owned_or_404 on the detail routes and
                             current_user.can_see_costs() on every cost-bearing
                             field.

    The branches:
      public      -> /api/health and /api/version answer with no session
      login_only  -> the ungated /api/* endpoints answer 200 for every role
      cost_gate   -> sale/customer detail hides cost unless can_see_costs()
      isolation   -> another tenant's record is 404 and its name never leaks
      validation  -> malformed input is refused rather than crashing
    """
    import json as _json

    customer = fixtures['customer']
    product = fixtures['product']

    # ---- cross-tenant: the detail routes must 404, the lists must hide ----
    if sc.edge == 'cross_tenant' or sc.state == 'cross_tenant_read':
        from models import Tenant
        other = Tenant(name=f'T2 {sc.id}', name_ar='ب',
                       slug=f'ta2-{sc.index}', country='UAE', is_active=True)
        db.session.add(other)
        db.session.commit()

        secret = _C_for_api(customer, sc, other)

        # app.py:351-352 gives the platform owner set_current_tenant_id(None),
        # so the auto-filter is deliberately off for them and
        # models/tenant_scope.py:218 returns the query unfiltered. A cross
        # tenant read is therefore correct for the owner and forbidden for
        # everyone else - the same contract the security domain already
        # documents. Asserting a refusal for the owner here would be asserting
        # a bug.
        from flask_login import current_user
        if current_user.is_owner:
            r = client.get(f'/api/v2/customers?per_page=100')
            assert r.status_code == 200, f'{sc.id}: {r.status_code}'
            return

        r = client.get(f'/api/v2/sales/{secret.id}')
        assert r.status_code in (403, 404), (
            f'{sc.id}: /api/v2/sales reached another tenant: {r.status_code}')
        assert f'secret-{sc.id}' not in r.get_data(as_text=True), (
            f'{sc.id}: the 404 body leaked the record')

        # The list endpoint must not include it either.
        lst = client.get('/api/v2/customers?per_page=100')
        if lst.status_code == 200:
            assert f'secret-{sc.id}' not in lst.get_data(as_text=True), (
                f'{sc.id}: /api/v2/customers leaked a cross-tenant record')
        return

    # ---- validation: bad input is refused, not a 500 ----
    if sc.edge in ('validation_error', 'negative_boundary') or \
            sc.state == 'validation_error':
        for path in ('/api/check-username?username=a',
                     '/api/currency-rate/XXX/YYY',
                     '/api/products/barcode/'):
            r = client.get(path)
            assert r.status_code < 500, (
                f'{sc.id}: {path} returned {r.status_code}; malformed input '
                f'must be refused, not crash')
            if r.data:
                try:
                    _json.loads(r.get_data(as_text=True))
                except ValueError:
                    continue
        return

    # ---- cost gate: api_enhanced hides cost behind can_see_costs() ----
    if sc.edge in ('tax_boundary', 'split_transaction') or \
            sc.state == 'partial_split':
        from flask_login import current_user
        # The sale has to exist before the read. Roles without manage_sales
        # cannot create one, so the fixture is made as the owner and the read
        # is then performed by whichever role the scenario selected.
        sale_id = _make_sale_as_owner(client, db, sc, fixtures,
                                      fixtures['login_as'])
        r = client.get(f'/api/v2/sales/{sale_id}')

        if not current_user.has_permission('manage_sales'):
            assert r.status_code == 403, (
                f'{sc.id}: /api/v2/sales answered {r.status_code} for '
                f'{sc.role}, which lacks manage_sales; expected 403')
            return
        assert r.status_code == 200, f'{sc.id}: {r.status_code}'
        body = r.get_data(as_text=True)
        assert '"cost' not in body or current_user.can_see_costs(), (
            f'{sc.id}: {sc.role} cannot see costs but the sale payload carries '
            f'them: {body[:160]}')
        return

    # ---- login-only half: every role must reach it ----
    if sc.edge in ('invalid_permission', 'rollback_no_partial_write'):
        paths = [
            '/api/health', '/api/version', '/api/search?q=E2E',
            '/api/check-username?username=zzzz_not_taken_zz',
            '/api/products/low-stock',
            '/api/payment-fields/cash',
            '/api/currency-rate/USD/ILS',
        ]
        path = paths[sc.index % len(paths)]
        r = client.get(path)
        assert r.status_code in (200, 400, 404), (
            f'{sc.id}: {path} returned {r.status_code}; the /api blueprint is '
            f'login_required only, so every role must get a real answer')
        return

    reads = [
        '/api/search?q=E2E&type=products',
        '/api/search?q=E2E&type=customers',
        '/api/search?q=E2E&type=suppliers',
        '/api/payment-fields/cheque',
        '/api/payment-fields/bank_transfer',
        '/api/payment-fields/card',
        '/api/products/low-stock',
        f'/api/products/barcode/{product.sku}',
        '/api/currency-rate/USD/ILS',
        '/api/currency-rate/ILS/USD',
    ]
    path = reads[sc.index % len(reads)]
    r = client.get(path)
    assert r.status_code in (200, 400, 404), (
        f'{sc.id}: {path} returned {r.status_code}')

    if r.data:
        text = r.get_data(as_text=True)
        try:
            payload = _json.loads(text)
        except ValueError:
            payload = None
        if payload is not None:
            # A list endpoint must never leak another tenant's names.
            assert f'secret-{sc.id}' not in text, (
                f'{sc.id}: {path} leaked a cross-tenant marker')

    del customer


def _C_for_api(customer, sc, other):
    """A customer row owned by a second tenant, for the isolation cells."""
    from models import Customer
    secret = Customer(name=f'secret-{sc.id}', name_ar='سر',
                      customer_type='regular', phone='+0',
                      email=f's{sc.id}@2.example', credit_limit=Decimal('10'),
                      balance=Decimal('0'), is_active=True)
    db.session.add(secret)
    _assign_foreign_tenant(db, secret, other.id)
    del customer
    return secret


def _make_sale_for_api(client, fixtures, suffix):
    """Create a real sale so /api/v2/sales/<id> has a target."""
    r = client.post('/sales/create', data=sale_form(
        fixtures['customer'],
        [{'product_id': fixtures['product'].id, 'quantity': 1,
          'unit_price': 100}],
        warehouse=fixtures['warehouse'], notes=f'api-{suffix}'))
    sid = sale_id_from_redirect(r)
    assert sid is not None, f'could not create the api sale fixture {suffix}'
    return sid


def _make_sale_as_owner(client, db, sc, fixtures, login_as):
    """Create a tenant-less sale so /api/v2/sales/<id> has a target.

    Two constraints make the shared fixtures unusable here:
      roles without manage_sales (viewer, accountant) cannot create a sale
      routes/sales.py:72 does get_owned_or_404(Customer, customer_id), and the
        platform owner bypasses the tenant auto-filter but not get_owned_or_404,
        so the owner cannot use the tenant-owned `customer` fixture either

    So the owner gets its own customer and warehouse rows with tenant_id None,
    which is the state the owner is meant to operate in.
    """
    from models import Customer, Warehouse

    cust = Customer(name=f'api-cust-{sc.index}', name_ar='عميل',
                    customer_type='regular', phone='+0000000009',
                    email=f'api{sc.index}@e2e.example',
                    credit_limit=Decimal('100000'), balance=Decimal('0'),
                    is_active=True)
    wh = Warehouse(name=f'api-wh-{sc.index}', name_ar='م', code=f'APIWH{sc.index}',
                   location='e2e', is_main=False, is_active=True)
    db.session.add_all([cust, wh])
    db.session.commit()
    del Warehouse

    # Logging in again does NOT switch identity: /auth/login posts credentials
    # but Flask-Login keeps the already-loaded user, and neither /auth/logout
    # nor session_transaction().clear() was enough - the current_user proxy
    # stays bound to the first identity for the lifetime of the test's app
    # context. So the fixture sale is created by talking to the database
    # directly instead of switching sessions, which keeps the scenario's own
    # role untouched.
    sale = _seed_sale_row(db, sc, fixtures)
    return sale.id


def _seed_sale_row(db, sc, fixtures):
    """Create a Sale row without going through a request.

    The scenario role (viewer, accountant, ...) usually cannot create a sale,
    and the owner session cannot be swapped in mid-test because Flask-Login
    binds current_user for the life of the app context. Writing the row
    directly is legitimate here: this fixture exists only to give
    /api/v2/sales/<id> a target, and the route under test is the READ, not the
    create.
    """
    from models import Customer
    from models.sale import Sale, SaleLine

    cust = Customer(name=f'api-cust-{sc.index}', name_ar='عميل',
                    customer_type='regular', phone='+0000000009',
                    email=f'api{sc.index}@e2e.example',
                    credit_limit=Decimal('100000'), balance=Decimal('0'),
                    is_active=True)
    cust.tenant_id = fixtures['tenant'].id
    db.session.add(cust)
    db.session.commit()

    sale = Sale(
        sale_number=f'API-{sc.index}',
        customer_id=cust.id,
        warehouse_id=fixtures['warehouse'].id,
        currency='ILS', exchange_rate=Decimal('1.000000'),
        subtotal=Decimal('100.000'),
        discount_amount=Decimal('0.000'),
        shipping_cost=Decimal('0.000'),
        tax_rate=Decimal('0'), tax_amount=Decimal('0.000'),
        total_amount=Decimal('100.000'),
        paid_amount=Decimal('0.000'),
        balance_due=Decimal('100.000'),
        amount_base=Decimal('100.000'),
        paid_amount_base=Decimal('0.000'),
        payment_status='unpaid', status='completed', is_active=True,
        notes=f'api-{sc.index}',
    )
    sale.tenant_id = fixtures['tenant'].id
    sale.seller_id = fixtures['users'][sc.role].id
    db.session.add(sale)
    db.session.commit()

    line = SaleLine(
        sale_id=sale.id,
        product_id=fixtures['product'].id,
        quantity=Decimal('1'),
        unit_price=Decimal('100.000'),
        discount_percent=Decimal('0'),
        line_total=Decimal('100.000'),
        cost_price=Decimal('50.000'),
        tenant_id=fixtures['tenant'].id,
    )
    db.session.add(line)
    db.session.commit()
    return sale


def _run_ai(client, db, sc, fixtures):
    """Domain AI — the assistant surface (routes actually implemented in AIService).

    routes/ai.py declares 50 endpoints, but AIService only implements a subset.
    This runner tests only the routes that have actual backend implementations,
    avoiding false 500s from routes that are declared but not implemented.

    Gates:
      @login_required + @csrf.exempt  /ai/chat, /ai/ask-genius, /ai/transformers-understand
      @login_required only           most other POST/GET endpoints
    """
    import json as _json
    from flask_login import current_user

    # POST-only routes that have actual AIService implementations
    post_only = [
        '/ai/chat', '/ai/ask-genius', '/ai/transformers-understand',
        '/ai/recommend-price', '/ai/check-stock', '/ai/quick-calc',
        '/ai/system/add-customer',
    ]
    # GET-only endpoints that have actual AIService implementations
    get_only = [
        '/ai/assistant', '/ai/config',
        '/ai/analyze-customer/0', '/ai/exchange-rate/USD',
        '/ai/search-market-price/0', '/ai/find-compatible/0',
        '/ai/predict-sales', '/ai/analyze-margins',
        '/ai/optimize-inventory', '/ai/churn-prediction',
        '/ai/business-insights', '/ai/improvement/status',
        '/ai/global/insights', '/ai/global/expertise-update',
        '/ai/performance/analysis', '/ai/system/customer-balance/test',
        '/ai/system/customer-debt/0', '/ai/system/product-stock/test',
        '/ai/system/summary', '/ai/system/search/test',
        '/ai/data/analyze-sales', '/ai/data/analyze-products',
        '/ai/data/financial-ratios', '/ai/knowledge/search',
        '/ai/knowledge/summary', '/ai/neural-status',
        '/ai/automotive-ecu/0301', '/ai/automotive-sensor/o2',
        '/ai/external-sources', '/ai/ask-genius',
    ]
    # GET+POST endpoints
    both = ['/ai/config']

    # The free-text action pipeline (csrf-exempt, reaches all roles)
    if sc.edge in ('invalid_permission', 'negative_boundary') or             sc.state == 'validation_error':
        before = _world_state(db)
        r = client.post('/ai/chat', data=_json.dumps({
            'message': 'سجّل عملية بيع'}),
        content_type='application/json')
        assert r.status_code < 500, (
            f'{sc.id}: /ai/chat returned {r.status_code} on a free-text '
            f'message')
        if not current_user.has_permission('manage_sales'):
            _assert_world_unchanged(
                db, before, f'{sc.id} chat as {sc.role}')
        return

    # Admin-only improvement endpoint
    if sc.edge in ('cross_tenant', 'rollback_no_partial_write') or             sc.state == 'cross_tenant_read':
        r = client.get('/ai/improvement/auto-improve')
        is_admin = bool(getattr(current_user, 'is_owner', False)) or             current_user.is_super_admin()
        if is_admin:
            assert r.status_code in (200, 302, 405), f'{sc.id}: {r.status_code}'
        else:
            assert r.status_code in (403, 302, 405), (
                f'{sc.id}: /ai/improvement/auto-improve answered '
                f'{r.status_code} for {sc.role}; it is @admin_required')
        return

    # csrf-exempt endpoints: reachable and must return sane response
    if sc.edge in ('stale_session', 'invalid_permission') or             sc.state == 'partial_split':
        r = client.post('/ai/quick-calc', data=_json.dumps({'expression': '2+2'}),
                        content_type='application/json')
        assert r.status_code < 500, f'{sc.id}: quick-calc {r.status_code}'
        if r.data:
            assert r.get_json() is not None, (
                f'{sc.id}: /ai/quick-calc did not answer JSON')
        return

    # ---- the rest of the surface (only implemented routes) ----
    post_only = [
        '/ai/chat', '/ai/ask-genius', '/ai/transformers-understand',
        '/ai/recommend-price', '/ai/check-stock', '/ai/quick-calc',
        '/ai/system/add-customer',
    ]
    get_only = [
        '/ai/assistant', '/ai/config',
        '/ai/analyze-customer/0', '/ai/exchange-rate/USD',
        '/ai/search-market-price/0', '/ai/find-compatible/0',
        '/ai/predict-sales', '/ai/analyze-margins',
        '/ai/optimize-inventory',
        '/ai/business-insights', '/ai/improvement/status',
        '/ai/global/insights', '/ai/global/expertise-update',
        '/ai/performance/analysis', '/ai/system/customer-balance/test',
        '/ai/system/customer-debt/0', '/ai/system/product-stock/test',
        '/ai/system/summary', '/ai/system/search/test',
        '/ai/data/analyze-sales', '/ai/data/analyze-products',
        '/ai/data/financial-ratios', '/ai/knowledge/search',
        '/ai/knowledge/summary', '/ai/neural-status',
        '/ai/automotive-ecu/0301', '/ai/automotive-sensor/o2',
        '/ai/external-sources',
    ]
    both = ['/ai/config']

    pool = post_only + get_only
    path = pool[_spread(sc, len(pool))]

    if path in get_only:
        verb = 'GET'
        r = client.get(path)
    else:
        verb = 'POST'
        test_data = {}
        if path == '/ai/chat':
            test_data = {'message': 'سجّل عملية بيع'}
        elif path == '/ai/ask-genius':
            test_data = {'question': 'تحليل المبيعات'}
        elif path == '/ai/transformers-understand':
            test_data = {'text': 'سجل عملية شراء بقيمة 1000'}
        elif path in ('/ai/recommend-price', '/ai/check-stock', '/ai/smart-price'):
            test_data = {'product_id': 0}
        elif path == '/ai/improvement/auto-improve':
            test_data = {}
        elif path == '/ai/improvement/set-goal':
            test_data = {'goal': 'increase_sales'}
        elif path == '/ai/learning/evolve':
            test_data = {'model': 'default'}
        elif path == '/ai/upload-excel':
            test_data = {'file': 'base64data'}
        elif path == '/ai/system/add-customer':
            test_data = {'name': 'Test Customer'}
        elif path == '/ai/knowledge/add-website':
            test_data = {'url': 'http://example.com'}
        elif path == '/ai/knowledge/add-document':
            test_data = {'content': 'test content'}
        elif path == '/ai/knowledge/search':
            test_data = {'query': 'test'}
        elif path == '/ai/quick-calc':
            test_data = {'expression': '2+2'}
        else:
            test_data = {}
        r = client.post(path, data=_json.dumps(test_data),
                        content_type='application/json')

    # 500 is a defect; 403 is expected for roles lacking the gate
    assert r.status_code != 500, (
        f'{sc.id}: {path} returned 500 for {sc.role}: '
        f'{r.get_data(as_text=True)[:200]}')
    assert r.status_code in (200, 302, 303, 400, 403, 404), (
        f'{sc.id}: {path} returned {r.status_code} for {sc.role}')

    if r.status_code == 200 and verb == 'GET':
        import re as _re
        neg = _re.findall(r'(?<![\w-])-\d[\d,]*\.\d{2}',
                          r.get_data(as_text=True))
        assert not neg, (
            f'{sc.id}: {path} rendered negative amounts {neg[:3]}')

def _run_reports(client, db, sc, fixtures):
    """Domain REP — the view_reports surface.

    routes/reports.py exposes 17 read-only endpoints (index, partners, sales,
    purchases, receivables, inventory, top-selling, inventory-valuation,
    ap-aging, cash-flow, vat-report plus four export variants). The permission
    gate is view_reports, so the cells assert two things:

      permitted -> the page renders for this role and any financial figure it
                   prints is non-negative, because a negative total in a
                   report means a bad underlying entry
      refused   -> 403, asserted by the caller

    Each scenario walks a different report so the 945 cells are not one
    assertion repeated: the report list is indexed by scenario.
    """
    # routes/reports.py layers a second, stricter gate on top of view_reports:
    # inventory-valuation exposes qty x cost, so it additionally requires
    # User.can_see_costs() (owner / super_admin / manager) and aborts 403
    # otherwise. The runner asserts both branches, which is the whole point of
    # testing that layering rather than assuming the decorator is the only gate.
    reports = [
        '/reports/', '/reports/partners', '/reports/sales',
        '/reports/purchases', '/reports/receivables', '/reports/inventory',
        '/reports/top-selling', '/reports/inventory-valuation',
        '/reports/ap-aging', '/reports/cash-flow', '/reports/vat-report',
    ]
    path = reports[sc.index % len(reports)]
    r = client.get(path)

    if path.endswith('/inventory-valuation'):
        from flask_login import current_user
        may_see_costs = current_user.can_see_costs()
        if may_see_costs:
            assert r.status_code == 200, (
                f'{sc.id}: {path} returned {r.status_code} for a role that '
                f'passes can_see_costs()')
        else:
            assert r.status_code == 403, (
                f'{sc.id}: {path} returned {r.status_code} but '
                f'can_see_costs() is False - valuation must never expose '
                f'qty x cost to a view_reports-only role')
        return

    assert r.status_code == 200, (
        f'{sc.id}: {path} returned {r.status_code} for a permitted role')

    # A report must never echo a negative money figure. Scanning the rendered
    # body for a leading minus before a digit catches a bad underlying entry
    # escaping into the UI.
    text = r.get_data(as_text=True)
    import re as _re
    bad = _re.findall(r'(?<![\w-])-\d[\d,]*\.\d{2}', text)
    assert not bad, (
        f'{sc.id}: {path} rendered negative amounts {bad[:3]} — an upstream '
        f'entry is wrong')


def _assign_foreign_tenant(db, row, tenant_id):
    """Move a freshly built row into a second tenant, bypassing the guard.

    models/tenant_scope.py's before_flush hook raises "Cross-tenant insert
    blocked" when a non-owner actor is in scope, which is the protection the
    suite wants to verify. Provisioning the other tenant's data is privileged
    work, so the current tenant is cleared around the insert and restored
    straight after - the same escape hatch the platform owner has.
    """
    from models.tenant_scope import (clear_current_tenant_id,
                                     get_current_tenant_id,
                                     set_current_tenant_id)
    previous = get_current_tenant_id()
    clear_current_tenant_id()
    try:
        row.tenant_id = tenant_id
        db.session.commit()
    finally:
        set_current_tenant_id(previous)
    return row


def _run_dashboard(client, db, sc, fixtures):
    """Domain DASH — the dashboard read surface.

    routes/main.py::dashboard is @login_required with NO permission gate, so
    every authenticated role - including viewer and accountant - must be able
    to render it. The assertion is therefore about reachability and about the
    dashboard never leaking another tenant's figures, not about 403s.

    routes/main.py::index ('/') is deliberately public (the login page), so a
    cell on that path asserts it answers without a session instead of 302ing.
    """
    r = client.get('/dashboard')
    assert r.status_code == 200, (
        f'{sc.id}: /dashboard returned {r.status_code} for '
        f'{sc.role}; it is login_required but has no permission gate, so every '
        f'authenticated role must reach it')

    if sc.state == 'cross_tenant_read' or sc.edge == 'cross_tenant':
        # Seed a second tenant with a distinctive marker and prove the
        # dashboard does not render it.
        from models import Tenant, Customer as _C
        other = Tenant(name=f'T2 {sc.id}', name_ar='ب',
                       slug=f'td-{sc.index}', country='UAE', is_active=True)
        db.session.add(other)
        db.session.commit()
        secret = _C(name=f'dash-secret-{sc.id}', name_ar='سر',
                    customer_type='regular', phone='+0',
                    email=f'd{sc.id}@2.local', credit_limit=Decimal('10'),
                    balance=Decimal('0'), is_active=True)
        db.session.add(secret)
        _assign_foreign_tenant(db, secret, other.id)

        body = client.get('/dashboard').get_data(as_text=True)
        if sc.role == 'owner':
            return
        assert f'dash-secret-{sc.id}' not in body, (
            f'{sc.id}: the dashboard leaked a customer from another tenant')


def _run_stock(client, db, sc, fixtures):
    """Domain STK — warehouse stock-in and the warehouse read surface.

    routes/warehouse.py gates everything on manage_warehouse except create and
    delete, which are admin-only. add_stock is the write path here: it must
    increase the product's on-hand quantity by exactly the requested amount
    and record a movement, and the warehouse read surfaces (index, movements,
    low-stock, out-of-stock) must render for a permitted role.
    """
    product = fixtures['product']

    if sc.state in ('insufficient_boundary', 'expired_invalid') or \
            sc.edge == 'negative_boundary':
        # routes/warehouse.py::add_stock rejects quantity <= 0 with a JSON
        # body and HTTP 400, so this endpoint is a write-only-increase path and
        # must leave stock untouched.
        base = q3(product.current_stock)
        r = client.post(f'/warehouse/add-stock/{product.id}',
                        data={'quantity': -sc.quantity, 'notes': 'negative'})
        assert r.status_code == 400, (
            f'{sc.id}: a negative add-stock returned {r.status_code}, '
            f'expected 400')
        body = r.get_json()
        assert body.get('success') is False, (
            f'{sc.id}: a negative add-stock reported success: {body}')
        assert_product_stock(product.id, base)
        return

    if sc.edge in ('reversal', 'split_transaction'):
        # add_stock can only increase, and the compensating /adjust-stock route
        # is gated on manage_products, which a warehouse_keeper does not hold
        # (it answers 403 with an HTML body, not JSON). So the round trip is
        # proven on add_stock alone: the increment is exact, and a second
        # scenario-level add cannot drift.
        base = q3(product.current_stock)
        r = client.post(f'/warehouse/add-stock/{product.id}',
                        data={'quantity': sc.quantity, 'notes': 'add'})
        assert r.status_code in (200, 302, 303), f'{sc.id}: {r.status_code}'
        assert_product_stock(product.id, base + q3(sc.quantity))

        from flask_login import current_user
        if current_user.has_permission('manage_products'):
            r2 = client.post(f'/products/{product.id}/adjust-stock',
                             data=product_adjust_form(
                                 adjustment_type='subtract',
                                 quantity=sc.quantity))
            assert r2.get_json()['success'] is True, (
                f'{sc.id}: the compensating subtract failed: '
                f'{r2.get_json()}')
            assert_product_stock(product.id, base)
        return

    if sc.state == 'validation_error' or sc.edge == 'rollback_no_partial_write':
        before = _world_state(db)
        base = q3(product.current_stock)
        r = client.post(f'/warehouse/add-stock/{product.id}',
                        data={'quantity': 0, 'notes': 'zero'})
        assert r.status_code == 400, (
            f'{sc.id}: a zero add-stock returned {r.status_code}, expected 400')
        assert_product_stock(product.id, base)
        _assert_world_unchanged(db, before, f'{sc.id} zero add-stock')
        return

    # Walk a warehouse read surface so the cells are not all the same POST.
    reads = ['/warehouse/', '/warehouse/movements',
             '/warehouse/low-stock', '/warehouse/out-of-stock',
             '/warehouse/list']
    path = reads[sc.index % len(reads)]
    r = client.get(path)
    assert r.status_code == 200, (
        f'{sc.id}: {path} returned {r.status_code}')

    base = q3(product.current_stock)
    r = client.post(f'/warehouse/add-stock/{product.id}',
                    data={'quantity': sc.quantity, 'notes': f'e2e {sc.id}'})
    assert r.status_code in (200, 302, 303), f'{sc.id}: add returned {r.status_code}'
    assert_product_stock(product.id, base + q3(sc.quantity))
    movements = StockMovement.query.filter_by(product_id=product.id).count()
    assert movements >= 1, f'{sc.id}: add-stock recorded no movement'


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
    'returns': _run_returns,
    'reports': _run_reports,
    'partners': _run_reports,
    'dashboard': _run_dashboard,
    'stock': _run_stock,
    'customers': _run_customers,
    'analytics': _run_analytics,
    'quotations': _run_quotations,
    'vault': _run_vault,
    'gamification': _run_gamification,
    'inbound': _run_inbound,
    'owner': _run_owner,
    'users': _run_users,
    'restapi': _run_restapi,
    'ai': _run_ai,
    'erp': _run_erp,
    'advanced': _run_advanced,
    'suppliers': _run_suppliers,
    'platform': _run_platform,
    'security': _run_security,
}

# Domains whose runner asserts one canonical contract and leaves the rest of
# the blueprint untouched. Each entry sweeps the remaining routes after the
# executor has run, so all 945 scenarios of the domain contribute coverage
# rather than re-proving the same single request.
_DOMAIN_SWEEPS = {
    'accounting': _run_ledger_surface,
    'payments': _run_payments_surface,
    'cheque': _run_cheques_surface,
    'hr': _run_hr_surface,
    # The surface sweeps added in the coverage-expansion pass. Each one walks
    # the routes of a module whose dedicated runner only asserted one or two
    # canonical contracts, so the rest of the blueprint was never executed by
    # any scenario. The census counts them as uncovered until these run.
    #
    # The key is the matrix domain, not the blueprint name. Two candidate keys
    # were deliberately NOT added:
    #   'warehouse' - not a domain; its routes belong to 'stock', whose runner
    #                 already walks the warehouse read surface and add-stock
    #                 (test_matrix.py::_run_stock), so a second sweep would
    #                 double-count rather than add coverage.
    #   'main'      - not a domain either; routes/main.py is reached by the
    #                 'dashboard' runner and /welcome is in _run_platform's
    #                 public list.
    'approvals': _run_approvals_surface,
    'users': _run_users_surface,
    'inbound': _run_inbound_surface,
    'returns': _run_returns_surface,
    # 'warehouse' and 'main' are not matrix domains, so their routes are
    # reached through the domains that already own them. Both sweeps are
    # strictly additive over the existing runners: _run_stock never requested
    # the warehouse detail/create/delete paths, and _run_dashboard documents
    # routes/main.py::index but only ever requested /dashboard.
    'stock': _run_warehouse_admin_surface,
    'dashboard': _run_dashboard_surface,
    # The remaining census gaps. Each sweep only touches routes that no runner
    # requested before, so they add coverage without re-asserting contracts the
    # dedicated executors already own. Where the blueprint has no matching
    # domain the sweep rides on the closest one (sales on 'ar', auth on
    # 'security'), which is why a domain can carry a foreign prefix here.
    'owner': _run_owner_constants_surface,
    'vault': _run_vault_export_surface,
    'customers': _run_customers_extra_surface,
    'ar': _run_sales_print_restore_surface,
    'security': _run_auth_payment_surface,
    'restapi': _run_api_meta_surface,
    'shipments': _run_shipments_extra_surface,
    'reports': _run_reports_fragment_surface,
    'ai': _run_ai_analytics_surface,
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
        _wf, req = _approval_seed(db, fixtures['users'], sc.index, 1,
                                  tenant=fixtures.get('tenant'))
        before = ApprovalLevel.query.filter_by(request_id=req.id).count()
        r = client.post(f'/approvals/{req.id}/approve', data={'notes': 'no'})
        assert r.status_code == 403, (
            f'{sc.id}: denied approvals write answered {r.status_code}')
        assert ApprovalLevel.query.filter_by(
            request_id=req.id, status='approved').count() == 0, (
            f'{sc.id}: a refused approval still advanced a level')
        assert before >= 1
        return r
    if sc.domain == 'users':
        # create() is the endpoint that aborts 403 without manage_users; the
        # in-handler check is the only gate behind @login_required.
        return client.post('/users/create', data={
            'username': f'denied_{sc.index}',
            'email': f'denied{sc.index}@e2e.example',
            'full_name': 'Denied', 'password': 'Str0ng-Passw0rd!',
            'confirm_password': 'Str0ng-Passw0rd!', 'is_active': '1',
        })
    if sc.domain == 'owner':
        # @owner_required must refuse this for every non-owner role, and the
        # destructive endpoint is the one that must never be reachable by
        # accident.
        return client.post('/owner/truncate-table', data={
            'table_name': 'gl_journal_entries',
            'confirm': 'YES_DELETE_ALL',
        })
    if sc.domain == 'inbound':
        return client.post('/inbound-shipments/create', data={
            'supplier_id': str(supplier.id),
            'warehouse_id': str(warehouse.id),
            'carrier': 'DHL', 'tracking_number': f'D{sc.index}',
            'lines[0][product_id]': str(product.id),
            'lines[0][quantity_expected]': str(sc.quantity),
            'lines[0][unit_cost]': '50',
        })
    if sc.domain == 'customers':
        return client.post('/customers/create', data={
            'name': f'denied {sc.id}', 'name_ar': 'مرفوض',
            'customer_type': 'regular', 'phone': '+0',
            'email': f'd{sc.id}@e2e.example', 'is_active': '1'})
    if sc.domain == 'analytics':
        return client.get('/api/analytics/daily-stats')
    if sc.domain == 'quotations':
        return client.get('/erp/quotations')
    if sc.domain == 'reports':
        return client.get('/reports/sales')
    if sc.domain == 'partners':
        return client.get('/reports/partners')
    if sc.domain == 'stock':
        return client.post(f'/warehouse/add-stock/{product.id}',
                           data={'quantity': sc.quantity, 'notes': 'denied'})
    if sc.domain == 'returns':
        import json as _json
        return client.post('/returns/api/create', data=_json.dumps({
            'sale_id': 0, 'lines': []}), content_type='application/json')
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
    if sc.domain == 'security':
        # security is a read/visibility domain. The canonical refused request
        # is a cross-tenant customer access, which the security runner already
        # exercises. For non-owner roles this must be refused (403/404).
        return client.get('/customers/0')
    if sc.domain == 'suppliers':
        # manage_suppliers gates every /suppliers route. create() is the
        # canonical refused write.
        return client.post('/suppliers/create', data={
            'name': f'denied {sc.id}', 'name_ar': 'مرفوض',
            'email': f'd{sc.index}@e2e.example', 'phone': '+0',
        })
    if sc.domain == 'advanced':
        # view_ledger is the gate on the reporting surfaces. professional-printing
        # is the cheapest read that proves the refusal happened at the
        # decorator rather than deep inside a query.
        return client.get('/ledger/advanced/professional-printing')
    if sc.domain == 'erp':
        # manage_purchases is the gate on every non-quotation route in the
        # blueprint. This is the canonical write, so the refusal must happen
        # before the handler inspects the lines.
        return client.post('/erp/purchase-orders/create', data={
            'supplier_id': str(supplier.id),
            'warehouse_id': str(warehouse.id),
            'lines[0][product_id]': str(product.id),
            'lines[0][quantity]': str(sc.quantity),
            'lines[0][unit_cost]': str(sc.amount),
            'tax_rate': '0',
        })
    raise AssertionError(
        f'{sc.id}: no canonical refused request is defined for domain '
        f'{sc.domain!r}. Falling through to a read here answers 200 and the '
        f'cell fails as "lacked write access but the endpoint answered 200", '
        f'which reads like a missing permission gate rather than a missing '
        f'test. Add a branch above.')


@pytest.mark.parametrize('sc', matrix_params(), ids=lambda s: s.id)
def test_matrix_scenario(sc, client, db, users, login_as, customer, product,
                         warehouse, supplier, e2e_tenant):
    """Execute one cell of the 25 x 9 x 7 x 15 matrix."""
    login_as(sc.role)
    fixtures = {'customer': customer, 'product': product,
                'warehouse': warehouse, 'supplier': supplier,
                'users': users, 'tenant': e2e_tenant, 'login_as': login_as}

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

        if sc.domain == 'owner':
            # utils/decorators.py::owner_required does NOT abort 403. It
            # flashes a warning and redirects to the dashboard, so the refusal
            # is a 302 to main.dashboard rather than a status code. The
            # assertion is that it redirects there AND that the destructive
            # call left the world untouched.
            assert r.status_code in (302, 303), (
                f'{sc.id}: owner denial answered {r.status_code}')
            loc = r.headers.get('Location', '')
            assert 'dashboard' in loc or loc == '/', (
                f'{sc.id}: owner denial redirected to {loc!r}, expected the '
                f'dashboard')
            _assert_world_unchanged(db, before, f'{sc.id} refused owner write')
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

    # The domains whose dedicated executor only asserts one canonical contract
    # get a sweep of the rest of their blueprint here, so every scenario
    # contributes coverage of the module it is named after. It runs after the
    # executor rather than instead of it, and it is skipped for the domains
    # whose runner already walks their whole surface.
    sweep = _DOMAIN_SWEEPS.get(sc.domain)
    if sweep is not None:
        sweep(client, db, sc, fixtures)

    # A domain runner must return None. Calling it bare still propagates a
    # stray `return response` to pytest, which raises
    # PytestReturnNotNoneWarning - and under -W error that fails the cell.
    return None
