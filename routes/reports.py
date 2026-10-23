from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from flask import Blueprint, render_template, request, jsonify, make_response, abort, current_app
from flask_login import login_required, current_user
from werkzeug.exceptions import HTTPException
from sqlalchemy import func
from extensions import db
from models import Sale, SaleLine, Purchase, Product, Customer, ProductPartner, StockMovement
from utils.decorators import permission_required, get_owned_or_404
from utils.helpers import create_audit_log
from services.costing_service import CostingService

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')

# ═══════════════════════════════════════════════════════════════════════════
# مساعدات مشتركة مع دفتر الأستاذ (نفس مصدر البيانات ⇒ نفس الأرقام)
# ═══════════════════════════════════════════════════════════════════════════
from routes.ledger import (  # noqa: E402  (استيراد بعد تعريف Blueprint)
    _REPORT_BUCKET_KEYS,
    _archived_record_ids,
    _receivables_aging,
)

# ═══════════════════════════════════════════════════════════════════════════
# قائمة سماح أعمدة التقارير المخصصة (F8)
# ═══════════════════════════════════════════════════════════════════════════
# SECURITY: الأعمدة المسموح عرضها في «التقرير المخصص» محددة صراحةً لكل
# نموذج. أي عمود غير مذكور هنا لا يُعرض أبداً — حتى لو أُضيف عمود جديد
# إلى النموذج لاحقاً، فلا يظهر قبل مراجعته هنا.
_REPORT_FIELD_ALLOWLIST = {
    'sales': (
        'sale_number', 'sale_date', 'customer_id', 'seller_id', 'warehouse_id',
        'subtotal', 'discount_amount', 'shipping_cost', 'tax_rate', 'tax_amount',
        'total_amount', 'paid_amount', 'balance_due', 'currency', 'exchange_rate',
        'amount_base', 'paid_amount_base', 'payment_status', 'status',
    ),
    'purchases': (
        'purchase_number', 'purchase_date', 'supplier_id', 'warehouse_id',
        'supplier_name', 'supplier_phone', 'supplier_email', 'subtotal',
        'discount_amount', 'tax_rate', 'tax_amount', 'total_amount',
        'paid_amount', 'currency', 'exchange_rate', 'amount_base',
        'payment_status', 'status',
    ),
    'products': (
        'name', 'name_ar', 'description', 'sku', 'part_number', 'barcode',
        'country_of_origin', 'category_id', 'merchant_customer_id',
        'regular_price', 'merchant_price', 'merchant_share', 'partner_price',
        'current_stock', 'min_stock_alert', 'unit', 'location', 'is_active',
    ),
    'customers': (
        'name', 'name_ar', 'commercial_name', 'customer_type',
        'customer_classification', 'phone', 'email', 'address', 'tax_number',
        'preferred_currency', 'credit_limit', 'total_purchases', 'balance',
        'is_active',
    ),
}

# أعمدة التكلفة — تُضاف فقط لمن يملك صلاحية view_costs
_REPORT_COST_FIELDS = {
    'products': ('cost_price', 'average_cost'),
}


@reports_bp.route('/')
@login_required
@permission_required('view_reports')
def index():
    return render_template('reports/index.html')


@reports_bp.route('/partners')
@login_required
@permission_required('view_reports')
def partners():  # noqa: C901
    """تقرير الشركاء والمنتجات التابعة للتجار"""
    from models import Payment, Receipt, Supplier

    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)

    # --- 1. PRODUCT SHARES CALCULATION (aggregated at DB level) ---
    # Aggregate sales per product in a single query
    partner_sales_agg = db.session.query(
        SaleLine.product_id,
        func.sum(SaleLine.line_total).label('total_revenue'),
        func.sum(SaleLine.quantity).label('total_qty')
    ).join(Sale).filter(
        Sale.status == 'confirmed'
    )
    if date_from:
        partner_sales_agg = partner_sales_agg.filter(func.date(Sale.sale_date) >= date_from)
    if date_to:
        partner_sales_agg = partner_sales_agg.filter(func.date(Sale.sale_date) <= date_to)
    partner_sales_agg = partner_sales_agg.group_by(SaleLine.product_id).all()
    agg_dict = {r.product_id: (r.total_revenue or Decimal('0'), r.total_qty or 0) for r in partner_sales_agg}

    partner_products = Product.query.join(ProductPartner).filter(Product.is_active == True).distinct().all()
    partners_data = []
    partner_share_totals = {}

    for product in partner_products:
        total_revenue, total_qty = agg_dict.get(product.id, (Decimal('0'), 0))
        avg_unit_price = total_revenue / total_qty if total_qty > 0 else 0
        if total_revenue > 0:
            for share in product.partner_shares:
                percentage = Decimal(str(share.percentage))
                partner_amount = total_revenue * (percentage / Decimal('100'))
                partners_data.append({
                    'product_name': product.name,
                    'partner_name': share.partner_customer.name,
                    'percentage': share.percentage,
                    'avg_unit_price': avg_unit_price,
                    'total_qty': total_qty,
                    'total_revenue': total_revenue,
                    'partner_share_amount': partner_amount
                })
                p_id = share.partner_customer.id
                partner_share_totals[p_id] = partner_share_totals.get(p_id, Decimal('0')) + partner_amount

    # Find products linked to a merchant
    # Aggregate merchant sales at DB level
    merchant_sales_agg = db.session.query(
        SaleLine.product_id,
        func.sum(SaleLine.line_total).label('total_revenue'),
        func.sum(SaleLine.quantity).label('total_qty')
    ).join(Sale).filter(
        Sale.status == 'confirmed'
    )
    if date_from:
        merchant_sales_agg = merchant_sales_agg.filter(func.date(Sale.sale_date) >= date_from)
    if date_to:
        merchant_sales_agg = merchant_sales_agg.filter(func.date(Sale.sale_date) <= date_to)
    merchant_sales_agg = merchant_sales_agg.group_by(SaleLine.product_id).all()
    merchant_agg_dict = {r.product_id: (r.total_revenue or Decimal('0'), r.total_qty or 0) for r in merchant_sales_agg}

    merchant_products = Product.query.filter(
        Product.merchant_customer_id.isnot(None),
        Product.is_active.is_(True)
    ).all()

    merchants_data = []
    merchant_share_totals = {}

    for product in merchant_products:
        total_revenue, total_qty = merchant_agg_dict.get(product.id, (Decimal('0'), 0))
        avg_unit_price = total_revenue / total_qty if total_qty > 0 else 0
        if total_revenue > 0:
            merchant_percentage = float(product.merchant_share or 100)
            merchant_amount = total_revenue * (Decimal(merchant_percentage) / 100)
            merchants_data.append({
                'product_name': product.name,
                'merchant_name': product.merchant_customer.name,
                'percentage': merchant_percentage,
                'avg_unit_price': avg_unit_price,
                'total_qty': total_qty,
                'total_revenue': total_revenue,
                'merchant_share_amount': merchant_amount
            })
            m_id = product.merchant_customer.id
            merchant_share_totals[m_id] = merchant_share_totals.get(m_id, Decimal('0')) + merchant_amount

    # --- 2. FINANCIAL SUMMARIES (Partners & Merchants) ---
    # Helper to get payments/receipts
    def get_financials(customer_type, share_totals_dict):
        customers = Customer.query.filter_by(customer_type=customer_type).all()
        # Aggregate payments and receipts per customer at DB level
        paid_agg = db.session.query(
            Payment.customer_id,
            func.sum(Payment.amount_base).label('paid')
        ).filter(
            Payment.direction == 'outgoing',
            Payment.customer_id.in_([c.id for c in customers])
        ).group_by(Payment.customer_id)
        receipts_agg = db.session.query(
            Receipt.customer_id,
            func.sum(Receipt.amount_base).label('received')
        ).filter(Receipt.customer_id.in_([c.id for c in customers])).group_by(Receipt.customer_id)
        payment_in_agg = db.session.query(
            Payment.customer_id,
            func.sum(Payment.amount_base).label('received')
        ).filter(
            Payment.direction == 'incoming',
            Payment.customer_id.in_([c.id for c in customers])
        ).group_by(Payment.customer_id)
        if date_from:
            paid_agg = paid_agg.filter(func.date(Payment.payment_date) >= date_from)
            receipts_agg = receipts_agg.filter(func.date(Receipt.receipt_date) >= date_from)
            payment_in_agg = payment_in_agg.filter(func.date(Payment.payment_date) >= date_from)
        if date_to:
            paid_agg = paid_agg.filter(func.date(Payment.payment_date) <= date_to)
            receipts_agg = receipts_agg.filter(func.date(Receipt.receipt_date) <= date_to)
            payment_in_agg = payment_in_agg.filter(func.date(Payment.payment_date) <= date_to)
        paid_dict = {r.customer_id: (r.paid or Decimal('0')) for r in paid_agg.all()}
        receipts_dict = {r.customer_id: (r.received or Decimal('0')) for r in receipts_agg.all()}
        payment_in_dict = {r.customer_id: (r.received or Decimal('0')) for r in payment_in_agg.all()}

        summary_list = []
        for cust in customers:
            total_paid_to = paid_dict.get(cust.id, Decimal('0'))
            total_receipts = receipts_dict.get(cust.id, Decimal('0'))
            total_payment_in = payment_in_dict.get(cust.id, Decimal('0'))
            total_received_from = total_receipts + total_payment_in
            total_share = share_totals_dict.get(cust.id, Decimal('0'))
            net_balance = (total_share + total_received_from) - total_paid_to
            if total_share > 0 or total_paid_to > 0 or total_received_from > 0:
                summary_list.append({
                    'name': cust.name,
                    'total_share': total_share,
                    'paid_to': total_paid_to,
                    'received_from': total_received_from,
                    'net_balance': net_balance
                })
        return summary_list

    partners_summary = get_financials('partner', partner_share_totals)
    merchants_summary = get_financials('merchant', merchant_share_totals)

    # --- 3. SUPPLIERS SUMMARY (aggregated at DB level) ---
    suppliers = Supplier.query.filter_by(is_active=True).all()
    suppliers_summary = []

    # Aggregate purchases per supplier once
    purchase_agg = db.session.query(
        Purchase.supplier_id,
        func.sum(Purchase.amount_base).label('total_purchases')
    ).filter(Purchase.status == 'confirmed')
    if date_from:
        purchase_agg = purchase_agg.filter(func.date(Purchase.purchase_date) >= date_from)
    if date_to:
        purchase_agg = purchase_agg.filter(func.date(Purchase.purchase_date) <= date_to)
    purchase_agg = purchase_agg.group_by(Purchase.supplier_id).all()
    purchase_dict = {r.supplier_id: (r.total_purchases or Decimal('0')) for r in purchase_agg}

    # Aggregate payments per supplier once
    payment_agg = db.session.query(
        Payment.supplier_id,
        func.sum(Payment.amount_base).label('total_paid')
    ).filter(Payment.direction == 'outgoing')
    if date_from:
        payment_agg = payment_agg.filter(func.date(Payment.payment_date) >= date_from)
    if date_to:
        payment_agg = payment_agg.filter(func.date(Payment.payment_date) <= date_to)
    payment_agg = payment_agg.group_by(Payment.supplier_id).all()
    paid_dict = {r.supplier_id: (r.total_paid or Decimal('0')) for r in payment_agg}

    # Aggregate refunds per supplier once
    refund_agg = db.session.query(
        Payment.supplier_id,
        func.sum(Payment.amount_base).label('total_refunds')
    ).filter(Payment.direction == 'incoming', Payment.supplier_id.isnot(None))
    if date_from:
        refund_agg = refund_agg.filter(func.date(Payment.payment_date) >= date_from)
    if date_to:
        refund_agg = refund_agg.filter(func.date(Payment.payment_date) <= date_to)
    refund_agg = refund_agg.group_by(Payment.supplier_id).all()
    refund_dict = {r.supplier_id: (r.total_refunds or Decimal('0')) for r in refund_agg}

    for sup in suppliers:
        total_purchases = purchase_dict.get(sup.id, Decimal('0'))
        total_paid_to = paid_dict.get(sup.id, Decimal('0'))
        total_refunds = refund_dict.get(sup.id, Decimal('0'))
        net_paid = total_paid_to - total_refunds
        balance_due = total_purchases - net_paid
        if total_purchases > 0 or total_paid_to > 0 or total_refunds > 0:
            suppliers_summary.append({
                'name': sup.name,
                'total_purchases': total_purchases,
                'paid_to': total_paid_to,
                'received_from': total_refunds,
                'balance_due': balance_due
            })

    return render_template('reports/partners.html',
                           partners_data=partners_data,
                           merchants_data=merchants_data,
                           partners_summary=partners_summary,
                           merchants_summary=merchants_summary,
                           suppliers_summary=suppliers_summary)


