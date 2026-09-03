"""Unit tests for pure-logic AI knowledge modules.

Covers combined-coverage gaps without external keys or heavy models:
security_rules (32%), beginners_mode (32%), advanced_laws (29%),
master_brain (29%), transformers_brain (32%).
"""
import math
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from ai_knowledge.security_rules import SecurityRules, security_rules
from ai_knowledge.beginners_mode import BeginnersGuide, beginners_guide
from ai_knowledge.advanced_laws import AdvancedLaws
from ai_knowledge.master_brain import (
    MasterBrain, get_master_brain, ask_azad, quick_calc, explain_concept,
)
from ai_knowledge.transformers_brain import TransformersBrain


def _anon():
    return SimpleNamespace(is_authenticated=False)


def _owner():
    return SimpleNamespace(is_authenticated=True, is_owner=True,
                           username='owner', role=None)


def _seller():
    return SimpleNamespace(is_authenticated=True, is_owner=False,
                           username='seller',
                           role=SimpleNamespace(slug='seller'))


# ── SecurityRules ─────────────────────────────────────────────────────────────

class TestSecurityRules:
    def test_is_owner_false_for_anon(self):
        with patch('ai_knowledge.security_rules.current_user', _anon()):
            assert SecurityRules.is_owner() is False

    def test_is_owner_true_for_owner(self):
        with patch('ai_knowledge.security_rules.current_user', _owner()):
            assert SecurityRules.is_owner() is True
            assert SecurityRules.can_access_sensitive_info() is True

    def test_non_owner_cannot_access_sensitive(self):
        with patch('ai_knowledge.security_rules.current_user', _seller()):
            assert SecurityRules.can_access_sensitive_info() is False

    def test_filter_passthrough_for_owner(self):
        data = {'password': 'x', 'email': 'a@b.c'}
        with patch('ai_knowledge.security_rules.current_user', _owner()):
            assert SecurityRules.filter_sensitive_data(data) == data

    def test_filter_masks_secrets(self):
        data = {'password': 'x', 'api_key': 'y', 'token': 'z',
                'secret': 's', 'key': 'k', 'name': 'n'}
        with patch('ai_knowledge.security_rules.current_user', _seller()):
            out = SecurityRules.filter_sensitive_data(data)
            for k in ['password', 'api_key', 'token', 'secret', 'key']:
                assert out[k] == '*** محمي ***'
            assert out['name'] == 'n'

    def test_filter_masks_email_phone(self):
        data = {'email': 'user@example.com', 'phone': '0501234567'}
        with patch('ai_knowledge.security_rules.current_user', _seller()):
            out = SecurityRules.filter_sensitive_data(data)
            assert out['email'] == 'user@***.***'
            assert out['phone'] == '050***67'

    def test_filter_non_dict_passthrough(self):
        with patch('ai_knowledge.security_rules.current_user', _seller()):
            assert SecurityRules.filter_sensitive_data([1, 2]) == [1, 2]

    def test_known_and_unknown_responses(self):
        assert 'كلمات المرور' in SecurityRules.get_security_response('password_request')
        assert SecurityRules.get_security_response('nope').startswith('🔒')

    def test_check_permissions_anon(self):
        with patch('ai_knowledge.security_rules.current_user', _anon()):
            ok, _ = SecurityRules.check_user_permissions('view_all')
            assert ok is False

    def test_check_permissions_by_role(self):
        with patch('ai_knowledge.security_rules.current_user', _seller()):
            assert SecurityRules.check_user_permissions('view_limited')[0] is True
            assert SecurityRules.check_user_permissions('delete_all')[0] is False
        with patch('ai_knowledge.security_rules.current_user', _owner()):
            assert SecurityRules.check_user_permissions('anything')[0] is True

    @pytest.mark.parametrize('text,expected', [
        ('', ''),
        (None, ''),
        ('hello', 'hello'),
        ('<script>alert(1)</script>', 'scriptalert1/script'),
        ('a;b|c`d$e', 'abcde'),
    ])
    def test_sanitize_input(self, text, expected):
        assert SecurityRules.sanitize_input(text) == expected

    def test_sanitize_truncates(self):
        out = SecurityRules.sanitize_input('x' * 1500)
        assert len(out) == 1003 and out.endswith('...')

    def test_log_event_prints(self, capsys):
        SecurityRules.log_security_event('test', 'details')
        assert 'SECURITY_LOG:' in capsys.readouterr().out

    def test_rate_limit_default(self):
        assert SecurityRules.rate_limit_check(1, 'x')[0] is True

    def test_singleton_instance(self):
        assert isinstance(security_rules, SecurityRules)


# ── BeginnersGuide ────────────────────────────────────────────────────────────

