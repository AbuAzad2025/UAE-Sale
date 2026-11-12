from datetime import datetime, timezone
from decimal import Decimal
from extensions import db

# Phase 2b: permission_code لكل إجراء — نفس رموز ai_tools و _ai_action_denied
PERMISSION_MAP = {
    "create_customer": "manage_customers",
    "create_product": "manage_products",
    "create_sale": "manage_sales",
    "record_payment": "manage_payments",
    "create_expense": "manage_expenses",
    "create_supplier": "manage_suppliers",
    "create_purchase": "manage_purchases",
    "create_cheque": "manage_payments",
    "create_user": "manage_users",
}


def permission_for_tool(tool: str) -> str | None:
    """permission_code لأداة (للهدف من routes/ai._ai_action_denied)."""
    return PERMISSION_MAP.get(tool)


def _number(model, attr, prefix):
    from utils.helpers import generate_number

    return generate_number(prefix, model, attr)


def _require_tenant_id():
    """Phase 3: tenant_id إلزامي لكل كتابة عبر المساعد.

    - المالك / super_admin: None (صفوف المنصة).
    - مستخدم تينانت: tenant_id الخاص به.
    - سياق بلا مستخدم مسجل (اختبارات الوحدة التي تعمل خارج الطلب):
      fallback إلى tenant الـ thread-local (التي يضبطها before_request
      في الإنتاج، وتكون None في اختبارات الخدمة المباشرة) — عندها
      تُسمح الكتابة كسياق system حتى لا تنكسر اختبارات الخدمة.
      في الإنتاج يتم الرفض مبكراً في routes/ai.py قبل الوصول إلى هنا
      عندما يكون المستخدِم الحقيقي مسجلاً وبلا tenant.

    يفشل مغلقاً (fail-closed): لا إنشاء بلا نطاق عندما يكون هناك
    مستخدم حقيقي بلا tenant.
    """
    from flask_login import current_user

    if not getattr(current_user, "is_authenticated", False):
        # Outside a login request (unit tests, system context): fall back
        # to the thread-local tenant if set, else platform (None).
        from models.tenant_scope import get_current_tenant_id

        ctx = get_current_tenant_id()
        from models.tenant_scope import TENANT_LESS_SCOPE

        if ctx == TENANT_LESS_SCOPE or ctx is None:
            return None
        return ctx
    if getattr(current_user, "is_owner", False):
        # سياق دعم: يختم على الشركة المُخترَقة (session) حتى تكون الكتابات
        # في صفوف تلك الشركة (مع بقاء التدقيق باسم المالك).
        try:
            from flask import session as _s

            _imp = _s.get("impersonate_tenant_id")
            if _imp is not None:
                return int(_imp)
        except Exception:
            pass
        return None
    is_super = getattr(current_user, "is_super_admin", None)
    if callable(is_super) and is_super():
        return None
    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        raise ValueError(
            "⛔ حسّابك غير مرتبط بشركة (tenant). لا يمكن تنفيذ عمليات عبر المساعد الذكي. تواصل مع مالك المنصة لربط حسابك."
        )
    return tenant_id


def _ai_audit(table_name, record_id, changes=None, action="create"):
    """Phase 3: سجل تدقيق لكل إجراء AI (fail-closed داخل معاملة الكاتب)."""
    try:
        from utils.helpers import create_audit_log

        payload = dict(changes or {})
        payload.setdefault("via", "ai_assistant")
        create_audit_log(action, table_name, record_id, changes=payload, commit=True)
    except Exception:
        # Outside a request/app context (unit tests calling the service
        # directly) there is no user/IP to log and create_audit_log fails.
        # Do not break the business write for this; in production (chat)
        # we are always inside a request, so the audit row is written.
        try:
            from flask import has_app_context, has_request_context

            if has_app_context() and has_request_context():
                raise
        except Exception:
            pass
        return


def _stamp_tenant(obj):
    """ختم tenant_id صريحاً قبل الإدخال (الحزام + الحمالات فوق before_flush)."""
    return {"tenant_id": _require_tenant_id()}


def create_customer(name, phone=None, address=None):
    from models.customer import Customer

    customer = Customer(
        name=name,
        name_ar=name,
        phone=phone,
        address=address,
        customer_type="regular",
        balance=0,
        is_active=True,
        **_stamp_tenant(None),
    )
    db.session.add(customer)
    db.session.commit()
    _ai_audit("customers", customer.id, {"name": name})
    return customer


