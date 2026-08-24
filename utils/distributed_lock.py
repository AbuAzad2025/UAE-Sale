"""
Distributed Lock — قفل موزع للعمليات الحساسة
Redis-based distributed lock for generate_number() and balance repair.

Falls back to in-process lock if Redis is unavailable.
"""

import logging
import os
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# ── Redis connection (lazy, fail-open) ──────────────────────────────────

_redis_client = None
_redis_checked = False


def _get_redis():
    """Get Redis client if available; returns None if Redis is down."""
    global _redis_client, _redis_checked

    if _redis_checked:
        return _redis_client

    _redis_checked = True
    try:
        import redis
        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        client = redis.from_url(redis_url, decode_responses=True, socket_timeout=3)
        client.ping()
        _redis_client = client
        logger.info('Distributed lock: Redis connected')
    except Exception as e:
        _redis_client = None
        logger.warning(f'Distributed lock: Redis unavailable ({e}), using in-process fallback')

    return _redis_client


# ── In-process fallback lock ───────────────────────────────────────────

_fallback_locks = {}
_fallback_lock_lock = threading.Lock()


def _get_fallback_lock(name):
    """Get or create an in-process threading lock for the given name."""
    with _fallback_lock_lock:
        if name not in _fallback_locks:
            _fallback_locks[name] = threading.Lock()
        return _fallback_locks[name]


# ── Public API ──────────────────────────────────────────────────────────

@contextmanager
def distributed_lock(name, timeout=10, blocking_timeout=5):
    """
    Context manager for distributed locking.

    Args:
        name:            Unique lock name (e.g., 'generate_number_S-2026')
        timeout:         Lock auto-release after this many seconds (safety)
        blocking_timeout: Max seconds to wait for the lock before giving up

    Yields nothing — just ensures mutual exclusion.

    Behavior:
      - If Redis is available → uses redis.lock.Lock
      - If Redis is down → falls back to threading.Lock (single-worker only)
      - If lock cannot be acquired within blocking_timeout → logs warning, proceeds anyway (fail-open)
    """
    redis = _get_redis()

    if redis is not None:
        lock = redis.lock(
            name=f'distributed_lock:{name}',
            timeout=timeout,
            blocking_timeout=blocking_timeout,
        )
        acquired = False
        try:
            acquired = lock.acquire(blocking=True)
            if not acquired:
                logger.warning(f'Distributed lock [{name}]: could not acquire within {blocking_timeout}s — proceeding (fail-open)')
            yield
        except Exception as e:
            logger.warning(f'Distributed lock [{name}]: Redis error ({e}) — proceeding (fail-open)')
            yield
        finally:
            if acquired:
                try:
                    lock.release()
                except Exception:
                    pass
    else:
        # Fallback: in-process threading lock
        lock = _get_fallback_lock(name)
        lock.acquire(timeout=blocking_timeout)
        try:
            yield
        finally:
            try:
                lock.release()
            except Exception:
                pass


def repair_distributed_lock(name, timeout=30, blocking_timeout=10):
    """
    Stricter lock for repair/critical operations.
    Logs a WARNING but still proceeds (fail-open) if lock unavailable.
    """
    return distributed_lock(name, timeout=timeout, blocking_timeout=blocking_timeout)
