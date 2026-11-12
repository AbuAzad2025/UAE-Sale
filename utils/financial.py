"""Strict financial parsing helpers for azad_erp.

All monetary values MUST transition through `Decimal` with explicit
quantization and `ROUND_HALF_UP`. Never use `float()` for money, tax rates,
discounts, or quantities.

`parse_decimal()` rejects malformed input with `ValueError` instead of
silently coercing to 0.0.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from utils.errors import ValidationError


def parse_decimal(raw, field_name="value", quantize="0.001", allow_none=False):
    """Strictly parse a raw input into a quantized Decimal.

    Raises ValidationError (-> 400) on malformed input. Never coerces to 0.
    """
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        if allow_none:
            return None
        raise ValidationError(f"{field_name} is required")
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, bool):
        raise ValidationError(f"{field_name} must be a number, not a boolean")
    elif isinstance(raw, (int,)):
        value = Decimal(raw)
    elif isinstance(raw, float):
        # Convert via str to avoid binary float artifacts
        value = Decimal(str(raw))
    else:
        try:
            value = Decimal(str(raw).strip())
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError(f"{field_name} must be a valid number")
    try:
        q = Decimal(quantize)
        value = value.quantize(q, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{field_name} has invalid precision")
    return value


def safe_decimal(raw, default=None, quantize="0.001"):
    """Lenient variant for display/reporting only — never for financial writes."""
    try:
        return parse_decimal(raw, quantize=quantize, allow_none=(default is None))
    except ValidationError:
        return default
PYEOF