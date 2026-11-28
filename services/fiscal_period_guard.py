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
period, and a date with no period is NOT open. If several periods overlap,
the date is closed as soon as ANY covering period in scope is closed — an
overlapping new period can never silently re-open closed books.

    assert_period_open(document_date)      -> raises ValidationError if closed
    assert_period_open()                  -> uses today
    is_open(document_date)                -> bool, no raise
    period_for_date(document_date)        -> FiscalPeriod | None
    covering_periods(document_date)       -> all covering rows (optional lock)
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


def covering_periods(document_date=None, *, tenant_id=None, for_update=False):
    """Every fiscal period covering *document_date* in the effective scope.

    Scope is the explicit tenant plus the platform-wide rows (tenant_id NULL).
    ``for_update`` locks those rows for the caller's transaction so a period
    cannot be closed between the guard check and the posting it protects.
    """
    from models.erp_modules import FiscalPeriod
    from models.tenant_scope import get_current_tenant_id

    target = _to_date(document_date) or datetime.now(timezone.utc).date()
    tenant_id = tenant_id if tenant_id is not None else get_current_tenant_id()

    query = FiscalPeriod.query.filter(
        FiscalPeriod.start_date <= target,
        FiscalPeriod.end_date >= target,
    )
    if tenant_id is not None and hasattr(FiscalPeriod, "tenant_id"):
        query = query.filter(
            (FiscalPeriod.tenant_id == tenant_id) | (FiscalPeriod.tenant_id.is_(None))
        )
    if for_update:
        query = query.with_for_update()
    return query.all()


def _has_closed_period(scoped):
    """True when ANY covering period is closed (fail-closed on overlaps)."""
    return any(bool(getattr(p, "is_closed", False)) for p in scoped)


def _select_period(scoped):
    """Deterministic representative of a set of covering periods.

    A closed period wins over an open one — a closed year must stay closed
    even when a new overlapping period was opened on top of it — then a
    tenant-specific row wins over a platform row, then the most recent
    start_date wins. Ties no longer depend on database row order.
    """
    if not scoped:
        return None

    def _sort_key(p):
        is_global = getattr(p, "tenant_id", None) is None
        return (
            not bool(getattr(p, "is_closed", False)),
            is_global,
            -(p.start_date.toordinal() if p.start_date else 0),
        )

    return sorted(scoped, key=_sort_key)[0]


def period_for_date(document_date=None, *, tenant_id=None):
    """Return the FiscalPeriod covering *document_date*, or None.

    Deterministic and fail-closed: a closed covering period beats an open
    one, so an overlapping open period cannot silently re-open closed books.
    The previous implementation used an unordered ``.first()``, so the
    answer depended on database row order.
    """
    return _select_period(
        covering_periods(document_date, tenant_id=tenant_id)
    )


def is_open(document_date=None, *, tenant_id=None):
    """True when *document_date* is covered and NO covering period is closed.

    A date covered by NO period is NOT open. The old behaviour treated a
    missing period as open, so a year nobody created was unprotected.
    """
    scoped = covering_periods(document_date, tenant_id=tenant_id)
    return bool(scoped) and not _has_closed_period(scoped)


def _resolve_tenant_id(tenant_id=None):
    """Resolve the tenant for period provisioning (None = platform scope).

    ``TENANT_LESS_SCOPE`` (-1) means "rows with no tenant", not a tenant id,
    so it is normalised to None instead of being stamped on the row.
    """
    from models.tenant_scope import TENANT_LESS_SCOPE, get_current_tenant_id

    resolved = tenant_id if tenant_id is not None else get_current_tenant_id()
    return None if resolved == TENANT_LESS_SCOPE else resolved


def ensure_current_period(year=None, tenant_id=None):
    """Create an open annual period for *year* if none exists. Idempotent.

    The period belongs to *tenant_id* (or the current tenant). A platform
    scope (no tenant) provisions a global period, which applies to every
    tenant but is owned by the platform — a tenant cannot close it.

    Used by the application factory (a deployment must be able to post
    documents the moment it starts) and by the test fixtures, which rebuild
    the schema between tests and would otherwise leave the books with no
    writable period.
    """
    from datetime import date as _date

    from extensions import db
    from models.erp_modules import FiscalPeriod

    target_year = year or _date.today().year
    tenant_id = _resolve_tenant_id(tenant_id)

    query = FiscalPeriod.query.filter(
        FiscalPeriod.year == target_year,
        FiscalPeriod.period_type == "annual",
    )
    if tenant_id is None:
        query = query.filter(FiscalPeriod.tenant_id.is_(None))
    else:
        query = query.filter(FiscalPeriod.tenant_id == tenant_id)
    existing = query.first()
    if existing is not None:
        return existing

    period = FiscalPeriod(
        name=f"السنة المالية {target_year}",
        year=target_year,
        period_type="annual",
        start_date=_date(target_year, 1, 1),
        end_date=_date(target_year, 12, 31),
        is_closed=False,
        tenant_id=tenant_id,
    )
    db.session.add(period)
    db.session.flush()
    return period


def ensure_periods_for_active_tenants(year=None):
    """Provision *year* for every active tenant (platform scope if none).

    Booting with a single global period meant one tenant closing the year
    froze every other tenant, and a tenant manager could never close their
    own year because the period belonged to the platform. Each tenant now
    gets its own period.
    """
    from models import Tenant

    try:
        tenant_ids = [
            row.id for row in Tenant.query.filter_by(is_active=True).all()
        ]
    except Exception:
        tenant_ids = []
    if not tenant_ids:
        return [ensure_current_period(year)]
    return [ensure_current_period(year, tenant_id=tid) for tid in tenant_ids]


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


def assert_period_open(document_date=None, document_type="document", *, tenant_id=None):
    """Raise ValidationError when ANY covering period is closed.

    Overlapping periods must not re-open closed books: creating a fresh open
    period over a closed one used to let postings through whenever the
    representative period happened to be the open one. The covering rows are
    locked (where the backend supports SELECT ... FOR UPDATE) for the caller's
    transaction so a concurrent close cannot race the check.

    Importing ValidationError lazily keeps this module importable from
    models/ and services/ without a circular import.
    """
    from utils.errors import ValidationError

    target = _to_date(document_date) or datetime.now(timezone.utc).date()
    scoped = covering_periods(target, tenant_id=tenant_id, for_update=True)
    if not scoped:
        raise ValidationError(
            f"لا توجد فترة مالية معرَّفة لتاريخ {target}. "
            "أنشئ الفترة المالية أولاً قبل ترحيل المستندات."
        )

    if _has_closed_period(scoped):
        raise ValidationError(
            f"الفترة المالية بتاريخ {target} مغلقة. لا يمكن ترحيل مستند إلى فترة مغلقة."
        )
    return _select_period(scoped)
