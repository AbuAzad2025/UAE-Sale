"""
Log Sanitizer — Filters sensitive data from log messages.

Prevents accidental logging of passwords, API keys, tokens,
database credentials, and other secrets.
"""

import re

SENSITIVE_PATTERNS = [
    re.compile(r"://([^:]+):([^@]+)@", re.IGNORECASE),
    re.compile(
        r'(api[_-]?key|apikey)\s*[=:]\s*["\']?([A-Za-z0-9_\-]{20,})', re.IGNORECASE
    ),
    re.compile(r"(Bearer\s+[A-Za-z0-9_\-\.]+)", re.IGNORECASE),
    re.compile(
        r'(secret|password|passwd|pwd)\s*[=:]\s*["\']?([^\s"\']+)', re.IGNORECASE
    ),
    re.compile(r"\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\b"),
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b"),
]

REDACTED = "***REDACTED***"


def _kv_replacement(match):
    """Keep the 'key=' prefix, redact the secret value."""
    head = re.split(r"[=:]", match.group(0), maxsplit=1)[0]
    return f"{head}={REDACTED}"


def _connection_replacement(match):
    """Mask only the password in 'scheme://user:password@host'."""
    inner = match.group(0)[3:-1]  # strip leading '://' and trailing '@'
    user = inner.split(":", 1)[0]
    return f"://{user}:{REDACTED}@"


_PATTERN_REPLACEMENTS = {
    0: _connection_replacement,
    1: _kv_replacement,
    2: lambda m: f"Bearer {REDACTED}",
    3: _kv_replacement,
    4: lambda m: REDACTED,
    5: lambda m: REDACTED,
}


def sanitize_log_message(message):
    """Remove sensitive data from a log message string.

    Args:
        message: The log message to sanitize

    Returns:
        Sanitized message with sensitive data replaced
    """
    if not isinstance(message, str):
        return message

    sanitized = message

    for index, pattern in enumerate(SENSITIVE_PATTERNS):
        sanitized = pattern.sub(_PATTERN_REPLACEMENTS[index], sanitized)

    return sanitized


class SanitizeFilter:
    """Logging filter that sanitizes sensitive data from log records."""

    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = sanitize_log_message(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: sanitize_log_message(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    sanitize_log_message(str(a)) if isinstance(a, str) else a
                    for a in record.args
                )
        return True
