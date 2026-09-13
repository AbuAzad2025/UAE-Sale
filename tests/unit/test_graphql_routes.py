import pytest
from routes.graphql import _estimate_query_depth, _strip_graphql_ignored, _extract_query_types, _GRAPHQL_PERMISSION_MAP


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
