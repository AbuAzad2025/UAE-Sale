"""Tests for services/analytics_service.py and services/advanced_analytics.py."""

from datetime import date, datetime, timedelta, time, timezone
from decimal import Decimal

import pytest

from models import (
    Donation,
    GLAccount,
    GLJournalEntry,
    GLJournalLine,
    Package,
    PackagePurchase,
)
from services.advanced_analytics import AdvancedFinancialAnalytics
from services.analytics_service import AnalyticsService


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_days_ago(days=0, hours=0):
    return utc_now() - timedelta(days=days, hours=hours)


def make_donation(**kwargs):
    data = {
        'amount_usd': Decimal('100.00'),
        'payment_method': 'crypto',
        'status': 'completed',
        'transaction_type': 'donation',
        'created_at': utc_days_ago(hours=1),
    }
    data.update(kwargs)
    return Donation(**data)


def make_package(db, slug, name_ar, is_active=True):
    package = Package(
        name_ar=name_ar, name_en=slug.title(), slug=slug, price=99.0,
        currency='USD', is_active=is_active,
    )
    db.session.add(package)
    db.session.flush()
    return package


def make_purchase(db, package, email, amount, status='completed'):
    purchase = PackagePurchase(
        package_id=package.id, customer_name=email.split('@')[0],
        customer_email=email, payment_method='card', payment_status=status,
        amount_paid=float(amount),
    )
    db.session.add(purchase)
    return purchase


def gl_account(db, code, acc_type, **kwargs):
    account = GLAccount(
        code=code, name=f'Account {code}', name_ar=f'حساب {code}',
        type=acc_type, **kwargs,
    )
    db.session.add(account)
    db.session.flush()
    return account


def post_line(db, account, amount_base, number, when, posted=True):
    entry = GLJournalEntry(
        entry_number=number, entry_date=when,
        reference_type='manual', is_posted=posted,
    )
    db.session.add(entry)
    db.session.flush()
    db.session.add(GLJournalLine(
        entry_id=entry.id, account_id=account.id,
        amount_base=Decimal(str(amount_base)),
    ))
    return entry


def local_noon(days_back=0):
    day = date.today() - timedelta(days=days_back)
    return datetime.combine(day, time(12, 0))


class TestGetRevenueByPeriod:
    def test_empty_db_zero_shape(self, db):
        result = AnalyticsService.get_revenue_by_period(months=3)
        assert len(result['labels']) == 3
        assert result['purchases'] == [0.0, 0.0, 0.0]
        assert result['donations'] == [0.0, 0.0, 0.0]
        assert result['total_revenue'] == 0
        default = AnalyticsService.get_revenue_by_period()
        assert len(default['labels']) == 6
        assert default['total_revenue'] == 0

    def test_completed_donations_counted_pending_failed_and_old_excluded(self, db):
        db.session.add(make_donation(amount_usd=Decimal('250.00'), created_at=utc_days_ago(hours=2)))
        db.session.add(make_donation(amount_usd=Decimal('999.00'), status='pending'))
        db.session.add(make_donation(amount_usd=Decimal('888.00'), status='failed'))
        db.session.add(make_donation(amount_usd=Decimal('500.00'), created_at=utc_days_ago(200)))
        db.session.commit()

        result = AnalyticsService.get_revenue_by_period(months=3)
        assert result['donations'][-1] == 250.0
        assert sum(result['donations']) == 250.0
        assert result['purchases'] == [0.0, 0.0, 0.0]
        assert result['total_revenue'] == 250.0

    def test_purchase_type_lands_in_purchases_bucket(self, db):
        db.session.add(make_donation(
            amount_usd=Decimal('120.00'), transaction_type='purchase',
            created_at=utc_days_ago(5),
        ))
        db.session.add(make_donation(amount_usd=Decimal('60.00'), created_at=utc_days_ago(hours=5)))
        db.session.commit()

        result = AnalyticsService.get_revenue_by_period(months=3)
        assert result['purchases'] == [0.0, 0.0, 120.0]
        assert result['donations'] == [0.0, 0.0, 60.0]
        assert result['total_revenue'] == 180.0

    def test_multiple_buckets_and_label_format(self, db):
        db.session.add(make_donation(amount_usd=Decimal('200.00'), created_at=utc_days_ago(40)))
        db.session.add(make_donation(amount_usd=Decimal('100.00'), created_at=utc_days_ago(5)))
        db.session.commit()

        result = AnalyticsService.get_revenue_by_period(months=3)
        assert result['donations'] == [0.0, 200.0, 100.0]
        assert len(result['labels']) == 3
        for label in result['labels']:
            parts = label.split(' ')
            assert len(parts) == 2 and len(parts[0]) == 3 and len(parts[1]) == 4


