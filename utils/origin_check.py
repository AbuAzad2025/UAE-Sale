"""Exact URL origin validation (replaces insecure startswith checks)."""
from urllib.parse import urlsplit


def origin_allowed(origin, allowed):
    """Return True iff *origin* exactly matches one of the configured origins.

    Comparison is on scheme+host+port (case-insensitive host). A prefix match
    would let ``https://trusted.example.com.attacker.com`` through, so we
    parse and compare components instead.
    """
    if not origin:
        return False
    try:
        parts = urlsplit(origin)
    except Exception:
        return False
    if not parts.scheme or not parts.hostname:
        return False
    origin_key = (parts.scheme.lower(), parts.hostname.lower(), parts.port)
    for allowed_origin in allowed or []:
        try:
            ap = urlsplit(allowed_origin)
            if not ap.scheme or not ap.hostname:
                continue
            allowed_key = (ap.scheme.lower(), ap.hostname.lower(), ap.port)
            if origin_key == allowed_key:
                return True
        except Exception:
            continue
    return False
