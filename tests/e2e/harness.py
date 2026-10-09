"""
E2E harness — request builders for the REAL endpoints, and validators that
actually run.

Why this module exists
----------------------
The first attempt at this matrix was fake-green because:
  * it posted `lines-0-account_id` to /ledger/manual-entry, but the route reads
    `line_{i}_account` (an account CODE). No field matched, the `while` loop
    broke on iteration 0, `lines` stayed empty, and GLService happily created a
    0/0 "balanced" entry that passed a naive balance assertion.
  * `create_manual_entry` validates `total_debit == total_credit`. An EMPTY
    line list satisfies that (0 == 0). So "entry is balanced" is worthless as an
    assertion unless we also assert the totals are non-zero and match intent.

Everything below therefore asserts *amounts and identities*, never just status.
"""

import re
from decimal import Decimal
from urllib.parse import urlparse

from extensions import db
from models.gl import GLJournalEntry, GLJournalLine, GLAccount
from models.warehouse import StockMovement
from models.product import Product

TWO = Decimal('0.01')
THREE = Decimal('0.001')

# Canonical leaf account codes, taken from
# services/gl_service.py::GLService.ensure_core_accounts (the production tree).
# These are authoritative: 1000/1100/2000/3000/4000/5000 are HEADERS, Cash is
# 1110, AR is 1130, Inventory is 1140, AP is 2110, Sales Revenue is 4100.
ACC = {
    'cash':               '1110',
    'bank':               '1120',
    'bank_savings':       '1121',
    'ar':                 '1130',
    'inventory':          '1140',
    'cheques_collection': '1150',
    'ap':                 '2110',
    'merchants_payable':  '2115',
    'deferred_cheques':   '2120',
    'tax_payable':        '2130',
    'salaries_payable':   '2140',
    'sales_revenue':      '4100',
    'service_revenue':    '4200',
    'shipping_revenue':   '4300',
    'fx_gain':            '4400',
    'cogs':               '5100',
    'inventory_adj':      '5150',
    'discounts_given':    '5200',
    'shipping_expense':   '5300',
    'salaries':           '6100',
    'rent':               '6200',
    'utilities':          '6300',
    'supplies':           '6400',
    'fx_loss':            '6900',
    'bank_charges':       '6950',
    'other_expenses':     '6990',
    'header_assets':      '1000',
    'header_liabs':       '2000',
    'header_equity':      '3000',
    'header_revenue':     '4000',
    'header_cos':         '5000',
    'header_opex':        '6000',
}


def q2(v) -> Decimal:
    return Decimal(str(v)).quantize(TWO)


def q3(v) -> Decimal:
    return Decimal(str(v)).quantize(THREE)


# ---------------------------------------------------------------------------
# Request builders (field names taken verbatim from the route handlers)
# ---------------------------------------------------------------------------

def manual_entry_form(description, lines, entry_date=None, notes=None):
    """POST body for POST /ledger/manual-entry.

    Route contract (routes/ledger.py:387):
      description, entry_date (YYYY-MM-DD), notes
      line_{i}_account  -> account CODE (string), loop breaks when absent
      line_{i}_debit / line_{i}_credit
    Lines with debit == 0 AND credit == 0 are dropped by the route.
    """
    data = {'description': description}
    if entry_date:
        data['entry_date'] = entry_date
    if notes:
        data['notes'] = notes
    for i, ln in enumerate(lines):
        data[f'line_{i}_account'] = ln['account']
        data[f'line_{i}_debit'] = str(ln.get('debit', 0))
        data[f'line_{i}_credit'] = str(ln.get('credit', 0))
        data[f'line_{i}_description'] = ln.get('description', '')
    # A terminator row so the server-side while-loop has a hard stop even if a
    # caller passes a zero-amount final line.
    data[f'line_{len(lines)}_account'] = ''
    return data


def sale_form(customer, lines, warehouse=None, currency=None,
              exchange_rate=None, discount_amount=0, shipping_cost=0,
              tax_rate=0, payment_amount=0, payment_method='cash', notes=None):
    """POST body for POST /sales/create (routes/sales.py:64)."""
    data = {
        'customer_id': str(customer.id),
        'line_count': str(len(lines)),
    }
    for i, ln in enumerate(lines):
        data[f'lines[{i}][product_id]'] = str(ln['product_id'])
        data[f'lines[{i}][quantity]'] = str(ln['quantity'])
        data[f'lines[{i}][unit_price]'] = str(ln.get('unit_price', 0))
        data[f'lines[{i}][discount_percent]'] = str(ln.get('discount_percent', 0))
    if warehouse is not None:
        data['warehouse_id'] = str(warehouse.id)
    if currency:
        data['currency'] = currency
    if exchange_rate is not None:
        data['exchange_rate'] = str(exchange_rate)
    data['discount_amount'] = str(discount_amount)
    data['shipping_cost'] = str(shipping_cost)
    data['tax_rate'] = str(tax_rate)
    data['payment_amount'] = str(payment_amount)
    data['payment_method'] = payment_method
    if notes:
        data['notes'] = notes
    return data


