"""
Inventory Reconciliation — قياس فرق المخزون بين الحركات والأستاذ العام
======================================================================

لماذا هذا الملف موجود
----------------------
تقرير المخزون (``routes/reports.py::inventory``) يُقيّم المخزون المتبقي
بـ ``qty × product.cost_price``، و ``services/stock_service.py`` يُحدّث
``cost_price`` بآخر سعر شراء. النتيجة: مخزون اشتُري بسعر 10 ثم اشتُري
مرة أخرى بسعر 12 يُقيَّم بالكامل بسعر 12، بينما الأستاذ العام يحمل 10
للوحدات الأصلية — فلا يلتقي تقرير الإدارة مع الميزانية أبداً.

تكلفة متوسط متحرك قرار تجاري وخارج نطاق هذا الملف. ما هو داخل نطاقه هو
**قياس** الفرق وإظهاره بدل إخفائه: لكل منتج نُقارن

  1. الكمية الفعلية من حركات المخزون (المصدر الحقيقي للحركة),
  2. ``product.current_stock`` (العمود denormalized),
  3. القيمة الدفترية التي يحملها حساب المخزون في الأستاذ العام،
  4. القيمة التقديرية ``qty × cost_price`` التي تستخدمها التقارير.

الفرق بين (3) و (4) هو بالضبط الفجوة التي كان التقرير يخفيها.

اصطلاحات (مطابقة لـ ``services/subledger_reconciliation.py``)
--------------------------------------------------------------
* حدود التسامح ``TOLERANCE`` = 0.01 (من utils.balance_checker).
* كل المبالغ ``Decimal`` — لا حسابات بمؤشرات عائمة إطلاقاً.
* نطاق المستأجر: التصفية التلقائية للمستأجر (TenantScopedMixin) +
  فلتر ``tenant_id`` صريح اختياري.
* الخدمة قراءة فقط: لا تعدّل أي قيد ولا أي رصيد.

توزيع القيد على المنتجات
------------------------
قيد واحد قد يخص عدة منتجات (مثلاً قيد تكلفة المبيعات لفاتورة متعددة
الأسطر)، لذلك يُوزَّع مبلغ سطر المخزون على منتجات المستند بالتناسب مع
أساس تكلفة كل منتج (الكمية × التكلفة). الأساس مجموعه يساوي مبلغ
السطر بالضبط، فالتوزيع لا يخلق فرقاً مصطنعاً. ما لا يمكن نسبته إلى
منتج (قيد يدوي مثلاً) يُعزل في ``unattributed_gl_balance`` بدل إخفائه.
"""

import logging
from decimal import Decimal

from extensions import db
from utils.balance_checker import TOLERANCE, get_control_account_balance, to_decimal

logger = logging.getLogger(__name__)

#: حساب مراقبة المخزون في دليل الحسابات (services/gl_service.py::
#: ensure_core_accounts يبذّره بالرمز '1140').
DEFAULT_INVENTORY_CONTROL_CODES = ['1140']

try:  # pragma: no cover - the resolver ships with the GL rollout
    from services.account_resolution import AccountResolver, AccountRole
except ImportError:  # pragma: no cover
    AccountResolver = None  # type: ignore[assignment,misc]
    AccountRole = None  # type: ignore[assignment,misc]


def _q2(value):
    """تقريب النقود المعروضة إلى منزلتين."""
    return Decimal(value).quantize(Decimal('0.01'))


def _q3(value):
    """تقريب المبالغ الداخلية إلى ثلاث منازل (دقة أعمدة Numeric(15,3))."""
    return Decimal(value).quantize(Decimal('0.001'))


def inventory_control_codes():
    """رموز حسابات مراقبة المخزون (مع مراعاة خريطة الأدوار)."""
    codes = []
    resolved = None
    if AccountResolver is not None and AccountRole is not None:
        try:
            resolved = AccountResolver.resolve(AccountRole.INVENTORY)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                f'AccountResolver failed for INVENTORY ({exc}) — '
                f'using the literal fallback')
    for code in ([resolved] if resolved else []) + DEFAULT_INVENTORY_CONTROL_CODES:
        if code and str(code) not in codes:
            codes.append(str(code))
    return codes


def _movement_quantities(tenant_id=None, product_ids=None):
    """مجموع كميات الحركات لكل منتج (المصدر الحقيقي)."""
    from models import StockMovement

    query = db.session.query(
        StockMovement.product_id,
        db.func.coalesce(db.func.sum(StockMovement.quantity), 0),
    ).group_by(StockMovement.product_id)

    if tenant_id is not None:
        query = query.filter(StockMovement.tenant_id == tenant_id)
    if product_ids:
        query = query.filter(StockMovement.product_id.in_(list(product_ids)))

    return {
        row[0]: to_decimal(row[1])
        for row in query.all()
    }


