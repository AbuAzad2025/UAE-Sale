"""Wave coverage: auth, users, api routes + sanitizer, backup/compression utils,
fixed_asset model math. Deterministic & offline (NOWPayments/Currency/GL mocked)."""
import gzip
import os
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import routes.auth as auth_routes
from extensions import db
from models import Customer, Product, ProductCategory, Role, Sale, User
from models.fixed_asset import DepreciationSchedule, FixedAsset
from models.gl import GLAccount
from models.login_history import LoginHistory
from services.currency_service import CurrencyService
from services.gl_service import GLService
from utils.asset_compression import AssetCompressor
from utils.backup_optimizer import BackupOptimizer
from utils.sanitizer import InputSanitizer, sanitize_form_data

STRONG_PW = 'Str0ng!Pass#9'


@pytest.fixture(autouse=True)
def _fast_password_hashes(monkeypatch):
    """Swap PBKDF2 for reversible stub hashes so this wave's wide matrix stays fast."""
    import models.user as user_module

    def fake_generate(password, method=None):
        return f'fast${password}'
    monkeypatch.setattr(user_module, 'generate_password_hash', fake_generate)
    monkeypatch.setattr(user_module, 'check_password_hash',
                        lambda hashed, password: hashed == f'fast${password}')


def _login(client, username='testowner', password='OwnerPass123!'):
    return client.post('/auth/login', data={'username': username, 'password': password},
                       follow_redirects=False)


def _mk_role(dbf, slug):
    role = Role(name=f'Role-{slug}', name_ar='دور تجريبي', slug=slug)
    dbf.session.add(role)
    dbf.session.commit()
    return role


def _mk_user(dbf, username, role_id=None, password=STRONG_PW, active=True, owner=False):
    role_id = role_id or _mk_role(dbf, f'r-{username}').id
    user = User(username=username, email=f'{username}@example.com', full_name=username,
                full_name_ar=username, phone='+971500000000', role_id=role_id,
                is_owner=owner, is_active=active)
    user.set_password(password)
    dbf.session.add(user)
    dbf.session.commit()
    return user


def _html(resp):
    return resp.get_data(as_text=True)


def _patch_np(monkeypatch, **methods):
    svc = MagicMock()
    for name, ret in methods.items():
        getattr(svc, name).return_value = ret
    monkeypatch.setattr(auth_routes, 'NOWPaymentsService', MagicMock(return_value=svc))
    return svc


class TestAuthLoginLogout:
    def test_login_get_then_authenticated_redirect(self, client, owner_user):
        resp = client.get('/auth/login')
        assert resp.status_code == 200
        assert 'csrf_token' in _html(resp)
        assert _login(client).status_code == 302
        authed = client.get('/auth/login')
        assert authed.status_code == 302
        # Owner is sent to the owner console, not the general dashboard
        assert authed.headers['Location'].endswith('/owner/dashboard')

    def test_login_missing_fields_no_history(self, client, owner_user):
        resp = client.post('/auth/login', data={'username': '', 'password': ''})
        assert resp.status_code == 200
        assert 'مطلوبان' in _html(resp)
        assert LoginHistory.query.count() == 0

    def test_login_success_db_side_effects(self, client, owner_user):
        resp = _login(client)
        assert resp.status_code == 302
        history = LoginHistory.query.filter_by(username='testowner', success=True).all()
        assert len(history) == 1 and history[0].user_id == owner_user.id
        assert history[0].ip_address == '127.0.0.1'
        assert history[0].success is True
        fresh = User.query.filter_by(id=owner_user.id).first()
        assert fresh.last_login is not None and fresh.login_attempts == 0

    def test_login_case_insensitive_and_remember(self, client, owner_user):
        resp = client.post('/auth/login', data={
            'username': 'TESTOWNER', 'password': 'OwnerPass123!', 'remember': 'on'})
        assert resp.status_code == 302

    @pytest.mark.parametrize('next_page', ['/users/', '//evil.com', 'http://evil.com'])
    def test_login_next_redirect_rules(self, client, owner_user, next_page):
        resp = client.post(f'/auth/login?next={next_page}',
                           data={'username': 'testowner', 'password': 'OwnerPass123!'})
        assert resp.status_code == 302
        if next_page == '/users/':
            assert resp.headers['Location'] == '/users/'
        else:
            assert 'evil.com' not in resp.headers['Location']

    def test_login_unknown_username_history_row(self, client, owner_user):
        resp = client.post('/auth/login', data={'username': 'ghost', 'password': 'x123456!Aa'})
        assert resp.status_code == 200
        row = LoginHistory.query.filter_by(username='ghost').first()
        assert row is not None and row.success is False and row.user_id is None
        assert row.failure_reason == 'Invalid credentials'
        assert len(LoginHistory.query.all()) >= 1

    def test_login_wrong_password_attempts_and_lockout(self, client, seller_user):
        from config import Config
        max_attempts = getattr(Config, 'MAX_LOGIN_ATTEMPTS', 5)
        resp = client.post('/auth/login',
                           data={'username': 'testseller', 'password': 'wrong-pass-1!'})
        seller = User.query.filter_by(id=seller_user.id).first()
        assert seller.login_attempts == 1
        assert f'متبقي {max_attempts - 1} محاولات' in _html(resp)

        seller.login_attempts = max_attempts - 1
        db.session.commit()
        locked_now = client.post('/auth/login',
                                 data={'username': 'testseller', 'password': 'nope-Aa1!'})
        assert 'تم قفل حسابك' in _html(locked_now)
        seller = User.query.filter_by(id=seller_user.id).first()
        assert seller.locked_until is not None
        lock_until = seller.locked_until.replace(tzinfo=timezone.utc) \
            if seller.locked_until.tzinfo is None else seller.locked_until
        assert lock_until > datetime.now(timezone.utc)

        blocked = client.post('/auth/login',
                              data={'username': 'testseller', 'password': STRONG_PW})
        assert 'مقفل مؤقتاً' in _html(blocked)
        assert client.get('/users/').status_code == 302
        failures = LoginHistory.query.filter_by(success=False, user_id=seller_user.id).all()
        assert len(failures) >= 2

    def test_login_inactive_account(self, client, seller_user):
        seller = User.query.filter_by(id=seller_user.id).first()
        seller.is_active = False
        db.session.commit()
        resp = client.post('/auth/login',
                           data={'username': 'testseller', 'password': 'SellerPass123!'})
        assert resp.status_code == 200
        assert 'غير نشط' in _html(resp)

    def test_logout_flow(self, client, seller_user):
        assert _login(client, 'testseller', 'SellerPass123!').status_code == 302
        resp = client.get('/auth/logout')
        assert resp.status_code == 302
        # Logout now redirects to the public landing page (the user can
        # then re-login from there). 302 itself is the contract we care about.
        assert resp.status_code == 302
        assert client.get('/auth/logout').status_code == 302


