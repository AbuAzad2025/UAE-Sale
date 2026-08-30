from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, current_app
from flask_login import login_required, current_user
from extensions import db
from models import User, Role
from utils.decorators import admin_required, _role_level, _current_user_level, _enforce_target_role_not_higher, get_owned_or_404
from utils.helpers import create_audit_log

users_bp = Blueprint('users', __name__, url_prefix='/users')


def _role_level_local(slug):
    """Local role-level map for filtering the role dropdown.
    Kept here so the filter is visible in one place; the canonical
    ranking lives in ``utils.decorators._role_level``.
    """
    return _role_level(Role(slug=slug) if slug else None) if False else _role_level(_role_obj_for(slug))


def _role_obj_for(slug):
    """Best-effort role stub for the local level map.  We only need the
    slug to map to a level, so build a lightweight object that satisfies
    ``_role_level``'s contract (``role.slug``)."""
    class _R:
        pass
    r = _R()
    r.slug = slug
    return r


@users_bp.route('/')
@login_required
def index():
    if not current_user.has_permission('manage_users'):
        flash('⛔ ليس لديك صلاحية لإدارة المستخدمين.', 'danger')
        return redirect(url_for('main.dashboard'))

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)

    query = User.query.filter_by(is_owner=False, is_active=True)

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
                           pagination=pagination)


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

    if request.method == 'POST':
        try:
            role_id = request.form.get('role_id', type=int)
            if not role_id:
                flash('⚠️ يرجى اختيار الدور الوظيفي.', 'warning')
                form_values = request.form.to_dict()
                form_values['is_active'] = request.form.get('is_active', '1')
                return render_template('users/create.html', roles=roles, form_data=form_values)

            # SECURITY: Re-validate the chosen role server-side against the
            # current user's privilege level. The dropdown is filtered, but
            # body tampering must not be able to inject a higher role.
            target_role = Role.query.get(role_id)
            if target_role is None:
                flash('⚠️ الدور المختار غير صالح.', 'danger')
                return render_template('users/create.html', roles=roles,
                                       form_data=request.form.to_dict())
            _enforce_target_role_not_higher(target_role)

            is_active = request.form.get('is_active', '1') == '1'

            user = User(
                username=request.form.get('username'),
                email=request.form.get('email'),
                full_name=request.form.get('full_name'),
                full_name_ar=request.form.get('full_name_ar'),
                phone=request.form.get('phone'),
                role_id=role_id,
                is_owner=False,  # SECURITY: never let non-owner routes create owners
                tenant_id=getattr(current_user, 'tenant_id', None),  # SECURITY: same tenant
                is_active=is_active
            )

            password = request.form.get('password')

            # SECURITY: Enforce password strength policy
            from utils.password_validator import PasswordValidator
            is_valid, errors = PasswordValidator.validate(password or '')
            if not is_valid:
                flash('⚠️ كلمة المرور ضعيفة:\n' + '\n'.join(errors), 'danger')
                form_values = request.form.to_dict()
                form_values['is_active'] = request.form.get('is_active', '1')
                return render_template('users/create.html', roles=roles, form_data=form_values)

            user.set_password(password)

            db.session.add(user)
            db.session.flush()

            create_audit_log('create', 'users', user.id)

            db.session.commit()

            flash('✅ تم إضافة المستخدم بنجاح!', 'success')
            return redirect(url_for('users.index'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'User creation error: {e}')
            flash('❌ حدث خطأ في إنشاء المستخدم. يرجى المحاولة مرة أخرى.', 'danger')
            form_values = request.form.to_dict()
            form_values['is_active'] = request.form.get('is_active', '1')
            return render_template('users/create.html', roles=roles, form_data=form_values)

    return render_template('users/create.html', roles=roles, form_data=default_form)


@users_bp.route('/<int:id>')
@login_required
def view(id):
    if not current_user.has_permission('manage_users'):
        abort(403)

    # SECURITY: cross-tenant check via get_owned_or_404.
    user = get_owned_or_404(User, id, code=404)
    if user.is_owner:
        abort(404)
    return render_template('users/view.html', user=user)


@users_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit(id):
    # SECURITY: use get_owned_or_404 to enforce cross-tenant isolation
    # in addition to the @admin_required role gate.
    user = get_owned_or_404(User, id, code=404)
    if user.is_owner:
        # Owner accounts cannot be edited through this route.
        abort(404)

    if request.method == 'POST':
        try:
            user.email = request.form.get('email')
            user.full_name = request.form.get('full_name')
            user.full_name_ar = request.form.get('full_name_ar')
            user.phone = request.form.get('phone')

            # SECURITY: server-side role-level re-validation. The dropdown
            # is filtered to ≤ current user's level, but body tampering
            # could try to inject a higher role. Reject 403.
            new_role_id = request.form.get('role_id', type=int)
            if new_role_id and new_role_id != user.role_id:
                new_role = Role.query.get(new_role_id)
                if new_role is None:
                    flash('⚠️ الدور المختار غير صالح.', 'danger')
                    return redirect(url_for('users.edit', id=user.id))
                _enforce_target_role_not_higher(new_role)
                user.role_id = new_role_id

            new_password = request.form.get('new_password')
            if new_password:
                from utils.password_validator import PasswordValidator
                is_valid, errors = PasswordValidator.validate(new_password)
                if not is_valid:
                    flash('⚠️ كلمة المرور ضعيفة:\n' + '\n'.join(errors), 'danger')
                    return redirect(url_for('users.edit', id=user.id))
                user.set_password(new_password)

            db.session.commit()

            create_audit_log('update', 'users', user.id)

            flash('✅ تم تحديث بيانات المستخدم بنجاح!', 'success')
            return redirect(url_for('users.view', id=user.id))

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
        abort(404)

    user.is_active = not user.is_active
    db.session.commit()

    status_msg = 'تفعيل' if user.is_active else 'إلغاء تفعيل'
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
    if user.is_owner:
        # Never allow owner account to be deleted through this route.
        abort(404)

    if user.id == current_user.id:
        flash('⚠️ لا يمكنك حذف حسابك الخاص.\n💡 اطلب من مدير آخر حذف حسابك إذا لزم الأمر.', 'danger')
        return redirect(url_for('users.index'))

    try:
        from models import Sale
        sales_count = Sale.query.filter_by(seller_id=id).count()

        if sales_count > 0:
            user.is_active = False
            db.session.commit()
            flash(f'⚠️ تم إلغاء تفعيل المستخدم "{user.username}" (لديه {sales_count} عملية مسجلة).\n💡 لا يمكن حذفه نهائياً للحفاظ على السجلات.', 'warning')
            create_audit_log('deactivate', 'users', id)
        else:
            username = user.username
            db.session.delete(user)
            db.session.commit()
            flash(f'✅ تم حذف المستخدم "{username}" نهائياً!', 'success')
            create_audit_log('delete', 'users', id)

        return redirect(url_for('users.index'))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'User delete error: {e}')
        flash('❌ حدث خطأ في حذف المستخدم.', 'danger')
        return redirect(url_for('users.index'))


@users_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Self-service password change — any authenticated user can change their own password."""
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Verify current password
        if not current_user.check_password(current_password):
            flash('❌ كلمة المرور الحالية غير صحيحة.', 'danger')
            return render_template('users/change_password.html')

        # Validate new password matches confirmation
        if new_password != confirm_password:
            flash('❌ كلمة المرور الجديدة غير متطابقة.', 'danger')
            return render_template('users/change_password.html')

        # Enforce password strength policy
        from utils.password_validator import PasswordValidator
        is_valid, errors = PasswordValidator.validate(new_password)
        if not is_valid:
            flash('⚠️ كلمة المرور ضعيفة:\n' + '\n'.join(errors), 'danger')
            return render_template('users/change_password.html')

        # Prevent reusing the current password
        if current_user.check_password(new_password):
            flash('❌ كلمة المرور الجديدة يجب أن تختلف عن الحالية.', 'danger')
            return render_template('users/change_password.html')

        # Update password
        current_user.set_password(new_password)
        db.session.commit()
        create_audit_log('change_password', 'users', current_user.id)
        flash('✅ تم تغيير كلمة المرور بنجاح!', 'success')
        return redirect(url_for('users.change_password'))

    return render_template('users/change_password.html')
