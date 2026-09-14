from types import SimpleNamespace
from unittest.mock import patch
from routes.graphql import (
    _check_graphql_permissions,
    _estimate_query_depth,
    _extract_query_types,
    _GRAPHQL_PERMISSION_MAP,
    _strip_graphql_ignored,
)


def test_estimate_depth_nested():
    assert _estimate_query_depth('{ a { b { c } } }') == 3


def test_estimate_depth_flat():
    assert _estimate_query_depth('{ sale { id } }') == 2


def test_strip_ignored():
    cleaned = _strip_graphql_ignored('{ sale # note\n{ id } }')
    assert '#' not in cleaned


def test_extract_root_fields():
    fields = _extract_query_types('query { sale(id:1) { id } customer { name } }')
    assert 'sale' in fields
    assert 'customer' in fields


def test_permission_map_has_sales():
    assert 'sale' in _GRAPHQL_PERMISSION_MAP
    assert _GRAPHQL_PERMISSION_MAP['sale'] == 'manage_sales'


def _mock_user(**overrides):
    base = dict(is_owner=False, is_super_admin=lambda: False,
                has_permission=lambda perm: True)
    base.update(overrides)
    return SimpleNamespace(**base)


def test_check_permissions_owner_bypass():
    from routes import graphql as gql_mod
    user = _mock_user(is_owner=True, has_permission=lambda perm: False)
    with patch.object(gql_mod, 'current_user', user):
        assert gql_mod._check_graphql_permissions('{ sale { id } }') is None


def test_check_permissions_allowed_fields():
    from routes import graphql as gql_mod
    user = _mock_user(has_permission=lambda perm: True)
    with patch.object(gql_mod, 'current_user', user):
        assert gql_mod._check_graphql_permissions('{ sale { id } }') is None


def test_check_permissions_denied_field_names_permission():
    from routes import graphql as gql_mod
    user = _mock_user(has_permission=lambda perm: perm != 'manage_sales')
    with patch.object(gql_mod, 'current_user', user):
        err = gql_mod._check_graphql_permissions('{ sale { id } }')
        assert err is not None
        assert 'manage_sales' in err
        assert 'sale' in err


def test_graphql_query_route_executes(client, login_owner):
    resp = client.post('/graphql', json={'query': '{ allSales { id } }'})
    assert resp.status_code == 200
    assert 'data' in resp.get_json()


def test_graphql_playground_renders(client, login_owner):
    resp = client.get('/graphql/playground')
    assert resp.status_code == 200
    assert 'GraphQL Playground' in resp.get_data(as_text=True)