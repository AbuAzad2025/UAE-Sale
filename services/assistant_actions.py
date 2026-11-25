"""Interpret, validate, authorize and audit the ERP operations offered in chat."""

import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from flask import current_app, url_for
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import AssistantAction, Customer, Product, Sale
from models.tenant_scope import TENANT_LESS_SCOPE, get_current_tenant_id
from services.ai_normalize import normalize
from utils.helpers import create_audit_log

PROPOSAL_TTL = timedelta(minutes=15)

_CREATE_CUSTOMER = re.compile(
    r"^(?:(?:أضف|اضف|أنشئ|انشئ|إضافة|اضافة|إنشاء|انشاء|سج[ّ]?ل)\s+"
    r"(?:عميلا|عميلًا|عميل|زبون)(?:\s+جديد)?(?:\s*[:：]\s*|\s+|$)"
    r"|(?:عميل|زبون)(?:\s+جديد)?\s*[:：]\s*)"
)
_BALANCE = re.compile(
    r"^(?:(?:كم|ما|شو|قديش|ما هو|اعرض|عرض)\s+)?رصيد(?:\s*[:：]\s*|\s+)(.+)$"
)
_CUSTOMER_ID = re.compile(r"^#?([0-9٠-٩]{1,9})$")
_STOCK = re.compile(
    r"^(?:(?:تحقق من|اعرض|كم)\s+)?مخزون\s+(?:الصنف|المنتج|SKU)\s*[:：]?\s+(.+)$",
    re.IGNORECASE,
)
_INVOICE = re.compile(
    r"^(?:(?:اعرض|ما|شو)\s+)?حالة\s+(?:فاتورة|فاتوره|الفاتورة)\s*[:：]?\s+(.+)$"
)
_DOCUMENT_NUMBER = re.compile(r"^[\w./-]{1,50}$")


_WRITE_PREFIX = re.compile(
    r"^(?:اضف|اضافه|انشي|انشاء|سجل|احذف|عدل|تعديل|الغ|ارحل|صرف|استلم|create|add|post|delete|update)\b"
)
_QUOTE = re.compile(
    r"^(?:(?:أنشئ|انشئ|أضف|اضف|جهز)\s+)?(?:مسودة\s+)?"
    r"عرض\s+(?:سعر|أسعار|اسعار)\s*[:：]\s*"
)
_WRITE_PERMISSIONS = {
    "create_customer": "manage_customers",
    "create_draft_quote": "manage_sales",
    "import_stock": "manage_products",
    "stock_transfer": "manage_warehouse",
    "create_purchase_order": "manage_purchases",
}


_FORMAL_ROUTES = {
    "balance": "customers.index",
    "cheque": "cheques.create",
    "customer": "customers.create",
    "expense": "expenses.create",
    "give": "payments.create_voucher",
    "product": "products.create",
    "purchase": "purchases.create",
    "create_draft_quote": "erp_modules.create_quotation",
    "receive": "payments.create_voucher",
    "sale": "sales.create",
    "supplier": "suppliers.create",
}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _scope(user):
    tenant = get_current_tenant_id()
    if tenant == TENANT_LESS_SCOPE:
        return None
    if tenant is not None:
        return tenant
    return None if user.is_owner else user.tenant_id


def available_warehouses(user):
    from models import Warehouse

    if not user.has_permission(_WRITE_PERMISSIONS["import_stock"]):
        return []
    return Warehouse.query.filter_by(tenant_id=_scope(user), is_active=True).order_by(
        Warehouse.is_main.desc(), Warehouse.name
    ).all()


def _scoped(model, user):
    scope = _scope(user)
    query = model.query
    if scope is not None or not user.is_owner:
        query = query.filter(model.tenant_id == scope)
    return query