class TestAuthPaymentEndpoints:
    def test_payment_create_no_body(self, client):
        resp = client.post('/auth/payment/create', data='null', content_type='application/json')
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['success'] is False and 'بيانات غير صحيحة' in body['error']

    def test_payment_create_invalid_amount(self, client):
        resp = client.post('/auth/payment/create', json={'amount': 'abc'})
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'Invalid amount'

    @pytest.mark.parametrize('amount', [0.5, -3, 100001])
    def test_payment_create_range_rejected(self, client, amount):
        resp = client.post('/auth/payment/create', json={'amount': amount})
        assert resp.status_code == 400
        assert '$1' in resp.get_json()['error']

    def test_payment_create_success_passes_fields(self, monkeypatch, client):
        svc = _patch_np(monkeypatch, create_payment={'success': True, 'payment_id': 'pid-7'})
        payload = {
            'amount': 25, 'crypto_currency': 'btc', 'customer_email': 'c@x.com',
            'description': 'desc', 'type': 'purchase', 'package': 'pro',
            'customer_name': 'N', 'customer_phone': '+9715', 'donor_name': 'D',
            'donor_email': 'd@x.com', 'donor_message': 'hi'}
        resp = client.post('/auth/payment/create', json=payload)
        assert resp.status_code == 200
        assert resp.get_json()['payment_id'] == 'pid-7'
        kwargs = svc.create_payment.call_args.kwargs
        assert kwargs['transaction_type'] == 'purchase'
        assert kwargs['customer_email'] == 'c@x.com'
        assert float(kwargs['amount']) == 25.0
        assert kwargs['package'] == 'pro'

    def test_payment_create_bad_type_normalized(self, monkeypatch, client):
        svc = _patch_np(monkeypatch, create_payment={'success': True})
        client.post('/auth/payment/create',
                    json={'amount': 10, 'type': 'h4ck', 'crypto_currency': 'litecoincash!!'})
        kwargs = svc.create_payment.call_args.kwargs
        assert kwargs['transaction_type'] == 'donation'
        assert len(kwargs['crypto_currency']) <= 10

    def test_payment_create_service_error_passthrough(self, monkeypatch, client):
        _patch_np(monkeypatch, create_payment={'success': False, 'error': 'gateway down'})
        resp = client.post('/auth/payment/create', json={'amount': 9})
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'gateway down'

    def test_payment_create_service_raises(self, monkeypatch, client):
        svc = _patch_np(monkeypatch)
        svc.create_payment.side_effect = RuntimeError('boom')
        resp = client.post('/auth/payment/create', json={'amount': 9})
        assert resp.status_code == 500
        assert 'خطأ في إنشاء الدفعة' in resp.get_json()['error']

    @pytest.mark.parametrize('result,status', [
        ({'success': True, 'data': {'s': 'finished'}}, 200),
        ({'success': False, 'error': 'nf'}, 400)])
    def test_payment_status_branches(self, monkeypatch, client, result, status):
        _patch_np(monkeypatch, get_payment_status=result)
        resp = client.get('/auth/payment/status/pay-1')
        assert resp.status_code == status
        assert resp.get_json()['success'] is result['success']

    def test_payment_status_exception(self, monkeypatch, client):
        svc = _patch_np(monkeypatch)
        svc.get_payment_status.side_effect = ValueError('dead')
        assert client.get('/auth/payment/status/x').status_code == 500

    @pytest.mark.parametrize('result,status', [
        ({'success': True, 'currencies': ['btc', 'eth']}, 200),
        ({'success': False, 'error': 'e'}, 400)])
    def test_payment_currencies_branches(self, monkeypatch, client, result, status):
        _patch_np(monkeypatch, get_available_currencies=result)
        resp = client.get('/auth/payment/currencies')
        assert resp.status_code == status
        assert resp.get_json()['success'] is result['success']

    def test_payment_currencies_exception(self, monkeypatch, client):
        svc = _patch_np(monkeypatch)
        svc.get_available_currencies.side_effect = OSError('net')
        assert client.get('/auth/payment/currencies').status_code == 500

    def test_callback_missing_signature(self, client):
        resp = client.post('/auth/payment/callback', json={'payment_id': 'p1'})
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'توقيع مفقود'

    def test_callback_bad_signature(self, monkeypatch, client):
        svc = _patch_np(monkeypatch)
        svc.verify_ipn.return_value = False
        resp = client.post('/auth/payment/callback', headers={'x-nowpayments-sig': 'zz'},
                           json={'payment_id': 'p1'})
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'توقيع غير صحيح'
        payload, signature = svc.verify_ipn.call_args.args
        assert payload == {'payment_id': 'p1'} and signature == 'zz'

    def test_callback_processed_ok(self, monkeypatch, client):
        svc = _patch_np(monkeypatch)
        svc.verify_ipn.return_value = True
        svc.process_payment_callback.return_value = True
        resp = client.post('/auth/payment/callback', headers={'x-nowpayments-sig': 'ok'},
                           json={'payment_id': 'p1', 'payment_status': 'finished'})
        assert resp.status_code == 200
        assert resp.get_json() == {'status': 'success'}

    def test_callback_processing_failed(self, monkeypatch, client):
        svc = _patch_np(monkeypatch)
        svc.verify_ipn.return_value = True
        svc.process_payment_callback.return_value = False
        resp = client.post('/auth/payment/callback', headers={'x-nowpayments-sig': 'ok'}, json={})
        assert resp.status_code == 500
        assert 'فشل في معالجة الدفعة' in resp.get_json()['error']

    def test_callback_verify_raises(self, monkeypatch, client):
        svc = _patch_np(monkeypatch)
        svc.verify_ipn.side_effect = TypeError('bad json')
        resp = client.post('/auth/payment/callback', headers={'x-nowpayments-sig': 'x'},
                           json={'a': 1})
        assert resp.status_code == 500
        assert 'خطأ في معالجة callback' in resp.get_json()['error']

    @pytest.mark.parametrize('query,status', [('amount=abc', 400), ('amount=zzz', 400)])
    def test_estimate_unparseable_amount(self, monkeypatch, client, query, status):
        resp = client.get(f'/auth/payment/estimate?{query}')
        assert resp.status_code == status
        assert resp.get_json() == {'success': False, 'error': 'مبلغ غير صالح'}

    def test_estimate_min_amount_guard(self, client):
        resp = client.get('/auth/payment/estimate?amount=0.5')
        assert resp.status_code == 400
        assert 'الحد الأدنى للتبرع' in resp.get_json()['error']

    def test_estimate_success_forwarding(self, monkeypatch, client):
        svc = _patch_np(monkeypatch, get_estimated_amount={'success': True, 'data': {'v': 1}})
        resp = client.get('/auth/payment/estimate?amount=2.5&from=usd&to=eth')
        assert resp.status_code == 200
        args = svc.get_estimated_amount.call_args.args
        assert args[0] == 2.5 and args[1] == 'usd' and args[2] == 'eth'

    def test_estimate_service_error(self, monkeypatch, client):
        _patch_np(monkeypatch, get_estimated_amount={'success': False, 'error': 'upstream'})
        assert client.get('/auth/payment/estimate?amount=5').status_code == 400

    def test_estimate_service_raises(self, monkeypatch, client):
        svc = _patch_np(monkeypatch)
        svc.get_estimated_amount.side_effect = RuntimeError('x')
        assert client.get('/auth/payment/estimate?amount=5').status_code == 500

    def test_support_lists_only_active_packages(self, client):
        from models.package import Package
        db.session.add_all([
            Package(name_ar='أساسية', name_en='Basic', slug='basic-w', price=9.99,
                    is_active=True, features=['a']),
            Package(name_ar='مخفية', name_en='Hidden', slug='hidden-w', price=19.99,
                    is_active=False),
        ])
        db.session.commit()
        resp = client.get('/auth/support')
        html = _html(resp)
        assert resp.status_code == 200
        assert 'أساسية' in html and 'مخفية' not in html

    def test_thank_you_page(self, client):
        resp = client.get('/auth/thank-you?payment_id=P42&status=finished')
        assert resp.status_code == 200