class TestPackagePerformance:
    def test_empty_db_returns_empty_list(self, db):
        assert AnalyticsService.get_package_performance() == []

    def test_status_breakdown_inactive_package_and_avg_guard(self, db):
        active = make_package(db, 'pkg-active', 'باقة نشطة')
        inactive = make_package(db, 'pkg-inactive', 'باقة موقوفة', is_active=False)
        empty_pkg = make_package(db, 'pkg-empty', 'باقة فارغة')

        make_purchase(db, active, 'alice@test.com', Decimal('300.00'), 'completed')
        make_purchase(db, active, 'bob@test.com', Decimal('100.00'), 'completed')
        make_purchase(db, active, 'carol@test.com', Decimal('50.00'), 'pending')
        make_purchase(db, active, 'dave@test.com', Decimal('25.00'), 'failed')
        make_purchase(db, inactive, 'eve@test.com', Decimal('700.00'), 'completed')
        make_purchase(db, empty_pkg, 'frank@test.com', Decimal('80.00'), 'pending')
        db.session.commit()

        performance = {p['package_name']: p for p in AnalyticsService.get_package_performance()}
        assert set(performance.keys()) == {'باقة نشطة', 'باقة فارغة'}

        active_stats = performance['باقة نشطة']
        assert active_stats['total_sales'] == 4
        assert active_stats['completed'] == 2
        assert active_stats['pending'] == 1
        assert active_stats['revenue'] == 400.0
        assert active_stats['avg_price'] == 200.0

        empty_stats = performance['باقة فارغة']
        assert empty_stats['completed'] == 0
        assert empty_stats['pending'] == 1
        assert empty_stats['revenue'] == 0
        assert empty_stats['avg_price'] == 0


class TestPaymentMethodStats:
    def test_empty_db_shape(self, db):
        stats = AnalyticsService.get_payment_method_stats()
        assert stats == {'methods': [], 'counts': [], 'totals': []}

    def test_aggregation_per_method_completed_only(self, db):
        db.session.add(make_donation(amount_usd=Decimal('100.00'), payment_method='crypto'))
        db.session.add(make_donation(amount_usd=Decimal('50.00'), payment_method='crypto'))
        db.session.add(make_donation(amount_usd=Decimal('75.00'), payment_method='card'))
        db.session.add(make_donation(amount_usd=Decimal('999.00'), payment_method='paypal', status='pending'))
        db.session.commit()

        stats = AnalyticsService.get_payment_method_stats()
        by_method = dict(zip(stats['methods'], zip(stats['counts'], stats['totals'])))
        assert set(stats['methods']) == {'crypto', 'card'}
        assert by_method['crypto'] == (2, 150.0)
        assert by_method['card'] == (1, 75.0)


class TestCustomerBehavior:
    def test_empty_db_all_zeros(self, db):
        behavior = AnalyticsService.get_customer_behavior()
        assert behavior == {
            'total_customers': 0,
            'new_customers': 0,
            'returning_customers': 0,
            'vip_customers': 0,
            'avg_purchases_per_customer': 0,
            'avg_spent_per_customer': 0,
        }

    def test_new_returning_vip_and_averages(self, db):
        basic = make_package(db, 'pkg-basic', 'باقة أساسية')
        pro = make_package(db, 'pkg-pro', 'باقة احترافية')
        elite = make_package(db, 'pkg-elite', 'باقة النخبة')

        make_purchase(db, basic, 'alice@test.com', Decimal('600.00'))
        make_purchase(db, pro, 'alice@test.com', Decimal('600.00'))
        make_purchase(db, basic, 'bob@test.com', Decimal('100.00'))
        make_purchase(db, elite, 'carol@test.com', Decimal('1500.00'))
        db.session.commit()

        behavior = AnalyticsService.get_customer_behavior()
        assert behavior['total_customers'] == 3
        assert behavior['new_customers'] == 2
        assert behavior['returning_customers'] == 1
        assert behavior['vip_customers'] == 2
        assert behavior['avg_purchases_per_customer'] == 1.33
        assert behavior['avg_spent_per_customer'] == 933.33

        alice_purchases = PackagePurchase.query.filter_by(customer_email='alice@test.com').all()
        assert {p.package.name_ar for p in alice_purchases} == {'باقة أساسية', 'باقة احترافية'}


