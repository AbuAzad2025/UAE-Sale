"""Flow tests for routes/payment_vault.py — donations, packages, exports, lock.

payment_vault.py sat at ~29-34% combined coverage. These tests seed an
unlocked vault plus donation/package/purchase rows and exercise the
approve/reject/toggle/activate/export/decrypt paths with owner +
non-owner actors.
"""
import pytest
from decimal import Decimal

from models import User, Role
from models.payment_vault import PaymentVault
from models.donation import Donation
from models.package import Package, PackagePurchase
from extensions import db as _db


@pytest.fixture(scope='function')
def vault_owner(db):
    role = Role(name='VOwner', name_ar='م', slug='vault_owner_role')
    _db.session.add(role)
    _db.session.flush()
    u = User(username='vault_owner', email='vo@test.com', full_name='VO',
             is_owner=True, is_active=True, role_id=role.id)
    u.set_password('Pass123!')
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture(scope='function')
def vault_plain(db):
    role = Role(name='VPlain', name_ar='م', slug='vault_plain_role')
    _db.session.add(role)
    _db.session.flush()
    u = User(username='vault_plain', email='vp@test.com', full_name='VP',
             is_owner=False, is_active=True, role_id=role.id)
    u.set_password('Pass123!')
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture(scope='function')
def unlocked_vault(db):
    v = PaymentVault()
    v.set_vault_password('VaultPass123!')
    v.is_locked = False
    _db.session.add(v)
    _db.session.commit()
    return v


@pytest.fixture(scope='function')
def donation(db):
    d = Donation(amount_usd=Decimal('50'), payment_method='crypto',
                 donor_name='Donor', donor_email='donor@test.com',
                 status='pending')
    _db.session.add(d)
    _db.session.commit()
    return d


@pytest.fixture(scope='function')
def package(db):
    p = Package(name_ar='باقة', name_en='Pack', slug='pack-test',
                price=Decimal('99'), is_active=True)
    _db.session.add(p)
    _db.session.commit()
    return p


@pytest.fixture(scope='function')
def purchase(db, package):
    pu = PackagePurchase(package_id=package.id, customer_name='C',
                         customer_email='c@test.com',
                         payment_method='crypto',
                         amount_paid=Decimal('99'))
    _db.session.add(pu)
    _db.session.commit()
    return pu


def _login(client, user):
    client.post('/auth/login', data={
        'username': user.username, 'password': 'Pass123!',
    }, follow_redirects=True)


# ── Donations ─────────────────────────────────────────────────────────────────

class TestDonationFlows:
    def test_detail_ok(self, client, vault_owner, unlocked_vault, donation):
        _login(client, vault_owner)
        assert client.get(f'/payment-vault/donation/{donation.id}').status_code == 200

    def test_detail_missing_404(self, client, vault_owner, unlocked_vault):
        _login(client, vault_owner)
        assert client.get('/payment-vault/donation/999999').status_code == 404

    def test_detail_locked_vault_redirects(self, client, vault_owner, db, donation):
        _login(client, vault_owner)
        resp = client.get(f'/payment-vault/donation/{donation.id}')
        assert resp.status_code == 302  # -> unlock (no vault row at all)

    def test_detail_non_owner_redirects(self, client, vault_plain, unlocked_vault, donation):
        _login(client, vault_plain)
        assert client.get(f'/payment-vault/donation/{donation.id}').status_code == 302

    def test_approve_completes(self, client, vault_owner, unlocked_vault, donation, db):
        _login(client, vault_owner)
        resp = client.post(f'/payment-vault/donation/{donation.id}/approve')
        assert resp.status_code in (200, 302)
        assert _db.session.get(Donation, donation.id).status == 'completed'

    def test_reject_fails(self, client, vault_owner, unlocked_vault, donation, db):
        _login(client, vault_owner)
        resp = client.post(f'/payment-vault/donation/{donation.id}/reject')
        assert resp.status_code in (200, 302)
        assert _db.session.get(Donation, donation.id).status == 'failed'

    def test_approve_non_owner_blocked(self, client, vault_plain, unlocked_vault, donation, db):
        _login(client, vault_plain)
        client.post(f'/payment-vault/donation/{donation.id}/approve')
        assert _db.session.get(Donation, donation.id).status == 'pending'


