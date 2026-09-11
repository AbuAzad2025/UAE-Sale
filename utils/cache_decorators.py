from functools import wraps
from flask import current_app
from extensions import cache
import fnmatch
import hashlib
import json


def _cache_scope_token():
    """Role/tenant/permission scope for cache keys.

    SECURITY: cached responses can differ per role (e.g. cost_price masked
    for sellers, present for owner) and per tenant. A role-agnostic key
    would serve an owner's cost-bearing response to a seller (cross-role
    bleed) or one tenant's numbers to another. Key on the security
    attributes that determine the response body, not the user id (so
    equivalent users still share the cache).
    """
    try:
        from flask_login import current_user

        if not getattr(current_user, 'is_authenticated', False):
            return 'anon'
        if getattr(current_user, 'is_owner', False):
            # Owner bypasses tenant filter and sees all costs.
            return 'owner'
        role_slug = getattr(getattr(current_user, 'role', None), 'slug', None) or 'norole'
        tenant = getattr(current_user, 'tenant_id', None) or '0'
        # Cost visibility is permission-driven; include the effective bit so a
        # same-slug role with divergent view_costs grants never shares a body.
        try:
            costs = 'c1' if current_user.can_see_costs() else 'c0'
        except Exception:
            costs = 'cx'
        return f'{role_slug}:{costs}:t{tenant}'
    except Exception:
        # Fail closed: never share a cached body across unknown scopes.
        return 'unknown'


def cached_query(timeout=300, key_prefix=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            scope = _cache_scope_token()
            if key_prefix:
                cache_key = f"{key_prefix}:{scope}:{hashlib.md5(json.dumps(str(args) + str(kwargs)).encode(), usedforsecurity=False).hexdigest()}"
            else:
                cache_key = f"{f.__name__}:{scope}:{hashlib.md5(json.dumps(str(args) + str(kwargs)).encode(), usedforsecurity=False).hexdigest()}"

            try:
                result = cache.get(cache_key)
            except Exception as e:
                # Cache read failure must never break the request — treat as
                # a miss and recompute (e.g. unpicklable response objects in
                # test environments, or a corrupted/evicted entry).
                try:
                    current_app.logger.warning(
                        f"Cache get failed for key {cache_key}: {str(e)}")
                except Exception:
                    pass
                result = None
            if result is not None:
                return result

            result = f(*args, **kwargs)
            try:
                cache.set(cache_key, result, timeout=timeout)
            except Exception as e:
                # If caching fails (e.g. UnboundLocalError in cachelib), log it but don't crash
                current_app.logger.warning(f"Cache set failed for key {cache_key}: {str(e)}")
            return result
        return decorated_function
    return decorator


def invalidate_cache(key_pattern):
    """Delete cached entries matching a literal key, prefix, or glob pattern.

    cached_query() builds keys as '<prefix>:<scope>:<md5>', so callers pass a
    key_prefix (e.g. 'products') rather than a full key. Passing such a
    pattern straight to delete()/delete_many() only matches literal keys, so
    prefix invalidation silently did nothing. This walks the underlying store
    (cachelib SimpleCache dict, Redis SCAN) and deletes every key that equals,
    starts with, or fnmatch-matches the pattern, then falls back to a literal
    delete for anything left.
    """
    try:
        pattern = str(key_pattern or '')

        def _matches(key):
            if isinstance(key, (bytes, bytearray)):
                key = key.decode('utf-8', 'ignore')
            else:
                key = str(key)
            return key == pattern or key.startswith(pattern) or fnmatch.fnmatch(key, pattern)

        # 1) cachelib in-memory store (SimpleCache._cache dict)
        try:
            store = getattr(getattr(cache, 'cache', None), '_cache', None)
            if isinstance(store, dict):
                for raw_key in [k for k in list(store.keys()) if _matches(k)]:
                    name = raw_key.decode('utf-8', 'ignore') if isinstance(raw_key, (bytes, bytearray)) else str(raw_key)
                    try:
                        cache.delete(name)
                    except Exception:
                        try:
                            store.pop(raw_key, None)
                        except Exception:
                            pass
        except Exception:
            pass

        # 2) Redis-backed caches via SCAN (never KEYS — production-safe)
        try:
            client = getattr(getattr(cache, 'cache', None), '_client', None)
            if client is not None and hasattr(client, 'scan_iter'):
                try:
                    for raw_key in client.scan_iter(match=f'*{pattern}*', count=200):
                        name = raw_key.decode('utf-8', 'ignore') if isinstance(raw_key, (bytes, bytearray)) else str(raw_key)
                        try:
                            cache.delete(name)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

        # 3) literal fallback (preserves old behavior for exact keys)
        try:
            cache.delete(pattern)
        except Exception:
            pass
    except Exception:
        pass
