"""Wave-1 coverage tests for routes/owner.py — real endpoint hits only.

Covers owner endpoints NOT already covered by test_owner_panel.py,
test_owner_tenants.py, or test_error_logs_page.py (no /tenants*,
no invoice/payment-gateway POSTs, no preview-template or read-page
duplicates). Every test hits a real endpoint and asserts statuses,
JSON shapes, redirects, or DB effects.
"""


def _owner_login(client):
    client.post('/auth/login', data={
        'username': 'testowner', 'password': 'OwnerPass123!',
    }, follow_redirects=True)


def _seller_login(client):
    client.post('/auth/login', data={
        'username': 'testseller', 'password': 'SellerPass123!',
    }, follow_redirects=True)


class TestOwnerArchived:
    def test_archived_owner_200(self, client, owner_user):
        _owner_login(client)
        assert client.get('/owner/archived').status_code == 200

    def test_archived_table_filter_200(self, client, owner_user):
        _owner_login(client)
        resp = client.get('/owner/archived', query_string={'table': 'sales'})
        assert resp.status_code == 200

    def test_archived_seller_302(self, client, seller_user):
        _seller_login(client)
        resp = client.get('/owner/archived', follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/dashboard')

    def test_archived_anonymous_302(self, client, db):
        assert client.get('/owner/archived',
                          follow_redirects=False).status_code == 302


class TestOwnerCardVault:
    def _card(self, db, test_customer):
        from models import CardVault
        card = CardVault(customer_id=test_customer.id, is_active=True)
        card.set_card_data('4111111111111111', 'John Doe', '12', '2030',
                           '123')
        db.session.add(card)
        db.session.commit()
        return card

    def test_view_card_missing_404(self, client, owner_user):
        _owner_login(client)
        assert client.get('/owner/cards-vault/99999/view').status_code == 404

    def test_view_card_success(self, client, owner_user, db, test_customer):
        _owner_login(client)
        card = self._card(db, test_customer)
        resp = client.get(f'/owner/cards-vault/{card.id}/view')
        assert resp.status_code == 200
        assert '1111' in resp.get_data(as_text=True)

    def test_view_card_seller_302(self, client, seller_user):
        _seller_login(client)
        resp = client.get('/owner/cards-vault/1/view',
                          follow_redirects=False)
        assert resp.status_code == 302

    def test_view_card_anonymous_302(self, client, db):
        assert client.get('/owner/cards-vault/1/view',
                          follow_redirects=False).status_code == 302


class TestOwnerIntegrations:
    def test_update_whatsapp_db_effect(self, client, owner_user, db):
        from models import IntegrationSettings
        _owner_login(client)
        resp = client.post('/owner/integrations/update/whatsapp', data={
            'enabled': 'true', 'api_token': 'tok-1',
            'phone_number': '+971500000001'}, follow_redirects=False)
        assert resp.status_code == 302
        row = IntegrationSettings.query.filter_by(
            service_name='whatsapp').first()
        assert row is not None
        assert row.enabled is True
        assert row.get_config()['api_token'] == 'tok-1'

    def test_update_email_db_effect(self, client, owner_user, db):
        from models import IntegrationSettings
        _owner_login(client)
        resp = client.post('/owner/integrations/update/email', data={
            'enabled': '1', 'smtp_host': 'smtp.test.local',
            'smtp_port': '587'}, follow_redirects=False)
        assert resp.status_code == 302
        row = IntegrationSettings.query.filter_by(
            service_name='email').first()
        assert row is not None
        assert row.get_config()['smtp_host'] == 'smtp.test.local'

    def test_update_seller_302(self, client, seller_user, db):
        from models import IntegrationSettings
        _seller_login(client)
        before = IntegrationSettings.query.count()
        resp = client.post('/owner/integrations/update/whatsapp',
                           data={'enabled': 'true'}, follow_redirects=False)
        assert resp.status_code == 302
        assert IntegrationSettings.query.count() == before


class TestOwnerBackups:
    def test_backup_now_json_sqlite_400(self, client, owner_user):
        # sqlite has no pg params -> BackupService returns None -> 400 JSON.
        _owner_login(client)
        resp = client.post('/owner/backup-now', json={'description': 't'})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_backup_now_form_redirects(self, client, owner_user):
        _owner_login(client)
        resp = client.post('/owner/backup-now',
                           data={'description': 't'}, follow_redirects=False)
        assert resp.status_code == 302

    def test_backup_now_seller_403(self, client, seller_user):
        _seller_login(client)
        assert client.post('/owner/backup-now',
                           json={}).status_code == 403

    def test_verify_traversal_400(self, client, owner_user):
        # 'evil file.sql.gz' reaches the view (no path separator, so no
        # Werkzeug 404) but fails validate_backup_filename -> 400 JSON.
        _owner_login(client)
        resp = client.post('/owner/backups/verify/evil%20file.sql.gz')
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_verify_missing_404(self, client, owner_user):
        _owner_login(client)
        assert client.post(
            '/owner/backups/verify/does-not-exist.sql.gz').status_code == 404

    def test_restore_traversal_redirects(self, client, owner_user):
        _owner_login(client)
        resp = client.post('/owner/backups/restore/evil%20file.sql.gz',
                           follow_redirects=False)
        assert resp.status_code == 302

    def test_restore_without_password_redirects(self, client, owner_user):
        _owner_login(client)
        resp = client.post('/owner/backups/restore/some.sql.gz', data={},
                           follow_redirects=False)
        assert resp.status_code == 302

    def test_custom_restore_non_dump_redirects(self, client, owner_user):
        _owner_login(client)
        resp = client.post('/owner/backups/custom-restore/x.sql.gz',
                           data={}, follow_redirects=False)
        assert resp.status_code == 302

    def test_delete_no_filename_redirects(self, client, owner_user):
        _owner_login(client)
        assert client.post('/owner/backups/delete', data={},
                           follow_redirects=False).status_code == 302

    def test_delete_traversal_redirects(self, client, owner_user):
        _owner_login(client)
        assert client.post('/owner/backups/delete',
                           data={'filename': '../evil.sql.gz'},
                           follow_redirects=False).status_code == 302

    def test_delete_missing_redirects(self, client, owner_user):
        _owner_login(client)
        assert client.post('/owner/backups/delete',
                           data={'filename': 'nope.sql.gz'},
                           follow_redirects=False).status_code == 302

    def test_download_traversal_redirects(self, client, owner_user):
        _owner_login(client)
        assert client.get('/owner/backups/download/evil%20file.sql.gz',
                          follow_redirects=False).status_code == 302

    def test_download_missing_redirects(self, client, owner_user):
        _owner_login(client)
        assert client.get('/owner/backups/download/nope.sql.gz',
                          follow_redirects=False).status_code == 302


class TestOwnerMaintenance:
    def test_clear_cache_redirects(self, client, owner_user):
        _owner_login(client)
        resp = client.post('/owner/clear-cache', follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/owner/dashboard')

    def test_clear_cache_seller_302(self, client, seller_user):
        _seller_login(client)
        assert client.post('/owner/clear-cache',
                           follow_redirects=False).status_code == 302

    def test_edit_table_customers_200(self, client, owner_user):
        _owner_login(client)
        resp = client.get('/owner/edit-table-data/customers')
        assert resp.status_code == 200

    def test_edit_table_unknown_redirects(self, client, owner_user):
        _owner_login(client)
        assert client.get('/owner/edit-table-data/no_such_xyz',
                          follow_redirects=False).status_code == 302

    def test_export_database_sql_redirects(self, client, owner_user):
        _owner_login(client)
        assert client.post('/owner/export-database', data={'format': 'sql'},
                           follow_redirects=False).status_code == 302

    def test_database_optimize_redirects(self, client, owner_user):
        _owner_login(client)
        assert client.post('/owner/database-optimize',
                           follow_redirects=False).status_code == 302


class TestOwnerConstants:
    def test_index_200(self, client, owner_user):
        _owner_login(client)
        assert client.get('/owner/constants').status_code == 200

    def test_group_valid_200(self, client, owner_user):
        _owner_login(client)
        resp = client.get('/owner/constants/genders')
        assert resp.status_code == 200
        assert 'male' in resp.get_data(as_text=True)

    def test_group_unknown_404(self, client, owner_user):
        _owner_login(client)
        assert client.get('/owner/constants/nope-x').status_code == 404

    def test_add_custom_redirects(self, client, owner_user):
        _owner_login(client)
        resp = client.post('/owner/constants/genders/add', data={
            'code': 'wave1x', 'ar': 'اختبار', 'en': 'Wave1'},
            follow_redirects=False)
        assert resp.status_code == 302
        assert client.get('/owner/constants/genders').status_code == 200

    def test_label_redirects(self, client, owner_user):
        _owner_login(client)
        resp = client.post('/owner/constants/genders/label', data={
            'code': 'male', 'ar': 'ذكر', 'en': 'Male'},
            follow_redirects=False)
        assert resp.status_code == 302

    def test_visibility_toggle_redirects(self, client, owner_user):
        _owner_login(client)
        resp = client.post('/owner/constants/genders/visibility', data={
            'code': 'male', 'disabled': '1'}, follow_redirects=False)
        assert resp.status_code == 302
        resp = client.post('/owner/constants/genders/visibility', data={
            'code': 'male', 'disabled': '0'}, follow_redirects=False)
        assert resp.status_code == 302

    def test_index_seller_302(self, client, seller_user):
        _seller_login(client)
        assert client.get('/owner/constants',
                          follow_redirects=False).status_code == 302


class TestOwnerSecurityAlerts:
    def _alert(self, db):
        from models.security_alert import SecurityAlert
        alert = SecurityAlert(alert_type='test', severity='high',
                              title='Wave1 alert', is_resolved=False)
        db.session.add(alert)
        db.session.commit()
        return alert

    def test_resolve_db_effect(self, client, owner_user, db):
        from models.security_alert import SecurityAlert
        _owner_login(client)
        alert = self._alert(db)
        resp = client.post(f'/owner/security-alerts/{alert.id}/resolve',
                           follow_redirects=False)
        assert resp.status_code == 302
        db.session.expire_all()
        row = SecurityAlert.query.get(alert.id)
        assert row.is_resolved is True
        assert row.resolved_by == owner_user.id

    def test_resolve_missing_404(self, client, owner_user):
        _owner_login(client)
        assert client.post('/owner/security-alerts/99999/resolve',
                           follow_redirects=False).status_code == 404

    def test_resolve_seller_302(self, client, owner_user, seller_user, db):
        _owner_login(client)
        alert = self._alert(db)
        alert_id = alert.id
        client.get('/auth/logout', follow_redirects=True)
        _seller_login(client)
        resp = client.post(f'/owner/security-alerts/{alert_id}/resolve',
                           follow_redirects=False)
        assert resp.status_code == 302
        db.session.expire_all()
        from models.security_alert import SecurityAlert
        assert SecurityAlert.query.get(alert_id).is_resolved is False


class TestOwnerIpWhitelist:
    def test_add_valid_ip_persisted(self, client, owner_user, db):
        from models import SystemSettings
        from routes.owner import _get_ip_whitelist
        _owner_login(client)
        resp = client.post('/owner/ip-whitelist', data={
            'ip_address': '10.1.2.3', 'description': 'wave1'},
            follow_redirects=False)
        assert resp.status_code == 302
        db.session.expire_all()
        assert any(e.get('ip') == '10.1.2.3'
                   for e in _get_ip_whitelist(SystemSettings.get_current()))

    def test_add_invalid_ip_rejected(self, client, owner_user, db):
        from models import SystemSettings
        from routes.owner import _get_ip_whitelist
        _owner_login(client)
        resp = client.post('/owner/ip-whitelist',
                           data={'ip_address': 'not-an-ip'},
                           follow_redirects=False)
        assert resp.status_code == 302
        db.session.expire_all()
        assert _get_ip_whitelist(SystemSettings.get_current()) == []

    def test_delete_index_db_effect(self, client, owner_user, db):
        from models import SystemSettings
        from routes.owner import _get_ip_whitelist
        _owner_login(client)
        client.post('/owner/ip-whitelist',
                    data={'ip_address': '10.9.9.9', 'description': 'x'})
        resp = client.post('/owner/ip-whitelist/0/delete',
                           follow_redirects=False)
        assert resp.status_code == 302
        db.session.expire_all()
        assert _get_ip_whitelist(SystemSettings.get_current()) == []


class TestOwnerApiKeys:
    def test_create_db_effect(self, client, owner_user, db):
        from models.api_key import APIKey
        _owner_login(client)
        before = APIKey.query.count()
        resp = client.post('/owner/api-keys',
                           data={'name': 'wave1', 'service': 'test'},
                           follow_redirects=False)
        assert resp.status_code == 302
        assert APIKey.query.count() == before + 1
        row = APIKey.query.filter_by(name='wave1').first()
        assert row is not None
        assert row.key

    def test_toggle_db_effect(self, client, owner_user, db):
        from models.api_key import APIKey
        _owner_login(client)
        client.post('/owner/api-keys',
                    data={'name': 'wave1t', 'service': 'test'})
        row = APIKey.query.filter_by(name='wave1t').first()
        assert row.is_active is True
        resp = client.post(f'/owner/api-keys/{row.id}/toggle',
                           follow_redirects=False)
        assert resp.status_code == 302
        db.session.expire_all()
        assert APIKey.query.get(row.id).is_active is False

    def test_toggle_missing_404(self, client, owner_user):
        _owner_login(client)
        assert client.post('/owner/api-keys/99999/toggle',
                           follow_redirects=False).status_code == 404


class TestOwnerExportExcel:
    def test_unknown_table_redirects(self, client, owner_user):
        _owner_login(client)
        assert client.get('/owner/export-excel/nope',
                          follow_redirects=False).status_code == 302

    def test_empty_table_redirects(self, client, owner_user):
        _owner_login(client)
        assert client.get('/owner/export-excel/customers',
                          follow_redirects=False).status_code == 302

    def test_customers_export_200(self, client, owner_user, test_customer):
        _owner_login(client)
        resp = client.get('/owner/export-excel/customers')
        assert resp.status_code == 200
        assert 'spreadsheetml.sheet' in resp.content_type
        assert resp.data[:2] == b'PK'
