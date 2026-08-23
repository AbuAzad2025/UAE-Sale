from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, current_app
from flask_login import login_required, current_user
from extensions import db
from models import User, Role
from utils.decorators import admin_required
from utils.helpers import create_audit_log

users_bp = Blueprint('users', __name__, url_prefix='/users')


def _role_level(slug):
    return {
        'seller': 10,
        'manager': 20,
        'super_admin': 90,
        'developer': 95,
        'owner': 100
    }.get(slug, 0)


def _current_user_level():
    if getattr(current_user, 'is_owner', False):
        return 100
    role = getattr(current_user, 'role', None)
    slug = getattr(role, 'slug', None) if role else None
    return _role_level(slug)


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
    roles = [r for r in roles if _role_level(getattr(r, 'slug', None)) <= current_level]
    default_form = {'is_active': '1'}
    
    if request.method == 'POST':
        try:
            role_id = request.form.get('role_id', type=int)
            if not role_id:
                flash('⚠️ يرجى اختيار الدور الوظيفي.', 'warning')
                form_values = request.form.to_dict()
                form_values['is_active'] = request.form.get('is_active', '1')
                return render_template('users/create.html', roles=roles, form_data=form_values)
            
            is_active = request.form.get('is_active', '1') == '1'
            
            user = User(
                username=request.form.get('username'),
                email=request.form.get('email'),
                full_name=request.form.get('full_name'),
                full_name_ar=request.form.get('full_name_ar'),
                phone=request.form.get('phone'),
                role_id=role_id,
                is_owner=False,
                is_active=is_active
            )
            
            password = request.form.get('password')
            user.set_password(password)
            
            db.session.add(user)
            db.session.flush()
            
            create_audit_log('create', 'users', user.id)
            
            db.session.commit()
            
            flash('✅ تم إضافة المستخدم بنجاح!', 'success')
            return redirect(url_for('users.index'))
        
        except Exception as e:
            db.session.rollback()
            import traceback
            error_details = traceback.format_exc()
            current_app.logger.error(f'User creation error: {error_details}')
            flash(f'❌ حدث خطأ: {str(e)}\n💡 تحقق من البيانات المدخلة وحاول مرة أخرى.', 'danger')
            form_values = request.form.to_dict()
            form_values['is_active'] = request.form.get('is_active', '1')
            return render_template('users/create.html', roles=roles, form_data=form_values)
    
    return render_template('users/create.html', roles=roles, form_data=default_form)


@users_bp.route('/<int:id>')
@login_required
def view(id):
    if not current_user.has_permission('manage_users'):
        abort(403)

    user = User.query.filter_by(id=id, is_owner=False).first_or_404()
    return render_template('users/view.html', user=user)


@users_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit(id):
    user = User.query.filter_by(id=id, is_owner=False).first_or_404()
    
    if request.method == 'POST':
        try:
            user.email = request.form.get('email')
            user.full_name = request.form.get('full_name')
            user.full_name_ar = request.form.get('full_name_ar')
            user.phone = request.form.get('phone')
            user.role_id = request.form.get('role_id', type=int)
            
            new_password = request.form.get('new_password')
            if new_password:
                user.set_password(new_password)
            
            db.session.commit()
            
            create_audit_log('update', 'users', user.id)
            
            flash('✅ تم تحديث بيانات المستخدم بنجاح!', 'success')
            return redirect(url_for('users.view', id=user.id))
        
        except Exception as e:
            db.session.rollback()
            flash(f'❌ حدث خطأ: {str(e)}\n💡 تحقق من البيانات المدخلة وحاول مرة أخرى.', 'danger')
    
    current_level = _current_user_level()
    roles = Role.query.filter_by(is_active=True).all()
    roles = [r for r in roles if _role_level(getattr(r, 'slug', None)) <= current_level]
    return render_template('users/edit.html', user=user, roles=roles)


@users_bp.route('/<int:id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_active(id):
    user = User.query.filter_by(id=id, is_owner=False).first_or_404()
    
    user.is_active = not user.is_active
    db.session.commit()
    
    status = 'تفعيل' if user.is_active else 'تعطيل'
    status_msg = 'تفعيل' if user.is_active else 'إلغاء تفعيل'
    flash(f'✅ تم {status_msg} المستخدم "{user.username}" بنجاح!', 'success')
    
    create_audit_log('toggle_active', 'users', user.id)
    
    return redirect(url_for('users.index'))


@users_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    # Check permission instead of is_owner
    if not current_user.has_permission('manage_users'):
        flash('⛔ ليس لديك صلاحية لحذف المستخدمين.', 'danger')
        return redirect(url_for('users.index'))
    
    # Ensure target is NOT owner (double check, though filter handles it)
    user = User.query.filter_by(id=id, is_owner=False).first_or_404()
    
    if user.id == current_user.id:
        flash('⚠️ لا يمكنك حذف حسابك الخاص.\n💡 اطلب من مدير آخر حذف حسابك إذا لزم الأمر.', 'danger')
        return redirect(url_for('users.index'))
    
    try:
        from models import Sale, AuditLog
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
        flash(f'❌ خطأ في الحذف: {str(e)}\n💡 راجع البيانات المدخلة.', 'danger')
        return redirect(url_for('users.index'))

