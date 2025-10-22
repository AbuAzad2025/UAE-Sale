"""
مسارات الشيكات - Cheques Routes
إدارة الشيكات الواردة والصادرة
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Cheque, Customer, Supplier, Sale, Receipt, Expense
from services.currency_service import CurrencyService
from utils.decorators import admin_required, permission_required
from utils.helpers import create_audit_log, generate_number
from datetime import datetime, timedelta
from decimal import Decimal

cheques_bp = Blueprint('cheques', __name__, url_prefix='/cheques')


@cheques_bp.route('/')
@login_required
@permission_required('manage_payments')
def index():
    """قائمة كل الشيكات"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    cheque_type = request.args.get('type', '', type=str)
    status = request.args.get('status', '', type=str)
    search = request.args.get('search', '', type=str)
    
    # تحديث حالة كل الشيكات
    Cheque.update_all_statuses()
    
    query = Cheque.query.filter_by(is_active=True)
    
    if cheque_type:
        query = query.filter_by(cheque_type=cheque_type)
    
    if status:
        query = query.filter_by(status=status)
    
    if search:
        search_filter = f'%{search}%'
        query = query.filter(
            db.or_(
                Cheque.cheque_number.ilike(search_filter),
                Cheque.cheque_bank_number.ilike(search_filter),
                Cheque.bank_name.ilike(search_filter),
                Cheque.drawer_name.ilike(search_filter),
                Cheque.payee_name.ilike(search_filter)
            )
        )
    
    pagination = query.order_by(Cheque.due_date).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    stats = Cheque.get_statistics()
    
    return render_template('cheques/index.html',
                         cheques=pagination.items,
                         pagination=pagination,
                         stats=stats)


@cheques_bp.route('/incoming')
@login_required
@permission_required('manage_payments')
def incoming():
    """الشيكات الواردة"""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '', type=str)
    
    Cheque.update_all_statuses()
    
    query = Cheque.query.filter_by(cheque_type='incoming', is_active=True)
    
    if status:
        query = query.filter_by(status=status)
    
    pagination = query.order_by(Cheque.due_date).paginate(
        page=page,
        per_page=25,
        error_out=False
    )
    
    stats = Cheque.get_statistics()
    
    return render_template('cheques/incoming.html',
                         cheques=pagination.items,
                         pagination=pagination,
                         stats=stats)


@cheques_bp.route('/outgoing')
@login_required
@permission_required('manage_payments')
def outgoing():
    """الشيكات الصادرة"""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '', type=str)
    
    Cheque.update_all_statuses()
    
    query = Cheque.query.filter_by(cheque_type='outgoing', is_active=True)
    
    if status:
        query = query.filter_by(status=status)
    
    pagination = query.order_by(Cheque.due_date).paginate(
        page=page,
        per_page=25,
        error_out=False
    )
    
    stats = Cheque.get_statistics()
    
    return render_template('cheques/outgoing.html',
                         cheques=pagination.items,
                         pagination=pagination,
                         stats=stats)


@cheques_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_payments')
def create():
    """إضافة شيك جديد"""
    if request.method == 'POST':
        try:
            cheque_number = generate_number('CHQ', Cheque, 'cheque_number')
            
            cheque_type = request.form.get('cheque_type')
            amount = Decimal(str(request.form.get('amount')))
            currency = request.form.get('currency', 'AED')
            
            # حساب سعر الصرف
            exchange_rate = CurrencyService.get_exchange_rate(
                currency,
                'AED',
                user_rate=request.form.get('exchange_rate', type=float)
            )
            
            # تحويل التواريخ
            issue_date = datetime.strptime(request.form.get('issue_date'), '%Y-%m-%d').date()
            due_date = datetime.strptime(request.form.get('due_date'), '%Y-%m-%d').date()
            
            cheque = Cheque(
                cheque_number=cheque_number,
                cheque_bank_number=request.form.get('cheque_bank_number'),
                cheque_type=cheque_type,
                bank_name=request.form.get('bank_name'),
                bank_branch=request.form.get('bank_branch'),
                account_number=request.form.get('account_number'),
                amount=amount,
                currency=currency,
                exchange_rate=exchange_rate,
                issue_date=issue_date,
                due_date=due_date,
                drawer_name=request.form.get('drawer_name'),
                drawer_id_number=request.form.get('drawer_id_number'),
                payee_name=request.form.get('payee_name'),
                customer_id=request.form.get('customer_id', type=int) or None,
                supplier_id=request.form.get('supplier_id', type=int) or None,
                notes=request.form.get('notes'),
                user_id=current_user.id
            )
            
            cheque.calculate_amount_aed()
            cheque.update_status_based_on_date()
            
            db.session.add(cheque)
            db.session.commit()
            
            create_audit_log('create', 'cheques', cheque.id)
            
            flash(f'✅ تم إضافة الشيك {cheque.cheque_bank_number} بنجاح', 'success')
            return redirect(url_for('cheques.view', id=cheque.id))
        
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')
    
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    exchange_rates = CurrencyService.get_all_rates('AED')
    
    return render_template('cheques/create.html',
                         customers=customers,
                         suppliers=suppliers,
                         exchange_rates=exchange_rates)


