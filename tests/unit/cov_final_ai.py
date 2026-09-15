"""Backend test coverage for routes/ai.py (user setup + route registry)."""
import pytest

from models import User, Role
from extensions import db as _db


@pytest.fixture(scope='function')
def vault_owner(db):
    """Create an owner user for testing."""
    role = Role(name='Owner', name_ar='المالك', slug='owner', permissions=[])
    _db.session.add(role)
    _db.session.flush()
    u = User(
        username='testowner', email='owner@test.com', full_name='Test Owner',
        is_owner=True, is_active=True, role_id=role.id
    )
    u.set_password('OwnerPass123!')
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture(scope='function')
def vault_plain(db):
    """Create a plain user for testing."""
    role = Role(name='User', name_ar='المستخدم', slug='user', permissions=[])
    _db.session.add(role)
    _db.session.flush()
    u = User(
        username='testuser', email='testuser@test.com', full_name='Test User',
        is_owner=False, is_active=True, role_id=role.id
    )
    u.set_password('UserPass123!')
    _db.session.add(u)
    _db.session.commit()
    return u


def test_create_owner_user(vault_owner):
    """Test creation of an owner user."""
    assert vault_owner.is_owner is True
    assert vault_owner.is_active is True
    assert vault_owner.role.name == 'Owner'


def test_create_plain_user(vault_plain):
    """Test creation of a plain user."""
    assert vault_plain.is_owner is False
    assert vault_plain.is_active is True
    assert vault_plain.role.name == 'User'


def test_ai_routes_registered(app):
    """Key AI endpoints are registered on the app URL map."""
    rules = {str(r) for r in app.url_map.iter_rules()}
    assert '/ai/neural-status' in rules
    assert '/ai/chat' in rules
    assert '/ai/assistant' in rules
