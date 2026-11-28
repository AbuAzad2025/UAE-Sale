"""GROQ / LLM response cache — reduce API costs.

- In-memory TTL cache keyed by (provider, model, tenant-scoped prompt hash).
- Thread-safe, zero-dependency, graceful degradation.
- Records hit/miss into AIMetricsCollector when available.

Tenant safety: the legacy key (provider, model, prompt) was shared across all
companies, so a grounded answer produced for tenant A could be served to
tenant B. The prompt scope is now computed by ``ai_cache_tenant.make_key``
which binds tenant_id, user_id, cost visibility and locale. Callers should
pass those scope values; omitting them degrades to an unscoped key (kept only
for backwards compatibility with direct unit tests).
"""

import hashlib
import threading
import time

_TTL_SECONDS = 3600  # 1 hour default
_MAX_ENTRIES = 500

_lock = threading.Lock()
_store = {}  # key -> (expires_at, value)


def enabled() -> bool:
    """Is the LLM cache active?

    Disabled when tests run (APP_ENV=testing or Flask TESTING) so mocked
    HTTP layers stay deterministic, or explicitly via AI_CACHE_ENABLED=0.
    Production behaviour is unchanged (enabled by default).
    """
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
    if not text:
        return ""
    return " ".join(str(text).strip().lower().split())


def _scope_key(
    message: str,
    knowledge_context: str,
    tenant_id=None,
    user_id=None,
    locale=None,
    can_see_costs: bool = False,
) -> str:
    """Delegate the identity/locale scope to the tenant cache key builder."""
    from services.ai_cache_tenant import make_key as tenant_make_key

    return tenant_make_key(
        tenant_id=tenant_id,
        user_id=user_id,
        can_see_costs=bool(can_see_costs),
        locale=locale or "",
        message=message,
        follow_up_topic=_normalize(knowledge_context)[:2000] or None,
    )


def make_key(
    provider: str,
    model: str,
    message: str,
    knowledge_context: str = "",
    *,
    tenant_id=None,
    user_id=None,
    locale=None,
    can_see_costs: bool = False,
) -> str:
    scope = _scope_key(
        message,
        knowledge_context,
        tenant_id,
        user_id,
        locale,
        can_see_costs,
    )
    raw = f"{provider}|{model}|{scope}|{_normalize(knowledge_context)[:2000]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get(
    provider: str,
    model: str,
    message: str,
    knowledge_context: str = "",
    *,
    tenant_id=None,
    user_id=None,
    locale=None,
    can_see_costs: bool = False,
):
    key = make_key(
        provider,
        model,
        message,
        knowledge_context,
        tenant_id=tenant_id,
        user_id=user_id,
        locale=locale,
        can_see_costs=can_see_costs,
    )
    now = time.time()
    with _lock:
        item = _store.get(key)
        if not item:
            _record_miss()
            return None
        expires_at, value = item
        if expires_at < now:
            _store.pop(key, None)
            _record_miss()
            return None
        _record_hit()
        return value


def set_value(
    provider: str,
    model: str,
    message: str,
    knowledge_context: str,
    value: str,
    *,
    tenant_id=None,
    user_id=None,
    locale=None,
    can_see_costs: bool = False,
):
    key = make_key(
        provider,
        model,
        message,
        knowledge_context,
        tenant_id=tenant_id,
        user_id=user_id,
        locale=locale,
        can_see_costs=can_see_costs,
    )
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


def clear():
    with _lock:
        _store.clear()


def stats():
    with _lock:
        return {"entries": len(_store)}


def _record_hit():
    try:
        from utils.monitoring import AIMetricsCollector

        AIMetricsCollector.record_cache_hit()
    except Exception:
        pass


def _record_miss():
    try:
        from utils.monitoring import AIMetricsCollector

        AIMetricsCollector.record_cache_miss()
    except Exception:
        pass
