"""Permanent guard: a tenant's own settings never inherit later owner changes.

Rule: package/feature defaults set by the platform owner apply only when a
tenant is FIRST created. Afterwards each tenant is independent — changing
platform defaults or another tenant's settings must not leak in.
"""
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgres"),
    reason="PostgreSQL-only: needs tenant rows with real currencies",
)
D = __import__("decimal").Decimal


def _tenant(db, slug, currency):
    from models import Tenant
    t = Tenant.query.filter_by(slug=slug).first()
    if t is None:
        t = Tenant(name=slug, name_ar=slug, slug=slug, is_active=True,
                   default_currency=currency)
        db.session.add(t)
        db.session.commit()
    return t


def test_tenant_currency_independent_of_each_other(db, app):
    from services.currency_service import CurrencyService
    from models.tenant_scope import set_current_tenant_id, clear_current_tenant_id

    with app.app_context():
        a = _tenant(db, "indep-a", "AED")
        b = _tenant(db, "indep-b", "ILS")
        try:
            set_current_tenant_id(a.id)
            assert CurrencyService.get_base_currency() == "AED"
            set_current_tenant_id(b.id)
            assert CurrencyService.get_base_currency() == "ILS"
            # Changing A later must not affect B.
            a.default_currency = "USD"
            db.session.commit()
            set_current_tenant_id(b.id)
            assert CurrencyService.get_base_currency() == "ILS"
        finally:
            a.default_currency = "AED"
            db.session.commit()
            clear_current_tenant_id()


def test_invoice_settings_tenant_isolated(db, app):
    from models.invoice_settings import InvoiceSettings
    from models.tenant_scope import set_current_tenant_id, clear_current_tenant_id

    with app.app_context():
        a = _tenant(db, "iso-letter-a", "AED")
        b = _tenant(db, "iso-letter-b", "ILS")
        try:
            set_current_tenant_id(a.id)
            s0 = InvoiceSettings.get_active()
            s0.company_name_ar = "TENANT-A-ONLY"
            db.session.commit()

            set_current_tenant_id(b.id)
            s1 = InvoiceSettings.get_active()
            assert s1.company_name_ar != "TENANT-A-ONLY"
            assert s1.tenant_id == b.id
        finally:
            set_current_tenant_id(a.id)
            s0 = InvoiceSettings.get_active()
            s0.company_name_ar = "شركة أزاد"
            db.session.commit()
            clear_current_tenant_id()
