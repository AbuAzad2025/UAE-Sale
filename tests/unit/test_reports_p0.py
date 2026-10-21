"""اختبارات P0 للتقارير المالية — الأصول والخصوم النقدية.

تغطي:
  • F1: القوائم المالية تعرض المبالغ بعملة الأساس لا بعملة المعاملة.
  • F2: الميزانية العمومية تُعلن فرق المعادلة المحاسبية.
  • F3/F5: قائمة التدفقات النقدية لا تتشوَّش بالقيد المعكوس، والصفحة
    والتصدير يتطابقان.
  • F4: تقرير ضريبة القيمة المضافة — أساس خاضع (بدون ضريبة)، استبعاد
    المرتجعات من قائمة المبيعات مع عكس الضريبة، وتطابق التصدير مع الشاشة.
  • F7: ميزان المراجعة يستبعد القيود المسودة والسطور اليتيمة.
"""

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from models import (
    GLAccount,
    GLJournalEntry,
    GLJournalLine,
    ProductReturn,
    ProductReturnLine,
    Purchase,
    Sale,
    Supplier,
)
from services.cash_flow_service import CashFlowService
from services.gl_service import GLService


BASE_CURRENCY = 'ILS'


@pytest.fixture
def chart_of_accounts(db):
    """شجرة الحسابات الأساسية + فترة مالية مفتوحة (تُنشأ مرة لكل اختبار)."""
    from models.erp_modules import FiscalPeriod

    period = FiscalPeriod.query.filter_by(name='P0 Test Period').first()
    if period is None:
        period = FiscalPeriod(
            name='P0 Test Period',
            year=date.today().year,
            period_type='annual',
            start_date=date(date.today().year - 2, 1, 1),
            end_date=date(date.today().year + 2, 12, 31),
            is_closed=False,
        )
        db.session.add(period)
    GLService.ensure_core_accounts()
    db.session.commit()
    return {acc.code: acc for acc in GLAccount.query.all()}


def _post_entry(lines, currency=BASE_CURRENCY, exchange_rate=Decimal('1'),
                description='p0-test', entry_date=None, reference_type=None,
                reference_id=None):
    entry = GLService.post_entry(
        lines,
        description=description,
        currency=currency,
        exchange_rate=exchange_rate,
        reference_type=reference_type,
        reference_id=reference_id,
        entry_date=entry_date,
    )
    return entry


def _formatted(value):
    return '{:,.2f}'.format(float(value))


# ═══════════════════════════════════════════════════════════════════════════
# F1 — العملة: القوائم المالية بعملة الأساس
# ═══════════════════════════════════════════════════════════════════════════

class TestBaseCurrencyStatements:

    def test_balance_sheet_shows_base_amount_not_transaction_amount(
            self, client, db, owner_user, login_owner, chart_of_accounts):
        """فاتورة USD تُظهر المبلغ بعملة الأساس في الميزانية العمومية."""
        _post_entry(
            lines=[
                {'account': '1130', 'debit': Decimal('1000'), 'credit': Decimal('0')},
                {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('1000')},
            ],
            currency='USD',
            exchange_rate=Decimal('3.67'),
            description='USD sale',
        )
        db.session.commit()

        resp = client.get('/ledger/balance-sheet')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # 1000 USD × 3.67 = 3670 بعملة الأساس
        assert _formatted(Decimal('3670')) in html
        # مبلغ المعاملة (1000) لا يجوز أن يظهر كمبلغ معروض
        assert _formatted(Decimal('1000')) not in html

    def test_trial_balance_sums_base_currency(
            self, client, db, owner_user, login_owner, chart_of_accounts):
        """ميزان المراجعة يجمع الحركات بعملة الأساس."""
        _post_entry(
            lines=[
                {'account': '1130', 'debit': Decimal('1000'), 'credit': Decimal('0')},
                {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('1000')},
            ],
            currency='USD',
            exchange_rate=Decimal('3.67'),
            description='USD sale',
        )
        db.session.commit()

        resp = client.get('/ledger/trial-balance')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert _formatted(Decimal('3670')) in html
        assert _formatted(Decimal('1000')) not in html

    def test_income_statement_is_base_currency(
            self, client, db, owner_user, login_owner, chart_of_accounts):
        """قائمة الدخل تعرض الإيراد بعملة الأساس."""
        _post_entry(
            lines=[
                {'account': '1130', 'debit': Decimal('1000'), 'credit': Decimal('0')},
                {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('1000')},
            ],
            currency='USD',
            exchange_rate=Decimal('3.67'),
            description='USD sale',
        )
        db.session.commit()

        resp = client.get('/ledger/income-statement')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert _formatted(Decimal('3670')) in html
        assert _formatted(Decimal('1000')) not in html


