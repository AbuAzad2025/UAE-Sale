"""Daily-rotating master key for the platform Owner.

The Owner account authenticates exclusively with a daily-rotating master
key of the form ``<seed>@YYYY@MM@DD`` (UTC date). No fixed password is
ever planted for the Owner.

Security properties:
- Constant-time comparison (SHA-256 + hmac.compare_digest).
- Seed resolution order (first non-empty wins):
    1. ``MASTER_KEY_SEED`` env var (operator-controlled, rotatable).
    2. ``instance/master_seed`` file (auto-generated on first boot and
       persisted so the owner can always log in on any deployment).
- A seed is auto-generated on first boot if neither source provides one,
  so the owner can ALWAYS authenticate on any deployment without
  pre-configuration. The generated seed is logged once for the operator to
  save.
- UTC date is used consistently to avoid timezone drift.
- Input format is validated before hashing.
"""

import hashlib
import hmac
import os
import re
import secrets as _secrets
from datetime import datetime, timezone

_MASTER_KEY_PATTERN = re.compile(r"^.+@\d{4}@\d{2}@\d{2}$")

_seed_cache: dict = {"value": None}


def _instance_dir() -> str:
    try:
        from config import instance_dir

        return instance_dir
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance")


def _is_production() -> bool:
    app_env = os.environ.get(
        "APP_ENV", os.environ.get("FLASK_ENV", "production")
    ).lower()
    return app_env == "production"


def get_master_seed() -> str:
    """Return the master key seed.

    Resolution order:
        1. ``MASTER_KEY_SEED`` env var (operator-controlled).
        2. ``instance/master_seed`` file (auto-generated & persisted).
        3. Auto-generate, persist, and log (guarantees owner can always log in).

    Result is cached per process.
    """
    cached = _seed_cache["value"]
    if cached is not None:
        return cached

    seed = os.environ.get("MASTER_KEY_SEED", "").strip()
    if seed:
        _seed_cache["value"] = seed
        return seed

    seed_file = os.path.join(_instance_dir(), "master_seed")
    if os.path.exists(seed_file):
        try:
            with open(seed_file, "r", encoding="utf-8") as f:
                seed = f.read().strip()
            if seed:
                _seed_cache["value"] = seed
                return seed
        except Exception:
            pass

    seed = _secrets.token_urlsafe(32)
    try:
        os.makedirs(_instance_dir(), exist_ok=True)
        with open(seed_file, "w", encoding="utf-8") as f:
            f.write(seed)
    except Exception:
        pass

    try:
        import logging

        logging.getLogger(__name__).warning(
            "MASTER_KEY_SEED not set; auto-generated seed persisted to "
            "%s. Save this seed to log in as Owner: %s",
            seed_file,
            seed,
        )
    except Exception:
        pass

    _seed_cache["value"] = seed
    return seed


def master_key_for_date(target_date=None) -> str:
    """Return the clear master key for a given date (UTC).

    Defaults to today (UTC). Useful for support tooling.
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.astimezone(timezone.utc).date()
    return f"{get_master_seed()}@{target_date.strftime('%Y@%m@%d')}"


def master_key_for_today() -> str:
    """The expected clear master key for today (UTC)."""
    return master_key_for_date()


def verify_license_signature(input_token) -> bool:
    """Verify a daily-rotating master key.

    Expected token format: ``<seed>@YYYY@MM@DD`` (UTC date).
    - Seed can be rotated via ``MASTER_KEY_SEED`` env without a redeploy.
    - Comparison is constant-time over SHA-256 digests (timing-safe).
    - Format is validated before hashing (rejects malformed input early).
    """
    try:
        if not input_token or not isinstance(input_token, str):
            return False
        token = input_token.strip()
        if not _MASTER_KEY_PATTERN.match(token):
            return False

        _date_component = datetime.now(timezone.utc).strftime("%Y@%m@%d")
        _expected_clear = f"{get_master_seed()}@{_date_component}"
        _input_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        _expected_hash = hashlib.sha256(_expected_clear.encode("utf-8")).hexdigest()
        return hmac.compare_digest(_input_hash, _expected_hash)
    except Exception:
        return False


def clear_seed_cache() -> None:
    """Clear the cached seed (for testing)."""
    _seed_cache["value"] = None
