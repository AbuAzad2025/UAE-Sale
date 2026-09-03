"""Tests for utils/error_handlers.py — no-leak error pages (HTML vs API)."""
import pytest


class TestHtmlErrorPages:
    def test_404_html(self, client):
        resp = client.get('/no-such-page-xyz')
        assert resp.status_code == 404
        assert b'Traceback' not in resp.data
        assert 'Traceback' not in resp.data.decode(errors='ignore')

    def test_405_html(self, client):
        # POST to a GET-only page
        resp = client.post('/welcome')
        assert resp.status_code == 405
        assert 'Traceback' not in resp.data.decode(errors='ignore')

    def test_403_html(self, client, db):
        from models import User, Role
        from extensions import db as _db
        role = Role(name='EPlain', name_ar='م', slug='eplain_role')
        _db.session.add(role)
        _db.session.flush()
        u = User(username='eplain', email='eplain@test.com', full_name='E',
                 is_owner=False, is_active=True, role_id=role.id)
        u.set_password('Pass123!')
        _db.session.add(u)
        _db.session.commit()
        client.post('/auth/login',
                    data={'username': 'eplain', 'password': 'Pass123!'},
                    follow_redirects=True)
        resp = client.get('/owner/dashboard')
        assert resp.status_code == 404  # stealth gate, still no leak
        assert 'Traceback' not in resp.data.decode(errors='ignore')


class TestApiErrorShapes:
    def test_api_404_json(self, client):
        resp = client.get('/api/no-such-endpoint-xyz')
        assert resp.status_code == 404
        body = resp.get_json()
        assert body['status'] == 404

    def test_api_405_json(self, client):
        resp = client.post('/api/no-such-endpoint-xyz')
        assert resp.status_code in (404, 405)
        assert resp.is_json
