from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from extensions import db, csrf, limiter
from models import Customer, Supplier, Product, User

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/inline-edit/<entity_type>/<int:entity_id>', methods=['PATCH'])
@login_required
def api_inline_edit(entity_type, entity_id):
    """تعديل حقل واحد مباشرة في الجدول.

    static/js/azad-app.js يستدعي هذا المسار، ولم يكن موجوداً فكان كل
    تحرير مباشر يعيد 404. الخدمة في services/inline_edit_service.py.
    """
    from services.inline_edit_service import inline_edit
    return inline_edit(entity_type, entity_id)


@api_bp.route('/products/<int:product_id>/info')
@login_required
def api_product_info(product_id):
    """معلومات المنتج مع رصيده في مستودع محدد.

    static/js/sales.js يطلب /api/products/<id>/info?warehouse_id=<id> لعرض
    الرصيد الذي ينطبق على البيع، والمسار لم يكن موجوداً.
    """
    from models import Warehouse
    from utils.decorators import get_owned_or_404

    product = get_owned_or_404(Product, product_id, code=404)
    if product is None:
        return jsonify({
            'success': False,
            'error': 'المنتج غير موجود',
            'code': 'NOT_FOUND',
        }), 404

    warehouse_id = request.args.get('warehouse_id', type=int)
    stock = float(product.current_stock or 0)
    warehouse_name = None

    if warehouse_id:
        warehouse = get_owned_or_404(Warehouse, warehouse_id, code=404)
        if warehouse is None:
            return jsonify({
                'success': False,
                'error': 'المستودع غير موجود',
                'code': 'NOT_FOUND',
            }), 404
        warehouse_name = warehouse.name
        # الرصيد الفعلي في هذا المستودع يأتي من حركات المخزون، لا من
        # current_stock الإجمالي للمنتج.
        try:
            from models import StockMovement
            received = db.session.query(
                db.func.coalesce(db.func.sum(StockMovement.quantity), 0)
            ).filter(
                StockMovement.product_id == product.id,
                StockMovement.warehouse_id == warehouse.id,
                StockMovement.movement_type.in_(['in', 'purchase', 'receipt'])
            ).scalar() or 0
            issued = db.session.query(
                db.func.coalesce(db.func.sum(StockMovement.quantity), 0)
            ).filter(
                StockMovement.product_id == product.id,
                StockMovement.warehouse_id == warehouse.id,
                StockMovement.movement_type.in_(['out', 'sale', 'issue'])
            ).scalar() or 0
            stock = float(received) - float(issued)
        except Exception:
            # لا motions ⇒ المستودع مخصص للبيع فقط؛ يبقى الرصيد الإجمالي
            current_app.logger.warning(
                'Product stock breakdown unavailable for product %s',
                product.id)
            stock = float(product.current_stock or 0)

    data = {
        'success': True,
        'id': product.id,
        'name': product.name,
        'name_ar': product.name_ar,
        'sku': product.sku,
        'barcode': product.barcode,
        'unit': product.unit,
        'current_stock': stock,
        'default_price': float(product.regular_price or 0),
        'unit_price': float(product.regular_price or 0),
        'regular_price': float(product.regular_price or 0),
        'merchant_price': (float(product.merchant_price)
                           if product.merchant_price else None),
        'partner_price': (float(product.partner_price)
                          if product.partner_price else None),
        # SECURITY: cost data only for roles allowed to see costs
        # (owner / super_admin / manager). Cashiers and sellers use this
        # endpoint from the POS screen — never expose cost to them.
        'cost_price': (float(product.cost_price) if product.cost_price else 0)
                      if current_user.can_see_costs() else None,
        'is_low_stock': product.is_low_stock(),
        'warehouse_id': warehouse_id,
        'warehouse_name': warehouse_name,
    }
    return jsonify(data)


@api_bp.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'message': 'API is running'
    })


