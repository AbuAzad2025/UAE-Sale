"""
🏪 Suppliers Routes - مسارات الموردين
إدارة الموردين: عرض، إضافة، تعديل، تقارير
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Supplier, Purchase
from utils.decorators import admin_required
from utils.helpers import create_audit_log
from sqlalchemy import func, desc

suppliers_bp = Blueprint('suppliers', __name__, url_prefix='/suppliers')


@suppliers_bp.route('/')
@login_required
@admin_required
def index():
    """قائمة الموردين"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)
    supplier_type = request.args.get('type', '', type=str)
    
    query = Supplier.query.filter_by(is_active=True)
    
    # البحث
    if search:
        search_filter = f'%{search}%'
        query = query.filter(
            db.or_(
                Supplier.name.ilike(search_filter),
                Supplier.company_name.ilike(search_filter),
                Supplier.phone.ilike(search_filter),
                Supplier.email.ilike(search_filter)
            )
        )
    
    # الفلترة حسب النوع
    if supplier_type:
        query = query.filter_by(supplier_type=supplier_type)
    
    pagination = query.order_by(Supplier.name).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    # إحصائيات
    stats = {
        'total': Supplier.query.filter_by(is_active=True).count(),
        'verified': Supplier.query.filter_by(is_active=True, is_verified=True).count(),
        'parts': Supplier.query.filter_by(is_active=True, supplier_type='parts').count(),
        'equipment': Supplier.query.filter_by(is_active=True, supplier_type='equipment').count(),
    }
    
    return render_template('suppliers/index.html',
                         suppliers=pagination.items,
                         pagination=pagination,
                         stats=stats)


@suppliers_bp.route('/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create():
    """إضافة مورد جديد"""
    if request.method == 'POST':
        try:
            supplier = Supplier(
                name=request.form.get('name'),
                name_en=request.form.get('name_en'),
                company_name=request.form.get('company_name'),
                phone=request.form.get('phone'),
                phone2=request.form.get('phone2'),
                email=request.form.get('email'),
                website=request.form.get('website'),
                address=request.form.get('address'),
                city=request.form.get('city'),
                country=request.form.get('country', 'UAE'),
                tax_number=request.form.get('tax_number'),
                commercial_registration=request.form.get('commercial_registration'),
                supplier_type=request.form.get('supplier_type', 'parts'),
                rating=request.form.get('rating', type=int, default=3),
                credit_limit=request.form.get('credit_limit', type=float, default=0),
                payment_terms_days=request.form.get('payment_terms_days', type=int, default=30),
                preferred_currency=request.form.get('preferred_currency', 'AED'),
                notes=request.form.get('notes'),
                tags=request.form.get('tags'),
                is_verified=request.form.get('is_verified') == 'on',
                created_by=current_user.id
            )
            
            db.session.add(supplier)
            db.session.commit()
            
            create_audit_log('create', 'suppliers', supplier.id)
            
            flash('✅ تم إضافة المورد بنجاح', 'success')
            return redirect(url_for('suppliers.view', id=supplier.id))
        
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')
    
    return render_template('suppliers/create.html')


@suppliers_bp.route('/<int:id>')
@login_required
@admin_required
def view(id):
    """عرض تفاصيل المورد"""
    supplier = Supplier.query.get_or_404(id)
    
    # آخر المشتريات
    recent_purchases = supplier.purchases.filter_by(status='confirmed').order_by(
        desc(Purchase.purchase_date)
    ).limit(10).all()
    
    # إحصائيات
    stats = {
        'total_purchases': supplier.purchases.filter_by(status='confirmed').count(),
        'total_amount': float(supplier.total_purchases_aed or 0),
        'balance': float(supplier.get_balance_aed()),
        'avg_purchase': 0
    }
    
    if stats['total_purchases'] > 0:
        stats['avg_purchase'] = stats['total_amount'] / stats['total_purchases']
    
    return render_template('suppliers/view.html',
                         supplier=supplier,
                         recent_purchases=recent_purchases,
                         stats=stats)


@suppliers_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit(id):
    """تعديل المورد"""
    supplier = Supplier.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            supplier.name = request.form.get('name')
            supplier.name_en = request.form.get('name_en')
            supplier.company_name = request.form.get('company_name')
            supplier.phone = request.form.get('phone')
            supplier.phone2 = request.form.get('phone2')
            supplier.email = request.form.get('email')
            supplier.website = request.form.get('website')
            supplier.address = request.form.get('address')
            supplier.city = request.form.get('city')
            supplier.country = request.form.get('country')
            supplier.tax_number = request.form.get('tax_number')
            supplier.commercial_registration = request.form.get('commercial_registration')
            supplier.supplier_type = request.form.get('supplier_type')
            supplier.rating = request.form.get('rating', type=int)
            supplier.credit_limit = request.form.get('credit_limit', type=float)
            supplier.payment_terms_days = request.form.get('payment_terms_days', type=int)
            supplier.preferred_currency = request.form.get('preferred_currency')
            supplier.notes = request.form.get('notes')
            supplier.tags = request.form.get('tags')
            supplier.is_verified = request.form.get('is_verified') == 'on'
            
            db.session.commit()
            
            create_audit_log('update', 'suppliers', supplier.id)
            
            flash('✅ تم تحديث المورد بنجاح', 'success')
            return redirect(url_for('suppliers.view', id=supplier.id))
        
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')
    
    return render_template('suppliers/edit.html', supplier=supplier)


@suppliers_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete(id):
    """حذف (إلغاء تفعيل) المورد"""
    supplier = Supplier.query.get_or_404(id)
    
    try:
        supplier.is_active = False
        db.session.commit()
        
        create_audit_log('delete', 'suppliers', supplier.id)
        
        flash('✅ تم إلغاء تفعيل المورد', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    
    return redirect(url_for('suppliers.index'))


@suppliers_bp.route('/<int:id>/statement')
@login_required
@admin_required
def statement(id):
    """كشف حساب المورد"""
    supplier = Supplier.query.get_or_404(id)
    
    purchases = supplier.purchases.filter_by(status='confirmed').order_by(
        Purchase.purchase_date.desc()
    ).all()
    
    return render_template('suppliers/statement.html',
                         supplier=supplier,
                         purchases=purchases)


@suppliers_bp.route('/api/search')
def api_search():
    """API endpoint للبحث عن الموردين"""
    try:
        query = request.args.get('q', '')
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        # السماح بالبحث حتى بدون query (لعرض كل الموردين)
        if query and len(query) >= 1:
            suppliers = Supplier.query.filter(
                Supplier.is_active == True,
                db.or_(
                    Supplier.name.ilike(f'%{query}%'),
                    Supplier.phone.ilike(f'%{query}%'),
                    Supplier.email.ilike(f'%{query}%')
                )
            ).order_by(Supplier.name).limit(per_page).all()
        else:
            # عرض كل الموردين (مرتبين أبجدياً)
            suppliers = Supplier.query.filter_by(
                is_active=True
            ).order_by(Supplier.name).limit(per_page).all()
        
        results = [{
            'id': s.id,
            'name': s.name,
            'phone': s.phone or '',
            'text': f"{s.name} - {s.phone}" if s.phone else s.name,
            'supplier_type': s.supplier_type,
            'balance': float(s.get_balance_aed())
        } for s in suppliers]
        
        return jsonify(results)
    except Exception as e:
        print(f"Error in supplier search API: {e}")
        return jsonify([])
