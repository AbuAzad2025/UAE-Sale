from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, current_app
from flask_login import login_required, current_user
from extensions import db
from models import User, Role, Tenant
from services.user_service import UserService
from utils.decorators import admin_required, _role_level, _current_user_level, get_owned_or_404
from utils.helpers import create_audit_log

users_bp = Blueprint('users', __name__, url_prefix='/users')


def _role_obj_for(slug):
    """Lightweight role stub satisfying ``_role_level`` (``role.slug``)."""
    class _R:
        pass
    r = _R()
    r.slug = slug
    return r


def _is_platform_owner():
    return bool(getattr(current_user, 'is_owner', False))


@users_bp.route('/')
@login_required
def index():
    if not current_user.has_permission('manage_users'):
        flash('⛔ ليس لديك صلاحية لإدارة المستخدمين.', 'danger')
        return redirect(url_for('main.dashboard'))

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)

    stats = None
    tenants = None
    tenant_filter = request.args.get('tenant_id', type=int)
    if _is_platform_owner():
        query = User.query
        if tenant_filter:
            query = query.filter_by(tenant_id=tenant_filter)
        tenants = Tenant.query.order_by(Tenant.name_ar).all()
        stats = {
            'total': User.query.count(),
            'active': User.query.filter_by(is_active=True).count(),
            'inactive': User.query.filter_by(is_active=False).count(),
            'owners': User.query.filter_by(is_owner=True).count(),
        }
    else:
        query = User.query.filter_by(is_owner=False, is_active=True)
        if getattr(current_user, 'tenant_id', None):
            query = query.filter_by(tenant_id=current_user.tenant_id)

    if search:
        search_filter = f'%{search}%'
        query = query.filter(
            db.or_(
                User.username.ilike(search_filter),
                User.email.ilike(search_filter),
                User.full_name.ilike(search_filter)
            )
        )

    pagination = query.order_by(User.username).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    return render_template('users/index.html',
                           users=pagination.items,
                           pagination=pagination,
                           stats=stats,
                           tenants=tenants,
                           tenant_filter=tenant_filter,
                           search=search)


@users_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if not current_user.has_permission('manage_users'):
        abort(403)

    current_level = _current_user_level()
    roles = Role.query.filter_by(is_active=True).all()
    # SECURITY: Never offer roles higher than the actor's own level —
    # prevents a manager from creating a super_admin in the role dropdown.
    roles = [r for r in roles if _role_level(r) <= current_level]
    default_form = {'is_active': '1'}

    # Owner may pre-scope creation to a tenant (?tenant_id= → locked banner).
    fixed_tenant = None
    if _is_platform_owner():
        fixed_tenant_id = request.args.get('tenant_id', type=int)
        if fixed_tenant_id:
            fixed_tenant = Tenant.query.get(fixed_tenant_id)
    tenants = Tenant.query.order_by(Tenant.name_ar).all() if _is_platform_owner() else []

    if request.method == 'POST':
        form_values = request.form.to_dict()
        try:
            if _is_platform_owner():
                tenant_id = fixed_tenant.id if fixed_tenant else request.form.get('tenant_id', type=int)
                is_owner = request.form.get('is_owner') == 'on'
            else:
                # SECURITY: same tenant, forced server-side; owners never
                # created outside the platform-owner path.
                tenant_id = getattr(current_user, 'tenant_id', None)
                is_owner = False
            user = UserService.provision_user(
                username=request.form.get('username'),
                email=request.form.get('email'),
                password=request.form.get('password'),
                role_id=request.form.get('role_id', type=int),
                full_name=request.form.get('full_name'),
                full_name_ar=request.form.get('full_name_ar'),
                phone=request.form.get('phone'),
                tenant_id=tenant_id,
                is_owner=is_owner,
                is_active=request.form.get('is_active', '1') == '1',
                actor=current_user,
            )
            create_audit_log('create', 'users', user.id)
            flash('✅ تم إضافة المستخدم بنجاح!', 'success')
            if fixed_tenant:
                return redirect(url_for('owner.tenant_detail', id=fixed_tenant.id))
            return redirect(url_for('users.index'))
        except ValueError as e:
            flash(f'⚠️ {str(e)}', 'danger')
            return render_template('users/create.html', roles=roles,
                                   form_data=form_values, tenants=tenants,
                                   fixed_tenant=fixed_tenant)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'User creation error: {e}')
            flash('❌ حدث خطأ في إنشاء المستخدم. يرجى المحاولة مرة أخرى.', 'danger')
            return render_template('users/create.html', roles=roles,
                                   form_data=form_values, tenants=tenants,
                                   fixed_tenant=fixed_tenant)

    return render_template('users/create.html', roles=roles,
                           form_data=default_form, tenants=tenants,
                           fixed_tenant=fixed_tenant)


