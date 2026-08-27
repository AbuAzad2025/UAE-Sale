"""Dense ops coverage matrix for wave routes:
sales, payments, expenses, purchases, customers, suppliers, warehouse."""
import time
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import quote_plus
from uuid import uuid4

import pytest

from extensions import db
from models import (ArchivedRecord, Cheque, Customer, Expense, ExpenseCategory,
                    GLAccount, GLJournalEntry, GLJournalLine, Payment,
                    ProductCategory, Purchase, PurchaseLine, Receipt, Sale,
                    SaleLine, StockMovement, Supplier, Warehouse)


@pytest.fixture(autouse=True)
def _offline_rates():
    from services.currency_service import CurrencyService
    for base in ('AED', 'ILS'):
        CurrencyService._rates_cache[base] = {
            'timestamp': time.time(),
            'rates': {'AED': Decimal('1'), 'ILS': Decimal('1')},
        }
    yield


def _uniq(prefix=''):
    return f'{prefix}{uuid4().hex[:8].upper()}'


def _wh(**over):
    data = dict(name=_uniq('WH-'), location='Dubai', is_active=True)
    data.update(over)
    wh = Warehouse(**data)
    db.session.add(wh)
    db.session.commit()
    return wh


def _sup(**over):
    sup = Supplier(name=_uniq('مورد-'), is_active=True, **over)
    db.session.add(sup)
    db.session.commit()
    return sup


def _new_product(stock='100', min_alert='5'):
    from models import Product
    cat = ProductCategory(name=_uniq('فئة-'), is_active=True)
    db.session.add(cat)
    db.session.flush()
    prod = Product(name=_uniq('منتج-'), sku=_uniq('SKU-'), category_id=cat.id,
                   cost_price=Decimal('25.000'), regular_price=Decimal('50.000'),
                   current_stock=Decimal(stock), min_stock_alert=Decimal(min_alert),
                   is_active=True)
    db.session.add(prod)
    db.session.commit()
    return prod


def _new_customer():
    cust = Customer(name=_uniq('زبون-'), customer_type='regular', is_active=True,
                    credit_limit=Decimal('50000'))
    db.session.add(cust)
    db.session.commit()
    return cust


def _sale_http(client, customer_id, product_id, **over):
    data = {
        'customer_id': str(customer_id), 'line_count': '1',
        'lines[0][product_id]': str(product_id),
        'lines[0][quantity]': '2', 'lines[0][unit_price]': '50',
        'currency': 'AED', 'exchange_rate': '1',
    }
    data.update(over)
    return client.post('/sales/create', data=data)


def _voucher(**over):
    data = {
        'direction': 'outgoing', 'party_type': 'supplier',
        'payment_method': 'cash', 'currency': 'AED', 'exchange_rate': '1',
        'amount': '120', 'date': date.today().isoformat(),
    }
    data.update(over)
    return data


def _purchase_db(owner_user, supplier_obj, total='500'):
    pur = Purchase(purchase_number=_uniq('P-DB-'), supplier_id=supplier_obj.id,
                   supplier_name=supplier_obj.name, currency='AED',
                   exchange_rate=Decimal('1'), subtotal=Decimal(total),
                   total_amount=Decimal(total), amount_base=Decimal(total),
                   user_id=owner_user.id)
    db.session.add(pur)
    db.session.commit()
    return pur


def _gl_codes(reference_type, reference_id):
    rows = (db.session.query(GLAccount.code)
            .join(GLJournalLine, GLJournalLine.account_id == GLAccount.id)
            .join(GLJournalEntry, GLJournalLine.entry_id == GLJournalEntry.id)
            .filter(GLJournalEntry.reference_type == reference_type,
                    GLJournalEntry.reference_id == reference_id)
            .all())
    return {r[0] for r in rows}


# ---------------------------------------------------------------- access matrix

ANON_URLS = ['/sales/', '/payments/receipts', '/expenses/', '/purchases/',
             '/customers/', '/suppliers/', '/warehouse/']
SELLER_403 = ['/payments/receipts', '/expenses/', '/purchases/', '/suppliers/',
              '/warehouse/', '/warehouse/create']
MANAGER_403 = ['/expenses/', '/suppliers/', '/warehouse/']


def test_anon_all_lists_redirect_to_login(client):
    for url in ANON_URLS:
        resp = client.get(url)
        assert resp.status_code == 302, url
        assert '/auth/login' in resp.headers['Location']


def test_seller_permission_matrix_and_idor(client, login_seller, owner_user):
    seller_ok = ['/sales/', '/customers/']
    for url in seller_ok:
        assert client.get(url).status_code == 200, url
    for url in SELLER_403:
        assert client.get(url).status_code == 403, url

    cust = _new_customer()
    prod = _new_product()
    sale = Sale(sale_number=_uniq('S-OTH-'), customer_id=cust.id,
                seller_id=owner_user.id, total_amount=Decimal('100'),
                amount_base=Decimal('100'), paid_amount=Decimal('0'),
                paid_amount_base=Decimal('0'), balance_due=Decimal('100'),
                currency='AED', exchange_rate=Decimal('1'),
                payment_status='unpaid', status='confirmed', is_active=True)
    db.session.add(sale)
    db.session.flush()
    db.session.add(SaleLine(sale_id=sale.id, product_id=prod.id,
                            quantity=Decimal('1'), unit_price=Decimal('100'),
                            discount_percent=Decimal('0'),
                            line_total=Decimal('100'), cost_price=Decimal('10')))
    rcv = Receipt(receipt_number=_uniq('RCV-OTH-'), source_type='manual',
                  direction='incoming', customer_id=cust.id, amount=Decimal('30'),
                  currency='AED', exchange_rate=Decimal('1'),
                  amount_base=Decimal('30'), payment_method='cash',
                  user_id=owner_user.id)
    db.session.add(rcv)
    db.session.commit()

    for method, url in (('get', f'/sales/{sale.id}'), ('get', f'/sales/{sale.id}/print'),
                        ('get', f'/sales/{sale.id}/edit'), ('post', f'/sales/{sale.id}/delete'),
                        ('post', f'/sales/{sale.id}/cancel')):
        resp = getattr(client, method)(url)
        assert resp.status_code == 302, url
        assert 'login' not in resp.headers['Location'], url
    assert client.post(f'/payments/receipts/{rcv.id}').status_code == 405
    resp = client.get(f'/payments/receipts/{rcv.id}')
    assert resp.status_code == 403
    body = client.get('/sales/').get_data(as_text=True)
    assert sale.sale_number not in body


