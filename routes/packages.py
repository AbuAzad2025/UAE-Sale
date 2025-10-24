"""
Routes for package management
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from extensions import db
from models import Package, PackagePurchase
from utils.decorators import permission_required, owner_required
from datetime import datetime

bp = Blueprint('packages', __name__, url_prefix='/packages')


@bp.route('/support')
def support_page():
    """صفحة الدعم والشراء - متاحة للجميع"""
    packages = Package.query.filter_by(is_active=True).order_by(Package.sort_order.asc()).all()
    return render_template('support.html', packages=packages)


# ملاحظة: إدارة الباقات منقولة إلى /payment-vault/packages-management
# هذا الملف للـ API والصفحات العامة فقط


@bp.route('/api/packages')
def api_packages():
    """API للحصول على الباقات النشطة"""
    packages = Package.query.filter_by(is_active=True).order_by(Package.sort_order.asc()).all()
    return jsonify([pkg.to_dict() for pkg in packages])


@bp.route('/api/package/<int:id>')
def api_package(id):
    """API للحصول على باقة محددة"""
    package = Package.query.get_or_404(id)
    return jsonify(package.to_dict())


@bp.route('/purchase', methods=['POST'])
def create_purchase():
    """إنشاء عملية شراء جديدة"""
    try:
        data = request.get_json()
        
        # التحقق من البيانات المطلوبة
        required_fields = ['package_id', 'customer_name', 'customer_email', 'payment_method', 'amount_paid']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'error': f'الحقل {field} مطلوب'}), 400
        
        # التحقق من وجود الباقة
        package = Package.query.get(data['package_id'])
        if not package or not package.is_active:
            return jsonify({'success': False, 'error': 'الباقة غير متاحة'}), 404
        
        # التحقق من المبلغ
        if float(data['amount_paid']) < package.price:
            return jsonify({'success': False, 'error': 'المبلغ المدفوع أقل من سعر الباقة'}), 400
        
        # إنشاء عملية الشراء
        purchase = PackagePurchase(
            package_id=data['package_id'],
            customer_name=data['customer_name'],
            customer_email=data['customer_email'],
            customer_phone=data.get('customer_phone'),
            company_name=data.get('company_name'),
            payment_method=data['payment_method'],
            payment_status='pending',
            amount_paid=float(data['amount_paid']),
            currency=data.get('currency', 'USD'),
            transaction_id=data.get('transaction_id'),
            payment_details=data.get('payment_details'),
            notes=data.get('notes')
        )
        
        db.session.add(purchase)
        db.session.commit()
        
        # تسجيل في جدول التبرعات أيضاً للتوافق
        from models import Donation
        donation = Donation(
            amount_usd=purchase.amount_paid,
            payment_method=purchase.payment_method,
            transaction_type='purchase',
            package=package.slug,
            customer_name=purchase.customer_name,
            customer_email=purchase.customer_email,
            customer_phone=purchase.customer_phone,
            status='pending',
            transaction_hash=purchase.transaction_id
        )
        db.session.add(donation)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم إنشاء طلب الشراء بنجاح',
            'purchase_id': purchase.id,
            'status': 'pending'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/donation', methods=['POST'])
def create_donation():
    """إنشاء تبرع جديد"""
    try:
        data = request.get_json()
        
        # التحقق من البيانات المطلوبة
        if not data.get('amount') or not data.get('payment_method'):
            return jsonify({'success': False, 'error': 'المبلغ وطريقة الدفع مطلوبة'}), 400
        
        # التحقق من الحد الأدنى
        if float(data['amount']) < 1:
            return jsonify({'success': False, 'error': 'الحد الأدنى للتبرع هو $1'}), 400
        
        from models import Donation
        donation = Donation(
            amount_usd=float(data['amount']),
            payment_method=data['payment_method'],
            crypto_type=data.get('crypto_type'),
            transaction_type='donation',
            donor_name=data.get('donor_name'),
            donor_email=data.get('donor_email'),
            donor_message=data.get('message'),
            status='pending',
            transaction_hash=data.get('transaction_id'),
            gateway_name=data.get('gateway_name'),
            gateway_transaction_id=data.get('gateway_transaction_id')
        )
        
        db.session.add(donation)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'شكراً على تبرعك! تم استلام طلبك',
            'donation_id': donation.id,
            'status': 'pending'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

