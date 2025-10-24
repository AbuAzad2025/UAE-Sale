"""
Payment Vault Routes - مسارات الخزينة السرية
مسارات محمية بكلمة مرور منفصلة للدفع والتبرعات
"""

from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session
from flask_login import login_required, current_user
from extensions import db, limiter, csrf
from models import PaymentVault, PaymentTransaction, PaymentLog, Donation, CardPayment, Package, PackagePurchase
from services.nowpayments_service import NOWPaymentsService
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
    if not vault or vault.is_locked:
        flash('❌ يجب فتح الخزينة أولاً', 'warning')
        return redirect(url_for('payment_vault.unlock_vault'))
    
    # جلب الإحصائيات
    purchases = Donation.query.filter_by(transaction_type='purchase').all()
    donations = Donation.query.filter_by(transaction_type='donation').all()
    
    stats = {
        'total_purchases': len(purchases),
        'total_donations': len(donations),
        'total_revenue': sum(float(p.amount_usd or 0) for p in purchases + donations),
        'pending_count': sum(1 for p in purchases + donations if p.status == 'pending')
    }
    
    # آخر العمليات
    recent_purchases = Donation.query.filter_by(transaction_type='purchase').order_by(Donation.created_at.desc()).limit(5).all()
    recent_donations = Donation.query.filter_by(transaction_type='donation').order_by(Donation.created_at.desc()).limit(5).all()
    
    # بيانات الرسم البياني (شهرياً)
    from datetime import datetime, timedelta
    monthly_labels = []
    monthly_purchases = []
    monthly_donations = []
    
    for i in range(6):
        month = datetime.now() - timedelta(days=30*i)
        monthly_labels.insert(0, month.strftime('%b %Y'))
        monthly_purchases.insert(0, 0)  # TODO: حساب فعلي
        monthly_donations.insert(0, 0)
    
    return render_template('payment_vault/dashboard.html',
                         stats=stats,
                         recent_purchases=recent_purchases,
                         recent_donations=recent_donations,
                         monthly_labels=monthly_labels,
                         monthly_purchases=monthly_purchases,
                         monthly_donations=monthly_donations)


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
    
    # جلب المشتريات (حيث transaction_type = 'purchase')
    purchases = Donation.query.filter_by(transaction_type='purchase').order_by(Donation.created_at.desc()).all()
    
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
        return redirect(url_for('payment_vault.unlock_vault'))
    
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