def purchase_form(supplier, lines, warehouse=None, currency=None,
                  exchange_rate=None, discount_amount=0, tax_rate=0,
                  payment_amount=0, payment_method='cash', notes=None):
    """POST body for POST /purchases/create (routes/purchases.py:129-175).

    NOTE the cost field is `unit_cost`, NOT `unit_price` as on /sales/create.
    Sending unit_price here silently drops the line, exactly like the
    lines-0-account_id mistake on the ledger form.
    """
    data = {
        'supplier_id': str(supplier.id),
        'line_count': str(len(lines)),
    }
    if supplier.name:
        data['supplier_name'] = supplier.name
    if warehouse is not None:
        data['warehouse_id'] = str(warehouse.id)
    if currency:
        data['currency'] = currency
    if exchange_rate is not None:
        data['exchange_rate'] = str(exchange_rate)
    data['discount_amount'] = str(discount_amount)
    data['tax_rate'] = str(tax_rate)
    data['payment_amount'] = str(payment_amount)
    data['payment_method'] = payment_method
    if notes:
        data['notes'] = notes
    for i, ln in enumerate(lines):
        data[f'lines[{i}][product_id]'] = str(ln['product_id'])
        data[f'lines[{i}][quantity]'] = str(ln['quantity'])
        data[f'lines[{i}][unit_cost]'] = str(ln.get('unit_cost', 0))
        data[f'lines[{i}][discount_percent]'] = str(ln.get('discount_percent', 0))
    return data


def purchase_id_from_redirect(response):
    location = response.headers.get('Location', '')
    match = re.search(r'/purchases/(\d+)', urlparse(location).path)
    return int(match.group(1)) if match else None


def add_stock_form(quantity, warehouse=None, notes=None):
    """POST body for /warehouse/add-stock/<product_id> (routes/warehouse.py:262)."""
    data = {'quantity': str(quantity)}
    if warehouse is not None:
        data['warehouse_id'] = str(warehouse.id)
    if notes:
        data['notes'] = notes
    return data


def product_adjust_form(adjustment_type='add', quantity=0, reason='adjustment',
                        notes=None):
    """POST body for /products/<id>/adjust-stock (routes/products.py:577).

    The handler answers JSON and returns HTTP 200 even when it refuses the
    adjustment (success=False), so callers must assert on the flag.
    """
    data = {
        'adjustment_type': adjustment_type,
        'quantity': str(quantity),
        'reason': reason,
    }
    if notes:
        data['notes'] = notes
    return data


def cheque_form(customer=None, supplier=None, amount=0, cheque_number='',
                bank_name='', issue_date=None, due_date=None, currency=None,
                exchange_rate=None, **extra):
    """POST body for POST /cheques/create (routes/cheques.py:130-215).

    issue_date and due_date must be %Y-%m-%d: the handler calls
    datetime.strptime(request.form.get('issue_date'), '%Y-%m-%d') with no
    guard, so a missing value raises and is swallowed into a 200 re-render.
    """
    data = {
        'amount': str(amount),
        'cheque_bank_number': cheque_number,
        'bank_name': bank_name,
        'issue_date': issue_date,
        'due_date': due_date,
    }
    if customer is not None:
        data['customer_id'] = str(customer.id)
    if supplier is not None:
        data['supplier_id'] = str(supplier.id)
    if currency:
        data['currency'] = currency
    if exchange_rate is not None:
        data['exchange_rate'] = str(exchange_rate)
    data.update(extra)
    return {k: v for k, v in data.items() if v is not None}


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

_ENTRY_RE = re.compile(r'/(?:ledger/)?entry/(\d+)')


def entry_id_from_redirect(response):
    """Extract the created GL entry id from the post-POST redirect target.

    The manual-entry and reverse routes answer 302 to ledger.view_entry, so the
    new entry id lives in the Location header. Reading response.json instead
    (as the first attempt did) never yields an id for an HTML redirect, which
    silently disabled every GL assertion.
    """
    location = response.headers.get('Location', '')
    match = _ENTRY_RE.search(urlparse(location).path)
    if not match:
        return None
    return int(match.group(1))


def sale_id_from_redirect(response):
    location = response.headers.get('Location', '')
    match = re.search(r'/sales/(\d+)', urlparse(location).path)
    return int(match.group(1)) if match else None


def is_login_redirect(response):
    return '/auth/login' in response.headers.get('Location', '')


# ---------------------------------------------------------------------------
# Validators — hard assertions on amounts, identity and isolation
# ---------------------------------------------------------------------------

def get_entry_lines(entry_id):
    """Return {account_code: (debit, credit)} for an entry."""
    entry = db.session.get(GLJournalEntry, entry_id)
    assert entry is not None, f'GL entry {entry_id} does not exist'
    lines = GLJournalLine.query.filter_by(entry_id=entry_id).order_by(
        GLJournalLine.id).all()
    out = {}
    for ln in lines:
        code = db.session.get(GLAccount, ln.account_id).code
        prev_d, prev_c = out.get(code, (Decimal('0'), Decimal('0')))
        out[code] = (prev_d + q3(ln.debit), prev_c + q3(ln.credit))
    return entry, out