@reports_bp.route('/sales')
@login_required
@permission_required('view_reports')
def sales():
    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)
    customer_id = request.args.get('customer', type=int)
    seller_id = request.args.get('seller', type=int)

    query = Sale.query.filter_by(status='confirmed')

    if date_from:
        query = query.filter(func.date(Sale.sale_date) >= date_from)

    if date_to:
        query = query.filter(func.date(Sale.sale_date) <= date_to)

    if customer_id:
        query = query.filter_by(customer_id=customer_id)

    if seller_id:
        query = query.filter_by(seller_id=seller_id)
    elif current_user.is_seller():
        query = query.filter_by(seller_id=current_user.id)

    sales_list = query.order_by(Sale.sale_date.desc()).all()

    total_sales = Decimal('0')
    total_paid = Decimal('0')
    total_due = Decimal('0')

    for sale in sales_list:
        total_sales += (sale.amount_base or Decimal('0'))
        total_paid += (sale.paid_amount_base or Decimal('0'))
        total_due += ((sale.amount_base or Decimal('0')) - (sale.paid_amount_base or Decimal('0')))

    total_profit = Decimal('0')
    if current_user.can_see_costs():
        for sale in sales_list:
            total_profit += (sale.get_profit() or Decimal('0'))

    summary = {
        'sales_count': len(sales_list),
        'total_sales_aed': float(total_sales),
        'total_paid_aed': float(total_paid),
        'total_pending_aed': float(total_due),
        'total_profit': float(total_profit) if current_user.can_see_costs() else None
    }

    return render_template('reports/sales.html',
                           sales=sales_list,
                           summary=summary)


@reports_bp.route('/purchases')
@login_required
@permission_required('view_reports')
def purchases():  # noqa: C901
    if current_user.is_seller():
        return render_template('errors/403.html'), 403

    date_from = request.args.get('start_date', '', type=str)
    date_to = request.args.get('end_date', '', type=str)
    supplier_id = request.args.get('supplier_id', type=int)

    query = Purchase.query.filter_by(status='confirmed')

    # F3: الأرشفة تكتب صفاً في archived_records ولا تقلب is_active ولا
    # status — فالمشتريات المؤرشفة تبقى 'confirmed' وتُحتسب في التقرير.
    # لذلك الاستبعاد يجب أن يكون صريحاً (نفس فلتر routes/ledger.py).
    query = query.filter(~Purchase.id.in_(_archived_record_ids('purchases')))

    if date_from:
        query = query.filter(func.date(Purchase.purchase_date) >= date_from)

    if date_to:
        query = query.filter(func.date(Purchase.purchase_date) <= date_to)

    if supplier_id:
        query = query.filter_by(supplier_id=supplier_id)

    purchases_list = query.order_by(Purchase.purchase_date.desc()).all()

    total_amount = Decimal('0')

    # Calculate total purchases amount
    for p in purchases_list:
        amount = p.amount_base or Decimal('0')
        total_amount += amount
        # Add dummy attributes for template compatibility if not present
        if not hasattr(p, 'paid_amount'):
            p.paid_amount = Decimal('0')
        if not hasattr(p, 'balance_due'):
            p.balance_due = amount

    # Calculate total paid from Payments table
    from models import Payment
    payment_query = Payment.query.filter(
        Payment.direction == 'outgoing',
        Payment.supplier_id.isnot(None)
    )

    # F3: السندات المؤرشفة لا تُحتسب ضمن المدفوع (نفس منطق الاستبعادات).
    payment_query = payment_query.filter(
        ~Payment.id.in_(_archived_record_ids('payments')))

    if date_from:
        payment_query = payment_query.filter(func.date(Payment.payment_date) >= date_from)
    if date_to:
        payment_query = payment_query.filter(func.date(Payment.payment_date) <= date_to)
    if supplier_id:
        payment_query = payment_query.filter_by(supplier_id=supplier_id)

    payments_list = payment_query.all()
    total_paid = sum((p.amount_base or Decimal('0') for p in payments_list), Decimal('0'))

    # Total due is rough estimate: Purchases - Payments
    # Note: This doesn't account for opening balance
    total_due = total_amount - total_paid

    stats = {
        'total_purchases': len(purchases_list),
        'total_amount': float(total_amount),
        'total_paid': float(total_paid),
        'total_due': float(total_due)
    }

    # Get suppliers for filter
    from models import Supplier
    suppliers = Supplier.query.filter_by(is_active=True).all()

    return render_template('reports/purchases.html',
                           purchases=purchases_list,
                           stats=stats,
                           suppliers=suppliers,
                           start_date=date_from,
                           end_date=date_to,
                           supplier_id=supplier_id)


