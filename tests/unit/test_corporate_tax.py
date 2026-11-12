"""ضريبة الشركات: الحساب، الذرّية، وعدم التكرار، وتوثيق الاستثناء."""

from decimal import Decimal

import pytest

from services.corporate_tax import compute_ct, post_corporate_tax


class _CTTenant:
    id = 777001
    corp_tax_enabled = True
    corp_tax_rate = Decimal("9.00")
    corp_tax_threshold = Decimal("375000.00")
    allowed_currencies = "AED, USD"


def test_compute_ct_below_threshold_is_zero():
    assert compute_ct(Decimal("375000"), _CTTenant()) == Decimal("0")
    assert compute_ct(Decimal("200000"), _CTTenant()) == Decimal("0")


def test_compute_ct_above_threshold():
    assert compute_ct(Decimal("575000"), _CTTenant()) == Decimal("18000.00")


def test_compute_ct_disabled():
    tenant = _CTTenant()
    tenant.corp_tax_enabled = False
    assert compute_ct(Decimal("1000000"), tenant) == Decimal("0")


def test_post_corporate_tax_is_atomic_and_idempotent(db, owner_user):
    from models.gl import GLJournalEntry

    tenant = _CTTenant()
    res1 = post_corporate_tax(tenant, Decimal("575000"))
    assert res1["posted"] is True
    assert res1["liability"] == Decimal("18000.00")

    entries = GLJournalEntry.query.filter_by(
        reference_type="CorporateTax", reference_id=tenant.id
    ).all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.is_posted and entry.total_debit == entry.total_credit

    with pytest.raises(ValueError, match="سابق"):
        post_corporate_tax(tenant, Decimal("575000"))
    assert (
        GLJournalEntry.query.filter_by(
            reference_type="CorporateTax", reference_id=tenant.id
        ).count()
        == 1
    )