class TestUsersRoutes:
    @pytest.mark.parametrize('path,method,data', [
        ('/users/', 'GET', None),
        ('/users/create', 'GET', None),
        ('/users/create', 'POST', {}),
        ('/users/99', 'GET', None),
        ('/users/99/edit', 'GET', None),
        ('/users/99/edit', 'POST', {}),
        ('/users/99/toggle-active', 'POST', {}),
        ('/users/99/delete', 'POST', {})])
    def test_manage_users_anonymous_redirects_to_login(self, client, path, method, data):
        resp = getattr(client, method.lower())(path, data=data)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_change_password_anonymous_redirects(self, client):
        resp = client.get('/users/change-password')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_seller_blocked_from_user_management_matrix(self, client, login_seller):
        seller = User.query.filter_by(username='testseller').first()
        checks = [
            ('get', '/users/', 302),
            ('get', '/users/create', 403),
            ('post', '/users/create', 403),
            ('get', f'/users/{seller.id}', 403),
            ('get', f'/users/{seller.id}/edit', 403),
            ('post', f'/users/{seller.id}/edit', 403),
            ('post', f'/users/{seller.id}/toggle-active', 403),
        ]
        for method, url, expected in checks:
            resp = getattr(client, method)(url)
            assert resp.status_code == expected, url
        resp = client.post(f'/users/{seller.id}/delete')
        assert resp.status_code == 302
        assert '/users/' in resp.headers['Location']

    def test_manager_without_permission_redirects_from_index(self, client, manager_user):
        assert _login(client, 'testmanager', 'ManagerPass123!').status_code == 302
        assert client.get('/users/').status_code == 302

    def test_index_excludes_owners_inactive_and_searches(self, client, owner_user,
                                                         seller_user):
        _mk_user(db, 'finder_one', active=True)
        _mk_user(db, 'finder_two', active=False)
        _login(client)
        html = _html(client.get('/users/'))
        assert 'testseller' in html and 'finder_one' in html
        assert 'owner@test.com' not in html
        assert 'finder_two' not in html
        assert User.query.filter_by(is_owner=True).count() >= 1
        page = _html(client.get('/users/?search=finder'))
        assert 'finder_one' in page and 'testseller' not in page
        empty = _html(client.get('/users/?search=no-match-anywhere-xyz'))
        assert 'finder_one' not in empty

    def test_view_and_404_branches(self, client, owner_user, seller_user):
        _login(client)
        assert client.get(f'/users/{seller_user.id}').status_code == 200
        assert client.get('/users/999999').status_code == 404
        assert client.get(f'/users/{owner_user.id}').status_code == 404

    def test_create_get_lists_roles_for_owner_level(self, client, owner_user, seller_user):
        tier_role = _mk_role(db, 'seller-tier')
        _login(client)
        resp = client.get('/users/create')
        assert resp.status_code == 200
        assert str(tier_role.id) in _html(resp)

    def test_create_valid_user_side_effects(self, client, owner_user, seller_user):
        target_role = _mk_role(db, 'cashier')
        _login(client)
        form = {'username': 'newbie1', 'email': 'newbie1@example.com', 'full_name': 'New Bie',
                'full_name_ar': 'نيو بي', 'phone': '+971501112233', 'role_id': target_role.id,
                'is_active': '1', 'password': STRONG_PW}
        resp = client.post('/users/create', data=form, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/users/')
        created = User.query.filter_by(username='newbie1').first()
        assert created is not None
        assert created.check_password(STRONG_PW)
        assert created.is_owner is False and created.is_active is True
        assert created.full_name_ar == 'نيو بي'

    @pytest.mark.parametrize('case,overrides,key_fragment', [
        ('no_role', {'role_id': ''}, 'الدور الوظيفي'),
        ('weak_pw', {'password': 'short'}, 'ضعيفة'),
        ('empty_pw', {'password': ''}, 'ضعيفة')])
    def test_create_validation_rejections(self, client, owner_user, seller_user, case,
                                          overrides, key_fragment):
        base = {'username': f'u_{case}', 'email': f'u_{case}@example.com',
                'full_name': 'X', 'role_id': seller_user.role_id, 'is_active': '1',
                'password': STRONG_PW}
        base.update(overrides)
        _login(client)
        resp = client.post('/users/create', data=base)
        assert resp.status_code == 200
        assert key_fragment in _html(resp)
        assert User.query.filter(User.username == base['username']).first() is None

    def test_create_duplicate_username_rolls_back(self, client, owner_user, seller_user):
        _login(client)
        resp = client.post('/users/create', data={
            'username': 'testseller', 'email': 'dupe@example.com', 'full_name': 'D',
            'role_id': seller_user.role_id, 'password': STRONG_PW})
        assert resp.status_code == 200
        assert 'حدث خطأ في إنشاء المستخدم' in _html(resp)
        assert User.query.filter_by(email='dupe@example.com').first() is None

    def test_edit_get_post_password_and_profile(self, client, owner_user, seller_user):
        _login(client)
        assert client.get(f'/users/{seller_user.id}/edit').status_code == 200
        old_hash = seller_user.password_hash
        resp = client.post(f'/users/{seller_user.id}/edit', data={
            'email': 'moved@example.com', 'full_name': 'Moved Seller',
            'phone': '+971599887766', 'role_id': seller_user.role_id,
            'new_password': 'Fresh-Pass#77'})
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f"/users/{seller_user.id}")
        seller = User.query.filter_by(id=seller_user.id).first()
        assert seller.email == 'moved@example.com'
        assert seller.password_hash != old_hash
        assert seller.check_password('Fresh-Pass#77') is True
        assert 'Moved Seller' in _html(client.get(f'/users/{seller_user.id}'))

    def test_edit_weak_password_keeps_old_hash(self, client, owner_user, seller_user):
        old_hash = seller_user.password_hash
        _login(client)
        resp = client.post(f'/users/{seller_user.id}/edit', data={
            'email': 'moved@example.com', 'full_name': seller_user.full_name,
            'role_id': seller_user.role_id, 'new_password': 'nope'})
        assert resp.status_code == 302
        assert f'/users/{seller_user.id}/edit' in resp.headers['Location']
        db.session.expire_all()
        seller = db.session.get(User, seller_user.id)
        assert seller.password_hash == old_hash
        assert seller.check_password('SellerPass123!')
        assert User.query.filter_by(email='moved@example.com').first() is None

    def test_toggle_active_and_not_found(self, client, owner_user, seller_user):
        _login(client)
        assert seller_user.is_active is True
        resp = client.post(f'/users/{seller_user.id}/toggle-active', follow_redirects=True)
        seller = User.query.filter_by(id=seller_user.id).first()
        assert seller.is_active is False
        assert 'إلغاء تفعيل' in _html(resp)
        assert client.post(f'/users/{owner_user.id}/toggle-active').status_code == 404
        assert client.post('/users/424242/toggle-active').status_code == 404

    def test_delete_self_guard_with_non_admin_staffer(self, client, owner_user):
        from models import Permission
        perm = Permission.query.filter_by(code='manage_users').first()
        staff_role = Role(name='Staff-Del', name_ar='موظف', slug='staff-del-x',
                          permissions=[perm])
        db.session.add(staff_role)
        db.session.flush()
        staffer = User(username='selfdel', email='selfdel@example.com', full_name='S',
                       role_id=staff_role.id)
        staffer.set_password(STRONG_PW)
        db.session.add(staffer)
        db.session.commit()
        _login(client, 'selfdel', STRONG_PW)
        resp = client.post(f'/users/{staffer.id}/delete', follow_redirects=True)
        assert 'لا يمكنك حذف حسابك الخاص' in _html(resp)
        assert User.query.filter_by(id=staffer.id).first() is not None

    def test_delete_user_with_sales_deactivates_instead(self, client, owner_user,
                                                        seller_user):
        category = ProductCategory(name='DelCat', name_ar='حذف', is_active=True)
        db.session.add(category)
        victim = _mk_user(db, 'victim-sales')
        db.session.add(Product(name='DelProd', sku='DEL-SKU-1', category_id=category.id,
                               cost_price=Decimal('1'), regular_price=Decimal('2'),
                               current_stock=Decimal('1'), min_stock_alert=Decimal('0'),
                               is_active=True))
        db.session.flush()
        db.session.add(Sale(sale_number='S-2026-900001', customer_id=None,
                            seller_id=victim.id, total_amount=Decimal('5'),
                            amount_base=Decimal('5'), paid_amount=Decimal('0'),
                            paid_amount_base=Decimal('0'), balance_due=Decimal('5'),
                            currency='AED', exchange_rate=Decimal('1'),
                            payment_status='unpaid', status='confirmed', is_active=True))
        db.session.commit()
        _login(client)
        resp = client.post(f'/users/{victim.id}/delete', follow_redirects=True)
        survivor = User.query.filter_by(id=victim.id).first()
        assert survivor is not None and survivor.is_active is False
        assert 'إلغاء تفعيل المستخدم' in _html(resp)

    def test_delete_user_without_sales_removes_row(self, client, owner_user):
        fresh = _mk_user(db, 'deleteme-clean')
        _login(client)
        resp = client.post(f'/users/{fresh.id}/delete', follow_redirects=True)
        assert 'نهائياً' in _html(resp)
        assert User.query.filter_by(id=fresh.id).first() is None
        assert client.post('/users/987654/delete', follow_redirects=False).status_code == 404

    def test_change_password_full_matrix(self, client, seller_user):
        _login(client, 'testseller', 'SellerPass123!')

        wrong_current = client.post('/users/change-password', data={
            'current_password': 'WRONG-old!', 'new_password': STRONG_PW,
            'confirm_password': STRONG_PW})
        assert 'كلمة المرور الحالية غير صحيحة' in _html(wrong_current)

        mismatched = client.post('/users/change-password', data={
            'current_password': 'SellerPass123!', 'new_password': STRONG_PW,
            'confirm_password': 'Different-Pass#9'})
        assert 'غير متطابقة' in _html(mismatched)

        weak = client.post('/users/change-password', data={
            'current_password': 'SellerPass123!', 'new_password': 'short',
            'confirm_password': 'short'})
        assert 'ضعيفة' in _html(weak)

        changed = client.post('/users/change-password', data={
            'current_password': 'SellerPass123!', 'new_password': STRONG_PW,
            'confirm_password': STRONG_PW})
        assert changed.status_code == 302
        seller = User.query.filter_by(id=seller_user.id).first()
        assert seller.check_password(STRONG_PW)

        duplicate = client.post('/users/change-password', data={
            'current_password': STRONG_PW, 'new_password': STRONG_PW,
            'confirm_password': STRONG_PW})
        assert 'يجب أن تختلف عن الحالية' in _html(duplicate)

        final = client.post('/users/change-password', data={
            'current_password': STRONG_PW, 'new_password': 'Brand-New#2026pw',
            'confirm_password': 'Brand-New#2026pw'})
        assert final.status_code == 302
        seller = User.query.filter_by(id=seller_user.id).first()
        assert seller.check_password('Brand-New#2026pw')
        assert seller.check_password(STRONG_PW) is False