@reports_bp.route('/receivables')
@login_required
@permission_required('view_reports')
def receivables():
    """تقرير الذمم المدينة.

    نفس مصدر البيانات المستخدم في صفحة دفتر الأستاذ
    (/ledger/aging-analysis): عملة الأساس، نفس الفلاتر (مبيعات مؤكدة نشطة
    غير مؤرشفة)، ونفس حدود الشرائح (0-30 / 31-60 / 61-90 / 91-120 / +120).
    """
    as_of_date = request.args.get('as_of_date', type=str) or None

    aging = _receivables_aging(as_of_date)

    # مفاتيح القالب القديمة (current / days_30 / ...) مع حدود الشرائح
    # الدقيقة الموثّقة في routes/ledger.py.
    aging_data = {
        _REPORT_BUCKET_KEYS[bucket]: {'sales': [], 'total': Decimal('0')}
        for bucket in ('0-30', '31-60', '61-90', '91-120', 'over_120')
    }
    for sale in aging['invoices']:
        key = _REPORT_BUCKET_KEYS[sale.aging_bucket]
        aging_data[key]['sales'].append(sale)
        aging_data[key]['total'] += sale.calculated_balance

    total_receivables = aging['total']

    summary = {
        'total_receivables': float(total_receivables),
        'current': float(aging['buckets']['0-30']),
        'days_30': float(aging['buckets']['31-60']),
        'days_60': float(aging['buckets']['61-90']),
        'days_90': float(aging['buckets']['91-120']),
        'over_90': float(aging['buckets']['over_120']),
    }

    return render_template('reports/receivables.html',
                           aging_data=aging_data,
                           summary=summary)


@reports_bp.route('/inventory')
@login_required
@permission_required('view_reports')
def inventory():
    category_id = request.args.get('category', type=int)

    query = Product.query.filter_by(is_active=True)

    if category_id:
        query = query.filter_by(category_id=category_id)

    products = query.order_by(Product.name).all()

    total_value = Decimal('0')
    total_items = Decimal('0')

    for p in products:
        total_items += (p.current_stock or Decimal('0'))
        if current_user.can_see_costs():
            # القيمة الدفترية على أساس المتوسط المتحرك — لا سعر آخر شراء.
            total_value += CostingService.stock_value(p)

    summary = {
        'products_count': len(products),
        'total_items': float(total_items),
        'total_value': float(total_value) if current_user.can_see_costs() else None
    }

    # SECURITY: cost columns in the template are gated on can_see_costs()
    return render_template('reports/inventory.html',
                           products=products,
                           summary=summary,
                           can_see_costs=current_user.can_see_costs())


@reports_bp.route('/api/model_fields')
@login_required
@permission_required('view_reports')
def api_model_fields():
    """حقول التقارير المتاحة لنموذج معيّن.

    static/js/reporting.js يطلب /reports/api/model_fields?model=<name>
    ويتوقع {columns, date_fields, all_fields}. المسار لم يكن موجوداً.

    SECURITY: الأعمدة تُشتق من قائمة سماح (allowlist) صريحة لكل نموذج —
    لا من أعمدة النموذج مباشرة — فأي عمود جديد يُضاف إلى النموذج لاحقاً
    لا يظهر في التقارير قبل مراجعته. أعمدة التكلفة تُضاف فقط لمن يملك
    صلاحية view_costs.
    """
    from models import Purchase as _Purchase
    from models import Sale as _Sale

    model_name = (request.args.get('model') or '').strip().lower()

    models = {
        'sales': (_Sale, 'sales'),
        'sale': (_Sale, 'sales'),
        'purchases': (_Purchase, 'purchases'),
        'purchase': (_Purchase, 'purchases'),
        'products': (Product, 'products'),
        'product': (Product, 'products'),
        'customers': (Customer, 'customers'),
        'customer': (Customer, 'customers'),
    }

    entry = models.get(model_name)
    if entry is None:
        return jsonify({
            'success': False,
            'error': 'نموذج غير معروف',
            'allowed': sorted(set(models)),
            'columns': [],
            'date_fields': [],
            'all_fields': [],
        }), 400

    model, allowlist_key = entry

    # SECURITY: قائمة السماح الصريحة + أعمدة التكلفة لمن يملك الصلاحية.
    allowed = set(_REPORT_FIELD_ALLOWLIST[allowlist_key])
    if current_user.can_see_costs():
        allowed |= set(_REPORT_COST_FIELDS.get(allowlist_key, ()))

    date_fields = []
    columns = []
    for col in model.__table__.columns:
        name = col.name
        if name not in allowed:
            continue
        if isinstance(col.type, db.DateTime) or name.endswith('_date') \
                or name.endswith('_at'):
            date_fields.append(name)
        columns.append(name)

    # كل الحقول (بما فيها التاريخية) هي الخيارات الكاملة.
    all_fields = list(columns)
    # تاريخية أولاً في القائمة الكاملة لأنها الأكثر استخداماً.
    all_fields = [f for f in date_fields if f in all_fields] + \
                 [f for f in columns if f not in date_fields]

    return jsonify({
        'success': True,
        'model': model_name,
        'columns': columns,
        'date_fields': date_fields,
        'all_fields': all_fields,
    })


@reports_bp.route('/api/entity-search')
@login_required
@permission_required('view_reports')
def api_entity_search():
    from models import Supplier
    query = request.args.get('q', '').strip()
    entity_type = request.args.get('type', 'supplier')

    results = []

    if entity_type == 'supplier':
        suppliers = Supplier.query.filter(
            db.or_(
                Supplier.name.ilike(f'%{query}%'),
                Supplier.phone.ilike(f'%{query}%')
            )
        ).limit(10).all()
        for s in suppliers:
            results.append({
                'id': s.id,
                'name': s.name,
                'phone': s.phone,
                'type': 'supplier'
            })

    else:  # customer, partner, merchant
        q_filter = Customer.query.filter(
            db.or_(
                Customer.name.ilike(f'%{query}%'),
                Customer.phone.ilike(f'%{query}%')
            )
        )

        if entity_type == 'partner':
            q_filter = q_filter.filter_by(customer_type='partner')
        elif entity_type == 'merchant':
            q_filter = q_filter.filter_by(customer_type='merchant')
        # If 'customer', we search all or just regular? Let's search all if type is generic, or filter if specific.
        # User dropdown will likely send specific types.

        customers = q_filter.limit(10).all()
        for c in customers:
            results.append({
                'id': c.id,
                'name': c.name,
                'phone': c.phone,
                'type': c.customer_type
            })

    return jsonify(results)