class TestPredictRevenue:
    def test_empty_db_zero_history_still_predicts(self, db):
        result = AnalyticsService.predict_revenue(months=3)
        assert result['historical_avg'] == 0
        assert result['growth_rate'] == 0.05
        assert len(result['predictions']) == 3
        for prediction in result['predictions']:
            assert prediction['predicted_revenue'] == 0

    def test_prediction_applies_growth_to_average(self, db):
        db.session.add(make_donation(amount_usd=Decimal('350.00'), created_at=utc_days_ago(hours=1)))
        db.session.add(make_donation(amount_usd=Decimal('250.00'), created_at=utc_days_ago(hours=2)))
        db.session.commit()

        result = AnalyticsService.predict_revenue(months=3)
        assert result['historical_avg'] == 100.0
        assert result['growth_rate'] == 0.05
        assert result['predictions'][0]['predicted_revenue'] == 105.0
        assert result['predictions'][1]['predicted_revenue'] == 110.25


class TestDailyStats:
    def test_empty_db_zero_shape(self, db):
        stats = AnalyticsService.get_daily_stats()
        assert stats == {
            'today_revenue': 0.0,
            'today_transactions': 0,
            'pending_today': 0,
            'completed_today': 0,
        }

    def test_today_counts_only_today_and_revenue_only_completed(self, db):
        db.session.add(make_donation(amount_usd=Decimal('100.00'), created_at=utc_now()))
        db.session.add(make_donation(
            amount_usd=Decimal('40.00'), status='pending', created_at=utc_now(),
        ))
        db.session.add(make_donation(
            amount_usd=Decimal('60.00'), status='failed', created_at=utc_now(),
        ))
        db.session.add(make_donation(amount_usd=Decimal('500.00'), created_at=utc_days_ago(2)))
        db.session.commit()

        stats = AnalyticsService.get_daily_stats()
        assert stats['today_revenue'] == 100.0
        assert stats['today_transactions'] == 3
        assert stats['pending_today'] == 1
        assert stats['completed_today'] == 1


