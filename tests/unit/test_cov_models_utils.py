"""Coverage: card/payment vault gating, total-safe decimals, cache
invalidation, upload gate, money/badge filters, security headers, form
contracts, CSRF/API-key pins, secret redaction, load_user guard.

NEW FILE ONLY (mission rule): no existing test file was touched.
"""
import logging
from decimal import Decimal

import flask_login
import pytest


# ---------------------------------------------------------------------------
# CardVault: owner gate on holder/expiry + to_dict PII exclusion
# ---------------------------------------------------------------------------

class TestCardVaultOwnerGating:
    def _vault(self, db, app, test_customer, monkeypatch, key='cov-key-1'):
        from models import CardVault
        monkeypatch.setitem(app.config, 'CARD_ENCRYPTION_KEY', key)
        vault = CardVault(customer_id=test_customer.id)
        vault.set_card_data('4539148803436467', 'John Doe', '12', '2027', cvv='123')
        db.session.add(vault)
        db.session.commit()
        return vault

    def test_non_owner_gets_masks(self, db, app, seller_user, test_customer, monkeypatch):
        monkeypatch.setattr(flask_login, 'current_user', seller_user)
        vault = self._vault(db, app, test_customer, monkeypatch)
        assert vault.get_cardholder_name() == '***'
        assert vault.get_expiry() == '**/**'
        assert vault.get_cvv() == '***'

    def test_owner_sees_plain_values(self, db, app, owner_user, test_customer, monkeypatch):
        monkeypatch.setattr(flask_login, 'current_user', owner_user)
        monkeypatch.setitem(app.config, 'ALLOW_CARD_DECRYPTION', True)
        vault = self._vault(db, app, test_customer, monkeypatch, key='cov-key-2')
        assert vault.get_cardholder_name() == 'John Doe'
        assert vault.get_expiry() == '12/2027'

    def test_system_context_keeps_legacy_read(self, db, app, test_customer, monkeypatch):
        # Anonymous/system context (background jobs, CLI): no authenticated
        # non-owner session exists, so getters keep the legacy fail-open read.
        # The serialization leak is closed separately via to_dict() below.
        vault = self._vault(db, app, test_customer, monkeypatch, key='cov-key-3')
        assert vault.get_cardholder_name() == 'John Doe'
        assert vault.get_expiry() == '12/2027'

    def test_to_dict_default_excludes_pii(self, db, app, seller_user, test_customer, monkeypatch):
        monkeypatch.setattr(flask_login, 'current_user', seller_user)
        vault = self._vault(db, app, test_customer, monkeypatch, key='cov-key-4')
        data = vault.to_dict()
        assert 'cardholder_name' not in data
        assert 'expiry' not in data
        assert 'card_number' not in data
        assert 'cvv' not in data
        assert data['last_four'] == '6467'

    def test_to_dict_sensitive_owner_and_seller(self, db, app, owner_user, seller_user,
                                                test_customer, monkeypatch):
        monkeypatch.setitem(app.config, 'ALLOW_CARD_DECRYPTION', True)
        monkeypatch.setattr(flask_login, 'current_user', owner_user)
        vault = self._vault(db, app, test_customer, monkeypatch, key='cov-key-5')
        owner_data = vault.to_dict(include_sensitive=True)
        assert owner_data['cardholder_name'] == 'John Doe'
        assert owner_data['expiry'] == '12/2027'
        assert owner_data['card_number'] == '4539-1488-0343-6467'
        assert owner_data['cvv'] == '123'

        monkeypatch.setattr(flask_login, 'current_user', seller_user)
        seller_data = vault.to_dict(include_sensitive=True)
        assert seller_data['cardholder_name'] == '***'
        assert 'card_number' not in seller_data
        assert 'cvv' not in seller_data


# ---------------------------------------------------------------------------
# PaymentVault: max_failed_attempts lockout enforced in unlock_vault
# ---------------------------------------------------------------------------

