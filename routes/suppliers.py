"""
🏪 Suppliers Routes - مسارات الموردين
إدارة الموردين: عرض، إضافة، تعديل، تقارير
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from extensions import db, limiter
from models import Supplier, Purchase, Payment
from utils.decorators import permission_required, admin_required
from utils.helpers import create_audit_log
from sqlalchemy import func, desc

suppliers_bp = Blueprint('suppliers', __name__, url_prefix='/suppliers')


@suppliers_bp.route('/')
@login_required
@permission_required('manage_suppliers')
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
@permission_required('manage_suppliers')
@limiter.limit("10 per minute", methods=['POST'])
def create():
    """إضافة مورد جديد"""
    if request.method == 'POST':
        try:
            supplier_type_value = (request.form.get('supplier_type') or '').strip()
            if not supplier_type_value:
                flash('⚠️ يرجى اختيار نوع المورد.', 'warning')
                return render_template('suppliers/create.html')
            
            rating_value = (request.form.get('rating') or '').strip()
            rating = None
            if rating_value:
                try:
                    rating = int(rating_value)
                except ValueError:
                    flash('⚠️ قيمة التقييم غير صحيحة.', 'warning')
                    return render_template('suppliers/create.html')
            
            initial_balance = request.form.get('initial_balance', type=float, default=0)
            
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
                supplier_type=supplier_type_value,
                rating=rating if rating is not None else None,
                credit_limit=request.form.get('credit_limit', type=float, default=0),
                payment_terms_days=request.form.get('payment_terms_days', type=int, default=30),
                preferred_currency=request.form.get('preferred_currency', 'AED'),
                total_purchases_aed=initial_balance,
                total_paid_aed=0,
                notes=request.form.get('notes'),
                tags=request.form.get('tags'),
                is_verified=request.form.get('is_verified') == 'on',
                created_by=current_user.id
            )
            
            db.session.add(supplier)
            db.session.commit()
            
            create_audit_log('create', 'suppliers', supplier.id)
            
            flash('✅ تم إضافة المورد بنجاح!', 'success')
            return redirect(url_for('suppliers.view', id=supplier.id))
        
        except Exception as e:
            db.session.rollback()
            flash(f'❌ حدث خطأ: {str(e)}\n💡 تحقق من البيانات المدخلة وحاول مرة أخرى.', 'danger')
    
    return render_template('suppliers/create.html')


@suppliers_bp.route('/<int:id>')
@login_required
@permission_required('manage_suppliers')
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
@permission_required('manage_suppliers')
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
            supplier_type_value = (request.form.get('supplier_type') or '').strip()
            supplier.supplier_type = supplier_type_value or None
            
            rating_value = (request.form.get('rating') or '').strip()
            supplier.rating = int(rating_value) if rating_value else None
            supplier.credit_limit = request.form.get('credit_limit', type=float)
            supplier.payment_terms_days = request.form.get('payment_terms_days', type=int)
            supplier.preferred_currency = request.form.get('preferred_currency')
            supplier.notes = request.form.get('notes')
            supplier.tags = request.form.get('tags')
            supplier.is_verified = request.form.get('is_verified') == 'on'
            
            db.session.commit()
            
            create_audit_log('update', 'suppliers', supplier.id)
            
            flash('✅ تم تحديث المورد بنجاح!', 'success')
            return redirect(url_for('suppliers.view', id=supplier.id))
        
        except Exception as e:
            db.session.rollback()
            flash(f'❌ حدث خطأ: {str(e)}\n💡 تحقق من البيانات المدخلة وحاول مرة أخرى.', 'danger')
    
    return render_template('suppliers/edit.html', supplier=supplier)


@suppliers_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_suppliers')
def delete(id):
    """حذف (إلغاء تفعيل) المورد"""
    supplier = Supplier.query.get_or_404(id)
    
    try:
        # Check for related records preventing deletion
        purchases_count = Purchase.query.filter_by(supplier_id=id).count()
        payments_count = Payment.query.filter_by(supplier_id=id).count()
        
        if purchases_count > 0 or payments_count > 0:
            supplier.is_active = False
            db.session.commit()
            flash(f'⚠️ تم إلغاء تفعيل المورد "{supplier.name}" بدلاً من حذفه لوجود ({purchases_count} فاتورة شراء، {payments_count} دفعة) مرتبطة به.', 'warning')
        else:
            db.session.delete(supplier)
            db.session.commit()
            flash(f'✅ تم حذف المورد "{supplier.name}" نهائياً!', 'success')
            
        create_audit_log('delete', 'suppliers', supplier.id)
        
    except Exception as e:
        db.session.rollback()
        # Fallback to soft delete if hard delete fails
        try:
            supplier.is_active = False
            db.session.commit()
            flash(f'⚠️ تعذر الحذف النهائي للمورد "{supplier.name}" بسبب ارتباطات في قاعدة البيانات. تم إلغاء تفعيله بدلاً من ذلك.', 'warning')
        except Exception as inner_e:
            flash(f'❌ حدث خطأ أثناء حذف المورد: {str(e)}', 'danger')
    
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
    
    payments = Payment.query.filter_by(supplier_id=id).order_by(Payment.payment_date.desc()).all()
    
    return render_template('suppliers/statement.html',
                         supplier=supplier,
                         purchases=purchases,
                         payments=payments)


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