# ═══════════════════════════════════════════════════════════════════════════
# F2 — المعادلة المحاسبية
# ═══════════════════════════════════════════════════════════════════════════

class TestBalanceSheetEquation:

    def test_balance_sheet_reports_non_zero_delta(
            self, client, db, owner_user, login_owner, chart_of_accounts):
        """قيد غير متوازن يُظهر تنبيهاً أحمر بالفرق في الميزانية."""
        cash = GLAccount.query.filter_by(code='1110').first()
        entry = GLJournalEntry(
            entry_number='JE-P0-UNBALANCED',
            description='قيد غير متوازن عمداً',
            entry_type='manual',
            is_posted=True,
            is_reversed=False,
            created_by=owner_user.id,
        )
        db.session.add(entry)
        db.session.flush()
        db.session.add(GLJournalLine(
            entry_id=entry.id,
            account_id=cash.id,
            debit=Decimal('500'),
            credit=Decimal('0'),
            amount_base=Decimal('500'),
        ))
        db.session.commit()

        resp = client.get('/ledger/balance-sheet')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert 'الميزانية غير متوازنة' in html
        assert _formatted(Decimal('500')) in html

    def test_balance_sheet_is_balanced_for_balanced_ledger(
            self, client, db, owner_user, login_owner, chart_of_accounts):
        """دفتر متوازن ⇒ لا تنبيه imbalances."""
        _post_entry(
            lines=[
                {'account': '1110', 'debit': Decimal('1000'), 'credit': Decimal('0')},
                {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('1000')},
            ],
            description='balanced sale',
        )
        db.session.commit()

        resp = client.get('/ledger/balance-sheet')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'الميزانية غير متوازنة' not in html
        assert 'الميزانية متوازنة' in html


# ═══════════════════════════════════════════════════════════════════════════
# F3/F5 — قائمة التدفقات النقدية
# ═══════════════════════════════════════════════════════════════════════════

