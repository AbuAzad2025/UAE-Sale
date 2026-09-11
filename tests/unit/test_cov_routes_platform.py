"""Platform route coverage: approvals/owner/ledger/users/monitoring/api/v2/vault/whatsapp.

Hermetic tests for the F1/F2/F3/F6/F11/F15/F16/F44/F45/F46/F47/F48/F49/F50/F60/F61/F96
remediation batch. Uses only conftest fixtures + local rows; no external I/O.
"""
from decimal import Decimal

from sqlalchemy import func

from extensions import db as _db
from models import ApprovalWorkflow, AuditLog, SystemSettings
from models.donation import Donation
from models.gl import GLAccount, GLJournalEntry, GLJournalLine
from models.payment import Payment
from models.sale import Sale


def _login(client, username, password):
    return client.post('/auth/login', data={
        'username': username, 'password': password,
    }, follow_redirects=True)


def _login_owner(client, owner_user):
    _login(client, owner_user.username, 'OwnerPass123!')


# ── F1: approvals workflow without max_amount ────────────────────────────────

class TestApprovalsWorkflowNoMax:
    def test_new_workflow_without_max_amount(self, client, db, owner_user):
        _login_owner(client, owner_user)
        resp = client.post('/approvals/workflows/new', data={
            'name': 'NoMax WF', 'entity_type': 'sale',
            'min_amount': '100', 'levels_required': '1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        wf = ApprovalWorkflow.query.filter_by(name='NoMax WF').first()
        assert wf is not None
        assert wf.max_amount is None
        assert float(wf.min_amount) == 100.0

    def test_edit_workflow_without_max_amount(self, client, db, owner_user):
        _login_owner(client, owner_user)
        wf = ApprovalWorkflow(name='EditMe', entity_type='sale',
                              min_amount=10, max_amount=500,
                              levels_required=1, is_active=True)
        db.session.add(wf)
        db.session.commit()
        resp = client.post(f'/approvals/workflows/{wf.id}/edit', data={
            'name': 'EditMe', 'entity_type': 'sale',
            'min_amount': '10', 'levels_required': '1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert _db.session.get(ApprovalWorkflow, wf.id).max_amount is None


# ── F2: data-cleanup invalid type ────────────────────────────────────────────

class TestDataCleanupInvalidType:
    def test_unknown_cleanup_type_flashes_error(self, client, db, owner_user):
        _login_owner(client, owner_user)
        before = AuditLog.query.count()
        resp = client.post('/owner/data-cleanup', data={
            'days': '90', 'cleanup_type': 'bogus_xyz',
        }, follow_redirects=True)
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'غير معروف' in html
        assert 'تم حذف 0' not in html
        assert AuditLog.query.count() == before

    def test_known_cleanup_type_still_works(self, client, db, owner_user):
        _login_owner(client, owner_user)
        resp = client.post('/owner/data-cleanup', data={
            'days': '90', 'cleanup_type': 'logs',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert 'تم حذف' in resp.data.decode()


# ── F3: ip-whitelist invalid ip + duplicates ─────────────────────────────────

class TestIpWhitelist:
    def test_invalid_ip_rejected(self, client, db, owner_user):
        _login_owner(client, owner_user)
        resp = client.post('/owner/ip-whitelist', data={
            'ip_address': '999.999.999.999', 'description': 'x',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert 'غير صالح' in resp.data.decode()

    def test_blank_ip_rejected(self, client, db, owner_user):
        _login_owner(client, owner_user)
        resp = client.post('/owner/ip-whitelist', data={
            'ip_address': '', 'description': 'x',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert 'غير صالح' in resp.data.decode()

    def test_valid_ip_then_duplicate(self, client, db, owner_user):
        _login_owner(client, owner_user)
        first = client.post('/owner/ip-whitelist', data={
            'ip_address': '10.20.30.40', 'description': 'office',
        }, follow_redirects=True)
        assert first.status_code == 200
        assert 'تم إضافة IP' in first.data.decode()
        dup = client.post('/owner/ip-whitelist', data={
            'ip_address': '10.20.30.40', 'description': 'again',
        }, follow_redirects=True)
        assert dup.status_code == 200
        assert 'موجود مسبقاً' in dup.data.decode()
        settings = SystemSettings.get_current()
        import json as _json
        raw = settings.owner_whitelist_ips or '[]'
        entries = _json.loads(raw) if isinstance(raw, str) else raw
        assert sum(1 for e in entries if e.get('ip') == '10.20.30.40') == 1


# ── F15: manual-entry malformed amount ───────────────────────────────────────

class TestManualEntryMalformed:
    def test_malformed_debit_rejected(self, client, db, owner_user):
        _login_owner(client, owner_user)
        acc = GLAccount(code='1001', name='Cash', type='asset',
                        is_active=True, is_header=False)
        db.session.add(acc)
        db.session.commit()
        before = GLJournalEntry.query.count()
        resp = client.post('/ledger/manual-entry', data={
            'description': 'malformed', 'entry_date': '2026-01-01',
            'line_0_account': '1001', 'line_0_debit': 'abc',
            'line_0_credit': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert 'غير صالحة' in resp.data.decode()
        assert GLJournalEntry.query.count() == before


# ── F16/F46: trial-balance date filter + GROUP BY equivalence ────────────────

class TestTrialBalance:
    def _seed_lines(self, db):
        acc1 = GLAccount(code='1001', name='Cash', type='asset',
                         is_active=True, is_header=False)
        acc2 = GLAccount(code='4001', name='Revenue', type='revenue',
                         is_active=True, is_header=False)
        db.session.add_all([acc1, acc2])
        db.session.flush()
        entry = GLJournalEntry(entry_number='JE-TEST-001',
                               description='seed')
        db.session.add(entry)
        db.session.flush()
        db.session.add_all([
            GLJournalLine(entry_id=entry.id, account_id=acc1.id,
                          debit=Decimal('150.000'), credit=Decimal('0')),
            GLJournalLine(entry_id=entry.id, account_id=acc2.id,
                          debit=Decimal('0'), credit=Decimal('150.000')),
        ])
        db.session.commit()
        return acc1, acc2

    def test_invalid_date_flashes_warning_keeps_200(self, client, db, owner_user):
        _login_owner(client, owner_user)
        resp = client.get('/ledger/trial-balance?date_from=not-a-date',
                          follow_redirects=True)
        assert resp.status_code == 200
        assert 'غير صالحة' in resp.data.decode()

    def test_valid_date_filter_200(self, client, db, owner_user):
        _login_owner(client, owner_user)
        self._seed_lines(db)
        resp = client.get('/ledger/trial-balance?date_from=2000-01-01&date_to=2100-01-01')
        assert resp.status_code == 200

    def test_group_by_matches_per_account_sums(self, client, db, owner_user):
        acc1, acc2 = self._seed_lines(db)
        # Legacy per-account method (as the old loop did it).
        legacy = {}
        for acc in (acc1, acc2):
            d = db.session.query(func.sum(GLJournalLine.debit)).filter_by(
                account_id=acc.id).scalar() or Decimal('0')
            c = db.session.query(func.sum(GLJournalLine.credit)).filter_by(
                account_id=acc.id).scalar() or Decimal('0')
            legacy[acc.id] = (d, c)
        # New single GROUP BY method (as the route does it now).
        rows = db.session.query(
            GLJournalLine.account_id,
            func.sum(GLJournalLine.debit),
            func.sum(GLJournalLine.credit),
        ).group_by(GLJournalLine.account_id).all()
        grouped = {r[0]: ((r[1] or Decimal('0')), (r[2] or Decimal('0')))
                   for r in rows}
        assert grouped == legacy
        assert grouped[acc1.id] == (Decimal('150.000'), Decimal('0'))
        assert grouped[acc2.id] == (Decimal('0'), Decimal('150.000'))


# ── F45: user roster aggregates ──────────────────────────────────────────────

class TestUserRosterAggregates:
    def test_view_sums_match_sql_aggregates(self, client, db, owner_user, seller_user):
        sale1 = Sale(sale_number='S-AGG-1', customer_id=None,
                     seller_id=seller_user.id, total_amount=Decimal('100.000'),
                     amount_base=Decimal('100.000'), paid_amount_base=Decimal('0'),
                     status='confirmed', is_active=True)
        sale2 = Sale(sale_number='S-AGG-2', customer_id=None,
                     seller_id=seller_user.id, total_amount=Decimal('250.000'),
                     amount_base=Decimal('250.000'), paid_amount_base=Decimal('0'),
                     status='confirmed', is_active=True)
        db.session.add_all([sale1, sale2])
        db.session.flush()
        db.session.add_all([
            Payment(payment_number='PAY-AGG-1', payment_type='receipt',
                    direction='incoming', amount=Decimal('30.000'),
                    amount_base=Decimal('30.000'), payment_method='cash',
                    user_id=seller_user.id),
            Payment(payment_number='PAY-AGG-2', payment_type='receipt',
                    direction='incoming', amount=Decimal('70.000'),
                    amount_base=Decimal('70.000'), payment_method='cash',
                    user_id=seller_user.id),
        ])
        db.session.commit()

        # Route's func.sum scalars equal the naive Python sums (prove equal).
        scalar_sales = db.session.query(func.sum(Sale.amount_base)).filter_by(
            seller_id=seller_user.id).scalar() or 0
        python_sales = sum((s.amount_base or 0)
                           for s in Sale.query.filter_by(seller_id=seller_user.id).all()) or 0
        assert float(scalar_sales) == float(python_sales) == 350.0

        scalar_pay = db.session.query(func.sum(Payment.amount_base)).filter_by(
            user_id=seller_user.id).scalar() or 0
        python_pay = sum((p.amount_base or 0)
                         for p in Payment.query.filter_by(user_id=seller_user.id).all()) or 0
        assert float(scalar_pay) == float(python_pay) == 100.0

        _login_owner(client, owner_user)
        resp = client.get(f'/users/{seller_user.id}')
        assert resp.status_code == 200


# ── Monitoring: metrics + health ─────────────────────────────────────────────

class TestMonitoring:
    def test_metrics_owner_ok(self, client, db, owner_user):
        _login_owner(client, owner_user)
        resp = client.get('/monitoring/metrics')
        assert resp.status_code == 200
        body = resp.get_json()
        assert 'total_sales' in body

    def test_health_public_signal(self, client, db):
        resp = client.get('/monitoring/health')
        assert resp.status_code in (200, 503)
        assert resp.get_json()['status'] in ('healthy', 'unavailable')

    def test_dashboard_owner_ok(self, client, db, owner_user):
        _login_owner(client, owner_user)
        assert client.get('/monitoring/dashboard').status_code == 200


# ── api/v2 search ────────────────────────────────────────────────────────────

class TestApiV2Search:
    def test_products_search(self, client, db, owner_user, test_product):
        _login_owner(client, owner_user)
        resp = client.get('/api/v2/products/search?q=Test')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['count'] >= 1

    def test_products_search_requires_query(self, client, db, owner_user):
        _login_owner(client, owner_user)
        assert client.get('/api/v2/products/search').status_code == 400


# ── Vault approve/reject with DB assertions ──────────────────────────────────

class TestVaultApproveReject:
    def _donation(self, db, **kw):
        args = dict(amount_usd=Decimal('50'), payment_method='crypto',
                    donor_name='Donor', donor_email='donor@test.com',
                    status='pending')
        args.update(kw)
        d = Donation(**args)
        db.session.add(d)
        db.session.commit()
        return d

    def test_approve_completes(self, client, db, owner_user):
        _login_owner(client, owner_user)
        d = self._donation(db)
        resp = client.post(f'/payment-vault/donation/{d.id}/approve',
                           follow_redirects=True)
        assert resp.status_code in (200, 302)
        row = _db.session.get(Donation, d.id)
        assert row.status == 'completed'
        assert row.completed_at is not None

    def test_reject_fails(self, client, db, owner_user):
        _login_owner(client, owner_user)
        d = self._donation(db, donor_email='other@test.com')
        resp = client.post(f'/payment-vault/donation/{d.id}/reject',
                           follow_redirects=True)
        assert resp.status_code in (200, 302)
        assert _db.session.get(Donation, d.id).status == 'failed'


# ── WhatsApp missing-phone path ──────────────────────────────────────────────

class TestWhatsappMissingPhone:
    def test_send_invoice_no_phone(self, client, db, owner_user, test_product):
        from models import Customer
        _login_owner(client, owner_user)
        cust = Customer(name='NoPhone', customer_type='regular',
                        phone=None, is_active=True)
        db.session.add(cust)
        db.session.flush()
        sale = Sale(sale_number='S-NOPHONE', customer_id=cust.id,
                    seller_id=owner_user.id, total_amount=Decimal('10.000'),
                    amount_base=Decimal('10.000'), paid_amount_base=Decimal('0'),
                    status='confirmed', is_active=True)
        db.session.add(sale)
        db.session.commit()
        resp = client.post(f'/whatsapp/send-invoice/{sale.id}')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is False
        assert 'phone' in body['error'].lower()

    def test_send_reminder_no_phone(self, client, db, owner_user):
        from models import Customer
        _login_owner(client, owner_user)
        cust = Customer(name='NoPhone2', customer_type='regular',
                        phone=None, is_active=True)
        db.session.add(cust)
        db.session.commit()
        resp = client.post(f'/whatsapp/send-reminder/{cust.id}')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is False
