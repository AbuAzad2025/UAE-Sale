from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session
from flask_login import login_user, logout_user, current_user
from extensions import db, limiter
from models import User, Donation
from utils.helpers import create_audit_log
from services.nowpayments_service import NOWPaymentsService

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/support')
def support():
    """صفحة الدعم والشراء - متاحة قبل تسجيل الدخول"""
    from models import Package
    # جلب الباقات النشطة
    packages = Package.query.filter_by(is_active=True).order_by(Package.sort_order.asc()).all()
    return render_template('support.html', packages=packages)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("100 per hour; 50 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        # Make username case-insensitive check
        # We will use the username as provided to find the user in a case-insensitive way
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)
        
        if not username or not password:
            flash('⚠️ الرجاء إدخال اسم المستخدم وكلمة المرور.\n💡 كلا الحقلين مطلوبان للدخول.', 'danger')
            return render_template('auth/login.html')
        
        # Case-insensitive query
        user = User.query.filter(User.username.ilike(username)).first()
        
        # --- Account lockout check ---
        if user and user.locked_until and user.locked_until > datetime.now(timezone.utc):
            remaining = (user.locked_until - datetime.now(timezone.utc)).seconds // 60 + 1
            flash(f'⚠️ حسابك مقفل مؤقتاً. حاول مرة أخرى بعد {remaining} دقيقة.', 'danger')
            return render_template('auth/login.html')

        if not user or not user.check_password(password):
            # Increment login attempts
            if user:
                from config import Config
                user.login_attempts = (user.login_attempts or 0) + 1
                max_attempts = getattr(Config, 'MAX_LOGIN_ATTEMPTS', 5)
                block_duration = getattr(Config, 'LOGIN_BLOCK_DURATION_MINUTES', 15)
                if user.login_attempts >= max_attempts:
                    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=block_duration)
                    flash(f'⚠️ تم قفل حسابك لمدة {block_duration} دقيقةdue to too many failed attempts.', 'danger')
                else:
                    remaining = max_attempts - user.login_attempts
                    flash(f'❌ اسم المستخدم أو كلمة المرور غير صحيحة. متبقي {remaining} محاولات.', 'danger')
                db.session.commit()
            else:
                flash('❌ اسم المستخدم أو كلمة المرور غير صحيحة.', 'danger')

            create_audit_log('login_failed', 'users', None, {'username': username})
            
            from models.login_history import LoginHistory
            failed_login = LoginHistory(
                user_id=user.id if user else None,
                username=username,
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string[:500] if request.user_agent.string else None,
                success=False,
                failure_reason='Invalid credentials',
                browser=request.user_agent.browser
            )
            db.session.add(failed_login)
            db.session.commit()
            
            return render_template('auth/login.html')
        
        if not user.is_active:
            flash('⚠️ حسابك غير نشط!\n💡 اتصل بمدير النظام لإعادة تفعيل حسابك.', 'danger')
            return render_template('auth/login.html')
        
        # Regenerate session to prevent session fixation
        session.clear()
        login_user(user, remember=remember)
        session['last_activity'] = datetime.now().isoformat()
        session.permanent = True
        
        user.last_login = datetime.now(timezone.utc)
        user.login_attempts = 0
        
        from models.login_history import LoginHistory
        successful_login = LoginHistory(
            user_id=user.id,
            username=user.username,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string[:500] if request.user_agent.string else None,
            success=True,
            browser=request.user_agent.browser,
            device_type='mobile' if request.user_agent.platform in ['android', 'iphone'] else 'desktop'
        )
        db.session.add(successful_login)
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
        session.pop('last_activity', None)
        flash('✅ تم تسجيل الخروج بنجاح. نراك قريباً!', 'success')
    
    return redirect(url_for('auth.login'))


# Payment Routes
@auth_bp.route('/payment/create', methods=['POST'])
@limiter.limit("10 per minute")
def create_payment():
    """إنشاء دفعة جديدة"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'بيانات غير صحيحة'
            }), 400
        
        amount = float(data.get('amount', 0))
        crypto_currency = data.get('crypto_currency', 'btc')
        customer_email = data.get('customer_email') or data.get('email', '')
        description = data.get('description', '')
        
        # معلومات المشترية
        transaction_type = data.get('type', 'donation')  # purchase or donation
        package = data.get('package', '')
        customer_name = data.get('customer_name', '')
        customer_phone = data.get('customer_phone', '')
        
        # معلومات التبرع
        donor_name = data.get('donor_name', '')
        donor_email = data.get('donor_email', '')
        donor_message = data.get('donor_message', '')
        
        # التحقق من الحد الأدنى
        if amount < 1:
            return jsonify({
                'success': False,
                'error': 'الحد الأدنى للتبرع هو $1'
            }), 400
        
        # إنشاء الدفعة
        nowpayments = NOWPaymentsService()
        result = nowpayments.create_payment(
            amount=amount,
            crypto_currency=crypto_currency,
            customer_email=customer_email or donor_email,
            description=description,
            transaction_type=transaction_type,
            package=package,
            customer_name=customer_name or donor_name,
            customer_phone=customer_phone,
            donor_name=donor_name,
            donor_email=donor_email,
            donor_message=donor_message
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'خطأ في إنشاء الدفعة: {str(e)}'
        }), 500


@auth_bp.route('/payment/status/<payment_id>')
def payment_status(payment_id):
    """الحصول على حالة الدفعة"""
    try:
        nowpayments = NOWPaymentsService()
        result = nowpayments.get_payment_status(payment_id)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'خطأ في الحصول على حالة الدفعة: {str(e)}'
        }), 500


@auth_bp.route('/payment/callback', methods=['POST'])
def payment_callback():
    """معالجة callback من NOWPayments"""
    try:
        # الحصول على التوقيع
        signature = request.headers.get('x-nowpayments-sig')
        if not signature:
            return jsonify({'error': 'توقيع مفقود'}), 400
        
        # التحقق من التوقيع
        nowpayments = NOWPaymentsService()
        if not nowpayments.verify_ipn(request.get_json(), signature):
            return jsonify({'error': 'توقيع غير صحيح'}), 400
        
        # معالجة البيانات
        payment_data = request.get_json()
        success = nowpayments.process_payment_callback(payment_data)
        
        if success:
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'فشل في معالجة الدفعة'}), 500
            
    except Exception as e:
        return jsonify({
            'error': f'خطأ في معالجة callback: {str(e)}'
        }), 500


@auth_bp.route('/payment/currencies')
def available_currencies():
    """الحصول على العملات المتاحة"""
    try:
        nowpayments = NOWPaymentsService()
        result = nowpayments.get_available_currencies()
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'خطأ في الحصول على العملات: {str(e)}'
        }), 500


@auth_bp.route('/payment/estimate')
def estimate_amount():
    """تقدير المبلغ للعملة الرقمية"""
    try:
        amount = float(request.args.get('amount', 0))
        from_currency = request.args.get('from', 'usd')
        to_currency = request.args.get('to', 'btc')
        
        if amount < 1:
            return jsonify({
                'success': False,
                'error': 'الحد الأدنى للتبرع هو $1'
            }), 400
        
        nowpayments = NOWPaymentsService()
        result = nowpayments.get_estimated_amount(amount, from_currency, to_currency)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'خطأ في التقدير: {str(e)}'
        }), 500


@auth_bp.route('/thank-you')
def thank_you():
    """صفحة الشكر بعد الدفع"""
    payment_id = request.args.get('payment_id')
    status = request.args.get('status', 'pending')
    
    return render_template('thank_you.html', 
                         payment_id=payment_id, 
                         status=status)