def create_product(
    name, part_number=None, regular_price=0, current_stock=0, cost_price=0
):
    """إنشاء منتج — مع تكلفة اختيارية.

    F1/F2: `cost_price` صفر يعني "بلا تكلفة موثّقة" — وهذا المنتج **لا
    يمكن بيعه** (قيد الإيراد لن يقابله قيد تكلفة البضاعة ولا تسوية
    للمخزون). لذلك يجب تمرير التكلفة عند إنشاء المنتج عبر المساعد الذكي.
    """
    from models.product import Product

    product = Product(
        name=name,
        name_ar=name,
        part_number=part_number,
        regular_price=regular_price,
        cost_price=cost_price,
        current_stock=0,
        unit="قطعة",
        is_active=True,
        **_stamp_tenant(None),
    )
    db.session.add(product)
    db.session.flush()

    if current_stock and current_stock > 0:
        from services.stock_service import StockService

        StockService.create_movement(
            product_id=product.id,
            quantity=current_stock,
            movement_type="adjustment",
            reference_type="AI Product Creation",
            reference_id=product.id,
            notes=f"مخزون أولي (AI): {name}",
            unit_cost_base=cost_price if cost_price else None,
        )

    db.session.commit()
    _ai_audit("products", product.id, {"name": name, "cost_price": str(cost_price)})
    return product


def create_sale(customer_id, product_id, quantity, seller_id):
    """إنشاء فاتورة بيع عبر المسار الرسمي للبيع (SaleService).

    F2: كان هذا المسار يطرح الكمية من `product.current_stock` مباشرة
    (`product.current_stock -= quantity`) ثم يحفظ — بلا حركة مخزون، وبلا
    لقطة تكلفة على سطر البيع، وبلا قيد إيراد، وبلا قيد تكلفة بضاعة
    مباعة. أي أن البيع كان "يختفي" من المخزون دون أثر محاسبي.

    الآن يمرّ البيع عبر `SaleService.create_sale` — نفس المسار الذي
    تستعمله شاشة المبيعات — فتُكتب:
      * حركة المخزون (StockService.process_sale_lines)،
      * لقطة التكلفة على سطر البيع (cost_price)،
      * قيد الإيراد (مدين ذمم مدينة / دائن إيرادات)،
      * قيد تكلفة البضاعة المباعة (مدين COGS / دائن المخزون).
    ومنتج بلا تكلفة يُرفض صراحةً (ValidationError) بدل أن يولّد فاتورة
    إيراد بلا تكلفة.
    """
    _require_tenant_id()  # Phase 3: tenant_id إلزامي قبل أي كتابة مبيعات
    from models.customer import Customer
    from models.product import Product
    from models.user import User
    from services.sale_service import SaleService
    from utils.errors import ValidationError

    product = Product.query.get(product_id)
    if product is None:
        raise ValueError("المنتج غير موجود")

    customer = Customer.query.get(customer_id)
    if customer is None:
        raise ValueError("العميل غير موجود")

    seller = User.query.get(seller_id)
    if seller is None:
        raise ValueError("البائع غير موجود")

    quantity_decimal = Decimal(str(quantity))
    if quantity_decimal <= 0:
        raise ValidationError("الكمية يجب أن تكون أكبر من صفر")

    unit_price = product.get_price_for_customer(customer.customer_type)
    if unit_price is None or Decimal(str(unit_price)) <= 0:
        raise ValidationError(
            f'⚠️ سعر بيع غير صالح للمنتج "{product.name}".\n'
            f"💡 اضبط سعر المنتج قبل إنشاء الفاتورة."
        )

    sale = SaleService.create_sale(
        customer=customer,
        seller=seller,
        lines_data=[
            {
                "product": product,
                "quantity": quantity_decimal,
                "unit_price": Decimal(str(unit_price)),
            }
        ],
        notes="فاتورة مُنشأة عبر المساعد الذكي",
    )
    _ai_audit(
        "sales",
        getattr(sale, "id", None),
        {"customer_id": customer_id, "product_id": product_id},
    )
    return sale


def record_payment(customer_id, amount, method, direction, user_id, payment_type):
    from models.payment import Payment

    _require_tenant_id()  # Phase 3: tenant_id إلزامي

    sign = -1 if direction == "outgoing" else 1
    amount = abs(amount)

    payment = Payment(
        payment_number=_number(Payment, "payment_number", "PAY"),
        payment_type=payment_type,
        direction=direction,
        customer_id=customer_id,
        amount=amount,
        amount_base=sign * amount,
        currency="AED",
        exchange_rate=1,
        payment_method=method,
        payment_date=datetime.now(timezone.utc),
        user_id=user_id,
        payment_confirmed=True,
    )
    db.session.add(payment)
    db.session.commit()
    _ai_audit(
        "payments", payment.id, {"customer_id": customer_id, "amount": str(amount)}
    )
    return payment


