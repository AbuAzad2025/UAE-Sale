"""
Security remediation tests — Agent S wave.

Covers:
1. Telemetry opt-in inversion (no external send unless ENABLE_TELEMETRY=1).
2. CardPayment Fernet encryption, CVV non-persistence, legacy payload rejection.
3. CardVault salted (peppered) card_hash.
4. TenantScopedMixin fail-fast column check + TENANT_STRICT warning path.
5. robots.txt dynamic base_url rendering.
6. payment-vault public endpoints: WhatsApp contact de-hardcoding,
   CVV accept-and-discard, PAN stored via CardVault, 5/min rate limit.
7. purchase_detail.html template extends a valid layout.
"""

import base64
import hashlib
import json
import logging
from decimal import Decimal
from pathlib import Path

import pytest

from models import CardPayment, CardVault, Customer, SystemSettings
from models.card_payment import _get_card_payment_cipher


# ============================ 1. TELEMETRY ============================


def _clear_tel_env(monkeypatch):
    for name in ('ENABLE_TELEMETRY', 'DISABLE_TELEMETRY', 'FORM_SUBMIT_URL',
                 'FORM_SUBMIT_EMAIL', 'OWNER_EMAIL', 'COMPANY_EMAIL'):
        monkeypatch.delenv(name, raising=False)


class TestTelemetryOptIn:
    def test_start_telemetry_default_off_never_spawns_thread(self, monkeypatch):
        from utils import telemetry as tel

        _clear_tel_env(monkeypatch)
        spawned = []

        def _boom(target=None, daemon=None):
            spawned.append(target)
            raise AssertionError('thread must not be spawned in off-mode')

        monkeypatch.setattr(tel, 'Thread', _boom)
        result = tel.start_telemetry()

        assert result == {'enabled': False}
        assert spawned == []

    def test_send_heartbeat_default_off_is_pure_noop(self, tmp_path, monkeypatch):
        from utils import telemetry as tel

        _clear_tel_env(monkeypatch)
        monkeypatch.setattr(tel, 'TOKEN_FILE', str(tmp_path / '.machine_token'))
        monkeypatch.setattr(tel, 'HIDDEN_LOG_FILE', str(tmp_path / '.security_audit.log'))

        network_calls = []

        def _net(*args, **kwargs):
            network_calls.append(args)
            raise AssertionError('network access forbidden in off-mode')

        monkeypatch.setattr(tel.requests, 'post', _net)
        monkeypatch.setattr(tel.requests, 'get', _net)

        result = tel.send_heartbeat()

        assert result == {'enabled': False}
        assert network_calls == []
        assert list(tmp_path.iterdir()) == []

    def test_enable_env_turns_on_background_thread(self, monkeypatch):
        from utils import telemetry as tel

        _clear_tel_env(monkeypatch)
        monkeypatch.setenv('ENABLE_TELEMETRY', '1')

        started = {}

        class FakeThread:
            def __init__(self, target=None, daemon=None):
                started['target'] = target
                self.daemon = daemon

            def start(self):
                started['launched'] = True
                started['daemon'] = self.daemon

        monkeypatch.setattr(tel, 'Thread', FakeThread)
        result = tel.start_telemetry()

        assert result == {'enabled': True}
        assert started['launched'] is True
        assert started['daemon'] is True
        assert started['target'] is tel.send_heartbeat

    def test_disable_telemetry_beats_enable(self, monkeypatch):
        from utils import telemetry as tel

        _clear_tel_env(monkeypatch)
        monkeypatch.setenv('ENABLE_TELEMETRY', '1')
        monkeypatch.setenv('DISABLE_TELEMETRY', '1')

        assert tel.is_telemetry_enabled() is False
        assert tel.start_telemetry() == {'enabled': False}

    @pytest.mark.parametrize('env,expected', [
        ({}, False),
        ({'ENABLE_TELEMETRY': '1'}, True),
        ({'ENABLE_TELEMETRY': ' true '}, False),
        ({'ENABLE_TELEMETRY': '0'}, False),
        ({'ENABLE_TELEMETRY': '1', 'DISABLE_TELEMETRY': '0'}, False),
    ])
    def test_is_telemetry_enabled_env_matrix(self, monkeypatch, env, expected):
        from utils import telemetry as tel

        _clear_tel_env(monkeypatch)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        assert tel.is_telemetry_enabled() is expected

    def test_enabled_heartbeat_sends_marks_token_and_reports(self, tmp_path, monkeypatch):
        from utils import telemetry as tel

        _clear_tel_env(monkeypatch)
        monkeypatch.setenv('ENABLE_TELEMETRY', '1')
        monkeypatch.setattr(tel, 'TOKEN_FILE', str(tmp_path / '.machine_token'))
        monkeypatch.setattr(tel, 'HIDDEN_LOG_FILE', str(tmp_path / '.security_audit.log'))
        monkeypatch.setattr(tel, 'get_machine_signature', lambda: 'sig-opt-in')
        monkeypatch.setattr(tel, 'collect_system_info', lambda: {
            'timestamp': '2026-08-26T00:00:00', 'hostname': 'box-1',
            'os': 'Windows', 'os_release': '11', 'machine': 'AMD64',
            'processor': 'CPU', 'python_version': '3.14', 'public_ip': '203.0.113.2',
        })
        submitted = []
        monkeypatch.setattr(
            tel, 'send_formsubmit',
            lambda subject, fields, to_email=None: submitted.append(fields) or True,
        )

        result = tel.send_heartbeat()

        assert result['enabled'] is True
        assert result['sent'] is True
        assert len(submitted) == 1
        assert (tmp_path / '.machine_token').read_text(encoding='utf-8') == 'sig-opt-in'


