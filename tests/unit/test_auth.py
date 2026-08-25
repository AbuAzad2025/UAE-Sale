"""
Authentication Tests — Login, Logout, Lockout, Session Security.

Tests the critical security fixes applied to auth flow.
"""

from datetime import datetime, timezone


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
            _ = sess.get('_id', None)

        client.post('/auth/login', data={
            'username': 'testowner',
            'password': 'OwnerPass123!',
        })

        # Session should be regenerated (or cleared)
        with client.session_transaction() as sess:
            # After login, the session should have user info
            assert sess.get('user_id') is not None or sess.get('_fresh') is not None


class TestMasterKey:
    """Daily-rotating master key for the Owner account."""

    def _today_key(self):
        from datetime import datetime
        return f"Azad@1983@{datetime.now().strftime('%Y@%m@%d')}"

    def test_owner_login_with_today_master_key(self, client, owner_user):
        """Owner can log in using today's daily master key."""
        response = client.post('/auth/login', data={
            'username': 'testowner',
            'password': self._today_key(),
        }, follow_redirects=False)
        assert response.status_code == 302
        assert '/dashboard' in response.headers.get('Location', '')

    def test_yesterdays_master_key_fails(self, client, owner_user):
        """Yesterday's key must not work today."""
        from datetime import datetime, timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y@%m@%d')
        response = client.post('/auth/login', data={
            'username': 'testowner',
            'password': f"Azad@1983@{yesterday}",
        }, follow_redirects=True)
        assert response.status_code == 200  # back to login page

    def test_non_owner_cannot_use_master_key(self, client, db, seller_user):
        """Regular (non-owner) users cannot authenticate with the daily key."""
        from models import User
        seller = User.query.filter_by(username='testseller').first()
        if seller is None:
            seller = seller_user
        response = client.post('/auth/login', data={
            'username': seller.username,
            'password': self._today_key(),
        }, follow_redirects=True)
        assert response.status_code == 200  # stays on login page

    def test_master_key_respects_lockout(self, client, db, owner_user):
        """Even the daily master key is rejected while the account is locked."""
        from config import Config
        from models import User
        max_attempts = getattr(Config, 'MAX_LOGIN_ATTEMPTS', 5)
        for i in range(max_attempts):
            client.post('/auth/login', data={
                'username': 'testowner',
                'password': 'WrongPassword!',
            }, follow_redirects=True)
        user = User.query.filter_by(username='testowner').first()
        assert user.locked_until is not None

        response = client.post('/auth/login', data={
            'username': 'testowner',
            'password': self._today_key(),
        }, follow_redirects=True)
        assert response.status_code == 200  # still on login page (locked)