def _audit(user, message, tool, outcome, *, confidence=1.0, entities=None, action_id=None):
    if message and re.search(r"\b(?:كلمه المرور|password|passcode)\b", normalize(message)):
        message = "[نص محجوب لاحتوائه على بيانات دخول]"
    return create_audit_log(
        "assistant_action",
        "assistant_actions",
        changes={
            "message": message,
            "intent": tool,
            "confidence": confidence,
            "matched_entities": entities or {},
            "action_id": action_id,
            "actor_id": user.id,
            "outcome": outcome,
        },
        commit=False,
    )


def _checked_result(user, message, tool, outcome, response, **details):
    _audit(user, message, tool, outcome, **details)
    db.session.commit()
    return {"response": response}


def audit_grounded_read(message, user, tool, response):
    outcome = "denied" if response.startswith("⛔") else "grounded_response"
    _audit(user, message, tool, outcome)
    db.session.commit()


def _balance(message, identity, user, *, confidence=1.0):
    from services.currency_service import CurrencyService

    tool = "get_customer_balance"
    if not user.has_permission("manage_customers"):
        return _checked_result(user, message, tool, "denied", "⛔ تحتاج إلى صلاحية إدارة العملاء.", confidence=confidence)
    identity = identity.strip(" ؟?")
    identity = re.sub(r"^(?:العميل|عميل|الزبون|زبون)\s*[:：]?\s+", "", identity)
    match = _CUSTOMER_ID.fullmatch(identity)
    scope = _scope(user)
    query = _scoped(Customer, user).filter(Customer.is_active.is_(True))
    if match:
        query = query.filter(Customer.id == int(match[1]))
    else:
        query = query.filter(func.lower(Customer.name) == identity.lower())
    candidates = query.order_by(Customer.id).limit(11).all()
    matched = {"customer_ids": [customer.id for customer in candidates]}
    if len(candidates) > 10:
        response = "هناك أكثر من 10 عملاء مطابقين. اكتب «رصيد #رقم العميل»."
        outcome = "ambiguous"
    elif len(candidates) > 1:
        choices = "\n".join(
            f"• {customer.name} — رصيد #{customer.id}" for customer in candidates
        )
        response = f"يوجد أكثر من عميل بهذا الاسم. اختر رقم العميل:\n{choices}"
        outcome = "ambiguous"
    elif not candidates:
        response = "لم أجد عميلًا نشطًا بهذا الاسم أو الرقم."
        outcome = "not_found"
    else:
        customer = candidates[0]
        if user.is_owner and scope is None and customer.tenant_id is not None:
            response = "اختر شركة العميل في النظام أولًا لعرض الرصيد بعملة الشركة."
            outcome = "scope_required"
        else:
            currency = CurrencyService.get_base_currency()
            response = f"رصيد {customer.name}: {customer.balance:,.2f} {currency}"
            outcome = "read"
    return _checked_result(user, message, tool, outcome, response, entities=matched, confidence=confidence)


def _product_stock(message, identity, user, *, confidence=1.0):
    tool = "check_stock"
    if not any(user.has_permission(permission) for permission in ("view_products", "manage_products", "view_reports")):
        return _checked_result(user, message, tool, "denied", "⛔ تحتاج إلى صلاحية عرض المنتجات.", confidence=confidence)

    identity = identity.strip(" ؟?")
    query = _scoped(Product, user).filter(Product.is_active.is_(True))
    match = _CUSTOMER_ID.fullmatch(identity)
    if match and identity.startswith("#"):
        query = query.filter(Product.id == int(match[1]))
    else:
        query = query.filter(
            or_(
                func.lower(Product.sku) == identity.lower(),
                func.lower(Product.part_number) == identity.lower(),
                func.lower(Product.name) == identity.lower(),
            )
        )
    products = query.order_by(Product.id).limit(10).all()
    matched = {"product_ids": [product.id for product in products]}
    if len(products) > 1:
        choices = "\n".join(
            f"• {product.name} — مخزون الصنف #{product.id}" for product in products
        )
        response = f"يوجد أكثر من صنف مطابق. اختر رقم الصنف:\n{choices}"
        outcome = "ambiguous"
    elif not products:
        response = "لم أجد صنفًا نشطًا بالاسم أو الرمز المحدد."
        outcome = "not_found"
    else:
        product = products[0]
        response = f"مخزون {product.name} عبر المستودعات: {product.current_stock:g}"
        outcome = "read"
    return _checked_result(user, message, tool, outcome, response, entities=matched, confidence=confidence)