def test_manager_permission_matrix(client, manager_user):
    client.post('/auth/login', data={'username': 'testmanager',
                                     'password': 'ManagerPass123!'},
                follow_redirects=True)
    manager_ok = ['/sales/', '/customers/', '/payments/receipts', '/purchases/']
    for url in manager_ok:
        assert client.get(url).status_code == 200, url
    for url in MANAGER_403:
        assert client.get(url).status_code == 403, url


# ---------------------------------------------------------------- sales ops

def test_sales_owner_full_lifecycle(client, login_owner, main_wh):
    cust = _new_customer()
    prod = _new_product()

    r_create = _sale_http(client, cust.id, prod.id)
    assert r_create.status_code == 302
    loc = r_create.headers['Location']
    sale1 = Sale.query.one()
    assert loc.endswith(f'/sales/{sale1.id}')
    assert sale1.total_amount == Decimal('100')
    assert GLJournalEntry.query.filter_by(
        reference_type='Sale', reference_id=sale1.id).count() >= 2
    assert StockMovement.query.filter_by(
        reference_type='Sale', reference_id=sale1.id).count() == 1

    before = Sale.query.count()
    no_lines = client.post('/sales/create', data={'customer_id': str(cust.id),
                                                  'line_count': '0'})
    assert no_lines.status_code == 302
    assert Sale.query.count() == before

    assert client.get(f'/sales/{sale1.id}/print').status_code == 200
    assert client.get(f'/sales/{sale1.id}/edit').status_code == 200
    edit_ok = client.post(f'/sales/{sale1.id}/edit', data={
        'notes': 'ملاحظة معدلة', 'discount_amount': '10'})
    assert edit_ok.status_code == 302 and f"/{sale1.id}" in edit_ok.headers['Location']
    db.session.refresh(sale1)
    assert sale1.notes == 'ملاحظة معدلة'
    assert Decimal(str(sale1.discount_amount)) == Decimal('10')

    sale1.payment_status = 'paid'
    db.session.commit()
    blocked = client.get(f'/sales/{sale1.id}/edit')
    assert blocked.status_code == 302 and '/edit' not in blocked.headers['Location']
    sale1.payment_status = 'unpaid'
    db.session.commit()

    cancel_resp = client.post(f'/sales/{sale1.id}/cancel', follow_redirects=True)
    assert cancel_resp.status_code == 200
    reversals = GLJournalEntry.query.filter_by(
        reference_type='Sale', reference_id=sale1.id, entry_type='reversing').all()
    assert len(reversals) >= 2
    db.session.refresh(sale1)
    assert sale1.status == 'cancelled'
    cancelled_edit = client.get(f'/sales/{sale1.id}/edit')
    assert cancelled_edit.status_code == 302

    hard_id = sale1.id
    assert client.post(f'/sales/{hard_id}/delete', follow_redirects=True).status_code == 200
    assert db.session.get(Sale, hard_id) is None
    assert SaleLine.query.count() == 0
    assert GLJournalEntry.query.filter_by(
        reference_type='Sale', reference_id=hard_id).count() == 0

    linked = _sale_http(client, cust.id, prod.id, payment_amount='40',
                        payment_method='cash')
    sale2 = Sale.query.order_by(Sale.id.desc()).first()
    assert linked.status_code == 302
    assert Payment.query.filter_by(sale_id=sale2.id).count() == 1
    sid = sale2.id
    num = sale2.sale_number
    del_resp = client.post(f'/sales/{sid}/delete', follow_redirects=True)
    assert del_resp.status_code == 200
    assert 'ارتباطات مالية' in del_resp.get_data(as_text=True)
    assert ArchivedRecord.query.filter_by(
        table_name='sales', record_id=sid).count() == 1
    assert db.session.get(Sale, sid) is not None
    archived_page = client.get('/sales/archived')
    assert archived_page.status_code == 200
    assert num in archived_page.get_data(as_text=True)

    arch = client.post(f'/sales/{sid}/archive')
    assert arch.status_code == 302
    assert db.session.get(Sale, sid) is not None
    archived_again = GLJournalEntry.query.filter_by(
        reference_type='Sale', reference_id=sid, entry_type='reversing').all()
    assert len(archived_again) >= 2

    while ArchivedRecord.query.filter_by(
            table_name='sales', record_id=sid).count() > 0:
        assert client.post(f'/sales/{sid}/restore').status_code == 302
    assert ArchivedRecord.query.filter_by(
        table_name='sales', record_id=sid).count() == 0

    body = client.get('/sales/?search=Test+Customer').get_data(as_text=True)
    body2 = client.get('/sales/?payment_status=partial').get_data(as_text=True)
    assert isinstance(body, str) and isinstance(body2, str)

    missing = client.get('/sales/api/get-price')
    assert missing.status_code == 400
    not_found = client.get(
        f'/sales/api/get-price?product_id=999999&customer_id={cust.id}')
    assert not_found.status_code == 404
    ok = client.get(
        f'/sales/api/get-price?product_id={prod.id}&customer_id={cust.id}')
    payload = ok.get_json()
    assert ok.status_code == 200
    assert payload['price'] == 50.0
    assert payload['current_stock'] == pytest.approx(98.0)
    assert 'unit' in payload

    empty_calc = client.post('/sales/api/calculate-totals', json={})
    assert empty_calc.status_code == 400
    calc = client.post('/sales/api/calculate-totals', json={
        'lines': [{'quantity': 2, 'unit_price': 50, 'discount_percent': 10}],
        'discount_amount': 0, 'shipping_cost': 5, 'tax_rate': 10})
    cdata = calc.get_json()
    assert calc.status_code == 200 and cdata['success'] is True
    assert cdata['subtotal'] == pytest.approx(90.0)
    assert cdata['tax_amount'] == pytest.approx(9.5)
    assert cdata['total'] == pytest.approx(104.5)