@reports_bp.route('/entity_report_fragment/<type>/<id>')
@login_required
@permission_required('view_reports')
def entity_report_fragment(type, id):  # noqa: C901
    try:
        from models import Receipt, Payment, PurchaseLine, Supplier

        context = {
            'entity': None,
            'type_label': '',
            'balance': 0,
            'balance_label': '',
            'products': [],
            'invoices': [],
            'transactions': []
        }

        if type == 'supplier':
            entity = get_owned_or_404(Supplier, id)
            context['entity'] = entity
            context['type_label'] = 'مورد'

            # Balance
            context['balance'] = entity.get_balance_aed()
            context['balance_label'] = 'مستحق للمورد'

            # Products (Purchased)
            p_lines = db.session.query(
                Product.name,
                func.sum(PurchaseLine.quantity).label('qty'),
                func.sum(PurchaseLine.line_total).label('total'),
                func.max(Purchase.purchase_date).label('last_date')
            ).join(Purchase).join(Product).filter(
                Purchase.supplier_id == id,
                Purchase.status == 'confirmed'
            ).group_by(Product.name).all()

            context['products'] = [{
                'name': p.name,
                'quantity': p.qty,
                'total': p.total,
                'last_date': p.last_date.strftime('%Y-%m-%d') if p.last_date else '-'
            } for p in p_lines]

            # Invoices (Purchases)
            # F3: استبعاد المشتريات المؤرشفة (الأرشفة لا تقلب is_active).
            purchases = (
                Purchase.query
                .filter_by(supplier_id=id)
                .filter(~Purchase.id.in_(_archived_record_ids('purchases')))
                .order_by(Purchase.purchase_date.desc()).all()
            )
            context['invoices'] = [{
                'number': p.purchase_number,
                'date': p.purchase_date.strftime('%Y-%m-%d'),
                'status': p.status,
                'amount': p.amount_base or 0,
                'paid': p.get_paid_amount(),
                'balance': (p.amount_base or 0) - p.get_paid_amount()
            } for p in purchases]

            # Transactions (Payments TO Supplier)
            # F3: استبعاد السندات المؤرشفة.
            payments = (
                Payment.query
                .filter_by(supplier_id=id)
                .filter(~Payment.id.in_(_archived_record_ids('payments')))
                .order_by(Payment.payment_date.desc()).all()
            )
            context['transactions'] = [{
                'number': p.payment_number,
                'type': 'out',  # Payment out
                'date': p.payment_date.strftime('%Y-%m-%d'),
                'amount': p.amount_base,
                'method': p.payment_method,
                'notes': p.notes or '-'
            } for p in payments]

        else:  # Customer/Partner/Merchant
            entity = get_owned_or_404(Customer, id)
            context['entity'] = entity
            context['type_label'] = {
                'partner': 'شريك',
                'merchant': 'تاجر',
                'regular': 'زبون',
                'vip': 'VIP'
            }.get(entity.customer_type, 'زبون')

            # Balance calculation (Receivables/Payables)
            # Sales (He took goods) + Payments Out (He took money) - Receipts (He gave money)
            # F3: الأرشفة تكتب صفاً في archived_records ولا تقلب is_active ولا
            # status — فالمستند المؤرشف يبقى 'confirmed' ويُحتسب في كشف
            # الحساب. الاستبعاد هنا صريح (نفس فلتر routes/ledger.py).
            total_sales = (
                db.session.query(func.sum(Sale.amount_base))
                .filter(Sale.customer_id == id, Sale.status == 'confirmed')
                .filter(~Sale.id.in_(_archived_record_ids('sales')))
                .scalar() or 0
            )
            total_receipts = (
                db.session.query(func.sum(Receipt.amount_base))
                .filter(Receipt.customer_id == id)
                .filter(~Receipt.id.in_(_archived_record_ids('receipts')))
                .scalar() or 0
            )
            # Payments made TO customer (e.g. returns/share/drawings)
            total_payments_to = (
                db.session.query(func.sum(Payment.amount_base))
                .filter(Payment.customer_id == id, Payment.direction == 'outgoing')
                .filter(~Payment.id.in_(_archived_record_ids('payments')))
                .scalar() or 0
            )

            context['balance'] = (total_sales + total_payments_to) - total_receipts  # Positive means they owe us
            context['balance_label'] = 'مستحق لنا'
            if context['balance'] < 0:
                context['balance'] = abs(context['balance'])
                context['balance_label'] = 'مستحق للعميل'

            # Products (Sold) - Products the customer BOUGHT
            s_lines = db.session.query(
                Product.name,
                func.sum(SaleLine.quantity).label('qty'),
                func.sum(SaleLine.line_total).label('total'),
                func.max(Sale.sale_date).label('last_date')
            ).join(Sale).join(Product).filter(
                Sale.customer_id == id,
                Sale.status == 'confirmed'
            ).group_by(Product.name).all()

            context['products'] = [{
                'name': p.name,
                'quantity': p.qty,
                'total': p.total,
                'last_date': p.last_date.strftime('%Y-%m-%d') if p.last_date else '-'
            } for p in s_lines]

            # IF PARTNER: Fetch products they have a share in (Products they EARN from)
            if entity.customer_type == 'partner':
                shared_products_query = db.session.query(
                    Product.name,
                    ProductPartner.percentage,
                    func.sum(SaleLine.quantity).label('qty'),
                    func.sum(SaleLine.line_total).label('total_sales'),
                    func.max(Sale.sale_date).label('last_date')
                ).join(ProductPartner, Product.id == ProductPartner.product_id)\
                 .join(SaleLine, SaleLine.product_id == Product.id)\
                 .join(Sale, Sale.id == SaleLine.sale_id)\
                 .filter(
                     ProductPartner.partner_customer_id == id,
                     Sale.status == 'confirmed'
                ).group_by(Product.name, ProductPartner.percentage).all()

                for sp in shared_products_query:
                    share_amount = sp.total_sales * (sp.percentage / 100)
                    context['products'].append({
                        'name': f"{sp.name} (Share: {sp.percentage}%)",
                        'quantity': sp.qty,
                        'total': share_amount,
                        'last_date': sp.last_date.strftime('%Y-%m-%d') if sp.last_date else '-'
                    })

            # IF MERCHANT: Fetch products they own (Products they EARN from)
            if entity.customer_type == 'merchant':
                merchant_products_query = db.session.query(
                    Product.name,
                    Product.merchant_share,
                    func.sum(SaleLine.quantity).label('qty'),
                    func.sum(SaleLine.line_total).label('total_sales'),
                    func.max(Sale.sale_date).label('last_date')
                ).join(SaleLine, SaleLine.product_id == Product.id)\
                 .join(Sale, Sale.id == SaleLine.sale_id)\
                 .filter(
                     Product.merchant_customer_id == id,
                     Sale.status == 'confirmed'
                ).group_by(Product.name, Product.merchant_share).all()

                for mp in merchant_products_query:
                    share_pct = mp.merchant_share or 100
                    share_amount = mp.total_sales * (share_pct / 100)
                    context['products'].append({
                        'name': f"{mp.name} (Merchant: {share_pct}%)",
                        'quantity': mp.qty,
                        'total': share_amount,
                        'last_date': mp.last_date.strftime('%Y-%m-%d') if mp.last_date else '-'
                    })

            # Invoices (Sales) — F3: بلا المستندات المؤرشفة
            sales = (
                Sale.query
                .filter_by(customer_id=id)
                .filter(~Sale.id.in_(_archived_record_ids('sales')))
                .order_by(Sale.sale_date.desc()).all()
            )
            context['invoices'] = [{
                'number': s.sale_number,
                'date': s.sale_date.strftime('%Y-%m-%d'),
                'status': s.status,
                'amount': s.amount_base or 0,
                'paid': s.paid_amount_base or 0,
                'balance': (s.amount_base or 0) - (s.paid_amount_base or 0)
            } for s in sales]

            # Transactions (Receipts + Payments) — F3: بلا السندات المؤرشفة
            receipts = (
                Receipt.query
                .filter_by(customer_id=id)
                .filter(~Receipt.id.in_(_archived_record_ids('receipts')))
                .all()
            )
            payments_out = (
                Payment.query
                .filter_by(customer_id=id, direction='outgoing')
                .filter(~Payment.id.in_(_archived_record_ids('payments')))
                .all()
            )

            all_trans = []
            for r in receipts:
                all_trans.append({
                    'number': r.receipt_number,
                    'type': 'in',  # Money In
                    'date': r.receipt_date,
                    'amount': r.amount_base,
                    'method': r.payment_method,
                    'notes': 'قبض'
                })
            for p in payments_out:
                all_trans.append({
                    'number': p.payment_number,
                    'type': 'out',  # Money Out
                    'date': p.payment_date,
                    'amount': p.amount_base,
                    'method': p.payment_method,
                    'notes': p.notes or 'دفع'
                })

            all_trans.sort(key=lambda x: x['date'], reverse=True)
            for t in all_trans:
                t['date'] = t['date'].strftime('%Y-%m-%d')

            context['transactions'] = all_trans

        return render_template('reports/partials/entity_report.html', **context)

    except HTTPException:
        raise
    except Exception as e:
        current_app.logger.error(f'Entity report fragment error: {e}', exc_info=True)
        return render_template('reports/partials/entity_report.html',
                               error='حدث خطأ أثناء تحميل التقرير.'), 500


@reports_bp.route('/top-selling')
@login_required
@permission_required('view_reports')
def top_selling():
    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)
    limit = request.args.get('limit', 20, type=int)

    query = db.session.query(
        Product.id,
        Product.name,
        func.sum(SaleLine.quantity).label('total_quantity'),
        func.sum(SaleLine.line_total).label('total_sales')
    ).join(
        SaleLine, Product.id == SaleLine.product_id
    ).join(
        Sale, SaleLine.sale_id == Sale.id
    ).filter(
        Sale.status == 'confirmed'
    )

    if date_from:
        query = query.filter(func.date(Sale.sale_date) >= date_from)

    if date_to:
        query = query.filter(func.date(Sale.sale_date) <= date_to)

    products = query.group_by(
        Product.id, Product.name
    ).order_by(
        func.sum(SaleLine.quantity).desc()
    ).limit(limit).all()

    return render_template('reports/top_selling.html', products=products)

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: NEW REPORTS
# ═══════════════════════════════════════════════════════════════════════════════