# ============================ 2. CARD PAYMENT ============================


LEGACY_PAN = '4111111111111111'
LEGACY_CVV = '123'


def _card(**kw):
    defaults = dict(customer_name='Ali Hassan', transaction_type='purchase',
                    amount=Decimal('50.00'))
    defaults.update(kw)
    return CardPayment(**defaults)


class TestCardPaymentFernet:
    def test_encrypt_never_stores_cvv_or_raw_pan(self, db, app):
        cp = _card()
        assert cp.encrypt_card_data(LEGACY_PAN, LEGACY_CVV, '12/27') is True
        assert cp.card_last_4 == '1111'
        blob = cp.encrypted_data
        assert LEGACY_CVV not in blob
        assert LEGACY_PAN not in blob
        payload = cp.decrypt_card_data()
        assert 'cvv' not in payload
        assert payload['card_number'] == '****1111'

    def test_legacy_insecure_payload_rejected(self, db, app):
        legacy_blob = base64.b64encode(json.dumps({
            'card_number': LEGACY_PAN,
            'cvv': LEGACY_CVV,
            'expiry': '12/27',
        }).encode('utf-8')).decode('ascii')
        cp = _card()
        cp.card_type = 'Visa'
        cp.encrypted_data = legacy_blob

        with pytest.raises(ValueError, match='legacy insecure payload rejected'):
            cp.decrypt_card_data()

    def test_fernet_roundtrip_keeps_shape_and_expiry(self, db, app):
        cp = _card()
        assert cp.encrypt_card_data(LEGACY_PAN, LEGACY_CVV, '12/27') is True
        data = cp.decrypt_card_data()
        assert set(data.keys()) == {'card_number', 'expiry', 'display'}
        assert data['expiry'] == '12/27'
        assert data['display'] == 'Visa ****1111'

    def test_stored_token_hash_matches_pan_not_reversed(self, db, app):
        cp = _card()
        cp.encrypt_card_data(LEGACY_PAN, LEGACY_CVV, '12/27')
        cipher = _get_card_payment_cipher()
        inner = json.loads(cipher.decrypt(cp.encrypted_data.encode('ascii')).decode('utf-8'))
        assert inner['masked_pan'] == '****1111'
        assert inner['token_hash'] == CardPayment._token_hash(LEGACY_PAN)
        assert LEGACY_CVV not in json.dumps(inner)

    def test_empty_and_corrupt_payload_behaviour(self, db, app):
        cp = _card()
        assert cp.decrypt_card_data() is None
        cp.encrypted_data = '%%%'
        assert cp.decrypt_card_data() is None

    def test_invalid_input_returns_false_without_side_effects(self, db, app):
        cp = _card()
        assert cp.encrypt_card_data(None, LEGACY_CVV, '12/27') is False
        assert cp.card_type is None
        assert cp.card_last_4 is None
        assert cp.encrypted_data is None

    def test_token_hash_deterministic(self):
        assert CardPayment._token_hash(LEGACY_PAN) == CardPayment._token_hash('4111 1111 1111 1111')
        assert CardPayment._token_hash(LEGACY_PAN) != hashlib.sha256(LEGACY_PAN.encode()).hexdigest()


# ============================ 3. CARD VAULT PEPPER ============================


