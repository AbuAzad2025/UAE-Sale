"""اختبارات P0 لتواريخ الاستحقاق وأعمار الذمم — tests/unit/test_due_dates_p0.py.

كان تحليل أعمار الذمم يقيس **عمر** الفاتورة لا **ما هو مستحقّ فعلاً**:
فاتورة عمرها 30 يوماً لم تستحق بعد وفاتورة عمرها 30 يوماً متأخرة 30
يوماً كانتا في الشريحة نفسها، لأن `sales` و`purchases` لم يحتويا تاريخ
استحقاق أصلاً ولم يُستعمل `payment_terms_days` في أي مكان.

تغطي:

  • اشتقاق تاريخ الاستحقاق: تاريخ صريح / شروط دفع / شروط صفر.
  • `overdue_days` وحدود شرائح التأخير.
  • أعمار الذمم بالاستحقاق: مجموع الشرائح = الإجمالي المستحق.
  • احترام `as_of` (التأخير يُقاس نسبةً إلى تاريخ المرجع).
  • تطابق اشتقاق رصيد العميل (models/customer.py) مع إجمالي الأعمار.
  • حفظ تاريخ الاستحقاق عند إنشاء فاتورة بيع/شراء من المسار.

كل المبالغ Decimal؛ الاختبارات بلا شبكة.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from extensions import db
from models import Customer, Purchase, Sale, Supplier
from services import due_date_service
from services.due_date_service import (
    OVERDUE_BUCKETS,
    bucket_for_overdue,
    due_date_for_purchase,
    due_date_for_sale,
    overdue_days,
)


# ─────────────────────────── helpers ───────────────────────────

def _customer(db, name, terms=0):
    c = Customer(name=name, name_ar=name, customer_type='regular',
                 balance=Decimal('0'), payment_terms_days=terms, is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _supplier(db, name, terms=30):
    s = Supplier(name=name, is_active=True, payment_terms_days=terms)
    db.session.add(s)
    db.session.commit()
    return s


def _sale(db, number, customer, seller, total='100.000', sale_date=None,
          due_date=None, paid='0'):
    """فاتورة بيع مؤكدة — التواريخ اختيارية حتى نختبر أعماراً مختلفة."""
    total_d = Decimal(str(total))
    paid_d = Decimal(str(paid))

    sale = Sale(
        sale_number=number, customer_id=customer.id, seller_id=seller.id,
        total_amount=total_d, amount_base=total_d,
        paid_amount=paid_d, paid_amount_base=paid_d,
        balance_due=total_d - paid_d,
        currency='ILS', exchange_rate=Decimal('1'),
        payment_status='unpaid' if paid_d == 0 else 'partial',
        status='confirmed', is_active=True,
        sale_date=sale_date or datetime.now(timezone.utc),
        due_date=due_date,
    )
    db.session.add(sale)
    db.session.commit()
    return sale


def _purchase(db, number, supplier, user_id, total='200.000', purchase_date=None,
              due_date=None):
    """فاتورة شراء مؤكدة — التواريخ اختيارية."""
    p = Purchase(
        purchase_number=number, supplier_id=supplier.id,
        supplier_name=supplier.name, total_amount=Decimal(total),
        amount_base=Decimal(total), currency='ILS', exchange_rate=Decimal('1'),
        status='confirmed', user_id=user_id, paid_amount=Decimal('0'),
        payment_status='unpaid',
        purchase_date=purchase_date or datetime.now(timezone.utc),
        due_date=due_date,
    )
    db.session.add(p)
    db.session.commit()
    return p


def _warehouse(db, name='P0 due-date warehouse'):
    from models import Warehouse

    w = Warehouse(name=name, name_ar=name, is_main=True, is_active=True)
    db.session.add(w)
    db.session.commit()
    return w


def _at(day):
    """تاريخ (يوم) عند منتصف الليل — يُستعمل لتواريخ الفواتير."""
    return datetime.combine(day, time.min)


# ─────────────────────── اشتقاق تاريخ الاستحقاق ───────────────────────

class TestDueDateDerivation:

    def test_explicit_due_date_wins_over_terms(self, db):
        """تاريخ استحقاق صريح يتقدّم على شروط الدفع."""
        customer = _customer(db, 'P0 explicit customer', terms=45)
        invoice_date = date(2026, 3, 1)

        due = due_date_for_sale(invoice_date, customer=customer,
                                explicit=date(2026, 4, 15))
        assert due == date(2026, 4, 15)

        # النص بصيغة ISO يُقبل أيضاً
        assert due_date_for_sale(invoice_date, customer=customer,
                                 explicit='2026-04-15') == date(2026, 4, 15)

    def test_terms_thirty_days_extend_the_invoice_date(self, db):
        """شروط 30 يوماً ⇒ الاستحقاق بعد 30 يوماً من تاريخ الفاتورة."""
        customer = _customer(db, 'P0 terms 30 customer', terms=30)
        invoice_date = date(2026, 3, 1)

        due = due_date_for_sale(invoice_date, customer=customer)
        assert due == invoice_date + timedelta(days=30)

    def test_terms_zero_means_due_on_the_invoice_date(self, db):
        """شروط 0 ⇒ الاستحقاق في تاريخ الفاتورة نفسه (مستحق فوراً)."""
        customer = _customer(db, 'P0 terms 0 customer', terms=0)
        invoice_date = date(2026, 3, 1)

        assert due_date_for_sale(invoice_date, customer=customer) == invoice_date

    def test_missing_terms_default_to_zero(self, db):
        """طرف بلا سمة شروط أو بقيمة None ⇒ استحقاق فوري."""
        invoice_date = date(2026, 3, 1)

        assert due_date_for_sale(invoice_date) == invoice_date
        assert due_date_for_sale(invoice_date, customer=None) == invoice_date

        class _NoTerms:
            payment_terms_days = None

        assert due_date_for_sale(invoice_date, customer=_NoTerms()) == invoice_date

    def test_purchase_uses_supplier_terms(self, db):
        """فاتورة الشراء تشتق استحقاقها من شروط دفع المورد."""
        supplier = _supplier(db, 'P0 terms supplier', terms=30)
        invoice_date = date(2026, 3, 1)

        due = due_date_for_purchase(invoice_date, supplier=supplier)
        assert due == invoice_date + timedelta(days=30)

    def test_datetime_input_is_normalised_to_date(self, db):
        """عمود الفاتورة من نوع DateTime — التطبيع يعيد `date`."""
        customer = _customer(db, 'P0 datetime customer', terms=10)
        stamp = datetime(2026, 3, 1, 14, 30, 45)

        due = due_date_for_sale(stamp, customer=customer)
        assert due == date(2026, 3, 11)
        assert isinstance(due, date) and not isinstance(due, datetime)

    def test_no_invoice_date_means_no_due_date(self, db):
        """بلا تاريخ فاتورة ⇒ لا استحقاق."""
        customer = _customer(db, 'P0 no date customer', terms=30)

        assert due_date_for_sale(None, customer=customer) is None
        assert due_date_for_purchase(None, supplier=None) is None

    def test_due_date_never_none_when_invoice_date_known(self, db):
        """قاعدة: تاريخ فاتورة معروف ⇒ استحقاق معروف دائماً."""
        customer = _customer(db, 'P0 never none customer', terms=0)

        for terms in (0, 1, 15, 30, 90):
            customer.payment_terms_days = terms
            assert due_date_for_sale(date(2026, 1, 1), customer=customer) is not None


# ─────────────────────────── overdue_days ───────────────────────────

class TestOverdueDays:

    def test_overdue_days_for_past_today_future_and_none(self):
        """المرجع الافتراضي هو تاريخ اليوم بتوقيت UTC."""
        today = datetime.now(timezone.utc).date()

        assert overdue_days(today - timedelta(days=10)) == 10
        assert overdue_days(today) == 0
        assert overdue_days(today + timedelta(days=10)) == 0
        assert overdue_days(None) == 0

    def test_explicit_as_of_overrides_the_default_reference(self):
        assert overdue_days(date(2026, 1, 1), as_of=date(2026, 1, 11)) == 10
        assert overdue_days(date(2026, 1, 1), as_of=date(2026, 1, 1)) == 0

    def test_due_date_equal_to_as_of_is_not_late_yet(self):
        """استحقاق اليوم = صفر يوم تأخير (ليس متأخراً بعد)."""
        assert overdue_days(date(2026, 5, 10), as_of=date(2026, 5, 10)) == 0
        assert overdue_days(date(2026, 5, 10), as_of=date(2026, 5, 11)) == 1
        assert overdue_days(date(2026, 5, 10), as_of=date(2026, 5, 9)) == 0

    def test_overdue_days_uses_the_reference_date_not_today(self):
        assert overdue_days(date(2026, 1, 1), as_of=date(2026, 1, 31)) == 30
        assert overdue_days(date(2026, 1, 1), as_of=date(2026, 1, 1)) == 0


# ─────────────────────────── شرائح التأخير ───────────────────────────

class TestOverdueBuckets:

    @pytest.mark.parametrize('days,expected', [
        (0, 'not_due'),
        (1, '1-30'),
        (30, '1-30'),
        (31, '31-60'),
        (60, '31-60'),
        (61, '61-90'),
        (90, '61-90'),
        (91, '90+'),
    ])
    def test_bucket_boundaries(self, days, expected):
        assert bucket_for_overdue(days) == expected

    def test_negative_days_are_not_due(self):
        assert bucket_for_overdue(-5) == 'not_due'

    def test_bucket_names_are_stable(self):
        assert OVERDUE_BUCKETS == ('not_due', '1-30', '31-60', '61-90', '90+')


# ─────────────────────── الأعمار بالاستحقاق ───────────────────────

class TestAgingByDueDate:

    def _aging_customer(self, db, owner_user, test_customer):
        """عميل بفاتورة في كل شريحة تأخير."""
        today = date.today()
        plan = (
            ('S-DD-NOT-DUE', '100.000', today + timedelta(days=25), 5),
            ('S-DD-1-30', '200.000', today - timedelta(days=10), 40),
            ('S-DD-31-60', '300.000', today - timedelta(days=45), 85),
            ('S-DD-61-90', '400.000', today - timedelta(days=75), 115),
            ('S-DD-90PLUS', '500.000', today - timedelta(days=120), 160),
        )
        for number, total, due, age in plan:
            _sale(db, number, test_customer, owner_user, total=total,
                  sale_date=_at(today - timedelta(days=age)), due_date=due)
        return test_customer

    def test_buckets_sum_to_the_total_outstanding(self, db, owner_user,
                                                    test_customer):
        """مجموع شرائح التأخير = الإجمالي المستحق (شرط التوازن)."""
        from services.aging_analysis_service import AgingAnalysisService

        self._aging_customer(db, owner_user, test_customer)

        report = AgingAnalysisService.get_receivables_aging()
        buckets = report['overdue_buckets']

        assert set(buckets) == set(OVERDUE_BUCKETS)
        assert float(buckets['not_due']) == 100.0
        assert float(buckets['1-30']) == 200.0
        assert float(buckets['31-60']) == 300.0
        assert float(buckets['61-90']) == 400.0
        assert float(buckets['90+']) == 500.0

        assert float(sum(buckets.values())) == pytest.approx(
            report['total_outstanding'])
        assert report['total_outstanding'] == pytest.approx(
            report['totals']['total'])
        assert report['overdue_total'] == pytest.approx(1400.0)

    def test_null_due_date_falls_back_to_the_invoice_date(self, db, owner_user,
                                                          test_customer):
        """فاتورة بلا تاريخ استحقاق ⇒ مستحقّة في تاريخها (مستحق فوراً)."""
        from services.aging_analysis_service import AgingAnalysisService

        today = date.today()
        _sale(db, 'S-DD-NULL-DUE', test_customer, owner_user, total='100.000',
              sale_date=_at(today - timedelta(days=40)), due_date=None)

        report = AgingAnalysisService.get_receivables_aging()
        assert float(report['overdue_buckets']['31-60']) == 100.0
        assert float(report['overdue_buckets']['not_due']) == 0.0

    def test_aging_respects_as_of(self, db, owner_user, test_customer):
        """التأخير يُقاس نسبةً إلى تاريخ المرجع لا إلى تاريخ اليوم."""
        from services.aging_analysis_service import AgingAnalysisService

        today = date.today()
        due = today - timedelta(days=100)
        _sale(db, 'S-DD-ASOF', test_customer, owner_user, total='100.000',
              sale_date=_at(due - timedelta(days=10)), due_date=due)

        # قبل الاستحقاق: ليس مستحقاً بعد
        report = AgingAnalysisService.get_receivables_aging(
            as_of=due - timedelta(days=1))
        assert float(report['overdue_buckets']['not_due']) == 100.0
        assert report['overdue_total'] == 0.0

        # في يوم الاستحقاق: ليس متأخراً بعد (صفر يوم)
        report = AgingAnalysisService.get_receivables_aging(as_of=due)
        assert float(report['overdue_buckets']['not_due']) == 100.0
        assert report['overdue_total'] == 0.0

        # يوم بعد الاستحقاق: يوم تأخير
        report = AgingAnalysisService.get_receivables_aging(
            as_of=due + timedelta(days=1))
        assert float(report['overdue_buckets']['1-30']) == 100.0
        assert report['overdue_total'] == pytest.approx(100.0)

        # والاسم القديم as_of_date يعمل أيضاً، والنتيجة اليوم 90+
        report = AgingAnalysisService.get_receivables_aging(as_of_date=due)
        assert float(report['overdue_buckets']['not_due']) == 100.0

        report = AgingAnalysisService.get_receivables_aging()
        assert float(report['overdue_buckets']['90+']) == 100.0

    def test_customer_balance_agrees_with_the_aging_total(self, db, owner_user,
                                                          test_customer):
        """اشتقاق رصيد العميل (models/customer.py) يوافق إجمالي الأعمار."""
        from models.customer import derive_customer_balance
        from services.aging_analysis_service import AgingAnalysisService

        today = date.today()
        _sale(db, 'S-DD-BAL-1', test_customer, owner_user, total='100.000',
              sale_date=_at(today - timedelta(days=5)),
              due_date=today + timedelta(days=25))
        _sale(db, 'S-DD-BAL-2', test_customer, owner_user, total='250.000',
              sale_date=_at(today - timedelta(days=60)),
              due_date=today - timedelta(days=30))
        db.session.commit()

        report = AgingAnalysisService.get_receivables_aging()
        entry = next(c for c in report['customers']
                     if c['customer'].id == test_customer.id)

        assert float(entry['total']) == 350.0
        assert float(entry['total_outstanding']) == 350.0
        assert derive_customer_balance(test_customer.id) == Decimal('350.000')

    def test_payables_aging_uses_the_due_date(self, db, owner_user):
        """الذمم الدائنة تحترم تاريخ الاستحقاق أيضاً."""
        from services.aging_analysis_service import AgingAnalysisService

        supplier = _supplier(db, 'P0 aging supplier', terms=30)
        today = date.today()
        _purchase(db, 'P-DD-1', supplier, owner_user.id, total='300.000',
                  purchase_date=_at(today - timedelta(days=10)),
                  due_date=today - timedelta(days=5))

        report = AgingAnalysisService.get_payables_aging()
        assert float(report['overdue_buckets']['1-30']) == 300.0
        assert report['total_outstanding'] == pytest.approx(300.0)

    def test_invoice_rows_carry_the_due_date_and_the_overdue_days(
            self, db, owner_user, test_customer):
        """تفاصيل الفاتورة تحمل تاريخ الاستحقاق والتأخير والشريحة."""
        from services.aging_analysis_service import AgingAnalysisService

        today = date.today()
        due = today - timedelta(days=10)
        _sale(db, 'S-DD-ROWS', test_customer, owner_user, total='100.000',
              sale_date=_at(today - timedelta(days=40)), due_date=due)

        report = AgingAnalysisService.get_receivables_aging()
        row = report['customers'][0]['invoices'][0]

        assert row['due_date'] == due
        assert row['days_overdue'] == 10
        assert row['overdue_bucket'] == '1-30'

    def test_legacy_age_buckets_are_still_exposed(self, db, owner_user,
                                                   test_customer):
        """شرائح العمر (مرجع دفتر الأستاذ) بقيت في المخرجات كما هي."""
        from services.aging_analysis_service import (
            AGING_BUCKETS,
            AgingAnalysisService,
        )

        today = date.today()
        _sale(db, 'S-DD-AGE', test_customer, owner_user, total='100.000',
              sale_date=_at(today - timedelta(days=45)), due_date=today)

        report = AgingAnalysisService.get_receivables_aging()

        for bucket in AGING_BUCKETS:
            assert bucket in report['totals']
            assert bucket in report['buckets']
        assert float(report['totals']['31-60']) == 100.0
        assert float(report['buckets']['31-60']) == 100.0


# ─────────────────────── المسارات تحفظ الاستحقاق ───────────────────────

class TestRoutesPersistDueDate:

    def test_sale_created_through_the_route_persists_the_derived_due_date(
            self, client, db, owner_user, login_owner, test_customer, test_product):
        """فاتورة بيع عبر /sales/create ⇒ الاستحقاق مشتق من شروط العميل."""
        warehouse = _warehouse(db)
        test_customer.payment_terms_days = 30
        db.session.commit()

        resp = client.post('/sales/create', data={
            'customer_id': str(test_customer.id),
            'warehouse_id': str(warehouse.id),
            'line_count': '1',
            'lines[0][product_id]': str(test_product.id),
            'lines[0][quantity]': '1',
            'lines[0][unit_price]': '100',
            'lines[0][discount_percent]': '0',
            'discount_amount': '0',
            'shipping_cost': '0',
            'tax_rate': '0',
        })
        assert resp.status_code in (302, 303)

        sale = Sale.query.order_by(Sale.id.desc()).first()
        assert sale is not None
        assert sale.due_date == sale.sale_date.date() + timedelta(days=30)

    def test_sale_created_through_the_route_honours_an_explicit_due_date(
            self, client, db, owner_user, login_owner, test_customer, test_product):
        """تاريخ استحقاق صريح في النموذج يتقدّم على شروط الدفع."""
        warehouse = _warehouse(db, 'P0 explicit warehouse')
        test_customer.payment_terms_days = 30
        db.session.commit()

        explicit = date.today() + timedelta(days=7)
        resp = client.post('/sales/create', data={
            'customer_id': str(test_customer.id),
            'warehouse_id': str(warehouse.id),
            'line_count': '1',
            'lines[0][product_id]': str(test_product.id),
            'lines[0][quantity]': '1',
            'lines[0][unit_price]': '100',
            'lines[0][discount_percent]': '0',
            'discount_amount': '0',
            'shipping_cost': '0',
            'tax_rate': '0',
            'due_date': explicit.isoformat(),
        })
        assert resp.status_code in (302, 303)

        sale = Sale.query.order_by(Sale.id.desc()).first()
        assert sale.due_date == explicit

    def test_purchase_created_through_the_route_persists_the_derived_due_date(
            self, client, db, owner_user, login_owner, test_product):
        """فاتورة شراء عبر /purchases/create ⇒ الاستحقاق من شروط المورد."""
        warehouse = _warehouse(db, 'P0 purchase warehouse')
        supplier = _supplier(db, 'P0 route supplier', terms=30)

        resp = client.post('/purchases/create', data={
            'supplier_id': str(supplier.id),
            'supplier_name': supplier.name,
            'warehouse_id': str(warehouse.id),
            'line_count': '1',
            'lines[0][product_id]': str(test_product.id),
            'lines[0][quantity]': '1',
            'lines[0][unit_cost]': '50',
            'lines[0][discount_percent]': '0',
            'discount_amount': '0',
            'tax_rate': '0',
        })
        assert resp.status_code in (302, 303)

        purchase = Purchase.query.order_by(Purchase.id.desc()).first()
        assert purchase is not None
        assert purchase.due_date == purchase.purchase_date.date() + timedelta(days=30)

    def test_sales_list_shows_the_due_date_and_the_overdue_badge(
            self, client, db, owner_user, login_owner, test_customer):
        """قائمة المبيعات تعرض تاريخ الاستحقاق وتعلّم الفاتورة المتأخرة."""
        today = date.today()
        _sale(db, 'S-DD-LIST', test_customer, owner_user, total='100.000',
              sale_date=_at(today - timedelta(days=40)),
              due_date=today - timedelta(days=10))

        resp = client.get('/sales/')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert (today - timedelta(days=10)).strftime('%Y-%m-%d') in html
        assert 'متأخر' in html

    def test_purchases_list_shows_the_due_date_and_the_overdue_badge(
            self, client, db, owner_user, login_owner):
        """قائمة المشتريات تعرض تاريخ الاستحقاق وتعلّم الفاتورة المتأخرة."""
        today = date.today()
        supplier = _supplier(db, 'P0 list supplier', terms=30)
        _purchase(db, 'P-DD-LIST', supplier, owner_user.id, total='300.000',
                  purchase_date=_at(today - timedelta(days=40)),
                  due_date=today - timedelta(days=10))

        resp = client.get('/purchases/')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert (today - timedelta(days=10)).strftime('%Y-%m-%d') in html
        assert 'متأخر' in html


# ─────────────────────── النموذج والخدمة ───────────────────────

class TestModelColumns:

    def test_customer_payment_terms_default_to_zero(self, db):
        customer = _customer(db, 'P0 default terms customer')
        db.session.refresh(customer)
        assert customer.payment_terms_days == 0

    def test_negative_payment_terms_are_refused_by_the_database(self, db):
        """قيد قاعدة البيانات يمنع شروط دفع سالبة."""
        customer = _customer(db, 'P0 negative terms customer')
        customer.payment_terms_days = -5
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()

    def test_document_helpers_expose_the_due_date(self, db, owner_user,
                                                   test_customer):
        """النموذج يعرض الاستحقاق والتأخير من الخدمة الواحدة."""
        today = date.today()
        sale = _sale(db, 'S-DD-HELPERS', test_customer, owner_user, total='100.000',
                     sale_date=_at(today - timedelta(days=40)),
                     due_date=today - timedelta(days=10))

        assert sale.effective_due_date == today - timedelta(days=10)
        assert sale.days_overdue == 10
        assert sale.overdue_bucket == '1-30'
        assert due_date_service.overdue_days(sale.effective_due_date,
                                             as_of=today) == 10
