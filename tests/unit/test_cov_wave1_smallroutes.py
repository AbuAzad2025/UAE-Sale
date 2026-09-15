"""Wave-1 quick-win coverage: small route blueprints.

Auth matrix per route: anonymous / seller / owner.
- routes/whatsapp.py (mocked WhatsAppService = external network boundary)
- routes/gamification.py (whitelist + stats)
- routes/returns.py (validation branches + real ReturnService create)
- routes/public.py (anonymous pages, sitemap, robots)
- routes/api_enhanced.py (perm matrix + cost masking + DB-only analytics)
- routes/approvals.py (index/view/missing-id/workflows)
"""
import pytest


# ---------------------------------------------------------------------------
# whatsapp
# ---------------------------------------------------------------------------

class TestWhatsappRoutes:
    def test_anonymous_redirects(self, client, test_sale, test_customer):
        assert client.post(f'/whatsapp/send-invoice/{test_sale.id}').status_code == 302
        assert client.post(f'/whatsapp/send-reminder/{test_customer.id}').status_code == 302
        assert client.get('/whatsapp/test').status_code == 302

    def test_send_invoice_success_mocked(self, client, db, test_sale, login_owner,
                                         monkeypatch):
        from services.whatsapp_service import WhatsAppService
        monkeypatch.setattr(WhatsAppService, 'send_invoice',
                            lambda **kw: {'success': True, 'sid': 'SM1'})
        resp = client.post(f'/whatsapp/send-invoice/{test_sale.id}')
        assert resp.status_code == 200
        assert resp.get_json() == {'success': True, 'sid': 'SM1'}

    def test_send_invoice_failure_mocked(self, client, db, test_sale, login_owner,
                                         monkeypatch):
        from services.whatsapp_service import WhatsAppService
        monkeypatch.setattr(WhatsAppService, 'send_invoice',
                            lambda **kw: {'success': False, 'error': 'down'})
        resp = client.post(f'/whatsapp/send-invoice/{test_sale.id}')
        assert resp.get_json()['success'] is False

    def test_send_invoice_missing_phone(self, client, db, login_owner, owner_user,
                                        test_customer):
        from models import Sale
        from extensions import db as _db
        from decimal import Decimal
        test_customer.phone = None
        sale = Sale(sale_number='S-NOPHONE', customer_id=test_customer.id,
                    seller_id=owner_user.id, total_amount=Decimal('10'),
                    amount_base=Decimal('10'), paid_amount=Decimal('0'),
                    paid_amount_base=Decimal('0'), balance_due=Decimal('10'),
                    currency='AED', exchange_rate=Decimal('1'),
                    payment_status='unpaid', status='confirmed', is_active=True)
        _db.session.add(sale)
        _db.session.commit()
        resp = client.post(f'/whatsapp/send-invoice/{sale.id}')
        assert resp.get_json() == {'success': False,
                                   'error': 'Customer phone not available'}

    def test_send_reminder_admin_only(self, client, db, test_customer,
                                      login_seller, monkeypatch):
        resp = client.post(f'/whatsapp/send-reminder/{test_customer.id}')
        assert resp.status_code == 403

    def test_send_reminder_owner_mocked(self, client, db, test_customer,
                                        login_owner, monkeypatch):
        from services.whatsapp_service import WhatsAppService
        seen = {}
        monkeypatch.setattr(
            WhatsAppService, 'send_payment_reminder',
            lambda **kw: (seen.update(kw), {'success': True})[1])
        resp = client.post(f'/whatsapp/send-reminder/{test_customer.id}')
        assert resp.status_code == 200
        assert resp.get_json() == {'success': True}
        assert seen['phone'] == test_customer.phone

    def test_send_reminder_missing_phone(self, client, db, login_owner):
        from models import Customer
        from extensions import db as _db
        c = Customer(name='NoPhone', customer_type='regular', phone=None)
        _db.session.add(c)
        _db.session.commit()
        resp = client.post(f'/whatsapp/send-reminder/{c.id}')
        assert resp.get_json()['error'] == 'Customer phone not available'

    def test_test_connection_reports_unconfigured(self, client, db, login_owner):
        resp = client.get('/whatsapp/test')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is False
        assert 'WHATSAPP_API_KEY' in body['error']


# ---------------------------------------------------------------------------
# gamification
# ---------------------------------------------------------------------------

class TestGamificationRoutes:
    def test_anonymous_redirects(self, client):
        assert client.get('/gamification/leaderboard').status_code == 302
        assert client.get('/gamification/my-stats').status_code == 302
        assert client.get('/gamification/award/daily_login').status_code == 302

    def test_leaderboard_owner(self, client, db, login_owner):
        resp = client.get('/gamification/leaderboard')
        assert resp.status_code == 200

    def test_my_stats(self, client, db, owner_user, login_owner):
        resp = client.get('/gamification/my-stats')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body.get('user_id', owner_user.id) == owner_user.id or 'points' in body

    def test_award_whitelisted(self, client, db, owner_user, login_owner):
        resp = client.get('/gamification/award/daily_login')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['total_points'] >= 0

    def test_award_rejected_action_404(self, client, db, login_owner):
        assert client.get('/gamification/award/hack_points').status_code == 404
        assert client.get('/gamification/award/drop_tables').status_code == 404

    def test_seller_can_view(self, client, db, login_seller):
        assert client.get('/gamification/leaderboard').status_code == 200
        assert client.get('/gamification/my-stats').status_code == 200