@pytest.fixture
def main_wh(db):
    return _wh(name=_uniq('WH-Main-'), code=_uniq('WMC-'), is_main=True)


# ---------------------------------------------------------------- payments ops

def test_payments_voucher_matrix_and_receipt_pages(client, login_owner):
    cust = _new_customer()
    sup = _sup()
    _wh(code=_uniq('WMC-'), is_main=True)

    combos = [
        ('incoming', 'customer', cust.id, 'cash'),
        ('incoming', 'supplier', sup.id, 'bank_transfer'),
        ('outgoing', 'supplier', sup.id, 'cash'),
        ('outgoing', 'customer', cust.id, 'card'),
    ]
    for direction, party_type, party_id, method in combos:
        resp = client.post('/payments/voucher/submit', data=_voucher(
            direction=direction, party_type=party_type, party_id=party_id,
            amount='120', payment_method=method))
        assert resp.status_code == 302
        assert '/payments/receipts' in resp.headers['Location']

    receipt = Receipt.query.filter(Receipt.cheque_id.is_(None)).one()
    assert receipt.direction == 'incoming' and receipt.source_type == 'manual'
    assert receipt.amount_base == Decimal('120')
    assert {'1110'} <= _gl_codes('Receipt', receipt.id)

    incoming_payment = Payment.query.filter_by(direction='incoming').one()
    assert incoming_payment.supplier_id == sup.id
    assert incoming_payment.payment_type == 'refund'

    cash_out = Payment.query.filter_by(direction='outgoing',
                                       supplier_id=sup.id).one()
    assert cash_out.payment_type == 'bill_payment'
    assert {'2110', '1110'} <= _gl_codes('Payment', cash_out.id)

    card_out = Payment.query.filter_by(customer_id=cust.id,
                                       direction='outgoing').one()
    assert card_out.payment_type == 'refund'
    assert {'1130', '1120'} <= _gl_codes('Payment', card_out.id)

    chq_num = _uniq('CHQ-V-')
    cheque_post = client.post('/payments/voucher/submit', data=_voucher(
        party_id=sup.id, amount='300', payment_method='cheque',
        cheque_number=chq_num,
        cheque_date=(date.today() + timedelta(days=7)).isoformat(),
        bank_name='بنك دبي'))
    assert cheque_post.status_code == 302
    out_chq = Cheque.query.one()
    assert out_chq.cheque_number == chq_num and out_chq.status == 'pending'
    assert {'2110', '2120'} <= _gl_codes('cheque_issue', out_chq.id)

    inc_chq_num = _uniq('CHQ-IN-')
    client.post('/payments/voucher/submit', data=_voucher(
        direction='incoming', party_type='customer', party_id=cust.id,
        amount='90', payment_method='cheque', cheque_number=inc_chq_num,
        cheque_date=date.today().isoformat(), bank_name='بنك الشارقة'))
    inc_rcv = Receipt.query.order_by(Receipt.id.desc()).first()
    assert inc_rcv.cheque_id is not None
    assert {'1150', '1130'} <= _gl_codes('cheque_receive', inc_rcv.cheque_id)

    warn = client.post('/payments/voucher/submit', data={
        'direction': 'outgoing'}, follow_redirects=True)
    assert 'يرجى تعبئة جميع الحقول الإلزامية' in warn.get_data(as_text=True)

    numbers = [r.receipt_number for r in Receipt.query.all()]
    page1 = client.get('/payments/receipts?per_page=2&page=1').get_data(as_text=True)
    page2 = client.get('/payments/receipts?per_page=2&page=2').get_data(as_text=True)
    visible = [n for n in numbers if n in page1 or n in page2]
    assert len(visible) >= 1
    incoming_only = client.get(
        '/payments/receipts?direction=incoming&per_page=50').get_data(as_text=True)
    pay_rows = Payment.query.filter_by(direction='outgoing').all()
    for pr in pay_rows[:1]:
        assert pr.payment_number not in incoming_only

    assert client.get('/payments/receipts/create').status_code == 302
    target = Receipt.query.filter(Receipt.cheque_id.is_(None)).first()
    assert client.get(f'/payments/receipts/{target.id}').status_code == 200
    assert client.get(f'/payments/receipts/{target.id}/print').status_code == 200

    client.post(f'/payments/receipts/{target.id}/archive')
    archived_body = client.get('/payments/archived')
    assert archived_body.status_code == 200
    assert target.receipt_number in archived_body.get_data(as_text=True)
    assert target.receipt_number not in client.get(
        '/payments/receipts').get_data(as_text=True)
    assert client.post(f'/payments/receipts/{target.id}/restore',
                       follow_redirects=True).status_code == 200
    assert ArchivedRecord.query.filter_by(table_name='receipts').count() == 0

    vid = target.id
    hard_del = client.post(f'/payments/receipts/{vid}/delete', follow_redirects=True)
    assert hard_del.status_code == 200
    assert 'نهائياً' in hard_del.get_data(as_text=True)
    assert db.session.get(Receipt, vid) is None
    assert GLJournalEntry.query.filter_by(
        reference_type='Receipt', reference_id=vid).count() == 0