@cheques_bp.route('/<int:id>')
@login_required
@permission_required('manage_payments')
def view(id):
    """عرض تفاصيل الشيك"""
    cheque = Cheque.query.get_or_404(id)
    cheque.update_status_based_on_date()
    db.session.commit()
    
    # إضافة today للـ template
    today = datetime.now().strftime('%Y-%m-%d')
    
    return render_template('cheques/view.html', cheque=cheque, today=today)


@cheques_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_payments')
def edit(id):
    """تعديل الشيك"""
    cheque = Cheque.query.get_or_404(id)
    
    # لا يمكن تعديل شيك تم صرفه أو ملغي
    if cheque.status in ['cleared', 'cancelled', 'bounced']:
        flash('❌ لا يمكن تعديل شيك تم صرفه أو إلغاؤه', 'danger')
        return redirect(url_for('cheques.view', id=id))
    
    if request.method == 'POST':
        try:
            cheque.cheque_bank_number = request.form.get('cheque_bank_number')
            cheque.bank_name = request.form.get('bank_name')
            cheque.bank_branch = request.form.get('bank_branch')
            cheque.account_number = request.form.get('account_number')
            
            cheque.amount = Decimal(str(request.form.get('amount')))
            cheque.currency = request.form.get('currency', 'AED')
            
            exchange_rate = CurrencyService.get_exchange_rate(
                cheque.currency,
                'AED',
                user_rate=request.form.get('exchange_rate', type=float)
            )
            cheque.exchange_rate = exchange_rate
            
            cheque.issue_date = datetime.strptime(request.form.get('issue_date'), '%Y-%m-%d').date()
            cheque.due_date = datetime.strptime(request.form.get('due_date'), '%Y-%m-%d').date()
            
            cheque.drawer_name = request.form.get('drawer_name')
            cheque.drawer_id_number = request.form.get('drawer_id_number')
            cheque.payee_name = request.form.get('payee_name')
            cheque.notes = request.form.get('notes')
            
            cheque.calculate_amount_aed()
            cheque.update_status_based_on_date()
            
            db.session.commit()
            
            create_audit_log('update', 'cheques', id)
            
            flash('✅ تم تحديث الشيك بنجاح', 'success')
            return redirect(url_for('cheques.view', id=id))
        
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')
    
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    exchange_rates = CurrencyService.get_all_rates('AED')
    
    return render_template('cheques/edit.html',
                         cheque=cheque,
                         customers=customers,
                         suppliers=suppliers,
                         exchange_rates=exchange_rates)


@cheques_bp.route('/<int:id>/deposit', methods=['POST'])
@login_required
@permission_required('manage_payments')
def deposit_cheque(id):
    """إيداع الشيك في البنك - الخطوة 1"""
    cheque = Cheque.query.get_or_404(id)
    
    try:
        deposit_date_str = request.form.get('deposit_date')
        deposit_date = datetime.strptime(deposit_date_str, '%Y-%m-%d').date() if deposit_date_str else None
        
        cheque.deposit_cheque(deposit_date)
        db.session.commit()
        
        create_audit_log('cheque_deposit', 'cheques', id, 
                        f'إيداع شيك رقم {cheque.cheque_bank_number} في البنك')
        
        flash(f'✅ تم إيداع الشيك {cheque.cheque_bank_number} في البنك', 'success')
    
    except ValueError as e:
        flash(f'❌ خطأ: {str(e)}', 'error')
        db.session.rollback()
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    
    return redirect(url_for('cheques.view', id=id))


@cheques_bp.route('/<int:id>/clear', methods=['POST'])
@login_required
@permission_required('manage_payments')
def clear_cheque(id):
    """تأكيد صرف الشيك من البنك - الخطوة 2 - المحاسبة الفعلية"""
    cheque = Cheque.query.get_or_404(id)
    
    try:
        clearance_date_str = request.form.get('clearance_date')
        clearance_date = datetime.strptime(clearance_date_str, '%Y-%m-%d').date() if clearance_date_str else None
        
        # سعر الصرف وقت الصرف (اختياري)
        clearance_exchange_rate = request.form.get('clearance_exchange_rate', type=float)
        
        # تأكيد الصرف - هنا تحدث المحاسبة!
        cheque.clear_cheque(clearance_date, clearance_exchange_rate)
        db.session.commit()
        
        # رسالة مفصلة عند وجود فرق عملة
        if cheque.currency_gain_loss and abs(cheque.currency_gain_loss) > Decimal('0.01'):
            if cheque.currency_gain_loss > 0:
                gain_loss_msg = f' - تم تحقيق ربح من فرق العملة: +{cheque.currency_gain_loss:.2f} AED'
            else:
                gain_loss_msg = f' - خسارة من فرق العملة: {cheque.currency_gain_loss:.2f} AED'
        else:
            gain_loss_msg = ''
        
        create_audit_log('cheque_clear', 'cheques', id,
                        f'تأكيد صرف شيك رقم {cheque.cheque_bank_number} من البنك - تم تحديث الحسابات{gain_loss_msg}')
        
        flash(f'✅ تم تأكيد صرف الشيك {cheque.cheque_bank_number} - تم تحديث الحسابات المالية{gain_loss_msg}', 'success')
    
    except ValueError as e:
        flash(f'❌ خطأ: {str(e)}', 'error')
        db.session.rollback()
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    
    return redirect(url_for('cheques.view', id=id))


