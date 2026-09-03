import json
import os

import pytest

# These tests explicitly exercise ensure_system_integrity(), which
# normally skips when APP_ENV=testing.  Force the function to run.
os.environ['SYSTEM_INTEGRITY_FORCE'] = '1'

import utils.telemetry
from models import User, Role, Permission, SystemSettings, SecurityAlert
from utils.system_init import (
    ensure_system_integrity,
    _ensure_permissions,
    _ensure_owner_role,
)
from utils.db_safety import (
    get_allowed_table_names,
    validate_table_name,
    validate_backup_filename,
)

EXPECTED_PERMS = {
    'manage_sales', 'manage_purchases', 'manage_products', 'manage_customers',
    'manage_suppliers', 'manage_payments', 'manage_expenses', 'view_reports',
    'manage_users', 'manage_warehouse', 'view_ledger', 'manage_ledger',
    'admin', 'manage_backups',
    'manage_hr', 'manage_approvals', 'manage_settings', 'view_products',
    'view_costs',
}


def _counts():
    links = sum(len(r.permissions) for r in Role.query.all())
    return {
        'permissions': Permission.query.count(),
        'roles': Role.query.count(),
        'users': User.query.count(),
        'alerts': SecurityAlert.query.count(),
        'settings': SystemSettings.query.count(),
        'role_permission_links': links,
    }


def _run_init(app):
    with app.app_context():
        ensure_system_integrity(app)


@pytest.fixture
def no_telemetry(monkeypatch):
    monkeypatch.setenv('DISABLE_TELEMETRY', '1')


class TestEnsurePermissions:
    def test_first_run_seeds_all_permissions(self, db, app, no_telemetry):
        assert Permission.query.count() == 0
        with app.app_context():
            _ensure_permissions()
        assert Permission.query.count() == len(EXPECTED_PERMS)
        codes = {p.code for p in Permission.query.all()}
        assert codes == EXPECTED_PERMS

    def test_second_run_is_idempotent(self, db, app, no_telemetry):
        with app.app_context():
            _ensure_permissions()
            _ensure_permissions()
        assert Permission.query.count() == len(EXPECTED_PERMS)

    def test_existing_permissions_not_duplicated(self, db, app, no_telemetry):
        db.session.add(Permission(code='admin', name='Admin Dashboard', category='admin'))
        db.session.commit()
        with app.app_context():
            _ensure_permissions()
        assert Permission.query.count() == len(EXPECTED_PERMS)
        assert Permission.query.filter_by(code='admin').count() == 1


class TestRolesSeeding:
    def test_full_init_creates_owner_user_and_roles(self, db, app, no_telemetry):
        _run_init(app)
        slugs = {r.slug for r in Role.query.all()}
        assert {'owner', 'super_admin', 'developer'} <= slugs
        for slug in ('owner', 'super_admin', 'developer'):
            role = Role.query.filter_by(slug=slug).first()
            assert role.is_active is True
            perm_codes = {p.code for p in role.permissions}
            assert perm_codes == EXPECTED_PERMS
            assert role.has_permission('manage_sales')
            assert not role.has_permission('nonexistent_perm')

    def test_owner_role_gets_newly_added_permission_on_rerun(self, db, app, no_telemetry):
        _run_init(app)
        extra = Permission(code='manage_auctions', name='Manage Auctions', category='sales')
        db.session.add(extra)
        db.session.commit()
        _run_init(app)
        owner = Role.query.filter_by(slug='owner').first()
        assert owner.has_permission('manage_auctions')

    def test_private_ensure_owner_role_direct(self, db, app, no_telemetry):
        with app.app_context():
            role = _ensure_owner_role()
            again = _ensure_owner_role()
        assert role.id == again.id
        assert Role.query.filter_by(slug='owner').count() == 1


