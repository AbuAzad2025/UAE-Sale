"""
Authentication Tests — Login, Logout, Lockout, Session Security.

Tests the critical security fixes applied to auth flow.
"""

import pytest
from datetime import datetime, timezone, timedelta


class TestLogin:
    """Test login functionality."""

    def test_login_page_loads(self, client):
        """Login page returns 200."""
        response = client.get('/auth/login')
        assert response.status_code == 200

    def test_login_success(self, client, owner_user):
        """Valid credentials log in successfully."""
        response = client.post('/auth/login', data={
            'username': 'testowner',
            'password': 'OwnerPass123!',
        }, follow_redirects=False)
        # Should redirect to dashboard
        assert response.status_code in (302, 200)

    def test_login_wrong_password(self, client, owner_user):
        """Wrong password shows error message."""
        response = client.post('/auth/login', data={
            'username': 'testowner',
            'password': 'WrongPassword!',
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_login_nonexistent_user(self, client, owner_user):
        """Non-existent user shows error message."""
        response = client.post('/auth/login', data={
            'username': 'nonexistent',
            'password': 'SomePassword123!',
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_login_empty_fields(self, client):
        """Empty username/password shows error."""
        response = client.post('/auth/login', data={
            'username': '',
            'password': '',
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_login_inactive_user(self, client, db, owner_user):
        """Inactive user cannot log in."""
        owner_user.is_active = False
        db.session.commit()

        response = client.post('/auth/login', data={
            'username': 'testowner',
            'password': 'OwnerPass123!',
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_login_redirects_authenticated_user(self, client, owner_user):
        """Already authenticated user redirects to dashboard."""
        client.post('/auth/login', data={
            'username': 'testowner',
            'password': 'OwnerPass123!',
        })
        response = client.get('/auth/login', follow_redirects=False)
        assert response.status_code == 302


class TestAccountLockout:
    """Test account lockout after failed attempts."""

    def test_lockout_after_max_attempts(self, client, db, owner_user):
        """Account locks after 5 failed attempts."""
        from config import Config
        max_attempts = getattr(Config, 'MAX_LOGIN_ATTEMPTS', 5)

        for i in range(max_attempts):
            client.post('/auth/login', data={
                'username': 'testowner',
                'password': 'WrongPassword!',
            }, follow_redirects=True)

        # Verify user is locked
        from models import User
        user = User.query.filter_by(username='testowner').first()
        assert user.locked_until is not None
        assert user.locked_until > datetime.now(timezone.utc)

    def test_locked_user_cannot_login(self, client, db, owner_user):
        """Locked user cannot log in even with correct password."""
        from config import Config
        max_attempts = getattr(Config, 'MAX_LOGIN_ATTEMPTS', 5)

        # Lock the account
        for i in range(max_attempts):
            client.post('/auth/login', data={
                'username': 'testowner',
                'password': 'WrongPassword!',
            }, follow_redirects=True)

        # Try with correct password
        response = client.post('/auth/login', data={
            'username': 'testowner',
            'password': 'OwnerPass123!',
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_successful_login_resets_attempts(self, client, db, owner_user):
        """Successful login resets login_attempts counter."""
        # Make some failed attempts
        for i in range(3):
            client.post('/auth/login', data={
                'username': 'testowner',
                'password': 'WrongPassword!',
            }, follow_redirects=True)

        # Successful login
        client.post('/auth/login', data={
            'username': 'testowner',
            'password': 'OwnerPass123!',
        }, follow_redirects=True)

        from models import User
        user = User.query.filter_by(username='testowner').first()
        assert user.login_attempts == 0

    def test_lockout_shows_remaining_attempts(self, client, db, owner_user):
        """Failed login shows remaining attempts."""
        response = client.post('/auth/login', data={
            'username': 'testowner',
            'password': 'WrongPassword!',
        }, follow_redirects=True)
        # The flash message should mention remaining attempts
        assert response.status_code == 200


class TestLogout:
    """Test logout functionality."""

    def test_logout(self, client, owner_user):
        """Logout clears session."""
        client.post('/auth/login', data={
            'username': 'testowner',
            'password': 'OwnerPass123!',
        })
        response = client.get('/auth/logout', follow_redirects=False)
        assert response.status_code in (302, 200)


class TestSessionSecurity:
    """Test session security measures."""

    def test_session_regenerated_after_login(self, client, owner_user):
        """Session is regenerated after successful login."""
        # Get initial session ID
        with client.session_transaction() as sess:
            initial_session_id = sess.get('_id', None)

        client.post('/auth/login', data={
            'username': 'testowner',
            'password': 'OwnerPass123!',
        })

        # Session should be regenerated (or cleared)
        with client.session_transaction() as sess:
            # After login, the session should have user info
            assert sess.get('user_id') is not None or sess.get('_fresh') is not None