FIELD_EXPECTATIONS = {
    'cash': ([], 0),
    'card': (['reference_number', 'card_last4'], 0),
    'bank_transfer': (['reference_number', 'bank_name'], 1),
    'cheque': (['cheque_number', 'cheque_date', 'bank_name'], 3),
}


class TestApiRoutes:
    def test_health_and_version_public_shapes(self, client):
        health = client.get('/api/health')
        assert health.status_code == 200
        assert health.get_json() == {'status': 'ok', 'message': 'API is running'}
        version = client.get('/api/version')
        assert version.status_code == 200
        vjson = version.get_json()
        assert vjson['version'] == '1.0.0'
        assert 'Warehouse' in vjson['name']

    @pytest.mark.parametrize('url', ['/api/payment-fields/cash', '/api/currency-rate/usd/aed',
                                     '/api/search?q=x', '/api/check-username?username=abc',
                                     '/api/products/low-stock'])
    def test_api_login_required_matrix(self, client, url):
        resp = client.get(url)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    @pytest.mark.parametrize('method,names,required_count', [
        ('cash', [], 0),
        ('card', ['reference_number', 'card_last4'], 0),
        ('bank_transfer', ['reference_number', 'bank_name'], 1),
        ('cheque', ['cheque_number', 'cheque_date', 'bank_name'], 3),
        ('e_wallet', ['reference_number', 'wallet_provider'], 1)])
    def test_payment_field_shapes_per_method(self, client, login_owner, method, names,
                                             required_count):
        data = client.get(f'/api/payment-fields/{method}').get_json()
        assert set(data.keys()) >= {'fields', 'ar_title', 'en_title'}
        assert [f['name'] for f in data['fields']] == names
        got_required = sum(1 for f in data['fields'] if f.get('required'))
        assert got_required == required_count

    def test_payment_fields_unknown_defaults_empty(self, client, login_owner):
        assert client.get('/api/payment-fields/bitcoin').get_json() == {'fields': []}

    def test_currency_rate_mocked(self, monkeypatch, client, login_owner):
        monkeypatch.setattr(CurrencyService, 'get_exchange_rate',
                            staticmethod(lambda f, t: Decimal('3.672500')))
        data = client.get('/api/currency-rate/usd/aed').get_json()
        assert data == {'from': 'usd', 'to': 'aed', 'rate': 3.6725, 'success': True}

    def test_currency_rate_failure_payload(self, monkeypatch, client, login_owner):
        def _explode(from_c, to_c):
            raise ValueError('offline rate provider')
        monkeypatch.setattr(CurrencyService, 'get_exchange_rate', staticmethod(_explode))
        resp = client.get('/api/currency-rate/usd/aed')
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['success'] is False
        assert body['manual_input_required'] is True
        assert 'offline' in body['error']

    def test_search_products_shape(self, client, login_owner, test_product):
        data = client.get('/api/search?type=products&q=brake').get_json()
        assert data['has_more'] is False
        hit = data['results'][0]
        assert hit['id'] == test_product.id
        assert hit['text'] == 'Test Brake Pad'
        assert hit['sku'] == 'SKU-TEST-001'
        assert hit['current_stock'] == 100.0
        assert hit['default_price'] == 100.0
        assert hit['cost_price'] == 50.0
        assert hit['is_low_stock'] is False
        assert isinstance(hit['unit_price'], float)
        assert isinstance(hit['merchant_price'], float) or hit['merchant_price'] is None

    def test_search_products_paging_has_more(self, client, login_owner, test_category):
        for i in range(21):
            db.session.add(Product(name=f'BulkItem{i}', sku=f'BULK-{i:03d}',
                                   category_id=test_category.id,
                                   cost_price=Decimal('1'), regular_price=Decimal('2'),
                                   current_stock=Decimal('5'), min_stock_alert=Decimal('1'),
                                   is_active=True))
        db.session.commit()
        page1 = client.get('/api/search?type=products&q=BULK-').get_json()
        assert page1['has_more'] is True
        assert len(page1['results']) == 20
        assert page1['results'][0]['is_low_stock'] is False

    def test_search_customers_default_type_and_filtering(self, client, login_owner,
                                                         test_customer):
        db.session.add(Customer(name='Quiet Person', customer_type='regular',
                                is_active=False))
        db.session.commit()
        plain = client.get('/api/search').get_json()
        names = [r['name'] for r in plain['results']]
        assert test_customer.name in names
        assert 'Quiet Person' not in names
        assert plain['has_more'] is False
        sample = plain['results'][0]
        assert set(sample.keys()) >= {'id', 'text', 'name', 'phone', 'email',
                                      'customer_type', 'balance_aed'}
        by_phone = client.get('/api/search?type=customers&q=971501234567').get_json()
        assert any(r['id'] == test_customer.id for r in by_phone['results'])

    def test_search_customers_paging_has_more(self, client, login_owner):
        for i in range(21):
            db.session.add(Customer(name=f'PageCust{i:02d}', customer_type='regular',
                                    is_active=True))
        db.session.commit()
        page1 = client.get('/api/search?type=customers&q=PageCust&page=1').get_json()
        assert page1['has_more'] is True
        assert len(page1['results']) == 20
        page2 = client.get('/api/search?type=customers&q=PageCust&page=2').get_json()
        assert page2['has_more'] is False
        assert len(page2['results']) == 1

    def test_search_suppliers_shape_and_types(self, client, login_owner):
        from models import Supplier
        sup = Supplier(name='Acme Parts', company_name='Acme Trading LLC',
                       phone='+971555000111', email='acme@example.com',
                       supplier_type='parts', rating=4, is_active=True, is_verified=True,
                       total_purchases_aed=Decimal('300'), total_paid_aed=Decimal('100'))
        db.session.add(sup)
        db.session.add(Supplier(name='Zombie Supply', supplier_type='other',
                                is_active=False))
        db.session.commit()
        data = client.get('/api/search?type=suppliers&q=Acme').get_json()
        assert data['has_more'] is False
        hit = data['results'][0]
        assert hit['company_name'] == 'Acme Trading LLC'
        assert hit['type_display'] == 'قطع غيار'
        assert hit['balance_aed'] == 200.0
        assert hit['is_verified'] is True
        assert '- Acme Trading LLC' in hit['text']
        empty = client.get('/api/search?type=suppliers&q=Zombie').get_json()
        assert empty['results'] == [] and empty['has_more'] is False

    @pytest.mark.parametrize('username,expectation', [
        ('', 'short'), ('ab', 'short'),
        ('has space', 'charset'), ('toolongusername_______x', 'charset'),
        ('ok-name7', 'charset'), ('ok_name7', 'available')])
    def test_check_username_branches(self, client, login_owner, username, expectation):
        from urllib.parse import quote
        data = client.get(f'/api/check-username?username={quote(username)}').get_json()
        if expectation == 'short':
            assert data['available'] is False
            assert 'قصير جداً' in data['error']
        elif expectation == 'charset':
            assert data['available'] is False
            assert 'استخدم حروف إنجليزية' in data['error']
        else:
            assert data['available'] is True
            assert data['message'] == 'اسم المستخدم متاح ✓'

    def test_check_username_existing_suggestions(self, client, login_owner):
        year = datetime.now().year
        data = client.get('/api/check-username?username=testowner').get_json()
        assert data['available'] is False
        assert 'موجود مسبقاً' in data['message']
        assert f'testowner_{year}' in data['suggestions']
        assert 'testowner_admin' in data['suggestions']

    def test_low_stock_endpoint(self, client, login_owner, test_category, test_product):
        db.session.add_all([
            Product(name='LowStockProbe', sku='LOW-STOCK-1', category_id=test_category.id,
                    cost_price=Decimal('1'), regular_price=Decimal('3'),
                    current_stock=Decimal('2'), min_stock_alert=Decimal('8'),
                    is_active=True),
            Product(name='InactiveLow', sku='LOW-OFF-1', category_id=test_category.id,
                    cost_price=Decimal('1'), regular_price=Decimal('3'),
                    current_stock=Decimal('0'), min_stock_alert=Decimal('8'),
                    is_active=False),
        ])
        db.session.commit()
        data = client.get('/api/products/low-stock').get_json()
        assert data['success'] is True
        assert data['count'] == 1
        entry = data['products'][0]
        assert entry['sku'] == 'LOW-STOCK-1'
        assert entry['current_stock'] == 2.0
        assert entry['min_stock_alert'] == 8.0
        assert entry['needed'] == 6.0
        assert 'SKU-TEST-001' not in {p['sku'] for p in data['products']}
        assert 'LOW-OFF-1' not in {p['sku'] for p in data['products']}

    @pytest.mark.parametrize('http_method,payload', [
        ('put', {'k': 'v1'}),
        ('patch', {'k': 'v2'}),
        ('delete', {'list': [1, 2]}),
        ('put', None),
    ])
    def test_echo_methods_roundtrip(self, client, login_owner, http_method, payload):
        kwargs = {'json': payload} if payload is not None else {}
        resp = getattr(client, http_method)('/api/echo', **kwargs)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['data'] == (payload or {})


