"""
Enhanced Redis Caching Utilities
"""
import hashlib
from functools import wraps
from flask import current_app
from extensions import cache


class RedisCache:
    """Redis cache helper with advanced features"""

    @staticmethod
    def get(key):
        """Get value from cache"""
        try:
            return cache.get(key)
        except Exception as e:
            current_app.logger.warning(f"Cache get error: {e}")
            return None

    @staticmethod
    def set(key, value, timeout=None):
        """Set value in cache"""
        try:
            if timeout is None:
                timeout = current_app.config.get('CACHE_DEFAULT_TIMEOUT', 300)
            cache.set(key, value, timeout=timeout)
            return True
        except Exception as e:
            current_app.logger.warning(f"Cache set error: {e}")
            return False

    @staticmethod
    def delete(key):
        """Delete key from cache"""
        try:
            cache.delete(key)
            return True
        except Exception as e:
            current_app.logger.warning(f"Cache delete error: {e}")
            return False

    @staticmethod
    def delete_pattern(pattern):
        """Delete all keys matching pattern.

        Uses SCAN (scan_iter) when the backend client exposes it to avoid
        blocking Redis on large keyspaces; falls back to KEYS otherwise.
        """
        try:
            if hasattr(cache.cache, '_client'):
                redis_client = cache.cache._client
                full_pattern = f"*{pattern}"
                if hasattr(redis_client, 'scan_iter'):
                    keys = list(redis_client.scan_iter(match=full_pattern))
                else:
                    keys = redis_client.keys(full_pattern)
                if keys:
                    redis_client.delete(*keys)
                return True
        except Exception as e:
            current_app.logger.warning(f"Cache delete pattern error: {e}")
        return False

    @staticmethod
    def get_many(keys):
        """Get multiple values"""
        try:
            return cache.get_many(*keys)
        except Exception as e:
            current_app.logger.warning(f"Cache get_many error: {e}")
            return {}

    @staticmethod
    def set_many(mapping, timeout=None):
        """Set multiple values"""
        try:
            if timeout is None:
                timeout = current_app.config.get('CACHE_DEFAULT_TIMEOUT', 300)
            cache.set_many(mapping, timeout=timeout)
            return True
        except Exception as e:
            current_app.logger.warning(f"Cache set_many error: {e}")
            return False

    @staticmethod
    def increment(key, delta=1):
        """Increment counter"""
        try:
            return cache.cache.inc(key, delta)
        except Exception as e:
            current_app.logger.warning(f"Cache increment error: {e}")
            return None

    @staticmethod
    def decrement(key, delta=1):
        """Decrement counter"""
        try:
            return cache.cache.dec(key, delta)
        except Exception as e:
            current_app.logger.warning(f"Cache decrement error: {e}")
            return None


def _stable_key_digest(fn, args, kwargs):
    """sha256 of (module, name, args, sorted kwargs) — identical across processes
    (unlike hash(), which is PYTHONHASHSEED-randomized) and kwargs order-normalized."""
    material = repr((fn.__module__, fn.__name__, args, sorted(kwargs.items())))
    return hashlib.sha256(material.encode('utf-8')).hexdigest()


def stable_cache_key(fn, args, kwargs):
    """Process-stable cache key for ``fn`` invoked with args/kwargs."""
    return f"cached:{fn.__name__}:{_stable_key_digest(fn, args, kwargs)}"


def cached(timeout=300, key_prefix='view'):
    """
    Decorator for caching function results

    Usage:
        @cached(timeout=600, key_prefix='products')
        def get_products():
            return Product.query.all()
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            cache_key = f"{key_prefix}:{f.__name__}"

            if args or kwargs:
                cache_key += f":{_stable_key_digest(f, args, kwargs)}"

            result = RedisCache.get(cache_key)

            if result is not None:
                return result

            result = f(*args, **kwargs)

            RedisCache.set(cache_key, result, timeout=timeout)

            return result

        return decorated_function
    return decorator


def cache_model(model_name, instance_id, data, timeout=3600):
    """Cache a model instance"""
    key = f"model:{model_name}:{instance_id}"
    RedisCache.set(key, data, timeout=timeout)


def get_cached_model(model_name, instance_id):
    """Get cached model instance"""
    key = f"model:{model_name}:{instance_id}"
    return RedisCache.get(key)


def invalidate_model_cache(model_name, instance_id=None):
    """Invalidate model cache"""
    if instance_id:
        key = f"model:{model_name}:{instance_id}"
        RedisCache.delete(key)
    else:
        pattern = f"model:{model_name}:*"
        RedisCache.delete_pattern(pattern)


def cache_query_result(query_key, result, timeout=600):
    """Cache database query result"""
    key = f"query:{query_key}"
    RedisCache.set(key, result, timeout=timeout)


def get_cached_query(query_key):
    """Get cached query result"""
    key = f"query:{query_key}"
    return RedisCache.get(key)


def rate_limit_check(identifier, limit=60, window=60):
    """
    Rate limiting using Redis

    Args:
        identifier: User ID or IP address
        limit: Max requests
        window: Time window in seconds

    Returns:
        (allowed, remaining, reset_time)
    """
    key = f"ratelimit:{identifier}"

    try:
        current = RedisCache.increment(key)

        if current == 1:
            cache.cache._client.expire(key, window)

        remaining = max(0, limit - current)
        allowed = current <= limit

        ttl = cache.cache._client.ttl(key)

        return allowed, remaining, ttl
    except Exception as e:
        current_app.logger.warning(f"Rate limit error: {e}")
        return True, limit, window


def cache_customer_balance(customer_id, balance, timeout=300):
    """Cache customer balance"""
    key = f"customer_balance:{customer_id}"
    RedisCache.set(key, balance, timeout=timeout)


def get_cached_customer_balance(customer_id):
    """Get cached customer balance"""
    key = f"customer_balance:{customer_id}"
    return RedisCache.get(key)


def cache_product_stock(product_id, quantity, timeout=300):
    """Cache product stock"""
    key = f"product_stock:{product_id}"
    RedisCache.set(key, quantity, timeout=timeout)


def get_cached_product_stock(product_id):
    """Get cached product stock"""
    key = f"product_stock:{product_id}"
    return RedisCache.get(key)


def cache_dashboard_stats(user_id, stats, timeout=600):
    """Cache dashboard statistics"""
    key = f"dashboard_stats:{user_id}"
    RedisCache.set(key, stats, timeout=timeout)


def get_cached_dashboard_stats(user_id):
    """Get cached dashboard stats"""
    key = f"dashboard_stats:{user_id}"
    return RedisCache.get(key)


def invalidate_customer_cache(customer_id):
    """Invalidate all customer-related cache"""
    RedisCache.delete(f"customer_balance:{customer_id}")
    RedisCache.delete_pattern(f"*customer:{customer_id}*")


def invalidate_product_cache(product_id):
    """Invalidate all product-related cache"""
    RedisCache.delete(f"product_stock:{product_id}")
    RedisCache.delete_pattern(f"*product:{product_id}*")
