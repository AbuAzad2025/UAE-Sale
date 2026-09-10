"""UserService — the SINGLE user provisioning/mutation pipeline.

Merges the three historical stacks (owner console, tenant admin, tenant
provisioning) with the STRICTEST rule from each:

* input sanitization (owner console)
* globally-unique username AND email (tenant provisioning)
* role exists + active + at/below actor level (all stacks)
* owner-mint only by owner-actor (owner console)
* tenant quota enforcement (tenant provisioning)
* password policy everywhere
* username IMMUTABLE after creation (tenant admin — audit-trail safety)
* delete: soft when the user owns sales, hard otherwise (tenant admin)
* owners can never be deleted/deactivated through these paths
* self delete / self-demote are refused
"""
from decimal import Decimal  # noqa: F401  (kept for call-site compat)

from extensions import db
from models import Role, Tenant, User
from utils.decorators import (
    _role_level as _canon_role_level,
    _enforce_target_role_not_higher,
    get_owned_or_404,
)


_UNCHANGED = object()


def _actor_level(actor):
    if getattr(actor, 'is_owner', False):
        return 100
    return _canon_role_level(getattr(actor, 'role', None))


def _role_level_of(role_or_slug):
    if role_or_slug is None:
        return 0
    if isinstance(role_or_slug, str):
        class _R:
            pass
        r = _R()
        r.slug = role_or_slug
        return _canon_role_level(r)
    return _canon_role_level(role_or_slug)


def _clean_username(raw):
    from utils.sanitizer import InputSanitizer
    username = InputSanitizer.sanitize_text(raw or '', max_length=50) or ''
    username = username.strip()
    if not (3 <= len(username) <= 20) or not username.replace('_', '').isalnum():
        raise ValueError('اسم المستخدم: 3-20 حرفاً (أحرف لاتينية/أرقام/_).')
    if not username[0].isalpha():
        raise ValueError('اسم المستخدم يجب أن يبدأ بحرف.')
    return username


def _clean_email(raw, required=True):
    from utils.sanitizer import InputSanitizer
    email = InputSanitizer.sanitize_email(raw or '') or ''
    email = email.strip()
    if not email:
        if required:
            raise ValueError('البريد الإلكتروني مطلوب.')
        return None
    if '@' not in email or '.' not in email:
        raise ValueError('البريد الإلكتروني غير صالح.')
    return email


def _resolve_role(role_id, actor):
    if not role_id:
        raise ValueError('يرجى اختيار الدور الوظيفي.')
    try:
        role_id = int(role_id)
    except (TypeError, ValueError):
        raise ValueError('الدور المختار غير صالح.')
    role = Role.query.get(role_id)
    if role is None or not getattr(role, 'is_active', True):
        raise ValueError('الدور المختار غير صالح.')
    _enforce_target_role_not_higher(role)
    actor_level = _actor_level(actor)
    if _role_level_of(role) > actor_level:
        raise ValueError('لا يمكنك منح دور أعلى من دورك.')
    return role


def _check_password(password):
    from utils.password_validator import PasswordValidator
    valid, errors = PasswordValidator.validate(password or '')
    if not valid:
        raise ValueError('كلمة المرور ضعيفة:\n' + '\n'.join(errors))


def _check_tenant_quota(tenant_id):
    if tenant_id is None:
        return
    tenant = Tenant.query.get(tenant_id)
    if tenant is None:
        raise ValueError('المستأجر المحدد غير موجود.')
    if not tenant.is_active or tenant.is_suspended:
        raise ValueError('لا يمكن إضافة مستخدمين لمستأجر موقوف أو غير نشط.')
    if tenant.max_users is not None:
        current = User.query.filter_by(
            tenant_id=tenant.id, is_owner=False, is_active=True).count()
        if current >= tenant.max_users:
            raise ValueError(
                f'بلغ المستأجر الحد الأقصى للمستخدمين ({tenant.max_users}).')


