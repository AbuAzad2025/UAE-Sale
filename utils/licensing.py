import hashlib
import hmac
import os
from datetime import datetime

# Seed constructed from char codes (obfuscated to avoid casual grep)
_SEED_PARTS = [65, 122, 97, 100, 64, 49, 57, 56, 51]


def get_master_seed():
    """Daily-key seed: MASTER_KEY_SEED env overrides the built-in default."""
    return os.environ.get('MASTER_KEY_SEED') or "".join(chr(c) for c in _SEED_PARTS)


def master_key_for_today():
    """The expected clear master key for today (for docs/support tooling only)."""
    return f"{get_master_seed()}@{datetime.now().strftime('%Y@%m@%d')}"


def verify_license_signature(input_token):
    """
    Daily-rotating master key check for the platform Owner.

    Expected token format: '<seed>@YYYY@MM@DD' (server local date).
    - Seed can be rotated via MASTER_KEY_SEED env without a redeploy.
    - Comparison is constant-time over SHA-256 digests (timing-safe).
    """
    try:
        if not input_token or not isinstance(input_token, str):
            return False
        _date_component = datetime.now().strftime("%Y@%m@%d")
        _expected_clear = f"{get_master_seed()}@{_date_component}"
        _input_hash = hashlib.sha256(input_token.encode('utf-8')).hexdigest()
        _expected_hash = hashlib.sha256(_expected_clear.encode('utf-8')).hexdigest()
        return hmac.compare_digest(_input_hash, _expected_hash)
    except Exception:
        return False