class TestCardVaultSaltedHash:
    def test_hash_card_is_peppered_with_secret_key(self, db, app):
        pepper = hashlib.sha256(app.config['SECRET_KEY'].encode('utf-8')).hexdigest()[:32]
        expected = hashlib.sha256(('4539148803436467' + pepper).encode('utf-8')).hexdigest()
        assert CardVault._hash_card('4539148803436467') == expected
        # Must differ from the old unsalted scheme
        assert expected != hashlib.sha256(b'4539148803436467').hexdigest()

    def test_hash_card_fallback_pepper_without_secret_key(self, db, app, monkeypatch):
        monkeypatch.delitem(app.config, 'SECRET_KEY', raising=False)
        pepper = hashlib.sha256(b'qmr-pepper').hexdigest()[:32]
        expected = hashlib.sha256(('4539148803436467' + pepper).encode('utf-8')).hexdigest()
        assert CardVault._hash_card(4539148803436467) == expected

    def test_set_card_data_writes_peppered_hash(self, db, app, test_customer, monkeypatch):
        monkeypatch.setitem(app.config, 'CARD_ENCRYPTION_KEY', 'sec-key-x')
        vault = CardVault(customer_id=test_customer.id)
        vault.set_card_data('4539148803436467', 'John Doe')
        assert vault.card_hash == CardVault._hash_card('4539148803436467')


# ============================ 4. TENANT SCOPE ============================


class TestTenantScopeFailFastAndStrict:
    def test_subclass_without_tenant_id_raises_runtimeerror_at_import(self):
        from models.tenant_scope import TenantScopedMixin

        with pytest.raises(RuntimeError, match='tenant_id'):
            class Broken(TenantScopedMixin):
                pass

    def test_subclass_with_own_tenant_id_column_accepted(self, db):
        from models.tenant_scope import TenantScopedMixin

        class ProperlyScoped(TenantScopedMixin):
            tenant_id = db.Column(db.Integer)

        assert 'tenant_id' in vars(ProperlyScoped)

    def test_core_scoped_registry_unchanged(self):
        from models import Sale, Customer, Product  # noqa: F401 — import-time check
        from models.tenant_scope import _tenant_scoped_tables

        expected = {
            'sales', 'sale_lines', 'purchases', 'purchase_lines',
            'payments', 'receipts', 'customers', 'suppliers',
            'products', 'stock_movements', 'cheques', 'gl_journal_entries',
            'warehouses',
        }
        assert expected == _tenant_scoped_tables

    @pytest.mark.usefixtures('db')
    def test_strict_mode_warns_on_unfiltered_registered_query(self, app, caplog):
        from models import set_current_tenant_id

        app.config['TENANT_STRICT'] = True
        try:
            set_current_tenant_id(None)
            with caplog.at_level(logging.WARNING, logger='models.tenant_scope'):
                Customer.query.all()
        finally:
            app.config.pop('TENANT_STRICT', None)
            set_current_tenant_id(None)

        messages = [r.getMessage() for r in caplog.records]
        assert any('TENANT_STRICT: unfiltered access to customers' in m for m in messages)

    @pytest.mark.usefixtures('db')
    def test_no_strict_warning_by_default(self, app, caplog):
        from models import set_current_tenant_id

        app.config.pop('TENANT_STRICT', None)
        set_current_tenant_id(None)
        with caplog.at_level(logging.WARNING, logger='models.tenant_scope'):
            Customer.query.all()

        assert not [r for r in caplog.records if 'TENANT_STRICT' in r.getMessage()]

    def test_strict_mode_preserves_default_filtering(self, app, db, caplog):
        from models import set_current_tenant_id
        from models.tenant import Tenant

        tenant_a = Tenant(name='A', name_ar='أ', slug='strict-a', is_active=True)
        tenant_b = Tenant(name='B', name_ar='ب', slug='strict-b', is_active=True)
        db.session.add_all([tenant_a, tenant_b])
        db.session.commit()
        mine = Customer(tenant_id=tenant_a.id, name='Mine', customer_type='regular')
        theirs = Customer(tenant_id=tenant_b.id, name='Theirs', customer_type='regular')
        db.session.add_all([mine, theirs])
        db.session.commit()

        app.config['TENANT_STRICT'] = True
        try:
            set_current_tenant_id(tenant_a.id)
            with caplog.at_level(logging.WARNING, logger='models.tenant_scope'):
                rows = Customer.query.filter_by(customer_type='regular').all()
            assert sorted(c.name for c in rows) == ['Mine']
            assert not [r for r in caplog.records if 'TENANT_STRICT' in r.getMessage()]
        finally:
            app.config.pop('TENANT_STRICT', None)
            set_current_tenant_id(None)


# ============================ 5. ROBOTS.TXT ============================


class TestRobotsTxt:
    def test_robots_sitemap_uses_request_url_root(self, client):
        resp = client.get('/robots.txt')
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        base_url = resp.request.url_root.rstrip('/')
        assert base_url
        assert f'Sitemap: {base_url}/sitemap.xml' in body
        assert '{base_url}' not in body

    def test_robots_rules_intact(self, client):
        resp = client.get('/robots.txt')
        body = resp.get_data(as_text=True)
        assert 'Disallow: /owner/' in body
        assert 'User-agent: *' in body
        assert resp.mimetype == 'text/plain'


# ============================ 6. PAYMENT VAULT PUBLIC ROUTES ============================


