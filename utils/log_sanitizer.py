"""
Log Sanitizer — Filters sensitive data from log messages.

Prevents accidental logging of passwords, API keys, tokens,
database credentials, and other secrets.
"""

import re

# Patterns that indicate sensitive data
SENSITIVE_PATTERNS = [
    # Passwords in connection strings
    re.compile(r'://([^:]+):([^@]+)@', re.IGNORECASE),
    # API keys
    re.compile(r'(api[_-]?key|apikey)\s*[=:]\s*["\']?([A-Za-z0-9_\-]{20,})', re.IGNORECASE),
    # Bearer tokens
    re.compile(r'(Bearer\s+[A-Za-z0-9_\-\.]+)', re.IGNORECASE),
    # Generic secrets
    re.compile(r'(secret|password|passwd|pwd)\s*[=:]\s*["\']?([^\s"\']+)', re.IGNORECASE),
    # Credit card numbers (16 digits)
    re.compile(r'\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\b'),
    # IBAN
    re.compile(r'\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b'),
]

# Replacement text
REDACTED = '***REDACTED***'


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

    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(sanitized):
            # For connection strings, mask the password
            if '://' in sanitized and '@' in sanitized:
                parts = sanitized.split('://')
                if len(parts) == 2:
                    scheme = parts[0]
                    rest = parts[1]
                    if '@' in rest:
                        user_pass, host = rest.split('@', 1)
                        if ':' in user_pass:
                            user, _ = user_pass.split(':', 1)
                            sanitized = f'{scheme}://{user}:{REDACTED}@{host}'

            # For key=value patterns
            sanitized = pattern.sub(lambda m: f'{m.group(0).split("=")[0].split(":")[0]}={REDACTED}', sanitized)

    return sanitized


class SanitizeFilter:
    """Logging filter that sanitizes sensitive data from log records."""

    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = sanitize_log_message(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: sanitize_log_message(str(v)) if isinstance(v, str) else v
                               for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    sanitize_log_message(str(a)) if isinstance(a, str) else a
                    for a in record.args
                )
        return True