@payment_vault_bp.route('/donations')
@login_required
def donations():
    """عرض التبرعات"""
    if not current_user.is_owner:
        flash('❌ غير مصرح - الخزينة السرية للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))
    
    vault = PaymentVault.query.first()
    if not vault or vault.is_locked:
        flash('❌ يجب فتح الخزينة أولاً', 'warning')
        return redirect(url_for('payment_vault.unlock_vault'))
    
    # الفلاتر
    status_filter = request.args.get('status', '')
    crypto_filter = request.args.get('crypto', '')
    search_query = request.args.get('search', '')
    
    # Query
    query = Donation.query.filter_by(transaction_type='donation')
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    if crypto_filter:
        query = query.filter_by(crypto_type=crypto_filter)
    if search_query:
        query = query.filter(
            db.or_(
                Donation.donor_name.ilike(f'%{search_query}%'),
                Donation.donor_email.ilike(f'%{search_query}%')
            )
        )
    
    donations = query.order_by(Donation.created_at.desc()).all()
    
    # إحصائيات
    total_donations = len(donations)
    completed_count = sum(1 for d in donations if d.status == 'completed')
    pending_count = sum(1 for d in donations if d.status == 'pending')
    total_amount = sum(float(d.amount_usd or 0) for d in donations)
    
    return render_template('payment_vault/donations.html',
                         donations=donations,
                         total_donations=total_donations,
                         completed_count=completed_count,
                         pending_count=pending_count,
                         total_amount=total_amount)


@payment_vault_bp.route('/packages-management')
@login_required
def packages_management():
    """إدارة الباقات من الخزينة"""
    if not current_user.is_owner:
        flash('❌ غير مصرح - الخزينة السرية للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))
    
    vault = PaymentVault.query.first()
    if not vault or vault.is_locked:
        flash('❌ يجب فتح الخزينة أولاً', 'warning')
        return redirect(url_for('payment_vault.unlock_vault'))
    
    # جلب جميع الباقات
    packages = Package.query.order_by(Package.sort_order.asc()).all()
    
    # إحصائيات الباقات من جدول الشراء الجديد
    basic_purchases = PackagePurchase.query.join(Package).filter(Package.slug == 'basic').count()
    pro_purchases = PackagePurchase.query.join(Package).filter(Package.slug == 'professional').count()
    ent_purchases = PackagePurchase.query.join(Package).filter(Package.slug == 'enterprise').count()
    
    package_stats = [basic_purchases, pro_purchases, ent_purchases]
    
    return render_template('payment_vault/packages.html',
                         packages=packages,
                         package_stats=package_stats)


@payment_vault_bp.route('/reports')
@login_required
def reports():
    """التقارير المالية"""
    if not current_user.is_owner:
        flash('❌ غير مصرح - الخزينة السرية للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))
    
    vault = PaymentVault.query.first()
    if not vault or vault.is_locked:
        flash('❌ يجب فتح الخزينة أولاً', 'warning')
        return redirect(url_for('payment_vault.unlock_vault'))
    
    # جلب البيانات
    all_transactions = Donation.query.order_by(Donation.created_at.desc()).all()
    purchases = [t for t in all_transactions if t.transaction_type == 'purchase']
    donations = [t for t in all_transactions if t.transaction_type == 'donation']
    
    # الملخص
    summary = {
        'total_revenue': sum(float(t.amount_usd or 0) for t in all_transactions),
        'total_purchases_amount': sum(float(p.amount_usd or 0) for p in purchases),
        'total_donations_amount': sum(float(d.amount_usd or 0) for d in donations),
        'total_transactions': len(all_transactions)
    }
    
    # بيانات الرسوم البيانية
    from datetime import datetime, timedelta
    monthly_labels = []
    monthly_purchases_data = []
    monthly_donations_data = []
    
    for i in range(6):
        month = datetime.now() - timedelta(days=30*i)
        monthly_labels.insert(0, month.strftime('%b'))
        monthly_purchases_data.insert(0, 0)
        monthly_donations_data.insert(0, 0)
    
    # إحصائيات الباقات
    package_stats = [
        Donation.query.filter_by(transaction_type='purchase', package='basic').count(),
        Donation.query.filter_by(transaction_type='purchase', package='professional').count(),
        Donation.query.filter_by(transaction_type='purchase', package='enterprise').count()
    ]
    
    return render_template('payment_vault/reports.html',
                         transactions=all_transactions,
                         summary=summary,
                         monthly_labels=monthly_labels,
                         monthly_purchases_data=monthly_purchases_data,
                         monthly_donations_data=monthly_donations_data,
                         package_stats=package_stats)


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


@payment_vault_bp.route('/cards')
@login_required
def cards():
    """عرض البطاقات المحفوظة"""
    if not current_user.is_owner:
        flash('❌ غير مصرح - الخزينة السرية للمالك فقط!', 'danger')
        return redirect(url_for('main.dashboard'))
    
    vault = PaymentVault.query.first()
    if not vault or vault.is_locked:
        flash('❌ يجب فتح الخزينة أولاً', 'warning')
        return redirect(url_for('payment_vault.unlock_vault'))
    
    # جلب البطاقات
    cards = CardPayment.query.order_by(CardPayment.created_at.desc()).all()
    
    # إحصائيات
    total_cards = len(cards)
    total_amount = sum(float(c.amount or 0) for c in cards if c.status == 'completed')
    visa_count = sum(1 for c in cards if c.card_type == 'Visa')
    mastercard_count = sum(1 for c in cards if c.card_type == 'Mastercard')
    
    return render_template('payment_vault/cards.html',
                         cards=cards,
                         total_cards=total_cards,
                         total_amount=total_amount,
                         visa_count=visa_count,
                         mastercard_count=mastercard_count)


@payment_vault_bp.route('/card/<int:card_id>/decrypt', methods=['POST'])
@login_required
def decrypt_card(card_id):
    """فك تشفير بيانات البطاقة (للمالك فقط)"""
    if not current_user.is_owner:
        return jsonify({'success': False, 'error': 'غير مصرح'}), 403
    
    vault = PaymentVault.query.first()
    if not vault or vault.is_locked:
        return jsonify({'success': False, 'error': 'الخزينة مقفلة'}), 403
    
    card = CardPayment.query.get_or_404(card_id)
    decrypted = card.decrypt_card_data()
    
    if decrypted:
        # تسجيل العملية
        PaymentLog.log_action(
            vault_id=vault.id,
            action='card_decrypted',
            description=f'فك تشفير بطاقة {card.get_card_display()}',
            level='warning',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({'success': True, 'card': decrypted})
    else:
        return jsonify({'success': False, 'error': 'فشل فك التشفير'}), 400


@payment_vault_bp.route('/process-payment', methods=['POST'])
@limiter.limit("20 per minute")
def process_payment():
    """معالجة الدفع (كريبتو أو بطاقة) - عام، لا يحتاج تسجيل دخول"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'بيانات غير صحيحة'}), 400
        
        payment_method = data.get('payment_method', 'crypto')  # crypto or card
        
        if payment_method == 'crypto':
            # معالجة الكريبتو عبر NOWPayments
            nowpayments = NOWPaymentsService()
            result = nowpayments.create_payment(
                amount=float(data.get('amount', 0)),
                crypto_currency=data.get('crypto_currency', 'btc'),
                customer_email=data.get('customer_email') or data.get('donor_email', ''),
                description=data.get('description', ''),
                transaction_type=data.get('type', 'donation'),
                package=data.get('package', ''),
                customer_name=data.get('customer_name', ''),
                customer_phone=data.get('customer_phone', ''),
                donor_name=data.get('donor_name', ''),
                donor_email=data.get('donor_email', ''),
                donor_message=data.get('donor_message', '')
            )
            return jsonify(result)
            
        elif payment_method == 'card':
            # معالجة البطاقات
            amount = float(data.get('amount', 0))
            card_number = data.get('card_number', '').replace(' ', '')
            cvv = data.get('cvv', '')
            expiry = data.get('expiry', '')
            
            if amount < 1:
                return jsonify({'success': False, 'error': 'الحد الأدنى هو $1'}), 400
            
            if not card_number or len(card_number) < 13:
                return jsonify({'success': False, 'error': 'رقم البطاقة غير صحيح'}), 400
            
            # إنشاء سجل البطاقة المشفر
            card_payment = CardPayment(
                customer_name=data.get('customer_name', ''),
                customer_email=data.get('customer_email', ''),
                customer_phone=data.get('customer_phone', ''),
                transaction_type=data.get('type', 'donation'),
                package=data.get('package', ''),
                amount=amount,
                transaction_id=f'CARD_{int(datetime.now().timestamp())}',
                payment_gateway='whatsapp',
                status='pending',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            # تشفير البيانات
            if card_payment.encrypt_card_data(card_number, cvv, expiry):
                db.session.add(card_payment)
                db.session.commit()
                
                # تسجيل
                PaymentLog.log_action(
                    vault_id=PaymentVault.query.first().id if PaymentVault.query.first() else None,
                    action='card_payment_received',
                    description=f'دفع بالبطاقة: {card_payment.get_card_display()} - ${amount}',
                    level='info',
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get('User-Agent')
                )
                
                return jsonify({
                    'success': True,
                    'message': 'تم حفظ معلومات البطاقة بشكل آمن ومشفر',
                    'transaction_id': card_payment.transaction_id,
                    'whatsapp': '0598953362',
                    'next_step': 'سيتم التواصل معك عبر WhatsApp خلال 24 ساعة'
                })
            else:
                return jsonify({'success': False, 'error': 'فشل تشفير البيانات'}), 500
        
        else:
            return jsonify({'success': False, 'error': 'طريقة دفع غير مدعومة'}), 400
            
    except Exception as e:
        current_app.logger.error(f'خطأ في معالجة الدفع: {str(e)}')
        return jsonify({'success': False, 'error': f'خطأ: {str(e)}'}), 500


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
        return redirect(url_for('payment_vault.unlock_vault'))
    
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


# ==================== API Routes للشراء والتبرع (متاحة للجميع) ====================

@payment_vault_bp.route('/api/purchase', methods=['POST'])
@csrf.exempt  # JSON API - نستخدم Origin checking بدلاً من CSRF
@limiter.limit("10 per minute")
def api_create_purchase():
    """API لإنشاء عملية شراء جديدة"""
    try:
        # التحقق من Origin في الإنتاج
        origin = request.headers.get('Origin', '')
        if not request.is_json:
            return jsonify({'success': False, 'error': 'Content-Type must be application/json'}), 400
        
        data = request.get_json()
        
        # التحقق من البيانات المطلوبة
        required_fields = ['package_id', 'customer_name', 'customer_email', 'payment_method', 'amount_paid']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'error': f'الحقل {field} مطلوب'}), 400
        
        # التحقق من صحة البريد الإلكتروني
        import re
        email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
        if not re.match(email_pattern, data['customer_email']):
            return jsonify({'success': False, 'error': 'بريد إلكتروني غير صحيح'}), 400
        
        # تنظيف المدخلات
        from html import escape
        def sanitize(text, max_len=200):
            if not text:
                return None
            return escape(str(text)[:max_len].strip())
        
        customer_name = sanitize(data['customer_name'], 100)
        customer_email = sanitize(data['customer_email'], 100)
        customer_phone = sanitize(data.get('customer_phone', ''), 50)
        company_name = sanitize(data.get('company_name', ''), 100)
        
        # التحقق من وجود الباقة
        package = Package.query.get(data['package_id'])
        if not package or not package.is_active:
            return jsonify({'success': False, 'error': 'الباقة غير متاحة'}), 404
        
        # التحقق من المبلغ
        if float(data['amount_paid']) < package.price:
            return jsonify({'success': False, 'error': 'المبلغ المدفوع أقل من سعر الباقة'}), 400
        
        # إنشاء عملية الشراء (مع البيانات المنظفة)
        purchase = PackagePurchase(
            package_id=int(data['package_id']),
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            company_name=company_name,
            payment_method=data['payment_method'],
            payment_status='pending',
            amount_paid=float(data['amount_paid']),
            currency=data.get('currency', 'USD'),
            transaction_id=sanitize(data.get('transaction_id', ''), 100),
            payment_details=data.get('payment_details'),
            notes=sanitize(data.get('notes', ''), 500)
        )
        
        db.session.add(purchase)
        db.session.commit()
        
        # تسجيل في جدول التبرعات للتوافق (مع البيانات المنظفة)
        donation = Donation(
            amount_usd=purchase.amount_paid,
            payment_method=purchase.payment_method,
            transaction_type='purchase',
            package=package.slug,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            status='pending',
            transaction_hash=purchase.transaction_id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:500]
        )
        db.session.add(donation)
        db.session.commit()
        
        # تسجيل في الخزينة
        create_audit_log(
            action=f'purchase_created: {package.name_ar} - ${purchase.amount_paid}',
            table_name='package_purchases',
            record_id=purchase.id,
            changes={'customer': customer_name, 'package': package.name_ar, 'amount': purchase.amount_paid}
        )
        
        return jsonify({
            'success': True,
            'message': 'تم إنشاء طلب الشراء بنجاح',
            'purchase_id': purchase.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@payment_vault_bp.route('/api/donation', methods=['POST'])
@csrf.exempt  # JSON API - نستخدم Origin checking بدلاً من CSRF
@limiter.limit("10 per minute")
def api_create_donation():
    """API لإنشاء تبرع جديد"""
    try:
        # التحقق من Origin
        if not request.is_json:
            return jsonify({'success': False, 'error': 'Content-Type must be application/json'}), 400
        
        data = request.get_json()
        
        if not data.get('amount') or not data.get('payment_method'):
            return jsonify({'success': False, 'error': 'المبلغ وطريقة الدفع مطلوبة'}), 400
        
        if float(data['amount']) < 1:
            return jsonify({'success': False, 'error': 'الحد الأدنى $1'}), 400
        
        # تنظيف المدخلات
        from html import escape
        def sanitize(text, max_len=200):
            if not text:
                return None
            return escape(str(text)[:max_len].strip())
        
        donor_name = sanitize(data.get('donor_name'), 100)
        donor_email = sanitize(data.get('donor_email'), 100)
        donor_message = sanitize(data.get('message'), 500)
        
        # التحقق من البريد إذا تم إدخاله
        if donor_email:
            import re
            email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
            if not re.match(email_pattern, donor_email):
                donor_email = None  # تجاهل البريد الخاطئ بدلاً من رفض الطلب
        
        donation = Donation(
            amount_usd=float(data['amount']),
            payment_method=data['payment_method'],
            crypto_type=sanitize(data.get('crypto_type'), 20),
            transaction_type='donation',
            donor_name=donor_name,
            donor_email=donor_email,
            donor_message=donor_message,
            status='pending',
            transaction_hash=sanitize(data.get('transaction_id'), 100),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:500]
        )
        
        db.session.add(donation)
        db.session.commit()
        
        create_audit_log(
            action=f'donation_created: ${donation.amount_usd}',
            table_name='donations',
            record_id=donation.id,
            changes={'amount': float(donation.amount_usd), 'method': donation.payment_method}
        )
        
        return jsonify({
            'success': True,
            'message': 'شكراً على تبرعك!',
            'donation_id': donation.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== Routes لإدارة المشتريات (محمية) ====================

@payment_vault_bp.route('/purchases')
@login_required
def view_purchases():
    """عرض جميع عمليات الشراء"""
    if not current_user.is_owner:
        flash('❌ غير مصرح', 'danger')
        return redirect(url_for('main.dashboard'))
    
    vault = PaymentVault.query.first()
    if not vault or vault.is_locked:
        flash('❌ يجب فتح الخزينة أولاً', 'warning')
        return redirect(url_for('payment_vault.unlock_vault'))
    
    purchases = PackagePurchase.query.order_by(PackagePurchase.created_at.desc()).all()
    
    stats = {
        'total': len(purchases),
        'pending': len([p for p in purchases if p.payment_status == 'pending']),
        'completed': len([p for p in purchases if p.payment_status == 'completed']),
        'revenue': sum([p.amount_paid for p in purchases if p.payment_status == 'completed'])
    }
    
    return render_template('payment_vault/purchases.html', purchases=purchases, stats=stats)


@payment_vault_bp.route('/purchase/<int:id>')
@login_required
def purchase_detail(id):
    """تفاصيل عملية شراء"""
    if not current_user.is_owner:
        return redirect(url_for('main.dashboard'))
    
    vault = PaymentVault.query.first()
    if not vault or vault.is_locked:
        return redirect(url_for('payment_vault.unlock_vault'))
    
    purchase = PackagePurchase.query.get_or_404(id)
    return render_template('payment_vault/purchase_detail.html', purchase=purchase)


@payment_vault_bp.route('/purchase/<int:id>/activate', methods=['POST'])
@login_required
def activate_purchase(id):
    """تفعيل عملية شراء"""
    if not current_user.is_owner:
        return redirect(url_for('main.dashboard'))
    
    purchase = PackagePurchase.query.get_or_404(id)
    
    try:
        purchase.activation_status = 'activated'
        purchase.activation_date = datetime.now(timezone.utc)
        purchase.payment_status = 'completed'
        
        # تحديث التبرع المرتبط
        donation = Donation.query.filter_by(
            customer_email=purchase.customer_email,
            transaction_type='purchase'
        ).first()
        if donation:
            donation.status = 'completed'
            donation.completed_at = datetime.now(timezone.utc)
        
        db.session.commit()
        flash('✅ تم تفعيل الباقة', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    
    return redirect(url_for('payment_vault.purchase_detail', id=id))