@api_bp.route('/healthz')
def healthz():
    """Kubernetes/Load Balancer health probe.

    Runs the full health check (DB, encryption, NOWPayments, system
    resources, AI engine).

    Only an "unhealthy" result answers 503. A "warning" - for example a
    payment vault that has not been initialised yet, which is the normal
    state of a fresh deployment - still answers 200: the application can
    serve traffic, and taking it out of the load balancer's rotation over a
    missing optional integration would be worse than the warning itself.
    The per-check detail is in the body for monitoring.
    """
    from services.health_service import HealthCheckService
    result = HealthCheckService.run_full_health_check()
    status_code = 200 if result['overall_status'] != 'unhealthy' else 503
    return jsonify(result), status_code


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
            'error': 'حدث خطأ غير متوقع',
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

    results, has_more = _search_entities(query, search_type, page)
    return jsonify({'results': results, 'has_more': has_more})


@api_bp.route('/search/<target>')
@login_required
def api_search_target(target):
    """🔍 البحث بصيغة المسار: /api/search/<target>?q=...

    static/js/app.js calls this form - `$.get('/api/search/' + target, {q: query})`
    - and renders `data.html` into a `[data-search-target="..."]` container,
    so the response carries a ready-to-render HTML fragment next to the
    structured rows.

    The lookup itself is shared with /api/search?type= through
    _search_entities(), so there is exactly one implementation of each search
    and the two endpoints cannot drift apart.

    `target` is matched against a fixed set, so an unknown target is a 400
    rather than a silent empty list.
    """
    target = (target or '').lower()
    if target not in ('customers', 'products', 'suppliers'):
        return jsonify({
            'success': False,
            'error': 'نوع بحث غير معروف',
            'allowed': ['customers', 'products', 'suppliers'],
        }), 400

    query = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)

    results, has_more = _search_entities(query, target, page)
    return jsonify({
        'results': results,
        'has_more': has_more,
        'html': _render_search_html(results, target),
    })


def _search_entities(query, search_type, page=1, per_page=20):
    """ابحث في الكيانات المطلوبة.

    يقود المسار /api/search?type= والمسار /api/search/<target> معاً حتى لا
    تختلف نتائجهما. يعيد (results, has_more).
    """
    # ========================================
    # 1. البحث عن المنتجات
    # ========================================
    if search_type == 'products':
        products = Product.query.filter(
            Product.is_active.is_(True),
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
            # SECURITY: cost data only for roles allowed to see costs
            # (owner / super_admin / manager). Cashiers and sellers use this
            # endpoint from the POS screen — never expose cost to them.
            'cost_price': (float(p.cost_price) if p.cost_price else 0)
                          if current_user.can_see_costs() else None,
            'unit': p.unit,
            'is_low_stock': p.is_low_stock(),
        } for p in products]

        return results, len(results) >= per_page

    # ========================================
    # 2. البحث عن الموردين
    # ========================================
    if search_type == 'suppliers':
        base_query = Supplier.query.filter(Supplier.is_active == True).order_by(Supplier.name)  # noqa: E712  (SQLAlchemy boolean filter)

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

        return results, has_more

    # ========================================
    # 3. البحث عن الزبائن (الافتراضي)
    # ========================================
    base_query = Customer.query.filter(Customer.is_active == True).order_by(Customer.name)  # noqa: E712  (SQLAlchemy boolean filter)

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

    return results, has_more


def _render_search_html(results, target):
    """.results -> جزء HTML جاهز للقائمة المنسدلة.

    يُبنى من نفس الصفوف التي تعيدها _search_entities، فلا يمكن أن يختلف
    ما يراه المستخدم عن البيانات التي عادت من الخادم. القيم تُهرَّب لأن
    أسماء العملاء والموردين منتجات من المستخدم.
    """
    from markupsafe import escape

    if not results:
        return ''

    items = []
    for row in results:
        label = escape(str(row.get('name') or row.get('text') or ''))
        extra = ''
        if row.get('sku'):
            extra = (f'<small class="text-muted">'
                     f'SKU: {escape(str(row["sku"]))}</small>')
        elif row.get('phone'):
            extra = (f'<small class="text-muted">'
                     f'{escape(str(row["phone"]))}</small>')
        items.append(
            f'<div class="search-result p-2 border-bottom" '
            f'data-id="{escape(str(row.get("id")))}" '
            f'data-type="{escape(target)}">'
            f'<div class="fw-bold">{label}</div>{extra}</div>'
        )
    return ''.join(items)


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
            Product.is_active.is_(True)
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
            'error': 'حدث خطأ غير متوقع'
        }), 500


