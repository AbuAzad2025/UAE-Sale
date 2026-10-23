"""
Inventory Costing — متوسط التكلفة المتحرك للمخزون (Moving Weighted Average)
=========================================================================

لماذا هذا الملف موجود
----------------------
كان المخزون يُقيَّم بـ ``products.cost_price`` وهو **سعر آخر شراء**، بينما
حساب مراقبة المخزون في الأستاذ العام يحمل **المبلغ المدفوع فعلياً** (صافي
خصم المستند). الفجوة بينهما مبنية في التصميم: منتج اشتُري بسعر 10 ثم مرة
أخرى بسعر 12 كان يُقيَّم بالكامل بسعر 12، بينما الأستاذ يحمل 10 للوحدات
الأصلية — فلا يلتقي تقرير التقييم مع الميزانية أبداً.

هنا التقييم قائم على **متوسط تكلفة متحرك** مرحَّل:

    new_avg = (old_qty * old_avg + in_qty * in_unit_cost) / (old_qty + in_qty)

* المخزون يُقيَّم بـ ``current_stock * average_cost`` (بالعملة الأساسية).
* تكلفة البضاعة المباعة **تُثبَّت لحظة البيع** — التكلفة حينها لا التكلفة
  بعدها.
* ``cost_price`` يبقى **سعر التكلفة المرجعي** (آخر شراء) — مرجع للعرض
  والرقابة، لا أساس تقييم.

هذا الملف هو المصدر الوحيد للتكلفة: كل حركة داخلية تمرّ عبر
:meth:`CostingService.apply_inbound`، وكل بيع يلتقط التكلفة عبر
:meth:`CostingService.cost_for_sale`.

اصطلاحات
---------
* كل المبالغ ``Decimal`` — لا حسابات بمؤشرات عائمة إطلاقاً.
* دقة المبالغ ``Numeric(15,3)`` — تقريب ``ROUND_HALF_UP`` إلى ثلاث منازل
  (نفس ``MONEY_Q`` في models/customer.py وservices/payment_service.py).
"""

from decimal import Decimal, ROUND_HALF_UP

#: دقة المبالغ — دقة أعمدة ``Numeric(15, 3)`` في المستودع كله.
MONEY_QUANTUM = Decimal('0.001')


def _dec(value, default=Decimal('0')):
    """تحويل أي قيمة حدودية إلى ``Decimal`` (لا تنهار على بيانات قذرة)."""
    if value is None or value == '':
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip().replace(',', ''))
    except Exception:
        return default


