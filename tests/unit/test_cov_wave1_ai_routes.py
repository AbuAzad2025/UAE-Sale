"""Wave-1 coverage tests for routes/ai.py — real endpoint hits only.

Every test logs in through the real auth stack (or stays anonymous on
purpose), calls a real /ai/* endpoint, and asserts status codes plus
JSON shapes / DB effects. No external network is used: chat runs with
``ai_mode='local'`` and all other exercised paths are local/DB-backed.
"""
import io
from urllib.parse import quote

import pytest


class TestAiPricingStock:
    def test_recommend_price_missing_params_400(self, client, login_owner):
        resp = client.post('/ai/recommend-price', json={})
        assert resp.status_code == 400
        assert 'error' in resp.get_json()

    def test_recommend_price_success(self, client, login_owner, test_product,
                                     test_customer):
        resp = client.post('/ai/recommend-price', json={
            'product_id': test_product.id, 'customer_id': test_customer.id})
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'recommended_price' in data
        assert 'base_price' in data

    def test_recommend_price_unknown_product_404(self, client, login_owner,
                                                 test_customer):
        resp = client.post('/ai/recommend-price', json={
            'product_id': 99999, 'customer_id': test_customer.id})
        assert resp.status_code == 404

    def test_check_stock_missing_product_400(self, client, login_owner):
        resp = client.post('/ai/check-stock', json={})
        assert resp.status_code == 400
        assert 'error' in resp.get_json()

    def test_check_stock_sufficient(self, client, login_owner, test_product):
        resp = client.post('/ai/check-stock', json={
            'product_id': test_product.id, 'quantity': 1})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['type'] == 'success'
        assert 'message' in data

    def test_check_stock_insufficient_alert(self, client, login_owner,
                                            test_product):
        resp = client.post('/ai/check-stock', json={
            'product_id': test_product.id, 'quantity': 10 ** 9})
        assert resp.status_code == 200
        assert resp.get_json()['type'] == 'error'

    def test_smart_price_missing_400(self, client, login_owner):
        resp = client.post('/ai/smart-price', json={})
        assert resp.status_code == 400
        assert 'error' in resp.get_json()

    def test_smart_price_known_ids_server_error(self, client, login_owner,
                                                     test_product,
                                                     test_customer):
        # BUG (routes/ai.py:3395): AIService.smart_pricing_engine does not
        # exist -> AttributeError propagates (TESTING=True). Documents bug.
        with pytest.raises(AttributeError, match='smart_pricing_engine'):
            client.post('/ai/smart-price', json={
                'product_id': test_product.id,
                'customer_id': test_customer.id, 'quantity': 1})