@reports_bp.route('/inventory-valuation')
@login_required
@permission_required('view_reports')
def inventory_valuation():
    """
    تقرير تقييم المخزون — Inventory Valuation
    Per warehouse/category, qty × cost, totals.

    SECURITY: valuation exposes qty × cost — owner/super_admin/manager only.
    view_reports alone must never reveal cost-based inventory value.
    """
    if not current_user.can_see_costs():
        abort(403)
    from models import Warehouse, ProductCategory

    warehouse_id = request.args.get('warehouse_id', type=int)
    category_id = request.args.get('category_id', type=int)

    # Schema reality: Product carries one global current_stock column with no
    # per-product warehouse link; per-warehouse quantities live in StockMovement
    # (warehouse_id NOT NULL). When a warehouse filter is present we therefore
    # aggregate net movement quantity per product for that warehouse instead of
    # using the global stock figure.
    qty_by_product = {}
    if warehouse_id:
        movement_rows = db.session.query(
            StockMovement.product_id.label('product_id'),
            func.sum(StockMovement.quantity).label('net_qty'),
        ).filter(
            StockMovement.warehouse_id == warehouse_id
        ).group_by(StockMovement.product_id).all()
        qty_by_product = {
            row.product_id: (row.net_qty or Decimal('0'))
            for row in movement_rows
        }

    products_query = Product.query.filter(Product.is_active.is_(True))

    if warehouse_id:
        stocked_ids = [pid for pid, qty in qty_by_product.items() if qty > 0]
        products_query = products_query.filter(Product.id.in_(stocked_ids or [0]))
    else:
        products_query = products_query.filter(Product.current_stock > 0)

    if category_id:
        products_query = products_query.filter_by(category_id=category_id)

    products = products_query.order_by(Product.name).all()

    # Group by category
    categories_data = {}
    total_value = Decimal('0')
    total_qty = Decimal('0')

    for product in products:
        if warehouse_id:
            qty = qty_by_product.get(product.id) or Decimal('0')
        else:
            qty = product.current_stock or Decimal('0')
        # أساس التقييم: المتوسط المتحرك لتكلفة الوحدة (average_cost) —
        # وهو نفس الأساس الذي يحمله حساب المخزون في الأستاذ العام
        # (المبلغ المدفوع فعلياً)، فالتقرير يلتقي بالميزانية.
        cost = Decimal(str(product.average_cost or 0))
        if cost <= 0:
            cost = CostingService.current_unit_cost(product)
        value = qty * cost
        total_value += value
        total_qty += qty

        cat_name = product.category.name if product.category else 'بدون فئة'
        cat_name_ar = product.category.name_ar if product.category and product.category.name_ar else cat_name

        if cat_name not in categories_data:
            categories_data[cat_name] = {
                'name': cat_name,
                'name_ar': cat_name_ar,
                'products': [],
                'total_qty': Decimal('0'),
                'total_value': Decimal('0'),
                'product_count': 0,
            }

        categories_data[cat_name]['products'].append({
            'product': product,
            'qty': qty,
            'cost': cost,
            'average_cost': cost,
            'reference_cost': Decimal(str(product.cost_price or 0)),
            'value': value,
        })
        categories_data[cat_name]['total_qty'] += qty
        categories_data[cat_name]['total_value'] += value
        categories_data[cat_name]['product_count'] += 1

    warehouses = Warehouse.query.filter_by(is_active=True).all()
    categories = ProductCategory.query.filter_by(is_active=True).all()

    # F7: قياس فرق المخزون عن الأستاذ العام.
    # قيمة الإدارة (qty × average_cost) تُقارن بقيد حساب المخزون في
    # الأستاذ العام — والطرفين على **نفس الأساس** (المبلغ المدفوع
    # فعلياً، صافي خصم المستند) بعد التحويل إلى المتوسط المتحرك — فالفرق
    # المقاس فرق حقيقي لا فرق تعريف. خدمة
    # services/inventory_reconciliation تقيس الفرق: الحركات مقابل
    # product.current_stock مقابل حساب المخزون في الأستاذ.
    # القياس يُمرَّر للقالب (يحتاج سطراً في القالب من صاحبه) ويُتاح أيضاً
    # عبر /reports/inventory-valuation/reconciliation.
    inventory_reconciliation = _inventory_reconciliation_summary()

    return render_template('reports/inventory_valuation.html',
                           categories_data=categories_data,
                           warehouses=warehouses,
                           categories_list=categories,
                           total_value=total_value,
                           total_qty=total_qty,
                           total_products=len(products),
                           inventory_reconciliation=inventory_reconciliation,
                           selected_warehouse=warehouse_id,
                           selected_category=category_id)


def _inventory_reconciliation_summary():
    """F7: خلاصة قياس فرق المخزون (قراءة فقط، لا ترمي استثناء).

    تعيد قاموساً جاهزاً للعرض: أساس التقييم، رصيد حساب المخزون في الأستاذ،
    قيمة التقييم، والفرق بينهما — بدل إخفائه. المبالغ Decimal داخلياً
    وتُحوَّل إلى float للعرض/JSON (نفس أسلوب بقية صفحات التقارير).

    أساس التقييم هو **المتوسط المتحرك** (qty × average_cost) — نفس أساس
    قيد حساب المخزون في الأستاذ، فالفرق المقاس هو فرق حقيقي.
    """
    def _f(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _row(row):
        return {key: (_f(value) if isinstance(value, Decimal) else value)
                for key, value in row.items()}

    summary = {
        'available': False,
        'valuation_basis': 'qty × average_cost (متوسط التكلفة المتحرك)',
        'control_accounts': [],
        'control_balance': None,
        'valuation_at_cost_price': None,
        'valuation_at_average_cost': None,
        'gl_difference': None,
        'stock_vs_movements_difference': None,
        'break_count': 0,
        'balanced': None,
    }
    try:
        from services.inventory_reconciliation import reconcile_inventory

        report = reconcile_inventory(include_inactive=False)
    except Exception as exc:  # pragma: no cover - measurement must not break the page
        current_app.logger.warning(f'inventory reconciliation unavailable: {exc}')
        summary['error'] = str(exc)
        return summary

    summary.update({
        'available': True,
        'control_accounts': report.get('control_accounts', []),
        'control_balance': _f(report.get('control_balance')),
        'valuation_at_cost_price': _f(report.get('total_valuation_at_cost_price')),
        'valuation_at_average_cost': _f(report.get('total_valuation_at_average_cost')),
        'gl_difference': _f(report.get('gl_difference')),
        'unattributed_gl_balance': _f(report.get('unattributed_gl_balance')),
        'stock_vs_movements_difference': _f(report.get('difference')),
        'total_quantity_from_movements': _f(report.get('total_quantity_from_movements')),
        'total_current_stock': _f(report.get('total_current_stock')),
        'break_count': len(report.get('breaks', [])),
        'balanced': report.get('balanced'),
        'products': [_row(row) for row in report.get('products', [])],
        'breaks': [_row(row) for row in report.get('breaks', [])],
    })
    return summary


@reports_bp.route('/inventory-valuation/reconciliation')
@login_required
@permission_required('view_reports')
def inventory_valuation_reconciliation():
    """F7: قياس فرق تقييم المخزون عن الأستاذ العام (JSON).

    نفس gate التكلفة في صفحة التقييم: الأرقام تعتمد على سعر التكلفة.
    """
    if not current_user.can_see_costs():
        abort(403)

    return jsonify(_inventory_reconciliation_summary())


@reports_bp.route('/ap-aging')
@login_required
@permission_required('view_reports')
def ap_aging():
    """
    تقرير أعمار الذمم الدائنة — Accounts Payable Aging
    الآن يستخدم خدمة التحليل الموحدة (AgingAnalysisService) التي تستند
    إلى تاريخ الاستحقاق (due_date) لا تاريخ الفاتورة، فتُقسَم الأرصدة
    حسب المتأخرات الحقيقية (overdue) لا العمر.
    """
    from services.aging_analysis_service import AgingAnalysisService

    report = AgingAnalysisService.get_payables_aging()

    # تحويل التقرير إلى التنسيق المتوقع من القالب
    supplier_aging = []
    for supplier_data in report.get('suppliers', []):
        sup = supplier_data['supplier']
        # تحديد السلة بناءً على المتأخرات (overdue) للعرض
        overdue = supplier_data.get('overdue_total', 0)
        # للتوافق مع القالب الحالي نحسب days_old بناءً على أقدم فاتورة
        # لكن السلة الحقيقية هي overdue_buckets
        supplier_aging.append({
            'supplier': sup,
            'total_purchases': supplier_data.get('total', 0) + supplier_data.get('overdue_total', 0),
            'total_paid': supplier_data.get('total', 0) + supplier_data.get('overdue_total', 0) - supplier_data.get('total', 0),
            'balance': supplier_data.get('total', 0),
            'days_old': 0,  # غير مستخدم للعرض الجديد
            'bucket': 'current' if supplier_data.get('overdue_total', 0) == 0 else 'over_90',
            'payment_terms': sup.payment_terms_days or 0,
            'overdue_buckets': supplier_data.get('overdue_buckets', {}),
            'overdue_total': supplier_data.get('overdue_total', 0),
        })

    aging_buckets = {
        'current': report['totals'].get('0-30', 0),
        'days_31_60': report['totals'].get('31-60', 0),
        'days_61_90': report['totals'].get('61-90', 0),
        'over_90': report['totals'].get('91-120', 0) + report['totals'].get('over_120', 0),
    }
    total_payable = report['totals'].get('total', 0)

    return render_template('reports/ap_aging.html',
                           supplier_aging=supplier_aging,
                           aging_buckets=aging_buckets,
                           total_payable=total_payable,
                           overdue_buckets=report['overdue_buckets'],
                           overdue_total=report['overdue_total'],
                           report=report)


@reports_bp.route('/cash-flow')
@login_required
@permission_required('view_reports')
def cash_flow():
    """
    قائمة التدفقات النقدية — Cash Flow Statement
    Operating / Investing / Financing from GL data.

    المصدر الوحيد: CashFlowService.generate_gl_cash_flow() — نفس البيانات
    التي تعرضها صفحة دفتر الأستاذ (/ledger/cash-flow) ونفس ملف التصدير.
    """
    from services.cash_flow_service import CashFlowService

    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)

    report = CashFlowService.generate_gl_cash_flow(date_from, date_to)

    return render_template('reports/cash_flow.html',
                           report=report,
                           operating_items=report['operating_items'],
                           investing_items=report['investing_items'],
                           financing_items=report['financing_items'],
                           operating_total=report['operating_total'],
                           investing_total=report['investing_total'],
                           financing_total=report['financing_total'],
                           net_change=report['net_change'],
                           cash_beginning=report['cash_beginning'],
                           cash_ending=report['cash_ending'],
                           cash_ending_computed=report['cash_ending_computed'],
                           tie_out=report['tie_out'],
                           date_from=date_from,
                           date_to=date_to)