def test_payments_from_sale_allocation_and_linked_delete_reversal(
        client, login_owner, main_wh, test_sale):
    page = client.get(f'/payments/create_from_sale/{test_sale.id}')
    assert page.status_code == 200

    miss = client.post(f'/payments/create_from_sale/{test_sale.id}',
                       data={'amount': '40'}, follow_redirects=True)
    assert 'يرجى اختيار طريقة الدفع' in miss.get_data(as_text=True)
    assert Receipt.query.count() == 0

    alloc = client.post(f'/payments/create_from_sale/{test_sale.id}', data={
        'amount': '40', 'currency': 'AED', 'exchange_rate': '1',
        'payment_method': 'cash'})
    assert alloc.status_code == 302
    rcv = Receipt.query.one()
    assert rcv.source_type == 'sale' and rcv.source_id == test_sale.id
    db.session.refresh(test_sale)
    assert Decimal(str(test_sale.paid_amount)) == Decimal('40')
    assert Decimal(str(test_sale.balance_due)) == Decimal('60')
    assert test_sale.payment_status == 'partial'

    del_resp = client.post(f'/payments/receipts/{rcv.id}/delete', follow_redirects=True)
    assert del_resp.status_code == 200
    assert 'لوجود حركات مرتبطة' in del_resp.get_data(as_text=True)
    rid = rcv.id
    assert db.session.get(Receipt, rid) is not None
    assert ArchivedRecord.query.filter_by(
        table_name='receipts', record_id=rid).count() == 1
    entries = GLJournalEntry.query.filter_by(
        reference_type='Receipt', reference_id=rid).all()
    assert any(e.is_reversed for e in entries)
    db.session.refresh(test_sale)
    assert Decimal(str(test_sale.paid_amount)) == Decimal('0')
    assert Decimal(str(test_sale.balance_due)) == Decimal('100')
    assert test_sale.payment_status == 'unpaid'


def test_payments_supplier_docs_archive_delete_flow(client, login_owner):
    sup = _sup()
    _wh(code=_uniq('WMC-'), is_main=True)
    post = client.post('/payments/voucher/submit', data=_voucher(
        party_id=sup.id, amount='300'))
    assert post.status_code == 302
    pay = Payment.query.one()
    pid = pay.id
    assert client.get(f'/payments/payments/{pid}').status_code == 200
    assert client.get(f'/payments/payments/{pid}/print').status_code == 200

    arch = client.post(f'/payments/payments/{pid}/archive', follow_redirects=True)
    assert arch.status_code == 200
    entries = GLJournalEntry.query.filter_by(
        reference_type='Payment', reference_id=pid).all()
    assert any(e.is_reversed for e in entries)
    assert ArchivedRecord.query.filter_by(
        table_name='payments', record_id=pid).count() == 1
    assert pay.payment_number not in client.get('/payments/receipts').get_data(as_text=True)
    body = client.get('/payments/archived').get_data(as_text=True)
    assert pay.payment_number in body
    restore = client.post(f'/payments/payments/{pid}/restore', follow_redirects=True)
    assert restore.status_code == 200
    assert ArchivedRecord.query.filter_by(
        table_name='payments', record_id=pid).count() == 0

    chq = _uniq('CHQ-DL-')
    client.post('/payments/voucher/submit', data=_voucher(
        party_id=sup.id, amount='150', payment_method='cheque', cheque_number=chq,
        cheque_date=date.today().isoformat(), bank_name='بنك عجمان'))
    pay2 = Payment.query.filter(Payment.id != pid).one()
    soft = client.post(f'/payments/payments/{pay2.id}/delete', follow_redirects=True)
    assert soft.status_code == 200
    assert ArchivedRecord.query.filter_by(table_name='payments').count() == 1
    assert ArchivedRecord.query.filter_by(table_name='cheques').count() == 1

    fresh = client.post('/payments/voucher/submit', data=_voucher(
        party_id=sup.id, amount='80'))
    assert fresh.status_code == 302
    pay3 = Payment.query.filter(~Payment.id.in_([pid, pay2.id])).one()
    p3 = pay3.id
    hard = client.post(f'/payments/payments/{p3}/delete', follow_redirects=True)
    assert hard.status_code == 200
    assert 'نهائياً' in hard.get_data(as_text=True)
    assert db.session.get(Payment, p3) is None


