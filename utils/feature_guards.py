"""
Feature Gates - بوابات الميزات (Feature Gates)
"""

import logging
from extensions import db

logger = logging.getLogger(__name__)


# Infrastructure endpoints that must stay available regardless of a tenant's
# feature flags (enable_*): health probes, version info, CSRF token and browser error reports.
# Blocking these would break monitoring and error reporting for every tenant
# that hasn't purchased the gated feature.
_GATE_EXEMPT_ENDPOINTS = frozenset({
    "api.health", "api.healthz", "api.version", "api.client_errors",
    "api.csrf_token",
    # Reference data the UI itself needs on every page (currency label/rate).
    # Blocking it for tenants without enable_api only produces console
    # noise; it is not a paid API capability.
    "api.currency_rate",
    # Internal UI support endpoints (search pickers, payment-method fields,
    # product info/barcode). They are not the paid public API; blocking them
    # breaks ordinary pages for tenants that haven't enabled enable_api.
    "api.payment_fields",
    "api.api_search", "api.api_search_target",
    "api.api_product_info", "api.product_by_barcode", "api.products_low_stock",
    "api.check_username",
    "monitoring.health", "monitoring.metrics",
})


def install_feature_gate(blueprint, feature_name):
    """
    تركيب Feature Gate على بلوبرينت.
    إذا كان التينانتurrent لا يملك الميزة مفعلة، يُرجع استجابة رفض (403).
    """

    def _check(feature):
        from flask import abort, request
        from werkzeug.exceptions import HTTPException

        # Never gate shared infrastructure endpoints.
        if request.endpoint in _GATE_EXEMPT_ENDPOINTS:
            return

        try:
            from models.tenant_scope import get_current_tenant_id

            from models.tenant_scope import TENANT_LESS_SCOPE
            tenant_id = get_current_tenant_id()
            # None = platform/owner; TENANT_LESS_SCOPE (-1) = a tenant-less
            # context. Neither maps to a real tenant, so per-tenant feature flags cannot
            # be enforced against them — let the permission layer decide.
            if tenant_id is None or tenant_id == TENANT_LESS_SCOPE:
                return
            from models import Tenant

            tenant = db.session.get(Tenant, tenant_id)
            if tenant is None or not tenant.is_active:
                abort(403, description="Tenant not found")
            enabled = getattr(tenant, f"enable_{feature}", False)
            if not enabled:
                abort(403, description=f"Feature {feature} not enabled for this tenant")
        except HTTPException:
            raise
        except Exception:
            logger.exception("Feature gate check failed for %s", feature)
            abort(503, description="Feature availability could not be verified")

    @blueprint.before_request
    def _feature_gate_check():
        _check(feature_name)

    return blueprint


def is_feature_enabled(feature_name):
    """
    التحقق من تفعيل ميزة معينة للتينانت الحالي.
    """
    try:
        from models.tenant_scope import get_current_tenant_id

        from models.tenant_scope import TENANT_LESS_SCOPE
        tenant_id = get_current_tenant_id()
        if tenant_id is None or tenant_id == TENANT_LESS_SCOPE:
            return True  # Platform-level / tenant-less context
        from models import Tenant

        tenant = db.session.get(Tenant, tenant_id)
        if tenant is None or not tenant.is_active:
            return False
        return bool(getattr(tenant, f"enable_{feature_name}", False))
    except Exception:
        return False