def _document_weights():
    """خريطة توزيع: (نوع المرجع، معرّفه) → [(product_id, weight)].

    ``weight`` هو أساس تكلفة المنتج داخل المستند (الكمية × التكلفة)،
    ومجموع الأوزان يساوي مبلغ سطر المخزون في القيد.
    """
    from models import (Product, ProductReturnLine, PurchaseLine, Sale,
                        SaleLine, StockMovement)

    weights = {}

    # ---- فواتير البيع: قيد تكلفة المبيعات (مدين COGS / دائن المخزون) ----
    sales = db.session.query(
        Sale.id,
        SaleLine.product_id,
        db.func.coalesce(db.func.sum(
            db.func.coalesce(SaleLine.cost_price, 0) * SaleLine.quantity), 0),
    ).join(SaleLine, SaleLine.sale_id == Sale.id).group_by(
        Sale.id, SaleLine.product_id).all()
    for sale_id, product_id, weight in sales:
        weights.setdefault(('Sale', sale_id), []).append(
            (product_id, to_decimal(weight)))

    # ---- المشتريات: قيد المخزون (مدين 1140) ----
    purchases = db.session.query(
        PurchaseLine.purchase_id,
        PurchaseLine.product_id,
        db.func.coalesce(db.func.sum(PurchaseLine.line_total), 0),
    ).group_by(PurchaseLine.purchase_id, PurchaseLine.product_id).all()
    for purchase_id, product_id, weight in purchases:
        weights.setdefault(('Purchase', purchase_id), []).append(
            (product_id, to_decimal(weight)))

    # ---- المرتجعات: قيد إعادة المخزون (مدين 1140) ----
    # أساس التكلفة: تكلفة سطر البيع (أساس تاريخي) وإلا تكلفة المنتج.
    product_costs = {
        pid: to_decimal(cost)
        for pid, cost in db.session.query(
            Product.id, Product.cost_price).all()
    }
    returns = db.session.query(
        ProductReturnLine.return_id,
        ProductReturnLine.product_id,
        db.func.coalesce(db.func.sum(
            db.func.coalesce(ProductReturnLine.quantity, 0)), 0),
    ).group_by(
        ProductReturnLine.return_id, ProductReturnLine.product_id).all()
    return_costs = db.session.query(
        ProductReturnLine.return_id,
        ProductReturnLine.product_id,
        db.func.coalesce(db.func.sum(
            db.func.coalesce(SaleLine.cost_price, 0) * ProductReturnLine.quantity), 0),
    ).join(
        SaleLine, SaleLine.id == ProductReturnLine.sale_line_id
    ).group_by(
        ProductReturnLine.return_id, ProductReturnLine.product_id).all()
    cost_by_return = {
        (rid, pid): to_decimal(cost) for rid, pid, cost in return_costs
    }
    for return_id, product_id, qty in returns:
        cost = cost_by_return.get((return_id, product_id))
        if not cost:
            cost = product_costs.get(product_id, Decimal('0')) * to_decimal(qty)
        weights.setdefault(('ProductReturn', return_id), []).append(
            (product_id, to_decimal(cost)))

    # ---- تسويات المخزون: مرجعه حركة المخزون نفسها ----
    movements = db.session.query(
        StockMovement.id, StockMovement.product_id).all()
    for movement_id, product_id in movements:
        weights.setdefault(('stock_adjustment', movement_id), []).append(
            (product_id, Decimal('1')))

    return weights


def _gl_inventory_lines(codes, tenant_id=None, as_of=None):
    """سطور الأستاذ العام على حسابات المخزون (بالعملة الأساسية)."""
    from models import GLAccount, GLJournalEntry, GLJournalLine

    if not codes:
        return []

    query = (
        db.session.query(
            GLJournalLine.id,
            GLJournalLine.amount_base,
            GLJournalEntry.reference_type,
            GLJournalEntry.reference_id,
        )
        .join(GLJournalEntry, GLJournalLine.entry_id == GLJournalEntry.id)
        .join(GLAccount, GLJournalLine.account_id == GLAccount.id)
        .filter(GLAccount.code.in_(codes))
    )
    if tenant_id is not None:
        query = query.filter(GLJournalLine.tenant_id == tenant_id)
    if as_of is not None:
        query = query.filter(GLJournalEntry.entry_date <= as_of)

    return query.all()


def _allocate(amount, allocation):
    """توزيع مبلغ على [(product_id, weight)] بالتناسب مع الأوزان."""
    total_weight = sum((w for _, w in allocation), Decimal('0'))
    if total_weight <= 0:
        return {}
    result = {}
    allocated = Decimal('0')
    items = list(allocation)
    for index, (product_id, weight) in enumerate(items):
        if index == len(items) - 1:
            share = amount - allocated
        else:
            share = (amount * weight / total_weight)
            allocated += share
        result[product_id] = result.get(product_id, Decimal('0')) + share
    return result