class TestCashFlowStatement:

    def test_reversed_entry_does_not_distort_cash_flow(
            self, client, db, owner_user, login_owner, chart_of_accounts):
        """القيد المعكوس وأصله يلغيان أثرهما — لا يظهر القيد العاكس وحده."""
        entry = _post_entry(
            lines=[
                {'account': '1110', 'debit': Decimal('1000'), 'credit': Decimal('0')},
                {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('1000')},
            ],
            description='sale to be reversed',
        )
        db.session.commit()

        entry.reverse_entry(description='reversal')
        db.session.commit()

        report = CashFlowService.generate_gl_cash_flow(
            date.today() - timedelta(days=2), date.today() + timedelta(days=2))

        assert report['operating_total'] == Decimal('0')
        assert report['net_change'] == Decimal('0')
        # لا يبقى أي بند بقيمة 1000 في القائمة
        assert all(value == Decimal('0') for value in report['operating_items'].values())

        resp = client.get('/reports/cash-flow')
        assert resp.status_code == 200

    def test_cash_flow_screen_and_export_agree(
            self, client, db, owner_user, login_owner, chart_of_accounts):
        """صفحة التدفقات النقدية والتصدير يعرضان نفس الأرقام."""
        _post_entry(
            lines=[
                {'account': '1110', 'debit': Decimal('1000'), 'credit': Decimal('0')},
                {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('1000')},
            ],
            description='sale',
        )
        db.session.commit()

        report = CashFlowService.generate_gl_cash_flow(
            date.today() - timedelta(days=2), date.today() + timedelta(days=2))
        assert report['operating_total'] == Decimal('1000')

        page = client.get('/reports/cash-flow')
        assert page.status_code == 200
        page_html = page.get_data(as_text=True)
        assert _formatted(report['operating_total']) in page_html

        export = client.get('/reports/cash-flow/export?format=csv')
        assert export.status_code == 200
        body = export.get_data(as_text=False).decode('utf-8-sig')
        rows = list(csv.reader(io.StringIO(body)))
        # كل صف يعرض القسم والحساب والصافي
        assert any('تشغيلي' in (row[0] or '') for row in rows if row), body
        assert any(str(float(report['operating_total'])) in (row[-1] or '')
                   for row in rows if row), body

    def test_ledger_cash_flow_uses_same_source(
            self, client, db, owner_user, login_owner, chart_of_accounts):
        """صفحة دفتر الأستاذ تعرض نفس أرقام صفحة التقارير."""
        _post_entry(
            lines=[
                {'account': '1110', 'debit': Decimal('750'), 'credit': Decimal('0')},
                {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('750')},
            ],
            description='sale',
        )
        db.session.commit()

        params = (f'date_from={(date.today() - timedelta(days=2)).isoformat()}'
                  f'&date_to={(date.today() + timedelta(days=2)).isoformat()}')

        ledger_page = client.get(f'/ledger/cash-flow?{params}')
        assert ledger_page.status_code == 200
        ledger_html = ledger_page.get_data(as_text=True)

        report = CashFlowService.generate_gl_cash_flow(
            date.today() - timedelta(days=2), date.today() + timedelta(days=2))
        assert _formatted(report['operating_total']) in ledger_html


# ═══════════════════════════════════════════════════════════════════════════
# F4 — تقرير ضريبة القيمة المضافة
# ═══════════════════════════════════════════════════════════════════════════

def _make_sale(db, customer, seller_id, number, net, tax_rate, tax_amount,
               currency=BASE_CURRENCY, exchange_rate=Decimal('1')):
    gross = net + tax_amount
    sale = Sale(
        sale_number=number,
        customer_id=customer.id,
        seller_id=seller_id,
        subtotal=net,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        total_amount=gross,
        currency=currency,
        exchange_rate=exchange_rate,
        amount_base=(gross * exchange_rate).quantize(Decimal('0.001')),
        paid_amount=Decimal('0'),
        paid_amount_base=Decimal('0'),
        balance_due=gross,
        payment_status='unpaid',
        status='confirmed',
        is_active=True,
        sale_date=datetime.now(),
    )
    db.session.add(sale)
    db.session.commit()
    return sale


def _make_credit_note(db, sale, customer, product, number, net,
                      tax_rate=Decimal('5')):
    """إشعار دائن (مرتجع) على مستوى سطر واحد."""
    tax = (Decimal(str(net)) * Decimal(str(tax_rate)) / Decimal('100')).quantize(
        Decimal('0.001'))
    credit_note = ProductReturn(
        return_number=number,
        sale_id=sale.id,
        customer_id=customer.id,
        total_amount=net,
        refund_amount=net + tax,
        currency=sale.currency,
        exchange_rate=sale.exchange_rate,
        amount_base=net,
        status='approved',
        return_date=datetime.now(),
    )
    db.session.add(credit_note)
    db.session.flush()
    db.session.add(ProductReturnLine(
        return_id=credit_note.id,
        product_id=product.id,
        quantity=Decimal('1'),
        unit_price=net,
        line_total=net,
    ))
    db.session.commit()
    return credit_note


