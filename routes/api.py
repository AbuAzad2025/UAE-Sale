from flask import Blueprint, jsonify, request
from flask_login import login_required
from extensions import db
from models import Customer, Supplier, Product, User

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'message': 'API is running'
    })


@api_bp.route('/version')
def version():
    return jsonify({
        'version': '1.0.0',
        'name': 'Warehouse & Sales Management System'
    })


@api_bp.route('/payment-fields/<payment_method>')
@login_required
def payment_fields(payment_method):
    fields = {
        'cash': {
            'fields': [],
            'ar_title': 'دفع نقدي',
            'en_title': 'Cash Payment'
        },
        'card': {
            'fields': [
                {'name': 'reference_number', 'type': 'text', 'label_ar': 'رقم المعاملة', 'label_en': 'Transaction Number', 'required': False},
                {'name': 'card_last4', 'type': 'text', 'label_ar': 'آخر 4 أرقام البطاقة', 'label_en': 'Card Last 4 Digits', 'required': False}
            ],
            'ar_title': 'دفع ببطاقة',
            'en_title': 'Card Payment'
        },
        'bank_transfer': {
            'fields': [
                {'name': 'reference_number', 'type': 'text', 'label_ar': 'رقم الحوالة', 'label_en': 'Transfer Reference', 'required': True},
                {'name': 'bank_name', 'type': 'text', 'label_ar': 'اسم البنك', 'label_en': 'Bank Name', 'required': False}
            ],
            'ar_title': 'تحويل بنكي',
            'en_title': 'Bank Transfer'
        },
        'cheque': {
            'fields': [
                {'name': 'cheque_number', 'type': 'text', 'label_ar': 'رقم الشيك', 'label_en': 'Cheque Number', 'required': True},
                {'name': 'cheque_date', 'type': 'date', 'label_ar': 'تاريخ الاستحقاق', 'label_en': 'Due Date', 'required': True},
                {'name': 'bank_name', 'type': 'text', 'label_ar': 'اسم البنك', 'label_en': 'Bank Name', 'required': True}
            ],
            'ar_title': 'دفع بشيك',
            'en_title': 'Cheque Payment'
        },
        'e_wallet': {
            'fields': [
                {'name': 'reference_number', 'type': 'text', 'label_ar': 'رقم المعاملة', 'label_en': 'Transaction ID', 'required': True},
                {'name': 'wallet_provider', 'type': 'select', 'label_ar': 'المحفظة', 'label_en': 'Wallet Provider', 'required': False, 
                 'options': [
                     {'value': 'apple_pay', 'label_ar': 'Apple Pay', 'label_en': 'Apple Pay'},
                     {'value': 'google_pay', 'label_ar': 'Google Pay', 'label_en': 'Google Pay'},
                     {'value': 'samsung_pay', 'label_ar': 'Samsung Pay', 'label_en': 'Samsung Pay'},
                     {'value': 'other', 'label_ar': 'أخرى', 'label_en': 'Other'}
                 ]}
            ],
            'ar_title': 'محفظة إلكترونية',
            'en_title': 'E-Wallet'
        }
    }
    
    return jsonify(fields.get(payment_method, {'fields': []}))


@api_bp.route('/currency-rate/<from_currency>/<to_currency>')
@login_required
def currency_rate(from_currency, to_currency):
    from services.currency_service import CurrencyService
    
    try:
        rate = CurrencyService.get_exchange_rate(from_currency, to_currency)
        return jsonify({
            'from': from_currency,
            'to': to_currency,
            'rate': float(rate),
            'success': True
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'manual_input_required': True
        }), 400


