import hashlib
import hmac
import os
from datetime import datetime


def get_master_seed():
    """Daily-key seed: MASTER_KEY_SEED env is REQUIRED in production.

    No built-in default: a missing/empty seed raises RuntimeError so the
    platform cannot boot with a known, hardcoded credential.
    """
    seed = os.environ.get("MASTER_KEY_SEED", "").strip()
    if not seed:
        # Fail-closed: never fall back to a known seed.
        raise RuntimeError(
            "MASTER_KEY_SEED environment variable is required and must not be empty. "
            "Set it before starting the application."
        )
    return seed


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
        _input_hash = hashlib.sha256(input_token.encode("utf-8")).hexdigest()
        _expected_hash = hashlib.sha256(_expected_clear.encode("utf-8")).hexdigest()
        return hmac.compare_digest(_input_hash, _expected_hash)
    except Exception:
        return False