def _invoice_status(message, reference, user, *, confidence=1.0):
    tool = "get_invoice_status"
    if not any(user.has_permission(permission) for permission in ("manage_sales", "view_reports")):
        return _checked_result(user, message, tool, "denied", "⛔ تحتاج إلى صلاحية عرض المبيعات.", confidence=confidence)

    reference = reference.strip(" ؟?")
    match = _CUSTOMER_ID.fullmatch(reference)
    query = _scoped(Sale, user)
    if match and reference.startswith("#"):
        query = query.filter(Sale.id == int(match[1]))
    elif _DOCUMENT_NUMBER.fullmatch(reference):
        query = query.filter(func.lower(Sale.sale_number) == reference.lower())
    else:
        return _checked_result(user, message, tool, "invalid", "اكتب «حالة فاتورة» متبوعة برقم الفاتورة.", confidence=confidence)

    invoices = query.limit(2).all()
    if not invoices:
        return _checked_result(user, message, tool, "not_found", "لم أجد فاتورة بهذا الرقم.", confidence=confidence)
    if len(invoices) > 1:
        return _checked_result(user, message, tool, "ambiguous", "أدخل المعرّف الداخلي للفاتورة مسبوقًا بـ #.", confidence=confidence)
    sale = invoices[0]
    status = {"confirmed": "مؤكدة", "cancelled": "ملغاة", "draft": "مسودة"}.get(
        sale.status, sale.status or "غير محددة"
    )
    payment = {"paid": "مدفوعة", "partial": "مدفوعة جزئيًا", "unpaid": "غير مدفوعة"}.get(
        sale.payment_status, "غير محددة"
    )
    return _checked_result(
        user, message, tool, "read",
        f"الفاتورة {sale.sale_number}\nالحالة: {status}\nحالة الدفع: {payment}",
        entities={"sale_id": sale.id}, confidence=confidence,
    )


def _uuid(value):
    try:
        identifier = UUID(value)
        return str(identifier) if identifier.version == 4 else None
    except (TypeError, ValueError, AttributeError):
        return None


def _find_action(action_id, user):
    return db.session.scalar(
        select(AssistantAction).where(
            AssistantAction.id == action_id,
            AssistantAction.user_id == user.id,
            AssistantAction.tenant_id == _scope(user),
        )
    )


def _proposal_response(action):
    result = {"response": action.response, "action_status": action.status}
    if action.status != "confirmed" and action.expires_at <= _now():
        return {"response": "انتهت مهلة المسودة. أرسل طلبًا جديدًا.", "action_status": "expired"}
    if action.status == "pending":
        result["confirm_url"] = url_for("ai.confirm_assistant_action", action_id=action.id)
    elif action.status.startswith("po_"):
        result["collect_url"] = url_for(
            "ai.collect_assistant_details", action_id=action.id, step=action.status
        )
        result["multiline"] = action.status == "po_lines"
    return result


def _create_customer_proposal(message, fields, key, user):
    fields = re.sub(r"^(?:اسمه|باسم)\s+", "", fields.strip())
    values = [value.strip() for value in re.split(r"[،,]", fields, maxsplit=2)]
    name, phone, address = (values + [None, None])[:3]
    return propose_customer(message, name, phone, address, key, user)