def test_payments_purchase_voucher_flow_and_balance_api(client, login_owner, owner_user,
                                                        test_customer, test_sale):
    sup = _sup()
    pur = _purchase_db(owner_user, sup)
    base = f'/payments/create_payment/{pur.id}'
    assert client.get(base).status_code == 200

    miss = client.post(base, data={'amount': '100'}, follow_redirects=True)
    assert 'يرجى اختيار طريقة الدفع' in miss.get_data(as_text=True)
    assert Payment.query.count() == 0

    over = client.post(base, data={'amount': '600', 'payment_method': 'cash'},
                       follow_redirects=True)
    assert 'المبلغ غير صحيح' in over.get_data(as_text=True)
    assert Payment.query.count() == 0

    ok = client.post(base, data={'amount': '300', 'payment_method': 'cash'})
    assert ok.status_code == 302
    assert f'/purchases/{pur.id}' in ok.headers['Location']
    pay = Payment.query.one()
    assert pay.direction == 'outgoing' and pay.payment_type == 'supplier_payment'
    assert pay.amount_base == Decimal('300')
    assert {'2110', '1110'} <= _gl_codes('Payment', pay.id)

    balance = client.get(f'/payments/api/customer-balance/{test_customer.id}')
    bdata = balance.get_json()
    assert balance.status_code == 200
    assert abs(bdata['balance_aed'] - 100.0) < 0.001
    assert bdata['unpaid_sales'][0]['balance_due'] == 100.0


# ---------------------------------------------------------------- expenses ops

def test_expenses_cash_cheque_edit_categories_archive_delete(client, login_owner):
    cat = ExpenseCategory(name=_uniq('إيجار-'), name_ar='إيجار',
                          gl_account_code='6200', is_active=True)
    db.session.add(cat)
    db.session.commit()

    create = client.post('/expenses/create', data={
        'category_id': str(cat.id), 'description': 'صيانة دورية',
        'description_ar': 'صيانة', 'amount': '500', 'currency': 'AED',
        'payment_method': 'cash', 'reference_number': _uniq('REF-')},
        headers={})
    assert create.status_code == 302
    exp = Expense.query.one()
    eid = exp.id
    assert exp.amount == Decimal('500') and exp.status == 'confirmed'
    entry = GLJournalEntry.query.filter_by(
        reference_type='Expense', reference_id=eid).one()
    assert entry.total_debit == entry.total_credit
    assert {'6200', '1110'} <= _gl_codes('Expense', eid)
    assert client.get(f'/expenses/{eid}').status_code == 200
    assert client.get(f'/expenses/{eid}/print').status_code == 200

    repost = client.post(f'/expenses/{eid}/edit', data={
        'category_id': str(cat.id), 'description': 'أصل معدل',
        'description_ar': '', 'amount': '750', 'currency': 'AED',
        'supplier_name': '', 'notes': ''})
    assert repost.status_code == 302
    entries = GLJournalEntry.query.filter_by(
        reference_type='Expense', reference_id=eid).all()
    assert len(entries) == 3
    reversed_rows = [e for e in entries if e.is_reversed]
    assert len(reversed_rows) == 1 and reversed_rows[0].id == entry.id
    corrected_rows = [e for e in entries if e.description and '(corrected)' in e.description]
    assert len(corrected_rows) == 1
    corrected = corrected_rows[0]
    assert not corrected.is_reversed
    assert sum(ln.debit for ln in corrected.lines) == Decimal('750')

    unchanged = client.post(f'/expenses/{eid}/edit', data={
        'category_id': str(cat.id), 'description': 'وصف جديد فقط',
        'description_ar': '', 'amount': '750', 'currency': 'AED',
        'supplier_name': '', 'notes': ''})
    assert unchanged.status_code == 302
    still = GLJournalEntry.query.filter_by(
        reference_type='Expense', reference_id=eid).all()
    assert len(still) == 3 and any(not e.is_reversed for e in still)

    # cheque-based expense issues a pending outgoing cheque
    chq_cat = ExpenseCategory(name=_uniq('رواتب-'), gl_account_code='6100',
                              is_active=True)
    db.session.add(chq_cat)
    db.session.commit()
    chq_num = _uniq('CHQ-EX-')
    cheq = client.post('/expenses/create', data={
        'category_id': str(chq_cat.id), 'description': 'رواتب شيك',
        'amount': '900', 'currency': 'AED', 'payment_method': 'cheque',
        'cheque_number': chq_num,
        'cheque_date': (date.today() + timedelta(days=14)).isoformat(),
        'bank_name': 'بنك الاتحاد', 'supplier_name': 'موظف'})
    assert cheq.status_code == 302
    exp2 = Expense.query.filter(Expense.id != eid).one()
    cheque = Cheque.query.one()
    assert cheque.expense_id == exp2.id and cheque.status == 'pending'
    assert {'2110', '2120'} <= _gl_codes('cheque_issue', cheque.id)

    cheque.status = 'cleared'
    db.session.commit()
    cleared_del = client.post(f'/expenses/{exp2.id}/delete', follow_redirects=True)
    assert cleared_del.status_code == 200
    assert 'ارتباطات' in cleared_del.get_data(as_text=True)
    assert db.session.get(Expense, exp2.id) is not None
    assert ArchivedRecord.query.filter_by(table_name='expenses').count() == 1
    assert ArchivedRecord.query.filter_by(table_name='cheques').count() == 1

    assert client.get('/expenses/categories').status_code == 200
    cat_name = _uniq('نقل-')
    form_cat = client.post('/expenses/categories/create', data={
        'name': cat_name, 'name_ar': 'نقل', 'gl_account_code': '6600'})
    assert form_cat.status_code == 302
    json_cat = client.post('/expenses/categories/create',
                           json={'name': cat_name, 'name_ar': 'فئة'})
    assert json_cat.status_code == 400
    new_json = client.post('/expenses/categories/create',
                           json={'name': _uniq('JSON-'), 'name_ar': 'فئة'})
    jbody = new_json.get_json()
    assert new_json.status_code == 200 and jbody['success'] is True
    assert jbody['category']['name'].startswith('JSON-')

    archived_cycle = Expense(
        expense_number=_uniq('EXP-ARC-'), category_id=cat.id,
        description='للأرشفة', amount=Decimal('250'), currency='AED',
        exchange_rate=Decimal('1'), amount_base=Decimal('250'),
        payment_method='bank_transfer', user_id=None)
    archived_cycle.user_id = 1
    db.session.add(archived_cycle)
    db.session.commit()
    aid = archived_cycle.id
    assert client.post(f'/expenses/{aid}/archive', follow_redirects=True).status_code == 200
    arch_body = client.get('/expenses/archived').get_data(as_text=True)
    assert archived_cycle.expense_number in arch_body
    assert client.post(f'/expenses/{aid}/restore', follow_redirects=True).status_code == 200
    assert ArchivedRecord.query.filter_by(table_name='expenses', record_id=aid).count() == 0

    keep = client.post(f'/expenses/{eid}/delete', follow_redirects=True)
    assert keep.status_code == 200 and 'نهائياً' in keep.get_data(as_text=True)
    assert db.session.get(Expense, eid) is None
    assert GLJournalEntry.query.filter_by(
        reference_type='Expense', reference_id=eid).count() == 0