class TestFinancialRatios:
    def _seed_full_ledger(self, db):
        cash = gl_account(db, '1101', 'asset')
        fixed = gl_account(db, '1201', 'asset')
        payables = gl_account(db, '2101', 'liability')
        loan = gl_account(db, '2201', 'liability')
        equity = gl_account(db, '3101', 'equity')
        revenue = gl_account(db, '4101', 'revenue')
        rent = gl_account(db, '5101', 'expense')
        utilities = gl_account(db, '6101', 'expense')

        plan = [
            (cash, 800), (fixed, 200),
            (payables, -400), (loan, -100),
            (equity, -300),
            (revenue, -1000),
            (rent, 250), (utilities, 50),
        ]
        for idx, (account, amount) in enumerate(plan, start=1):
            post_line(db, account, amount, f'JE-FULL-{idx:03d}', local_noon())
        db.session.commit()

    def test_full_ratio_math(self, db):
        self._seed_full_ledger(db)

        ratios = AdvancedFinancialAnalytics.get_financial_ratios()

        assert ratios['liquidity']['current_ratio'] == pytest.approx(2.0)
        assert ratios['liquidity']['quick_ratio'] == pytest.approx(1.6)
        assert ratios['liquidity']['cash_ratio'] == pytest.approx(0.6)

        assert ratios['profitability']['gross_profit_margin'] == pytest.approx(70.0)
        assert ratios['profitability']['net_profit_margin'] == pytest.approx(70.0)
        assert ratios['profitability']['return_on_assets'] == pytest.approx(70.0)
        assert ratios['profitability']['return_on_equity'] == pytest.approx(233.33, rel=1e-4)

        assert ratios['efficiency']['asset_turnover'] == pytest.approx(1.0)
        assert ratios['efficiency']['expense_ratio'] == pytest.approx(30.0)

        assert ratios['leverage']['debt_to_equity'] == pytest.approx(5.0 / 3.0)
        assert ratios['leverage']['debt_to_assets'] == pytest.approx(0.5)
        assert ratios['leverage']['equity_multiplier'] == pytest.approx(10.0 / 3.0)

        base = ratios['base_data']
        assert base == {
            'current_assets': 800.0,
            'total_assets': 1000.0,
            'current_liabilities': 400.0,
            'total_liabilities': 500.0,
            'equity': 300.0,
            'revenue': 1000.0,
            'expenses': 300.0,
            'net_profit': 700.0,
        }

    def test_unposted_entries_are_excluded(self, db):
        self._seed_full_ledger(db)
        revenue = GLAccount.query.filter_by(code='4101').first()
        cash = GLAccount.query.filter_by(code='1101').first()
        post_line(db, revenue, -999, 'JE-DRAFT-001', local_noon(), posted=False)
        post_line(db, cash, 555, 'JE-DRAFT-002', local_noon(), posted=False)
        db.session.commit()

        base = AdvancedFinancialAnalytics.get_financial_ratios()['base_data']
        assert base['revenue'] == 1000.0
        assert base['total_assets'] == 1000.0

    def test_pl_window_filters_while_balance_sheet_is_cumulative(self, db):
        revenue = gl_account(db, '4101', 'revenue')
        rent = gl_account(db, '5101', 'expense')
        cash = gl_account(db, '1101', 'asset')

        post_line(db, revenue, -1000, 'JE-WIN-001', local_noon(days_back=100))
        post_line(db, revenue, -5000, 'JE-WIN-002', local_noon(days_back=730))
        post_line(db, rent, 250, 'JE-WIN-003', local_noon(days_back=100))
        post_line(db, rent, 999, 'JE-WIN-004', local_noon(days_back=-10))
        post_line(db, cash, 111, 'JE-WIN-005', local_noon(days_back=730))
        db.session.commit()

        date_from = date.today() - timedelta(days=365)
        base = AdvancedFinancialAnalytics.get_financial_ratios(
            date_from=date_from, date_to=date.today(),
        )['base_data']

        assert base['revenue'] == 1000.0
        assert base['expenses'] == 250.0
        assert base['net_profit'] == 750.0
        assert base['total_assets'] == 111.0

    def test_empty_ledger_all_guards_return_zero(self, db):
        ratios = AdvancedFinancialAnalytics.get_financial_ratios()
        for group in ('liquidity', 'profitability', 'efficiency', 'leverage'):
            for value in ratios[group].values():
                assert value == 0
        assert all(v == 0.0 for v in ratios['base_data'].values())

    def test_entry_dated_today_included_until_end_of_day(self, db):
        cash = gl_account(db, '1101', 'asset')
        today_afternoon = datetime.combine(date.today(), time(15, 30))
        post_line(db, cash, 777, 'JE-TODAY-001', today_afternoon)
        db.session.commit()

        base = AdvancedFinancialAnalytics.get_financial_ratios()['base_data']
        assert base['total_assets'] == 777.0