def propose_customer(message, name, phone, address, key, user):
    tool = "create_customer"
    scoped = _scope(user) is not None or user.is_owner
    if not user.has_permission(_WRITE_PERMISSIONS[tool]) or not scoped:
        return _checked_result(
            user, message, tool, "denied",
            "⛔ تحتاج إلى صلاحية إدارة العملاء ونطاق شركة.",
        ), 403
    fields = (name, phone, address)
    if any(value is not None and not isinstance(value, str) for value in fields):
        return _checked_result(user, message, tool, "invalid", "حقول العميل يجب أن تكون نصية."), 400
    name, phone, address = (value.strip() if value else None for value in fields)
    if not name or len(name) > 200 or (phone and not re.fullmatch(r"\+?[\d() -]{3,29}", phone)):
        return _checked_result(
            user, message, tool, "invalid",
            "اكتب «أضف عميل: اسم العميل» أو «أضف عميل: الاسم، الهاتف، العنوان».",
        ), 400

    payload = {"name": name, "phone": phone or None, "address": address or None}
    preview = f"مسودة إضافة عميل\nالاسم: {name}"
    if phone:
        preview += f"\nالهاتف: {phone}"
    if address:
        preview += f"\nالعنوان: {address}"
    preview += "\nالرصيد الافتتاحي: صفر. راجع البيانات ثم اختر تأكيد الإنشاء."
    return _persist_proposal(message, tool, key, user, payload, preview)


def _read_proposal(message, tool, key, user):
    action_id = _uuid(key)
    if not action_id:
        return {"error": "A UUID v4 Idempotency-Key is required for a proposal."}, 400
    existing = _find_action(action_id, user)
    if not existing:
        return None
    message_hash = sha256(message.encode()).hexdigest()
    if existing.tool != tool or existing.request_hash != message_hash:
        return {"error": "Idempotency key already used for a different action."}, 409
    return _proposal_response(existing)


def _persist_proposal(
    message, tool, key, user, payload, preview, *, audit_entities=None, status="pending", confidence=1.0
):
    prior = _read_proposal(message, tool, key, user)
    if prior is not None:
        return prior
    action_id = _uuid(key)
    action = AssistantAction(
        id=action_id,
        user_id=user.id,
        tenant_id=_scope(user),
        tool=tool,
        status=status,
        request_hash=sha256(message.encode()).hexdigest(),
        payload=payload,
        response=preview,
        expires_at=_now() + PROPOSAL_TTL,
    )
    try:
        db.session.add(action)
        matched = payload if audit_entities is None else audit_entities
        outcome = "proposed" if status == "pending" else "collecting"
        _audit(user, message, tool, outcome, entities=matched, action_id=action_id, confidence=confidence)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _read_proposal(message, tool, key, user) or ({"error": "Idempotency key could not be used."}, 409)
    return _proposal_response(action)


def propose_import(filename, content, warehouse_id, key, user):
    from services.assistant_imports import ImportValidationError, prepare

    tool = "import_stock"
    scope = _scope(user)
    digest = sha256(content).hexdigest()
    source = f"Excel: {filename} | SHA-256: {digest} | warehouse: {warehouse_id}"
    if not user.has_permission(_WRITE_PERMISSIONS[tool]) or (scope is None and not user.is_owner):
        return _checked_result(
            user, source, tool, "denied", "تحتاج إلى صلاحية إدارة المنتجات ونطاق شركة."
        ), 403
    prior = _read_proposal(source, tool, key, user)
    if prior is not None:
        return prior
    try:
        payload, preview = prepare(content, warehouse_id, scope)
    except ImportValidationError as error:
        return _checked_result(user, source, tool, "invalid", str(error), entities=error.entities), 400
    matched = {
        "warehouse_id": payload["warehouse_id"],
        "product_ids": [row["product_id"] for row in payload["rows"] if row["product_id"]],
        "row_count": len(payload["rows"]),
    }
    return _persist_proposal(source, tool, key, user, payload, preview, audit_entities=matched)