# ---------------------------------------------------------------- purchases ops

def test_purchases_create_full_flow_with_tax(client, login_owner, main_wh):
    sup = _sup()
    prod = _new_product()
    resp = client.post('/purchases/create', data={
        'warehouse_id': str(main_wh.id), 'supplier_id': str(sup.id),
        'line_count': '1', 'lines[0][product_id]': str(prod.id),
        'lines[0][quantity]': '5', 'lines[0][unit_cost]': '10',
        'currency': 'AED', 'tax_rate': '10'})
    assert resp.status_code == 302
    pur = Purchase.query.one()
    assert f'/purchases/{pur.id}' in resp.headers['Location']
    assert pur.subtotal == Decimal('50')
    assert pur.tax_amount == Decimal('5') and pur.total_amount == Decimal('55')
    assert PurchaseLine.query.count() == 1
    mv = StockMovement.query.one()
    assert mv.movement_type == 'purchase' and mv.quantity == Decimal('5')
    assert mv.reference_id == pur.id and mv.reference_type == 'Purchase'

    codes = _gl_codes('Purchase', pur.id)
    assert {'1140', '2110', '2130'} <= codes
    entry = GLJournalEntry.query.filter_by(
        reference_type='Purchase', reference_id=pur.id).one()
    dr = {ln.account.code: ln.debit for ln in entry.lines}
    cr = {ln.account.code: ln.credit for ln in entry.lines}
    assert dr['1140'] == Decimal('50') and dr['2130'] == Decimal('5')
    assert cr['2110'] == Decimal('55')


def test_purchases_validation_guard_branches(client, login_owner, main_wh):
    sup = _sup()
    prod = _new_product()
    no_wh = client.post('/purchases/create', data={
        'supplier_id': str(sup.id), 'line_count': '1'})
    assert no_wh.status_code == 302
    assert Purchase.query.count() == 0

    no_sup = client.post('/purchases/create', data={
        'warehouse_id': str(main_wh.id), 'line_count': '1',
        'lines[0][product_id]': str(prod.id), 'lines[0][quantity]': '1',
        'lines[0][unit_cost]': '5', 'supplier_name': ''})
    assert no_sup.status_code == 302
    assert Purchase.query.count() == 0

    zero_lines = client.post('/purchases/create', data={
        'warehouse_id': str(main_wh.id), 'supplier_id': str(sup.id),
        'line_count': '0'})
    assert zero_lines.status_code == 302
    assert Purchase.query.count() == 0


def test_purchases_view_edit_search_delete_and_api(client, login_owner, owner_user,
                                                   main_wh):
    pur = _purchase_db(owner_user, _sup(), total='200')
    assert client.get(f'/purchases/{pur.id}').status_code == 200
    assert client.get(f'/purchases/{pur.id}/print').status_code == 200
    assert client.get(f'/purchases/{pur.id}/edit').status_code == 200
    edited = client.post(f'/purchases/{pur.id}/edit', data={'notes': 'تعديل ملاحظات'})
    assert edited.status_code == 302
    db.session.refresh(pur)
    assert pur.notes == 'تعديل ملاحظات'

    pur.paid_amount = Decimal('75')
    db.session.commit()
    guarded = client.get(f'/purchases/{pur.id}/edit')
    assert guarded.status_code == 302
    assert '/edit' not in guarded.headers['Location']

    search_body = client.get(
        f'/purchases/?search={quote_plus(pur.purchase_number)}').get_data(as_text=True)
    assert pur.purchase_number in search_body
    assert client.get('/purchases/99999999').status_code == 404

    plain = _purchase_db(owner_user, _sup())
    db.session.add(PurchaseLine(purchase_id=plain.id, product_id=_new_product().id,
                                quantity=Decimal('1'), unit_cost=Decimal('1'),
                                line_total=Decimal('1')))
    db.session.commit()
    plain_id = plain.id
    hard = client.post(f'/purchases/{plain_id}/delete', follow_redirects=True)
    assert hard.status_code == 200 and 'نهائياً' in hard.get_data(as_text=True)
    assert db.session.get(Purchase, plain_id) is None

    paid = _purchase_db(owner_user, _sup())
    paid.paid_amount = Decimal('25')
    db.session.commit()
    paid_id = paid.id
    soft = client.post(f'/purchases/{paid_id}/delete', follow_redirects=True)
    assert soft.status_code == 200
    assert 'ارتباطات مالية' in soft.get_data(as_text=True)
    assert db.session.get(Purchase, paid_id) is not None
    assert ArchivedRecord.query.filter_by(
        table_name='purchases', record_id=paid_id).count() == 1

    calc = client.post('/purchases/api/calculate-totals', json={
        'lines': [{'quantity': 4, 'unit_cost': 12, 'discount_percent': 25}],
        'tax_rate': 5})
    pdata = calc.get_json()
    assert calc.status_code == 200 and pdata['success'] is True
    assert pdata['subtotal'] == pytest.approx(36.0)
    assert pdata['total'] == pytest.approx(37.8)
    assert pdata['line_count'] == 1


