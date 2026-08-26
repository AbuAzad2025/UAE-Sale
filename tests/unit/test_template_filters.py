"""Unit tests for Agent 7 financial UI filters (money / num / status_badge).

Covers:
- Exact-string outputs of the Decimal-quantized, LRM-embedded money filter.
- Bidi ordering preservation with Arabic text surrounding amounts.
- Complete payment-status badge mapping (Arabic labels + Bootstrap classes).
- Smoke rendering of the heaviest report pages asserting grid cell classes.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from flask import render_template_string

from models import (
    Sale, SaleLine, Customer, Product, ProductCategory, ProductPartner,
    GLAccount, GLJournalEntry, GLJournalLine,
)

LRM = '\u200e'


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _seed_sale(db, seller_id, customer, number, total,
               paid=Decimal('0'), when=None):
    """Minimal confirmed sale (unpaid by default) for report smoke tests."""
    sale = Sale(
        sale_number=number,
        customer_id=customer.id,
        seller_id=seller_id,
        total_amount=total,
        amount_base=total,
        paid_amount=paid,
        paid_amount_base=paid,
        balance_due=total - paid,
        currency='AED',
        exchange_rate=Decimal('1'),
        payment_status='unpaid' if paid < total else 'paid',
        status='confirmed',
        is_active=True,
    )
    sale.sale_date = when or (
        datetime.now(timezone.utc) - timedelta(days=3))
    db.session.add(sale)
    db.session.commit()
    return sale


# --------------------------------------------------------------------------
# money() filter — exact strings
# --------------------------------------------------------------------------
class TestMoneyFilter:
    def test_money_exact_basic(self, app):
        with app.app_context():
            assert app.jinja_env.filters['money']('1234.5') == \
                f'{LRM}1,234.50{LRM}'

    def test_money_negative_keeps_minus_sign(self, app):
        with app.app_context():
            assert app.jinja_env.filters['money'](-1250.5) == \
                f'{LRM}-1,250.50{LRM}'

    def test_money_no_float_drift_at_boundary(self, app):
        # 0.1 + 0.2 style artifact must quantize cleanly via Decimal(str(x))
        with app.app_context():
            assert app.jinja_env.filters['money'](0.30000000000000004) == \
                f'{LRM}0.30{LRM}'

    def test_money_round_half_up_decimal_path(self, app):
        # A float would give 2.67; exact Decimal 2.675 half-up gives 2.68.
        with app.app_context():
            assert app.jinja_env.filters['money'](Decimal('2.675')) == \
                f'{LRM}2.68{LRM}'

    def test_money_currency_suffix(self, app):
        with app.app_context():
            assert app.jinja_env.filters['money'](100, 'AED') == \
                f'{LRM}100.00{LRM} AED'

    def test_money_thousands_grouping(self, app):
        with app.app_context():
            assert app.jinja_env.filters['money']('987654321.055') == \
                f'{LRM}987,654,321.06{LRM}'

    def test_money_none_and_invalid_passthrough(self, app):
        with app.app_context():
            f = app.jinja_env.filters['money']
            assert f(None) == ''
            assert f('abc') == 'abc'


# --------------------------------------------------------------------------
# num() filter — plain numeric cells
# --------------------------------------------------------------------------
class TestNumFilter:
    def test_num_grouping_and_quantize(self, app):
        with app.app_context():
            f = app.jinja_env.filters['num']
            assert f(5000) == '5,000.00'
            assert f(Decimal('50.000')) == '50.00'

    def test_num_none_and_invalid_passthrough(self, app):
        with app.app_context():
            f = app.jinja_env.filters['num']
            assert f(None) == ''
            assert f('n/a') == 'n/a'


# --------------------------------------------------------------------------
# status_badge() filter — complete mapping
# --------------------------------------------------------------------------
@pytest.mark.parametrize('status,cls,label', [
    ('unpaid', 'warning', 'غير مدفوع'),
    ('partial', 'info', 'جزئي'),
    ('paid', 'success', 'مدفوع'),
    ('void', 'secondary', 'ملغي'),
    ('bounced', 'danger', 'مرتد'),
])
class TestStatusBadgeFilter:
    def test_badge_mapping(self, app, status, cls, label):
        with app.app_context():
            html = str(app.jinja_env.filters['status_badge'](status))
        assert f'badge badge-{cls}' in html
        assert label in html

    def test_badge_mapping_case_insensitive(self, app, status, cls, label):
        with app.app_context():
            html = str(app.jinja_env.filters['status_badge'](
                status.upper()))
        assert f'badge badge-{cls}' in html

    def test_badge_unknown_status_escaped_secondary(self, app, status,
                                                    cls, label):
        with app.app_context():
            html = str(app.jinja_env.filters['status_badge']('<x>'))
        assert 'badge-secondary' in html
        assert '&lt;x&gt;' in html


# --------------------------------------------------------------------------
# Bidi safety — Arabic surrounding text keeps its order around amounts
# --------------------------------------------------------------------------
class TestBidiOrdering:
    def test_arabic_text_order_preserved_around_money(self, app):
        with app.app_context():
            out = render_template_string(
                'الإجمالي المستحق: {{ v|money }} بعد الخصم', v='1150.5')
        assert out == f'الإجمالي المستحق: {LRM}1,150.50{LRM} بعد الخصم'
        # digits stay one contiguous LTR run between the two LRMs
        digits = out[out.index(LRM) + 1:]
        assert digits.startswith('1,150.50')

    def test_negative_amount_inside_rtl_sentence(self, app):
        with app.app_context():
            out = render_template_string(
                'عجز الحساب {{ v|money }} درج بالسالب',
                v=Decimal('-42'))
        assert f'{LRM}-42.00{LRM}' in out

    def test_pipe_syntax_is_the_registered_contract(self, app):
        # Templates must use pipe syntax; guard against call-style regressions.
        with app.app_context():
            money_out = render_template_string('{{ v|money }}', v=7)
            cur_out = render_template_string("{{ v|money('AED') }}", v=7)
            num_out = render_template_string('{{ v|num }}', v='9.5')
            badge_out = render_template_string('{{ v|status_badge }}',
                                               v='paid')
        assert money_out == f'{LRM}7.00{LRM}'
        assert cur_out == f'{LRM}7.00{LRM} AED'
        assert num_out == '9.50'
        assert 'badge-success' in badge_out and 'مدفوع' in badge_out


# --------------------------------------------------------------------------
# Report page smoke renders (client + login_owner, seeded minimal data)
# --------------------------------------------------------------------------
@pytest.fixture
def seeded_report_data(db, owner_user):
    """Unpaid AED 1150.50 sale + a partner-share product so every audited
    grid (sales / receivables / partners) renders real amount rows."""
    cat = ProductCategory(name='Smoke Cat', name_ar='فئة', is_active=True)
    db.session.add(cat)
    db.session.flush()
    prod = Product(name='Grid Prod', sku='SKU-FILTERS-1',
                   category_id=cat.id, regular_price=Decimal('500'),
                   cost_price=Decimal('250'), current_stock=Decimal('9'),
                   min_stock_alert=Decimal('2'), is_active=True)
    cust = Customer(name='Grid Cust', customer_type='regular',
                    phone='+971509998877', is_active=True,
                    credit_limit=Decimal('90000'), balance=Decimal('0'))
    partner = Customer(name='Grid Partner', customer_type='partner',
                       phone='+971509996655', is_active=True,
                       credit_limit=Decimal('90000'), balance=Decimal('0'))
    db.session.add_all([prod, cust, partner])
    db.session.flush()
    db.session.add(ProductPartner(product_id=prod.id,
                                  partner_customer_id=partner.id,
                                  percentage=Decimal('25')))
    db.session.commit()
    sale = _seed_sale(db, owner_user.id, cust, 'S-FILTER-SMOKE-1',
                      Decimal('1150.50'))
    db.session.add(SaleLine(sale_id=sale.id, product_id=prod.id,
                            quantity=Decimal('2'), unit_price=Decimal('250'),
                            discount_percent=Decimal('0'),
                            line_total=Decimal('500'),
                            cost_price=Decimal('125')))
    db.session.commit()
    return sale


class TestReportPageSmoke:
    def test_sales_report_renders_num_cell(self, client, login_owner,
                                           seeded_report_data):
        resp = client.get('/reports/sales')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'class="num-cell"' in html
        assert '1,150.50' in html
        assert 'badge-success' in html or 'badge-warning' in html

    def test_receivables_report_renders_num_cell(self, client, login_owner,
                                                 seeded_report_data):
        resp = client.get('/reports/receivables')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'class="num-cell"' in html
        assert '1,150.50' in html

    def test_partners_report_renders_num_cell(self, client, login_owner,
                                              seeded_report_data):
        resp = client.get('/reports/partners')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'class="num-cell"' in html
        # 25% partner share of the AED 500 line total = 125.00
        assert '125.00' in html

    def test_cash_flow_negative_amount_red_class_with_minus(
            self, client, login_owner, db, owner_user):
        rev = GLAccount(code='4000-FT', name='Rev Filters',
                        type='revenue')
        exp = GLAccount(code='5000-FT', name='Exp Filters',
                        type='expense')
        db.session.add_all([rev, exp])
        db.session.flush()
        entry = GLJournalEntry(entry_number='JE-FILTER-1',
                               entry_date=datetime.now(),
                               is_posted=True, is_reversed=False,
                               created_by=owner_user.id)
        db.session.add(entry)
        db.session.flush()
        for acc, debit, credit in [(rev, 0, 100), (exp, 300, 0)]:
            db.session.add(GLJournalLine(
                entry_id=entry.id, account_id=acc.id,
                debit=Decimal(debit), credit=Decimal(credit),
                amount_base=Decimal(debit or credit)))
        db.session.commit()
        resp = client.get('/reports/cash-flow')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'class="num-cell money-neg"' in html
        assert '-200.00' in html
        assert 'money-pos' in html