@pytest.mark.parametrize('raw,expected', [
    (None, ''), ('', ''),
    ('<script>alert(1)</script>', '&lt;script&gt;alert(1)&lt;/script&gt;'),
    ('plain', 'plain'),
])
def test_sanitize_html_escape_mode(raw, expected):
    assert str(InputSanitizer.sanitize_html(raw)) == expected


def test_sanitize_html_allow_tags_strips_script_keeps_whitelist():
    dirty = '<script>evil()</script><b>Bold</b><i onclick="x()">it</i><article>drop</article>'
    cleaned = str(InputSanitizer.sanitize_html(dirty, allow_tags=True))
    assert '<b>Bold</b>' in cleaned
    assert 'onclick' not in cleaned
    assert '<script' not in cleaned
    assert '<article>' not in cleaned


@pytest.mark.parametrize('raw,expected', [
    (None, ''), ('', ''),
    ('<b>a</b> & <img src=x>', 'a &amp;'),
    (12345, '12345'),
])
def test_sanitize_text_matrix(raw, expected):
    assert str(InputSanitizer.sanitize_text(raw)) == expected


def test_sanitize_text_length_cap_and_strip():
    out = str(InputSanitizer.sanitize_text('  ' + 'x' * 300 + ' ', max_length=250))
    assert len(out) == 250
    assert InputSanitizer.sanitize_text(' spaced \t\n ') == 'spaced'
    assert InputSanitizer.sanitize_text('aaa', max_length=None) == 'aaa'


@pytest.mark.parametrize('raw,expected', [
    (None, None), ('', None), ('  User@Example.COM ', 'user@example.com'),
    ('weird+tag@example.co.uk', None),
    ('not-an-email', None), ('double@@at.com', None), ('missing-at.com', None),
])
def test_sanitize_email_matrix(raw, expected):
    assert InputSanitizer.sanitize_email(raw) == expected


