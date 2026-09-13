from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, current_app
from flask_login import login_user, logout_user, current_user
from extensions import db, limiter
from models import User
from utils.helpers import create_audit_log
from services.nowpayments_service import NOWPaymentsService

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/support')
def support():
    """صفحة الدعم والشراء - متاحة قبل تسجيل الدخول"""
    from flask import session
    from models import Package, PaymentVault
    # جلب الباقات النشطة
    packages = Package.query.filter_by(is_active=True).order_by(Package.sort_order.asc()).all()
    # إعدادات الدفع العامة (بدون أسرار): الطرق المتاحة + الحدود + بيانات
    # الاستقبال المعلنة من لوحة المالك. الطريقة تظهر فقط إذا كانت مفعّلة
    # ومُهيأة (مفتاح/عنوان/حساب موجود).
    vault = PaymentVault.query.first()
    pay_config = {
        'methods': {'crypto': False, 'card': False, 'paypal': False, 'bank': False},
        'min_amount': 15,
        'min_display': '15',
        'bank': None,
        'addresses': {},
        'whatsapp': current_app.config.get('COMPANY_WHATSAPP', ''),
    }
    if vault is not None:
        try:
            min_amt = float(vault.min_donation_amount or 15)
        except (TypeError, ValueError):
            min_amt = 15
        pay_config['min_amount'] = min_amt
        pay_config['min_display'] = ('%g' % min_amt)
        addrs = {}
        if vault.bitcoin_address:
            addrs['btc'] = vault.bitcoin_address
        if vault.ethereum_address:
            addrs['eth'] = vault.ethereum_address
        if vault.usdt_address:
            addrs['usdt'] = vault.usdt_address
        pay_config['addresses'] = addrs
        pay_config['methods'] = {
            'crypto': bool(getattr(vault, 'crypto_enabled', True)) and bool(
                vault.nowpayments_api_key or addrs),
            'card': bool(getattr(vault, 'card_enabled', True)),
            'paypal': bool(getattr(vault, 'paypal_enabled', True)) and bool(
                vault.paypal_client_id or vault.paypal_business_email),
            'bank': bool(getattr(vault, 'bank_enabled', True)) and bool(
                vault.bank_account_number or vault.bank_iban),
        }
        if pay_config['methods']['bank']:
            pay_config['bank'] = {
                'bank_name': vault.bank_name or '',
                'account_name': vault.bank_account_name or '',
                'account_number': vault.bank_account_number or '',
                'iban': vault.bank_iban or '',
                'swift': vault.bank_swift_code or '',
                'branch': vault.bank_branch or '',
                'country': vault.bank_country or '',
                'currency': vault.bank_currency or 'USD',
            }
    if session.get('language') == 'en':
        return render_template('public/support_en.html', packages=packages,
                               pay_config=pay_config)
    return render_template('support.html', packages=packages,
                           pay_config=pay_config)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("20 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        # Already logged in: send to the role-appropriate dashboard
        if getattr(current_user, 'is_owner', False) or current_user.is_super_admin():
            return redirect(url_for('owner.dashboard'))
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
                    flash(f'⚠️ تم قفل حسابك لمدة {block_duration} دقيقة بسبب تكرار المحاولات الفاشلة.', 'danger')
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
        # Only relative paths; reject protocol-relative '//evil.com' open redirects
        if next_page and next_page.startswith('/') and not next_page.startswith('//'):
            return redirect(next_page)

        # Role-based landing dashboard after login:
        #   owner / super_admin -> /owner/dashboard
        #   everyone else       -> /dashboard
        if getattr(user, 'is_owner', False) or user.is_super_admin():
            return redirect(url_for('owner.dashboard'))
        return redirect(url_for('main.dashboard'))

    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    if current_user.is_authenticated:
        create_audit_log('logout', 'users', current_user.id)
        logout_user()
        session.pop('last_activity', None)
        flash('✅ تم تسجيل الخروج بنجاح. نراك قريباً!', 'success')

    # After logout, send the user back to the public landing page so
    # they can browse marketing pages or sign back in cleanly.
    return redirect(url_for('public.landing'))

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

        # Input validation
        try:
            amount = float(data.get('amount', 0))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Invalid amount'}), 400

        # Sanitize string inputs (max lengths)
        crypto_currency = str(data.get('crypto_currency', 'btc'))[:10]
        customer_email = str(data.get('customer_email') or data.get('email', ''))[:200]
        description = str(data.get('description', ''))[:500]
        transaction_type = str(data.get('type', 'donation'))[:20]
        package = str(data.get('package', ''))[:100]
        customer_name = str(data.get('customer_name', ''))[:200]
        customer_phone = str(data.get('customer_phone', ''))[:30]
        donor_name = str(data.get('donor_name', ''))[:200]
        donor_email = str(data.get('donor_email', ''))[:200]
        donor_message = str(data.get('donor_message', ''))[:1000]

        # Validate amount range
        if amount < 1 or amount > 100000:
            return jsonify({
                'success': False,
                'error': 'Amount must be between $1 and $100,000'
            }), 400

        # Validate transaction type
        if transaction_type not in ('donation', 'purchase'):
            transaction_type = 'donation'

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
            current_app.logger.warning(f"NOWPayments create_payment failed: {result.get('error')}")
            return jsonify({
                'success': False,
                'error': '❌ فشلت عملية الدفع. يرجى المحاولة لاحقاً.'
            }), 400

    except Exception as e:
        current_app.logger.error(f'NOWPayments create_payment error: {e}', exc_info=True)
        return jsonify({
            'success': False,
            'error': '❌ حدث خطأ أثناء إنشاء الدفعة. يرجى المحاولة لاحقاً.'
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
            current_app.logger.warning(f"NOWPayments get_payment_status failed: {result.get('error')}")
            return jsonify({
                'success': False,
                'error': '❌ تعذر الحصول على حالة الدفعة. يرجى المحاولة لاحقاً.'
            }), 400

    except Exception as e:
        current_app.logger.error(f'NOWPayments payment_status error: {e}', exc_info=True)
        return jsonify({
            'success': False,
            'error': '❌ حدث خطأ أثناء الحصول على حالة الدفعة. يرجى المحاولة لاحقاً.'
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
        current_app.logger.error(f'NOWPayments callback error: {e}', exc_info=True)
        return jsonify({
            'error': '❌ حدث خطأ أثناء معالجة الدفعة. يرجى المحاولة لاحقاً.'
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
            current_app.logger.warning(f"NOWPayments get_available_currencies failed: {result.get('error')}")
            return jsonify({
                'success': False,
                'error': '❌ تعذر الحصول على العملات المتاحة. يرجى المحاولة لاحقاً.'
            }), 400

    except Exception as e:
        current_app.logger.error(f'NOWPayments currencies error: {e}', exc_info=True)
        return jsonify({
            'success': False,
            'error': '❌ حدث خطأ أثناء الحصول على العملات. يرجى المحاولة لاحقاً.'
        }), 500


@auth_bp.route('/payment/estimate')
def estimate_amount():
    """تقدير المبلغ للعملة الرقمية"""
    try:
        try:
            amount = float(request.args.get('amount', 0))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'مبلغ غير صالح'}), 400
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
            current_app.logger.warning(f"NOWPayments estimate failed: {result.get('error')}")
            return jsonify({
                'success': False,
                'error': '❌ تعذر تقدير المبلغ. يرجى المحاولة لاحقاً.'
            }), 400

    except Exception as e:
        current_app.logger.error(f'NOWPayments estimate error: {e}', exc_info=True)
        return jsonify({
            'success': False,
            'error': '❌ حدث خطأ أثناء التقدير. يرجى المحاولة لاحقاً.'
        }), 500


@auth_bp.route('/thank-you')
def thank_you():
    """صفحة الشكر بعد الدفع"""
    from flask import session
    payment_id = request.args.get('payment_id')
    status = request.args.get('status', 'pending')

    if session.get('language') == 'en':
        return render_template('thank_you_en.html',
                               payment_id=payment_id,
                               status=status)
    return render_template('thank_you.html',
                           payment_id=payment_id,
                           status=status)
