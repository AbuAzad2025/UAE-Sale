"""HTTP integration tests for routes/reports.py and routes/api_analytics.py."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from extensions import cache
from models import (
    Sale, SaleLine, Purchase, Product, ProductCategory, Customer, Supplier,
    Payment, Receipt, ProductPartner, User, Role, Permission,
    GLAccount, GLJournalEntry, GLJournalLine,
)


class _NoCache:
    def get(self, key):
        return None

    def set(self, key, value, timeout=None):
        return True


@pytest.fixture(autouse=True)
def _clean_cache(app, monkeypatch):
    import utils.cache_decorators as cache_mod
    monkeypatch.setattr(cache_mod, 'cache', _NoCache())
    with app.app_context():
        cache.clear()
    yield
    with app.app_context():
        cache.clear()


def _dt(days=0):
    return datetime.now() - timedelta(days=days)


def _mk_customer(db, name, ctype='regular', phone='+971500000000'):
    c = Customer(name=name, customer_type=ctype, phone=phone, is_active=True,
                 credit_limit=Decimal('100000'), balance=Decimal('0'))
    db.session.add(c)
    db.session.commit()
    return c


def _mk_product(db, name, sku, category=None, stock=Decimal('10'),
                cost=Decimal('50'), price=Decimal('100'),
                merchant=None, share=Decimal('80')):
    p = Product(name=name, sku=sku, regular_price=price,
                cost_price=cost, current_stock=stock,
                min_stock_alert=Decimal('5'), is_active=True)
    if category is not None:
        p.category_id = category.id
    if merchant is not None:
        p.merchant_customer_id = merchant.id
        p.merchant_share = share
    db.session.add(p)
    db.session.commit()
    return p


def _mk_sale(db, customer, seller_id, number, total, paid=Decimal('0'),
             when=None, tax_rate=Decimal('0'), tax_amount=Decimal('0'),
             lines=()):
    sale = Sale(sale_number=number, customer_id=customer.id, seller_id=seller_id,
                total_amount=total, amount_base=total,
                paid_amount=paid, paid_amount_base=paid,
                balance_due=total - paid, currency='AED',
                exchange_rate=Decimal('1'),
                payment_status='paid' if paid >= total else 'unpaid',
                tax_rate=tax_rate, tax_amount=tax_amount,
                status='confirmed', is_active=True)
    if when is None:
        sale.sale_date = _dt()
    else:
        sale.sale_date = when
    db.session.add(sale)
    db.session.flush()
    for prod, qty, price, cost in lines:
        db.session.add(SaleLine(sale_id=sale.id, product_id=prod.id,
                                quantity=qty, unit_price=price,
                                discount_percent=Decimal('0'),
                                line_total=qty * price, cost_price=cost))
    db.session.commit()
    return sale


def _mk_purchase(db, owner, supplier, number, total, when=None,
                 tax_rate=Decimal('0'), tax_amount=Decimal('0')):
    pur = Purchase(purchase_number=number, supplier_id=supplier.id,
                   supplier_name=supplier.name,
                   purchase_date=_dt() if when is None else when,
                   total_amount=total, currency='AED',
                   exchange_rate=Decimal('1'), amount_base=total,
                   tax_rate=tax_rate, tax_amount=tax_amount,
                   status='confirmed', user_id=owner.id)
    db.session.add(pur)
    db.session.commit()
    return pur


def _mk_payment(db, number, amount, direction='outgoing', supplier_id=None,
                customer_id=None, confirmed=True, when=None):
    pay = Payment(payment_number=number, payment_type='supplier_payment',
                  direction=direction, supplier_id=supplier_id,
                  customer_id=customer_id, amount=amount, currency='AED',
                  exchange_rate=Decimal('1'), amount_base=amount,
                  payment_method='cash', payment_confirmed=confirmed,
                  payment_date=_dt() if when is None else when)
    db.session.add(pay)
    db.session.commit()
    return pay


def _mk_receipt(db, number, customer, amount, when=None):
    r = Receipt(receipt_number=number, customer_id=customer.id,
                amount=amount, currency='AED', exchange_rate=Decimal('1'),
                amount_base=amount, payment_method='cash',
                receipt_date=_dt() if when is None else when)
    db.session.add(r)
    db.session.commit()
    return r


class TestAuthAndPermissions:
    def test_reports_require_login(self, client):
        resp = client.get('/reports/sales', follow_redirects=False)
        assert resp.status_code == 302

    def test_reports_denied_without_view_reports(self, client, login_seller):
        resp = client.get('/reports/sales', follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_seller_purchases_report_blocked_even_with_view_reports(
            self, client, db, owner_user, test_customer):
        perms = [Permission.query.filter_by(code='manage_sales').first(),
                 Permission.query.filter_by(code='view_reports').first()]
        role = Role(name='SellerRep', name_ar='بائع', slug='seller',
                    permissions=[p for p in perms if p])
        db.session.add(role)
        db.session.flush()
        u = User(username='rep_seller', email='rs@test.com',
                 full_name='Rep Seller', is_owner=False, is_active=True,
                 role_id=role.id)
        u.set_password('RepSeller1!')
        db.session.add(u)
        db.session.commit()
        client.post('/auth/login', data={'username': 'rep_seller',
                                         'password': 'RepSeller1!'},
                    follow_redirects=True)
        resp = client.get('/reports/purchases')
        assert resp.status_code == 403

    def test_seller_scoped_sales_report(self, client, db, owner_user,
                                        test_customer):
        perms = [Permission.query.filter_by(code='manage_sales').first(),
                 Permission.query.filter_by(code='view_reports').first()]
        role = Role(name='SellerRep2', name_ar='بائع', slug='seller',
                    permissions=[p for p in perms if p])
        db.session.add(role)
        db.session.flush()
        u = User(username='rep_seller2', email='rs2@test.com',
                 full_name='Rep Seller 2', is_owner=False, is_active=True,
                 role_id=role.id)
        u.set_password('RepSeller2!')
        db.session.add(u)
        db.session.commit()
        _mk_sale(db, test_customer, u.id, 'S-RPT-MINE', Decimal('70'))
        _mk_sale(db, test_customer, owner_user.id, 'S-RPT-OTHERS',
                 Decimal('700'))
        client.post('/auth/login', data={'username': 'rep_seller2',
                                         'password': 'RepSeller2!'},
                    follow_redirects=True)
        resp = client.get('/reports/sales')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'S-RPT-MINE' in html
        assert 'S-RPT-OTHERS' not in html

    def test_api_analytics_requires_login(self, client):
        resp = client.get('/api/analytics/daily-stats', follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_api_analytics_requires_view_reports(self, client, login_seller):
        resp = client.get('/api/analytics/top-customers')
        assert resp.status_code == 403


class TestDashboardPages:
    def test_index(self, client, login_owner):
        resp = client.get('/reports/')
        assert resp.status_code == 200
        assert 'التقارير المالية' in resp.get_data(as_text=True)

    def test_inventory_summary_and_category_filter(self, client, login_owner,
                                                   db, owner_user,
                                                   test_category,
                                                   test_product):
        cat2 = ProductCategory(name='ValCat2', name_ar='فئة ثانية',
                               is_active=True)
        db.session.add(cat2)
        db.session.commit()
        other = _mk_product(db, 'Other Item', 'SKU-INV-2', category=cat2)
        _mk_sale(db, _mk_customer(db, 'Inv Cust'), owner_user.id,
                 'S-RPT-INV', Decimal('99'),
                 lines=[(test_product, Decimal('2'), Decimal('50'),
                         Decimal('25'))])
        resp = client.get('/reports/inventory')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert test_product.name in html
        assert other.name in html
        assert '5000.0' in html
        resp = client.get(f'/reports/inventory?category={test_category.id}')
        html = resp.get_data(as_text=True)
        assert test_product.name in html
        assert other.name not in html

    def test_top_selling(self, client, login_owner, db, owner_user,
                         test_customer, test_product):
        prod_b = _mk_product(db, 'Slow Mover', 'SKU-TOP-2')
        cust = _mk_customer(db, 'Top Cust')
        _mk_sale(db, cust, owner_user.id, 'S-RPT-TOP1', Decimal('600'),
                 lines=[(test_product, Decimal('4'), Decimal('100'),
                         Decimal('50'))])
        _mk_sale(db, cust, owner_user.id, 'S-RPT-TOP2', Decimal('450'),
                 lines=[(prod_b, Decimal('6'), Decimal('75'),
                         Decimal('40'))])
        resp = client.get('/reports/top-selling?limit=1')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'المنتجات الأكثر مبيعاً' in html
        assert prod_b.name in html
        assert test_product.name not in html

    def test_receivables_aging(self, client, login_owner, db, owner_user,
                               test_customer):
        cust = _mk_customer(db, 'Aging Cust')
        _mk_sale(db, cust, owner_user.id, 'S-RPT-AGE1', Decimal('100'))
        _mk_sale(db, cust, owner_user.id, 'S-RPT-AGE2', Decimal('1200'),
                 when=_dt(days=200))
        _mk_sale(db, cust, owner_user.id, 'S-RPT-AGE3', Decimal('75'),
                 paid=Decimal('75'))
        resp = client.get('/reports/receivables')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'تفاصيل الذمم' in html
        assert 'S-RPT-AGE1' in html and 'S-RPT-AGE2' in html
        assert 'S-RPT-AGE3' not in html
        assert '1,200' in html

    def test_partners_merchants_suppliers_math(self, client, login_owner,
                                               db, owner_user,
                                               test_customer):
        partner = _mk_customer(db, 'شريك الحصص', ctype='partner')
        merchant = _mk_customer(db, 'تاجر العمولات', ctype='merchant')
        prod_x = _mk_product(db, 'Partner Product', 'SKU-PRT-1')
        prod_y = _mk_product(db, 'Merchant Product', 'SKU-MER-1',
                             merchant=merchant, share=Decimal('80'))
        db.session.add(ProductPartner(product_id=prod_x.id,
                                      partner_customer_id=partner.id,
                                      percentage=Decimal('25')))
        db.session.commit()
        cust = _mk_customer(db, 'Partners Page Cust')
        _mk_sale(db, cust, owner_user.id, 'S-RPT-PRT1', Decimal('200'),
                 lines=[(prod_x, Decimal('4'), Decimal('50'),
                         Decimal('20'))])
        _mk_sale(db, cust, owner_user.id, 'S-RPT-PRT2', Decimal('150'),
                 lines=[(prod_y, Decimal('2'), Decimal('75'),
                         Decimal('30'))])
        sup = Supplier(name='Sup Partners', is_active=True)
        db.session.add(sup)
        db.session.flush()
        _mk_purchase(db, owner_user, sup, 'P-RPT-PRT1', Decimal('400'))
        _mk_payment(db, 'PAY-RPT-PRT1', Decimal('150'),
                    supplier_id=sup.id)
        _mk_payment(db, 'PAY-RPT-PRT2', Decimal('25'), direction='incoming',
                    supplier_id=sup.id)
        resp = client.get('/reports/partners')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'تقرير الشركاء والتجار' in html
        assert 'شريك الحصص' in html and '50.00' in html
        assert 'تاجر العمولات' in html and '120.00' in html
        assert 'Sup Partners' in html and '275.00' in html

    def test_partners_date_filter_excludes_all(self, client, login_owner,
                                               db, owner_user):
        tomorrow = (datetime.now() + timedelta(days=2)).date().isoformat()
        resp = client.get(f'/reports/partners?date_from={tomorrow}')
        assert resp.status_code == 200
        assert 'لا توجد حركات مالية للشركاء' in resp.get_data(as_text=True)


class TestFinancialReports:
    def test_purchases_stats_and_supplier_filter(self, client, login_owner,
                                                 db, owner_user):
        sup1 = Supplier(name='Pur Sup 1', is_active=True)
        sup2 = Supplier(name='Pur Sup 2', is_active=True)
        db.session.add_all([sup1, sup2])
        db.session.commit()
        _mk_purchase(db, owner_user, sup1, 'P-RPT-A', Decimal('400'))
        _mk_purchase(db, owner_user, sup2, 'P-RPT-B', Decimal('900'))
        _mk_payment(db, 'PAY-RPT-A', Decimal('150'), supplier_id=sup1.id)
        resp = client.get('/reports/purchases')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert '400.0' in html and '900.0' in html
        assert '1300.0' in html and '150.0' in html and '1150.0' in html
        resp = client.get(f'/reports/purchases?supplier_id={sup2.id}')
        html = resp.get_data(as_text=True)
        assert '900.0' in html
        assert 'P-RPT-B' in html and 'P-RPT-A' not in html

    def test_cash_flow_gl_math(self, client, login_owner, db, owner_user):
        rev = GLAccount(code='4000-R', name='Sales Revenue', type='revenue')
        exp = GLAccount(code='5000-R', name='Rent Expense', type='expense')
        ast = GLAccount(code='1100-R', name='Equipment', type='asset')
        liab = GLAccount(code='2100-R', name='Loans', type='liability')
        db.session.add_all([rev, exp, ast, liab])
        db.session.flush()
        entry = GLJournalEntry(entry_number='JE-RPT-1', entry_date=_dt(),
                               is_posted=True, is_reversed=False,
                               created_by=owner_user.id)
        db.session.add(entry)
        db.session.flush()
        for acc, debit, credit in [(rev, 0, 1000), (exp, 300, 0),
                                   (ast, 500, 0), (liab, 0, 200)]:
            db.session.add(GLJournalLine(entry_id=entry.id, account_id=acc.id,
                                         debit=Decimal(debit),
                                         credit=Decimal(credit),
                                         amount_base=Decimal(debit or credit)))
        unposted = GLJournalEntry(entry_number='JE-RPT-2', entry_date=_dt(),
                                  is_posted=False, is_reversed=False,
                                  created_by=owner_user.id)
        db.session.add(unposted)
        db.session.flush()
        db.session.add(GLJournalLine(entry_id=unposted.id, account_id=exp.id,
                                     debit=Decimal('999'), credit=Decimal('0'),
                                     amount_base=Decimal('999')))
        db.session.commit()
        resp = client.get('/reports/cash-flow')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'الأنشطة التشغيلية' in html
        assert '700.00' in html
        assert '500.00' in html
        assert '200.00' in html
        assert '1,400.00' in html
        assert '999' not in html

    def test_vat_report_math(self, client, login_owner, db, owner_user):
        sup = Supplier(name='Vat Sup', is_active=True)
        db.session.add(sup)
        db.session.commit()
        cust = _mk_customer(db, 'Vat Cust')
        _mk_sale(db, cust, owner_user.id, 'S-RPT-VAT1', Decimal('500'),
                 tax_rate=Decimal('5'), tax_amount=Decimal('25'))
        _mk_sale(db, cust, owner_user.id, 'S-RPT-VAT2', Decimal('100'))
        _mk_purchase(db, owner_user, sup, 'P-RPT-VAT1', Decimal('200'),
                     tax_rate=Decimal('5'), tax_amount=Decimal('10'))
        resp = client.get('/reports/vat-report')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert '25.00' in html and '10.00' in html and '15.00' in html
        assert '100.00' in html
        assert 'S-RPT-VAT1' in html

    def test_ap_aging_buckets(self, client, login_owner, db, owner_user):
        old = Supplier(name='Old Sup', is_active=True)
        new = Supplier(name='New Sup', is_active=True)
        dormant = Supplier(name='Dormant Sup', is_active=True)
        db.session.add_all([old, new, dormant])
        db.session.commit()
        _mk_purchase(db, owner_user, old, 'P-RPT-OLD', Decimal('800'),
                     when=_dt(days=100))
        _mk_purchase(db, owner_user, new, 'P-RPT-NEW', Decimal('500'))
        _mk_payment(db, 'PAY-RPT-NEW', Decimal('100'), supplier_id=new.id)
        _mk_payment(db, 'PAY-RPT-PEND', Decimal('50'), supplier_id=new.id,
                    confirmed=False)
        resp = client.get('/reports/ap-aging')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'أعمار الذمم الدائنة' in html
        assert 'Old Sup' in html and '800.00' in html
        assert 'New Sup' in html and '400.00' in html
        assert 'Dormant Sup' not in html
        assert '1,200.00 AED' in html

    def test_inventory_valuation_page(self, client, login_owner, db,
                                      test_category, test_product):
        zero = Product(name='Zero Stock', sku='SKU-ZERO',
                       regular_price=Decimal('10'),
                       current_stock=Decimal('0'), is_active=True)
        db.session.add(zero)
        db.session.commit()
        resp = client.get(
            f'/reports/inventory-valuation?category_id={test_category.id}')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert test_product.name_ar in html
        assert '5,000.000' in html
        assert 'Zero Stock' not in html


class TestEntitySearchAndFragment:
    def test_entity_search_supplier_and_customers(self, client, login_owner,
                                                  db):
        sup = Supplier(name='Alpha Trading', phone='+971501112233',
                       is_active=True)
        db.session.add(sup)
        db.session.commit()
        _mk_customer(db, 'Beta Regular', phone='+971555555555')
        part = _mk_customer(db, 'Gamma Partner', ctype='partner',
                            phone='+971566666666')
        resp = client.get('/reports/api/entity-search?q=Alpha&type=supplier')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['id'] == sup.id
        assert data[0]['type'] == 'supplier'
        resp = client.get('/reports/api/entity-search?q=&type=partner')
        data = resp.get_json()
        assert [c['id'] for c in data] == [part.id]
        resp = client.get('/reports/api/entity-search?q=Beta&type=customer')
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['name'] == 'Beta Regular'

    def test_fragment_customer_balance(self, client, login_owner, db,
                                       owner_user, test_customer,
                                       test_product):
        _mk_sale(db, test_customer, owner_user.id, 'S-RPT-FRAG1',
                 Decimal('100'),
                 lines=[(test_product, Decimal('2'), Decimal('50'),
                         Decimal('25'))])
        _mk_receipt(db, 'RCP-RPT-1', test_customer, Decimal('30'))
        _mk_payment(db, 'PAY-RPT-CX1', Decimal('20'), direction='outgoing',
                    customer_id=test_customer.id)
        resp = client.get(
            f'/reports/entity_report_fragment/customer/{test_customer.id}')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert test_customer.name in html
        assert '90.00' in html
        assert 'مستحق لنا' in html
        assert 'S-RPT-FRAG1' in html
        assert 'RCP-RPT-1' in html and 'PAY-RPT-CX1' in html

    def test_fragment_supplier_clean(self, client, login_owner, db):
        sup = Supplier(name='Clean Sup', phone='+971577777777',
                       is_active=True, total_purchases_aed=Decimal('600'),
                       total_paid_aed=Decimal('150'))
        db.session.add(sup)
        db.session.commit()
        resp = client.get(
            f'/reports/entity_report_fragment/supplier/{sup.id}')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Clean Sup' in html
        assert '450.00' in html
        assert 'مستحق للمورد' in html

    def test_fragment_unknown_id_returns_404(self, client, login_owner):
        resp = client.get('/reports/entity_report_fragment/customer/999999')
        assert resp.status_code == 404


class TestExportEndpoints:
    def test_inventory_valuation_csv(self, client, login_owner, db,
                                     test_product, test_category):
        resp = client.get('/reports/inventory-valuation/export?format=csv')
        assert resp.status_code == 200
        assert resp.headers['Content-Type'].startswith('text/csv')
        body = resp.get_data(as_text=False).decode('utf-8-sig')
        assert test_product.name in body
        assert '5000.0' in body

    def test_ap_aging_xlsx(self, client, login_owner, db, owner_user):
        sup = Supplier(name='Xls Sup', is_active=True)
        db.session.add(sup)
        db.session.commit()
        _mk_purchase(db, owner_user, sup, 'P-RPT-XLS', Decimal('300'))
        resp = client.get('/reports/ap-aging/export')
        assert resp.status_code == 200
        assert resp.data[:2] == b'PK'
        assert 'ap_aging.xlsx' in resp.headers['Content-Disposition']

    def test_vat_report_csv(self, client, login_owner, db, owner_user):
        sup = Supplier(name='VatCsv Sup', is_active=True)
        db.session.add(sup)
        db.session.commit()
        cust = _mk_customer(db, 'VatCsv Cust')
        _mk_sale(db, cust, owner_user.id, 'S-RPT-VE', Decimal('500'),
                 tax_rate=Decimal('5'), tax_amount=Decimal('25'))
        resp = client.get('/reports/vat-report/export?format=csv')
        assert resp.status_code == 200
        body = resp.get_data(as_text=False).decode('utf-8-sig')
        assert 'S-RPT-VE' in body

    def test_cash_flow_csv(self, client, login_owner, db, owner_user):
        rev = GLAccount(code='4000-C', name='Rev Csv', type='revenue')
        db.session.add(rev)
        db.session.flush()
        entry = GLJournalEntry(entry_number='JE-RPT-C1', entry_date=_dt(),
                               is_posted=True, is_reversed=False,
                               created_by=owner_user.id)
        db.session.add(entry)
        db.session.flush()
        db.session.add(GLJournalLine(entry_id=entry.id, account_id=rev.id,
                                     debit=Decimal('0'),
                                     credit=Decimal('800'),
                                     amount_base=Decimal('800')))
        db.session.commit()
        resp = client.get('/reports/cash-flow/export?format=csv')
        assert resp.status_code == 200
        body = resp.get_data(as_text=False).decode('utf-8-sig')
        assert '4000-C' in body


class TestApiAnalytics:
    def test_overdue_payments(self, client, login_owner, db, owner_user):
        big = _mk_customer(db, 'Big Debtor')
        small = _mk_customer(db, 'Small Debtor')
        _mk_sale(db, big, owner_user.id, 'S-RPT-OD1', Decimal('1500'))
        _mk_sale(db, small, owner_user.id, 'S-RPT-OD2', Decimal('200'))
        resp = client.get('/api/analytics/overdue-payments')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['count'] == 1
        assert data['total_amount'] == 1500.0
        assert data['customers'][0]['name'] == 'Big Debtor'
        assert data['customers'][0]['balance'] == 1500.0

    def test_daily_stats(self, client, login_owner, db, owner_user):
        cust = _mk_customer(db, 'Daily Cust')
        sup = Supplier(name='Daily Sup', is_active=True)
        db.session.add(sup)
        db.session.commit()
        _mk_sale(db, cust, owner_user.id, 'S-RPT-DS1', Decimal('100'))
        _mk_sale(db, cust, owner_user.id, 'S-RPT-DS2', Decimal('250.5'))
        _mk_sale(db, cust, owner_user.id, 'S-RPT-DS3', Decimal('900'),
                 when=_dt(days=3))
        _mk_payment(db, 'PAY-RPT-DS1', Decimal('40'), customer_id=cust.id)
        _mk_payment(db, 'PAY-RPT-DS2', Decimal('10'), supplier_id=sup.id)
        _mk_payment(db, 'PAY-RPT-DS3', Decimal('70'), customer_id=cust.id,
                    when=_dt(days=2))
        resp = client.get('/api/analytics/daily-stats')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['sales']['count'] == 2
        assert data['sales']['total'] == 350.5
        assert data['payments']['count'] == 2
        assert data['payments']['total'] == 50.0

    def test_top_customers_order_and_limit(self, client, login_owner, db):
        vip = _mk_customer(db, 'Vip One')
        vip.total_purchases = Decimal('5000')
        vip.customer_classification = 'vip'
        reg = _mk_customer(db, 'Reg One')
        reg.total_purchases = Decimal('1000')
        db.session.commit()
        resp = client.get('/api/analytics/top-customers')
        data = resp.get_json()
        assert data['success'] is True
        assert [c['name'] for c in data['customers']] == ['Vip One',
                                                          'Reg One']
        assert data['customers'][0]['total_purchases'] == 5000.0
        assert data['customers'][0]['classification'] == 'vip'
        resp = client.get('/api/analytics/top-customers?limit=1')
        data = resp.get_json()
        assert len(data['customers']) == 1
        assert data['customers'][0]['name'] == 'Vip One'

    def test_low_stock_products(self, client, login_owner, db):
        critical = Product(name='Crit Item', sku='SKU-LOW-1',
                           regular_price=Decimal('20'),
                           current_stock=Decimal('0'),
                           min_stock_alert=Decimal('5'), is_active=True)
        high = Product(name='High Item', sku='SKU-LOW-2',
                       regular_price=Decimal('20'),
                       current_stock=Decimal('3'),
                       min_stock_alert=Decimal('10'), is_active=True)
        fine = Product(name='Fine Item', sku='SKU-LOW-3',
                       regular_price=Decimal('20'),
                       current_stock=Decimal('50'),
                       min_stock_alert=Decimal('10'), is_active=True)
        db.session.add_all([critical, high, fine])
        db.session.commit()
        resp = client.get('/api/analytics/low-stock-products')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['count'] == 2
        by_name = {p['name']: p for p in data['products']}
        assert by_name['Crit Item']['urgency'] == 'critical'
        assert by_name['Crit Item']['current_stock'] == 0.0
        assert by_name['High Item']['urgency'] == 'high'
        assert 'Fine Item' not in by_name

    def test_revenue_trend(self, client, login_owner, db, owner_user):
        cust = _mk_customer(db, 'Trend Cust')
        _mk_sale(db, cust, owner_user.id, 'S-RPT-RT1', Decimal('300'))
        _mk_sale(db, cust, owner_user.id, 'S-RPT-RT2', Decimal('200'),
                 when=_dt(days=10))
        draft = Sale(sale_number='S-RPT-RT3', customer_id=cust.id,
                     seller_id=owner_user.id, sale_date=_dt(days=1),
                     total_amount=Decimal('888'), amount_base=Decimal('888'),
                     paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
                     balance_due=Decimal('888'), currency='AED',
                     exchange_rate=Decimal('1'), payment_status='unpaid',
                     status='draft', is_active=True)
        db.session.add(draft)
        db.session.commit()
        resp = client.get('/api/analytics/revenue-trend?days=30')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert len(data['data']) == 2
        assert sum(row['revenue'] for row in data['data']) == 500.0
        resp = client.get('/api/analytics/revenue-trend?days=5')
        data = resp.get_json()
        assert len(data['data']) == 1
        assert data['data'][0]['revenue'] == 300.0