CARD_PAYLOAD = {
    'payment_method': 'card',
    'amount': 25,
    'card_number': '4111111111111111',
    'cvv': '999',
    'expiry': '11/28',
    'customer_name': 'Web Buyer',
    'customer_email': 'buyer@example.com',
}


@pytest.fixture
def card_post(client):
    def _post(payload=None):
        return client.post(
            '/payment-vault/process-payment',
            json=payload if payload is not None else dict(CARD_PAYLOAD),
        )
    return _post


class TestProcessPaymentPublicEndpoint:
    def test_card_flow_success_and_contact_from_config(self, client, card_post, app):
        monkey_phone = '+970599000111'
        app.config['COMPANY_PHONE'] = monkey_phone
        resp = card_post()
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['whatsapp'] == monkey_phone

    def test_hardcoded_phone_removed_from_response(self, client, card_post, app, db):
        settings = SystemSettings.query.filter_by(is_active=True).first()
        if settings is None:
            settings = SystemSettings()
            db.session.add(settings)
            db.session.commit()
        settings.set_custom_setting('contact_whatsapp', '0999888777')
        db.session.commit()

        app.config['COMPANY_PHONE'] = '0598953362'
        body = card_post().get_json()
        assert body['whatsapp'] == '0999888777'

    def test_cvv_discarded_from_every_store(self, client, card_post):
        resp = card_post()
        assert resp.status_code == 200

        payment = CardPayment.query.order_by(CardPayment.id.desc()).first()
        assert payment is not None
        assert '999' not in (payment.encrypted_data or '')
        decrypted = payment.decrypt_card_data()
        assert 'cvv' not in decrypted
        assert '999' not in json.dumps(decrypted)

        vault_row = CardVault.query.order_by(CardVault.id.desc()).first()
        assert vault_row is not None
        assert vault_row.cvv_encrypted is None
        if vault_row.card_number_encrypted:
            assert b'999' not in bytes(vault_row.card_number_encrypted)

    def test_pan_stored_via_cardvault_only_masked_display(self, client, card_post, app):
        app.config.pop('ALLOW_CARD_DECRYPTION', None)
        assert card_post().status_code == 200

        vault_row = CardVault.query.order_by(CardVault.id.desc()).first()
        assert vault_row is not None
        assert vault_row.last_four == '1111'
        assert vault_row.card_type == 'visa'
        assert vault_row.get_card_number() == '****-****-****-1111'

        payment = CardPayment.query.order_by(CardPayment.id.desc()).first()
        assert payment.card_last_4 == '1111'
        assert LEGACY_PAN not in (payment.encrypted_data or '')

    def test_unique_transaction_ids_for_rapid_posts(self, client, card_post):
        first = card_post().get_json()['transaction_id']
        second = card_post().get_json()['transaction_id']
        assert first != second

    def test_public_posts_rate_limited_five_per_minute(self, app):
        """The three public POST endpoints carry an explicit 5/minute limit.

        (Runtime 429 enforcement is flask-limiter's own contract; the suite
        boots the limiter disabled, so we assert the registered limit config.)
        """
        from extensions import limiter

        public_post_endpoints = {
            'payment_vault.process_payment',
            'payment_vault.api_create_purchase',
            'payment_vault.api_create_donation',
        }
        assert set(app.view_functions) >= public_post_endpoints

        for endpoint in sorted(public_post_endpoints):
            view_func = app.view_functions[endpoint]
            name = f'{view_func.__module__}.{view_func.__qualname__}.{view_func.__name__}'
            decorated = limiter.limit_manager.decorated_limits(name)
            configured = [(rl.limit.amount, rl.limit.get_expiry()) for rl in decorated]
            assert (5, 60) in configured, (
                f'{endpoint} is not rate limited to 5 per minute: {configured}'
            )


# ============================ 7. TEMPLATE ============================


class TestPurchaseDetailTemplate:
    def test_extends_base_layout_with_existing_blocks(self):
        base_dir = Path(__file__).resolve().parents[2] / 'templates'
        template = (base_dir / 'payment_vault' / 'purchase_detail.html').read_text(encoding='utf-8')
        base = (base_dir / 'base.html').read_text(encoding='utf-8')

        assert '{% extends "base.html" %}' in template
        assert 'layout.html' not in template

        # blocks this template overrides must exist in base.html
        for block in ('title', 'content'):
            assert f'{{% block {block} %}}' in base, f'base.html lacks block {block}'
            assert '{% endblock %}' in template

    def test_template_has_no_hardcoded_whatsapp_number(self):
        base_dir = Path(__file__).resolve().parents[2] / 'templates'
        template = (base_dir / 'payment_vault' / 'purchase_detail.html').read_text(encoding='utf-8')
        assert '0598953362' not in template
        assert '970598953362' not in template
        assert 'config.COMPANY_PHONE' in template