class TestVatReport:

    def test_vat_report_uses_net_taxable_base_and_credit_note_reversal(
            self, client, db, owner_user, login_owner, test_customer,
            test_product):
        """الأساس الخاضع بدون ضريبة، والمرتجع يعكس ضريبة المخرجات."""
        from routes.reports import _vat_report_data

        sale = _make_sale(db, test_customer, owner_user.id, 'S-VAT-P0-1',
                          Decimal('500'), Decimal('5'), Decimal('25'))
        _make_credit_note(db, sale, test_customer, test_product, 'R-VAT-P0-1',
                          Decimal('100'), Decimal('5'))

        data = _vat_report_data()
        summary = data['summary']

        # المبيعات الخاضعة: 525 إجمالية − 25 ضريبة = 500 أساس خاضع
        # (قبل خصم المرتجع)
        assert summary['total_credit_notes_net'] == Decimal('100')
        assert summary['total_credit_notes_vat'] == Decimal('5')
        # بعد خصم المرتجع (100 أساس + 5 ضريبة) من المبيعات وضريبة المخرجات
        assert summary['total_taxable_sales'] == Decimal('400')
        assert summary['total_output_vat'] == Decimal('20')

        # المرتجع لا يظهر ضمن قائمة المبيعات الخاضعة
        taxable_numbers = [row['number'] for row in data['taxable_sales']]
        assert 'R-VAT-P0-1' not in taxable_numbers
        assert 'S-VAT-P0-1' in taxable_numbers
        # لكنه يظهر في قسم إشعارات الدائنة
        assert [row['number'] for row in data['credit_notes']] == ['R-VAT-P0-1']

        resp = client.get('/reports/vat-report')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert _formatted(Decimal('20')) in html   # ضريبة المخرجات بعد العكس
        assert _formatted(Decimal('400')) in html  # الأساس الخاضع بعد خصم المرتجع
        assert 'R-VAT-P0-1' in html

    def test_vat_report_excludes_archived_documents(
            self, client, db, owner_user, login_owner, test_customer):
        """المستند المؤرشف (حالةه بقيت confirmed) لا يُحتسب في التقرير."""
        from models import ArchivedRecord
        from routes.reports import _vat_report_data

        sale = _make_sale(db, test_customer, owner_user.id, 'S-VAT-ARCH',
                          Decimal('500'), Decimal('5'), Decimal('25'))
        db.session.add(ArchivedRecord(
            table_name='sales',
            record_id=sale.id,
            data={'sale_number': sale.sale_number},
            reason='test archive',
        ))
        db.session.commit()

        data = _vat_report_data()
        assert data['summary']['total_output_vat'] == Decimal('0')
        assert data['taxable_sales'] == []

    def test_vat_export_totals_equal_screen_totals(
            self, client, db, owner_user, login_owner, test_customer,
            test_product):
        """تصدير CSV يعطي نفس الإجماليات المعروضة على الشاشة."""
        from routes.reports import _vat_report_data

        sale = _make_sale(db, test_customer, owner_user.id, 'S-VAT-EXP',
                          Decimal('500'), Decimal('5'), Decimal('25'))
        _make_credit_note(db, sale, test_customer, test_product, 'R-VAT-EXP',
                          Decimal('100'), Decimal('5'))

        supplier = Supplier(name='VAT Supplier', is_active=True)
        db.session.add(supplier)
        db.session.commit()
        purchase = Purchase(
            purchase_number='P-VAT-EXP',
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            subtotal=Decimal('200'),
            tax_rate=Decimal('5'),
            tax_amount=Decimal('10'),
            total_amount=Decimal('210'),
            currency=BASE_CURRENCY,
            exchange_rate=Decimal('1'),
            amount_base=Decimal('210'),
            status='confirmed',
            user_id=owner_user.id,
            purchase_date=datetime.now(),
        )
        db.session.add(purchase)
        db.session.commit()

        summary = _vat_report_data()['summary']

        # الشاشة
        page = client.get('/reports/vat-report')
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert _formatted(summary['total_output_vat']) in html
        assert _formatted(summary['total_input_vat']) in html
        assert _formatted(summary['net_vat']) in html
        assert _formatted(summary['total_exempt_sales']) in html

        # التصدير CSV
        export = client.get('/reports/vat-report/export?format=csv')
        assert export.status_code == 200
        body = export.get_data(as_text=False).decode('utf-8-sig')
        rows = list(csv.reader(io.StringIO(body)))
        exported = {row[0]: row[1] for row in rows if len(row) >= 2 and row[0]}

        assert float(exported['ضريبة المبيعات (Output VAT)']) == float(
            summary['total_output_vat'])
        assert float(exported['ضريبة المشتريات (Input VAT)']) == float(
            summary['total_input_vat'])
        assert float(exported['الرصيد النهائي']) == float(summary['net_vat'])
        assert float(exported['إجمالي المبيعات المعفاة']) == float(
            summary['total_exempt_sales'])
        assert float(exported['إجمالي المشتريات المعفاة']) == float(
            summary['total_exempt_purchases'])

        # صفوف المشتريات لا تُدمج تحت عناوين المبيعات
        headers = [row for row in rows if row and row[0] == 'رقم الفاتورة']
        assert len(headers) >= 2  # عنوان المبيعات وعنوان المشتريات

    def test_vat_export_xlsx_totals_equal_screen_totals(
            self, client, db, owner_user, login_owner, test_customer):
        """تصدير Excel يعطي نفس الإجماليات المعروضة على الشاشة."""
        from openpyxl import load_workbook
        from routes.reports import _vat_report_data

        _make_sale(db, test_customer, owner_user.id, 'S-VAT-XLSX',
                   Decimal('500'), Decimal('5'), Decimal('25'))

        summary = _vat_report_data()['summary']

        export = client.get('/reports/vat-report/export?format=xlsx')
        assert export.status_code == 200
        workbook = load_workbook(io.BytesIO(export.data))
        sheet = workbook['الملخص']
        exported = {row[0].value: row[1].value for row in sheet.iter_rows()}

        assert float(exported['ضريبة المبيعات (Output VAT)']) == float(
            summary['total_output_vat'])
        assert float(exported['الرصيد النهائي']) == float(summary['net_vat'])