# ---------------------------------------------------------------- customers ops

def test_customers_statement_filters_deletes_and_apis(client, login_owner, main_wh,
                                                      test_customer, test_sale):
    stmt_url = f'/customers/{test_customer.id}/statement'
    client.post('/payments/voucher/submit', data=_voucher(
        direction='incoming', party_type='customer', party_id=test_customer.id,
        amount='25', payment_method='cash'))
    full = client.get(stmt_url)
    assert full.status_code == 200
    assert test_sale.sale_number in full.get_data(as_text=True)

    today_iso = date.today().isoformat()
    ranged = client.get(f'{stmt_url}?date_from={today_iso}&date_to={today_iso}')
    assert ranged.status_code == 200
    assert test_sale.sale_number in ranged.get_data(as_text=True)

    excluded = client.get(
        f"{stmt_url}?date_from={(date.today() + timedelta(days=1)).isoformat()}")
    assert test_sale.sale_number not in excluded.get_data(as_text=True)

    pay_only = client.get(f'{stmt_url}?transaction_type=payment').get_data(as_text=True)
    sale_only = client.get(f'{stmt_url}?transaction_type=sale').get_data(as_text=True)
    assert test_sale.sale_number not in pay_only
    assert test_sale.sale_number in sale_only

    bal = client.get(f'/customers/{test_customer.id}/balance').get_json()
    assert bal['unpaid_sales'][0]['sale_number'] == test_sale.sale_number

    found = client.get(
        f"/customers/api/search?q={quote_plus('+971501234567')}").get_json()
    assert any(r['id'] == test_customer.id for r in found)
    assert all(key in found[0] for key in ('name', 'text', 'balance'))
    all_rows = client.get('/customers/api/search').get_json()
    assert len(all_rows) >= 1
    none_found = client.get('/customers/api/search?q=zzz-nope-zzz').get_json()
    assert none_found == []

    cid = test_customer.id
    soft = client.post(f'/customers/{cid}/delete', follow_redirects=True)
    assert soft.status_code == 200
    db.session.refresh(test_customer)
    assert test_customer.is_active is False
    assert test_customer.name not in client.get('/customers/').get_data(as_text=True)

    fresh = Customer(name=_uniq('نظيف-'), is_active=True)
    db.session.add(fresh)
    db.session.commit()
    fid = fresh.id
    hard = client.post(f'/customers/{fid}/delete', follow_redirects=True)
    assert hard.status_code == 200 and 'نهائياً' in hard.get_data(as_text=True)
    assert db.session.get(Customer, fid) is None


# ---------------------------------------------------------------- suppliers ops

def test_suppliers_full_module_matrix(client, login_owner, owner_user):
    sup = _sup()
    pur = _purchase_db(owner_user, sup, total='200')
    pay = Payment(payment_number=_uniq('PAY-SUP-'), payment_type='bill_payment',
                  direction='outgoing', supplier_id=sup.id,
                  supplier_name=sup.name, amount=Decimal('60'), currency='AED',
                  exchange_rate=Decimal('1'), amount_base=Decimal('60'),
                  payment_method='cash', user_id=owner_user.id)
    db.session.add(pay)
    db.session.commit()

    stmt = client.get(f'/suppliers/{sup.id}/statement')
    assert stmt.status_code == 200
    sbody = stmt.get_data(as_text=True)
    assert sup.name in sbody and pur.purchase_number in sbody

    view = client.get(f'/suppliers/{sup.id}')
    assert view.status_code == 200
    assert sup.name in view.get_data(as_text=True)
    assert client.get('/suppliers/99999999').status_code == 404

    tag = _uniq()
    created = client.post('/suppliers/create', data={
        'name': f'مورد-{tag}', 'company_name': 'الخليج لقطع الغيار',
        'phone': '+971501112233', 'email': f'{tag}@sup.com', 'city': 'دبي',
        'country': 'UAE', 'supplier_type': 'parts', 'rating': '5',
        'credit_limit': '4000', 'payment_terms_days': '45',
        'preferred_currency': 'AED', 'initial_balance': '950',
        'is_verified': 'on', 'tags': 'سريع'})
    assert created.status_code == 302
    newsup = Supplier.query.filter_by(email=f'{tag}@sup.com').one()
    assert f'/suppliers/{newsup.id}' in created.headers['Location']
    assert newsup.is_verified is True and newsup.rating == 5
    assert abs(float(newsup.total_purchases_aed) - 950.0) < 0.001

    r1 = client.post('/suppliers/create', data={'name': 'بلا نوع'})
    assert r1.status_code == 200
    assert 'يرجى اختيار نوع المورد' in r1.get_data(as_text=True)
    r2 = client.post('/suppliers/create', data={
        'name': 'تقييم خاطئ', 'supplier_type': 'parts', 'rating': 'abc'})
    assert r2.status_code == 200
    assert 'قيمة التقييم غير صحيحة' in r2.get_data(as_text=True)
    assert Supplier.query.filter_by(name='بلا نوع').count() == 0

    edit_page = client.get(f'/suppliers/{newsup.id}/edit')
    assert edit_page.status_code == 200
    edit = client.post(f'/suppliers/{newsup.id}/edit', data={
        'name': 'اسم مورد محدث', 'company_name': '', 'phone': '+971500000000',
        'supplier_type': 'equipment', 'rating': '3', 'credit_limit': '800',
        'payment_terms_days': '15', 'preferred_currency': 'AED',
        'country': 'UAE'})
    assert edit.status_code == 302
    db.session.refresh(newsup)
    assert newsup.name == 'اسم مورد محدث' and newsup.rating == 3

    found = client.get(f"/suppliers/api/search?q={quote_plus(newsup.name)}").get_json()
    assert any(r['id'] == newsup.id for r in found)
    none = client.get('/suppliers/api/search?q=zzz-nope-zzz').get_json()
    assert none == []
    everyone = client.get('/suppliers/api/search').get_json()
    assert len(everyone) >= 1

    soft = client.post(f'/suppliers/{sup.id}/delete', follow_redirects=True)
    assert soft.status_code == 200
    db.session.expire(sup)
    assert sup.is_active is False

    virgin = _sup()
    vid = virgin.id
    hard = client.post(f'/suppliers/{vid}/delete', follow_redirects=True)
    assert hard.status_code == 200 and 'نهائياً' in hard.get_data(as_text=True)
    assert db.session.get(Supplier, vid) is None