@api_bp.route('/search')
@login_required
def api_search():
    """
    🔍 API بحث موحد: زبائن، موردين، منتجات
    """
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'customers')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # ========================================
    # 1. البحث عن المنتجات
    # ========================================
    if search_type == 'products':
        products = Product.query.filter(
            Product.is_active == True,
            db.or_(
                Product.name.ilike(f'%{query}%'),
                Product.sku.ilike(f'%{query}%'),
                Product.barcode.ilike(f'%{query}%')
            )
        ).limit(per_page).all()
        
        results = [{
            'id': p.id,
            'text': p.name,
            'name': p.name,
            'sku': p.sku,
            'current_stock': float(p.current_stock or 0),
            'default_price': float(p.regular_price or 0),
            'unit_price': float(p.regular_price or 0),
            'regular_price': float(p.regular_price or 0),
            'merchant_price': float(p.merchant_price) if p.merchant_price else None,
            'partner_price': float(p.partner_price) if p.partner_price else None,
            'cost_price': float(p.cost_price) if p.cost_price else 0,
            'unit': p.unit,
            'is_low_stock': p.is_low_stock(),
        } for p in products]
        
        return jsonify({'results': results, 'has_more': len(results) >= per_page})
    
    # ========================================
    # 2. البحث عن الموردين
    # ========================================
    elif search_type == 'suppliers':
        base_query = Supplier.query.filter(Supplier.is_active == True).order_by(Supplier.name)
        
        if query:
            base_query = base_query.filter(
                db.or_(
                    Supplier.name.ilike(f'%{query}%'),
                    Supplier.company_name.ilike(f'%{query}%'),
                    Supplier.phone.ilike(f'%{query}%'),
                    Supplier.email.ilike(f'%{query}%')
                )
            )
        
        offset = (page - 1) * per_page
        suppliers = base_query.limit(per_page + 1).offset(offset).all()
        has_more = len(suppliers) > per_page
        suppliers = suppliers[:per_page]
        
        results = [{
            'id': s.id,
            'text': f"{s.name} {('- ' + s.company_name) if s.company_name else ''} - {s.phone or 'لا يوجد رقم'}",
            'name': s.name,
            'company_name': s.company_name,
            'phone': s.phone,
            'email': s.email,
            'supplier_type': s.supplier_type,
            'type_display': s.get_type_display(),
            'balance_aed': float(s.get_balance_aed()),
            'rating': s.rating,
            'is_verified': s.is_verified
        } for s in suppliers]
        
        return jsonify({'results': results, 'has_more': has_more})
    
    # ========================================
    # 3. البحث عن الزبائن (الافتراضي)
    # ========================================
    else:
        base_query = Customer.query.filter(Customer.is_active == True).order_by(Customer.name)
        
        if query:
            base_query = base_query.filter(
                db.or_(
                    Customer.name.ilike(f'%{query}%'),
                    Customer.phone.ilike(f'%{query}%'),
                    Customer.email.ilike(f'%{query}%') if Customer.email else False
                )
            )
        
        offset = (page - 1) * per_page
        customers = base_query.limit(per_page + 1).offset(offset).all()
        has_more = len(customers) > per_page
        customers = customers[:per_page]
        
        results = [{
            'id': c.id,
            'text': f"{c.name} - {c.phone or 'لا يوجد رقم'}",
            'name': c.name,
            'phone': c.phone,
            'email': c.email,
            'customer_type': c.customer_type,
            'balance_aed': float(c.get_balance_aed())
        } for c in customers]
        
        return jsonify({'results': results, 'has_more': has_more})


@api_bp.route('/check-username')
@login_required
def check_username():
    """التحقق من توفر اسم المستخدم"""
    username = request.args.get('username', '').strip()
    
    if not username or len(username) < 3:
        return jsonify({'available': False, 'error': 'اسم المستخدم قصير جداً'})
    
    import re
    if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
        return jsonify({'available': False, 'error': 'استخدم حروف إنجليزية وأرقام و_ فقط'})
    
    existing = User.query.filter_by(username=username).first()
    
    if existing:
        from datetime import datetime
        year = datetime.now().year
        suggestions = [f'{username}_{year}', f'{username}_2024', f'{username}_admin']
        
        return jsonify({
            'available': False,
            'message': f'اسم المستخدم "{username}" موجود مسبقاً',
            'suggestions': suggestions
        })
    
    return jsonify({'available': True, 'message': 'اسم المستخدم متاح ✓'})


@api_bp.route('/products/low-stock')
@login_required
def products_low_stock():
    """API للمنتجات قليلة المخزون"""
    try:
        from models import Product
        low_stock_products = Product.query.filter(
            Product.current_stock <= Product.min_stock_alert,
            Product.is_active == True
        ).order_by(Product.current_stock).all()

        products_data = []
        for product in low_stock_products:
            products_data.append({
                'id': product.id,
                'name': product.name,
                'sku': product.sku,
                'current_stock': float(product.current_stock),
                'min_stock_alert': float(product.min_stock_alert or 0),
                'needed': float((product.min_stock_alert or 0) - (product.current_stock or 0))
            })
        
        return jsonify({
            'success': True,
            'products': products_data,
            'count': len(products_data)
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api_bp.route('/echo', methods=['PUT', 'PATCH', 'DELETE'])
@login_required
def echo():
    payload = request.get_json(silent=True) or {}
    return jsonify({'success': True, 'data': payload}), 200

