"""Unit tests for AutoApprovalService — القبول التلقائي للتبرعات والمشتريات."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from models import Donation
from services.auto_approval_service import AutoApprovalService


def _old_donation(**kwargs):
    defaults = dict(
        amount_usd=Decimal("25.00"),
        payment_method="crypto",
        status="pending",
        transaction_type="donation",
        created_at=datetime.now(timezone.utc) - timedelta(hours=3),
    )
    defaults.update(kwargs)
    return Donation(**defaults)