class TestPaymentVaultLockout:
    def _vault(self, db):
        from extensions import db as _db
        from models.payment_vault import PaymentVault
        vault = PaymentVault()
        vault.set_vault_password('VaultPass123!')
        vault.max_failed_attempts = 3
        vault.failed_attempts = 0
        vault.is_locked = True
        _db.session.add(vault)
        _db.session.commit()
        return vault

    def test_lockout_blocks_even_correct_password(self, db):
        vault = self._vault(db)
        assert vault.unlock_vault('wrong-1') is False
        assert vault.unlock_vault('wrong-2') is False
        assert vault.unlock_vault('wrong-3') is False
        assert vault.is_locked_out() is True
        # Correct password is now blocked; counter keeps incrementing.
        assert vault.unlock_vault('VaultPass123!') is False
        assert vault.failed_attempts == 4
        assert vault.is_locked is True

    def test_success_resets_counter(self, db):
        vault = self._vault(db)
        assert vault.unlock_vault('wrong') is False
        assert vault.failed_attempts == 1
        assert vault.unlock_vault('VaultPass123!') is True
        assert vault.failed_attempts == 0
        assert vault.is_locked is False


# ---------------------------------------------------------------------------
# balance_checker.to_decimal: total-safe (0 on garbage, never raises)
# ---------------------------------------------------------------------------

class TestTotalSafeToDecimal:
    def test_garbage_coerces_to_zero(self):
        from utils.balance_checker import to_decimal
        assert to_decimal(None) == Decimal('0')
        assert to_decimal('') == Decimal('0')
        assert to_decimal('abc') == Decimal('0')
        assert to_decimal('12.34.56') == Decimal('0')
        assert to_decimal(float('nan')) == Decimal('0')
        assert to_decimal(float('inf')) == Decimal('0')
        assert to_decimal('Infinity') == Decimal('0')
        assert to_decimal(object()) == Decimal('0')

    def test_valid_values_preserved(self):
        from utils.balance_checker import to_decimal
        assert to_decimal('10.5') == Decimal('10.5')
        assert to_decimal(5) == Decimal('5')
        assert to_decimal(Decimal('7.25')) == Decimal('7.25')
        assert to_decimal('1,234.56') == Decimal('1234.56')
        assert to_decimal(0) == Decimal('0')


# ---------------------------------------------------------------------------
# invalidate_cache: real prefix/pattern invalidation (was literal-only)
# ---------------------------------------------------------------------------

class TestInvalidateCache:
    def test_prefix_invalidation_is_real(self, app):
        from extensions import cache
        from utils.cache_decorators import cached_query, invalidate_cache
        calls = []
        with app.app_context():
            @cached_query(timeout=60, key_prefix='covprefixA')
            def _expensive(x):
                calls.append(x)
                return len(calls)

            try:
                assert _expensive(1) == 1
                assert _expensive(1) == 1  # served from cache
                invalidate_cache('covprefixA')
                assert _expensive(1) == 2  # recomputed after invalidation
            finally:
                invalidate_cache('covprefixA')

    def test_unrelated_prefix_survives(self, app):
        from utils.cache_decorators import cached_query, invalidate_cache
        calls_a, calls_b = [], []
        with app.app_context():
            @cached_query(timeout=60, key_prefix='covprefixB')
            def _fn_a(x):
                calls_a.append(x)
                return len(calls_a)

            @cached_query(timeout=60, key_prefix='covprefixC')
            def _fn_b(x):
                calls_b.append(x)
                return len(calls_b)

            try:
                assert (_fn_a(1), _fn_b(1)) == (1, 1)
                invalidate_cache('covprefixB')
                assert _fn_a(1) == 2  # invalidated
                assert _fn_b(1) == 1  # untouched
            finally:
                invalidate_cache('covprefixB')
                invalidate_cache('covprefixC')

    def test_glob_pattern_supported(self, app):
        from utils.cache_decorators import cached_query, invalidate_cache
        calls = []
        with app.app_context():
            @cached_query(timeout=60, key_prefix='covprefixD')
            def _fn(x):
                calls.append(x)
                return len(calls)

            try:
                assert _fn(1) == 1
                invalidate_cache('covprefix*')
                assert _fn(1) == 2
            finally:
                invalidate_cache('covprefixD')


# ---------------------------------------------------------------------------
# Upload gate: config-honoring cap + double-extension + polyglot rejection
# ---------------------------------------------------------------------------

class FakeUpload:
    def __init__(self, filename, content=b'data', size=None):
        self.filename = filename
        self.content = content
        self.size = len(content) if size is None else size
        self.saved_to = None

    def seek(self, offset, whence=0):
        self.pos = offset

    def tell(self):
        return self.size

    def read(self, n=-1):
        return self.content if n < 0 else self.content[:n]

    def save(self, dst):
        self.saved_to = dst
        with open(dst, 'wb') as fh:
            fh.write(self.content)