def _quote_proposal(message, fields, key, user):
    from services.assistant_quotes import QuoteValidationError, prepare

    tool = "create_draft_quote"
    scope = _scope(user)
    if not user.has_permission(_WRITE_PERMISSIONS[tool]) or (scope is None and not user.is_owner):
        return _checked_result(user, message, tool, "denied", "⛔ تحتاج إلى صلاحية إدارة المبيعات ونطاق شركة.")
    prior = _read_proposal(message, tool, key, user)
    if prior is not None:
        return prior
    try:
        payload, preview = prepare(fields, scope)
    except QuoteValidationError as error:
        return _checked_result(user, message, tool, "invalid", str(error), entities=error.entities)
    return _persist_proposal(message, tool, key, user, payload, preview)


def _start_purchase(message, key, user, *, confidence=1.0):
    from services.assistant_purchases import STEPS

    tool = "create_purchase_order"
    if not user.has_permission(_WRITE_PERMISSIONS[tool]) or (_scope(user) is None and not user.is_owner):
        return _checked_result(
            user, message, tool, "denied", "تحتاج إلى صلاحية إدارة المشتريات ونطاق شركة.",
            confidence=confidence,
        )
    return _persist_proposal(
        message, tool, key, user, {}, STEPS["po_supplier"], status="po_supplier", confidence=confidence
    )


def collect(action_id, step, message, user):
    from services.assistant_purchases import STEPS, PurchaseValidationError, advance, matched_entities

    tool = "create_purchase_order"
    action_id = str(action_id)
    action = _find_action(action_id, user)
    if not action or action.tool != tool or step not in STEPS:
        return {"response": "خطوة أمر الشراء غير متاحة."}, 404
    if not user.has_permission(_WRITE_PERMISSIONS[tool]):
        return _checked_result(
            user, message, tool, "denied", "تحتاج إلى صلاحية إدارة المشتريات.", action_id=action_id
        ), 403
    if action.status != step or action.expires_at <= _now():
        return _proposal_response(action)
    try:
        status, payload, preview = advance(step, message, action.payload, action.tenant_id)
    except PurchaseValidationError as error:
        return _checked_result(
            user, message, tool, "invalid", str(error), entities=error.entities, action_id=action_id,
        ), 400
    changed = db.session.execute(
        update(AssistantAction)
        .where(
            AssistantAction.id == action_id,
            AssistantAction.status == step,
            AssistantAction.expires_at > _now(),
        )
        .values(status=status, payload=payload, response=preview)
    )
    if not changed.rowcount:
        db.session.rollback()
        current = _find_action(action_id, user)
        return _proposal_response(current) if current else ({"response": "المسودة غير متاحة."}, 404)
    _audit(
        user, message, tool, "proposed" if status == "pending" else "step_saved",
        entities=matched_entities(payload), action_id=action_id,
    )
    db.session.commit()
    return _proposal_response(action)


def interpret(message, user, key):
    command = re.split(r"[،,؛;\n]", message, maxsplit=1)[0]
    if re.fullmatch(
        r"(?:اريد |بدي |ابغي )?(?:انشي |انشا |جهز |اعمل )?(?:مسوده )?امر شرا"
        r"|(?:(?:start|draft|create)(?: a)? )?purchase order",
        normalize(command),
    ):
        return _start_purchase(message, key, user)

    match = _QUOTE.match(message)
    if match:
        return _quote_proposal(message, message[match.end():], key, user)

    match = _CREATE_CUSTOMER.match(message)
    if match:
        return _create_customer_proposal(message, message[match.end():], key, user)

    match = _BALANCE.match(message)
    if match:
        return _balance(message, match[1], user)

    match = _STOCK.match(message)
    if match:
        return _product_stock(message, match[1], user)

    match = _INVOICE.match(message)
    if match:
        return _invoice_status(message, match[1], user)
    return None