# ── Packages & purchases ──────────────────────────────────────────────────────

class TestPackageFlows:
    def test_toggle_flips(self, client, vault_owner, package, db):
        _login(client, vault_owner)
        resp = client.post(f'/payment-vault/package/{package.id}/toggle')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        assert _db.session.get(Package, package.id).is_active is False

    def test_toggle_missing_404(self, client, vault_owner):
        _login(client, vault_owner)
        assert client.post('/payment-vault/package/999999/toggle').status_code == 404

    def test_toggle_non_owner_403(self, client, vault_plain, package):
        _login(client, vault_plain)
        assert client.post(f'/payment-vault/package/{package.id}/toggle').status_code == 403

    def test_activate_purchase(self, client, vault_owner, purchase, db):
        _login(client, vault_owner)
        resp = client.post(f'/payment-vault/purchase/{purchase.id}/activate')
        assert resp.status_code in (200, 302)
        pu = _db.session.get(PackagePurchase, purchase.id)
        assert pu.activation_status == 'activated'
        assert pu.payment_status == 'completed'

    def test_package_stats(self, client, vault_owner, package):
        _login(client, vault_owner)
        resp = client.get(f'/payment-vault/api/package-stats/{package.id}')
        assert resp.status_code in (200, 302)


# ── Exports ───────────────────────────────────────────────────────────────────

class TestVaultExports:
    @pytest.mark.parametrize('url', [
        '/payment-vault/export/purchases',
        '/payment-vault/export/donations',
        '/payment-vault/export/cards',
    ])
    def test_owner_downloads_csv(self, client, vault_owner, url):
        _login(client, vault_owner)
        resp = client.get(url)
        assert resp.status_code == 200
        assert 'text/csv' in resp.content_type

    @pytest.mark.parametrize('url', [
        '/payment-vault/export/purchases',
        '/payment-vault/export/donations',
    ])
    def test_non_owner_403(self, client, vault_plain, url):
        _login(client, vault_plain)
        assert client.get(url).status_code == 403


# ── Lock / unlock / cards ─────────────────────────────────────────────────────

class TestVaultLock:
    def test_unlock_page_ok(self, client, vault_owner):
        _login(client, vault_owner)
        assert client.get('/payment-vault/unlock').status_code == 200

    def test_unlock_empty_password_stays(self, client, vault_owner):
        _login(client, vault_owner)
        assert client.post('/payment-vault/unlock',
                           data={'vault_password': ''}).status_code == 200

    def test_unlock_wrong_password_stays_locked(self, client, vault_owner,
                                               unlocked_vault, db):
        unlocked_vault.is_locked = True
        _db.session.commit()
        _login(client, vault_owner)
        client.post('/payment-vault/unlock',
                    data={'vault_password': 'wrong!'})
        assert _db.session.get(PaymentVault, unlocked_vault.id).is_locked is True

    def test_unlock_correct_password(self, client, vault_owner,
                                     unlocked_vault, db):
        unlocked_vault.is_locked = True
        _db.session.commit()
        _login(client, vault_owner)
        resp = client.post('/payment-vault/unlock',
                           data={'vault_password': 'VaultPass123!'})
        assert resp.status_code in (200, 302)
        assert _db.session.get(PaymentVault, unlocked_vault.id).is_locked is False

    def test_lock_vault(self, client, vault_owner, unlocked_vault, db):
        _login(client, vault_owner)
        client.get('/payment-vault/lock')
        assert _db.session.get(PaymentVault, unlocked_vault.id).is_locked is True

    def test_decrypt_missing_card_404(self, client, vault_owner, unlocked_vault):
        _login(client, vault_owner)
        assert client.post('/payment-vault/card/999999/decrypt').status_code in (403, 404)

    def test_change_password_page_ok(self, client, vault_owner):
        _login(client, vault_owner)
        assert client.get('/payment-vault/change-password').status_code in (200, 302)