class TestUploadGate:
    def test_double_extension_rejected(self, app):
        from utils.helpers import allowed_file, save_uploaded_file
        assert allowed_file('invoice.php.jpg', {'.jpg'}) is False
        assert allowed_file('report.pdf', {'.pdf'}) is True
        assert allowed_file('my.report.pdf', {'.pdf'}) is True
        with pytest.raises(ValueError, match='not allowed'):
            save_uploaded_file(FakeUpload('invoice.php.jpg'), 'up', {'.jpg'})
        with pytest.raises(ValueError, match='not allowed'):
            save_uploaded_file(FakeUpload('shell.sh.png'), 'up', {'.png'})

    def test_polyglot_script_rejected(self, app, tmp_path, monkeypatch):
        from utils.helpers import save_uploaded_file
        monkeypatch.setattr(app, 'static_folder', str(tmp_path))
        with app.app_context():
            with pytest.raises(ValueError, match='Executable'):
                save_uploaded_file(
                    FakeUpload('img.png', content=b'\x89PNG\r\n\x1a\n<?php echo 1;'),
                    'up', {'.png'})
            with pytest.raises(ValueError, match='Executable'):
                save_uploaded_file(
                    FakeUpload('img.png', content=b'GIF89a<script>alert(1)</script>'),
                    'up', {'.png'})
            with pytest.raises(ValueError, match='Executable'):
                save_uploaded_file(
                    FakeUpload('run.png', content=b'#!/bin/sh\nid'),
                    'up', {'.png'})

    def test_stricter_config_cap_is_honored(self, app, monkeypatch):
        from utils.helpers import save_uploaded_file
        monkeypatch.setitem(app.config, 'MAX_CONTENT_LENGTH', 1 * 1024 * 1024)
        with app.app_context():
            with pytest.raises(ValueError, match=r'size.*\(1MB\)'):
                save_uploaded_file(
                    FakeUpload('a.png', size=2 * 1024 * 1024), 'up', {'.png'})

    def test_effective_cap_is_stricter_of_config_and_policy(self, app):
        # Default config is 16MB but the 5MB app-level policy still wins, so
        # the pre-existing 6MB rejection stands.
        from utils.helpers import save_uploaded_file
        assert app.config.get('MAX_CONTENT_LENGTH', 0) > 5 * 1024 * 1024
        with app.app_context():
            with pytest.raises(ValueError, match=r'size.*\(5MB\)'):
                save_uploaded_file(
                    FakeUpload('big.png', size=6 * 1024 * 1024), 'up', {'.png'})

    def test_clean_upload_still_succeeds(self, app, tmp_path, monkeypatch):
        from utils.helpers import save_uploaded_file
        with app.app_context():
            monkeypatch.setattr(app, 'static_folder', str(tmp_path))
            payload = b'\x89PNG\r\n\x1a\n' + b'x' * 64
            result = save_uploaded_file(
                FakeUpload('receipt.png', content=payload), 'cov_up', {'.png'})
            assert result.startswith('cov_up/')
            assert result.endswith('.png')


# ---------------------------------------------------------------------------
# Money filters + security headers (TESTS ONLY — no app.py changes)
# ---------------------------------------------------------------------------

class TestMoneyFilters:
    def test_rounding_half_up(self):
        from app import _format_money
        assert '2.35' in _format_money('2.345')
        assert '2.34' in _format_money('2.344')
        assert '10.50' in _format_money(Decimal('10.5'))
        assert '1,000.00' in _format_money(1000)

    def test_none_and_garbage_passthrough(self):
        from app import _format_money
        assert _format_money(None) == ''
        assert _format_money('abc') == 'abc'

    def test_badge_escapes_xss(self):
        from app import _status_badge
        payload = '<script>alert(1)</script>'
        html = str(_status_badge(payload))
        assert '<script>' not in html
        assert '&lt;script&gt;' in html
        assert 'badge-secondary' in html

    def test_badge_known_status(self):
        from app import _status_badge
        html = str(_status_badge('paid'))
        assert 'badge-success' in html