class TestTrendAnalysis:
    def test_buckets_revenue_expense_profit_and_change(self, db):
        revenue = gl_account(db, '4101', 'revenue')
        rent = gl_account(db, '5101', 'expense')

        post_line(db, revenue, -900, 'JE-T-001', local_noon(days_back=1))
        post_line(db, rent, 300, 'JE-T-002', local_noon(days_back=1))
        post_line(db, revenue, -400, 'JE-T-003', local_noon(days_back=45))
        db.session.commit()

        trends = AdvancedFinancialAnalytics.get_trend_analysis(months=3)
        assert len(trends) == 3

        assert trends[0]['revenue'] == 0.0 and trends[0]['profit'] == 0.0
        assert trends[0]['change'] == 0

        assert trends[1]['revenue'] == 400.0
        assert trends[1]['profit'] == 400.0
        assert trends[1]['margin'] == 100.0
        assert trends[1]['change'] == 0

        assert trends[2]['revenue'] == 900.0
        assert trends[2]['expenses'] == 300.0
        assert trends[2]['profit'] == 600.0
        assert trends[2]['margin'] == pytest.approx(66.67, rel=1e-3)
        assert trends[2]['change'] == 50.0

    def test_empty_ledger_zero_series(self, db):
        trends = AdvancedFinancialAnalytics.get_trend_analysis(months=4)
        assert len(trends) == 4
        for item in trends:
            assert item['revenue'] == 0.0
            assert item['expenses'] == 0.0
            assert item['profit'] == 0.0
            assert item['margin'] == 0
            assert item['change'] == 0


class TestComparativeAnalysis:
    def test_current_and_last_month_periods(self, db):
        revenue = gl_account(db, '4101', 'revenue')
        rent = gl_account(db, '5101', 'expense')

        today_afternoon = datetime.combine(date.today(), time(15, 30))
        post_line(db, revenue, -700, 'JE-C-001', today_afternoon)
        post_line(db, rent, 200, 'JE-C-002', today_afternoon)
        post_line(db, revenue, -300, 'JE-C-003', local_noon(days_back=(date.today().day)))
        db.session.commit()

        periods = AdvancedFinancialAnalytics.get_comparative_analysis()
        assert set(periods.keys()) == {'current', 'last_month', 'last_year'}

        current = periods['current']
        assert current['revenue'] == 700.0
        assert current['expenses'] == 200.0
        assert current['profit'] == 500.0
        assert current['margin'] == pytest.approx(500 / 7, rel=1e-6)

        last_month = periods['last_month']
        assert last_month['revenue'] == 300.0
        assert last_month['profit'] == 300.0

    def test_unknown_period_is_skipped(self, db):
        periods = AdvancedFinancialAnalytics.get_comparative_analysis(['current', 'bogus'])
        assert list(periods.keys()) == ['current']

    def test_last_year_period_boundary(self, db):
        revenue = gl_account(db, '4101', 'revenue')
        last_year_day = date(date.today().year - 1, 1, 15)
        post_line(db, revenue, -250, 'JE-Y-001',
                  datetime.combine(last_year_day, time(12, 0)))
        db.session.commit()

        periods = AdvancedFinancialAnalytics.get_comparative_analysis(['last_year'])
        assert periods['last_year']['revenue'] == 250.0
        assert periods['last_year']['profit'] == 250.0
        assert periods['last_year']['margin'] == 100.0


class TestAccountTypeBalanceFullPeriod:
    def test_full_balance_branch_uses_abs_get_balance(self, db):
        revenue = gl_account(db, '4201', 'revenue')
        post_line(db, revenue, -800, 'JE-B-001', local_noon())
        db.session.commit()

        total = AdvancedFinancialAnalytics._calculate_account_type_balance('revenue')
        assert total == Decimal('800.000')


