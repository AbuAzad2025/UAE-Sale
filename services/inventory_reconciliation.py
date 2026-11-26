"""
Inventory Reconciliation — قياس فرق المخزون بين الحركات والأستاذ العام
======================================================================

لماذا هذا الملف موجود
----------------------
تقرير المخزون (``routes/reports.py::inventory``) يُقيّم المخزون المتبقي
بـ ``qty × average_cost`` — **متوسط التكلفة المتحرك** — وهو نفس الأساس
الذي يحمله حساب المخزون في الأستاذ العام (المبالغ المدفوعة فعلياً، صافي
خصم المستند). قبل الترحيل إلى المتوسط المتحرك كان التقييم على
``qty × product.cost_price`` (سعر آخر شراء) بينما الأستاذ يحمل 10
للوحدات الأصلية في منتج اشتُري مرتين (10 ثم 12) — فلا يلتقي تقرير
الإدارة مع الميزانية أبداً.

ما هو داخل نطاق هذا الملف هو **قياس** الفرق وإظهاره بدل إخفائه: لكل
منتج نُقارن

  1. الكمية الفعلية من حركات المخزون (المصدر الحقيقي للحركة),
  2. ``product.current_stock`` (العمود denormalized),
  3. القيمة الدفترية التي يحملها حساب المخزون في الأستاذ العام،
  4. القيمة الدفترية ``qty × average_cost`` (المتوسط المتحرك) التي
     تستخدمها التقارير.

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
from services.account_resolution import AccountResolver, AccountRole
from services.costing_service import CostingService
from utils.balance_checker import TOLERANCE, to_decimal
from utils.money import (
    qMoney as _q2,
    qQty as _q3,
    qUnitCost as _q6,
    valuation as _valuation,
)

logger = logging.getLogger(__name__)

DEFAULT_INVENTORY_CONTROL_CODES = ["1140"]


def inventory_control_codes(tenant_id=None):
    """رموز حسابات مراقبة المخزون (مع مراعاة خريطة الأدوار)."""
    resolved = AccountResolver.resolve(AccountRole.INVENTORY, tenant_id=tenant_id)
    return list(dict.fromkeys([resolved, *DEFAULT_INVENTORY_CONTROL_CODES]))


def _movement_quantities(tenant_id=None, product_ids=None, as_of=None):
    """Signed movement quantities for each product and warehouse."""
    from models import StockMovement

    query = db.session.query(
        StockMovement.product_id,
        StockMovement.warehouse_id,
        db.func.coalesce(db.func.sum(StockMovement.quantity), 0),
    ).group_by(StockMovement.product_id, StockMovement.warehouse_id)

    if tenant_id is not None:
        query = query.filter(StockMovement.tenant_id == tenant_id)
    if product_ids:
        query = query.filter(StockMovement.product_id.in_(list(product_ids)))
    if as_of is not None:
        query = query.filter(StockMovement.created_at <= as_of)

    return query.all()


def _document_weights(tenant_id=None):
    """خريطة توزيع: (نوع المرجع، معرّفه) → [(product_id, weight)].

    ``weight`` هو أساس تكلفة المنتج داخل المستند (الكمية × التكلفة)،
    ومجموع الأوزان يساوي مبلغ سطر المخزون في القيد.
    """
    from models import (
        Product,
        ProductReturnLine,
        PurchaseLine,
        Sale,
        SaleLine,
        StockMovement,
    )
    from models.maintenance import MaintenanceOrderItem, MaintenanceReturnLine

    weights = {}

    def scoped(query, *models):
        if tenant_id is not None:
            query = query.filter(*(model.tenant_id == tenant_id for model in models))
        return query

    sales = (
        scoped(
            db.session.query(
                Sale.id,
                SaleLine.product_id,
                db.func.coalesce(
                    db.func.sum(
                        db.func.coalesce(SaleLine.cost_price, 0) * SaleLine.quantity
                    ),
                    0,
                ),
            ).join(SaleLine, SaleLine.sale_id == Sale.id),
            Sale,
            SaleLine,
        )
        .group_by(Sale.id, SaleLine.product_id)
        .all()
    )
    for sale_id, product_id, weight in sales:
        weights.setdefault(("Sale", sale_id), []).append(
            (product_id, to_decimal(weight))
        )

    purchases = (
        scoped(
            db.session.query(
                PurchaseLine.purchase_id,
                PurchaseLine.product_id,
                db.func.coalesce(db.func.sum(PurchaseLine.line_total), 0),
            ),
            PurchaseLine,
        )
        .group_by(PurchaseLine.purchase_id, PurchaseLine.product_id)
        .all()
    )
    for purchase_id, product_id, weight in purchases:
        weights.setdefault(("Purchase", purchase_id), []).append(
            (product_id, to_decimal(weight))
        )

    product_costs = {
        pid: CostingService.current_unit_cost(product)
        for pid, product in scoped(db.session.query(Product.id, Product), Product).all()
    }
    returns = (
        scoped(
            db.session.query(
                ProductReturnLine.return_id,
                ProductReturnLine.product_id,
                db.func.coalesce(
                    db.func.sum(db.func.coalesce(ProductReturnLine.quantity, 0)), 0
                ),
            ),
            ProductReturnLine,
        )
        .group_by(ProductReturnLine.return_id, ProductReturnLine.product_id)
        .all()
    )
    return_costs = (
        scoped(
            db.session.query(
                ProductReturnLine.return_id,
                ProductReturnLine.product_id,
                db.func.coalesce(
                    db.func.sum(
                        db.func.coalesce(SaleLine.cost_price, 0)
                        * ProductReturnLine.quantity
                    ),
                    0,
                ),
            ).join(SaleLine, SaleLine.id == ProductReturnLine.sale_line_id),
            SaleLine,
            ProductReturnLine,
        )
        .group_by(ProductReturnLine.return_id, ProductReturnLine.product_id)
        .all()
    )
    cost_by_return = {(rid, pid): to_decimal(cost) for rid, pid, cost in return_costs}
    for return_id, product_id, qty in returns:
        cost = cost_by_return.get((return_id, product_id))
        if not cost:
            cost = product_costs.get(product_id, Decimal("0")) * to_decimal(qty)
        weights.setdefault(("ProductReturn", return_id), []).append(
            (product_id, to_decimal(cost))
        )

    movements = scoped(
        db.session.query(StockMovement.id, StockMovement.product_id), StockMovement
    ).all()
    for movement_id, product_id in movements:
        for source in ("OpeningStock", "stock_adjustment"):
            weights[(source, movement_id)] = [(product_id, Decimal("1"))]

    items = scoped(
        db.session.query(MaintenanceOrderItem.id, MaintenanceOrderItem.product_id),
        MaintenanceOrderItem,
    )
    for item_id, product_id in items:
        weights[("maintenance_item", item_id)] = [(product_id, Decimal("1"))]

    returns = scoped(
        db.session.query(
            MaintenanceReturnLine.return_id,
            MaintenanceOrderItem.product_id,
            MaintenanceReturnLine.quantity,
            MaintenanceOrderItem.cost_price,
        ).join(
            MaintenanceOrderItem,
            MaintenanceOrderItem.id == MaintenanceReturnLine.order_item_id,
        ),
        MaintenanceReturnLine,
        MaintenanceOrderItem,
    )
    for return_id, product_id, qty, cost in returns:
        weights.setdefault(("maintenance_return", return_id), []).append(
            (product_id, to_decimal(qty) * to_decimal(cost))
        )

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
        .filter(GLAccount.code.in_(codes), GLJournalEntry.is_posted.is_(True))
    )
    if tenant_id is not None:
        query = query.filter(
            GLJournalLine.tenant_id == tenant_id, GLJournalEntry.tenant_id == tenant_id
        )
    if as_of is not None:
        query = query.filter(GLJournalEntry.entry_date <= as_of)

    return query.all()


def _allocate(amount, allocation):
    """توزيع مبلغ على [(product_id, weight)] بالتناسب مع الأوزان."""
    total_weight = sum((w for _, w in allocation), Decimal("0"))
    if total_weight <= 0:
        return {}
    result = {}
    allocated = Decimal("0")
    items = list(allocation)
    for index, (product_id, weight) in enumerate(items):
        if index == len(items) - 1:
            share = amount - allocated
        else:
            share = amount * weight / total_weight
            allocated += share
        result[product_id] = result.get(product_id, Decimal("0")) + share
    return result


def reconcile_inventory(
    tenant_id=None, product_ids=None, as_of=None, include_inactive=True
):
    """مطابقة المخزون: الحركات مقابل العمود مقابل الأستاذ العام.

    Returns a dict::

        {
          'section': 'INVENTORY',
          'control_accounts': ['1140'],
          'control_balance': Decimal,        # رصيد المخزون في الأستاذ (أساسي)
          'total_quantity_from_movements': Decimal,
          'total_current_stock': Decimal,
          'total_valuation_at_cost_price': Decimal,   # = مجموع التقييم
          'total_valuation_at_average_cost': Decimal, # على المتوسط المتحرك
          'difference': Decimal,             # current_stock − movements
          'gl_difference': Decimal,          # control_balance − valuation
          'unattributed_gl_balance': Decimal,
          'balanced': bool,
          'products': [
              {'product_id', 'sku', 'name',
               'quantity_from_movements', 'current_stock', 'difference',
               'average_cost', 'cost_price',
               'valuation_at_average_cost', 'valuation_at_cost_price',
               'gl_control_balance', 'gl_difference'},
              ...
          ],
          'breaks': [ {...} ],
        }

    ``products`` carries one row per product; ``breaks`` lists the rows
    whose difference exceeds the tolerance (|delta| > 0.01).

    أساس التقييم هو **المتوسط المتحرك** (``average_cost``) — فالمقارنة
    مع حساب المخزون في الأستاذ تصبح مقارنة بين amounts بنفس الأساس.
    """
    from models import Product, Warehouse
    from models.tenant_scope import get_current_tenant_id

    if tenant_id is None:
        tenant_id = get_current_tenant_id()
    codes = inventory_control_codes(tenant_id)

    product_query = Product.query
    if tenant_id is not None:
        product_query = product_query.filter(Product.tenant_id == tenant_id)
    if product_ids:
        product_query = product_query.filter(Product.id.in_(list(product_ids)))
    if not include_inactive:
        product_query = product_query.filter(Product.is_active.is_(True))

    products = product_query.order_by(Product.id).all()

    movement_totals = {}
    warehouse_totals = {}
    negative_positions = []
    visible_products = {product.id: product for product in products}
    warehouse_query = Warehouse.query
    if tenant_id is not None:
        warehouse_query = warehouse_query.filter(Warehouse.tenant_id == tenant_id)
    warehouse_names = {warehouse.id: warehouse.name for warehouse in warehouse_query}
    for product_id, warehouse_id, quantity in _movement_quantities(
        tenant_id, product_ids, as_of
    ):
        product = visible_products.get(product_id)
        if product is None:
            continue
        qty = to_decimal(quantity)
        movement_totals[product_id] = (
            movement_totals.get(product_id, Decimal("0")) + qty
        )
        warehouse = warehouse_totals.setdefault(
            warehouse_id,
            {
                "warehouse_id": warehouse_id,
                "warehouse": warehouse_names.get(warehouse_id),
                "quantity": Decimal("0"),
                "valuation": Decimal("0"),
            },
        )
        warehouse["quantity"] += qty
        warehouse["valuation"] += qty * CostingService.current_unit_cost(product)
        if qty < 0:
            negative_positions.append(
                {
                    "product_id": product_id,
                    "sku": product.sku,
                    "warehouse_id": warehouse_id,
                    "warehouse": warehouse["warehouse"],
                    "quantity": _q3(qty),
                }
            )

    weights = _document_weights(tenant_id)
    gl_by_product = {}
    unattributed = Decimal("0")
    total_gl = Decimal("0")
    for _line_id, amount_base, reference_type, reference_id in _gl_inventory_lines(
        codes, tenant_id=tenant_id, as_of=as_of
    ):
        amount = to_decimal(amount_base)
        total_gl += amount
        allocation = weights.get((reference_type, reference_id))
        if not allocation or sum(weight for _, weight in allocation) <= 0:
            unattributed += amount
            continue
        for product_id, share in _allocate(amount, allocation).items():
            gl_by_product[product_id] = (
                gl_by_product.get(product_id, Decimal("0")) + share
            )

    rows = []
    breaks = []
    total_qty = Decimal("0")
    total_stock = Decimal("0")
    total_valuation = Decimal("0")
    total_valuation_cost_price = Decimal("0")

    for product in products:
        qty = movement_totals.get(product.id, Decimal("0"))
        stock = to_decimal(product.current_stock)
        difference = stock - qty
        cost = CostingService.current_unit_cost(product)
        valuation = qty * cost
        # cost_price is the VAT-inclusive purchase price and is a genuinely
        # different basis from the net moving average — never copy one into the
        # other or the report silently lies about the cost-price valuation.
        cost_price = to_decimal(getattr(product, "cost_price", 0) or 0)
        valuation_cost_price = _valuation(qty, cost_price)
        gl_amount = _q3(gl_by_product.get(product.id, Decimal("0")))
        gl_difference = _q3(gl_amount - valuation)

        total_qty += qty
        total_stock += stock
        total_valuation += valuation
        total_valuation_cost_price += valuation_cost_price

        row = {
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
            "quantity_from_movements": _q3(qty),
            "current_stock": _q3(stock),
            "difference": _q3(difference),
            "average_cost": _q6(cost),
            "cost_price": _q2(to_decimal(product.cost_price)),
            "valuation_at_average_cost": _q2(valuation),
            "valuation_at_cost_price": _q2(valuation_cost_price),
            "gl_control_balance": _q2(gl_amount),
            "gl_difference": _q2(gl_difference),
        }
        rows.append(row)

        if difference or abs(gl_difference) > TOLERANCE:
            breaks.append(
                {
                    "product_id": product.id,
                    "sku": product.sku,
                    "name": product.name,
                    "quantity_difference": _q3(difference),
                    "gl_difference": _q2(gl_difference),
                }
            )
            logger.warning(
                "Inventory break: product#%s (%s) movement-vs-stock=%s "
                "gl-vs-valuation=%s",
                product.id,
                product.sku,
                _q2(difference),
                _q2(gl_difference),
            )

    total_difference = total_stock - total_qty
    control_balance = _q2(total_gl)
    gl_difference = control_balance - _q2(total_valuation)

    return {
        "section": "INVENTORY",
        "control_accounts": codes,
        "control_balance": _q2(control_balance),
        "total_quantity_from_movements": _q3(total_qty),
        "total_current_stock": _q3(total_stock),
        "total_valuation_at_average_cost": _q2(total_valuation),
        "total_valuation_at_cost_price": _q2(total_valuation_cost_price),
        "difference": _q3(total_difference),
        "gl_difference": _q2(gl_difference),
        "unattributed_gl_balance": _q2(unattributed),
        "warehouses": [
            {
                **row,
                "quantity": _q3(row["quantity"]),
                "valuation": _q2(row["valuation"]),
            }
            for row in sorted(
                warehouse_totals.values(), key=lambda row: row["warehouse_id"]
            )
        ],
        "negative_warehouse_positions": negative_positions,
        # Per-product GL amounts are an approximate allocation: GL lines that
        # cannot be attributed to a specific document (opening stock, FX and
        # restatement entries) are reported in `unattributed_gl_balance`, so a
        # per-product break does NOT imply a real imbalance. The authoritative
        # check is the control account total vs the total valuation.
        "balanced": (
            not negative_positions
            and all(row["difference"] == 0 for row in rows)
            and abs(gl_difference) <= TOLERANCE
        ),
        "products": rows,
        "breaks": breaks,
    }


class InventoryReconciliation:
    """واجهة صفّية مطابقة services/subledger_reconciliation.py."""

    @staticmethod
    def reconcile_inventory(
        tenant_id=None, product_ids=None, as_of=None, include_inactive=True
    ):
        return reconcile_inventory(
            tenant_id=tenant_id,
            product_ids=product_ids,
            as_of=as_of,
            include_inactive=include_inactive,
        )