def _q3(value):
    """تقريب مبلغ إلى ثلاث منازل (دقة أعمدة Numeric(15,3))."""
    return _dec(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


class CostingService:
    """تكلفة المخزون المتحركة — المصدر الوحيد للتكلفة في النظام."""

    # =================================================================
    # المتوسط المتحرك
    # =================================================================

    @staticmethod
    def moving_average(old_qty, old_avg, in_qty, in_unit_cost) -> Decimal:
        """المتوسط المتحرك الجديد بعد حركة داخلية.

            new_avg = (old_qty * old_avg + in_qty * in_unit_cost)
                      / (old_qty + in_qty)

        Args:
            old_qty: الكمية القائمة **قبل** الحركة.
            old_avg: المتوسط الحالي (بالعملة الأساسية).
            in_qty: كمية الحركة الداخلية (موجبة).
            in_unit_cost: تكلفة الوحدة الواردة **صافي خصم المستند**
                وبالعملة الأساسية.

        Returns:
            Decimal: المتوسط الجديد مقرّباً إلى ثلاث منازل.

        حراسات:
            * ``in_qty <= 0`` ⇒ المتوسّط يعود كما هو (الحركة الخارجة
              أو الصفرية لا تحرّك المتوسط).
            * ``old_qty + in_qty == 0`` ⇒ لا قسمة على صفر: يعود
              المتوسّط القديم.
        """
        old_qty = _dec(old_qty)
        old_avg = _dec(old_avg)
        in_qty = _dec(in_qty)
        in_unit_cost = _dec(in_unit_cost)

        if in_qty <= 0:
            return _q3(old_avg)

        if old_qty < 0:
            old_qty = Decimal('0')

        total_qty = old_qty + in_qty
        if total_qty <= 0:
            return _q3(old_avg)

        total_value = (old_qty * old_avg) + (in_qty * in_unit_cost)
        return _q3(total_value / total_qty)

    # =================================================================
    # الحركات الداخلية
    # =================================================================

    @staticmethod
    def apply_inbound(product, qty, unit_cost_base) -> Decimal:
        """يطبّق حركة داخلية على متوسط التكلفة المتحرك للمنتج.

        **عقد الاستدعاء (مهم):** الدالة تقرأ الكمية من
        ``product.current_stock`` كما هي **قبل** الحركة، أي أن المستدعي
        **يجب** أن يستدعيها **قبل** زيادة ``product.current_stock``.
        (تستدعيها ``StockService.create_movement`` قبل تعديل الرصيد
        مباشرةً، فالعقد مضمون في موضع واحد.)

        Args:
            product: كائن ``Product``.
            qty: الكمية الداخلة (موجبة).
            unit_cost_base: تكلفة الوحدة الواردة صافي خصم المستند
                وبالعملة الأساسية.

        Returns:
            Decimal: المتوسط الجديد بعد الحركة.
        """
        if product is None:
            return Decimal('0.000')

        qty = _dec(qty)
        old_avg = _dec(getattr(product, 'average_cost', 0))

        if qty <= 0:
            return _q3(old_avg)

        new_avg = CostingService.moving_average(
            _dec(getattr(product, 'current_stock', 0)),
            old_avg,
            qty,
            _dec(unit_cost_base),
        )
        product.average_cost = new_avg
        return new_avg

    @staticmethod
    def current_unit_cost(product) -> Decimal:
        """تكلفة الوحدة المعروفة حالياً: المتوسط المتحرك، أو سعر آخر شراء.

        تُستعمل للحركة الداخلية التي لا تحمل تكلفة معروفة (تسوية يدوية،
        إرجاع من مستودع، استلام شحنة): فإذا حُمّلت الواردات بتكلفة الوحدة
        نفسها فلا يتغيّر المتوسط.
        """
        if product is None:
            return Decimal('0.000')
        average = _dec(getattr(product, 'average_cost', 0))
        if average > 0:
            return _q3(average)
        reference = _dec(getattr(product, 'cost_price', 0))
        return _q3(reference) if reference > 0 else Decimal('0.000')

    # =================================================================
    # البيع
    # =================================================================

    @staticmethod
    def cost_for_sale(product, qty=1) -> Decimal:
        """تكلفة الوحدة وقت البيع — لقطة الكلفة المعبّأة على سطر البيع.

        الأساس هو **المتوسط المتحرك** لا سعر آخر شراء: بيعٌ بسعر 10 ثم
        شراءٌ بسعر 12 ثم بيعٌ ثانٍ يلتقط المتوسط (لا 12 ولا 10).

        الفحص مغلق (fail-closed): منتج بلا أساس تكلفة (لا متوسط ولا سعر
        مرجعي) يُرفض بالخطأ نفسه الموروث من
        ``StockService.require_cost_basis`` — بيعٌ بلا تكلفة يضخّم الربح،
        وهو بالضبط ما كشفه التدقيق.

        Args:
            product: كائن ``Product``.
            qty: الكمية المطلوبة (تُمرَّر إلى حارس التكلفة).

        Returns:
            Decimal: تكلفة الوحدة بالعملة الأساسية.

        Raises:
            ValidationError: إذا لم يكن للمنتج أساس تكلفة موثوق.
        """
        from services.stock_service import StockService

        average = _dec(getattr(product, 'average_cost', 0))
        if average > 0:
            return _q3(average)

        # لا متوسط مُثبَت (منتج بلا حركات داخلية ولا بذر أولي): يُستعمل
        # الحارس الموروث — يرفض العملية إن لم يكن هناك أي تكلفة، وإلا
        # يعيد آخر سعر شراء كمرجع.
        return _q3(StockService.require_cost_basis(product, qty))

    # =================================================================
    # التقييم
    # =================================================================

    @staticmethod
    def stock_value(product) -> Decimal:
        """قيمة المخزون الدفترية للمنتج = الكمية × المتوسط المتحرك."""
        if product is None:
            return Decimal('0.000')
        quantity = _dec(getattr(product, 'current_stock', 0))
        average = _dec(getattr(product, 'average_cost', 0))
        return _q3(quantity * average)

    @staticmethod
    def net_unit_cost(line, purchase) -> Decimal:
        """تكلفة الوحدة الصافية لسطر الشراء — net of the document discount.

        خصم الشراء على مستوى المستند (``purchase.discount_amount``)، فَيُوزَّع
        على الأسطر بالتناسب مع قيمة كل سطر (``line_total``) — وإلا حمل
        سطر واحد كل الخصم أو حُمِل الخصم مرتين. المجموع بعد التوزيع يساوي
        خصم المستند بالضبط.

        ``line_total`` يشمل خصم السطر (``discount_percent``) إن وُجد، فالنتيجة
        هي **المبلغ المدفوع فعلياً** مقسوماً على الكمية، محوَّلاً إلى
        العملة الأساسية بسعر صرف الفاتورة — وهو نفس المبلغ الذي يُرحَّل
        مديناً على حساب المخزون (1140).

        Args:
            line: سطر الشراء (``PurchaseLine``).
            purchase: فاتورة الشراء (``Purchase``).

        Returns:
            Decimal: تكلفة الوحدة الصافية بالعملة الأساسية.
        """
        qty = _dec(getattr(line, 'quantity', 0))
        if qty <= 0:
            return Decimal('0.000')

        line_total = getattr(line, 'line_total', None)
        if line_total is None:
            unit_cost = _dec(getattr(line, 'unit_cost', 0))
            discount_percent = _dec(getattr(line, 'discount_percent', 0))
            multiplier = (Decimal('100') - discount_percent) / Decimal('100')
            line_total = qty * unit_cost * multiplier
        line_total = _dec(line_total)

        subtotal = _dec(getattr(purchase, 'subtotal', 0))
        document_discount = _dec(getattr(purchase, 'discount_amount', 0))

        allocated_discount = Decimal('0')
        if document_discount > 0 and subtotal > 0:
            allocated_discount = document_discount * line_total / subtotal

        net_line_amount = line_total - allocated_discount

        exchange_rate = _dec(getattr(purchase, 'exchange_rate', 1) or 1)
        if exchange_rate <= 0:
            exchange_rate = Decimal('1')

        return _q3((net_line_amount * exchange_rate) / qty)

    @staticmethod
    def valuation_rows(tenant_id=None):
        """سطور تقييم المخزون — سطر لكل منتج.

        Args:
            tenant_id: نطاق المستأجر (اختياري؛ بلا него يُطبَّق النطاق
                التلقائي لـ ``TenantScopedMixin``).

        Returns:
            list[dict]: ``{product_id, sku, name, quantity, average_cost,
            value}`` — كل المبالغ ``Decimal`` مقرّبة إلى ثلاث منازل.
        """
        from models import Product

        query = Product.query
        if tenant_id is not None:
            query = query.filter(Product.tenant_id == tenant_id)

        rows = []
        for product in query.order_by(Product.id).all():
            quantity = _q3(getattr(product, 'current_stock', 0))
            average = _q3(getattr(product, 'average_cost', 0))
            rows.append({
                'product_id': product.id,
                'sku': product.sku,
                'name': product.name,
                'quantity': quantity,
                'average_cost': average,
                'value': _q3(quantity * average),
            })
        return rows