class TestExpenseRevenueBreakdown:
    def test_expense_breakdown_sorted_with_percentages(self, db):
        salaries = gl_account(db, '5001', 'expense')
        marketing = gl_account(db, '5201', 'expense')
        gl_account(db, '5000', 'expense', is_header=True)
        retired = gl_account(db, '5900', 'expense', is_active=False)

        post_line(db, salaries, 300, 'JE-E-001', local_noon())
        post_line(db, marketing, 100, 'JE-E-002', local_noon())
        post_line(db, retired, 999, 'JE-E-003', local_noon())
        db.session.commit()

        result = AdvancedFinancialAnalytics.get_expense_breakdown()
        assert result['total'] == 400.0
        assert [item['account_code'] for item in result['items']] == ['5001', '5201']
        assert [item['amount'] for item in result['items']] == [300.0, 100.0]
        assert [item['percentage'] for item in result['items']] == [75.0, 25.0]
        assert result['items'][0]['account_name'].startswith('5001')

    def test_revenue_breakdown_credit_normal_accounts(self, db):
        sales_rev = gl_account(db, '4101', 'revenue')
        other_rev = gl_account(db, '4201', 'revenue')

        post_line(db, sales_rev, -800, 'JE-RB-001', local_noon())
        post_line(db, other_rev, -200, 'JE-RB-002', local_noon())
        db.session.commit()

        result = AdvancedFinancialAnalytics.get_revenue_breakdown()
        assert result['total'] == 1000.0
        assert [(item['account_code'], item['amount'], item['percentage'])
                for item in result['items']] == [('4101', 800.0, 80.0), ('4201', 200.0, 20.0)]

    def test_empty_breakdowns(self, db):
        assert AdvancedFinancialAnalytics.get_expense_breakdown() == {'items': [], 'total': 0.0}
        assert AdvancedFinancialAnalytics.get_revenue_breakdown() == {'items': [], 'total': 0.0}

    def test_zero_balance_accounts_report_zero_percentage(self, db):
        gl_account(db, '5301', 'expense')
        gl_account(db, '4301', 'revenue')
        db.session.commit()

        expenses = AdvancedFinancialAnalytics.get_expense_breakdown()
        revenue = AdvancedFinancialAnalytics.get_revenue_breakdown()
        assert expenses['total'] == 0.0
        assert expenses['items'][0]['percentage'] == 0
        assert revenue['total'] == 0.0
        assert revenue['items'][0]['percentage'] == 0


class TestForecastingData:
    def test_flat_history_produces_flat_forecast(self, db):
        revenue = gl_account(db, '4101', 'revenue')
        rent = gl_account(db, '5101', 'expense')

        plan = [
            ('JE-FC-001', 10), ('JE-FC-002', 10),
            ('JE-FC-003', 40), ('JE-FC-004', 40),
            ('JE-FC-005', 70), ('JE-FC-006', 70),
        ]
        for idx, (number, days_back) in enumerate(plan):
            account = revenue if idx % 2 == 0 else rent
            post_line(db, account, -600 if account is revenue else 200,
                      number, local_noon(days_back=days_back))
        db.session.commit()

        forecasts = AdvancedFinancialAnalytics.get_forecasting_data(months_ahead=3)
        assert len(forecasts) == 3
        for item in forecasts:
            assert item['is_forecast'] is True
            assert item['revenue'] == 600.0
            assert item['expenses'] == 200.0
            assert item['profit'] == 400.0
            assert item['margin'] == 66.67

    def test_returns_empty_when_history_missing(self, db, monkeypatch):
        monkeypatch.setattr(
            AdvancedFinancialAnalytics, 'get_trend_analysis',
            staticmethod(lambda months=12: []),
        )
        assert AdvancedFinancialAnalytics.get_forecasting_data(months_ahead=4) == []


class TestDashboardSummary:
    def test_summary_combines_all_sections(self, db):
        revenue = gl_account(db, '4101', 'revenue')
        rent = gl_account(db, '5101', 'expense')
        cash = gl_account(db, '1101', 'asset')
        payables = gl_account(db, '2101', 'liability')

        post_line(db, revenue, -1000, 'JE-D-001', local_noon())
        post_line(db, rent, 400, 'JE-D-002', local_noon())
        post_line(db, cash, 800, 'JE-D-003', local_noon())
        post_line(db, payables, -400, 'JE-D-004', local_noon())
        db.session.commit()

        summary = AdvancedFinancialAnalytics.get_dashboard_summary()
        assert {'ratios', 'trends', 'expense_breakdown',
                'revenue_breakdown', 'forecast', 'generated_at'} <= set(summary.keys())

        assert summary['ratios']['base_data']['revenue'] == 1000.0
        assert summary['ratios']['base_data']['net_profit'] == 600.0
        assert len(summary['trends']) == 6
        assert len(summary['forecast']) == 3
        assert summary['expense_breakdown']['total'] == 400.0
        assert summary['revenue_breakdown']['total'] == 1000.0
        datetime.fromisoformat(summary['generated_at'])