def assert_entry_balanced_and_non_trivial(entry_id, expect_total=None):
    """Double-entry integrity PLUS a non-zero guard.

    The non-zero guard is the whole point: GLService.create_manual_entry accepts
    an empty line list because 0 == 0. A test that only checks balance would
    pass on a meaningless entry.
    """
    entry, by_code = get_entry_lines(entry_id)
    total_debit = sum((d for d, _ in by_code.values()), Decimal('0'))
    total_credit = sum((c for _, c in by_code.values()), Decimal('0'))

    assert entry.total_debit == entry.total_credit, (
        f'{entry.entry_number}: header unbalanced '
        f'{entry.total_debit} != {entry.total_credit}')
    assert total_debit == total_credit, (
        f'{entry.entry_number}: lines unbalanced {total_debit} != {total_credit}')
    assert total_debit > 0, (
        f'{entry.entry_number}: TRIVIAL ENTRY — total is 0. The POST body did '
        f'not match the route field names, so no line was accepted. '
        f'lines={by_code}')
    assert len(by_code) >= 2, (
        f'{entry.entry_number}: expected >=2 accounts touched, got {len(by_code)}')
    if expect_total is not None:
        assert q3(total_debit) == q3(expect_total), (
            f'{entry.entry_number}: expected total {q3(expect_total)}, '
            f'got {q3(total_debit)}')
    return entry, by_code


def assert_entry_accounts(entry_id, expected):
    """expected: {account_code: (debit, credit)} compared exactly."""
    entry, by_code = get_entry_lines(entry_id)
    assert set(by_code) == set(expected), (
        f'{entry.entry_number}: accounts {sorted(by_code)} != '
        f'expected {sorted(expected)}')
    for code, (exp_d, exp_c) in expected.items():
        got_d, got_c = by_code[code]
        assert got_d == q3(exp_d), (
            f'{entry.entry_number} {code}: debit {got_d} != {exp_d}')
        assert got_c == q3(exp_c), (
            f'{entry.entry_number} {code}: credit {got_c} != {exp_c}')
    return entry, by_code


def assert_no_entry_created(before_ids, action_desc=''):
    """Negative control: the action under test must not post a GL entry."""
    after_ids = {e.id for e in GLJournalEntry.query.all()}
    new_ids = after_ids - set(before_ids)
    assert not new_ids, (
        f'{action_desc}: expected no new GL entry, but {sorted(new_ids)} '
        f'were posted')


def snapshot_entry_ids():
    return {e.id for e in GLJournalEntry.query.all()}


def entries_for_reference(reference_type, reference_id):
    """All GL entries posted against a business document, oldest first."""
    entries = GLJournalEntry.query.filter_by(
        reference_type=reference_type,
        reference_id=reference_id,
    ).order_by(GLJournalEntry.id).all()
    return entries


def lines_for_entries(entries):
    """Merge {code: (debit, credit)} across several entries."""
    merged = {}
    for entry in entries:
        _, by_code = get_entry_lines(entry.id)
        for code, (d, c) in by_code.items():
            pd, pc = merged.get(code, (Decimal('0'), Decimal('0')))
            merged[code] = (pd + d, pc + c)
    return merged


def assert_no_header_account_posted(entry_id):
    """A posting to a header account is an accounting-integrity defect.

    services/sale_service.py maps COGS -> '5000', but 5000 is a HEADER in the
    canonical tree (ensure_core_accounts marks it is_header=True). create_manual
    _entry refuses headers; this guards the service-posted paths too.
    """
    entry, by_code = get_entry_lines(entry_id)
    for code in by_code:
        acc = GLAccount.query.filter_by(code=code).first()
        assert acc is not None, f'{code} not in chart of accounts'
        assert acc.is_header is False, (
            f'{entry.entry_number}: posted to HEADER account {code} '
            f'({acc.name_en or acc.name}) — must post to a leaf')


def assert_product_stock(product_id, expected):
    p = db.session.get(Product, product_id)
    assert p is not None, f'product {product_id} missing'
    assert q3(p.current_stock) == q3(expected), (
        f'product {p.sku}: stock {q3(p.current_stock)} != {q3(expected)}')


def assert_stock_movement(product_id, movement_type, expected_qty,
                          warehouse_id=None):
    q = StockMovement.query.filter_by(product_id=product_id,
                                      movement_type=movement_type)
    if warehouse_id is not None:
        q = q.filter_by(warehouse_id=warehouse_id)
    moves = q.all()
    assert moves, (
        f'no {movement_type} movement recorded for product {product_id}')
    total = sum((q3(m.quantity) for m in moves), Decimal('0'))
    assert total == q3(expected_qty), (
        f'{movement_type} movement total {total} != {q3(expected_qty)}')


def assert_stock_valuation(product_id, expected_value):
    """stock qty x cost price, to the cent."""
    p = db.session.get(Product, product_id)
    value = q2(q3(p.current_stock) * q3(p.cost_price))
    assert value == q2(expected_value), (
        f'product {p.sku}: stock value {value} != {q2(expected_value)}')
