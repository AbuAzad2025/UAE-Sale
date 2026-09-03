"""Unit tests for models/validators.py — F-03/F-04/F-05 decorator factories.

The factories are pure (no DB): single_parent and direction rules are
exercised with stub objects; the tenant-consistency rule uses a stub
mapper so no database round-trip is needed.
"""
import pytest
from types import SimpleNamespace

from models.validators import (
    direction_fk_validator,
    single_parent_validator,
    tenant_consistency_validator,
)


class Stub:
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def _wrap_single(*fks):
    @single_parent_validator(*fks)
    def validate(self, key, value):
        return value
    return validate


def _wrap_direction(**kw):
    @direction_fk_validator(**kw)
    def validate(self, key, value):
        return value
    return validate


# ── F-04: single parent ───────────────────────────────────────────────────────

class TestSingleParentValidator:
    def test_none_always_passes(self):
        obj = Stub(sale_id=1)
        assert _wrap_single('sale_id', 'purchase_id')(obj, 'purchase_id', None) is None

    def test_first_parent_set_ok(self):
        obj = Stub(purchase_id=None)
        assert _wrap_single('sale_id', 'purchase_id')(obj, 'sale_id', 7) == 7

    def test_second_parent_rejected(self):
        obj = Stub(sale_id=3)
        with pytest.raises(ValueError, match='mutually'):
            _wrap_single('sale_id', 'purchase_id')(obj, 'purchase_id', 9)

    def test_same_key_reassignment_ok(self):
        obj = Stub(sale_id=3, purchase_id=None)
        assert _wrap_single('sale_id', 'purchase_id')(obj, 'sale_id', 4) == 4

    def test_missing_sibling_attr_treated_as_unset(self):
        obj = Stub()
        assert _wrap_single('sale_id', 'purchase_id')(obj, 'sale_id', 1) == 1


# ── F-05: direction FK ────────────────────────────────────────────────────────

class TestDirectionFkValidator:
    RULE = dict(for_direction='outgoing', required_fk='supplier_id',
                forbidden_fk='customer_id')

    def test_other_direction_passes_through(self):
        obj = Stub(direction='incoming')
        fn = _wrap_direction(**self.RULE)
        assert fn(obj, 'customer_id', 5) == 5
        assert fn(obj, 'supplier_id', None) is None

    def test_forbidden_fk_rejected(self):
        obj = Stub(direction='outgoing')
        with pytest.raises(ValueError, match='must be NULL'):
            _wrap_direction(**self.RULE)(obj, 'customer_id', 5)

    def test_required_fk_missing_rejected(self):
        obj = Stub(direction='outgoing')
        with pytest.raises(ValueError, match='must be set'):
            _wrap_direction(**self.RULE)(obj, 'supplier_id', None)

    def test_happy_path(self):
        obj = Stub(direction='outgoing')
        fn = _wrap_direction(**self.RULE)
        assert fn(obj, 'supplier_id', 5) == 5
        assert fn(obj, 'customer_id', None) is None

    def test_missing_direction_attr_passes_through(self):
        obj = Stub()
        assert _wrap_direction(**self.RULE)(obj, 'customer_id', 5) == 5


# ── F-03: tenant consistency ──────────────────────────────────────────────────

class _FakeQuery:
    tenant_by_id = {}

    @classmethod
    def get(cls, _id):
        tenant = cls.tenant_by_id.get(_id)
        if tenant is None:
            return None
        return SimpleNamespace(tenant_id=tenant)


class _FakeParent:
    query = _FakeQuery


def _wrap_tenant(parent_fk='order_ref'):
    rel = SimpleNamespace(
        property=SimpleNamespace(mapper=SimpleNamespace(class_=_FakeParent)))
    cls = type('FakeChild', (), {parent_fk: rel})

    @tenant_consistency_validator(parent_fk)
    def validate(self, key, value):
        return value

    obj = cls()
    return obj, validate


class TestTenantConsistencyValidator:
    def test_unrelated_key_passes_through(self):
        obj, fn = _wrap_tenant()
        assert fn(obj, 'name', 'x') == 'x'

    def test_null_child_tenant_skips_check(self):
        obj, fn = _wrap_tenant()
        obj.tenant_id = None
        _FakeQuery.tenant_by_id = {4: 2}
        assert fn(obj, 'order_ref', 4) == 4

    def test_null_parent_id_skips_check(self):
        obj, fn = _wrap_tenant()
        obj.tenant_id = 1
        assert fn(obj, 'order_ref', None) is None

    def test_missing_parent_row_skips_check(self):
        obj, fn = _wrap_tenant()
        obj.tenant_id = 1
        _FakeQuery.tenant_by_id = {}
        assert fn(obj, 'order_ref', 999) == 999

    def test_matching_tenant_ok(self):
        obj, fn = _wrap_tenant()
        obj.tenant_id = 2
        _FakeQuery.tenant_by_id = {4: 2}
        assert fn(obj, 'order_ref', 4) == 4

    def test_mismatched_tenant_rejected(self):
        obj, fn = _wrap_tenant()
        obj.tenant_id = 1
        _FakeQuery.tenant_by_id = {4: 2}
        with pytest.raises(ValueError, match='cross-tenant'):
            fn(obj, 'order_ref', 4)

    def test_tenant_change_checked_against_parent(self):
        obj, fn = _wrap_tenant()
        obj.order_ref = 4
        _FakeQuery.tenant_by_id = {4: 2}
        with pytest.raises(ValueError, match='cross-tenant'):
            fn(obj, 'tenant_id', 1)
        assert fn(obj, 'tenant_id', 2) == 2