def interpret_prediction(message, user, prediction, key=None):
    if prediction is None:
        return None
    tool, confidence, references = prediction
    if confidence < 0.65:
        return None
    if len(references) == 1 and not _WRITE_PREFIX.match(normalize(message)):
        if tool == "check_stock":
            return _product_stock(message, references[0], user, confidence=confidence)
        if tool == "get_invoice_status":
            return _invoice_status(message, references[0], user, confidence=confidence)
        if tool == "get_customer_balance" and _CUSTOMER_ID.fullmatch(references[0]):
            return _balance(message, references[0], user, confidence=confidence)

    examples = {
        "check_stock": "اكتب «مخزون الصنف» متبوعة برمز الصنف.",
        "get_invoice_status": "اكتب «حالة فاتورة» متبوعة برقم الفاتورة.",
        "get_customer_balance": "اكتب «رصيد» متبوعة باسم العميل أو رقمه.",
        "create_customer": "اكتب «أضف عميل: اسم العميل» لعرض مسودة للمراجعة.",
    }
    if tool in examples:
        return _checked_result(
            user, message, tool, "clarification", examples[tool], confidence=confidence
        )
    if tool == "create_draft_quote":
        return _quotation_form(message, user, confidence)
    if tool == "create_purchase_order":
        return _start_purchase(message, key, user, confidence=confidence)
    return None


def _quotation_form(message, user, confidence):
    tool = "create_draft_quote"
    if not user.has_permission("manage_sales"):
        return _checked_result(
            user, message, tool, "denied", "⛔ تحتاج إلى صلاحية إدارة المبيعات.",
            confidence=confidence,
        )
    result = _checked_result(
        user, message, tool, "use_erp",
        "اكتب «عرض سعر: العميل | رمز الصنف | الكمية | رمز المستودع | العملة» لمراجعة المسودة، "
        "أو افتح نموذج عرض السعر.",
        confidence=confidence,
    )
    result["formal_url"] = url_for(_FORMAL_ROUTES[tool])
    return result


def formal_action(message, user):
    """Route legacy operations to ERP forms with their usual authorization."""
    from services.ai_flows import find_flow

    text = normalize(message)
    if _WRITE_PREFIX.match(text) and re.search(r"\b(?:عرض اسعار|عرض سعر|تسعيره|quotation|quote)\b", text):
        return _quotation_form(message, user, 1.0)
    if not _WRITE_PREFIX.match(text) and ":" not in message:
        return None
    flow = find_flow(text)
    if not flow:
        if not _WRITE_PREFIX.match(text):
            return None
        return _checked_result(
            user, message, "unsupported_write", "use_erp",
            "أكمل هذه العملية من نموذجها في النظام.",
            confidence=0.0,
        )
    if not user.has_permission(flow.permission):
        return _checked_result(
            user, message, flow.key, "denied", "⛔ تحتاج إلى صلاحية هذه العملية.",
            confidence=0.8,
        )
    result = _checked_result(
        user, message, flow.key, "use_erp",
        "أكمل العملية من نموذجها في النظام لمراجعة البيانات قبل الحفظ.",
        confidence=0.8,
    )
    if flow.key in _FORMAL_ROUTES:
        result["formal_url"] = url_for(_FORMAL_ROUTES[flow.key])
    return result


def pending(user):
    permissions = [
        tool
        for tool, permission in _WRITE_PERMISSIONS.items()
        if user.has_permission(permission)
    ]
    if not permissions:
        return []
    actions = db.session.scalars(
        select(AssistantAction)
        .where(
            AssistantAction.user_id == user.id,
            AssistantAction.tenant_id == _scope(user),
            AssistantAction.tool.in_(permissions),
            or_(AssistantAction.status == "pending", AssistantAction.status.startswith("po_")),
            AssistantAction.expires_at > _now(),
        )
        .order_by(AssistantAction.created_at, AssistantAction.id)
    ).all()
    return [_proposal_response(action) for action in actions]