def _vat_base_amounts(document):
    """(الأساس الخاضع للضريبة، الضريبة) بعملة الأساس لمستند واحد.

    المستند يحمل الضريبة بعملة المعاملة (tax_amount) والإجمالي بعملة
    الأساس (amount_base). لذلك تُحوَّل الضريبة إلى عملة الأساس بسعر صرف
    المستند نفسه، ثم يُشتق الأساس الخاضع (بدون ضريبة) من الإجمالي:
        base_net = amount_base − (tax_amount × exchange_rate)
    """
    gross_base = document.amount_base or Decimal('0')
    tax_rate = document.tax_rate or Decimal('0')
    tax_txn = document.tax_amount or Decimal('0')
    exchange_rate = document.exchange_rate or Decimal('1')
    if exchange_rate <= 0:
        exchange_rate = Decimal('1')

    tax_base = (Decimal(str(tax_txn)) * Decimal(str(exchange_rate))).quantize(
        Decimal('0.001'), rounding=ROUND_HALF_UP)
    net_base = gross_base - tax_base
    return net_base, tax_base, tax_rate


def _return_vat_amounts(product_return):
    """(الأساس، الضريبة) بإشعار دائن (مرتجع) بعملة الأساس.

    المرتجع لا يحمل عمود ضريبة؛ الضريبة تُحسب بنفس سياسة
    services/return_service.py (لكل سطر على حدة ثم الجمع) من فاتورة
    البيع الأصلية، لأن دفتر الأستاذينكز الضريبة على نفس المبلغ.
    """
    from models import ProductReturnLine
    from services.tax_engine import TaxEngine

    sale = product_return.sale
    tax_rate = (sale.tax_rate if sale else Decimal('0')) or Decimal('0')
    exchange_rate = product_return.exchange_rate or Decimal('1')
    if exchange_rate <= 0:
        exchange_rate = Decimal('1')

    line_totals = [
        Decimal(str(line.line_total))
        for line in ProductReturnLine.query.filter_by(
            return_id=product_return.id).all()
    ]
    breakdown = TaxEngine.compute_invoice(
        [{'amount': total, 'rate': tax_rate} for total in line_totals])

    tax_base = (breakdown['total_tax'] * Decimal(str(exchange_rate))).quantize(
        Decimal('0.001'), rounding=ROUND_HALF_UP)
    net_base = (product_return.amount_base or Decimal('0')).quantize(
        Decimal('0.001'), rounding=ROUND_HALF_UP)
    return net_base, tax_base, tax_rate


def _vat_report_data(date_from=None, date_to=None):
    """تقرير ضريبة القيمة المضافة — مصدر واحد للصفحة والتصدير.

    سياسة موحّدة:
      • العملة: عملة الأساس فقط (الإجمالي والأساس الخاضع والضريبة).
      • الأساس الخاضع: المبلغ قبل الضريبة (لا الإجمالي الشامل لها).
      • المرتجعات (إشعارات الدائنة): تُخصم من المبيعات الخاضعة ومن
        ضريبة المخرجات — دفتر الأستاذينكز حساب ضريبة المخرجات عند
        المرتجع، فإغفاله يُظهر ضريبة مخرجات أعلى من الحقيقة.
      • المستندات المؤرشفة (أرشفة تعكس القيود وتترك الحالة 'confirmed')
        تُستبعد من التقرير.
    """
    from models import ArchivedRecord  # noqa: F401  (مستخدم عبر المساعد)

    # --- المبيعات الخاضعة للضريبة (ضريبة مخرجات) ---
    sales_query = Sale.query.filter(
        Sale.status == 'confirmed',
        Sale.is_active.is_(True),
    )
    if date_from:
        sales_query = sales_query.filter(func.date(Sale.sale_date) >= date_from)
    if date_to:
        sales_query = sales_query.filter(func.date(Sale.sale_date) <= date_to)
    sales_query = sales_query.filter(~Sale.id.in_(_archived_record_ids('sales')))

    taxable_sales = []
    exempt_sales = []
    total_taxable_sales = Decimal('0')
    total_output_vat = Decimal('0')
    total_exempt_sales = Decimal('0')

    for sale in sales_query.order_by(Sale.sale_date).all():
        net_base, tax_base, tax_rate = _vat_base_amounts(sale)
        row = {
            'number': sale.sale_number,
            'date': sale.sale_date,
            'party': sale.customer.name if sale.customer else 'عميل نقدي',
            'net_amount': net_base,
            'gross_amount': sale.amount_base or Decimal('0'),
            'tax_rate': tax_rate,
            'tax_amount': tax_base,
        }
        if tax_rate > 0:
            taxable_sales.append(row)
            total_taxable_sales += net_base
            total_output_vat += tax_base
        else:
            exempt_sales.append(row)
            total_exempt_sales += row['gross_amount']

    # --- إشعارات الدائنة (المرتجعات) ---
    from models import ProductReturn

    returns_query = ProductReturn.query.filter(
        ProductReturn.status.notin_(['pending', 'cancelled'])
    )
    if date_from:
        returns_query = returns_query.filter(
            func.date(ProductReturn.return_date) >= date_from)
    if date_to:
        returns_query = returns_query.filter(
            func.date(ProductReturn.return_date) <= date_to)

    credit_notes = []
    total_credit_notes_net = Decimal('0')
    total_credit_notes_vat = Decimal('0')

    for product_return in returns_query.order_by(ProductReturn.return_date).all():
        net_base, tax_base, tax_rate = _return_vat_amounts(product_return)
        customer = product_return.customer
        credit_notes.append({
            'number': product_return.return_number,
            'date': product_return.return_date,
            'party': customer.name if customer else 'عميل نقدي',
            'net_amount': -net_base,
            'gross_amount': -(product_return.amount_base or Decimal('0')),
            'tax_rate': tax_rate,
            'tax_amount': -tax_base,
        })
        total_credit_notes_net += net_base
        total_credit_notes_vat += tax_base

    # --- المشتريات الخاضعة للضريبة (ضريبة مدخلات) ---
    purchases_query = Purchase.query.filter(Purchase.status == 'confirmed')
    if date_from:
        purchases_query = purchases_query.filter(
            func.date(Purchase.purchase_date) >= date_from)
    if date_to:
        purchases_query = purchases_query.filter(
            func.date(Purchase.purchase_date) <= date_to)
    purchases_query = purchases_query.filter(
        ~Purchase.id.in_(_archived_record_ids('purchases')))

    taxable_purchases = []
    exempt_purchases = []
    total_taxable_purchases = Decimal('0')
    total_input_vat = Decimal('0')
    total_exempt_purchases = Decimal('0')

    for purchase in purchases_query.order_by(Purchase.purchase_date).all():
        net_base, tax_base, tax_rate = _vat_base_amounts(purchase)
        row = {
            'number': purchase.purchase_number,
            'date': purchase.purchase_date,
            'party': (purchase.supplier.name if purchase.supplier
                      else purchase.supplier_name),
            'net_amount': net_base,
            'gross_amount': purchase.amount_base or Decimal('0'),
            'tax_rate': tax_rate,
            'tax_amount': tax_base,
        }
        if tax_rate > 0:
            taxable_purchases.append(row)
            total_taxable_purchases += net_base
            total_input_vat += tax_base
        else:
            exempt_purchases.append(row)
            total_exempt_purchases += row['gross_amount']

    # المرتجعات تخصم من المبيعات الخاضعة ومن ضريبة المخرجات
    total_taxable_sales -= total_credit_notes_net
    total_output_vat -= total_credit_notes_vat

    net_vat = total_output_vat - total_input_vat

    summary = {
        'total_taxable_sales': total_taxable_sales,
        'total_output_vat': total_output_vat,
        'total_exempt_sales': total_exempt_sales,
        'total_credit_notes_net': total_credit_notes_net,
        'total_credit_notes_vat': total_credit_notes_vat,
        'total_taxable_purchases': total_taxable_purchases,
        'total_input_vat': total_input_vat,
        'total_exempt_purchases': total_exempt_purchases,
        'net_vat': net_vat,
        'vat_payable': net_vat if net_vat > 0 else Decimal('0'),
        'vat_refund': abs(net_vat) if net_vat < 0 else Decimal('0'),
    }

    return {
        'taxable_sales': taxable_sales,
        'exempt_sales': exempt_sales,
        'credit_notes': credit_notes,
        'taxable_purchases': taxable_purchases,
        'exempt_purchases': exempt_purchases,
        'summary': summary,
        'date_from': date_from or '',
        'date_to': date_to or '',
    }


