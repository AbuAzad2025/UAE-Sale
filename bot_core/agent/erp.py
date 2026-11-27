"""Typed ERP adapters. Each query applies the authenticated company scope."""

from datetime import timedelta
from functools import partial
from hashlib import sha256
import json
from typing import cast

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from bot_core.agent import Tool, ToolRegistry, ToolResult
from bot_core.context import REFERENCE_PERMISSIONS
from bot_core.dialogue import Dialogue, StateManager
from bot_core.gateway import normalize
from bot_core.neural_nlu.retrieval import rank
from bot_core.observability import utcnow
from bot_core.security import Actor, Effect
from extensions import db
from models import AssistantAction, Customer, Product, Sale, SaleLine, Tenant
from services.ai_questions import COMPANY_SELECTION_REQUIRED, SUMMARY_PERMISSIONS, business_summary
from utils.constants import SALE_STATUSES


class Reference(BaseModel):
    reference: str = Field(min_length=1, max_length=200)


class CustomerDraft(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class PurchaseTurn(BaseModel):
    answer: str | None = Field(default=None, min_length=1, max_length=4000)


class CustomerNote(BaseModel):
    customer_id: int = Field(gt=0, le=2147483647)
    note: str = Field(min_length=1, max_length=4000)


class SalesReport(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    period: str | None = None


class SummaryRequest(BaseModel):
    """The tool accepts no parameters from the conversation."""


def summary_report(kind: str, args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    return ToolResult(business_summary(kind, actor.tenant_id), "read" if actor.tenant_id is not None else "clarification", {})


def sales_report(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    from services.ai_questions import _sales_answer

    if actor.tenant_id is None:
        return ToolResult(COMPANY_SELECTION_REQUIRED, "clarification", {})
    report = cast(SalesReport, args)
    query = Sale.query.filter_by(tenant_id=actor.tenant_id, status="confirmed")
    periods = []
    message = _sales_answer(query, Sale, report.question, period=report.period, resolved_periods=periods)
    return ToolResult(message, "read", {}, {"follow_up_topic": "sales"},
                      Dialogue("sales_report", {"periods": periods}))


def _query(model, actor: Actor):
    return select(model).where(model.tenant_id == actor.tenant_id)


def _reference(query, model, value: str, *columns):
    key = normalize(value)
    if key.startswith("#") and len(key) <= 11 and key[1:].isascii() and key[1:].isdigit() and int(key[1:]) <= 2147483647:
        return query.where(model.id == int(key[1:]))
    return query.where(or_(*(func.lower(column) == value.lower() for column in columns)))


def _suggestions(query, model, value: str):
    words = [word[:3] for word in normalize(value).split() if len(word) >= 3][:8]
    if not words or value.strip().startswith("#"):
        return []
    candidates = db.session.scalars(
        query.where(or_(*(func.lower(model.name).contains(word, autoescape=True) for word in words)))
        .order_by(model.id).limit(300)
    )
    return rank(value, ((row, row.name) for row in candidates))


def customer_balance(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    value = cast(Reference, args).reference
    query = _query(Customer, actor).where(Customer.is_active.is_(True))
    matches = db.session.scalars(
        _reference(query, Customer, value, Customer.name).order_by(Customer.id).limit(11)
    ).all()
    if not matches and (similar := _suggestions(query, Customer, value)):
        options = "، ".join(f"{row.name} (#{row.id})" for row in similar)
        return ToolResult(f"وجدت أسماء قريبة. اختر الرقم المطلوب: {options}", "ambiguous",
                          {"customer_ids": [row.id for row in similar]})
    entities = {"customer_ids": [customer.id for customer in matches]}
    if len(matches) > 1:
        options = "، ".join(f"{customer.name} (#{customer.id})" for customer in matches[:10])
        return ToolResult(f"وجدت أكثر من عميل. اختر رقمًا من القائمة: {options}", "ambiguous", entities)
    if not matches:
        return ToolResult("لم أجد عميلًا مطابقًا في الشركة الحالية.", "not_found", entities)
    customer = matches[0]
    return ToolResult(
        f"رصيد {customer.name}: {customer.balance:,.2f} بالعملة الأساسية.",
        "read", entities,
    )


def _stock_message(name, quantity) -> str:
    if quantity is None:
        return f"كمية المخزون غير مسجلة للصنف {name}."
    formatted = f"{quantity:,.3f}".rstrip("0").rstrip(".")
    availability = "متوفر" if quantity > 0 else "غير متوفر"
    return f"{name} {availability}. المخزون الإجمالي المسجل: {formatted}."


def stock(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    value = cast(Reference, args).reference
    query = _query(Product, actor).where(Product.is_active.is_(True))
    matches = db.session.scalars(
        _reference(query, Product, value, Product.sku, Product.part_number, Product.name)
        .order_by(Product.id).limit(11)
    ).all()
    if not matches and (similar := _suggestions(query, Product, value)):
        options = "، ".join(f"{row.name} (#{row.id})" for row in similar)
        return ToolResult(f"وجدت أصنافًا قريبة. اختر الرقم المطلوب: {options}", "ambiguous",
                          {"product_ids": [row.id for row in similar]})
    entities = {"product_ids": [product.id for product in matches]}
    if len(matches) > 1:
        options = "، ".join(f"{product.name} (#{product.id})" for product in matches[:10])
        return ToolResult(f"وجدت أكثر من صنف. اختر رقمًا من القائمة: {options}", "ambiguous", entities)
    if not matches:
        return ToolResult("لم أجد صنفًا مطابقًا في الشركة الحالية.", "not_found", entities)
    product = matches[0]
    return ToolResult(_stock_message(product.name, product.current_stock), "read", entities)


_SALE_LABEL = {key: labels["ar"] for key, labels in SALE_STATUSES}
_PAYMENT_LABEL = {"paid": "مدفوعة", "partial": "مدفوعة جزئيًا", "unpaid": "غير مدفوعة"}


def _invoice_rows(actor: Actor):
    return select(Sale.id, Sale.sale_number, Sale.status, Sale.payment_status, Sale.balance_due, Sale.customer_id, Customer.name.label("customer_name")).outerjoin(
        Customer, (Customer.id == Sale.customer_id) & (Customer.tenant_id == Sale.tenant_id)
    ).where(
        Sale.tenant_id == actor.tenant_id, Sale.is_active.is_(True),
    )


def _invoice_by_reference(actor: Actor, value: str):
    query = _reference(_invoice_rows(actor), Sale, value, Sale.sale_number)
    return db.session.execute(query.limit(1)).first()


def _invoice_result(match, actor: Actor, *, prefix: str = "") -> ToolResult:
    if match is None:
        return ToolResult("لم أجد فاتورة مطابقة في الشركة الحالية.", "not_found", {"sale_id": None})
    status = _SALE_LABEL.get(match.status, "غير محددة")
    payment = _PAYMENT_LABEL.get(match.payment_status, "غير محددة")
    detail = f"الفاتورة {match.sale_number} {status} وحالة السداد {payment}."
    if match.customer_name and not prefix:
        detail += f" العميل: {match.customer_name}."
    if match.status == "confirmed" and match.balance_due is not None:
        base = db.session.scalar(select(Tenant.default_currency).where(Tenant.id == actor.tenant_id))
        currency = base or "بالعملة الأساسية"
        detail += f" المتبقي للسداد: {match.balance_due:,.2f} {currency}."
    return ToolResult(prefix + detail, "read", {"sale_id": match.id})


def invoice_status(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    return _invoice_result(_invoice_by_reference(actor, cast(Reference, args).reference), actor)


def latest_customer_invoice(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    value = cast(Reference, args).reference
    query = select(Customer.id, Customer.name).where(Customer.tenant_id == actor.tenant_id, Customer.is_active.is_(True))
    customers = db.session.execute(_reference(query, Customer, value, Customer.name).order_by(Customer.id).limit(10)).all()
    if not customers:
        return ToolResult("لم أجد العميل في الشركة الحالية.", "not_found", {"customer_id": None, "sale_id": None})
    if len(customers) > 1:
        options = "، ".join(f"{customer.name} (#{customer.id})" for customer in customers)
        return ToolResult(f"أي عميل تقصد؟ {options}", "ambiguous",
                          {"customer_ids": [customer.id for customer in customers], "sale_id": None})
    customer = customers[0]
    match = db.session.execute(_invoice_rows(actor).where(
        Sale.customer_id == customer.id, Sale.status == "confirmed",
    ).order_by(Sale.sale_date.desc(), Sale.id.desc()).limit(1)).first()
    if match is None:
        return ToolResult(f"لا توجد فواتير مؤكدة للعميل {customer.name}.", "not_found",
                          {"customer_id": customer.id, "sale_id": None})
    result = _invoice_result(match, actor, prefix=f"آخر فاتورة مؤكدة للعميل {customer.name}. ")
    return ToolResult(result.message, result.outcome, {"customer_id": customer.id, **result.entities})


def invoice_stock(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    match = _invoice_by_reference(actor, cast(Reference, args).reference)
    if match is None:
        return ToolResult("لم أجد الفاتورة في الشركة الحالية.", "not_found", {"sale_id": None})
    products = db.session.execute(
        select(Product.id, Product.name, Product.current_stock)
        .join(SaleLine, SaleLine.product_id == Product.id)
        .where(SaleLine.tenant_id == actor.tenant_id, SaleLine.sale_id == match.id,
               Product.tenant_id == actor.tenant_id, Product.is_active.is_(True))
        .distinct().order_by(Product.id).limit(10)
    ).all()
    if not products:
        return ToolResult("لا توجد أصناف نشطة مرتبطة بهذه الفاتورة.", "not_found", {"product_ids": []})
    entities = {"sale_id": match.id, "product_ids": [product.id for product in products]}
    if len(products) > 1:
        options = "، ".join(f"{product.name} (#{product.id})" for product in products)
        return ToolResult(f"أي صنف من الفاتورة {match.sale_number} تقصد؟ {options}", "ambiguous", entities,
                          dialogue=Dialogue("check_stock", {"candidate_ids": entities["product_ids"]}))
    product = products[0]
    return ToolResult(f"الصنف في الفاتورة {match.sale_number}. " + _stock_message(product.name, product.current_stock),
                      "read", entities)


def invoice_customer_balance(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    match = _invoice_by_reference(actor, cast(Reference, args).reference)
    if match is None:
        return ToolResult("لم أجد الفاتورة في الشركة الحالية.", "not_found", {"sale_id": None, "customer_id": None})
    result = customer_balance(Reference(reference=f"#{match.customer_id}"), actor, request_id)
    return ToolResult(result.message, result.outcome, {"sale_id": match.id, **result.entities})


def stage_action(actor: Actor, request_id: str, tool: str, payload: dict, preview: str) -> AssistantAction:
    digest = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    action = db.session.get(AssistantAction, request_id)
    if action is not None and (
        action.user_id != actor.user_id or action.tenant_id != actor.tenant_id
        or action.tool != tool or action.request_hash != digest
    ):
        raise ValueError("The action key is already in use.")
    if action is None:
        action = AssistantAction(
            id=request_id, user_id=actor.user_id, tenant_id=actor.tenant_id,
            tool=tool, status="pending", request_hash=digest, payload=payload, response=preview,
            expires_at=utcnow() + timedelta(minutes=15),
        )
        db.session.add(action)
    return action


def draft_customer(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    name = cast(CustomerDraft, args).name
    action = stage_action(
        actor, request_id, "create_customer", {"name": name, "phone": None, "address": None},
        f"مسودة إضافة عميل: {name}. الرصيد الافتتاحي صفر.",
    )
    return ToolResult(action.response, "proposed", {}, {"action_id": action.id})


def add_customer_note(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    from utils.helpers import create_audit_log

    update = cast(CustomerNote, args)
    customer = db.session.scalar(_query(Customer, actor).where(
        Customer.id == update.customer_id, Customer.is_active.is_(True)
    ).with_for_update())
    if customer is None:
        return ToolResult("لم أجد عميلًا مطابقًا في الشركة الحالية.", "not_found", {})
    customer.notes = f"{customer.notes}\n{update.note}" if customer.notes else update.note
    create_audit_log(
        "update", "customers", customer.id,
        changes={"field": "notes", "agent_request_id": request_id}, commit=False, actor_id=actor.user_id,
    )
    return ToolResult(f"أُضيفت ملاحظة للعميل {customer.name}.", "updated", {"customer_id": customer.id})


def purchase_order(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    from services.assistant_purchases import STEPS, PurchaseValidationError, advance, matched_entities

    answer = cast(PurchaseTurn, args).answer
    dialogue = StateManager().load(actor)
    if answer is None:
        if dialogue is None or dialogue.topic != "purchase_order":
            dialogue = Dialogue("purchase_order", {"step": "po_supplier", "fields": {}})
        return ToolResult(STEPS[dialogue.slots["step"]], "clarification", {}, dialogue=dialogue)
    if dialogue is None or dialogue.topic != "purchase_order":
        return ToolResult("ابدأ أمر شراء جديدًا لمتابعة إدخال البيانات.", "clarification", {})
    try:
        step, payload, message = advance(
            dialogue.slots["step"], answer, dialogue.slots["fields"], actor.tenant_id,
        )
    except PurchaseValidationError as error:
        return ToolResult(str(error), "invalid", error.entities, dialogue=dialogue)
    entities = matched_entities(payload)
    if step == "pending":
        action = stage_action(actor, request_id, "create_purchase_order", payload, message)
        return ToolResult(action.response, "proposed", entities, {"action_id": action.id})
    state = Dialogue("purchase_order", {"step": step, "fields": payload})
    return ToolResult(message, "clarification", entities, dialogue=state)


def build_registry() -> ToolRegistry:
    from bot_core.agent.operations import operation_tools

    return ToolRegistry((
        Tool("get_customer_balance", "Look up a customer's current balance.", Reference,
             ("manage_customers",), Effect.READ, customer_balance),
        Tool("check_stock", "Look up stock by product code or name.", Reference,
             ("view_products", "manage_products", "view_reports"), Effect.READ, stock),
        Tool("get_invoice_status", "Look up a sales invoice by number.", Reference,
             ("manage_sales", "view_reports"), Effect.READ, invoice_status),
        Tool("get_latest_customer_invoice", "Read the newest confirmed invoice for a scoped customer.", Reference,
             REFERENCE_PERMISSIONS["invoice"], Effect.READ, latest_customer_invoice,
             related_permissions=REFERENCE_PERMISSIONS["customer"]),
        Tool("check_invoice_stock", "Read live stock for an item of a scoped invoice.", Reference,
             REFERENCE_PERMISSIONS["product"], Effect.READ, invoice_stock,
             related_permissions=REFERENCE_PERMISSIONS["invoice"]),
        Tool("get_invoice_customer_balance", "Read the live balance of the customer on a scoped invoice.", Reference,
             REFERENCE_PERMISSIONS["customer"], Effect.READ, invoice_customer_balance,
             related_permissions=REFERENCE_PERMISSIONS["invoice"]),
        Tool("sales_report", "Summarize and compare confirmed sales by period and currency.", SalesReport,
             ("view_reports", "manage_sales"), Effect.READ, sales_report),
        *(Tool(f"summary_{kind}", f"Read the {kind} summary.", SummaryRequest, permissions, Effect.READ,
               partial(summary_report, kind)) for kind, permissions in SUMMARY_PERMISSIONS.items()),
        Tool("draft_customer", "Prepare a customer for human confirmation.", CustomerDraft,
             ("manage_customers",), Effect.PREVIEW, draft_customer),
        Tool("add_customer_note", "Append a non-financial customer note.", CustomerNote,
             ("manage_customers",), Effect.MUTATION, add_customer_note),
        Tool("purchase_order", "Collect purchase details and prepare a human-confirmed draft.", PurchaseTurn,
             ("manage_purchases",), Effect.PREVIEW, purchase_order),
        *operation_tools(),
    ))
