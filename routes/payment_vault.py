"""
Payment Vault Routes - مسارات الخزينة السرية
مسارات محمية بكلمة مرور منفصلة للدفع والتبرعات
"""

from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session
from flask_login import login_required, current_user
from extensions import db, limiter
from models import PaymentVault, PaymentTransaction, PaymentLog, Donation
from utils.helpers import create_audit_log
import secrets
import string

payment_vault_bp = Blueprint('payment_vault', __name__, url_prefix='/payment-vault')


@payment_vault_bp.route('/')
@login_required
def index():
    """الصفحة الرئيسية للخزينة السرية"""
    # التحقق من صلاحيات المالك
    if not current_user.is_owner:
        flash('❌ غير مصرح - الخزينة السرية للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))
    
    return render_template('payment_vault/index.html')


@payment_vault_bp.route('/unlock', methods=['GET', 'POST'])
@login_required
@limiter.limit("5 per minute")
def unlock_vault():
    """فتح الخزينة السرية"""
    if not current_user.is_owner:
        flash('❌ غير مصرح - الخزينة السرية للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        password = request.form.get('vault_password', '').strip()
        
        if not password:
            flash('❌ يرجى إدخال كلمة مرور الخزينة', 'danger')
            return render_template('payment_vault/unlock.html')
        
        # البحث عن الخزينة أو إنشاؤها
        vault = PaymentVault.query.first()
        if not vault:
            # إنشاء خزينة جديدة
            vault = PaymentVault()
            vault.set_vault_password(password)  # كلمة المرور الأولى
            vault.nowpayments_api_key = ""
            vault.nowpayments_ipn_secret = ""
            vault.bitcoin_address = ""
            vault.is_locked = False
            db.session.add(vault)
            db.session.commit()
            
            # تسجيل العملية
            PaymentLog.log_action(
                vault_id=vault.id,
                action='vault_created',
                description='تم إنشاء الخزينة السرية',
                level='info',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            flash('✅ تم إنشاء الخزينة السرية بنجاح!', 'success')
            return redirect(url_for('payment_vault.dashboard'))
        
        # محاولة فتح الخزينة
        if vault.unlock_vault(password):
            # تسجيل العملية
            PaymentLog.log_action(
                vault_id=vault.id,
                action='vault_unlocked',
                description='تم فتح الخزينة السرية',
                level='info',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            flash('✅ تم فتح الخزينة السرية بنجاح!', 'success')
            return redirect(url_for('payment_vault.dashboard'))
        else:
            # تسجيل المحاولة الفاشلة
            PaymentLog.log_action(
                vault_id=vault.id,
                action='vault_unlock_failed',
                description=f'محاولة فتح فاشلة - كلمة مرور خاطئة',
                level='warning',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            if vault.is_locked_out():
                flash('❌ تم قفل الخزينة بسبب المحاولات الفاشلة المتكررة!', 'danger')
            else:
                flash('❌ كلمة مرور الخزينة غير صحيحة!', 'danger')
            
            return render_template('payment_vault/unlock.html')
    
    return render_template('payment_vault/unlock.html')


@payment_vault_bp.route('/dashboard')
@login_required
def dashboard():
    """لوحة تحكم الخزينة السرية"""
    if not current_user.is_owner:
        flash('❌ غير مصرح - الخزينة السرية للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # التحقق من وجود الخزينة
    vault = PaymentVault.query.first()
    if not vault:
        flash('❌ الخزينة غير موجودة، يرجى إنشاؤها أولاً', 'warning')
        return redirect(url_for('payment_vault.unlock'))
    
    # التحقق من إمكانية الوصول
    if not vault.is_vault_accessible():
        flash('❌ الخزينة مقفلة، يرجى إدخال كلمة المرور', 'warning')
        return redirect(url_for('payment_vault.unlock'))
    
    flash('✅ تم فتح الخزينة السرية بنجاح!', 'success')
    return redirect(url_for('payment_vault.settings'))


@payment_vault_bp.route('/purchases')
@login_required
def purchases():
    """عرض مشتريات النظام"""
    if not current_user.is_owner:
        flash('❌ غير مصرح - الخزينة السرية للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # التحقق من فتح الخزينة
    vault = PaymentVault.query.first()
    if not vault or vault.is_locked:
        flash('❌ يجب فتح الخزينة أولاً', 'warning')
        return redirect(url_for('payment_vault.unlock_vault'))
    
    # جلب المشتريات
    purchases = Donation.query.filter_by(payment_method='crypto').order_by(Donation.created_at.desc()).all()
    
    # إحصائيات
    total_purchases = len(purchases)
    completed_purchases = sum(1 for p in purchases if p.status == 'completed')
    pending_purchases = sum(1 for p in purchases if p.status == 'pending')
    total_amount = sum(float(p.amount_usd or 0) for p in purchases)
    
    # جلب التبرعات
    donations = Donation.query.order_by(Donation.created_at.desc()).limit(5).all()
    
    return render_template('payment_vault/purchases.html',
                         purchases=purchases,
                         donations=donations,
                         total_purchases=total_purchases,
                         completed_purchases=completed_purchases,
                         pending_purchases=pending_purchases,
                         total_amount=total_amount)


@payment_vault_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """إعدادات الخزينة السرية"""
    if not current_user.is_owner:
        flash('❌ غير مصرح - الخزينة السرية للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))
    
    vault = PaymentVault.query.first()
    if not vault or not vault.is_vault_accessible():
        flash('❌ الخزينة مقفلة، يرجى إدخال كلمة المرور', 'warning')
        return redirect(url_for('payment_vault.unlock'))
    
    if request.method == 'POST':
        # تحديث إعدادات الدفع
        vault.nowpayments_api_key = request.form.get('nowpayments_api_key', vault.nowpayments_api_key)
        vault.nowpayments_ipn_secret = request.form.get('nowpayments_ipn_secret', vault.nowpayments_ipn_secret)
        vault.bitcoin_address = request.form.get('bitcoin_address', vault.bitcoin_address)
        vault.ethereum_address = request.form.get('ethereum_address', vault.ethereum_address)
        vault.usdt_address = request.form.get('usdt_address', vault.usdt_address)
        
        # تحديث حدود الدفع
        vault.min_donation_amount = float(request.form.get('min_donation_amount', vault.min_donation_amount))
        vault.max_donation_amount = float(request.form.get('max_donation_amount', vault.max_donation_amount))
        vault.daily_limit = float(request.form.get('daily_limit', vault.daily_limit))
        
        # تحديث إعدادات الأمان
        vault.require_2fa = bool(request.form.get('require_2fa'))
        vault.auto_lock_minutes = int(request.form.get('auto_lock_minutes', vault.auto_lock_minutes))
        vault.max_failed_attempts = int(request.form.get('max_failed_attempts', vault.max_failed_attempts))
        
        vault.updated_at = datetime.utcnow()
        db.session.commit()
        
        # تسجيل العملية
        PaymentLog.log_action(
            vault_id=vault.id,
            action='settings_updated',
            description='تم تحديث إعدادات الخزينة',
            level='info',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        flash('✅ تم تحديث إعدادات الخزينة بنجاح!', 'success')
        return redirect(url_for('payment_vault.settings'))
    
    return render_template('payment_vault/settings.html', vault=vault)




@payment_vault_bp.route('/lock')
@login_required
def lock_vault():
    """قفل الخزينة"""
    if not current_user.is_owner:
        flash('❌ غير مصرح - الخزينة السرية للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))
    
    vault = PaymentVault.query.first()
    if vault:
        vault.lock_vault()
        
        # تسجيل العملية
        PaymentLog.log_action(
            vault_id=vault.id,
            action='vault_locked',
            description='تم قفل الخزينة السرية',
            level='info',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        flash('✅ تم قفل الخزينة السرية بنجاح!', 'success')
    
    return redirect(url_for('payment_vault.index'))


@payment_vault_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """تغيير كلمة مرور الخزينة"""
    if not current_user.is_owner:
        flash('❌ غير مصرح - الخزينة السرية للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))
    
    vault = PaymentVault.query.first()
    if not vault or not vault.is_vault_accessible():
        flash('❌ الخزينة مقفلة، يرجى إدخال كلمة المرور', 'warning')
        return redirect(url_for('payment_vault.unlock'))
    
    if request.method == 'POST':
        current_password = request.form.get('current_password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        if not current_password or not new_password or not confirm_password:
            flash('❌ يرجى ملء جميع الحقول', 'danger')
            return render_template('payment_vault/change_password.html')
        
        if not vault.check_vault_password(current_password):
            flash('❌ كلمة المرور الحالية غير صحيحة', 'danger')
            return render_template('payment_vault/change_password.html')
        
        if new_password != confirm_password:
            flash('❌ كلمة المرور الجديدة غير متطابقة', 'danger')
            return render_template('payment_vault/change_password.html')
        
        if len(new_password) < 8:
            flash('❌ كلمة المرور يجب أن تكون 8 أحرف على الأقل', 'danger')
            return render_template('payment_vault/change_password.html')
        
        # تحديث كلمة المرور
        vault.set_vault_password(new_password)
        vault.updated_at = datetime.utcnow()
        db.session.commit()
        
        # تسجيل العملية
        PaymentLog.log_action(
            vault_id=vault.id,
            action='password_changed',
            description='تم تغيير كلمة مرور الخزينة',
            level='info',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        flash('✅ تم تغيير كلمة مرور الخزينة بنجاح!', 'success')
        return redirect(url_for('payment_vault.dashboard'))
    
    return render_template('payment_vault/change_password.html')