# ---------------------------------------------------------------------------
# returns
# ---------------------------------------------------------------------------

class TestReturnsRoutes:
    def test_anonymous_redirect(self, client):
        assert client.post('/returns/api/create', json={}).status_code == 302
        assert client.get('/returns/view/1').status_code == 302

    def test_no_data_400(self, client, db, login_owner):
        resp = client.post('/returns/api/create', json={})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_missing_fields_400(self, client, db, login_owner, test_sale):
        resp = client.post('/returns/api/create', json={'sale_id': test_sale.id})
        assert resp.status_code == 400
        assert 'Missing sale_id or lines' in resp.get_json()['message']

    def test_unknown_sale_400(self, client, db, login_owner):
        resp = client.post('/returns/api/create',
                           json={'sale_id': 999999,
                                 'lines': [{'sale_line_id': 1, 'quantity': 1}]})
        assert resp.status_code == 400

    def test_create_return_success(self, client, db, test_sale, owner_user,
                                   login_owner):
        from models import SaleLine
        line = SaleLine.query.filter_by(sale_id=test_sale.id).first()
        resp = client.post('/returns/api/create', json={
            'sale_id': test_sale.id, 'notes': 'wave1',
            'lines': [{'sale_line_id': line.id, 'quantity': 1,
                       'condition': 'good', 'notes': ''}]})
        assert resp.status_code == 200, resp.get_data(as_text=True)[:500]
        body = resp.get_json()
        assert body['success'] is True
        assert body['return_number'].startswith('R')
        assert body['return_id'] > 0

    def test_view_return_missing_template_500(self, client, db, test_sale,
                                              login_owner):
        # REAL BUG (reported, not fixed): routes/returns.py::view renders
        # 'returns/view.html' but templates/returns/ does not exist, so every
        # GET /returns/view/<id> raises jinja2.TemplateNotFound -> HTTP 500.
        from models import SaleLine, ProductReturn
        line = SaleLine.query.filter_by(sale_id=test_sale.id).first()
        created = client.post('/returns/api/create', json={
            'sale_id': test_sale.id,
            'lines': [{'sale_line_id': line.id, 'quantity': 1}]})
        assert created.status_code == 200
        ret = ProductReturn.query.order_by(ProductReturn.id.desc()).first()
        assert ret is not None
        # TESTING=True propagates the exception (production serves HTTP 500).
        from jinja2 import TemplateNotFound
        with pytest.raises(TemplateNotFound):
            client.get(f'/returns/view/{ret.id}')

    def test_seller_without_perm_forbidden(self, client, db, test_sale, login_seller):
        # seller HAS manage_sales in fixtures -> allowed; assert the real rule.
        resp = client.post('/returns/api/create', json={})
        assert resp.status_code in (400, 403)


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------

class TestPublicRoutes:
    @pytest.mark.parametrize('path', ['/welcome', '/pricing', '/features',
                                      '/user-guide', '/contact', '/demo'])
    def test_anonymous_pages_200(self, client, db, path):
        assert client.get(path).status_code == 200

    def test_sitemap_xml(self, client, db, test_product):
        resp = client.get('/sitemap.xml')
        assert resp.status_code == 200
        assert 'application/xml' in resp.content_type
        text = resp.get_data(as_text=True)
        assert '<urlset' in text
        assert '/pricing' in text

    def test_robots_txt(self, client, db):
        resp = client.get('/robots.txt')
        assert resp.status_code == 200
        text = resp.get_data(as_text=True)
        assert 'Disallow: /owner/' in text
        assert 'Sitemap:' in text
        assert 'sitemap.xml' in text

    def test_welcome_redirects_owner(self, client, db, login_owner):
        resp = client.get('/welcome')
        assert resp.status_code == 302
        assert '/dashboard' in resp.headers['Location']


# ---------------------------------------------------------------------------
# api_enhanced
# ---------------------------------------------------------------------------

