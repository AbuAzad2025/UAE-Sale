"""Tenant-safe cache for grounded AI answers."""
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import pytest

from services import ai_cache_tenant as cache


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.invalidate_all()
    yield
    cache.invalidate_all()


def test_cache_key_includes_tenant_and_user():
    k1 = cache.make_key(tenant_id=1, user_id=1, can_see_costs=False, locale="ar", message="كم عدد العملاء؟")
    k2 = cache.make_key(tenant_id=2, user_id=1, can_see_costs=False, locale="ar", message="كم عدد العملاء؟")
    k3 = cache.make_key(tenant_id=1, user_id=2, can_see_costs=False, locale="ar", message="كم عدد العملاء؟")
    assert len({k1, k2, k3}) == 3


def test_cache_key_includes_cost_visibility_and_locale():
    base = dict(tenant_id=1, user_id=1, message="ما حالة المخزون؟")
    k1 = cache.make_key(**base, can_see_costs=True, locale="ar")
    k2 = cache.make_key(**base, can_see_costs=False, locale="ar")
    k3 = cache.make_key(**base, can_see_costs=True, locale="en")
    assert len({k1, k2, k3}) == 3


def test_cache_hit_and_miss(monkeypatch):
    monkeypatch.setattr(cache, "enabled", lambda: True)
    key = cache.make_key(tenant_id=1, user_id=1, can_see_costs=False, locale="ar", message="x")
    assert cache.get(key) is None
    cache.set_value(key, {"response": "ok"})
    assert cache.get(key) == {"response": "ok"}


def test_cache_invalidated_on_commit(db, monkeypatch):
    monkeypatch.setattr(cache, "enabled", lambda: True)
    key = cache.make_key(tenant_id=1, user_id=1, can_see_costs=False, locale="ar", message="x")
    cache.set_value(key, {"response": "ok"})
    db.session.commit()
    assert cache.get(key) is None