class TestSecurityHeaders:
    def test_csp_and_hardening_headers_present(self, client):
        resp = client.get('/auth/login')
        assert resp.status_code == 200
        assert "default-src 'self'" in resp.headers.get('Content-Security-Policy', '')
        assert resp.headers.get('X-Content-Type-Options') == 'nosniff'
        assert resp.headers.get('X-Frame-Options') == 'SAMEORIGIN'
        assert 'Referrer-Policy' in resp.headers

    def test_hsts_only_outside_debug(self, app, client, monkeypatch):
        monkeypatch.setitem(app.config, 'DEBUG', False)
        resp = client.get('/auth/login')
        assert 'max-age=31536000' in resp.headers.get('Strict-Transport-Security', '')
        monkeypatch.setitem(app.config, 'DEBUG', True)
        resp = client.get('/auth/login')
        assert 'Strict-Transport-Security' not in resp.headers


# ---------------------------------------------------------------------------
# Form validation contracts (TESTS ONLY)
# ---------------------------------------------------------------------------

def _validate_form(app, cls, mapping, choice_overrides=None):
    from werkzeug.datastructures import ImmutableMultiDict
    with app.test_request_context('/'):
        form = cls(formdata=ImmutableMultiDict(mapping))
        if choice_overrides:
            for name, choices in choice_overrides.items():
                getattr(form, name).choices = choices
        return form.validate(), form


class TestFormContracts:
    def test_login_form(self, app):
        from forms import LoginForm
        ok, _ = _validate_form(app, LoginForm, {'username': 'ahmad', 'password': 's3cret!'})
        assert ok is True
        ok, form = _validate_form(app, LoginForm, {'username': 'ab', 'password': 's3cret!'})
        assert ok is False and 'username' in form.errors
        ok, form = _validate_form(app, LoginForm, {'username': 'ahmad'})
        assert ok is False and 'password' in form.errors

    def test_customer_form(self, app):
        from forms import CustomerForm
        ok, form = _validate_form(app, CustomerForm, {'customer_type': 'regular'})
        assert ok is False and 'name' in form.errors
        ok, form = _validate_form(
            app, CustomerForm,
            {'name': 'Acme', 'customer_type': 'regular', 'email': 'not-an-email'})
        assert ok is False and 'email' in form.errors
        ok, form = _validate_form(
            app, CustomerForm,
            {'name': 'Acme', 'customer_type': 'merchant', 'email': 'a@b.com',
             'is_active': '1', 'preferred_currency': 'AED'})
        assert ok is True, form.errors

    def test_product_form(self, app):
        from forms import ProductForm
        choices = {'category_id': [(1, 'Cat')]}
        ok, form = _validate_form(
            app, ProductForm, {'regular_price': '100', 'category_id': '1'}, choices)
        assert ok is False and 'name' in form.errors
        ok, form = _validate_form(
            app, ProductForm, {'name': 'Pad', 'regular_price': '-5', 'category_id': '1'},
            choices)
        assert ok is False and 'regular_price' in form.errors
        ok, form = _validate_form(
            app, ProductForm, {'name': 'Pad', 'regular_price': '100', 'category_id': '1'},
            choices)
        assert ok is True, form.errors

    def test_receipt_form(self, app):
        from forms import ReceiptForm
        choices = {'customer_id': [(7, 'C')]}
        ok, form = _validate_form(
            app, ReceiptForm,
            {'customer_id': '7', 'amount': '50', 'currency': 'AED',
             'payment_method': 'cash'}, choices)
        assert ok is True, form.errors
        ok, form = _validate_form(
            app, ReceiptForm,
            {'customer_id': '7', 'currency': 'AED', 'payment_method': 'cash'}, choices)
        assert ok is False and 'amount' in form.errors
        ok, form = _validate_form(
            app, ReceiptForm,
            {'customer_id': '7', 'amount': '0', 'currency': 'AED',
             'payment_method': 'cash'}, choices)
        assert ok is False and 'amount' in form.errors

    def test_purchase_form(self, app):
        from forms import PurchaseForm
        ok, _ = _validate_form(
            app, PurchaseForm, {'supplier_name': 'S', 'currency': 'AED'})
        assert ok is True
        ok, form = _validate_form(app, PurchaseForm, {'currency': 'AED'})
        assert ok is False and 'supplier_name' in form.errors
        ok, form = _validate_form(
            app, PurchaseForm, {'supplier_name': 'S', 'currency': 'XXX'})
        assert ok is False and 'currency' in form.errors
        ok, form = _validate_form(
            app, PurchaseForm,
            {'supplier_name': 'S', 'currency': 'AED', 'supplier_email': 'bad'})
        assert ok is False and 'supplier_email' in form.errors