class TestBeginnersGuide:
    def test_known_tutorial(self):
        assert 'فاتورة' in BeginnersGuide.get_tutorial('create_invoice')

    def test_unknown_falls_back(self):
        assert BeginnersGuide.get_tutorial('nope') == \
            BeginnersGuide.get_tutorial('first_time')

    def test_suggest_next_step_chain(self):
        nxt = BeginnersGuide.suggest_next_step('first_time')
        assert nxt == BeginnersGuide.get_tutorial('create_invoice')
        assert 'محترف' in BeginnersGuide.suggest_next_step('create_report')
        assert 'محترف' in BeginnersGuide.suggest_next_step('bogus')

    @pytest.mark.parametrize('msg,topic', [
        ('كيف أعمل فاتورة؟', 'create_invoice'),
        ('add customer please', 'add_customer'),
        ('product قطع', 'add_product'),
        ('show report', 'create_report'),
        ('hello there', 'first_time'),
    ])
    def test_beginner_response_routing(self, msg, topic):
        assert BeginnersGuide.get_beginner_response(msg) == \
            BeginnersGuide.get_tutorial(topic)

    def test_singleton(self):
        assert isinstance(beginners_guide, BeginnersGuide)


# ── AdvancedLaws ──────────────────────────────────────────────────────────────

class TestAdvancedLaws:
    @pytest.mark.parametrize('country', ['palestine', 'uae', 'israel', 'france'])
    def test_tax_info_countries(self, country):
        assert isinstance(AdvancedLaws.get_tax_info(country, 'vat'), str)

    @pytest.mark.parametrize('kind', ['sea', 'air', 'land'])
    def test_shipping_info(self, kind):
        assert isinstance(AdvancedLaws.get_shipping_info(kind), str)

    def test_customs_info(self):
        assert isinstance(AdvancedLaws.get_customs_info('uae'), str)

    @pytest.mark.parametrize('cat', ['food', 'electronics'])
    def test_quality_standards(self, cat):
        assert isinstance(AdvancedLaws.get_quality_standards(cat), str)


# ── MasterBrain (pure paths) ──────────────────────────────────────────────────

@pytest.fixture(scope='module')
def brain():
    return MasterBrain()


class TestMasterBrainPure:
    def test_gross_margin(self, brain):
        r = brain.quick_calc('gross_margin', sales=1000, cogs=600)
        assert r['success'] is True and r['result'] == 40.0

    def test_zero_division_safe(self, brain):
        assert brain.quick_calc('gross_margin', sales=0, cogs=5)['result'] == 0
        assert brain.quick_calc('current_ratio', current_assets=1,
                                current_liabilities=0)['result'] == 0
        assert brain.quick_calc('break_even', fixed_costs=1, price=5,
                                variable_cost=5)['result'] == 0

    def test_vat_roundtrip(self, brain):
        assert brain.quick_calc('vat', amount=100)['result'] == 5.0
        assert brain.quick_calc('price_with_vat', amount=100)['result'] == 105.0
        assert brain.quick_calc('price_without_vat', amount_with_vat=105)['result'] == 100.0

    def test_unknown_formula(self, brain):
        r = brain.quick_calc('nope', x=1)
        assert r['success'] is False and 'Unknown formula' in r['error']

    def test_bad_params(self, brain):
        r = brain.quick_calc('gross_margin', sales=1)
        assert r['success'] is False

    def test_validate_balanced(self, brain):
        r = brain.validate_accounting_entry(100.0, 100.0)
        assert r['is_balanced'] is True and r['confidence'] == 1.0

    def test_validate_unbalanced(self, brain):
        r = brain.validate_accounting_entry(100.0, 90.0)
        assert r['is_balanced'] is False
        assert r['difference'] == pytest.approx(10.0)

    def test_explain_known_and_unknown(self, brain):
        assert isinstance(brain.explain('test'), str)
        assert 'لم أجد' in brain.explain('zzz-no-such-concept-zzz')

    def test_singleton(self):
        assert get_master_brain() is get_master_brain()

    def test_module_helpers(self, brain):
        assert quick_calc('vat', amount=10)['result'] == 0.5
        assert isinstance(explain_concept('x'), str)
        assert isinstance(ask_azad('مرحبا'), dict)


# ── TransformersBrain (tiny dims — pure math) ─────────────────────────────────

@pytest.fixture(scope='module')
def tbridge():
    return TransformersBrain(vocab_size=50, d_model=8, n_heads=2)


class TestTransformersBrain:
    def test_softmax_sums_to_one(self, tbridge):
        out = tbridge._softmax([1.0, 2.0, 3.0])
        assert sum(out) == pytest.approx(1.0)
        assert out[2] > out[1] > out[0]

    def test_dot_product(self, tbridge):
        assert tbridge._dot_product([1, 2], [3, 4]) == 11.0

    def test_positional_encoding_shape(self, tbridge):
        assert len(tbridge.positional_encoding(3, 8)) == 8

    def test_layer_norm(self, tbridge):
        out = tbridge._layer_norm([1.0, 2.0, 3.0, 4.0])
        assert sum(out) == pytest.approx(0.0, abs=1e-6)

    def test_self_attention_shape(self, tbridge):
        q = [0.1] * 8
        assert len(tbridge.self_attention(q, q, q)) == 8

    def test_feed_forward_shape(self, tbridge):
        assert len(tbridge.feed_forward([0.5] * 8)) == 8

    def test_understand_returns_dict(self, tbridge):
        res = tbridge.understand('كم سعر الفلتر؟')
        assert isinstance(res, dict) and res

    def test_context_roundtrip(self, tbridge):
        tbridge.add_to_context('hello world')
        assert '1 رسالة' in tbridge.get_context_summary()

    def test_generate_response(self, tbridge):
        assert isinstance(tbridge.generate_response('test', max_length=5), str)