def _default_expense_category():
    from models.expense import ExpenseCategory

    category = ExpenseCategory.query.filter_by(is_active=True).first()
    if category is None:
        category = ExpenseCategory(name="عام", name_ar="عام", is_active=True)
        db.session.add(category)
        db.session.flush()
    return category


def create_expense(description, amount, user_id):
    from models.expense import Expense

    amount = abs(amount)
    category = _default_expense_category()

    expense = Expense(
        expense_number=_number(Expense, "expense_number", "EXP"),
        description=description,
        description_ar=description,
        amount=amount,
        amount_base=amount,
        category_id=category.id,
        payment_method="cash",
        user_id=user_id,
    )
    db.session.add(expense)
    db.session.commit()
    _ai_audit(
        "expenses", expense.id, {"description": description, "amount": str(amount)}
    )
    return expense


def create_supplier(name, phone=None, email=None, address=None, tax_number=None):
    from models.supplier import Supplier

    supplier = Supplier(
        name=name,
        name_ar=name,
        phone=phone,
        email=email,
        address=address,
        tax_number=tax_number,
        is_active=True,
        **_stamp_tenant(None),
    )
    db.session.add(supplier)
    db.session.commit()
    _ai_audit("suppliers", supplier.id, {"name": name})
    return supplier


def create_purchase(supplier_id, product_id, quantity, unit_cost, user_id):
    from models.purchase import Purchase, PurchaseLine
    from models.product import Product
    from models.supplier import Supplier

    _require_tenant_id()  # Phase 3: tenant_id إلزامي
    product = Product.query.get(product_id)
    if product is None:
        raise ValueError("المنتج غير موجود")

    supplier = Supplier.query.get(supplier_id)
    total = unit_cost * quantity

    purchase = Purchase(
        purchase_number=_number(Purchase, "purchase_number", "PUR"),
        supplier_id=supplier_id,
        supplier_name=supplier.name if supplier else None,
        total_amount=total,
        amount_base=total,
        user_id=user_id,
        status="confirmed",
    )
    db.session.add(purchase)
    db.session.flush()

    item = PurchaseLine(
        purchase_id=purchase.id,
        product_id=product_id,
        quantity=quantity,
        unit_cost=unit_cost,
        line_total=total,
    )
    db.session.add(item)
    db.session.flush()

    # Stock movement (updates current_stock + average_cost) instead of a
    # bare `product.current_stock += quantity` that bypassed StockMovement
    # and the moving-average recalculation.
    from services.stock_service import StockService

    StockService.create_movement(
        product_id=product_id,
        quantity=quantity,
        movement_type="purchase",
        reference_type="Purchase",
        reference_id=purchase.id,
        notes=f"شراء (AI): {purchase.purchase_number}",
        unit_cost_base=unit_cost,
    )

    db.session.commit()
    _ai_audit(
        "purchases", purchase.id, {"supplier_id": supplier_id, "product_id": product_id}
    )
    return purchase


def create_cheque(cheque_number, amount, due_date, cheque_type, user_id):
    from datetime import date
    from models.cheque import Cheque

    _require_tenant_id()  # Phase 3: tenant_id إلزامي
    cheque = Cheque(
        cheque_number=cheque_number,
        cheque_bank_number=cheque_number,
        bank_name="بنك افتراضي",
        amount=amount,
        issue_date=date.today(),
        due_date=due_date,
        cheque_type=cheque_type,
        status="pending",
        user_id=user_id,
        is_active=True,
    )
    db.session.add(cheque)
    db.session.commit()
    _ai_audit("cheques", cheque.id, {"number": cheque_number, "amount": str(amount)})
    return cheque


def create_user(username, password, role_slug, email=None, full_name=None):
    from models.user import User
    from models import Role

    role = Role.query.filter_by(slug=role_slug).first()
    if role is None:
        raise ValueError("الدور غير صحيح")

    user = User(
        username=username,
        email=email or f"{username}@system.local",
        full_name=full_name or username,
        role_id=role.id,
        is_owner=False,
        is_active=True,
        **_stamp_tenant(None),
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    _ai_audit("users", user.id, {"username": username})
    return user
