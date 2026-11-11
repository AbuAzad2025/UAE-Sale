"""
Feature Gates - بوابات الميزات (Feature Gates)
"""
import logging
from extensions import db

logger = logging.getLogger(__name__)


def install_feature_gate(blueprint, feature_name):
    """
    تركيب Feature Gate على بلوبرينت.
    إذا كان التينانتurrent لا يملك الميزة مفعلة، يُرجع استجابة رفض (403).
    """
    def _check(feature):
        from flask import abort
        from werkzeug.exceptions import HTTPException
        try:
            from models.tenant_scope import get_current_tenant_id
            tenant_id = get_current_tenant_id()
            if tenant_id is None:
                # Blueprints requiring a tenant must enforce that separately.
                return
            from models import Tenant
            tenant = db.session.get(Tenant, tenant_id)
            if tenant is None or not tenant.is_active:
                abort(403, description='Tenant not found')
            enabled = getattr(tenant, f'enable_{feature}', False)
            if not enabled:
                abort(403, description=f'Feature {feature} not enabled for this tenant')
        except HTTPException:
            raise
        except Exception:
            logger.exception('Feature gate check failed for %s', feature)
            abort(503, description='Feature availability could not be verified')

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
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            return True  # Platform-level
        from models import Tenant
        tenant = db.session.get(Tenant, tenant_id)
        if tenant is None or not tenant.is_active:
            return False
        return bool(getattr(tenant, f'enable_{feature_name}', False))
    except Exception:
        return False