@reports_bp.route('/vat-report')
@login_required
@permission_required('view_reports')
def vat_report():
    """
    تقرير ضريبة القيمة المضافة — VAT Report (UAE 5%)
    Taxable sales/purchases, output/input VAT, net payable.
    """
    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)

    data = _vat_report_data(date_from, date_to)

    return render_template('reports/vat_report.html',
                           taxable_sales=data['taxable_sales'],
                           exempt_sales=data['exempt_sales'],
                           credit_notes=data['credit_notes'],
                           taxable_purchases=data['taxable_purchases'],
                           exempt_purchases=data['exempt_purchases'],
                           summary=data['summary'],
                           date_from=data['date_from'],
                           date_to=data['date_to'])

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3: EXPORT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


def _send_export(export_func, filename, format_type):
    """Helper: generate export and return as downloadable file."""
    output = export_func()
    mime = {
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'pdf': 'application/pdf',
        'csv': 'text/csv; charset=utf-8',
    }.get(format_type, 'application/octet-stream')
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = mime
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _audit_export(report_name, fmt, filters=None, result='granted', reason=None):
    """F4: تدقيق كل عملية تصدير.

    ``models/audit.py`` يعرض الإجراء 'export' (و'print') في واجهة سجل
    التدقيق، لكن لم يكن هناك أي استدعاء يكتبهما. الآن كل تصدير يُسجَّل
    باسم التقرير وصيغة الملف ومرشّحاته — والرفض (gate التكلفة) يُسجَّل
    أيضاً حتى لا يختفي من السجل.
    """
    changes = {
        'report': report_name,
        'format': fmt,
        'filters': filters or {},
        'result': result,
    }
    if reason:
        changes['reason'] = reason
    return create_audit_log('export', 'reports', None, changes=changes)


@reports_bp.route('/inventory-valuation/export')
@login_required
@permission_required('view_reports')
def export_inventory_valuation():
    from services.export_service import ExportService
    fmt = request.args.get('format', 'xlsx')
    # SECURITY: export carries the same cost columns as the valuation page.
    if not current_user.can_see_costs():
        # F4: الرفض يُدقَّق أيضاً (لا يُخفى تصدير مرفوض).
        _audit_export('inventory_valuation', fmt, result='denied',
                      reason='missing view_costs permission')
        abort(403)

    _audit_export('inventory_valuation', fmt, filters={'scope': 'active_products_with_stock'})

    products = Product.query.filter(Product.is_active == True, Product.current_stock > 0).order_by(Product.name).all()  # noqa: E712
    headers = ['المنتج', 'الكود', 'الفئة', 'الكمية', 'متوسط التكلفة', 'القيمة']
    rows = []
    total_value = Decimal('0')
    total_qty = Decimal('0')
    for p in products:
        qty = p.current_stock or Decimal('0')
        cost = Decimal(str(p.average_cost or 0))
        if cost <= 0:
            cost = CostingService.current_unit_cost(p)
        val = qty * cost
        total_value += val
        total_qty += qty
        rows.append([p.name, p.sku or p.part_number or '',
                     p.category.name if p.category else '',
                     float(qty), float(cost), float(val)])
    summary = {'إجمالي الكمية': float(total_qty), 'إجمالي القيمة': float(total_value)}

    # F7: لا يُخفى فرق التقييم عن الأستاذ — يُذكر في الملف المُصدَّر.
    reconciliation = _inventory_reconciliation_summary()
    if reconciliation.get('available'):
        summary['رصيد المخزون في الأستاذ العام'] = reconciliation.get('control_balance')
        summary['قيمة التقييم (كمية × متوسط التكلفة)'] = reconciliation.get('valuation_at_average_cost')
        summary['الفرق بين الأستاذ والتقييم'] = reconciliation.get('gl_difference')

    def build():
        if fmt == 'pdf':
            return ExportService.export_to_pdf('تقييم المخزون — Inventory Valuation',
                                               headers, rows, summary=summary)
        elif fmt == 'csv':
            all_rows = rows + [['', '', 'المجموع', float(total_qty), '', float(total_value)]]
            if reconciliation.get('available'):
                all_rows.append(['', '', 'رصيد المخزون في الأستاذ العام', '',
                                 '', reconciliation.get('control_balance')])
                all_rows.append(['', '', 'الفرق بين الأستاذ والتقييم', '',
                                 '', reconciliation.get('gl_difference')])
            return ExportService.export_to_csv(all_rows, headers, 'inventory_valuation.csv')
        return ExportService.export_to_excel('تقييم المخزون — Inventory Valuation',
                                             headers, rows, summary=summary)

    ext = {'xlsx': 'xlsx', 'pdf': 'pdf', 'csv': 'csv'}.get(fmt, 'xlsx')
    return _send_export(build, f'inventory_valuation.{ext}', ext)


@reports_bp.route('/ap-aging/export')
@login_required
@permission_required('view_reports')
def export_ap_aging():
    from services.aging_analysis_service import AgingAnalysisService
    from services.export_service import ExportService
    fmt = request.args.get('format', 'xlsx')

    report = AgingAnalysisService.get_payables_aging()
    _audit_export('ap_aging', fmt, filters={'scope': 'active_suppliers'})

    headers = ['المورد', 'إجمالي المشتريات', 'المدفوع', 'الرصيد المستحق', 'المتأخر', 'شروط الدفع']
    rows = []
    total_payable = Decimal('0')
    for supplier_data in report.get('suppliers', []):
        sup = supplier_data['supplier']
        balance = supplier_data.get('total', 0)
        if balance <= 0:
            continue
        total_payable += balance
        overdue = supplier_data.get('overdue_total', 0)
        rows.append([sup.name, float(supplier_data.get('total', 0) + overdue),
                     float(overdue), float(balance), float(supplier_data.get('overdue_total', 0)),
                     sup.payment_terms_days or 0])

    summary = {'إجمالي الذمم الدائنة': float(report['totals'].get('total', 0))}

    def build():
        if fmt == 'pdf':
            return ExportService.export_to_pdf('أعمار الذمم الدائنة — AP Aging',
                                               headers, rows, summary=summary)
        elif fmt == 'csv':
            return ExportService.export_to_csv(rows, ['المورد', 'إجمالي المشتريات', 'المدفوع', 'الرصيد المستحق', 'المتأخر', 'شروط الدفع'], 'ap_aging.csv')
        return ExportService.export_to_excel('أعمار الذمم الدائنة — AP Aging',
                                             headers, rows, summary=summary)

    ext = {'xlsx': 'xlsx', 'pdf': 'pdf', 'csv': 'csv'}.get(fmt, 'xlsx')
    return _send_export(build, f'ap_aging.{ext}', ext)


@reports_bp.route('/cash-flow/export')
@login_required
@permission_required('view_reports')
def export_cash_flow():
    """تصدير قائمة التدفقات النقدية — نفس بيانات الشاشة تماماً."""
    from services.export_service import ExportService
    from services.cash_flow_service import CashFlowService
    fmt = request.args.get('format', 'xlsx')
    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)

    _audit_export('cash_flow', fmt, filters={'date_from': date_from, 'date_to': date_to})

    # نفس المصدر الواحد المستخدم في الشاشة — نفس الصفوف ونفس الإجماليات.
    report = CashFlowService.generate_gl_cash_flow(date_from, date_to)

    headers = ['القسم', 'الحساب', 'المدين', 'الدائن', 'صافي']
    rows = []
    for row in report['rows']:
        rows.append([
            row['section_label'],
            row['label'],
            float(row['debit']),
            float(row['credit']),
            float(row['net']),
        ])

    summary = {
        CashFlowService.SECTION_LABELS['operating']: float(report['operating_total']),
        CashFlowService.SECTION_LABELS['investing']: float(report['investing_total']),
        CashFlowService.SECTION_LABELS['financing']: float(report['financing_total']),
        'الصافي': float(report['net_change']),
    }

    def build():
        if fmt == 'pdf':
            return ExportService.export_to_pdf('قائمة التدفقات النقدية — Cash Flow',
                                               headers, rows, summary=summary)
        elif fmt == 'csv':
            return ExportService.export_to_csv(rows, headers, 'cash_flow.csv')
        return ExportService.export_to_excel('قائمة التدفقات النقدية — Cash Flow',
                                             headers, rows, summary=summary)

    ext = {'xlsx': 'xlsx', 'pdf': 'pdf', 'csv': 'csv'}.get(fmt, 'xlsx')
    return _send_export(build, f'cash_flow.{ext}', ext)