@pytest.mark.parametrize('raw,expected', [
    (None, None), ('', None),
    ('+971 (50) 123-4567', '+971 (50) 123-4567'),
    ('call me 50x60!??', '5060'),
    (97150, '97150'), ('   ', ''),
])
def test_sanitize_phone_matrix(raw, expected):
    result = InputSanitizer.sanitize_phone(raw)
    assert result == expected or result is expected


def test_sanitize_phone_keeps_allowed_marks_drops_letters():
    assert InputSanitizer.sanitize_phone('ab+971-50-cd(ef)!?g12') == '+971-50-()12'


@pytest.mark.parametrize('value,neg,dec,expected', [
    (None, True, True, None), ('', True, True, None),
    ('12.75', True, True, 12.75), (-8.25, True, True, -8.25),
    (-8.25, False, True, None), ('14', True, False, 14), (17, True, False, 17),
    ('garbage', True, True, None),
])
def test_sanitize_number_matrix(value, neg, dec, expected):
    result = InputSanitizer.sanitize_number(value, allow_negative=neg, allow_decimal=dec)
    if expected is None:
        assert result is None
    else:
        assert result == expected


def test_sanitize_number_int_decimal_string_fails_closed():
    assert InputSanitizer.sanitize_number('9.9', allow_decimal=False) is None


@pytest.mark.parametrize('raw,expected', [
    (None, ''), ('', ''),
    ('a;b', 'ab'), ('id--x', 'idx'), ('1/*2*/3', '123'), ('xp_foo', 'foo'),
    ('sp_bar exec query', 'bar  query'),
])
def test_sanitize_sql_input_matrix(raw, expected):
    assert InputSanitizer.sanitize_sql_input(raw) == expected


def test_sanitize_sql_input_known_quirks():
    assert InputSanitizer.sanitize_sql_input("'; DROP TABLE users; --") \
        == "' DROP TABLE users"
    assert InputSanitizer.sanitize_sql_input('execute hi') == 'ute hi'


def test_sanitize_form_data_rule_dispatch():
    rules = {
        'email': {'type': 'email'},
        'phone': {'type': 'phone'},
        'qty': {'type': 'number'},
        'bio': {'type': 'html'},
        'note': {'type': 'text', 'max_length': 5},
        'plain': {},
    }
    out = sanitize_form_data({
        'email': 'BAD@@Mail', 'phone': '12345-678', 'qty': '42.5',
        'bio': '<p>Hi <script>x()</script></p>', 'note': 'abcdefghij', 'plain': '<b>k</b>',
    }, rules)
    assert out['email'] is None
    assert out['phone'] == '12345-678'
    assert out['qty'] == 42.5
    bio = str(out['bio'])
    assert bio.startswith('<p>') and 'Hi' in bio
    assert '<script' not in bio
    assert out['note'] == 'abcde'
    assert str(out['plain']) == 'k'


class TestBackupOptimizer:
    def test_compress_backup_roundtrip_and_cleanup(self, tmp_path):
        target = tmp_path / 'db_backup.sql'
        payload = b'CREATE TABLE big_table;\nINSERT INTO t VALUES (42);\n' * 800
        target.write_bytes(payload)
        info = BackupOptimizer.compress_backup(str(target))
        assert info['success'] is True
        gz_path = info['compressed_path']
        assert gz_path.endswith('.gz') and os.path.exists(gz_path)
        assert os.path.exists(str(target)) is False
        assert info['original_size'] == len(payload)
        with gzip.open(gz_path, 'rb') as fh:
            assert fh.read() == payload
        assert 0 < info['compression_ratio'] < 100

    def test_compress_backup_missing_file_reports_error(self, tmp_path):
        info = BackupOptimizer.compress_backup(str(tmp_path / 'never.sql'))
        assert info['success'] is False
        assert 'error' in info

    def test_cleanup_old_backups_keep_n_across_patterns(self, tmp_path):
        base = time.time() - 10000
        paths = []
        for i in range(7):
            p = tmp_path / f'backup_{i}.sql.gz'
            p.write_text('-- dump')
            paths.append(p)
        for i in range(4):
            p = tmp_path / f'dump_{i}.dump'
            p.write_text('dumpdata')
            paths.append(p)
        for idx, p in enumerate(paths):
            os.utime(p, (base + idx * 100, base + idx * 100))
        other = tmp_path / 'notes.txt'
        other.write_text('keep me forever')
        result = BackupOptimizer.cleanup_old_backups(str(tmp_path), keep_count=5)
        assert result['success'] is True
        assert result['deleted_count'] == 6
        assert result['kept_count'] == 5
        survivors = list(tmp_path.glob('*.sql*')) + list(tmp_path.glob('*.dump*'))
        assert len(survivors) == 5
        assert (tmp_path / 'backup_0.sql.gz').exists() is False
        assert (tmp_path / 'backup_6.sql.gz').exists()
        assert (tmp_path / 'dump_3.dump').exists()
        assert other.exists()

    def test_cleanup_on_missing_dir_does_not_raise(self, tmp_path):
        result = BackupOptimizer.cleanup_old_backups(str(tmp_path / 'void'), keep_count=2)
        assert result['success'] is True
        assert result['deleted_count'] == 0

    def test_verify_backup_gz_plain_junk_and_missing(self, tmp_path):
        gz_target = tmp_path / 'real.sql.gz'
        with gzip.open(gz_target, 'wb') as fh:
            fh.write(b'SET client_encoding;\nCOPY public.users FROM stdin;')
        plain = tmp_path / 'plain.sql'
        plain.write_bytes(b'-- PostgreSQL dump\nCREATE TABLE notes (id int);')
        junk = tmp_path / 'junk.bin'
        junk.write_bytes(os.urandom(64))
        missing = tmp_path / 'missing.gz'
        assert BackupOptimizer.verify_backup(str(gz_target)) is True
        assert BackupOptimizer.verify_backup(str(plain)) is True
        assert BackupOptimizer.verify_backup(str(junk)) is False
        assert BackupOptimizer.verify_backup(str(missing)) is False

    def test_get_backup_info_flags_compression(self, tmp_path):
        gz_target = tmp_path / 'one.sql.gz'
        with gzip.open(gz_target, 'wb') as fh:
            fh.write(b'COPY tbl FROM stdin;' * 100)
        plain = tmp_path / 'two.sql'
        plain.write_bytes(b'INSERT INTO x VALUES (1);' * 100)
        info = BackupOptimizer.get_backup_info(str(tmp_path))
        assert info['success'] is True
        assert info['total_backups'] == 2
        flags = {b['filename']: b['compressed'] for b in info['backups']}
        assert flags['one.sql.gz'] is True
        assert flags['two.sql'] is False
        assert info['total_size_mb'] >= 0
        entries = [(b['filename'], b['size_mb'], b['created']) for b in info['backups']]
        assert len(entries) == 2

    def test_get_backup_info_empty_dir(self, tmp_path):
        info = BackupOptimizer.get_backup_info(str(tmp_path))
        assert info == {'success': True, 'total_backups': 0, 'total_size_mb': 0,
                        'backups': []}