# ---------------------------------------------------------------- warehouse ops

def test_warehouse_add_stock_branches_and_creation_validations(client, login_owner):
    prod = _new_product()
    pid = prod.id

    no_wh = client.post(f'/warehouse/add-stock/{pid}', data={'quantity': '3'})
    assert no_wh.status_code == 400
    assert 'لا يوجد مستودع نشط' in no_wh.get_json()['message']

    main = _wh(is_main=True, code=_uniq('WMC-'))
    add = client.post(f'/warehouse/add-stock/{pid}', data={
        'quantity': '25', 'warehouse_id': str(main.id), 'notes': 'جرد إضافي'})
    adata = add.get_json()
    assert add.status_code == 200 and adata['success'] is True
    db.session.refresh(prod)
    assert adata['new_stock'] == pytest.approx(float(prod.current_stock))
    assert float(prod.current_stock) > 100.0
    mv = StockMovement.query.one()
    assert mv.movement_type == 'adjustment' and mv.warehouse_id == main.id

    for bad in ('0', '-5'):
        badr = client.post(f'/warehouse/add-stock/{pid}', data={'quantity': bad})
        assert badr.status_code == 400 and badr.get_json()['success'] is False

    assert client.get('/warehouse/create').status_code == 200
    tag = _uniq()
    ok = client.post('/warehouse/create', data={
        'name': f'مستودع-{tag}', 'code': f'CODE-{tag}', 'location': 'أبوظبي'})
    assert ok.status_code == 302
    assert Warehouse.query.filter_by(code=f'CODE-{tag}').one() is not None

    dup = client.post('/warehouse/create', data={
        'name': f'آخر-{tag}', 'code': f'CODE-{tag}', 'location': 'دبي'})
    assert dup.status_code == 200
    assert 'رمز المستودع موجود مسبقاً' in dup.get_data(as_text=True)

    no_name = client.post('/warehouse/create', data={'location': 'x'})
    assert 'اسم المستودع مطلوب' in no_name.get_data(as_text=True)
    no_loc = client.post('/warehouse/create', data={'name': 'y'})
    assert 'الموقع مطلوب' in no_loc.get_data(as_text=True)


def test_warehouse_delete_branches_and_listing_pages(client, login_owner):
    main = _wh(is_main=True, code=_uniq('WMC-'))
    mid = main.id
    blocked = client.post(f'/warehouse/{mid}/delete', follow_redirects=True)
    assert 'لا يمكن حذف المستودع الرئيسي' in blocked.get_data(as_text=True)
    assert db.session.get(Warehouse, mid) is not None

    prod = _new_product()
    client.post(f'/warehouse/add-stock/{prod.id}', data={
        'quantity': '7', 'warehouse_id': str(mid)})
    busy = _wh(location='الشارقة')
    db.session.add(StockMovement(product_id=prod.id, warehouse_id=busy.id,
                                 movement_type='adjustment', quantity=Decimal('1')))
    db.session.commit()
    bid = busy.id
    soft = client.post(f'/warehouse/{bid}/delete', follow_redirects=True)
    assert soft.status_code == 200
    assert 'إلغاء تفعيل المستودع' in soft.get_data(as_text=True)
    db.session.refresh(busy)
    assert busy.is_active is False

    empty = _wh(location='رأس الخيمة')
    eid = empty.id
    hard = client.post(f'/warehouse/{eid}/delete', follow_redirects=True)
    assert hard.status_code == 200
    assert 'تم حذف المستودع' in hard.get_data(as_text=True)
    assert db.session.get(Warehouse, eid) is None

    assert client.get('/warehouse/movements').status_code == 200
    filt = client.get(f"/warehouse/movements?product={prod.id}&type=adjustment"
                      f"&warehouse={mid}")
    assert filt.status_code == 200

    low = _new_product(stock='3', min_alert='10')
    out = _new_product(stock='0', min_alert='5')
    low_body = client.get('/warehouse/low-stock').get_data(as_text=True)
    out_body = client.get('/warehouse/out-of-stock').get_data(as_text=True)
    assert low.sku in low_body and out.sku in out_body

    view = client.get(f'/warehouse/{mid}')
    assert view.status_code == 200
    assert prod.name in view.get_data(as_text=True)
    assert client.get('/warehouse/list').status_code == 200
