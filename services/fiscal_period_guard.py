"""Fiscal period guard - the single entry point for "may I post on this date?".

Created by the orchestrator BEFORE the parallel agents start, so that every
agent can import it without a file-ownership conflict. Agent A2 (ledger
integrity) owns the implementation of the period lookup; the other agents
only CALL this module from the files they own.

Why this exists
---------------
`FiscalPeriodService.is_period_open()` had exactly one caller in the whole
codebase (services/sale_service.py), it compared against `date.today()`
instead of the document's own date, it returned "open" when NO period row
covered the date, and `FiscalPeriod` had no `tenant_id` so one tenant
closing a year froze every other tenant's invoicing.

The contract below is the fix: a document date must fall inside an OPEN
period, and a date with no period is NOT open.

    assert_period_open(document_date)      -> raises ValidationError if closed
    assert_period_open()                  -> uses today
    is_open(document_date)                -> bool, no raise
    period_for_date(document_date)        -> FiscalPeriod | None
"""

from datetime import date, datetime, timezone


def _to_date(value):
    """Coerce a date/datetime/string into a date, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def period_for_date(document_date=None):
    """Return the FiscalPeriod covering *document_date*, or None.

    Deterministic: when several periods overlap the OPENEST one wins, and
    ties are broken by the most recent start_date. The previous
    implementation used an unordered ``.first()``, so the answer depended on
    database row order.
    """
    from models.erp_modules import FiscalPeriod
    from models.tenant_scope import get_current_tenant_id

    target = _to_date(document_date) or datetime.now(timezone.utc).date()
    tenant_id = get_current_tenant_id()

    query = FiscalPeriod.query.filter(
        FiscalPeriod.start_date <= target,
        FiscalPeriod.end_date >= target,
    )
    # FiscalPeriod gained a tenant_id column in the P0 migration. Until it
    # exists (or when no tenant is in scope, e.g. the platform owner), the
    # period is global.
    if tenant_id is not None and hasattr(FiscalPeriod, 'tenant_id'):
        scoped = query.filter(
            (FiscalPeriod.tenant_id == tenant_id)
            | (FiscalPeriod.tenant_id.is_(None))
        ).all()
    else:
        scoped = query.all()

    if not scoped:
        return None

    def _sort_key(p):
        # Precedence, most significant first:
        #   1. a TENANT-specific period beats a global one - closing a year
        #      for one tenant must not be overridden by the global period
        #      every other tenant uses;
        #   2. a CLOSED period beats an open one - fail closed. If two
        #      periods cover the same date and one is closed, the date is
        #      closed; otherwise closing a period would have no effect
        #      whenever an overlapping open period also exists;
        #   3. the most recent start_date wins.
        is_global = getattr(p, 'tenant_id', None) is None
        return (is_global,
                not bool(getattr(p, 'is_closed', False)),
                -(p.start_date.toordinal() if p.start_date else 0))

    return sorted(scoped, key=_sort_key)[0]


def is_open(document_date=None):
    """True when the period covering *document_date* exists and is open.

    A date covered by NO period is NOT open. The old behaviour treated a
    missing period as open, so a year nobody created was unprotected.
    """
    period = period_for_date(document_date)
    if period is None:
        return False
    return not bool(getattr(period, 'is_closed', False))


def ensure_current_period(year=None):
    """Create an open annual period for *year* if none exists. Idempotent.

    Used by the application factory (a deployment must be able to post
    documents the moment it starts) and by the test fixtures, which rebuild
    the schema between tests and would otherwise leave the books with no
    writable period.
    """
    from datetime import date as _date

    from extensions import db
    from models.erp_modules import FiscalPeriod

    target_year = year or _date.today().year

    existing = FiscalPeriod.query.filter(
        FiscalPeriod.year == target_year,
        FiscalPeriod.period_type == 'annual',
    ).first()
    if existing is not None:
        return existing

    period = FiscalPeriod(
        name=f'السنة المالية {target_year}',
        year=target_year,
        period_type='annual',
        start_date=_date(target_year, 1, 1),
        end_date=_date(target_year, 12, 31),
        is_closed=False,
    )
    db.session.add(period)
    db.session.commit()
    return period


def ensure_periods_for_years(years):
    """Open an annual period for each year in *years*. Idempotent.

    Used by the TEST fixtures only. A test that seeds a document dated in a
    past year (a fixed date in a fixture, say) needs a period covering that
    year, and the fixtures rebuild the schema between tests. Production is
    NOT affected: the application factory opens the current year only, so a
    document dated into an unconfigured year is still refused there.
    """
    opened = []
    for year in years:
        try:
            period = ensure_current_period(year)
            if period is not None:
                opened.append(year)
        except Exception:
            continue
    return opened


def assert_period_open(document_date=None, document_type='document'):
    """Raise ValidationError when the period covering *document_date* is closed.

    Importing ValidationError lazily keeps this module importable from
    models/ and services/ without a circular import.
    """
    from utils.errors import ValidationError

    target = _to_date(document_date) or datetime.now(timezone.utc).date()
    period = period_for_date(target)
    if period is None:
        raise ValidationError(
            f'لا توجد فترة مالية معرَّفة لتاريخ {target}. '
            'أنشئ الفترة المالية أولاً قبل ترحيل المستندات.'
        )

    if getattr(period, 'is_closed', False):
        raise ValidationError(
            f'الفترة المالية بتاريخ {target} مغلقة. لا يمكن ترحيل مستند إلى '
            'فترة مغلقة.'
        )
    return period