class TestAiCustomerProduct:
    def test_analyze_customer_success(self, client, login_owner,
                                      test_customer):
        resp = client.get(f'/ai/analyze-customer/{test_customer.id}')
        assert resp.status_code == 200
        assert resp.is_json

    def test_analyze_customer_missing_404(self, client, login_owner):
        resp = client.get('/ai/analyze-customer/99999')
        assert resp.status_code == 404

    def test_search_market_price_success(self, client, login_owner,
                                         test_product):
        resp = client.get(f'/ai/search-market-price/{test_product.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['product'] == test_product.name

    def test_search_market_price_missing_404(self, client, login_owner):
        assert client.get('/ai/search-market-price/99999').status_code == 404

    def test_find_compatible_success(self, client, login_owner, test_product):
        resp = client.get(f'/ai/find-compatible/{test_product.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'compatible_vehicles' in data

    def test_find_compatible_missing_404(self, client, login_owner):
        assert client.get('/ai/find-compatible/99999').status_code == 404

    def test_exchange_rate(self, client, login_owner):
        resp = client.get('/ai/exchange-rate/AED')
        assert resp.status_code == 200
        assert resp.is_json

    def test_exchange_rate_anonymous_302(self, client):
        resp = client.get('/ai/exchange-rate/AED', follow_redirects=False)
        assert resp.status_code == 302


class TestAiChat:
    def test_chat_empty_message_400(self, client, login_owner):
        resp = client.post('/ai/chat', json={'message': '   '})
        assert resp.status_code == 400
        assert 'error' in resp.get_json()

    def test_chat_anonymous_302(self, client):
        resp = client.post('/ai/chat', json={'message': 'hello'},
                           follow_redirects=False)
        assert resp.status_code == 302

    def test_chat_local_mode_200(self, client, login_owner):
        resp = client.post('/ai/chat', json={
            'message': 'hello', 'ai_mode': 'local'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'response' in data
        assert 'ai_enabled' in data


class TestAiAnalytics:
    def test_predict_sales(self, client, login_owner):
        assert client.get('/ai/predict-sales').status_code == 200

    def test_analyze_margins(self, client, login_owner):
        assert client.get('/ai/analyze-margins').status_code == 200

    def test_detect_patterns(self, client, login_owner):
        assert client.get('/ai/detect-patterns').status_code == 200

    def test_inventory_health(self, client, login_owner):
        assert client.get('/ai/inventory-health').status_code == 200

    def test_business_insights(self, client, login_owner):
        resp = client.get('/ai/business-insights')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert isinstance(data['insights'], list)

    def test_contextual_help(self, client, login_owner):
        assert client.get('/ai/contextual-help/sales').status_code == 200

    def test_deep_analysis_owner_server_error(self, client, login_owner):
        # BUG (routes/ai.py:3369): AIService.deep_business_analysis does
        # not exist -> AttributeError propagates. Documents current behavior.
        with pytest.raises(AttributeError, match='deep_business_analysis'):
            client.get('/ai/deep-analysis')

    def test_deep_analysis_seller_403(self, client, login_seller):
        assert client.get('/ai/deep-analysis').status_code == 403

    def test_cash_flow_prediction_server_error(self, client, login_owner):
        # BUG (routes/ai.py:3379): AIService.predict_cash_flow does not
        # exist (only predict_cash_flow_neural) -> AttributeError.
        with pytest.raises(AttributeError, match='predict_cash_flow'):
            client.get('/ai/cash-flow-prediction')

    def test_churn_prediction_server_error(self, client, login_owner):
        # BUG (routes/ai.py:3408): AIService.predict_customer_churn does
        # not exist -> AttributeError propagates.
        with pytest.raises(AttributeError, match='predict_customer_churn'):
            client.get('/ai/churn-prediction')

    def test_optimize_inventory(self, client, login_owner):
        assert client.get('/ai/optimize-inventory').status_code == 200

    def test_analyze_sales(self, client, login_owner):
        assert client.get('/ai/data/analyze-sales').status_code == 200

    def test_analyze_products_owner_200(self, client, login_owner):
        # Owner bypasses per-permission checks (User.has_permission True
        # for is_owner), so the 'view_products' gate does not apply.
        assert client.get('/ai/data/analyze-products').status_code == 200

    def test_analyze_products_seller_403(self, client, login_seller):
        assert client.get('/ai/data/analyze-products').status_code == 403

    def test_financial_ratios(self, client, login_owner):
        assert client.get('/ai/data/financial-ratios').status_code == 200


class TestAiLearning:
    def test_learning_status(self, client, login_owner):
        resp = client.get('/ai/learning/status')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_improvement_status(self, client, login_owner):
        resp = client.get('/ai/improvement/status')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_improvement_progress(self, client, login_owner):
        resp = client.get('/ai/improvement/progress')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_set_goal_missing_fields_400(self, client, login_owner):
        resp = client.post('/ai/improvement/set-goal', json={})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_set_goal_seller_403(self, client, login_seller):
        resp = client.post('/ai/improvement/set-goal',
                           json={'area': 'x', 'target_score': 9})
        assert resp.status_code == 403

    def test_evolve_seller_403(self, client, login_seller):
        assert client.post('/ai/learning/evolve').status_code == 403

    def test_auto_improve_seller_403(self, client, login_seller):
        assert client.post('/ai/improvement/auto-improve').status_code == 403

    def test_expertise_update_seller_403(self, client, login_seller):
        assert client.get('/ai/global/expertise-update').status_code == 403

    def test_global_insights(self, client, login_owner):
        resp = client.get('/ai/global/insights')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_performance_analysis(self, client, login_owner):
        resp = client.get('/ai/performance/analysis')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True


class TestAiSystem:
    def test_system_summary(self, client, login_owner):
        resp = client.get('/ai/system/summary')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_system_search(self, client, login_owner):
        assert client.get('/ai/system/search/test').status_code == 200

    def test_customer_balance(self, client, login_owner, test_customer):
        resp = client.get(
            f"/ai/system/customer-balance/{quote(test_customer.name)}")
        assert resp.status_code == 200
        assert resp.is_json

    def test_customer_debt(self, client, login_owner, test_customer):
        resp = client.get(
            f'/ai/system/customer-debt/{test_customer.id}')
        assert resp.status_code == 200
        assert resp.is_json

    def test_product_stock(self, client, login_owner, test_product):
        resp = client.get(
            f"/ai/system/product-stock/{quote(test_product.name)}")
        assert resp.status_code == 200
        assert resp.is_json

    def test_add_customer_missing_fields(self, client, login_owner):
        resp = client.post('/ai/system/add-customer', json={})
        assert resp.status_code == 200
        assert resp.get_json()['success'] is False

    def test_add_customer_success_db_effect(self, client, login_owner, db):
        from models import Customer
        before = Customer.query.count()
        resp = client.post('/ai/system/add-customer', json={
            'name': 'AI Customer', 'customer_type': 'regular',
            'phone': '+971500000001'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert Customer.query.count() == before + 1
        assert Customer.query.filter_by(name='AI Customer').first() is not None


class TestAiKnowledge:
    def test_search_missing_q_400(self, client, login_owner):
        resp = client.get('/ai/knowledge/search')
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_search_with_q(self, client, login_owner):
        resp = client.get('/ai/knowledge/search', query_string={'q': 'oil'})
        assert resp.status_code == 200
        assert resp.is_json

    def test_summary(self, client, login_owner):
        assert client.get('/ai/knowledge/summary').status_code == 200

    def test_add_website_missing_url_400(self, client, login_owner):
        resp = client.post('/ai/knowledge/add-website', json={})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_add_website_seller_403(self, client, login_seller):
        resp = client.post('/ai/knowledge/add-website',
                           json={'url': 'https://example.com'})
        assert resp.status_code == 403

    def test_add_document_missing_400(self, client, login_owner):
        resp = client.post('/ai/knowledge/add-document', json={'title': 't'})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_add_document_seller_403(self, client, login_seller):
        resp = client.post('/ai/knowledge/add-document',
                           json={'title': 't', 'content': 'c'})
        assert resp.status_code == 403


class TestAiBrains:
    def test_neural_status(self, client, login_owner):
        resp = client.get('/ai/neural-status')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_automotive_ecu(self, client, login_owner):
        resp = client.get('/ai/automotive-ecu/P0300')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'diagnosis' in data

    def test_automotive_sensor(self, client, login_owner):
        resp = client.get('/ai/automotive-sensor/oxygen')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_external_sources(self, client, login_owner):
        resp = client.get('/ai/external-sources')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'sources' in data

    def test_ask_genius_missing_400(self, client, login_owner):
        resp = client.post('/ai/ask-genius', json={})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_ask_genius_valid(self, client, login_owner):
        resp = client.post('/ai/ask-genius',
                           json={'question': 'What is VAT?'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'result' in data

    def test_quick_calc_missing_400(self, client, login_owner):
        resp = client.post('/ai/quick-calc', json={})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_quick_calc_vat(self, client, login_owner):
        resp = client.post('/ai/quick-calc',
                           json={'formula': 'vat', 'params': {'amount': 1000}})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'result' in data

    def test_transformers_missing_400(self, client, login_owner):
        resp = client.post('/ai/transformers-understand', json={})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_transformers_valid(self, client, login_owner):
        resp = client.post('/ai/transformers-understand',
                           json={'text': 'What is VAT?'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'understanding' in data


class TestAiPages:
    def test_assistant_owner_200(self, client, login_owner):
        assert client.get('/ai/assistant').status_code == 200

    def test_assistant_seller_302(self, client, login_seller):
        resp = client.get('/ai/assistant', follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/dashboard')

    def test_assistant_anonymous_302(self, client):
        assert client.get('/ai/assistant',
                          follow_redirects=False).status_code == 302

    def test_config_get_owner_200(self, client, login_owner):
        assert client.get('/ai/config').status_code == 200

    def test_config_post_missing_key(self, client, login_owner):
        resp = client.post('/ai/config', data={'provider': 'groq'})
        assert resp.status_code == 200
        assert resp.get_json()['success'] is False

    def test_upload_no_file_400(self, client, login_owner):
        resp = client.post('/ai/upload-excel', data={})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_upload_bad_extension_400(self, client, login_owner):
        resp = client.post('/ai/upload-excel', data={
            'file': (io.BytesIO(b'not excel'), 'notes.txt')},
            content_type='multipart/form-data')
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False