class TestOwnerUser:
    def test_creates_master_owner_with_config_credentials(self, db, app, no_telemetry):
        app.config['OWNER_EMAIL'] = 'corp.owner@example.com'
        _run_init(app)
        owners = User.query.filter_by(is_owner=True).all()
        assert len(owners) == 1
        owner = owners[0]
        assert owner.username == app.config.get('OWNER_USERNAME', 'owner')
        assert owner.email == 'corp.owner@example.com'
        assert owner.is_active is True
        assert owner.email_verified is True
        assert owner.role.slug == 'owner'
        assert owner.check_password(app.config['OWNER_PASSWORD'])

    def test_legacy_username_user_promoted_to_owner(self, db, app, no_telemetry):
        app.config['OWNER_EMAIL'] = 'corp.owner@example.com'
        seller_role = Role(name='Seller', name_ar='بائع', slug='seller')
        legacy = User(
            username=app.config.get('OWNER_USERNAME', 'owner'),
            email='legacy@corp.example', full_name='Legacy',
            is_owner=False, is_active=True, role=seller_role,
        )
        legacy.set_password('LegacyPass123!')
        db.session.add_all([seller_role, legacy])
        db.session.commit()

        _run_init(app)

        db.session.expire_all()
        owners = User.query.filter_by(is_owner=True).all()
        assert len(owners) == 1
        assert owners[0].id == legacy.id
        assert owners[0].role.slug == 'owner'
        assert User.query.count() == 1

    def test_owner_email_updated_from_config_on_rerun(self, db, app, no_telemetry):
        app.config['OWNER_EMAIL'] = 'first@company.example'
        _run_init(app)
        app.config['OWNER_EMAIL'] = 'second@company.example'
        _run_init(app)
        owner = User.query.filter_by(is_owner=True).first()
        assert owner.email == 'second@company.example'

    def test_local_placeholder_config_email_never_overwrites(self, db, app, no_telemetry):
        app.config['OWNER_EMAIL'] = 'owner@system.local'
        seller_role = Role(name='S', slug='seller2')
        legacy = User(
            username=app.config.get('OWNER_USERNAME', 'owner'),
            email='keep@corp.example', full_name='L',
            is_owner=False, is_active=True, role=seller_role,
        )
        legacy.set_password('KeepPass123!')
        db.session.add_all([seller_role, legacy])
        db.session.commit()

        _run_init(app)

        db.session.expire_all()
        owner = User.query.filter_by(is_owner=True).first()
        assert owner.is_owner is True
        assert owner.email == 'keep@corp.example'


class TestServerActivationRecording:
    def test_first_activation_creates_high_alert_and_signature(self, db, app, no_telemetry):
        from utils.telemetry import get_machine_signature
        _run_init(app)
        alerts = SecurityAlert.query.filter_by(alert_type='system_activation').all()
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.severity == 'high'
        assert alert.title
        assert alert.user_id == User.query.filter_by(is_owner=True).first().id
        details = json.loads(alert.description)
        assert details['event'] == 'first_activation'
        assert details['previous_signature'] is None
        assert details['signature'] == get_machine_signature()
        settings = SystemSettings.get_current()
        assert settings.get_custom_setting('activation_machine_signature') == get_machine_signature()
        assert settings.get_custom_setting('activation_machine_signature_at')

    def test_same_server_rerun_records_no_new_alert(self, db, app, no_telemetry):
        _run_init(app)
        before = _counts()
        _run_init(app)
        after = _counts()
        assert before == after
        alerts = SecurityAlert.query.filter_by(alert_type='system_activation').all()
        assert len(alerts) == 1

    def test_signature_mismatch_raises_critical_server_changed_alert(self, db, app, no_telemetry):
        settings = SystemSettings.get_current()
        settings.set_custom_setting('activation_machine_signature', 'old-box-signature')
        db.session.commit()

        _run_init(app)

        alerts = SecurityAlert.query.filter_by(alert_type='system_activation').all()
        assert len(alerts) == 1
        assert alerts[0].severity == 'critical'
        details = json.loads(alerts[0].description)
        assert details['event'] == 'server_changed'
        assert details['previous_signature'] == 'old-box-signature'


class TestTelemetryToggle:
    def test_disabled_env_skips_start_telemetry(self, db, app, monkeypatch):
        monkeypatch.setenv('DISABLE_TELEMETRY', '1')
        calls = []
        monkeypatch.setattr(utils.telemetry, 'start_telemetry', lambda: calls.append(1))
        _run_init(app)
        assert calls == []

    def test_enabled_env_invokes_start_telemetry_once(self, db, app, monkeypatch):
        monkeypatch.delenv('DISABLE_TELEMETRY', raising=False)
        calls = []
        monkeypatch.setattr(utils.telemetry, 'start_telemetry', lambda: calls.append(1))
        _run_init(app)
        assert calls == [1]


