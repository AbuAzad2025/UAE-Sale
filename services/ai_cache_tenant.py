"""Tenant-safe cache for grounded AI answers.

The legacy ``services.ai_cache`` is keyed only by (provider, model, prompt) and
is therefore unsafe for a multi-tenant ERP: a cached answer for tenant A could
be served to tenant B. This cache is strictly scoped and is invalidated on
every database commit so stale financial/stock figures are never served after
a mutation.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

_TTL_SECONDS = 60
_MAX_ENTRIES = 500

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}


def enabled() -> bool:
    import os

    if os.environ.get("AI_CACHE_ENABLED", "").lower() in ("0", "false", "no", "off"):
        return False
    if os.environ.get("APP_ENV", "").lower() == "testing":
        return False
    try:
        from flask import current_app, has_app_context

        if has_app_context() and current_app.config.get("TESTING"):
            return False
    except Exception:
        pass
    return True


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def make_key(
    *,
    tenant_id,
    user_id,
    can_see_costs: bool,
    locale: str,
    message: str,
    follow_up_topic=None,
) -> str:
    raw = (
        f"{tenant_id}|{user_id}|{int(bool(can_see_costs))}|{locale}|"
        f"{_normalize(message)}|{follow_up_topic or ''}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get(key: str):
    now = time.time()
    with _lock:
        item = _store.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < now:
            _store.pop(key, None)
            return None
        return value


def set_value(key: str, value: Any):
    with _lock:
        if len(_store) >= _MAX_ENTRIES:
            now = time.time()
            expired = [k for k, (e, _) in _store.items() if e < now]
            for k in expired[:50]:
                _store.pop(k, None)
            if len(_store) >= _MAX_ENTRIES:
                oldest = next(iter(_store))
                _store.pop(oldest, None)
        _store[key] = (time.time() + _TTL_SECONDS, value)


def invalidate_tenant(tenant_id):
    with _lock:
        for key in [k for k in list(_store)]:
            # Keys are hashes, so we cannot reverse-map; clear all on any
            # tenant write. This is safe and keeps the implementation simple.
            _store.clear()
            break


def invalidate_all():
    with _lock:
        _store.clear()


# Invalidate after every commit so financial/stock mutations never serve stale
# grounded answers.
try:
    from extensions import db
    from sqlalchemy import event

    @event.listens_for(db.session, "after_commit")
    def _invalidate_after_commit(_session):
        invalidate_all()
except Exception:
    pass
