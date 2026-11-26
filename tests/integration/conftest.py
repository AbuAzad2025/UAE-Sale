from datetime import date

import pytest

from models import Tenant


@pytest.fixture
def posting_owner(db, client, login_owner):
    from models.tenant_scope import clear_current_tenant_id, set_current_tenant_id
    from services.fiscal_period_guard import ensure_current_period

    tenant = Tenant(
        name="Posting tenant",
        name_ar="منشأة الاختبار",
        slug="posting-test",
        default_currency="ILS",
    )
    db.session.add(tenant)
    db.session.flush()
    ensure_current_period(date.today().year, tenant_id=tenant.id)
    db.session.commit()
    with client.session_transaction() as session:
        session["impersonate_tenant_id"] = tenant.id
    set_current_tenant_id(tenant.id)
    try:
        yield tenant
    finally:
        clear_current_tenant_id()