# ═══════════════════════════════════════════════════════════════════════════
# F7 — ميزان المراجعة: المسودات والسطور اليتيمة
# ═══════════════════════════════════════════════════════════════════════════

class TestTrialBalanceScope:

    def test_trial_balance_excludes_drafts_and_orphan_lines(
            self, client, db, owner_user, login_owner, chart_of_accounts):
        """النسخة بلا فلتر تاريخ تُطابق النسخة المفلترة (بلا مسودات/يتيم)."""
        cash = GLAccount.query.filter_by(code='1110').first()

        draft = GLJournalEntry(
            entry_number='JE-P0-DRAFT',
            description='مسودة',
            entry_type='manual',
            is_posted=False,
            is_reversed=False,
            created_by=owner_user.id,
        )
        db.session.add(draft)
        db.session.flush()
        db.session.add(GLJournalLine(
            entry_id=draft.id, account_id=cash.id,
            debit=Decimal('999'), credit=Decimal('0'),
            amount_base=Decimal('999')))
        db.session.commit()

        # سطر يتيم: قيد حُذف بالقوة من قاعدة البيانات
        orphan = GLJournalLine(
            entry_id=987654, account_id=cash.id,
            debit=Decimal('777'), credit=Decimal('0'),
            amount_base=Decimal('777'))
        db.session.add(orphan)
        db.session.commit()

        resp = client.get('/ledger/trial-balance')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert _formatted(Decimal('999')) not in html
        assert _formatted(Decimal('777')) not in html