@users_bp.route('/<int:id>')
@login_required
def view(id):
    if not current_user.has_permission('manage_users'):
        abort(403)

    # SECURITY: cross-tenant check via get_owned_or_404.
    user = get_owned_or_404(User, id, code=404)
    if user.is_owner and not _is_platform_owner():
        abort(404)

    # User-scoped activity (never global counters).
    from models import Sale, Payment, AuditLog
    sales_q = Sale.query.filter_by(seller_id=user.id)
    stats = {
        'sales_count': sales_q.count(),
        'sales_total': float(sum((s.amount_base or 0) for s in sales_q.all()) or 0),
        'payments_total': float(sum(
            (p.amount_base or 0)
            for p in Payment.query.filter_by(user_id=user.id).all()) or 0),
        'audits_count': AuditLog.query.filter_by(user_id=user.id).count(),
    }
    recent_sales = sales_q.order_by(Sale.sale_date.desc()).limit(5).all()
    recent_audits = AuditLog.query.filter_by(user_id=user.id).order_by(
        AuditLog.created_at.desc()).limit(10).all()
    return render_template('users/view.html', user=user, stats=stats,
                           recent_sales=recent_sales,
                           recent_audits=recent_audits)


@users_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit(id):
    # SECURITY: use get_owned_or_404 to enforce cross-tenant isolation
    # in addition to the @admin_required role gate.
    user = get_owned_or_404(User, id, code=404)
    if user.is_owner and not _is_platform_owner():
        # Owner accounts cannot be edited through this route by non-owners.
        abort(404)

    if request.method == 'POST':
        try:
            from services.user_service import _UNCHANGED
            new_role_id = request.form.get('role_id', type=int)
            role_arg = new_role_id if new_role_id and new_role_id != user.role_id else _UNCHANGED
            if _is_platform_owner():
                owner_arg = request.form.get('is_owner') == 'on'
            else:
                owner_arg = _UNCHANGED
            UserService.update_user(
                user,
                email=request.form.get('email'),
                full_name=request.form.get('full_name'),
                full_name_ar=request.form.get('full_name_ar'),
                phone=request.form.get('phone'),
                role_id=role_arg,
                is_owner=owner_arg,
                new_password=request.form.get('new_password') or None,
                actor=current_user,
            )
            create_audit_log('update', 'users', user.id)
            flash('✅ تم تحديث بيانات المستخدم بنجاح!', 'success')
            return redirect(url_for('users.view', id=user.id))
        except ValueError as e:
            flash(f'⚠️ {str(e)}', 'danger')
            return redirect(url_for('users.edit', id=user.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'User edit error: {e}')
            flash('❌ حدث خطأ في تحديث المستخدم. يرجى المحاولة مرة أخرى.', 'danger')

    current_level = _current_user_level()
    roles = Role.query.filter_by(is_active=True).all()
    # SECURITY: only offer roles at or below the actor's level.
    roles = [r for r in roles if _role_level(r) <= current_level]
    return render_template('users/edit.html', user=user, roles=roles)


@users_bp.route('/<int:id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_active(id):
    # SECURITY: cross-tenant check before mutating.
    user = get_owned_or_404(User, id, code=404)
    if user.is_owner:
        # Owner accounts are immune here (same as the legacy rule).
        abort(404)

    updated = UserService.set_active(user, not user.is_active, current_user)

    status_msg = 'تفعيل' if updated.is_active else 'إلغاء تفعيل'
    flash(f'✅ تم {status_msg} المستخدم "{user.username}" بنجاح!', 'success')

    create_audit_log('toggle_active', 'users', user.id)

    return redirect(url_for('users.index'))


@users_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    if not current_user.has_permission('manage_users'):
        flash('⛔ ليس لديك صلاحية لحذف المستخدمين.', 'danger')
        return redirect(url_for('users.index'))

    # SECURITY: cross-tenant check before mutating.
    user = get_owned_or_404(User, id, code=404)
    if user.is_owner and not _is_platform_owner():
        # Never allow owner account to be deleted through this route.
        abort(404)

    try:
        outcome = UserService.delete_user(user, current_user)
    except ValueError as e:
        flash(f'⚠️ {str(e)}', 'danger')
        return redirect(url_for('users.index'))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'User delete error: {e}')
        flash('❌ حدث خطأ في حذف المستخدم.', 'danger')
        return redirect(url_for('users.index'))

    if outcome == 'deactivated':
        from models import Sale
        sales_count = Sale.query.filter_by(seller_id=id).count()
        flash(f'⚠️ تم إلغاء تفعيل المستخدم "{user.username}" (لديه {sales_count} عملية مسجلة).\n💡 لا يمكن حذفه نهائياً للحفاظ على السجلات.', 'warning')
        create_audit_log('deactivate', 'users', id)
    else:
        flash(f'✅ تم حذف المستخدم نهائياً!', 'success')
        create_audit_log('delete', 'users', id)

    return redirect(url_for('users.index'))


@users_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Self-service password change — any authenticated user can change their own password."""
    if request.method == 'POST':
        try:
            UserService.change_own_password(
                current_user,
                request.form.get('current_password', ''),
                request.form.get('new_password', ''),
                request.form.get('confirm_password', ''),
            )
        except ValueError as e:
            flash(f'❌ {str(e)}', 'danger')
            return render_template('users/change_password.html')

        create_audit_log('change_password', 'users', current_user.id)
        flash('✅ تم تغيير كلمة المرور بنجاح!', 'success')
        return redirect(url_for('users.change_password'))

    return render_template('users/change_password.html')