class TestAssetCompression:
    def test_minify_css_removes_comments_and_whitespace(self):
        src = '.box {\n  /* comment */\n  color : red ;\n  margin : 0 ; }\n.spam { } '
        out = AssetCompressor.minify_css(src)
        assert '/*' not in out and '\n' not in out
        assert 'color:red;margin:0}' in out
        assert ';}' not in out

    def test_minify_js_strips_comments_and_collapses(self):
        out = AssetCompressor.minify_js('var a = 1; // trailing\nvar b = 2; /* blk */')
        assert '//' not in out and 'blk' not in out
        assert out.endswith('2;')

    def test_minify_js_known_url_slashes_pitfall(self):
        js = 'const u = "http://a.com/x";\nlet y = 1;'
        out = AssetCompressor.minify_js(js)
        assert 'http:let' in out
        assert out == 'const u = "http:let y = 1;'

    def test_gzip_file_roundtrip(self, tmp_path):
        asset = tmp_path / 'app.js'
        original = 'console.log("wave");' * 50
        asset.write_text(original)
        gz_path = AssetCompressor.gzip_file(str(asset))
        assert gz_path.endswith('.gz')
        with gzip.open(gz_path, 'rb') as fh:
            assert fh.read().decode('utf-8') == original

    def test_get_file_hash_deterministic_short(self):
        h1 = AssetCompressor.get_file_hash('wave-content')
        h2 = AssetCompressor.get_file_hash('wave-content')
        assert h1 == h2 and len(h1) == 8
        assert AssetCompressor.get_file_hash('other') != h1

    def test_process_css_files_creates_min_and_gz(self, tmp_path):
        css_dir = tmp_path / 'css'
        css_dir.mkdir()
        (css_dir / 'style.css').write_text(
            'body { background : #fff; /* c */ padding : 0 ; }' * 20)
        (css_dir / 'prebuilt.min.css').write_text('a{color:red}')
        results = AssetCompressor.process_css_files(str(css_dir))
        assert len(results) == 1
        rec = results[0]
        assert rec['file'] == 'style.css'
        assert (css_dir / 'style.min.css').exists()
        assert (css_dir / 'style.min.css.gz').exists()
        assert rec['minified'] < rec['original']
        assert 0 < rec['gzipped'] < rec['original']
        assert AssetCompressor.process_css_files(str(tmp_path / 'none')) == []

    def test_process_js_files_creates_min_and_gz(self, tmp_path):
        js_dir = tmp_path / 'js'
        js_dir.mkdir()
        (js_dir / 'app.js').write_text('// header\nfunction run() {\n  return 41 + 1;\n}\n'
                                       * 20)
        (js_dir / 'vendor.min.js').write_text('v=1')
        results = AssetCompressor.process_js_files(str(js_dir))
        assert len(results) == 1
        assert (js_dir / 'app.min.js').exists()
        assert (js_dir / 'app.min.js.gz').exists()
        minified = (js_dir / 'app.min.js').read_text(encoding='utf-8')
        assert 'header' not in minified
        assert AssetCompressor.process_js_files(str(tmp_path / 'miss')) == []

    def test_compress_all_summary_from_static_layout(self, tmp_path, monkeypatch):
        static_css = tmp_path / 'static' / 'css'
        static_js = tmp_path / 'static' / 'js'
        static_css.mkdir(parents=True)
        static_js.mkdir(parents=True)
        (static_css / 'theme.css').write_text('.t { color : blue ; /* x */ }' * 10)
        (static_js / 'main.js').write_text('let z = 5;\n// note\n' * 10)
        monkeypatch.chdir(tmp_path)
        summary = AssetCompressor.compress_all()
        assert summary['css'] and summary['js']
        assert 0 < summary['total_savings'] < 100

    def test_register_compression_cli_registers_command(self, app):
        from utils.asset_compression import register_compression_cli
        register_compression_cli(app)
        assert 'compress-assets' in app.cli.commands


