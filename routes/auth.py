from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user
from extensions import db, limiter
from models import User
from utils.helpers import create_audit_log

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("100 per hour; 50 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)
        
        if not username or not password:
            flash('الرجاء إدخال اسم المستخدم وكلمة المرور', 'danger')
            return render_template('auth/login.html')
        
        user = User.query.filter_by(username=username).first()
        
        if not user or not user.check_password(password):
            flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
            create_audit_log('login_failed', 'users', None, {'username': username})
            return render_template('auth/login.html')
        
        if not user.is_active:
            flash('حسابك غير نشط، الرجاء الاتصال بالإدارة', 'danger')
            return render_template('auth/login.html')
        
        login_user(user, remember=remember)
        
        user.last_login = datetime.now(timezone.utc)
        user.login_attempts = 0
        db.session.commit()
        
        create_audit_log('login', 'users', user.id)
        
        next_page = request.args.get('next')
        if next_page and next_page.startswith('/'):
            return redirect(next_page)
        
        return redirect(url_for('main.dashboard'))
    
    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    if current_user.is_authenticated:
        create_audit_log('logout', 'users', current_user.id)
        logout_user()
        flash('تم تسجيل الخروج بنجاح', 'success')
    
    return redirect(url_for('auth.login'))