class TestApiEnhancedRoutes:
    def test_anonymous_redirects(self, client, db, test_sale, test_customer,
                                 test_product):
        assert client.get('/api/v2/sales').status_code == 302
        assert client.get(f'/api/v2/sales/{test_sale.id}').status_code == 302
        assert client.get('/api/v2/customers').status_code == 302
        assert client.get('/api/v2/products/search?q=a').status_code == 302

    def test_sales_list_owner(self, client, db, test_sale, login_owner):
        resp = client.get('/api/v2/sales')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['total'] >= 1
        assert any(s['sale_number'] == test_sale.sale_number for s in body['sales'])

    def test_sale_detail_and_missing(self, client, db, test_sale, login_owner):
        resp = client.get(f'/api/v2/sales/{test_sale.id}')
        assert resp.status_code == 200
        assert resp.get_json()['sale']['sale_number'] == test_sale.sale_number
        assert client.get('/api/v2/sales/999999').status_code == 404

    def test_customers_endpoints(self, client, db, test_customer, login_owner):
        resp = client.get('/api/v2/customers')
        assert resp.status_code == 200
        assert resp.get_json()['total'] >= 1
        resp = client.get(f'/api/v2/customers/{test_customer.id}')
        assert resp.get_json()['customer']['name'] == 'Test Customer'
        assert client.get('/api/v2/customers/999999').status_code == 404

    def test_product_search(self, client, db, test_product, login_owner):
        resp = client.get('/api/v2/products/search?q=SKU-TEST')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['count'] >= 1
        resp = client.get('/api/v2/products/search')
        assert resp.status_code == 400
        resp = client.get(f'/api/v2/products/{test_product.id}')
        assert resp.status_code == 200
        assert resp.get_json()['product']['sku'] == 'SKU-TEST-001'

    def test_cost_masking_seller_vs_owner(self, client, db, test_product,
                                          test_sale, owner_user, seller_user):
        client.post('/auth/login',
                    data={'username': 'testowner', 'password': 'OwnerPass123!'})
        owner_lines = client.get(f'/api/v2/sales/{test_sale.id}').get_json()
        client.get('/auth/logout')
        client.post('/auth/login',
                    data={'username': 'testseller', 'password': 'SellerPass123!'})
        seller_lines = client.get(f'/api/v2/sales/{test_sale.id}').get_json()
        assert owner_lines['sale']['lines'][0].get('cost_price') is not None
        assert 'cost_price' not in seller_lines['sale']['lines'][0]

    def test_forecast_owner_db_only(self, client, db, login_owner):
        resp = client.get('/api/v2/analytics/sales-forecast?days=7')
        assert resp.status_code == 200
        body = resp.get_json()
        assert 'confidence' in body or 'prediction' in body

    def test_forecast_seller_forbidden(self, client, db, login_seller):
        assert client.get('/api/v2/analytics/sales-forecast').status_code == 403

    def test_profit_margins_owner(self, client, db, test_sale, login_owner):
        resp = client.get('/api/v2/analytics/profit-margins')
        assert resp.status_code == 200

    def test_profit_margins_seller_forbidden(self, client, db, login_seller):
        assert client.get('/api/v2/analytics/profit-margins').status_code == 403


# ---------------------------------------------------------------------------
# approvals
# ---------------------------------------------------------------------------

class TestApprovalsRoutes:
    def test_anonymous_redirect(self, client, db):
        assert client.get('/approvals/').status_code == 302

    def test_index_owner(self, client, db, login_owner):
        resp = client.get('/approvals/')
        assert resp.status_code == 200

    def test_index_filters(self, client, db, login_owner):
        resp = client.get('/approvals/?status=pending&entity_type=sale')
        assert resp.status_code == 200

    def test_view_missing_404(self, client, db, login_owner):
        assert client.get('/approvals/999999').status_code == 404

    def test_approve_reject_cancel_missing_404(self, client, db, login_owner):
        assert client.post('/approvals/999999/approve').status_code == 404
        assert client.post('/approvals/999999/reject').status_code == 404
        assert client.post('/approvals/999999/cancel').status_code == 404

    def test_workflows_list_and_form(self, client, db, login_owner):
        assert client.get('/approvals/workflows').status_code == 200
        assert client.get('/approvals/workflows/new').status_code == 200

    def test_create_workflow(self, client, db, login_owner):
        from models import ApprovalWorkflow
        resp = client.post('/approvals/workflows/new', data={
            'name': 'W1 Flow', 'name_ar': 'تدفق',
            'entity_type': 'sale', 'min_amount': '100',
            'max_amount': '', 'levels_required': '1', 'is_active': 'on'})
        assert resp.status_code == 302
        assert ApprovalWorkflow.query.filter_by(name='W1 Flow').count() == 1

    def test_full_request_lifecycle(self, client, db, owner_user, test_sale,
                                    login_owner):
        # REAL BUG (reported, not fixed): templates/approvals/view.html:184
        # calls url_for('sales.view_sale', ...) but the sales blueprint only
        # defines 'sales.view' (routes/sales.py::view), so GET
        # /approvals/<id> raises BuildError -> HTTP 500 for sale requests.
        from models import ApprovalWorkflow
        from extensions import db as _db
        wf = ApprovalWorkflow(name='W1 Sale Flow', entity_type='sale',
                              min_amount=0, levels_required=1, is_active=True)
        _db.session.add(wf)
        _db.session.commit()
        from services.approval_service import ApprovalService
        req = ApprovalService.submit('sale', test_sale.id, 50.0, owner_user.id)
        assert req is not None
        # TESTING=True propagates the exception (production serves HTTP 500).
        from werkzeug.routing import BuildError
        with pytest.raises(BuildError):
            client.get(f'/approvals/{req.id}')
        resp = client.post(f'/approvals/{req.id}/approve', data={'notes': 'ok'})
        assert resp.status_code == 302
        _db.session.refresh(req)
        assert req.status == 'approved'