@reports_bp.route('/vat-report/export')
@login_required
@permission_required('view_reports')
def export_vat_report():  # noqa: C901
    """تصدير تقرير ضريبة القيمة المضافة — نفس أرقام الشاشة تماماً."""
    from services.export_service import ExportService
    fmt = request.args.get('format', 'xlsx')
    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)

    _audit_export('vat_report', fmt, filters={'date_from': date_from, 'date_to': date_to})

    # نفس المصدر الواحد المستخدم في الشاشة ⇒ نفس الصفوف ونفس الإجماليات.
    data = _vat_report_data(date_from, date_to)
    summary = data['summary']

    sales_headers = ['رقم الفاتورة', 'التاريخ', 'العميل', 'الأساس الخاضع',
                      'نسبة الضريبة', 'الضريبة']
    purchase_headers = ['رقم الفاتورة', 'التاريخ', 'المورد', 'الأساس الخاضع',
                        'نسبة الضريبة', 'الضريبة']
    credit_note_headers = ['رقم الإشعار', 'التاريخ', 'العميل', 'الأساس الخاضع',
                           'نسبة الضريبة', 'الضريبة']

    def _sale_row(row):
        return [row['number'],
                row['date'].strftime('%Y-%m-%d') if row['date'] else '',
                row['party'], float(row['net_amount']), f"{row['tax_rate']}%",
                float(row['tax_amount'])]

    def _purchase_row(row):
        return [row['number'],
                row['date'].strftime('%Y-%m-%d') if row['date'] else '',
                row['party'], float(row['net_amount']), f"{row['tax_rate']}%",
                float(row['tax_amount'])]

    sales_rows = [_sale_row(r) for r in data['taxable_sales']]
    exempt_sales_rows = [_sale_row(r) for r in data['exempt_sales']]
    credit_note_rows = [_sale_row(r) for r in data['credit_notes']]
    purchase_rows = [_purchase_row(r) for r in data['taxable_purchases']]
    exempt_purchase_rows = [_purchase_row(r) for r in data['exempt_purchases']]

    total_output = summary['total_output_vat']
    total_input = summary['total_input_vat']
    net_vat = summary['net_vat']

    def build_xlsx():
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb = Workbook()

        def _sheet(title, headers, rows, fill_color, total_row=None):
            ws = wb.create_sheet(title)
            ws.sheet_view.rightToLeft = True
            hf = Font(bold=True, color='FFFFFF', size=11)
            hfill = PatternFill(start_color=fill_color, end_color=fill_color,
                                fill_type='solid')
            for ci, h in enumerate(headers, 1):
                c = ws.cell(row=1, column=ci, value=h)
                c.font = hf
                c.fill = hfill
            for ri, row in enumerate(rows, 2):
                for ci, val in enumerate(row, 1):
                    ws.cell(row=ri, column=ci, value=val)
            if total_row is not None:
                label, net_value, tax_value = total_row
                r = len(rows) + 2
                ws.cell(row=r, column=3, value=label).font = Font(bold=True)
                ws.cell(row=r, column=4, value=float(net_value)).font = Font(bold=True)
                ws.cell(row=r, column=6, value=float(tax_value)).font = Font(bold=True)
            return ws

        _sheet('المبيعات الخاضعة', sales_headers, sales_rows, 'C0392B',
               ('المجموع', summary['total_taxable_sales'], total_output))
        _sheet('المبيعات المعفاة', sales_headers, exempt_sales_rows, '7F8C8D',
               ('المجموع', summary['total_exempt_sales'], 0))
        _sheet('إشعارات الدائنة', credit_note_headers, credit_note_rows, '8E44AD',
               ('المجموع', -summary['total_credit_notes_net'],
                -summary['total_credit_notes_vat']))
        _sheet('المشتريات الخاضعة', purchase_headers, purchase_rows, '27AE60',
               ('المجموع', summary['total_taxable_purchases'], total_input))
        _sheet('المشتريات المعفاة', purchase_headers, exempt_purchase_rows,
               '7F8C8D', ('المجموع', summary['total_exempt_purchases'], 0))

        ws3 = wb.create_sheet('الملخص')
        ws3.sheet_view.rightToLeft = True
        summary_rows = [
            ('الأساس الخاضع للمبيعات', float(summary['total_taxable_sales'])),
            ('ضريبة المبيعات (Output VAT)', float(total_output)),
            ('إجمالي المبيعات المعفاة', float(summary['total_exempt_sales'])),
            ('إشعارات الدائنة (أساس)', float(-summary['total_credit_notes_net'])),
            ('ضريبة إشعارات الدائنة', float(-summary['total_credit_notes_vat'])),
            ('الأساس الخاضع للمشتريات', float(summary['total_taxable_purchases'])),
            ('ضريبة المشتريات (Input VAT)', float(total_input)),
            ('إجمالي المشتريات المعفاة', float(summary['total_exempt_purchases'])),
            ('الرصيد النهائي', float(net_vat)),
        ]
        for ri, (label, value) in enumerate(summary_rows, 1):
            ws3.cell(row=ri, column=1, value=label).font = Font(
                bold=True, size=12 if label == 'الرصيد النهائي' else 11)
            ws3.cell(row=ri, column=2, value=value).font = Font(
                bold=True, size=12 if label == 'الرصيد النهائي' else 11)

        # الورقة الأولى يجب أن تكون قابلة للعرض (Excel لا يقبل ورقة بلا عنوان)
        default_sheet = wb['Sheet']
        wb.remove(default_sheet)
        wb.active = 0

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    def build():
        if fmt == 'pdf':
            # كل قسم بعناوينه الخاصة — لا تختلط صفوف المبيعات والمشتريات
            all_rows = (
                [['── المبيعات الخاضعة للضريبة ──'] + [''] * 5] + [sales_headers] + sales_rows +
                [['── المبيعات المعفاة ──'] + [''] * 5] + [sales_headers] + exempt_sales_rows +
                [['── إشعارات الدائنة (المرتجعات) ──'] + [''] * 5] + [credit_note_headers] + credit_note_rows +
                [['── المشتريات الخاضعة للضريبة ──'] + [''] * 5] + [purchase_headers] + purchase_rows +
                [['── المشتريات المعفاة ──'] + [''] * 5] + [purchase_headers] + exempt_purchase_rows
            )
            summary_pdf = {
                'Output VAT': float(total_output),
                'Input VAT': float(total_input),
                'Credit Notes VAT': float(-summary['total_credit_notes_vat']),
                'Exempt Sales': float(summary['total_exempt_sales']),
                'Exempt Purchases': float(summary['total_exempt_purchases']),
                'Net VAT': float(net_vat),
            }
            return ExportService.export_to_pdf('تقرير VAT — UAE 5%',
                                               sales_headers, all_rows,
                                               summary=summary_pdf)
        elif fmt == 'csv':
            # كل قسم بعناوينه الخاصة — لا تُدمج المشتريات تحت عناوين المبيعات
            combined = (
                [['── المبيعات الخاضعة للضريبة ──'] + [''] * 5] + [sales_headers] + sales_rows +
                [['── المبيعات المعفاة ──'] + [''] * 5] + [sales_headers] + exempt_sales_rows +
                [['── إشعارات الدائنة (المرتجعات) ──'] + [''] * 5] + [credit_note_headers] + credit_note_rows +
                [['── المشتريات الخاضعة للضريبة ──'] + [''] * 5] + [purchase_headers] + purchase_rows +
                [['── المشتريات المعفاة ──'] + [''] * 5] + [purchase_headers] + exempt_purchase_rows +
                [['── الملخص ──'] + [''] * 5,
                 ['الأساس الخاضع للمبيعات', float(summary['total_taxable_sales'])],
                 ['ضريبة المبيعات (Output VAT)', float(total_output)],
                 ['إجمالي المبيعات المعفاة', float(summary['total_exempt_sales'])],
                 ['إشعارات الدائنة (أساس)', float(-summary['total_credit_notes_net'])],
                 ['ضريبة إشعارات الدائنة', float(-summary['total_credit_notes_vat'])],
                 ['الأساس الخاضع للمشتريات', float(summary['total_taxable_purchases'])],
                 ['ضريبة المشتريات (Input VAT)', float(total_input)],
                 ['إجمالي المشتريات المعفاة', float(summary['total_exempt_purchases'])],
                 ['الرصيد النهائي', float(net_vat)]]
            )
            return ExportService.export_to_csv(combined, sales_headers, 'vat_report.csv')
        return build_xlsx()

    ext = {'xlsx': 'xlsx', 'pdf': 'pdf', 'csv': 'csv'}.get(fmt, 'xlsx')
    return _send_export(build, f'vat_report.{ext}', ext)