class TestFixedAssetModel:
    _gl_seq = iter(range(1, 500))

    @classmethod
    def _asset(cls, dbf=None, **overrides):
        price = overrides.get('purchase_price', Decimal('12000.000'))
        acc = overrides.get('accumulated_depreciation', Decimal('0'))
        defaults = dict(
            asset_number='FA-WAVE-001', name_ar='حاسوب محاسبي', name_en='Accounting PC',
            category='equipment', purchase_date=date(2025, 1, 1),
            purchase_price=price, accumulated_depreciation=acc,
            book_value=price - acc,
            salvage_value=Decimal('1000.000'),
            depreciation_method='straight_line', useful_life_years=10, status='active')
        if dbf is not None and 'asset_account_id' not in overrides:
            n = next(cls._gl_seq)
            trio = {
                'asset': GLAccount(code=f'9{n:02d}10', name=f'Assets {n}', type='asset'),
                'dep': GLAccount(code=f'9{n:02d}20', name=f'AccDep {n}', type='asset'),
                'expense': GLAccount(code=f'9{n:02d}30', name=f'DepExp {n}',
                                     type='expense'),
            }
            dbf.session.add_all(trio.values())
            dbf.session.flush()
            defaults['asset_account_id'] = trio['asset'].id
            defaults['depreciation_account_id'] = trio['dep'].id
            defaults['expense_account_id'] = trio['expense'].id
        defaults.update(overrides)
        return FixedAsset(**defaults)

    def test_properties_and_reprs(self, db):
        asset = self._asset(dbf=db)
        db.session.add(asset)
        db.session.commit()
        assert 'FA-WAVE-001' in repr(asset)
        schedule_repr = DepreciationSchedule(
            asset_id=asset.id, period_date=date(2026, 1, 31),
            depreciation_amount=Decimal('1'), accumulated_depreciation=Decimal('1'),
            book_value=Decimal('1'))
        assert 'DepreciationSchedule' in repr(schedule_repr)
        assert asset.category_ar == 'معدات'
        asset.category = 'unknown-cat'
        assert asset.category_ar == 'unknown-cat'
        assert asset.status_ar == 'نشط'
        asset.status = 'sold'
        assert asset.status_ar == 'تم بيعه'
        asset.status = 'weird'
        assert asset.status_ar == 'weird'
        assert asset.depreciable_amount == Decimal('11000.000')
        assert asset.remaining_book_value == Decimal('12000.000')

    @pytest.mark.parametrize('category,method,acc_dep,salvage,expected', [
        ('land', 'straight_line', Decimal('0'), Decimal('1000'), Decimal('0')),
        ('equipment', 'straight_line', Decimal('0'), Decimal('1000'), Decimal('91.67')),
        ('equipment', 'declining_balance', Decimal('0'), Decimal('1000'), Decimal('200.00')),
        ('vehicle', 'declining_balance', Decimal('450'), Decimal('11500'), Decimal('50.00')),
        ('building', 'declining_balance', Decimal('600'), Decimal('11500'), Decimal('0')),
        ('machine', 'unit_of_production_xyz', Decimal('0'), Decimal('1000'), Decimal('0')),
    ])
    def test_calculate_monthly_depreciation_matrix(self, db, category, method, acc_dep,
                                                   salvage, expected):
        asset = self._asset(dbf=db, category=category, depreciation_method=method,
                            accumulated_depreciation=acc_dep, salvage_value=salvage)
        db.session.add(asset)
        db.session.commit()
        assert asset.calculate_monthly_depreciation() == expected

    @staticmethod
    def _gl_accounts(dbf):
        accounts = {
            'asset': GLAccount(code='1510', name='Fixed Assets', name_ar='أصول ثابتة',
                               type='asset'),
            'dep': GLAccount(code='1520', name='Accumulated Dep.', name_ar='مجمع استهلاك',
                             type='asset'),
            'expense': GLAccount(code='6600', name='Depreciation Expense',
                                 name_ar='مصروف استهلاك', type='expense'),
        }
        dbf.session.add_all(accounts.values())
        dbf.session.flush()
        return accounts

    @staticmethod
    def _capture_gl(monkeypatch):
        calls = []

        def fake_post_entry(lines, description='', reference_type=None, reference_id=None,
                            currency=None, exchange_rate=1):
            calls.append({'lines': lines, 'description': description,
                          'reference_type': reference_type, 'reference_id': reference_id})
            return SimpleNamespace(id=len(calls) + 700)
        monkeypatch.setattr(GLService, 'post_entry', staticmethod(fake_post_entry))
        return calls

    def test_post_depreciation_happy_path_updates_ledger_fields(self, db, monkeypatch):
        gl = self._gl_accounts(db)
        asset = self._asset(depreciation_account_id=gl['dep'].id,
                            expense_account_id=gl['expense'].id,
                            asset_account_id=gl['asset'].id)
        db.session.add(asset)
        db.session.commit()
        calls = self._capture_gl(monkeypatch)
        period = date(2026, 3, 31)
        schedule = asset.post_depreciation(period_date=period)
        assert schedule.id is not None
        assert schedule.depreciation_amount == Decimal('91.67')
        assert schedule.journal_entry_id == 701
        assert schedule.asset_id == asset.id
        asset = FixedAsset.query.filter_by(id=asset.id).first()
        assert asset.accumulated_depreciation == Decimal('91.67')
        assert asset.book_value == Decimal('11908.33')
        assert asset.last_depreciation_date == period
        assert asset.status == 'active'
        posted = calls[0]
        debits = sum(Decimal(str(line['debit'])) for line in posted['lines'])
        credits = sum(Decimal(str(line['credit'])) for line in posted['lines'])
        assert debits == credits == Decimal('91.67')
        assert posted['reference_type'] == 'depreciation'
        codes = [line['account'] for line in posted['lines']]
        assert '6600' in codes and '1520' in codes
        assert len(DepreciationSchedule.query.all()) == 1

    def test_post_depreciation_duplicate_period_rejected(self, db, monkeypatch):
        gl = self._gl_accounts(db)
        asset = self._asset(depreciation_account_id=gl['dep'].id,
                            expense_account_id=gl['expense'].id,
                            asset_account_id=gl['asset'].id)
        db.session.add(asset)
        db.session.flush()
        period = date(2026, 4, 30)
        db.session.add(DepreciationSchedule(
            asset_id=asset.id, period_date=period, depreciation_amount=Decimal('1'),
            accumulated_depreciation=Decimal('1'), book_value=Decimal('1')))
        db.session.commit()
        captured = self._capture_gl(monkeypatch)
        with pytest.raises(ValueError, match='مسبقاً'):
            asset.post_depreciation(period_date=period)
        assert captured == []

    def test_post_depreciation_requires_active_status(self, db, monkeypatch):
        gl = self._gl_accounts(db)
        asset = self._asset(status='disposed', depreciation_account_id=gl['dep'].id,
                            expense_account_id=gl['expense'].id,
                            asset_account_id=gl['asset'].id)
        db.session.add(asset)
        db.session.commit()
        captured = self._capture_gl(monkeypatch)
        with pytest.raises(ValueError, match='غير نشط'):
            asset.post_depreciation(period_date=date(2026, 5, 31))
        assert captured == []
        assert DepreciationSchedule.query.count() == 0

    def test_post_depreciation_zero_amount_returns_none(self, db, monkeypatch):
        gl = self._gl_accounts(db)
        asset = self._asset(category='land', depreciation_account_id=gl['dep'].id,
                            expense_account_id=gl['expense'].id,
                            asset_account_id=gl['asset'].id)
        db.session.add(asset)
        db.session.commit()
        captured = self._capture_gl(monkeypatch)
        assert asset.post_depreciation(period_date=date(2026, 6, 30)) is None
        assert DepreciationSchedule.query.count() == 0
        assert captured == []

    def test_post_depreciation_flip_to_fully_depreciated(self, db, monkeypatch):
        gl = self._gl_accounts(db)
        asset = self._asset(useful_life_years=1, purchase_price=Decimal('1200'),
                            salvage_value=Decimal('1100'), accumulated_depreciation=95,
                            depreciation_account_id=gl['dep'].id,
                            expense_account_id=gl['expense'].id,
                            asset_account_id=gl['asset'].id)
        db.session.add(asset)
        db.session.commit()
        self._capture_gl(monkeypatch)
        asset.post_depreciation(period_date=date(2026, 7, 31))
        refreshed = FixedAsset.query.filter_by(id=asset.id).first()
        assert refreshed.book_value <= refreshed.salvage_value
        assert refreshed.status == 'fully_depreciated'

    def test_dispose_sold_with_gain_posts_gain_line(self, db, monkeypatch):
        gl = self._gl_accounts(db)
        asset = self._asset(accumulated_depreciation=2000,
                            depreciation_account_id=gl['dep'].id,
                            expense_account_id=gl['expense'].id,
                            asset_account_id=gl['asset'].id)
        db.session.add(asset)
        db.session.commit()
        calls = self._capture_gl(monkeypatch)
        asset.dispose(date(2026, 8, 15), Decimal('13500'), notes='buyer pickup')
        refreshed = FixedAsset.query.filter_by(id=asset.id).first()
        assert refreshed.status == 'sold'
        assert refreshed.disposal_price == Decimal('13500')
        assert refreshed.disposal_gain_loss == Decimal('3500')
        assert refreshed.disposal_date == date(2026, 8, 15)
        assert 'buyer pickup' in refreshed.notes
        lines = calls[0]['lines']
        postings = {(line['account'], float(line['debit']), float(line['credit']))
                    for line in lines}
        assert ('4500', 0.0, 3500.0) in postings
        assert ('1120', 13500.0, 0.0) in postings
        assert ('1520', 2000.0, 0.0) in postings
        assert calls[0]['reference_type'] == 'asset_disposal'
        with pytest.raises(ValueError, match='التخلص من الأصل مسبقاً'):
            asset.dispose(date(2026, 9, 1), Decimal('5'))

    def test_dispose_zero_price_scraps_at_loss(self, db, monkeypatch):
        gl = self._gl_accounts(db)
        asset = self._asset(purchase_price=Decimal('6000'), salvage_value=Decimal('0'),
                            accumulated_depreciation=Decimal('500'), useful_life_years=5,
                            depreciation_account_id=gl['dep'].id,
                            expense_account_id=gl['expense'].id,
                            asset_account_id=gl['asset'].id)
        db.session.add(asset)
        db.session.commit()
        calls = self._capture_gl(monkeypatch)
        asset.dispose(date(2026, 8, 20), Decimal('0'))
        refreshed = FixedAsset.query.filter_by(id=asset.id).first()
        assert refreshed.status == 'disposed'
        assert refreshed.disposal_gain_loss == Decimal('-5500')
        loss_lines = [ln for ln in calls[0]['lines'] if ln['account'] == '6990']
        assert loss_lines and float(loss_lines[0]['debit']) == 5500
        used_codes = [ln['account'] for ln in calls[0]['lines']]
        assert '1120' not in used_codes
        assert 'قيد إتلاف أصل' in calls[0]['description']