@cheques_bp.route('/<int:id>/bounce', methods=['POST'])
@login_required
@permission_required('manage_payments')
def bounce_cheque(id):
    """رفض الشيك من البنك - إرجاع الدين"""
    cheque = Cheque.query.get_or_404(id)
    
    try:
        reason = request.form.get('bounce_reason', 'غير محدد')
        details = request.form.get('bounce_details', '')
        full_reason = f"{reason}. {details}" if details else reason
        
        # رفض الشيك - إرجاع الدين
        cheque.bounce_cheque(full_reason)
        db.session.commit()
        
        create_audit_log('cheque_bounce', 'cheques', id,
                        f'رفض شيك رقم {cheque.cheque_bank_number}: {full_reason}')
        
        flash(f'❌ تم رفض الشيك {cheque.cheque_bank_number} - تم إرجاع الدين للزبون', 'warning')
    
    except ValueError as e:
        flash(f'❌ خطأ: {str(e)}', 'error')
        db.session.rollback()
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    
    return redirect(url_for('cheques.view', id=id))


@cheques_bp.route('/<int:id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel(id):
    """إلغاء الشيك"""
    cheque = Cheque.query.get_or_404(id)
    
    if cheque.status == 'cleared':
        flash('❌ لا يمكن إلغاء شيك تم صرفه', 'danger')
        return redirect(url_for('cheques.view', id=id))
    
    try:
        reason = request.form.get('cancel_reason')
        
        cheque.cancel_cheque(reason)
        db.session.commit()
        
        create_audit_log('cancel', 'cheques', id)
        
        flash(f'✅ تم إلغاء الشيك {cheque.cheque_bank_number}', 'success')
    
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    
    return redirect(url_for('cheques.view', id=id))


@cheques_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete(id):
    """حذف (أرشفة) الشيك"""
    cheque = Cheque.query.get_or_404(id)
    
    try:
        reason = request.form.get('delete_reason', 'حذف من قبل المستخدم')
        
        cheque.archive(reason)
        db.session.commit()
        
        create_audit_log('archive', 'cheques', id)
        
        flash(f'✅ تم أرشفة الشيك {cheque.cheque_bank_number}', 'success')
        return redirect(url_for('cheques.index'))
    
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
        return redirect(url_for('cheques.view', id=id))


@cheques_bp.route('/<int:id>/restore', methods=['POST'])
@login_required
@admin_required
def restore(id):
    """استعادة شيك من الأرشيف"""
    cheque = Cheque.query.get_or_404(id)
    
    try:
        cheque.restore()
        db.session.commit()
        
        create_audit_log('restore', 'cheques', id)
        
        flash(f'✅ تم استعادة الشيك {cheque.cheque_bank_number}', 'success')
    
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    
    return redirect(url_for('cheques.view', id=id))


@cheques_bp.route('/alerts')
@login_required
@permission_required('manage_payments')
def alerts():
    """تنبيهات الشيكات"""
    Cheque.update_all_statuses()
    
    due_soon = Cheque.get_due_soon_cheques()
    overdue = Cheque.get_overdue_cheques()
    bounced = Cheque.query.filter_by(status='bounced', is_active=True).all()
    
    stats = Cheque.get_statistics()
    
    return render_template('cheques/alerts.html',
                         due_soon=due_soon,
                         overdue=overdue,
                         bounced=bounced,
                         stats=stats)


@cheques_bp.route('/archived')
@login_required
@admin_required
def archived():
    """الشيكات المؤرشفة"""
    page = request.args.get('page', 1, type=int)
    
    pagination = Cheque.query.filter_by(is_active=False).order_by(
        Cheque.archived_at.desc()
    ).paginate(page=page, per_page=25, error_out=False)
    
    return render_template('cheques/archived.html',
                         cheques=pagination.items,
                         pagination=pagination)


@cheques_bp.route('/api/stats')
@login_required
def api_stats():
    """API للإحصائيات"""
    Cheque.update_all_statuses()
    stats = Cheque.get_statistics()
    return jsonify(stats)


@cheques_bp.route('/api/alerts')
@login_required
def api_alerts():
    """API للتنبيهات"""
    Cheque.update_all_statuses()
    
    due_soon = Cheque.get_due_soon_cheques()
    overdue = Cheque.get_overdue_cheques()
    
    return jsonify({
        'due_soon': len(due_soon),
        'overdue': len(overdue),
        'cheques_due_soon': [c.to_dict() for c in due_soon[:5]],
        'cheques_overdue': [c.to_dict() for c in overdue[:5]],
    })

