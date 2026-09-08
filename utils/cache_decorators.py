from functools import wraps
from flask import current_app
from extensions import cache
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
        return f'{role_slug}:t{tenant}'
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
    try:
        from extensions import cache
        if hasattr(cache, 'delete_many'):
            cache.delete_many(key_pattern)
        elif hasattr(cache, 'delete'):
            cache.delete(key_pattern)
    except Exception:
        pass
