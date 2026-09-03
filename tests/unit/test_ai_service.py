"""Unit tests for services/ai_service.py — AZAD AI assistant."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import services.ai_service as ai_mod
from models import Customer, Payment, Product, Sale, SaleLine
from services.ai_service import AIService


def _noop_load_dotenv(*args, **kwargs):
    return False


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.setattr('dotenv.load_dotenv', _noop_load_dotenv)
    for key in ('GROQ_API_KEY', 'GEMINI_API_KEY', 'OPENAI_API_KEY'):
        monkeypatch.delenv(key, raising=False)


def _utc(**delta):
    return datetime.now(timezone.utc) - timedelta(**delta)


def _make_sale(number, customer=None, seller=None, amount=Decimal('100'),
               paid=Decimal('0'), days_ago=0, hour=10, rate=Decimal('1'),
               currency='ILS', created_days_ago=0, status='confirmed'):
    sale_date = _utc(days=days_ago).replace(hour=hour, minute=0, second=0, microsecond=0)
    return Sale(
        sale_number=number,
        customer_id=customer.id if customer else None,
        seller_id=seller.id if seller else None,
        total_amount=amount, amount_base=amount,
        paid_amount=paid, paid_amount_base=paid,
        balance_due=amount - paid, currency=currency,
        exchange_rate=rate,
        payment_status='unpaid' if paid == 0 else 'partial',
        status=status, is_active=True, sale_date=sale_date,
        created_at=_utc(days=created_days_ago),
    )


def _make_payment(number, customer, amount):
    # F-05: customer payments are INCOMING (sale_id set, supplier_id NULL).
    return Payment(
        payment_number=number, payment_type='receipt', payment_method='cash',
        direction='incoming',
        customer_id=customer.id, amount=amount, amount_base=amount, currency='AED',
    )


def _make_product(sku, stock=Decimal('100'), minimum=Decimal('10'),
                  cost=Decimal('50'), price=Decimal('100')):
    return Product(name=f'P {sku}', sku=sku, cost_price=cost, regular_price=price,
                   current_stock=stock, min_stock_alert=minimum, is_active=True)


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _patch_engine(monkeypatch, attr):
    engine = Mock()
    monkeypatch.setattr(AIService, attr, engine)
    return engine


class TestProviderAndKeys:
    def test_api_key_priority_groq_first(self, clean_env, monkeypatch):
        monkeypatch.setenv('GROQ_API_KEY', 'gk')
        monkeypatch.setenv('GEMINI_API_KEY', 'mk')
        monkeypatch.setenv('OPENAI_API_KEY', 'ok')
        assert AIService.get_api_key() == 'gk'

    def test_api_key_gemini_then_openai(self, clean_env, monkeypatch):
        monkeypatch.setenv('GEMINI_API_KEY', 'mk')
        assert AIService.get_api_key() == 'mk'
        monkeypatch.delenv('GEMINI_API_KEY')
        monkeypatch.setenv('OPENAI_API_KEY', 'ok')
        assert AIService.get_api_key() == 'ok'

    def test_no_keys_returns_none_and_local_provider(self, clean_env):
        assert AIService.get_api_key() is None
        assert AIService.get_provider() == 'local'

    def test_provider_detection(self, clean_env, monkeypatch):
        monkeypatch.setenv('GROQ_API_KEY', 'gk')
        assert AIService.get_provider() == 'groq'
        monkeypatch.delenv('GROQ_API_KEY')
        monkeypatch.setenv('GEMINI_API_KEY', 'mk')
        assert AIService.get_provider() == 'gemini'
        monkeypatch.delenv('GEMINI_API_KEY')
        monkeypatch.setenv('OPENAI_API_KEY', 'ok')
        assert AIService.get_provider() == 'openai'

    def test_is_enabled_always_true(self):
        assert AIService.is_enabled() is True


class TestSensitiveRequest:
    def test_password_from_non_owner_denied(self):
        user = SimpleNamespace(is_owner=False)
        sensitive, owner_only, response = AIService.is_sensitive_request('ما كلمة المرور؟', user)
        assert sensitive is True and owner_only is False
        assert response['type'] == 'warning'
        assert response['icon'] == '🔒'

    def test_password_from_owner_allowed(self):
        user = SimpleNamespace(is_owner=True)
        assert AIService.is_sensitive_request('show password', user) == (True, True, None)

    def test_none_user_denied(self):
        sensitive, owner_only, response = AIService.is_sensitive_request('password؟', None)
        assert (sensitive, owner_only) == (True, False)
        assert 'سرية' in response['message']

    def test_user_without_is_owner_attr_denied(self):
        sensitive, owner_only, response = AIService.is_sensitive_request('pwd?', SimpleNamespace(name='x'))
        assert (sensitive, owner_only) == (True, False)
        assert response is not None

    def test_short_users_question_sensitive(self):
        sensitive, owner_only, response = AIService.is_sensitive_request('معلومات المستخدمين', None)
        assert (sensitive, owner_only) == (True, False)
        assert response is not None

    def test_long_users_question_not_sensitive(self):
        msg = 'أريد تحليل معلومات المستخدمين الذين سجلوا دخولهم خلال الشهر الماضي للتقارير'
        assert AIService.is_sensitive_request(msg, None) == (False, False, None)

    def test_definite_article_normalized_for_security_words(self):
        sensitive, _, response = AIService.is_sensitive_request('كيف أعدل الصلاحيات هنا', None)
        assert sensitive is True
        assert response is not None

    def test_normal_business_question_allowed(self):
        assert AIService.is_sensitive_request('كم سعر فلتر الزيت؟', None) == (False, False, None)


class TestExecuteAiAction:
    def test_no_json_in_response_returns_none(self):
        assert AIService._execute_ai_action('رد عادي بدون أي JSON هنا', 1) is None

    def test_create_customer_template(self):
        text = 'حسناً\n```json\n{"action": "create_customer", "data_needed": ["الاسم", "الهاتف"]}\n```'
        result = AIService._execute_ai_action(text, 1)
        assert result is not None
        assert 'عميل جديد' in result

    def test_create_product_template(self):
        result = AIService._execute_ai_action('{"action": "create_product"}', 1)
        assert 'منتج جديد' in result

    def test_create_sale_template(self):
        result = AIService._execute_ai_action('{"action": "create_sale"}', 1)
        assert 'فاتورة' in result

    def test_unknown_action_returns_none(self):
        assert AIService._execute_ai_action('{"action": "delete_world"}', 1) is None

    def test_broken_json_returns_none(self):
        assert AIService._execute_ai_action('{"action": "create_customer",,}', 1) is None


class TestRiskRecommendation:
    @pytest.mark.parametrize('level,fragment', [
        ('low', 'ممتاز'),
        ('medium', 'جيد'),
        ('high', 'عالي المخاطر'),
    ])
    def test_known_levels(self, level, fragment):
        assert fragment in AIService._get_risk_recommendation(level)

    def test_unknown_level_fallback(self):
        assert AIService._get_risk_recommendation('bogus') == 'تحليل غير متوفر'


class TestContextualHelpAndCapabilities:
    @pytest.mark.parametrize('page', ['dashboard', 'sales', 'products', 'customers', 'warehouse'])
    def test_known_pages(self, page):
        result = AIService.contextual_help(page, 'owner')
        assert result['page'] == page and result['user_role'] == 'owner'
        assert result['help'] != 'لا توجد مساعدة متاحة لهذه الصفحة'

    def test_unknown_page_default_message(self):
        result = AIService.contextual_help('nope', 'seller')
        assert result['help'] == 'لا توجد مساعدة متاحة لهذه الصفحة'

    def test_capabilities_structure(self):
        caps = AIService.get_system_capabilities()
        for key in ('neural_networks', 'reasoning', 'memory', 'code_generation',
                    'multi_agent', 'conversation', 'vision', 'self_improvement', 'master_brain'):
            assert key in caps
        assert caps['neural_networks']['models'] == 11
        assert caps['master_brain']['available'] is True


class TestRecommendPrice:
    def test_missing_product_or_customer(self, app, db, test_customer):
        assert AIService.recommend_price(99999, test_customer.id) is None

    def test_missing_customer(self, app, db, test_product):
        assert AIService.recommend_price(test_product.id, 99999) is None

    def test_regular_customer_without_history(self, app, db, test_product, test_customer):
        result = AIService.recommend_price(test_product.id, test_customer.id)
        assert result['base_price'] == 100.0
        assert result['recommended_price'] == 100.0
        assert result['customer_avg'] is None
        assert test_customer.name in result['reason']

    def test_merchant_and_partner_discounted_base(self, app, db, test_product, test_category):
        merchant = Customer(name='M', customer_type='merchant', is_active=True, balance=Decimal('0'))
        partner = Customer(name='P', customer_type='partner', is_active=True, balance=Decimal('0'))
        db.session.add_all([merchant, partner])
        test_product.merchant_price = Decimal('20')
        test_product.partner_price = Decimal('30')
        db.session.commit()
        assert AIService.recommend_price(test_product.id, merchant.id)['base_price'] == 80.0
        assert AIService.recommend_price(test_product.id, partner.id)['base_price'] == 70.0

    def test_history_blends_average(self, app, db, test_product, test_customer):
        sale = _make_sale('RP-H1', customer=test_customer, amount=Decimal('300'), paid=Decimal('300'))
        db.session.add(sale)
        db.session.flush()
        db.session.add(SaleLine(
            sale_id=sale.id, product_id=test_product.id, quantity=Decimal('2'),
            unit_price=Decimal('150'), discount_percent=Decimal('0'),
            line_total=Decimal('300'), cost_price=Decimal('50'),
        ))
        db.session.commit()
        result = AIService.recommend_price(test_product.id, test_customer.id)
        assert result['customer_avg'] == 150.0
        assert result['recommended_price'] == 125.0


class TestStockAlerts:
    def test_missing_product_returns_none(self, app, db):
        assert AIService.check_stock_alert(99999, 5) is None

    def test_insufficient_stock_error(self, app, db, test_product):
        alert = AIService.check_stock_alert(test_product.id, 150)
        assert alert['type'] == 'error'
        assert 'غير كافٍ' in alert['message']

    def test_low_remaining_warning(self, app, db, test_product):
        alert = AIService.check_stock_alert(test_product.id, 95)
        assert alert['type'] == 'warning'
        assert 'تحذير' in alert['message']

    def test_sufficient_stock_no_alert(self, app, db, test_product):
        assert AIService.check_stock_alert(test_product.id, 50) is None


class TestInventoryHealth:
    def test_empty_inventory(self, app, db):
        result = AIService.analyze_inventory_health()
        assert result['success'] is False
        assert 'منتجات' in result['message']

    def test_mixed_stock_weak_rating(self, app, db):
        db.session.add_all([
            _make_product('IH-A', stock=Decimal('0')),
            _make_product('IH-B', stock=Decimal('5')),
            _make_product('IH-C', stock=Decimal('100')),
        ])
        db.session.commit()
        result = AIService.analyze_inventory_health()
        assert result['summary'] == {'total': 3, 'out': 1, 'low': 1, 'good': 1}
        assert result['health_score'] == 33
        assert result['rating'] == 'ضعيف'

    def test_excellent_boundary_eighty(self, app, db):
        db.session.add_all([
            _make_product('IH-X', stock=Decimal('0')),
            *(_make_product(f'IH-G{i}', stock=Decimal('90')) for i in range(4)),
        ])
        db.session.commit()
        result = AIService.analyze_inventory_health()
        assert result['health_score'] == 80
        assert result['rating'] == 'ممتاز'


class TestOptimizeInventoryLevels:
    def test_low_stock_products_recommended(self, app, db):
        low = _make_product('OI-L', stock=Decimal('5'), minimum=Decimal('10'), cost=Decimal('50'))
        healthy = _make_product('OI-H', stock=Decimal('100'), minimum=Decimal('10'))
        db.session.add_all([low, healthy])
        db.session.commit()
        result = AIService.optimize_inventory_levels()
        assert result['success'] is True
        assert result['total_products'] == 1
        row = result['products_to_order'][0]
        assert row['product_id'] == low.id
        assert row['recommended_order'] == 25.0
        assert row['estimated_cost'] == 1250.0

    def test_healthy_inventory_empty_orders(self, app, db):
        db.session.add(_make_product('OI-OK', stock=Decimal('100')))
        db.session.commit()
        result = AIService.optimize_inventory_levels()
        assert result == {'success': True, 'products_to_order': [], 'total_products': 0}


class TestExchangeRateSuggestion:
    def test_defaults_when_no_sales(self, app, db):
        result = AIService.get_exchange_rate_suggestion('USD')
        assert result == {'currency': 'USD', 'suggested_rate': 3.70, 'latest_rate': None,
                          'source': 'سعر افتراضي', 'count': 0}

    @pytest.mark.parametrize('currency,expected', [('EUR', 4.05), ('ILS', 1.0), ('JPY', 1.0)])
    def test_default_rate_table(self, app, db, currency, expected):
        assert AIService.get_exchange_rate_suggestion(currency)['suggested_rate'] == expected

    def test_internal_average_of_recent_sales(self, app, db):
        db.session.add(_make_sale('ER-1', currency='USD', rate=Decimal('3.6'),
                                  amount=Decimal('10'), created_days_ago=2))
        db.session.add(_make_sale('ER-2', currency='USD', rate=Decimal('3.8'),
                                  amount=Decimal('10'), created_days_ago=1))
        db.session.commit()
        result = AIService.get_exchange_rate_suggestion('USD')
        assert result['count'] == 2
        assert result['suggested_rate'] == 3.7
        assert result['latest_rate'] == 3.8
        assert 'داخلي' in result['source']

    def test_stale_sales_outside_week_window_ignored(self, app, db):
        db.session.add(_make_sale('ER-old', currency='USD', rate=Decimal('9.9'),
                                  amount=Decimal('10'), created_days_ago=30))
        db.session.commit()
        result = AIService.get_exchange_rate_suggestion('USD')
        assert result['source'] == 'سعر افتراضي'
        assert result['suggested_rate'] == 3.70


class TestPredictSalesTrend:
    def test_no_sales(self, app, db):
        result = AIService.predict_sales_trend()
        assert result == {'prediction': None, 'confidence': 0, 'message': 'لا توجد بيانات كافية'}

    def test_fewer_than_seven_days(self, app, db):
        for i in range(6):
            db.session.add(_make_sale(f'TR-{i}', days_ago=i, amount=Decimal('100')))
        db.session.commit()
        result = AIService.predict_sales_trend()
        assert result['prediction'] is None
        assert '7 أيام' in result['message']

    def test_uptrend_predictions(self, app, db):
        for d in range(8):
            db.session.add(_make_sale(f'TU-{d}', days_ago=7 - d, amount=Decimal('100') * (d + 1)))
        db.session.commit()
        result = AIService.predict_sales_trend(days_ahead=3)
        assert 'صاعد' in result['trend']['direction']
        assert result['trend']['slope'] == 100.0
        assert result['prediction']['predictions'] == [1000.0, 1100.0, 1200.0]
        assert result['prediction']['total_predicted'] == 3300.0
        assert result['prediction']['daily_avg'] == 1100.0
        assert result['historical']['avg_daily'] == 450.0
        assert result['confidence'] == 100
        assert result['historical']['days_analyzed'] == 8

    def test_downtrend_clamps_negatives_to_zero(self, app, db):
        for d in range(7):
            db.session.add(_make_sale(f'TD-{d}', days_ago=6 - d,
                                      amount=Decimal('800') - Decimal('100') * d))
        db.session.commit()
        result = AIService.predict_sales_trend(days_ahead=2)
        assert 'نازل' in result['trend']['direction']
        assert all(p >= 0 for p in result['prediction']['predictions'])


class TestProfitMargins:
    def test_no_sales(self, app, db):
        assert AIService.analyze_profit_margins() == {'success': False, 'message': 'لا توجد مبيعات'}

    def test_margin_with_line_items(self, app, db, test_sale, test_product):
        result = AIService.analyze_profit_margins()
        assert result['success'] is True
        assert result['overall']['revenue'] == 100.0
        assert result['overall']['cost'] == 50.0
        assert result['overall']['profit'] == 50.0
        assert result['overall']['margin'] == 50.0
        top = result['top_profitable'][0]
        assert top['name'] == test_product.name
        assert top['quantity'] == 2.0
        assert top['margin'] == 50.0
        assert result['least_profitable'][-1]['name'] == test_product.name

    def test_zero_revenue_branch(self, app, db):
        db.session.add(_make_sale('PM-Z', amount=Decimal('0')))
        db.session.commit()
        result = AIService.analyze_profit_margins()
        assert result['success'] is True
        assert result['overall'] == {'revenue': 0.0, 'cost': 0.0, 'profit': 0.0, 'margin': 0.0}
        assert result['top_profitable'] == []


class TestSalesPatterns:
    def test_insufficient_data(self, app, db):
        for i in range(9):
            db.session.add(_make_sale(f'SP-{i}', days_ago=i))
        db.session.commit()
        assert AIService.detect_sales_patterns() == {'success': False, 'message': 'بيانات غير كافية'}

    def test_best_day_and_peak_hour(self, app, db):
        for i in range(10):
            db.session.add(_make_sale(f'SPX-{i}', days_ago=1, hour=14, amount=Decimal('100') * (i + 1)))
        db.session.commit()
        result = AIService.detect_sales_patterns()
        assert result['success'] is True
        assert result['best_day']['count'] == 10
        assert result['best_day']['sales'] == 5500.0
        assert result['peak_hour'] == {'hour': '14:00', 'count': 10}
        day_names = ['الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
        expected_day = day_names[_utc(days=1).replace(hour=14).weekday()]
        assert result['best_day']['day'] == expected_day


class TestCustomerBehaviorAnalysis:
    def test_unknown_customer(self, app, db):
        assert AIService.analyze_customer_behavior(999999) is None

    def test_clean_customer_low_risk(self, app, db, test_customer):
        result = AIService.analyze_customer_behavior(test_customer.id)
        assert result['total_sales_90d'] == 0.0
        assert result['current_balance'] == 0.0
        assert result['risk_level'] == 'low'
        assert 'ممتاز' in result['recommendation']

    def test_high_risk_unpaid_customer(self, app, db, test_customer):
        db.session.add(_make_sale('CB-H', customer=test_customer, amount=Decimal('1000')))
        db.session.commit()
        result = AIService.analyze_customer_behavior(test_customer.id)
        assert result['risk_level'] == 'high'
        assert 'عالي المخاطر' in result['recommendation']
        assert result['current_balance'] == 1000.0

    def test_medium_risk_partial_payment(self, app, db, test_customer):
        db.session.add(_make_sale('CB-M', customer=test_customer, amount=Decimal('1000'), paid=Decimal('700')))
        db.session.commit()
        result = AIService.analyze_customer_behavior(test_customer.id)
        assert result['risk_level'] == 'medium'
        assert result['avg_payment_delay_days'] == 0

    def test_payment_delay_measured(self, app, db, test_customer):
        sale = _make_sale('CB-D', customer=test_customer, amount=Decimal('1000'), paid=Decimal('900'))
        sale.created_at = _utc(days=5)
        db.session.add(sale)
        db.session.add(_make_payment('CB-P1', test_customer, Decimal('900')))
        db.session.commit()
        result = AIService.analyze_customer_behavior(test_customer.id)
        assert result['avg_payment_delay_days'] == 5.0
        assert result['total_paid_90d'] == 900.0
        assert result['risk_level'] == 'low'


class TestBusinessInsights:
    def test_fresh_system_today_insight(self, app, db):
        insights = AIService.generate_business_insights()
        titles = [i['title'] for i in insights]
        assert 'مبيعات اليوم' in titles
        today = [i for i in insights if i['title'] == 'مبيعات اليوم'][0]
        assert today['priority'] == 'low'

    def test_combined_insights(self, app, db, test_customer):
        db.session.add(_make_product('BI-L', stock=Decimal('5'), minimum=Decimal('10')))
        db.session.add(_make_sale('BI-S1', customer=test_customer, amount=Decimal('2000'), days_ago=1))
        db.session.commit()
        insights = AIService.generate_business_insights()
        by_title = {i['title']: i for i in insights}
        assert by_title['تنبيه المخزون']['priority'] == 'high'
        assert by_title['تنبيه المخزون']['message'].startswith('يوجد 1')
        assert by_title['متابعة المدفوعات']['priority'] == 'medium'
        assert by_title['مبيعات اليوم']['priority'] == 'low'


class TestGatherRelevantKnowledge:
    def test_basic_sections_present(self, app, db):
        result = AIService._gather_relevant_knowledge('سؤال', {'context': {}})
        assert 'بيانات النظام الكاملة' in result
        assert 'بيانات الشركة' in result

    def test_current_user_section_added(self, app, db, owner_user):
        local_result = {'context': {'current_user': owner_user}}
        result = AIService._gather_relevant_knowledge('سؤال', local_result)
        assert 'المستخدم الحالي' in result


class TestChatResponse:
    def _stub_assistant(self, monkeypatch, reply):
        import ai_knowledge.intelligent_assistant as ia_mod
        calls = {}

        def process(message, user_id=None, context=None):
            calls.update(message=message, user_id=user_id, context=context)
            return {'response': reply}

        monkeypatch.setattr(ia_mod.intelligent_assistant, 'process', process)
        return calls

    def test_force_local_skips_groq(self, app, db, monkeypatch, owner_user):
        self._stub_assistant(monkeypatch, 'LOCAL-REPLY')
        context = {'force_local': True, 'current_user': owner_user}
        result = AIService.chat_response('سؤال تجريبي', context)
        assert result.startswith('LOCAL-REPLY')
        assert result.endswith('<sub>💻 المصدر: النظام المحلي الذكي</sub>')

    def test_local_context_passed_to_assistant(self, app, db, monkeypatch, owner_user):
        calls = self._stub_assistant(monkeypatch, 'LOCAL')
        AIService.chat_response('مرحبا', {'force_local': True, 'current_user': owner_user})
        assert calls['user_id'] == owner_user.id
        assert calls['context']['force_local'] is True

    def test_no_api_key_local_fallback(self, app, db, monkeypatch, clean_env):
        self._stub_assistant(monkeypatch, 'LOCAL-ONLY')
        result = AIService.chat_response('سؤال', {})
        assert 'LOCAL-ONLY' in result
        assert 'النظام المحلي الذكي' in result

    def _setup_groq(self, monkeypatch, provider='groq'):
        monkeypatch.setattr(AIService, 'get_api_key', staticmethod(lambda: 'KEY'))
        monkeypatch.setattr(AIService, 'get_provider', staticmethod(lambda: provider))
        monkeypatch.setattr(AIService, '_train_local_from_groq', staticmethod(lambda *a: None))

    @pytest.mark.parametrize('provider,url,model', [
        ('groq', 'https://api.groq.com/openai/v1/chat/completions', 'llama-3.3-70b-versatile'),
        ('gemini',
         'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent',
         'gemini-2.0-flash-exp'),
        ('openai', 'https://api.openai.com/v1/chat/completions', 'gpt-4'),
    ])
    def test_provider_endpoints(self, app, db, monkeypatch, provider, url, model):
        self._stub_assistant(monkeypatch, 'LOCAL')
        self._setup_groq(monkeypatch, provider)
        captured = {}

        def fake_post(post_url, headers=None, json=None, timeout=None):
            captured.update(url=post_url, headers=headers, payload=json, timeout=timeout)
            return _FakeResp(200, {'choices': [{'message': {'content': 'GROQ-SAYS'}}]})

        monkeypatch.setattr(requests, 'post', fake_post)
        result = AIService.chat_response('سؤال', {})
        assert captured['url'] == url
        assert captured['payload']['model'] == model
        assert captured['timeout'] == 20
        assert captured['headers']['Authorization'] == 'Bearer KEY'
        assert 'GROQ-SAYS' in result
        assert f'<sub>🤖 المصدر: {provider.upper()} API + التحليل المحلي</sub>' in result

    def test_http_error_falls_back_local(self, app, db, monkeypatch):
        self._stub_assistant(monkeypatch, 'LOCAL-FALLBACK')
        self._setup_groq(monkeypatch)
        monkeypatch.setattr(requests, 'post', lambda *a, **k: _FakeResp(500, {}))
        result = AIService.chat_response('سؤال', {})
        assert 'LOCAL-FALLBACK' in result
        assert 'النظام المحلي الذكي' in result

    def test_network_exception_falls_back_local(self, app, db, monkeypatch):
        self._stub_assistant(monkeypatch, 'LOCAL-FALLBACK')
        self._setup_groq(monkeypatch)

        def boom(*a, **k):
            raise requests.exceptions.Timeout('offline')

        monkeypatch.setattr(requests, 'post', boom)
        result = AIService.chat_response('سؤال', {})
        assert 'LOCAL-FALLBACK' in result

    def test_action_json_in_groq_reply_is_executed(self, app, db, monkeypatch):
        self._stub_assistant(monkeypatch, 'LOCAL')
        self._setup_groq(monkeypatch)
        content = 'تم!\n{"action": "create_product", "data_needed": []}'
        monkeypatch.setattr(requests, 'post',
                            lambda *a, **k: _FakeResp(200, {'choices': [{'message': {'content': content}}]}))
        result = AIService.chat_response('أضف منتج', {})
        assert 'منتج جديد' in result
        assert 'GROQ' in result


class TestTrainLocalFromGroq:
    def test_feedback_forwarded_to_learning_system(self, monkeypatch):
        import ai_knowledge.learning_system as ls_mod
        captured = {}

        class LS:
            def learn_from_groq_feedback(self, data):
                captured.update(data)

        monkeypatch.setattr(ls_mod, 'learning_system', LS())
        AIService._train_local_from_groq('Q', 'L', 'G', 42)
        assert captured['question'] == 'Q'
        assert captured['local_answer'] == 'L'
        assert captured['improved_answer'] == 'G'
        assert captured['user_id'] == 42
        datetime.fromisoformat(captured['timestamp'])

    def test_learning_failure_swallowed(self, monkeypatch):
        import ai_knowledge.learning_system as ls_mod

        class LS:
            def learn_from_groq_feedback(self, data):
                raise RuntimeError('disk full')

        monkeypatch.setattr(ls_mod, 'learning_system', LS())
        assert AIService._train_local_from_groq('Q', 'L', 'G', 1) is None


class TestUserInfoForOwner:
    def test_lookup_by_username(self, app, db, owner_user):
        result = AIService.get_user_info_for_owner(owner_user.username)
        assert result['success'] is True
        assert result['user']['username'] == owner_user.username
        # Security: password hashes must NEVER be exfiltrated to the AI layer
        assert 'password_hash' not in result['user']
        assert result['user']['role'] == 'المالك'
        assert result['user']['is_owner'] is True

    def test_lookup_by_email_fragment(self, app, db, owner_user):
        result = AIService.get_user_info_for_owner('owner@te')
        assert result['success'] is True
        assert result['user']['id'] == owner_user.id

    def test_unknown_username(self, app, db):
        result = AIService.get_user_info_for_owner('ghost-user-404')
        assert result['success'] is False
        assert 'ghost-user-404' in result['message']

    def test_all_users_listing(self, app, db, owner_user):
        result = AIService.get_user_info_for_owner()
        assert result['success'] is True
        assert result['count'] == len(result['users'])
        assert any(u['is_owner'] for u in result['users'])
        # Security: no password hashes in the list either
        assert all('password_hash' not in u for u in result['users'])


class TestNeuralMethods:
    def test_predict_price_success_regular(self, app, db, monkeypatch, test_product):
        engine = _patch_engine(monkeypatch, '_neural_engine')
        engine.predict_optimal_price.return_value = {'price': 88.0}
        result = AIService.predict_price_with_neural(test_product.id, None, quantity=3)
        kwargs = engine.predict_optimal_price.call_args.kwargs
        assert kwargs['cost_price'] == 50.0
        assert kwargs['quantity'] == 3
        assert kwargs['customer_type'] == 'regular'
        assert result == {'price': 88.0}

    def test_predict_price_with_customer_type(self, app, db, monkeypatch, test_product, test_customer):
        engine = _patch_engine(monkeypatch, '_neural_engine')
        engine.predict_optimal_price.return_value = {'ok': True}
        AIService.predict_price_with_neural(test_product.id, test_customer.id)
        assert engine.predict_optimal_price.call_args.kwargs['customer_type'] == 'regular'

    def test_predict_price_missing_product(self, app, db):
        with app.app_context():
            assert AIService.predict_price_with_neural(99999, None) == {'error': 'Product not found'}

    def test_predict_price_failure_falls_back_to_recommend_price(
            self, app, db, monkeypatch, test_product, test_customer):
        engine = _patch_engine(monkeypatch, '_neural_engine')
        engine.predict_optimal_price.side_effect = RuntimeError('nn down')
        result = AIService.predict_price_with_neural(test_product.id, test_customer.id)
        assert result['base_price'] == 100.0

    def test_forecast_success_and_failure(self, app, monkeypatch):
        engine = _patch_engine(monkeypatch, '_neural_engine')
        engine.forecast_sales.return_value = {'forecast': [1, 2]}
        with app.app_context():
            assert AIService.forecast_sales_neural(5) == {'forecast': [1, 2]}
        engine.forecast_sales.side_effect = RuntimeError('x')
        with app.app_context():
            assert AIService.forecast_sales_neural() == {}

    def test_detect_fraud_success_and_failure(self, monkeypatch):
        engine = _patch_engine(monkeypatch, '_neural_engine')
        engine.detect_fraud.return_value = {'is_fraud': True, 'risk_score': 90}
        assert AIService.detect_fraud_neural({'amount': 5})['is_fraud'] is True
        engine.detect_fraud.side_effect = RuntimeError('x')
        assert AIService.detect_fraud_neural({}) == {'is_fraud': False, 'risk_score': 0}

    @pytest.mark.parametrize('method_name,engine_method', [
        ('classify_customer_neural', 'classify_customer_intelligence'),
        ('optimize_inventory_neural', 'optimize_stock_level'),
        ('predict_maintenance_neural', 'predict_maintenance_needs'),
        ('predict_cash_flow_neural', 'predict_cash_flow'),
    ])
    def test_neural_failures_return_empty_dict(self, app, monkeypatch, method_name, engine_method):
        engine = _patch_engine(monkeypatch, '_neural_engine')
        getattr(engine, engine_method).side_effect = RuntimeError('down')
        with app.app_context():
            assert getattr(AIService, method_name)(1) == {}

    def test_train_all_models_failure(self, app, monkeypatch):
        engine = _patch_engine(monkeypatch, '_neural_engine')
        engine.train_all_models.side_effect = RuntimeError('gpu missing')
        with app.app_context():
            result = AIService.train_all_neural_models()
        assert result['success'] is False
        assert 'gpu missing' in result['error']

    def test_neural_status(self, monkeypatch):
        engine = _patch_engine(monkeypatch, '_neural_engine')
        engine.get_status.return_value = {'trained_models': 11, 'total_models': 11}
        assert AIService.get_neural_status()['trained_models'] == 11
        engine.get_status.side_effect = RuntimeError('x')
        assert AIService.get_neural_status() == {'trained_models': 0, 'total_models': 0}


class TestMasterBrainMethods:
    def test_ask_genius_success_and_failure(self, app):
        brain = Mock()
        brain.ask.return_value = {'answer': '42', 'confidence': 99}
        AIService._master_brain = brain
        try:
            assert AIService.ask_genius('سؤال')['answer'] == '42'
            brain.ask.side_effect = RuntimeError('x')
            result = AIService.ask_genius('سؤال')
            assert result['confidence'] == 0
            assert 'خطأ' in result['answer']
        finally:
            AIService._master_brain = None

    def test_quick_calculate_passthrough_and_failure(self, app):
        brain = Mock()
        brain.quick_calc.return_value = {'result': 50.0, 'success': True}
        AIService._master_brain = brain
        try:
            assert AIService.quick_calculate('vat', amount=1000)['result'] == 50.0
            brain.quick_calc.side_effect = ZeroDivisionError('x')
            result = AIService.quick_calculate('vat', amount=1)
            assert result['success'] is False
        finally:
            AIService._master_brain = None

    def test_explain_anything_failure_string(self, app):
        brain = Mock()
        brain.explain.side_effect = RuntimeError('x')
        AIService._master_brain = brain
        try:
            assert AIService.explain_anything('مفهوم').startswith('عذراً، لم أتمكن من الشرح:')
        finally:
            AIService._master_brain = None

    def test_validate_entry_failure_dict(self, app):
        brain = Mock()
        brain.validate_accounting_entry.side_effect = RuntimeError('x')
        AIService._master_brain = brain
        try:
            result = AIService.validate_entry(5, 5)
            assert result['is_balanced'] is False and 'error' in result
        finally:
            AIService._master_brain = None


class TestTransformersMethods:
    def test_understand_success_and_failure(self, app):
        brain = Mock()
        brain.understand.return_value = {'tokens': ['a']}
        AIService._transformers_brain = brain
        try:
            assert AIService.understand_with_transformers('نص') == {'tokens': ['a']}
            brain.understand.side_effect = RuntimeError('x')
            assert AIService.understand_with_transformers('نص') == {}
        finally:
            AIService._transformers_brain = None

    def test_generate_forwards_max_length(self, app):
        brain = Mock()
        brain.generate_response.return_value = 'جواب'
        AIService._transformers_brain = brain
        try:
            assert AIService.generate_with_transformers('سؤال', max_length=77) == 'جواب'
            brain.generate_response.assert_called_once_with('سؤال', 77)
        finally:
            AIService._transformers_brain = None

    def test_generate_failure_message(self, app):
        brain = Mock()
        brain.generate_response.side_effect = RuntimeError('x')
        AIService._transformers_brain = brain
        try:
            assert AIService.generate_with_transformers('سؤال') == 'عذراً، حدث خطأ'
        finally:
            AIService._transformers_brain = None

    def test_analyze_attention_maps_fields(self, app):
        brain = Mock()
        brain.understand.return_value = {'attention_map': {0: [1]}, 'tokens': ['قيد']}
        AIService._transformers_brain = brain
        try:
            result = AIService.analyze_attention('قيد مدين')
            assert result['attention_map'] == {0: [1]}
            assert result['tokens'] == ['قيد']
            assert result['visualization']
        finally:
            AIService._transformers_brain = None

    def test_analyze_attention_defaults_on_missing_keys(self, app):
        brain = Mock()
        brain.understand.return_value = {}
        AIService._transformers_brain = brain
        try:
            result = AIService.analyze_attention('نص')
            assert result['attention_map'] == {} and result['tokens'] == []
        finally:
            AIService._transformers_brain = None


class TestAdvancedComponents:
    def test_think_deeply(self, app):
        reasoning = Mock()
        reasoning.think.return_value = {'steps': 3}
        AIService._reasoning_engine = reasoning
        try:
            assert AIService.think_deeply('مسألة', {'k': 1}) == {'steps': 3}
            reasoning.think.assert_called_once_with('مسألة', {'k': 1})
            reasoning.think.side_effect = RuntimeError('x')
            assert AIService.think_deeply('مسألة') == {}
        finally:
            AIService._reasoning_engine = None

    def test_delegate_to_expert(self, app):
        coordinator = Mock()
        coordinator.delegate_task.return_value = {'agent': 'sales'}
        AIService._agent_coordinator = coordinator
        try:
            assert AIService.delegate_to_expert('بيع') == {'agent': 'sales'}
            coordinator.delegate_task.side_effect = RuntimeError('x')
            assert AIService.delegate_to_expert('بيع') == {}
        finally:
            AIService._agent_coordinator = None

    def test_generate_sql_code(self, app):
        generator = Mock()
        generator.generate_sql_query.return_value = 'SELECT 1'
        AIService._code_generator = generator
        try:
            result = AIService.generate_code('sql', 'report', {'intent': 'select', 'table': 'sales'})
            assert result == {'code': 'SELECT 1', 'type': 'sql', 'purpose': 'report'}
            generator.generate_sql_query.assert_called_once_with('select', 'sales', None)
        finally:
            AIService._code_generator = None

    def test_generate_python_code(self, app):
        generator = Mock()
        generator.generate_python_function.return_value = 'def f(): pass'
        AIService._code_generator = generator
        try:
            result = AIService.generate_code('python', 'calc', {'name': 'f', 'params': ['x']})
            assert result['code'] == 'def f(): pass'
            generator.generate_python_function.assert_called_once_with('f', 'calc', ['x'])
        finally:
            AIService._code_generator = None

    def test_generate_unsupported_type(self, app):
        AIService._code_generator = Mock()
        try:
            result = AIService.generate_code('cobol', 'legacy', {})
            assert result['code'] == '# Unsupported code type'
        finally:
            AIService._code_generator = None

    def test_generate_code_missing_params_fails_soft(self, app):
        AIService._code_generator = Mock()
        try:
            assert AIService.generate_code('sql', 'r', None) == {}
        finally:
            AIService._code_generator = None

    def test_remember_conversation(self, app):
        memory = Mock()
        AIService._memory_system = memory
        try:
            assert AIService.remember_conversation(1, 'm', 'r') == {'status': 'remembered'}
            memory.remember_conversation.assert_called_once_with(1, 'm', 'r')
            memory.remember_conversation.side_effect = RuntimeError('x')
            assert AIService.remember_conversation(1, 'm', 'r') == {}
        finally:
            AIService._memory_system = None

    def test_recall_conversations(self, app):
        memory = Mock()
        memory.recall_conversations.return_value = [{'q': 'hi'}]
        AIService._memory_system = memory
        try:
            assert AIService.recall_conversations(7, limit=3) == [{'q': 'hi'}]
            memory.recall_conversations.assert_called_once_with(7, 3)
            memory.recall_conversations.side_effect = RuntimeError('x')
            assert AIService.recall_conversations(7) == []
        finally:
            AIService._memory_system = None

    def test_chat_failure_safe_response(self, app):
        manager = Mock()
        manager.process_message.side_effect = RuntimeError('x')
        AIService._conversation_manager = manager
        try:
            assert AIService.chat(1, 'مرحبا') == {'response': 'عذراً، حدث خطأ'}
        finally:
            AIService._conversation_manager = None

    def test_self_reflect(self, app):
        reflection = Mock()
        reflection.reflect_on_performance.return_value = {'score': 9}
        AIService._reflection_engine = reflection
        try:
            assert AIService.self_reflect() == {'score': 9}
            reflection.reflect_on_performance.side_effect = RuntimeError('x')
            assert AIService.self_reflect() == {}
        finally:
            AIService._reflection_engine = None

    def test_read_invoice_image(self, app):
        vision = Mock()
        vision.read_invoice_image.return_value = {'total': 100}
        AIService._vision_processor = vision
        try:
            assert AIService.read_invoice_image('/tmp/inv.png') == {'total': 100}
            vision.read_invoice_image.side_effect = OSError('missing')
            result = AIService.read_invoice_image('/tmp/x.png')
            assert 'missing' in result['error']
        finally:
            AIService._vision_processor = None


class TestAnalyticsIntegrationWrappers:
    def test_analyze_sales_with_predictions_success(self, monkeypatch):
        sales_stub = type('S', (), {
            'get_historical_trends': lambda self, days: {'days': days},
            'predict_next_period': lambda self, d: ['p1'],
        })
        analyzer_stub = type('D', (), {
            'analyze_sales_patterns': lambda self, hist: 'insight',
        })
        monkeypatch.setattr(ai_mod, 'SalesAnalytics', sales_stub)
        monkeypatch.setattr(ai_mod, 'DataAnalyzer', analyzer_stub)
        result = AIService.analyze_sales_with_predictions(days_ahead=13)
        assert result == {'historical': {'days': 90}, 'predictions': ['p1'], 'insights': 'insight'}

    def test_analyze_sales_with_predictions_failure(self, monkeypatch):
        monkeypatch.setattr(ai_mod, 'SalesAnalytics', None)
        assert AIService.analyze_sales_with_predictions() == {}

    def test_optimize_inventory_with_ai_success_and_failure(self, monkeypatch):
        inv_stub = type('I', (), {
            'analyze_stock_levels': lambda self: {'levels': []},
            'calculate_reorder_points': lambda self: ['reorder'],
            'detect_slow_moving_items': lambda self: [],
        })
        monkeypatch.setattr(ai_mod, 'InventoryAnalytics', inv_stub)
        result = AIService.optimize_inventory_with_ai()
        assert result == {'analysis': {'levels': []}, 'recommendations': ['reorder'], 'slow_moving': []}
        monkeypatch.setattr(ai_mod, 'InventoryAnalytics', None)
        assert AIService.optimize_inventory_with_ai() == {}

    def test_analyze_profitability_success_and_failure(self, monkeypatch):
        profit_stub = type('P', (), {
            'analyze_profit_margins': lambda self: {'margin': 10},
            'profitability_by_product': lambda self: ['prod'],
            'profitability_by_customer': lambda self: ['cust'],
        })
        monkeypatch.setattr(ai_mod, 'ProfitAnalytics', profit_stub)
        result = AIService.analyze_profitability()
        assert result['by_product'] == ['prod']
        monkeypatch.setattr(ai_mod, 'ProfitAnalytics', None)
        assert AIService.analyze_profitability() == {}


class TestKnowledgeWrappers:
    def test_vat_queries_english_and_arabic(self, monkeypatch):
        monkeypatch.setattr(ai_mod, 'tax_system', SimpleNamespace(get_vat_info=lambda: {'rate': 5}))
        assert AIService.get_tax_and_customs_info('explain VAT') == {'rate': 5}
        assert AIService.get_tax_and_customs_info('اشرح الضريبة') == {'rate': 5}

    def test_customs_queries(self, monkeypatch):
        monkeypatch.setattr(ai_mod, 'customs', SimpleNamespace(get_customs_procedures=lambda: {'steps': 4}))
        assert AIService.get_tax_and_customs_info('customs clearance') == {'steps': 4}
        assert AIService.get_tax_and_customs_info('عن الجمارك') == {'steps': 4}

    def test_comprehensive_guide_fallback_and_exception(self, monkeypatch):
        monkeypatch.setattr(ai_mod, 'tax_customs_knowledge',
                            SimpleNamespace(get_comprehensive_guide=lambda: {'guide': True}))
        assert AIService.get_tax_and_customs_info('anything else') == {'guide': True}
        monkeypatch.setattr(ai_mod, 'tax_system', None)
        assert AIService.get_tax_and_customs_info('vat now') == {}

    def test_parts_information(self, monkeypatch):
        monkeypatch.setattr(ai_mod, 'parts_knowledge', SimpleNamespace(search_part=lambda q: {'part': q}))
        assert AIService.get_parts_information('filter') == {'part': 'filter'}
        monkeypatch.setattr(ai_mod, 'parts_knowledge', None)
        assert AIService.get_parts_information('filter') == {}

    def test_market_insights_report(self, monkeypatch):
        monkeypatch.setattr(ai_mod, 'market_insights', SimpleNamespace(generate_market_report=lambda: {'m': 1}))
        assert AIService.get_market_insights_report() == {'m': 1}
        monkeypatch.setattr(ai_mod, 'market_insights', None)
        assert AIService.get_market_insights_report() == {}

    def test_customer_service_response(self, monkeypatch):
        monkeypatch.setattr(ai_mod, 'customer_service', SimpleNamespace(handle_customer_query=lambda q: 'جواب'))
        assert AIService.get_customer_service_response('شكوى') == 'جواب'
        monkeypatch.setattr(ai_mod, 'customer_service', None)
        assert 'خطأ' in AIService.get_customer_service_response('شكوى')

    def test_system_guide_combines_sources(self, monkeypatch):
        monkeypatch.setattr(ai_mod, 'system_guide', SimpleNamespace(get_guide_for_topic=lambda t: {'sys': t}))
        monkeypatch.setattr(ai_mod, 'user_guide', SimpleNamespace(get_user_guide=lambda t: {'usr': t}))
        assert AIService.get_system_guide('invoices') == {'system_guide': {'sys': 'invoices'},
                                                          'user_guide': {'usr': 'invoices'}}
        monkeypatch.setattr(ai_mod, 'system_guide', None)
        assert AIService.get_system_guide('x') == {}

    def test_document_generator(self, monkeypatch):
        doc_stub = type('Doc', (), {'generate': lambda self, t, d: {'doc': t}})
        monkeypatch.setattr(ai_mod, 'DocumentGenerator', doc_stub)
        assert AIService.generate_document_with_ai('invoice', {}) == {'doc': 'invoice'}
        monkeypatch.setattr(ai_mod, 'DocumentGenerator', None)
        assert AIService.generate_document_with_ai('invoice', {}) is None

    def test_company_information(self, monkeypatch):
        monkeypatch.setattr(ai_mod, 'company_info', SimpleNamespace(get_company_details=lambda: {'name': 'azad'}))
        assert AIService.get_company_information() == {'name': 'azad'}
        monkeypatch.setattr(ai_mod, 'company_info', None)
        assert AIService.get_company_information() == {}

    def test_system_knowledge(self, monkeypatch):
        monkeypatch.setattr(ai_mod, 'system_knowledge', SimpleNamespace(search_knowledge=lambda q: [q]))
        assert AIService.get_system_knowledge('gl') == ['gl']
        monkeypatch.setattr(ai_mod, 'system_knowledge', None)
        assert AIService.get_system_knowledge('gl') == {}

    def test_advanced_laws(self, monkeypatch):
        laws_stub = type('Laws', (), {'get_law_information': lambda self, t: {'law': t}})
        monkeypatch.setattr(ai_mod, 'advanced_laws', SimpleNamespace(AdvancedLaws=laws_stub))
        assert AIService.get_advanced_law_info('trade') == {'law': 'trade'}
        monkeypatch.setattr(ai_mod, 'advanced_laws', None)
        assert AIService.get_advanced_law_info('trade') == {}

    def test_expand_knowledge_base(self, monkeypatch):
        expander_stub = type('Exp', (), {'expand_knowledge': lambda self, t: {'expanded': t}})
        monkeypatch.setattr(ai_mod, 'KnowledgeExpander', expander_stub)
        assert AIService.expand_knowledge_base('topic') == {'expanded': 'topic'}
        monkeypatch.setattr(ai_mod, 'KnowledgeExpander', None)
        assert AIService.expand_knowledge_base('topic') == {}

    def test_perform_self_improvement(self, monkeypatch):
        si_stub = type('SI', (), {'analyze_and_improve': lambda self: ['fix']})
        monkeypatch.setattr(ai_mod, 'AzadSelfImprovement', si_stub)
        assert AIService.perform_self_improvement() == ['fix']
        monkeypatch.setattr(ai_mod, 'AzadSelfImprovement', None)
        assert AIService.perform_self_improvement() == {}

    def test_integrate_with_system(self, monkeypatch):
        integ_stub = type('Integ', (), {'execute_integration': lambda self, op, d: {'op': op}})
        monkeypatch.setattr(ai_mod, 'SystemIntegrator', integ_stub)
        assert AIService.integrate_with_system('sync', {}) == {'op': 'sync'}
        monkeypatch.setattr(ai_mod, 'SystemIntegrator', None)
        assert AIService.integrate_with_system('sync', {}) == {}

    def test_global_knowledge(self, monkeypatch):
        gk_stub = type('GK', (), {'fetch_knowledge': lambda self, q: {'q': q}})
        monkeypatch.setattr(ai_mod, 'GlobalKnowledgeConnector', gk_stub)
        assert AIService.get_global_knowledge('news') == {'q': 'news'}
        monkeypatch.setattr(ai_mod, 'GlobalKnowledgeConnector', None)
        assert AIService.get_global_knowledge('news') == {}

    def test_beginners_help(self, monkeypatch):
        bg_stub = type('BG', (), {'get_help': lambda self, t: f'help:{t}'})
        monkeypatch.setattr(ai_mod, 'BeginnersGuide', bg_stub)
        assert AIService.get_beginners_help('sales') == 'help:sales'
        monkeypatch.setattr(ai_mod, 'BeginnersGuide', None)
        assert AIService.get_beginners_help('sales') == {}

    def test_security_compliance(self, monkeypatch):
        security = Mock()
        security.check_compliance.return_value = (False, ['w1'])
        monkeypatch.setattr(AIService, 'get_security_rules', staticmethod(lambda: security))
        assert AIService.check_security_compliance('delete') == {'compliant': False, 'warnings': ['w1']}
        broken = Mock()
        broken.check_compliance.side_effect = RuntimeError('x')
        monkeypatch.setattr(AIService, 'get_security_rules', staticmethod(lambda: broken))
        assert AIService.check_security_compliance('delete') == {'compliant': True, 'warnings': []}


class TestEcuAndExternalLearning:
    def test_diagnose_obd_code(self, monkeypatch):
        ecu = Mock()
        ecu.diagnose_code.return_value = {'found': True, 'desc': 'catalyst'}
        monkeypatch.setattr(ai_mod, 'get_automotive_ecu_knowledge', lambda: ecu)
        assert AIService.diagnose_obd_code('P0420')['found'] is True

    def test_diagnose_obd_code_failure(self, monkeypatch):
        def boom():
            raise RuntimeError('ecu offline')

        monkeypatch.setattr(ai_mod, 'get_automotive_ecu_knowledge', boom)
        result = AIService.diagnose_obd_code('P0420')
        assert result['found'] is False and 'ecu offline' in result['error']

    def test_sensor_info(self, monkeypatch):
        ecu = Mock()
        ecu.get_sensor_info.return_value = {'sensor': 'MAF'}
        monkeypatch.setattr(ai_mod, 'get_automotive_ecu_knowledge', lambda: ecu)
        assert AIService.get_sensor_info('MAF') == {'sensor': 'MAF'}
        monkeypatch.setattr(ai_mod, 'get_automotive_ecu_knowledge', lambda: (_ for _ in ()).throw(ValueError('bad')))
        assert 'bad' in AIService.get_sensor_info('MAF')['error']

    def test_ecu_knowledge(self, monkeypatch):
        ecu = Mock()
        ecu.get_ecu_info.return_value = {'ecu': 'engine'}
        monkeypatch.setattr(ai_mod, 'get_automotive_ecu_knowledge', lambda: ecu)
        assert AIService.get_ecu_knowledge('engine_ecu') == {'ecu': 'engine'}
        monkeypatch.setattr(ai_mod, 'get_automotive_ecu_knowledge', None)
        assert AIService.get_ecu_knowledge('engine_ecu') == {}

    def test_get_learning_sources(self, monkeypatch):
        learning = Mock()
        learning.get_knowledge_sources_list.return_value = ['wikipedia', 'github']
        learning.get_statistics.return_value = {'learned': 5}
        monkeypatch.setattr(ai_mod, 'get_external_learning', lambda: learning)
        result = AIService.get_learning_sources()
        assert result['total_sources'] == 2
        assert result['statistics'] == {'learned': 5}

    def test_get_learning_sources_failure(self, monkeypatch):
        monkeypatch.setattr(ai_mod, 'get_external_learning', None)
        result = AIService.get_learning_sources()
        assert result['sources'] == [] and 'error' in result

    def test_learn_from_external(self, monkeypatch):
        learning = Mock()
        learning.learn_from_source.return_value = {'success': True}
        monkeypatch.setattr(ai_mod, 'get_external_learning', lambda: learning)
        assert AIService.learn_from_external('wikipedia', 'uae', 'content') == {'success': True}
        learning.learn_from_source.assert_called_once_with('wikipedia', 'uae', 'content')
        monkeypatch.setattr(ai_mod, 'get_external_learning', None)
        result = AIService.learn_from_external('wikipedia', 'uae', 'content')
        assert result['success'] is False


class TestContextualResponse:
    def test_happy_path_uses_personality_and_records_learning(self, monkeypatch):
        engine = Mock()
        engine.build_context.return_value = 'CTX'
        dialect = Mock()
        dialect.detect_dialect.return_value = 'gulf'
        personality = Mock()
        personality.generate_response.return_value = 'RESPONSE'
        learning = Mock()
        monkeypatch.setattr(AIService, '_context_engine', engine)
        monkeypatch.setattr(AIService, '_dialect_manager', dialect)
        monkeypatch.setattr(AIService, '_personality', personality)
        monkeypatch.setattr(AIService, '_learning_system', learning)
        result = AIService.get_contextual_response('مرحبا', user=None, conversation_history=[{'m': 'x'}])
        assert result == 'RESPONSE'
        engine.build_context.assert_called_once_with('مرحبا', None, [{'m': 'x'}])
        learning.learn_from_interaction.assert_called_once_with(
            question='مرحبا', response='RESPONSE', user_feedback=None,
            context={'dialect': 'gulf', 'context': 'CTX'})

    def test_failure_returns_error_response(self, monkeypatch):
        engine = Mock()
        engine.build_context.side_effect = RuntimeError('ctx failed')
        monkeypatch.setattr(AIService, '_context_engine', engine)
        result = AIService.get_contextual_response('سؤال')
        assert isinstance(result, str) and result


class TestBackwardCompatLocalResponse:
    def test_delegates_to_azad_responses(self, monkeypatch):
        import ai_knowledge.azad_responses as azad_responses_mod
        monkeypatch.setattr(azad_responses_mod.AzadResponses, 'smart_response',
                            staticmethod(lambda message, context=None: 'SMART'))
        assert AIService._local_response('مرحبا', {'x': 1}) == 'SMART'