@api_bp.route('/products/barcode/<barcode>')
@login_required
def product_by_barcode(barcode):
    """Lookup product by exact barcode — unified for all multi-line forms."""
    code = (barcode or '').strip()
    if not code:
        return jsonify({'error': 'barcode required'}), 400
    product = Product.query.filter_by(barcode=code).first()
    if not product:
        return jsonify({'error': 'Product not found', 'code': code}), 404
    return jsonify({
        'id': product.id,
        'name': product.name,
        'sku': product.sku,
        'barcode': product.barcode,
        'current_stock': float(product.current_stock or 0),
        'unit_price': float(product.regular_price or 0),
        'regular_price': float(product.regular_price or 0),
        'cost_price': float(product.cost_price or 0) if current_user.can_see_costs() else None,
        'is_active': product.is_active,
    })


@api_bp.route('/barcode/validate')
@login_required
def barcode_validate():
    """Validate barcode uniqueness and format for product create/edit."""
    code = (request.args.get('code') or '').strip()
    if not code:
        return jsonify({'valid': False, 'error': 'code required'}), 400
    exists = Product.query.filter_by(barcode=code).first()
    if exists:
        return jsonify({'valid': False, 'error': 'الباركود مستخدم بالفعل', 'exists': True, 'product_id': exists.id})
    return jsonify({'valid': True, 'exists': False})


@api_bp.route('/echo', methods=['PUT', 'PATCH', 'DELETE'])
@login_required
def echo():
    payload = request.get_json(silent=True) or {}
    return jsonify({'success': True, 'data': payload}), 200


@api_bp.route('/client-errors', methods=['POST'])
@csrf.exempt  # beacon/fetch from pages without a CSRF token; Origin + rate limit below
@limiter.limit("30 per minute")
def client_errors():
    """Receive browser error reports (window.onerror / unhandledrejection).

    Public by design (visitors hit JS errors before login), hardened by:
    Origin check (same host or CORS list), strict rate limit, server-side
    length caps + secret redaction. Always answers 200 on accepted payloads
    so a failing reporter can never break the page it reports from.
    """
    from services.error_report_service import (
        CATEGORY_FRONTEND, report_error)

    if not request.is_json:
        return jsonify({'success': False,
                        'error': 'Content-Type must be application/json'}), 400
    # Same-host rule (mirrors the language-switch referrer guard): the
    # page reporting the error must live on this host, or the Origin must
    # be explicitly allowed. Blocks cross-site report flooding.
    origin = request.headers.get('Origin', '')
    if origin:
        own_host = (request.host or '').split(':')[0].lower()
        try:
            origin_host = origin.split(
                '://', 1)[1].split('/')[0].split(':')[0].lower()
        except Exception:
            origin_host = ''
        allowed = current_app.config.get('CORS_ORIGINS', [])
        if origin_host != own_host and not any(
                origin.startswith(o) for o in allowed):
            return jsonify({'success': False, 'error': 'Invalid origin'}), 403

    data = request.get_json(silent=True) or {}
    message = data.get('message', '')
    if not isinstance(message, str) or not message.strip():
        return jsonify({'success': False, 'error': 'message is required'}), 400
    kind = data.get('kind', 'onerror')
    source = ('js-unhandledrejection'
              if kind == 'unhandledrejection' else 'js-onerror')
    entry = report_error(
        CATEGORY_FRONTEND, message,
        severity='error',
        traceback_text=data.get('stack'),
        source=source,
        path=data.get('page'))
    return jsonify({'success': True,
                    'report_id': entry.id if entry else None})