def confirmation_permission(tool):
    return _WRITE_PERMISSIONS.get(tool)


def apply_confirmed_action(action, user):
    """Apply a claimed business preview in the caller's transaction."""
    from services.ai_commands import create_customer
    from services.assistant_imports import apply as apply_import
    from services.assistant_purchases import create_draft as create_purchase_draft
    from services.assistant_quotes import create_draft
    from services.assistant_transfers import create_request

    if action.tool == "create_customer":
        customer = create_customer(**action.payload, commit=False, actor_id=user.id)
        if customer.tenant_id != action.tenant_id:
            raise ValueError("Confirmed customer's tenant differs from the proposal")
        entities = {"customer_id": customer.id}
        action.response = f"تم إنشاء العميل {customer.name} (#{customer.id})."
    elif action.tool == "create_purchase_order":
        order = create_purchase_draft(action.payload, user, action.tenant_id)
        entities = {"purchase_order_id": order.id}
        action.response = f"حُفظ أمر الشراء {order.po_number} كمسودة."
    elif action.tool == "import_stock":
        entities = apply_import(action.payload, action.tenant_id, actor_id=user.id)
        action.response = (
            f"تم استيراد {len(entities['product_ids'])} صنفًا إلى {action.payload['warehouse']}. "
            f"عدد حركات المخزون: {len(entities['movement_ids'])}."
        )
        action.payload = {}
    elif action.tool == "create_draft_quote":
        quote = create_draft(action.payload, user, action.tenant_id)
        entities = {"quotation_id": quote.id}
        action.response = f"حُفظ عرض السعر {quote.quotation_number} كمسودة."
    elif action.tool == "stock_transfer":
        transfer = create_request(action.payload, user, action.tenant_id)
        entities = {"stock_transfer_id": transfer.id}
        action.response = f"حُفظ طلب نقل المخزون {transfer.transfer_number} قيد الانتظار."
    else:
        raise ValueError("Unsupported assistant confirmation tool")
    return entities


def confirm(action_id, user):
    from services.assistant_imports import ImportValidationError
    from services.assistant_purchases import PurchaseValidationError
    from services.assistant_quotes import QuoteValidationError
    from services.assistant_transfers import TransferValidationError

    action = _find_action(str(action_id), user)
    if not action:
        return _checked_result(
            user, None, "confirmation", "unavailable", "المسودة غير متاحة.",
            action_id=str(action_id),
        ), 404

    permission = _WRITE_PERMISSIONS.get(action.tool)
    if not permission or not user.has_permission(permission):
        return _checked_result(
            user, None, action.tool, "confirmation_denied", "⛔ تحتاج إلى صلاحية هذه العملية.",
            action_id=action.id,
        ), 403

    if action.status != "pending" or action.expires_at <= _now():
        return _proposal_response(action)

    claimed = db.session.execute(
        update(AssistantAction)
        .where(
            AssistantAction.id == action.id,
            AssistantAction.status == "pending",
            AssistantAction.expires_at > _now(),
        )
        .values(status="confirmed")
    )
    if not claimed.rowcount:
        db.session.rollback()
        return _proposal_response(_find_action(str(action_id), user))

    try:
        entities = apply_confirmed_action(action, user)
        _audit(
            user, None, action.tool, "confirmed",
            entities=entities, action_id=action.id,
        )
        db.session.commit()
    except (QuoteValidationError, ImportValidationError, PurchaseValidationError, TransferValidationError) as error:
        db.session.rollback()
        return _checked_result(
            user, None, action.tool, "validation_failed_on_confirm", str(error),
            entities=error.entities, action_id=action.id,
        ), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Assistant action confirmation rolled back")
        _audit(user, None, action.tool, "confirmation_failed", action_id=action.id)
        db.session.commit()
        return {"response": "تعذّر حفظ العملية. يمكنك إعادة محاولة التأكيد."}, 500

    return _proposal_response(action)