class UserService:
    """Single choke point for every user write in the system."""

    # ------------------------------------------------------------------
    # provision
    # ------------------------------------------------------------------
    @staticmethod
    def provision_user(*, username, email, password, role_id, actor,
                       full_name=None, full_name_ar=None, phone=None,
                       tenant_id=None, is_owner=False, is_active=True):
        """Create a user with the merged strict rule-set. Commits."""
        from utils.sanitizer import InputSanitizer

        username = _clean_username(username)
        email = _clean_email(email, required=True)
        if User.query.filter_by(username=username).first() is not None:
            raise ValueError(f'اسم المستخدم "{username}" مستخدم بالفعل.')
        if User.query.filter_by(email=email).first() is not None:
            raise ValueError(f'البريد "{email}" مستخدم بالفعل.')
        role = _resolve_role(role_id, actor)
        if is_owner and not getattr(actor, 'is_owner', False):
            raise ValueError('لا يمكن إنشاء مالك جديد إلا من قِبل المالك الحالي.')
        if tenant_id is not None:
            try:
                tenant_id = int(tenant_id)
            except (TypeError, ValueError):
                raise ValueError('المستأجر المحدد غير صالح.')
        _check_tenant_quota(tenant_id)
        _check_password(password)

        user = User(
            username=username,
            email=email,
            full_name=(InputSanitizer.sanitize_text(full_name or '', max_length=100) or '').strip() or None,
            full_name_ar=(InputSanitizer.sanitize_text(full_name_ar or '', max_length=100) or '').strip() or None,
            phone=(phone or '').strip() or None,
            role_id=role.id,
            is_owner=bool(is_owner),
            tenant_id=tenant_id,
            is_active=bool(is_active),
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        db.session.commit()
        return user

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------
    @staticmethod
    def update_user(user, *, actor, email=_UNCHANGED, full_name=_UNCHANGED,
                    full_name_ar=_UNCHANGED, phone=_UNCHANGED,
                    role_id=_UNCHANGED, is_owner=_UNCHANGED,
                    is_active=_UNCHANGED, new_password=None):
        """Update a user. Username is immutable. Commits."""
        from utils.sanitizer import InputSanitizer

        if email is not _UNCHANGED:
            email = _clean_email(email, required=True)
            clash = User.query.filter_by(email=email).first()
            if clash is not None and clash.id != user.id:
                raise ValueError(f'البريد "{email}" مستخدم بالفعل.')
            user.email = email
        if full_name is not _UNCHANGED:
            user.full_name = (InputSanitizer.sanitize_text(full_name or '', max_length=100) or '').strip() or None
        if full_name_ar is not _UNCHANGED:
            user.full_name_ar = (InputSanitizer.sanitize_text(full_name_ar or '', max_length=100) or '').strip() or None
        if phone is not _UNCHANGED:
            user.phone = (phone or '').strip() or None
        if role_id is not _UNCHANGED and role_id != user.role_id:
            role = _resolve_role(role_id, actor)
            user.role_id = role.id
        if is_owner is not _UNCHANGED and bool(is_owner) != bool(user.is_owner):
            if not getattr(actor, 'is_owner', False):
                raise ValueError('لا يمكن منح صلاحية المالك لغير المالك الحالي.')
            if user.id == getattr(actor, 'id', None) and not is_owner:
                raise ValueError('لا يمكنك سحب صلاحية المالك من حسابك الخاص.')
            user.is_owner = bool(is_owner)
        if is_active is not _UNCHANGED:
            if user.is_owner:
                raise ValueError('لا يمكن تعطيل حساب مالك من هنا.')
            user.is_active = bool(is_active)
        if new_password:
            _check_password(new_password)
            user.set_password(new_password)
        if hasattr(user, 'updated_by') and getattr(actor, 'id', None):
            try:
                user.updated_by = actor.id
            except Exception:
                pass
        db.session.commit()
        return user

    # ------------------------------------------------------------------
    # activate / delete
    # ------------------------------------------------------------------
    @staticmethod
    def set_active(user, active, actor):
        """Enable/disable a user. Owners are immune here."""
        if user.is_owner:
            raise ValueError('لا يمكن تعطيل حساب مالك من هنا.')
        user.is_active = bool(active)
        db.session.commit()
        return user

    @staticmethod
    def delete_user(user, actor):
        """Delete a user: soft when they own sales, hard otherwise.

        Returns 'deactivated' | 'deleted'.
        """
        if user.is_owner:
            raise ValueError('لا يمكن حذف حساب مالك.')
        if user.id == getattr(actor, 'id', None):
            raise ValueError('لا يمكنك حذف حسابك الخاص.')
        from models import Sale
        has_sales = Sale.query.filter_by(seller_id=user.id).count() > 0
        if has_sales:
            user.is_active = False
            db.session.commit()
            return 'deactivated'
        db.session.delete(user)
        db.session.commit()
        return 'deleted'

    # ------------------------------------------------------------------
    # self-service password
    # ------------------------------------------------------------------
    @staticmethod
    def change_own_password(user, current_password, new_password,
                            confirm_password):
        """Self-service change: verifies current, forbids reuse. Commits."""
        if not user.check_password(current_password or ''):
            raise ValueError('كلمة المرور الحالية غير صحيحة.')
        if (new_password or '') != (confirm_password or ''):
            raise ValueError('كلمة المرور الجديدة غير متطابقة.')
        if user.check_password(new_password):
            raise ValueError('كلمة المرور الجديدة يجب أن تختلف عن الحالية.')
        _check_password(new_password)
        user.set_password(new_password)
        db.session.commit()
        return user

    # ------------------------------------------------------------------
    # lookups
    # ------------------------------------------------------------------
    @staticmethod
    def get_for_actor(user_id, actor):
        """Tenant-safe single-user lookup (owners bypass tenant scope)."""
        return get_owned_or_404(User, user_id)
