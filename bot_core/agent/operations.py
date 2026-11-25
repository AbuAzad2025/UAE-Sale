"""Structured actions accepted only from authenticated ERP controls."""

from base64 import b64decode
from decimal import Decimal
from typing import Annotated, cast

from pydantic import BaseModel, Field
from sqlalchemy import select, update

from bot_core.agent import Tool, ToolResult
from bot_core.agent.erp import stage_action
from bot_core.observability import utcnow
from bot_core.security import Actor, Effect
from extensions import db
from models import AssistantAction, User
from services.assistant_imports import MAX_FILE_BYTES, ImportValidationError, prepare


class ConfirmAction(BaseModel):
    action_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ImportWorkbook(BaseModel):
    content: str = Field(min_length=4, max_length=4 * ((MAX_FILE_BYTES + 2) // 3))
    warehouse_id: Annotated[int, Field(gt=0, le=2147483647)] | None = None


class StockTransfer(BaseModel):
    source: str = Field(min_length=1, max_length=50)
    target: str = Field(min_length=1, max_length=50)
    sku: str = Field(min_length=1, max_length=50)
    quantity: str = Field(pattern=r"^\d{1,9}(?:[.٫]\d{1,3})?$")


class QuoteDraft(BaseModel):
    details: str = Field(min_length=1, max_length=4000)


def prepare_quote(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    from services.assistant_quotes import prepare

    payload, preview = prepare(cast(QuoteDraft, args).details, actor.tenant_id)
    action = stage_action(actor, request_id, "create_draft_quote", payload, preview)
    entities = {key: payload[key] for key in ("customer_id", "product_id", "warehouse_id")}
    return ToolResult(action.response, "proposed", entities, {"action_id": action.id})


def prepare_transfer(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    from services.assistant_transfers import prepare

    transfer = cast(StockTransfer, args)
    payload, preview = prepare(
        transfer.source, transfer.target, transfer.sku,
        Decimal(transfer.quantity.replace("٫", ".")), actor.tenant_id,
    )
    action = stage_action(actor, request_id, "stock_transfer", payload, preview)
    entities = {key: payload[key] for key in ("source_id", "target_id", "product_id")}
    return ToolResult(action.response, "proposed", entities, {"action_id": action.id})


def prepare_import(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    workbook = cast(ImportWorkbook, args)
    content = b64decode(workbook.content, validate=True)
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("The workbook exceeds its size limit.")
    try:
        payload, preview = prepare(content, workbook.warehouse_id, actor.tenant_id)
    except ImportValidationError as error:
        return ToolResult(str(error), "invalid", error.entities)
    action = stage_action(actor, request_id, "import_stock", payload, preview)
    entities = {
        "warehouse_id": payload["warehouse_id"],
        "product_ids": [row["product_id"] for row in payload["rows"] if row["product_id"]],
        "row_count": len(payload["rows"]),
    }
    return ToolResult(action.response, "proposed", entities, {"action_id": action.id})


def confirm_action(args: BaseModel, actor: Actor, request_id: str) -> ToolResult:
    from services.assistant_actions import apply_confirmed_action, confirmation_permission

    action_id = cast(ConfirmAction, args).action_id
    scope = (
        AssistantAction.id == action_id,
        AssistantAction.user_id == actor.user_id,
        AssistantAction.tenant_id == actor.tenant_id,
    )
    action = db.session.scalar(select(AssistantAction).where(*scope))
    if action is None:
        return ToolResult("المسودة غير متاحة.", "not_found", {})
    principal = db.session.get(User, actor.user_id, execution_options={"skip_tenant_filter": True})
    permission = confirmation_permission(action.tool)
    if principal is None or not principal.is_active or not permission or not principal.has_permission(permission):
        raise PermissionError("The current ERP user cannot confirm this action.")
    changed = db.session.execute(
        update(AssistantAction)
        .where(*scope, AssistantAction.status == "pending", AssistantAction.expires_at > utcnow())
        .values(status="confirmed")
    )
    if changed.rowcount != 1:
        db.session.refresh(action)
        if action.status == "confirmed" or action.status == "cancelled":
            return ToolResult(action.response, action.status, {"action_id": action_id})
        return ToolResult("انتهت مهلة المسودة أو لم تكتمل بياناتها.", "invalid", {"action_id": action_id})
    entities = apply_confirmed_action(action, principal)
    return ToolResult(action.response, "confirmed", {"action_id": action_id, **entities})


def operation_tools() -> tuple[Tool, ...]:
    return (
        Tool("draft_quote", "Prepare a sales quotation for human confirmation.", QuoteDraft,
             ("manage_sales",), Effect.PREVIEW, prepare_quote),
        Tool("stock_transfer", "Prepare a reviewed same-company stock transfer request.",
             StockTransfer, ("manage_warehouse",), Effect.PREVIEW, prepare_transfer),
        Tool("prepare_stock_import", "Validate an uploaded workbook and prepare an inventory preview.",
             ImportWorkbook, ("manage_products",), Effect.PREVIEW, prepare_import, timeout_ms=60000),
        Tool("confirm_action", "Apply a specific reviewed preview after an explicit confirmation.",
             ConfirmAction, ("manage_products", "manage_sales", "manage_customers", "manage_purchases", "manage_warehouse"),
             Effect.CONFIRMED, confirm_action, timeout_ms=85000),
    )
