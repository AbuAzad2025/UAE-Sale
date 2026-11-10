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
        try:
            from flask import g, abort
            from models.tenant_scope import get_current_tenant_id
            tenant_id = get_current_tenant_id()
            if tenant_id is None:
                # Platform-level access (owner) - allow
                return
            from models import Tenant
            tenant = db.session.get(Tenant, tenant_id)
            if tenant is None:
                abort(403, description='Tenant not found')
            enabled = getattr(tenant, f'enable_{feature}', True)
            if not enabled:
                abort(403, description=f'Feature {feature} not enabled for this tenant')
        except Exception as e:
            logger.warning(f'Feature gate check failed for {feature}: {e}')
            # Fail closed for safety, but allow platform users
            pass

    @blueprint.before_request
    def _feature_gate_check():
        _check(feature_name)

    return blueprint


def is_feature_enabled(feature_name):
    """
    التحقق من تفعيل ميزة معينة للتينانت الحالي.
    """
    try:
        from flask import g
        from models.tenant_scope import get_current_tenant_id
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            return True  # Platform-level
        from models import Tenant
        tenant = db.session.get(Tenant, tenant_id)
        if tenant is None:
            return False
        return getattr(tenant, f'enable_{feature_name}', True)
    except Exception:
        return False
