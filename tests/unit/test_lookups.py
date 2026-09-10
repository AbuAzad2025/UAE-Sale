"""Unit tests for the unified system-constants layer.

Covers: registry integrity, LookupService merge/add/disable/label rules
(incl. locked-group guards), owner UI access + flows, and end-to-end
wiring (service override appears in a rendered form).
"""
import pytest

from utils import constants as C
from services import lookup_service as LS
from extensions import db as _db


class TestRegistryIntegrity:
    def test_every_group_source_exists(self):
        for key, meta in C.LOOKUP_GROUPS.items():
            assert hasattr(C, meta['source']), f"{key} -> missing {meta['source']}"
            assert meta.get('title_ar'), f"{key} missing title"

    def test_codes_unique_within_group(self):
        for key, meta in C.LOOKUP_GROUPS.items():
            codes = [c for c, _ in getattr(C, meta['source'])]
            assert len(codes) == len(set(codes)), f"duplicate codes in {key}"
            assert all(isinstance(c, str) and c for c in codes), key

    def test_each_entry_has_ar_label(self):
        for key, meta in C.LOOKUP_GROUPS.items():
            for code, m in getattr(C, meta['source']):
                assert m.get('ar'), f"{key}:{code} missing ar label"


class TestLookupService:
    def test_get_lookup_returns_base(self, db):
        rows = LS.get_lookup('product_units')
        assert ('piece', {'ar': 'قطعة'}) in [(c, {'ar': m['ar']}) for c, m in rows]

    def test_unknown_group_raises(self, db):
        with pytest.raises(ValueError, match='غير معروفة'):
            LS.get_lookup('nope_nothing')

    def test_add_custom_unlocked(self, db):
        LS.add_custom('product_units', 'pallet', 'طبيلة', 'Pallet')
        assert 'pallet' in LS.get_codes('product_units')
        assert LS.get_label('product_units', 'pallet') == 'طبيلة'

    def test_add_duplicate_rejected(self, db):
        with pytest.raises(ValueError, match='موجود بالفعل'):
            LS.add_custom('product_units', 'piece', 'مكرر', 'Dup')

    def test_add_locked_group_rejected(self, db):
        with pytest.raises(ValueError, match='مقفلة'):
            LS.add_custom('payment_methods', 'crypto_x', 'تشفير', 'Crypto')
        assert 'crypto_x' not in LS.get_codes('payment_methods')

    def test_disable_and_restore(self, db):
        LS.set_disabled('product_units', 'box', True)
        assert 'box' not in LS.get_codes('product_units')
        LS.set_disabled('product_units', 'box', False)
        assert 'box' in LS.get_codes('product_units')

    def test_disable_locked_rejected(self, db):
        with pytest.raises(ValueError, match='مقفلة'):
            LS.set_disabled('currencies', 'AED', True)
        assert 'AED' in LS.get_codes('currencies')

    def test_label_override_locked_group(self, db):
        LS.set_label('payment_methods', 'cash', 'كاش', 'Cash')
        assert LS.get_label('payment_methods', 'cash') == 'كاش'

    def test_label_unknown_code_rejected(self, db):
        with pytest.raises(ValueError, match='غير موجود'):
            LS.set_label('product_units', 'nope', 'لا', 'No')


class TestConstantsUI:
    def _owner(self, client, owner_user):
        client.post('/auth/login', data={
            'username': 'testowner', 'password': 'OwnerPass123!',
        }, follow_redirects=True)

    def test_index_owner_200(self, client, owner_user):
        self._owner(client, owner_user)
        resp = client.get('/owner/constants')
        assert resp.status_code == 200
        assert 'ثوابت النظام' in resp.get_data(as_text=True)

    def test_group_owner_200(self, client, owner_user):
        self._owner(client, owner_user)
        resp = client.get('/owner/constants/product_units')
        assert resp.status_code == 200

    def test_unknown_group_404(self, client, owner_user):
        self._owner(client, owner_user)
        assert client.get('/owner/constants/nope').status_code == 404

    def test_seller_forbidden(self, client, seller_user):
        client.post('/auth/login', data={
            'username': 'testseller', 'password': 'SellerPass123!',
        }, follow_redirects=True)
        assert client.get('/owner/constants').status_code == 404
        assert client.post('/owner/constants/product_units/add',
                           data={}).status_code == 404

    def test_add_flow_visible_in_lookup(self, client, owner_user):
        self._owner(client, owner_user)
        resp = client.post('/owner/constants/product_units/add', data={
            'code': 'bundle', 'ar': 'رزمة', 'en': 'Bundle'},
            follow_redirects=False)
        assert resp.status_code == 302
        assert 'bundle' in LS.get_codes('product_units')

    def test_add_locked_rejected(self, client, owner_user):
        self._owner(client, owner_user)
        client.post('/owner/constants/payment_methods/add', data={
            'code': 'barter', 'ar': 'مقايضة', 'en': 'Barter'})
        assert 'barter' not in LS.get_codes('payment_methods')

    def test_wiring_custom_unit_in_product_form(self, client, owner_user):
        self._owner(client, owner_user)
        LS.add_custom('product_units', 'drum', 'برميل', 'Drum')
        resp = client.get('/products/create')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'value="drum"' in html
        # Long lookup lists are searchable (select2) with a uniform rule.
        assert 'name="unit" class="form-control select2"' in html
