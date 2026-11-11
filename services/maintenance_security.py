"""Explicit tenant and actor checks for maintenance operations.

The generic ownership helper permits platform actors and unauthenticated
service callers to bypass tenant checks. Maintenance must instead always run
in an authenticated, explicitly selected tenant context.
"""
from flask import has_request_context
from flask_login import current_user

from models.tenant_scope import get_current_tenant_id
from models.maintenance import MaintenanceOrder
from utils.errors import ValidationError
from utils.feature_guards import is_feature_enabled


def current_maintenance_tenant():
    if (not has_request_context() or not getattr(current_user, 'is_authenticated', False)
            or not getattr(current_user, 'is_active', False)):
        raise ValidationError('يجب تسجيل الدخول ضمن حساب التينانت')
    tenant_id = get_current_tenant_id()
    if not isinstance(tenant_id, int) or tenant_id <= 0:
        raise ValidationError('يجب اختيار تينانت قبل استخدام الصيانة')
    platform_actor = bool(current_user.is_owner or current_user.is_super_admin())
    if not platform_actor and current_user.tenant_id != tenant_id:
        raise ValidationError('نطاق التينانت غير صالح')
    if not is_feature_enabled('maintenance'):
        raise ValidationError('ميزة الصيانة غير مفعلة لهذا التينانت')
    return tenant_id


def require_maintenance_actor(user_id, permission):
    tenant_id = current_maintenance_tenant()
    if current_user.id != user_id or not current_user.has_permission(permission):
        raise ValidationError('ليست لديك صلاحية تنفيذ هذا الإجراء')
    return tenant_id


def get_maintenance_order(order_id, *, for_update=False):
    tenant_id = current_maintenance_tenant()
    query = MaintenanceOrder.query.filter_by(id=order_id, tenant_id=tenant_id)
    if for_update:
        query = query.with_for_update()
    return query.first()
