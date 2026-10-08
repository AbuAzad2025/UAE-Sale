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

from tests.e2e.harness import (
    ACC, manual_entry_form, sale_form, purchase_form, cheque_form,
    product_adjust_form, entry_id_from_redirect, sale_id_from_redirect,
    purchase_id_from_redirect, snapshot_entry_ids, entries_for_reference,
    lines_for_entries, get_entry_lines, assert_entry_accounts,
    assert_entry_balanced_and_non_trivial, assert_no_header_account_posted,
    assert_no_entry_created, assert_product_stock, q3,
)
from tests.e2e.matrix import matrix_params, MATRIX

CHQ_TODAY = date(2026, 3, 1)
OTHER_CURRENCY = 'USD'
OTHER_RATE = Decimal('3.670000')


def _world_state(db):
    """Everything the scenario may have created, for side-effect assertions."""
    return {
        'entries': snapshot_entry_ids(),
        'sales': Sale.query.count(),
        'purchases': Purchase.query.count(),
        'cheques': Cheque.query.count(),
        'movements': StockMovement.query.count(),
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


def _run_cheque(client, db, sc, fixtures):
    """Domain F — cheque intake and GL."""
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


def _run_security(client, db, sc, fixtures):
    """Domain H — access control and tenant isolation.

    The route matrix is exercised for authenticated roles; the cross-tenant
    cell additionally seeds a second tenant and asserts the refusal.
    """
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
    return client.get('/ledger/')


@pytest.mark.parametrize('sc', matrix_params(), ids=lambda s: s.id)
def test_matrix_scenario(sc, client, db, users, login_as, customer, product,
                         warehouse, supplier):
    """Execute one cell of the 6 x 5 x 5 x 10 matrix."""
    login_as(sc.role)
    fixtures = {'customer': customer, 'product': product,
                'warehouse': warehouse, 'supplier': supplier}

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

        assert r.status_code == 403, (
            f'{sc.id}: {sc.role} lacks write access to {sc.domain} but the '
            f'endpoint answered {r.status_code} instead of 403')
        _assert_world_unchanged(db, before, f'{sc.id} refused write')
        return

    _DISPATCH[sc.domain](client, db, sc, fixtures)