# ---------------------------------------------------------------------------
# INTERNAL_API_KEY + CSRF exempt list + WTF_CSRF (TESTS ONLY — pin behavior)
# ---------------------------------------------------------------------------

class TestInternalApiKeyAndCsrf:
    def test_internal_api_key_defaults_empty(self, app):
        assert app.config.get('INTERNAL_API_KEY', '') == ''

    def test_key_gate_allows_match_and_blocks_mismatch(self, app, monkeypatch):
        from routes.ai import _validate_csrf_token
        monkeypatch.setitem(app.config, 'INTERNAL_API_KEY', 'cov-secret-key-123')
        with app.test_request_context(
                '/ai/chat', method='POST', headers={'X-API-Key': 'cov-secret-key-123'}):
            assert _validate_csrf_token() is True
        with app.test_request_context(
                '/ai/chat?api_key=cov-secret-key-123', method='POST'):
            assert _validate_csrf_token() is True
        with app.test_request_context(
                '/ai/chat', method='POST', headers={'X-API-Key': 'wrong-key'}):
            assert _validate_csrf_token() is False
        with app.test_request_context('/ai/chat', method='POST'):
            assert _validate_csrf_token() is False
        with app.test_request_context('/ai/chat', method='GET'):
            assert _validate_csrf_token() is True

    def test_csrf_exempt_list_pins_calculators(self, app):
        exempt = app.config.get('WTF_CSRF_EXEMPT_LIST', [])
        assert '/sales/api/calculate-totals' in exempt
        assert '/purchases/api/calculate-totals' in exempt
        assert '/ledger/api/calculate-journal-balance' in exempt

    def test_exempt_calculator_works_without_csrf_token(self, client, login_owner):
        resp = client.post('/sales/api/calculate-totals', json={
            'lines': [{'quantity': 2, 'unit_price': 50, 'discount_percent': 0}],
            'discount_amount': 0, 'shipping_cost': 0, 'tax_rate': 0,
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['subtotal'] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# SanitizeFilter + error-handler secrecy (TESTS ONLY — prove no secret leaks)
# ---------------------------------------------------------------------------

class TestSecretRedaction:
    def test_production_handlers_carry_sanitize_filter(self, app):
        from utils.log_sanitizer import SanitizeFilter
        wired = list(logging.getLogger().handlers) + list(app.logger.handlers)
        assert wired, 'expected logging handlers to be configured'
        assert any(
            any(isinstance(f, SanitizeFilter) for f in h.filters) for h in wired
        ), 'SanitizeFilter missing from logging pipeline'

    def test_error_record_with_secrets_is_redacted(self):
        from utils.log_sanitizer import REDACTED, SanitizeFilter
        record = logging.LogRecord(
            'utils.error_handlers', logging.ERROR, __file__, 1,
            'Internal Server Error: password=hunter2 api_key=ABCDEFGH1234567890XYZ',
            None, None)
        assert SanitizeFilter().filter(record) is True
        assert 'hunter2' not in record.msg
        assert 'ABCDEFGH1234567890XYZ' not in record.msg
        assert REDACTED in record.msg

    def test_500_page_never_echoes_secret(self, app):
        # Deterministic: dispatch an InternalServerError through the
        # registered 500 handler (no route registration, so no
        # order-dependence on the shared session app).
        from werkzeug.exceptions import InternalServerError
        secret = 'cov-hunter2-page-secret'
        with app.test_request_context('/some-page'):
            resp = app.handle_user_exception(
                InternalServerError(f'boom password={secret}'))
        assert resp[1] == 500
        assert secret not in resp[0].get_data(as_text=True)


# ---------------------------------------------------------------------------
# load_user tampered-session guard (extensions.load_user)
# ---------------------------------------------------------------------------

class TestLoadUserGuard:
    def test_garbage_session_id_returns_none(self, db):
        from extensions import load_user
        assert load_user('not-an-int') is None
        assert load_user('12.5') is None
        assert load_user('') is None
        assert load_user(None) is None
        assert load_user('-3') is None
        assert load_user('0') is None
        assert load_user('999999999') is None

    def test_valid_user_roundtrip(self, db, owner_user):
        from extensions import load_user
        assert load_user(str(owner_user.id)).id == owner_user.id
        assert load_user(owner_user.id).id == owner_user.id