def reconcile_inventory(tenant_id=None, product_ids=None, as_of=None,
                        include_inactive=True):
    """مطابقة المخزون: الحركات مقابل العمود مقابل الأستاذ العام.

    Returns a dict::

        {
          'section': 'INVENTORY',
          'control_accounts': ['1140'],
          'control_balance': Decimal,        # رصيد المخزون في الأستاذ (أساسي)
          'total_quantity_from_movements': Decimal,
          'total_current_stock': Decimal,
          'total_valuation_at_cost_price': Decimal,
          'difference': Decimal,             # current_stock − movements
          'gl_difference': Decimal,          # control_balance − valuation
          'unattributed_gl_balance': Decimal,
          'balanced': bool,
          'products': [
              {'product_id', 'sku', 'name',
               'quantity_from_movements', 'current_stock', 'difference',
               'cost_price', 'valuation_at_cost_price',
               'gl_control_balance', 'gl_difference'},
              ...
          ],
          'breaks': [ {...} ],
        }

    ``products`` carries one row per product; ``breaks`` lists the rows
    whose difference exceeds the tolerance (|delta| > 0.01).
    """
    from models import Product

    codes = inventory_control_codes()

    product_query = Product.query
    if tenant_id is not None:
        product_query = product_query.filter(Product.tenant_id == tenant_id)
    if product_ids:
        product_query = product_query.filter(Product.id.in_(list(product_ids)))
    if not include_inactive:
        product_query = product_query.filter(Product.is_active.is_(True))

    products = product_query.order_by(Product.id).all()

    movement_totals = _movement_quantities(
        tenant_id=tenant_id, product_ids=product_ids)

    # ---- رصيد المخزون في الأستاذ العام ----
    control_balance = get_control_account_balance(codes)

    # ---- توزيع سطور الأستاذ على المنتجات ----
    weights = _document_weights()
    gl_by_product = {}
    unattributed = Decimal('0')
    for _line_id, amount_base, reference_type, reference_id in \
            _gl_inventory_lines(codes, tenant_id=tenant_id, as_of=as_of):
        amount = to_decimal(amount_base)
        allocation = weights.get((reference_type, reference_id))
        if not allocation:
            unattributed += amount
            continue
        for product_id, share in _allocate(amount, allocation).items():
            gl_by_product[product_id] = gl_by_product.get(
                product_id, Decimal('0')) + share

    rows = []
    breaks = []
    total_qty = Decimal('0')
    total_stock = Decimal('0')
    total_valuation = Decimal('0')

    for product in products:
        qty = movement_totals.get(product.id, Decimal('0'))
        stock = to_decimal(product.current_stock)
        difference = stock - qty
        cost = to_decimal(product.cost_price)
        valuation = _q3(qty * cost)
        gl_amount = _q3(gl_by_product.get(product.id, Decimal('0')))
        gl_difference = _q3(gl_amount - valuation)

        total_qty += qty
        total_stock += stock
        total_valuation += valuation

        row = {
            'product_id': product.id,
            'sku': product.sku,
            'name': product.name,
            'quantity_from_movements': _q3(qty),
            'current_stock': _q3(stock),
            'difference': _q3(difference),
            'cost_price': _q2(cost),
            'valuation_at_cost_price': _q2(valuation),
            'gl_control_balance': _q2(gl_amount),
            'gl_difference': _q2(gl_difference),
        }
        rows.append(row)

        if abs(difference) > TOLERANCE or abs(gl_difference) > TOLERANCE:
            breaks.append({
                'product_id': product.id,
                'sku': product.sku,
                'name': product.name,
                'quantity_difference': _q2(difference),
                'gl_difference': _q2(gl_difference),
            })
            logger.warning(
                'Inventory break: product#%s (%s) movement-vs-stock=%s '
                'gl-vs-valuation=%s', product.id, product.sku,
                _q2(difference), _q2(gl_difference))

    total_difference = total_stock - total_qty
    gl_difference = control_balance - total_valuation

    return {
        'section': 'INVENTORY',
        'control_accounts': codes,
        'control_balance': _q2(control_balance),
        'total_quantity_from_movements': _q3(total_qty),
        'total_current_stock': _q3(total_stock),
        'total_valuation_at_cost_price': _q2(total_valuation),
        'difference': _q3(total_difference),
        'gl_difference': _q2(gl_difference),
        'unattributed_gl_balance': _q2(unattributed),
        'balanced': (
            not breaks
            and abs(total_difference) <= TOLERANCE
            and abs(gl_difference) <= TOLERANCE
        ),
        'products': rows,
        'breaks': breaks,
    }


class InventoryReconciliation:
    """واجهة صفّية مطابقة services/subledger_reconciliation.py."""

    @staticmethod
    def reconcile_inventory(tenant_id=None, product_ids=None, as_of=None,
                            include_inactive=True):
        return reconcile_inventory(
            tenant_id=tenant_id,
            product_ids=product_ids,
            as_of=as_of,
            include_inactive=include_inactive,
        )
