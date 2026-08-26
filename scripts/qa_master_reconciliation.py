"""
QA Master Reconciliation Engine (Agent 8 - QA Synthesizer & Master Reconciliation).

Standalone, deterministic, offline reconciliation harness.

It seeds a multi-entity scenario (2 customers, 1 supplier, sales with partial /
cheque / full-cash settlement, a purchase, an expense and manual GL entries)
using the PUBLIC business flows only (services + model methods), then computes
four independent reconciliation sections:

  1. Trial Balance      : sum(debits) == sum(credits) across ALL GL lines.
  2. Cash/Bank sanity   : GL movement of cash-family accounts
                          (1110 cash, 1120 bank-current, 1121 bank-savings,
                           1150 cheques-under-collection)
                          == receipts - non-cheque expenses (within period).
                          NOTE: cheque payments post to 1150 at creation time
                          regardless of confirmation status, so ALL sale
                          payments count as "receipts" here.
  3. AR control         : GL balance of 1130 == sum(sale.amount_base -
                          sale.paid_amount_base) over confirmed sales of
                          regular customers. Pending-cheque nuance is handled
                          by confirming the seeded cheque before reconciling.
  4. Inventory          : GL movement of 1140 == sum(stock delta x cost),
                          where cost comes from the source document lines
                          (PurchaseLine effective cost / SaleLine cost snapshot).

Exit code is 0 when every section passes, 1 otherwise.
main(check_only=True) runs in-process and returns a result dict instead of
exiting (used by tests/integration/test_master_reconciliation.py).

CHAOS CONTRACT (verified by tests): raw GLJournalEntry/GLJournalLine creation
bypassing the service layer is NOT blocked by any DB constraint TODAY - an
unbalanced entry persists silently and can only be detected by the trial
balance audit in section 1. The service layer (GLService.create_manual_entry /
post_entry) DOES raise ValueError on unbalanced input.
"""

import io
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal


def _utcnow():
    """Naive UTC now (DB stores naive datetimes); avoids deprecated utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'qa-master-reconciliation-secret-key')
os.environ.setdefault('OWNER_PASSWORD', 'TestOwner@1234567890123456!')
os.environ.setdefault('DEBUG', 'true')
os.environ.setdefault('WTF_CSRF_ENABLED', 'false')
os.environ.setdefault('RATELIMIT_ENABLED', 'false')
os.environ.setdefault('RATELIMIT_STORAGE_URI', 'memory://')
os.environ.setdefault('CACHE_TYPE', 'flask_caching.backends.SimpleCache')

# التسوية يجب أن تعمل على قاعدة معزولة حتمية — في CI قد يكون DATABASE_URL
# يشير لـPostgres مشتركة فتُصطدم البذرة بقيود UNIQUE من تشغيل سابق
# (roles_name_key) وينهار drop_all على مفاتيح FK. العزل إجباري ما لم يُطلب خلافه.
if os.environ.get('QMR_ALLOW_EXTERNAL_DB') != '1':
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
_ISOLATED_DB = os.environ.get('DATABASE_URL', '').startswith('sqlite')

from app import create_app  # noqa: E402
from extensions import db as _db  # noqa: E402

TOLERANCE = Decimal('0.0001')
CASH_FAMILY_CODES = ('1110', '1120', '1121', '1150')
AR_CONTROL_CODE = '1130'
INVENTORY_CODE = '1140'
CHEQUE_EXPENSE_CREDIT_CODE = '2110'


class _AbsorbentStream:
    """Minimal writable sink whose close() is a no-op.

    extensions.setup_logging rebinds ``sys.stdout = TextIOWrapper(
    sys.stdout.buffer, ...)`` on EVERY create_app(). When those transient
    wrappers are garbage-collected they close the underlying buffer — which
    under pytest is the shared capture file, killing all later output.
    Pointing them at this sink absorbs both the wrapping and the closing.
    """

    def write(self, data):
        return len(data)

    def flush(self):
        pass

    def close(self):
        pass

    def isatty(self):
        return False

    def writable(self):
        return True

    def readable(self):
        return False

    def seekable(self):
        return False

    @property
    def encoding(self):
        return 'utf-8'

    @property
    def closed(self):
        return False


class _Utf8Passthrough:
    """Text-stream shim over a raw buffer: UTF-8 always, close-inert.

    Downstream code (extensions.setup_logging) wraps and later abandons
    sys.stdout/stderr; when those transient TextIOWrappers are garbage
    collected they call close() on this object instead of the real console
    buffer, so the cascade can never shut down the process streams.
    """

    def __init__(self, raw):
        self._raw = raw

    def write(self, text):
        try:
            data = str(text).encode('utf-8', errors='replace')
        except Exception:
            return 0
        try:
            return self._raw.write(data)
        except Exception:
            return len(data)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        try:
            self._raw.flush()
        except Exception:
            pass

    def close(self):
        pass

    def isatty(self):
        try:
            return self._raw.isatty()
        except Exception:
            return False

    def readable(self):
        return False

    def seekable(self):
        return False

    def writable(self):
        return True

    @property
    def encoding(self):
        return 'utf-8'

    @property
    def errors(self):
        return 'replace'

    @property
    def closed(self):
        return False

    @property
    def buffer(self):
        return _CloseInertBuffer(self._raw)


class _CloseInertBuffer:
    """Binary shim delegating writes; close()/__del__ can never kill the real
    buffer when transient TextIOWrappers wrapping us are garbage-collected."""

    def __init__(self, raw):
        self._raw = raw

    def write(self, data):
        try:
            return self._raw.write(data)
        except Exception:
            return len(data)

    def flush(self):
        try:
            self._raw.flush()
        except Exception:
            pass

    def close(self):
        pass

    def isatty(self):
        try:
            return self._raw.isatty()
        except Exception:
            return False

    def writable(self):
        return True

    def readable(self):
        return False

    def seekable(self):
        return False

    @property
    def closed(self):
        return False


_STREAM_KEEPALIVE = []


def _install_utf8_console_streams():
    """Install close-inert UTF-8 process streams for stdout/stderr.

    App listeners (e.g. services/real_time_listeners.py) print emoji/Arabic
    unconditionally; legacy cp1252 consoles raise UnicodeEncodeError. The
    historical behaviour of extensions.setup_logging was a persistent UTF-8
    rebinding - reproduced here without ownership of the underlying buffers.
    Instances are kept referenced forever so nothing ever finalizes them.
    Skipped under pytest: capture owns the streams there and tests run quiet,
    so any rebidding only endangers the shared capture files.
    """
    if 'PYTEST_CURRENT_TEST' in os.environ or 'pytest' in sys.modules:
        return
    for name in ('stdout', 'stderr'):
        current = getattr(sys, name)
        if isinstance(current, _Utf8Passthrough):
            continue
        raw = getattr(current, 'buffer', None) or getattr(
            sys, f'__{name}__', None) or _AbsorbentStream()
        target = _Utf8Passthrough(raw)
        setattr(sys, name, target)
        _STREAM_KEEPALIVE.append(target)


def build_app():
    """Build a fresh Flask app bound to an in-memory SQLite database."""
    from contextlib import contextmanager

    @contextmanager
    def _guarded():
        saved = (sys.stdout, sys.stderr)
        decoys = (
            io.TextIOWrapper(_AbsorbentStream(), encoding='utf-8',
                             errors='replace'),
            io.TextIOWrapper(_AbsorbentStream(), encoding='utf-8',
                             errors='replace'),
        )
        sys.stdout, sys.stderr = decoys
        try:
            yield
        finally:
            # Decoys are NEVER closed: background app threads may hold them
            # past this point and closing raises into their excepthooks.
            # They are inert (absorbent sink) and garbage collection of their
            # wrappers closes only the no-op sink.
            _STREAM_KEEPALIVE.extend(decoys)
            sys.stdout, sys.stderr = saved

    with _guarded():
        app = create_app()
    if 'pytest' not in sys.modules:
        _install_utf8_console_streams()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {}
    return app


def _mk_user():
    from models import User, Role
    role = Role(name='QA Owner', name_ar='مالك', slug=f"qa-owner-{_utcnow().timestamp()}")
    _db.session.add(role)
    _db.session.flush()
    user = User(
        username=f"qa_master_owner_{_utcnow().timestamp():.0f}",
        email='qa_master@example.com',
        full_name='QA Master Owner',
        is_owner=True,
        is_active=True,
        role_id=role.id,
    )
    user.set_password('QaMasterPass123!')
    _db.session.add(user)
    _db.session.flush()
    return user


def seed_scenario():
    """Seed the deterministic multi-entity scenario via public flows."""
    from models import (
        Customer, Supplier, Warehouse, Product, ProductCategory,
        Purchase, PurchaseLine, Expense, ExpenseCategory,
    )
    from services.gl_service import GLService
    from services.sale_service import SaleService
    from services.stock_service import StockService
    from utils.helpers import generate_number

    period_start = _utcnow() - timedelta(days=1)
    period_end = _utcnow() + timedelta(days=1)

    owner = _mk_user()

    warehouse = Warehouse(name='QA Main WH', name_ar='مستودع الجودة',
                          code='WH-QA-01', is_active=True, is_main=True)
    category = ProductCategory(name='QA Spare Parts', name_ar='قطع غيار')
    _db.session.add_all([warehouse, category])
    _db.session.flush()

    product = Product(
        name='QA Brake Pad', name_ar='فحمات فرامل', sku='SKU-QA-001',
        category_id=category.id,
        cost_price=Decimal('25.000'), regular_price=Decimal('100.000'),
        current_stock=Decimal('10'), min_stock_alert=Decimal('2'),
        is_active=True,
    )
    customer_a = Customer(name='Alpha Trading LLC', customer_type='regular',
                          credit_limit=Decimal('0'), balance=Decimal('0'), is_active=True)
    customer_b = Customer(name='Beta Motors LLC', customer_type='regular',
                          credit_limit=Decimal('0'), balance=Decimal('0'), is_active=True)
    supplier = Supplier(name='Gulf Parts Co', supplier_type='parts', is_active=True)
    _db.session.add_all([product, customer_a, customer_b, supplier])
    _db.session.commit()

    sales_log = []

    # --- Purchase: 5 units @ 60 -> Inventory Dr 300, AP Cr 300; stock 10 -> 15 ---
    purchase = Purchase(
        purchase_number=generate_number('PUR', Purchase, 'purchase_number'),
        supplier_id=supplier.id, warehouse_id=warehouse.id,
        supplier_name=supplier.name, currency='ILS', exchange_rate=Decimal('1'),
        tax_rate=Decimal('0'), discount_amount=Decimal('0'),
        subtotal=Decimal('0'), tax_amount=Decimal('0'),
        total_amount=Decimal('0'), amount_base=Decimal('0'),
        user_id=owner.id, status='confirmed',
    )
    _db.session.add(purchase)
    _db.session.flush()
    p_line = PurchaseLine(purchase_id=purchase.id, product_id=product.id,
                          quantity=Decimal('5'), unit_cost=Decimal('60.000'))
    p_line.calculate_line_total()
    _db.session.add(p_line)
    purchase.calculate_totals()
    StockService.process_purchase_lines(purchase, warehouse.id)
    GLService.ensure_core_accounts()
    GLService.post_entry(
        [
            {'account': INVENTORY_CODE, 'debit': purchase.subtotal,
             'description': f'شراء بضاعة {purchase.purchase_number}'},
            {'account': CHEQUE_EXPENSE_CREDIT_CODE, 'credit': purchase.total_amount,
             'description': f'ذمم دائنة - مورد: {supplier.name}'},
        ],
        description=f'Purchase {purchase.purchase_number}',
        reference_type='Purchase', reference_id=purchase.id,
        currency=purchase.currency, exchange_rate=purchase.exchange_rate,
    )
    supplier.update_statistics()
    _db.session.commit()

    def _pay(sale, amount, method, **kw):
        payment = SaleService.create_payment_for_sale(
            sale=sale, amount=amount, payment_method=method,
            currency='ILS', exchange_rate=1.0, **kw)
        if method == 'cheque':
            payment.confirm_payment()
        sale.recalculate_payment_status()
        _db.session.commit()
        return payment

    # --- Sale A1 (partial cash): 3 @ 100 = 300; paid 100 cash; balance 200 ---
    s1 = SaleService.create_sale(
        customer=customer_a, seller=owner,
        lines_data=[{'product': product, 'quantity': Decimal('3'),
                     'unit_price': Decimal('100.000')}],
        currency='ILS', warehouse_id=warehouse.id)
    pay1 = _pay(s1, Decimal('100.000'), 'cash')
    sales_log.append({'number': s1.sale_number, 'customer': customer_a.name,
                      'total': s1.total_amount, 'paid': s1.paid_amount_base,
                      'balance': s1.balance_due, 'method': 'cash/partial'})

    # --- Sale A2 (full cash at creation): 2 @ 50 = 100 ---
    s2 = SaleService.create_sale(
        customer=customer_a, seller=owner,
        lines_data=[{'product': product, 'quantity': Decimal('2'),
                     'unit_price': Decimal('50.000')}],
        currency='ILS', warehouse_id=warehouse.id,
        payment_data={'amount': 100, 'payment_method': 'cash'})
    s2.recalculate_payment_status()
    _db.session.commit()
    sales_log.append({'number': s2.sale_number, 'customer': customer_a.name,
                      'total': s2.total_amount, 'paid': s2.paid_amount_base,
                      'balance': s2.balance_due, 'method': 'cash/full'})

    # --- Sale B1 (cheque): 4 @ 75 = 300; settled by confirmed cheque ---
    s3 = SaleService.create_sale(
        customer=customer_b, seller=owner,
        lines_data=[{'product': product, 'quantity': Decimal('4'),
                     'unit_price': Decimal('75.000')}],
        currency='ILS', warehouse_id=warehouse.id)
    pay3 = _pay(s3, Decimal('300.000'), 'cheque',
                cheque_number='CHQ-QA-3001', cheque_date='2026-12-31',
                bank_name='Emirates NBD')
    sales_log.append({'number': s3.sale_number, 'customer': customer_b.name,
                      'total': s3.total_amount, 'paid': s3.paid_amount_base,
                      'balance': s3.balance_due, 'method': 'cheque/confirmed'})

    # --- Expense (cash): Dr 6200 rent 200 / Cr 1110 cash 200 ---
    exp_category = ExpenseCategory(name='QA Rent', gl_account_code='6200')
    _db.session.add(exp_category)
    _db.session.flush()
    expense = Expense(
        expense_number=generate_number('EXP', Expense, 'expense_number'),
        category_id=exp_category.id, description='QA office rent',
        amount=Decimal('200.000'), amount_base=Decimal('200.000'),
        currency='ILS', exchange_rate=Decimal('1'),
        payment_method='cash', status='confirmed', user_id=owner.id,
    )
    _db.session.add(expense)
    _db.session.flush()
    GLService.post_entry(
        [
            {'account': exp_category.gl_account_code, 'debit': expense.amount,
             'description': expense.description},
            {'account': '1110', 'credit': expense.amount_base,
             'description': f"دفع {expense.payment_method}"},
        ],
        description=f'Expense {expense.expense_number}',
        reference_type='Expense', reference_id=expense.id,
        currency=expense.currency, exchange_rate=expense.exchange_rate,
    )
    _db.session.commit()

    # --- Manual entries (balanced, avoid controlled accounts) ---
    m1 = GLService.create_manual_entry(
        description='Accrued transportation bill',
        lines=[
            {'account_code': '6600', 'debit': Decimal('150.000')},
            {'account_code': '2110', 'credit': Decimal('150.000')},
        ],
        created_by=owner.id,
    )
    m2 = GLService.create_manual_entry(
        description='Accrued maintenance bill',
        lines=[
            {'account_code': '6400', 'debit': Decimal('75.000')},
            {'account_code': '2110', 'credit': Decimal('75.000')},
        ],
        created_by=owner.id,
    )

    scenario = {
        'period': (period_start, period_end),
        'owner': owner,
        'customers': 2,
        'suppliers': 1,
        'products': 1,
        'sales': sales_log,
        'payments': [pay1.payment_number, pay3.payment_number],
        'purchase': {'number': purchase.purchase_number,
                     'total': purchase.total_amount,
                     'stock_after': product.current_stock},
        'expenses': [{'number': expense.expense_number,
                      'amount': expense.amount_base}],
        'manual_entries': [m1.entry_number, m2.entry_number],
    }
    return scenario


def _d(value):
    return Decimal(str(value or 0))


def _gl_movement(code, date_from=None, date_to=None):
    """Net debit-minus-credit movement for one account code within a period."""
    from sqlalchemy import func
    from models import GLAccount, GLJournalEntry, GLJournalLine
    q = _db.session.query(func.sum(GLJournalLine.debit - GLJournalLine.credit)).join(
        GLJournalEntry, GLJournalLine.entry_id == GLJournalEntry.id).join(
        GLAccount, GLJournalLine.account_id == GLAccount.id).filter(
        GLAccount.code == code)
    if date_from:
        q = q.filter(GLJournalEntry.entry_date >= date_from)
    if date_to:
        q = q.filter(GLJournalEntry.entry_date <= date_to)
    return _d(q.scalar())


def _section(name, expected, actual, details):
    expected_d = _d(expected)
    actual_d = _d(actual)
    diff = abs(expected_d - actual_d)
    return {
        'name': name,
        'expected': expected_d,
        'actual': actual_d,
        'difference': diff,
        'passed': diff <= TOLERANCE,
        'details': details,
    }


def check_trial_balance():
    """Section 1: sum(debit) == sum(credit) across ALL journal lines."""
    from sqlalchemy import func
    from models import GLJournalEntry, GLJournalLine
    total_debit = _d(_db.session.query(
        func.sum(GLJournalLine.debit)).scalar())
    total_credit = _d(_db.session.query(
        func.sum(GLJournalLine.credit)).scalar())

    unbalanced = []
    for entry in GLJournalEntry.query.all():
        e_dr = sum((ln.debit for ln in entry.lines), Decimal('0'))
        e_cr = sum((ln.credit for ln in entry.lines), Decimal('0'))
        if abs(e_dr - e_cr) > TOLERANCE:
            unbalanced.append(f"{entry.entry_number}: Dr={e_dr} Cr={e_cr}")

    details = [
        f"journal entries: {GLJournalEntry.query.count()}",
        f"journal lines: {GLJournalLine.query.count()}",
        f"unbalanced entries: {len(unbalanced)}",
    ] + [f"BREAK {row}" for row in unbalanced[:10]]
    return _section('Trial Balance (sum Dr == sum Cr)',
                    total_debit, total_credit, details)


def check_cash_bank(period):
    """Section 2: cash-family GL movement == receipts - non-cheque expenses."""
    from models import Payment, Expense
    date_from, date_to = period
    gl_movement = Decimal('0')
    per_account = {}
    for code in CASH_FAMILY_CODES:
        mv = _gl_movement(code, date_from, date_to)
        per_account[code] = mv
        gl_movement += mv

    receipts = _d(_db.session.query(_db.func.sum(Payment.amount_base)).filter(
        Payment.payment_date >= date_from,
        Payment.payment_date <= date_to).scalar())

    expenses_cash = Decimal('0')
    for exp in Expense.query.filter(
            Expense.expense_date >= date_from,
            Expense.expense_date <= date_to).all():
        if exp.payment_method != 'cheque':
            expenses_cash += _d(exp.amount_base)

    expected = receipts - expenses_cash
    details = [
        "GL movement per account: " + ", ".join(
            f"{c}={per_account[c]}" for c in CASH_FAMILY_CODES),
        f"receipts (all sale payments, incl. cheques posting to 1150): {receipts}",
        f"non-cheque expenses: {expenses_cash}",
        f"expected net cash-family movement: {expected}",
    ]
    return _section('Cash/Bank movement == receipts - expenses',
                    expected, gl_movement, details)


def check_ar_control(period):
    """Section 3: GL 1130 balance == business AR of regular customers."""
    from models import Sale, Customer
    date_from, date_to = period
    gl_ar = _gl_movement(AR_CONTROL_CODE, date_from, date_to)

    business_ar = Decimal('0')
    per_customer = {}
    sales = Sale.query.join(Customer, Sale.customer_id == Customer.id).filter(
        Sale.status == 'confirmed',
        Sale.sale_date >= date_from,
        Sale.sale_date <= date_to,
        Customer.customer_type == 'regular').all()
    for sale in sales:
        owed = _d(sale.amount_base) - _d(sale.paid_amount_base)
        business_ar += owed
        key = sale.customer.name if sale.customer else '?'
        per_customer[key] = per_customer.get(key, Decimal('0')) + owed

    details = [
        f"confirmed regular-customer sales counted: {len(sales)}",
    ] + [f"AR {name}={owed}" for name, owed in sorted(per_customer.items())] + [
        f"business AR total: {business_ar}",
    ]
    return _section(f'AR control ({AR_CONTROL_CODE}) vs open customer balances',
                    business_ar, gl_ar, details)


def check_inventory(period):
    """Section 4: GL 1140 movement == stock deltas x source-document costs."""
    from models import StockMovement, PurchaseLine, SaleLine, Product
    date_from, date_to = period
    gl_inv = _gl_movement(INVENTORY_CODE, date_from, date_to)

    purchase_costs = {}
    for ln in PurchaseLine.query.all():
        qty = _d(ln.quantity)
        if qty:
            purchase_costs[(ln.purchase_id, ln.product_id)] = _d(ln.line_total) / qty
    sale_costs = {}
    for ln in SaleLine.query.all():
        sale_costs[(ln.sale_id, ln.product_id)] = _d(ln.cost_price)

    expected = Decimal('0')
    movements = StockMovement.query.filter(
        StockMovement.created_at >= date_from,
        StockMovement.created_at <= date_to).all()
    unmapped = []
    for mv in movements:
        qty = _d(mv.quantity)
        if mv.movement_type == 'purchase' and mv.reference_type == 'Purchase':
            unit_cost = purchase_costs.get((mv.reference_id, mv.product_id))
        elif mv.movement_type == 'sale' and mv.reference_type == 'Sale':
            unit_cost = sale_costs.get((mv.reference_id, mv.product_id))
        else:
            unit_cost = None
        if unit_cost is None:
            product = _db.session.get(Product, mv.product_id)
            unit_cost = _d(product.cost_price if product else 0)
            unmapped.append(f"{mv.movement_type}:{mv.reference_type}")
        expected += qty * unit_cost

    details = [
        f"stock movements valued: {len(movements)}"
        + (f" (fallback-priced: {len(unmapped)})" if unmapped else ""),
        f"expected inventory delta value: {expected}",
    ]
    return _section(f'Inventory ({INVENTORY_CODE}) vs stock deltas x cost',
                    expected, gl_inv, details)


def collect_sections(period):
    sections = [
        check_trial_balance(),
        check_cash_bank(period),
        check_ar_control(period),
        check_inventory(period),
    ]
    return sections, all(s['passed'] for s in sections)


def render_report(scenario, sections, ok):
    period_start, period_end = scenario['period']
    width = 78
    lines = ["=" * width]
    lines.append("QA MASTER RECONCILIATION REPORT".center(width))
    lines.append("=" * width)
    lines.append(f"Period     : {period_start:%Y-%m-%d %H:%M} .. {period_end:%Y-%m-%d %H:%M} (UTC)")
    lines.append(
        f"Scenario   : customers={scenario['customers']} suppliers={scenario['suppliers']} "
        f"sales={len(scenario['sales'])} "
        f"purchase={1 if scenario['purchase'] else 0} "
        f"expenses={len(scenario['expenses'])} manual_entries={len(scenario['manual_entries'])}")
    for s in scenario['sales']:
        lines.append(
            f"  sale {s['number']:<16} {s['customer']:<20} total={s['total']:>10} "
            f"paid={s['paid']:>10} balance={s['balance']:>10} [{s['method']}]")
    lines.append(f"  purchase {scenario['purchase']['number']:<14} "
                 f"total={scenario['purchase']['total']:>10} "
                 f"stock_after={scenario['purchase']['stock_after']}")
    lines.append("-" * width)
    header = f"{'SECTION':<44}{'EXPECTED':>13}{'ACTUAL':>13}{'DIFF':>9}  STATUS"
    lines.append(header)
    lines.append("-" * width)
    for sec in sections:
        lines.append(
            f"{sec['name']:<44}{sec['expected']:>13,.3f}{sec['actual']:>13,.3f}"
            f"{sec['difference']:>9,.4f}  {'PASS' if sec['passed'] else 'FAIL'}")
        for d in sec['details']:
            lines.append(f"    · {d}")
    lines.append("-" * width)
    lines.append(f"RESULT: {'ALL SECTIONS PASS' if ok else 'RECONCILIATION BREAKS DETECTED'}")
    lines.append("=" * width)
    return "\n".join(lines)


def _emit(text):
    """Print UTF-8 text even on legacy cp-something consoles."""
    out = sys.stdout
    try:
        out.reconfigure(encoding='utf-8', errors='replace')
        out.write(text + '\n')
        return
    except Exception:
        pass
    buffer = getattr(out, 'buffer', None)
    if buffer is not None:
        try:
            buffer.write((text + '\n').encode('utf-8', errors='replace'))
            buffer.flush()
            return
        except Exception:
            pass
    print(text.encode('ascii', errors='replace').decode('ascii'))


def main(check_only=False, quiet=False, json_path=None):
    """Run the full seed + reconciliation cycle.

    check_only=True  -> return result dict (no process exit); used in-process by tests.
    check_only=False -> print report and sys.exit(0/1).
    json_path        -> additionally dump the machine-readable payload there.
    """
    import logging
    logging.raiseExceptions = False
    app = build_app()
    with app.app_context():
        _db.create_all()
        try:
            scenario = seed_scenario()
            sections, ok = collect_sections(scenario['period'])
            report = render_report(scenario, sections, ok)
        except Exception:
            _db.session.rollback()
            if _ISOLATED_DB:
                _db.drop_all()
            raise
        _db.session.remove()
        if _ISOLATED_DB:
            _db.drop_all()

    payload = {
        'passed': ok,
        'sections': [
            {'name': s['name'], 'expected': str(s['expected']),
             'actual': str(s['actual']), 'difference': str(s['difference']),
             'passed': bool(s['passed']), 'details': list(s['details'])}
            for s in sections],
        'scenario': {
            'customers': scenario['customers'],
            'suppliers': scenario['suppliers'],
            'sales': [dict(s) for s in scenario['sales']],
            'purchase': dict(scenario['purchase']),
            'expenses': list(scenario['expenses']),
            'manual_entries': list(scenario['manual_entries']),
        },
        'report': report,
    }
    if json_path:
        import json
        with open(json_path, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2, default=str)
    if not quiet:
        _emit(report)
    if check_only:
        return payload
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    _json_arg = None
    _argv = sys.argv[1:]
    if '--json' in _argv:
        _idx = _argv.index('--json')
        _json_arg = _argv[_idx + 1]
        _argv = _argv[:_idx] + _argv[_idx + 2:]
    main(check_only=False, quiet=False, json_path=_json_arg)
