"""Tests for services/analytics_service.py and services/advanced_analytics.py."""

from datetime import date, datetime, timedelta, time, timezone
from decimal import Decimal

import pytest

from models import (
    Donation,
    GLAccount,
    GLJournalEntry,
    GLJournalLine,
)
from services.advanced_analytics import AdvancedFinancialAnalytics
from services.analytics_service import AnalyticsService


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_days_ago(days=0, hours=0):
    return utc_now() - timedelta(days=days, hours=hours)


def make_donation(**kwargs):
    data = {
        "amount_usd": Decimal("100.00"),
        "payment_method": "crypto",
        "status": "completed",
        "transaction_type": "donation",
        "created_at": utc_days_ago(hours=1),
    }
    data.update(kwargs)
    return Donation(**data)


