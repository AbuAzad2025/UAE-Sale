"""Build a short-lived context from scoped conversation memory and live ERP state."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from bot_core.dialogue import Dialogue
from bot_core.observability import utcnow
from bot_core.security import Actor, Principal
from extensions import db
from models import AssistantAction, Customer, Product, Sale, Tenant
from models.bot_event import BotContextMemory
from models.budget import Budget
from models.erp_modules import FiscalPeriod, Quotation
from services.tax_engine import resolve

REFERENCE_PERMISSIONS = {
    "customer": ("manage_customers",), "product": ("view_products", "manage_products", "view_reports"),
    "invoice": ("manage_sales", "view_reports"), "quotation": ("manage_sales",),
}
_REFERENCE_FIELDS = {
    "customer_ids": "customer", "customer_id": "customer", "product_ids": "product", "product_id": "product",
    "sale_id": "invoice", "quotation_id": "quotation",
}


@dataclass(frozen=True, slots=True)
class EntityReference:
    kind: str
    id: int
    label: str
    status: str | None = None
    balance_or_stock: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ConversationContext:
    dialogue: Dialogue | None
    last_tool: str | None
    references: tuple[EntityReference, ...]
    pending_action: str | None = None


@dataclass(frozen=True, slots=True)
class TenantContext:
    country: str | None
    industry: str | None
    business_type: str | None
    currency: str | None
    tax_rate: Decimal | None = None
    tax_inclusive: bool | None = None


@dataclass(frozen=True, slots=True)
class FinancialContext:
    fiscal_periods: tuple[tuple[int, bool], ...] = ()
    active_budget_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class InteractionContext:
    actor: Actor
    permissions: frozenset[str]
    conversation: ConversationContext
    tenant: TenantContext | None = None
    financial: FinancialContext = FinancialContext()


def _can(principal: Principal, *permissions: str) -> bool:
    return any(principal.has_permission(permission) for permission in permissions)


def _resolve_reference(actor: Actor, principal: Principal, kind: str, ids: list[int]) -> list[EntityReference]:
    if not ids or not _can(principal, *REFERENCE_PERMISSIONS[kind]):
        return []
    models = {
        "customer": (Customer, Customer.name, Customer.balance, None),
        "product": (Product, Product.name, Product.current_stock, None),
        "invoice": (Sale, Sale.sale_number, Sale.balance_due, Sale.payment_status),
        "quotation": (Quotation, Quotation.quotation_number, None, Quotation.status),
    }
    from sqlalchemy import null

    model, label, amount, status = models[kind]
    rows = db.session.execute(select(model.id, label, amount if amount is not None else null(),
                                    status if status is not None else null()).where(
        model.tenant_id == actor.tenant_id, model.id.in_(ids), model.is_active.is_(True),
    ))
    by_id = {record_id: EntityReference(kind, record_id, title, state, value)
             for record_id, title, value, state in rows}
    return [by_id[record_id] for record_id in ids if record_id in by_id]


def capture(actor: Actor, principal: Principal, dialogue: Dialogue | None) -> InteractionContext:
    if principal.id != actor.user_id or not principal.is_authenticated:
        raise PermissionError("An authenticated local agent principal is required")
    permissions = frozenset(code for code in {"manage_budget", "manage_ledger", "view_ledger",
                            *(code for group in REFERENCE_PERMISSIONS.values() for code in group)}
                            if principal.has_permission(code))
    if actor.tenant_id is None:
        return InteractionContext(actor, permissions, ConversationContext(dialogue, None, ()))

    now = utcnow()
    memory = db.session.get(BotContextMemory, (actor.user_id, actor.tenant_id))
    refs = []
    last_tool = None
    if memory is not None and memory.expires_at > now:
        last_tool = memory.last_tool
        for kind, ids in memory.references.items():
            if kind in REFERENCE_PERMISSIONS:
                refs.extend(_resolve_reference(actor, principal, kind, ids))

    action_id = None
    if dialogue is not None and dialogue.topic == "confirmation" and dialogue.slots.get("action_id"):
        action_id = db.session.scalar(select(AssistantAction.id).where(
            AssistantAction.user_id == actor.user_id, AssistantAction.tenant_id == actor.tenant_id,
            AssistantAction.id == dialogue.slots["action_id"], AssistantAction.status == "pending",
            AssistantAction.expires_at > now,
        ))

    tenant = db.session.get(Tenant, actor.tenant_id)
    if tenant is None or not tenant.is_active:
        raise PermissionError("The ERP company is unavailable")
    tax = resolve(tenant) if _can(principal, "manage_sales", "manage_ledger", "view_ledger") else (None, None)
    today = date.today()
    periods = ()
    budgets = ()
    if _can(principal, "manage_sales", "manage_ledger", "view_ledger"):
        periods = tuple(tuple(row) for row in db.session.execute(select(FiscalPeriod.id, FiscalPeriod.is_closed).where(
            FiscalPeriod.tenant_id == actor.tenant_id, FiscalPeriod.start_date <= today, FiscalPeriod.end_date >= today,
        ).order_by(FiscalPeriod.id).limit(5)))
    if _can(principal, "manage_budget"):
        budgets = tuple(db.session.scalars(select(Budget.id).where(
            Budget.tenant_id == actor.tenant_id, Budget.status == "active", Budget.period_start <= today,
            Budget.period_end >= today,
        ).order_by(Budget.id).limit(10)))
    return InteractionContext(actor, permissions, ConversationContext(dialogue, last_tool, tuple(refs), action_id),
                              TenantContext(tenant.country, tenant.industry, tenant.business_type, tenant.default_currency, *tax),
                              FinancialContext(periods, budgets))


def remember(context: InteractionContext, tool: str, entities: Mapping, *, ambiguous: bool = False) -> None:
    actor = context.actor
    if actor.tenant_id is None:
        return
    refs: dict[str, list[int]] = {}
    for reference in context.conversation.references:
        refs.setdefault(reference.kind, []).append(reference.id)
    for field, value in entities.items():
        kind = _REFERENCE_FIELDS.get(field)
        if kind is None:
            continue
        ids = value if isinstance(value, list) else [value]
        valid_ids = list(dict.fromkeys(item for item in ids if type(item) is int and item > 0))[:5]
        if valid_ids or ambiguous:
            refs[kind] = valid_ids
    db.session.merge(BotContextMemory(user_id=actor.user_id, tenant_id=actor.tenant_id,
                                     references=refs, last_tool=tool, expires_at=utcnow() + timedelta(minutes=15)))


def forget(actor: Actor) -> None:
    if actor.tenant_id is not None:
        row = db.session.get(BotContextMemory, (actor.user_id, actor.tenant_id))
        if row is not None:
            db.session.delete(row)