class TestFullInitIdempotency:
    def test_double_run_leaves_database_state_unchanged(self, db, app, no_telemetry):
        _run_init(app)
        snapshot = _counts()
        assert snapshot['permissions'] == len(EXPECTED_PERMS)
        assert snapshot['settings'] == 1
        result = ensure_system_integrity(app)
        assert result is None
        assert _counts() == snapshot


class TestValidateTableName:
    @pytest.mark.parametrize('name', ['users', 'sales', '_tmp_cache', 'Table9_x'])
    def test_valid_names_against_explicit_allowed_set(self, name):
        allowed = {'users', 'sales', '_tmp_cache', 'Table9_x'}
        assert validate_table_name(name, allowed=allowed) == name

    def test_allowed_set_match_is_case_sensitive(self):
        with pytest.raises(ValueError, match='does not exist'):
            validate_table_name('Users', allowed={'users'})

    @pytest.mark.parametrize('bad', ['', None, 123, ['users'], '   '])
    def test_rejects_empty_or_non_string(self, bad):
        with pytest.raises(ValueError, match='Invalid table name'):
            validate_table_name(bad, allowed={'users'})

    @pytest.mark.parametrize('bad', [
        'users; DROP TABLE users',
        '123abc',
        'has space',
        'col-name',
        'a.b',
        "users'",
    ])
    def test_rejects_invalid_format(self, bad):
        with pytest.raises(ValueError, match='Invalid table name format'):
            validate_table_name(bad, allowed={'users'})

    @pytest.mark.parametrize('bad', [
        'pg_class', 'pg_tables', 'pg_proc', 'pg_namespace',
        'information_schema', 'PG_CATALOG', 'Pg_Authid', 'PG_ATTRIBUTE',
    ])
    def test_rejects_dangerous_catalog_names_even_if_allowed(self, bad):
        allowed = {bad.lower()}
        with pytest.raises(ValueError, match='not allowed'):
            validate_table_name(bad, allowed=allowed)

    def test_real_schema_accepts_known_table(self, db):
        assert validate_table_name('users') == 'users'
        assert validate_table_name('system_settings') == 'system_settings'

    def test_real_schema_rejects_unknown_table(self, db):
        with pytest.raises(ValueError, match='does not exist'):
            validate_table_name('definitely_not_a_table_xyz')

    def test_explicit_allowed_set_missing_name_raises(self):
        with pytest.raises(ValueError, match='does not exist'):
            validate_table_name('products', allowed={'users'})


class TestGetAllowedTableNames:
    def test_returns_core_tables_from_live_schema(self, db):
        names = get_allowed_table_names()
        assert {'users', 'roles', 'permissions', 'system_settings', 'security_alerts'} <= names

    def test_returns_empty_set_when_introspection_fails(self, db, monkeypatch):
        def boom(engine):
            raise RuntimeError('no inspector')
        monkeypatch.setattr('utils.db_safety.sa_inspect', boom)
        assert get_allowed_table_names() == set()


class TestValidateBackupFilename:
    def test_safe_filename_resolves_inside_backup_dir(self, tmp_path):
        result = validate_backup_filename('backup_2026_08_26.sql', str(tmp_path))
        expected = os.path.realpath(os.path.join(str(tmp_path), 'backup_2026_08_26.sql'))
        assert result == expected
        assert os.path.isabs(result)
        assert result.startswith(os.path.realpath(str(tmp_path)) + os.sep)

    @pytest.mark.parametrize('bad', ['', None, 42])
    def test_rejects_empty_or_non_string(self, bad, tmp_path):
        with pytest.raises(ValueError, match='Invalid filename'):
            validate_backup_filename(bad, str(tmp_path))

    def test_rejects_null_bytes(self, tmp_path):
        with pytest.raises(ValueError, match='null bytes'):
            validate_backup_filename('evil\x00.sql', str(tmp_path))

    @pytest.mark.parametrize('bad', [
        '../../etc/passwd',
        '..\\..\\win.ini',
        'sub/dir/inner.sql',
        'my backup.sql',
        '..',
        'backup;.sql',
    ])
    def test_rejects_unsafe_or_altered_names(self, bad, tmp_path):
        with pytest.raises(ValueError):
            validate_backup_filename(bad, str(tmp_path))
