"""Unit tests for utils/security_helpers.py — IP gate, LIKE sanitizer, ORDER BY guard."""
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from utils.security_helpers import (
    OWNER_ALLOWED_IPS,
    owner_ip_check,
    sanitize_sql_like,
    validate_sql_order_by,
)


# ── sanitize_sql_like ─────────────────────────────────────────────────────────

class TestSanitizeSqlLike:
    @pytest.mark.parametrize('given,expected', [
        ('', ''),
        (None, ''),
        ('plain', 'plain'),
        ('100%', '100\\%'),
        ('a_b', 'a\\_b'),
        ('a[b', 'a\\[b'),
        ('c:\\path\\x', 'c:\\\\path\\\\x'),
        ('%_%[%\\', '\\%\\_\\%\\[\\%\\\\'),
        (123, '123'),
    ])
    def test_escapes_like_wildcards(self, given, expected):
        assert sanitize_sql_like(given) == expected


# ── validate_sql_order_by ─────────────────────────────────────────────────────

class TestValidateSqlOrderBy:
    def test_allowed_field_passes_through(self):
        assert validate_sql_order_by('name', ['name', 'date']) == 'name'

    @pytest.mark.parametrize('field', ['name; DROP TABLE x', '', 'Name', 'date '])
    def test_disallowed_field_raises(self, field):
        with pytest.raises(ValueError):
            validate_sql_order_by(field, ['name', 'date'])


# ── owner_ip_check ────────────────────────────────────────────────────────────

def _ok_view():
    return 'OK'


class _DebugScope:
    """Temporarily set app.debug (plain assignment; Flask.debug is a
    setter-only property so unittest.mock cannot patch it)."""

    def __init__(self, app, value):
        self.app = app
        self.value = value

    def __enter__(self):
        self.old = self.app.debug
        self.app.debug = self.value

    def __exit__(self, *exc):
        self.app.debug = self.old
        return False


class TestOwnerIpCheck:
    def _ctx(self, app, remote_addr):
        return app.test_request_context(
            '/', environ_overrides={'REMOTE_ADDR': remote_addr})

    def test_unauthenticated_passes_through(self, app):
        anon = SimpleNamespace(is_authenticated=False, is_owner=False)
        with self._ctx(app, '9.9.9.9'):
            with patch('flask_login.current_user', anon):
                assert owner_ip_check(_ok_view)() == 'OK'

    def test_non_owner_passes_through_from_any_ip(self, app):
        user = SimpleNamespace(is_authenticated=True, is_owner=False)
        with self._ctx(app, '9.9.9.9'):
            with patch('flask_login.current_user', user):
                assert owner_ip_check(_ok_view)() == 'OK'

    def test_owner_passes_in_debug_mode(self, app):
        owner = SimpleNamespace(is_authenticated=True, is_owner=True)
        with self._ctx(app, '9.9.9.9'):
            with patch('flask_login.current_user', owner):
                with _DebugScope(app, True):
                    assert owner_ip_check(_ok_view)() == 'OK'

    @pytest.mark.parametrize('ip', OWNER_ALLOWED_IPS)
    def test_owner_allowed_ips_pass(self, app, ip):
        owner = SimpleNamespace(is_authenticated=True, is_owner=True)
        remote = '127.0.0.1' if ip == 'localhost' else ip
        with self._ctx(app, remote):
            with patch('flask_login.current_user', owner):
                with _DebugScope(app, False):
                    assert owner_ip_check(_ok_view)() == 'OK'

    def test_owner_foreign_ip_blocked(self, app):
        from werkzeug.exceptions import Forbidden
        owner = SimpleNamespace(is_authenticated=True, is_owner=True)
        with self._ctx(app, '203.0.113.7'):
            with patch('flask_login.current_user', owner):
                with _DebugScope(app, False):
                    with pytest.raises(Forbidden):
                        owner_ip_check(_ok_view)()
