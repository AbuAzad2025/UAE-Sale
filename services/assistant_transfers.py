"""Validate and stage same-company stock transfers for the ERP workflow."""

from decimal import Decimal

from sqlalchemy import func, select

from extensions import db
from models import Product, StockMovement, Warehouse
from services.erp_modules_service import StockTransferService


class TransferValidationError(ValueError):
    def __init__(self, message, entities=None):
        super().__init__(message)
        self.entities = entities or {}


def _active(model, scope):
    return select(model).where(model.tenant_id == scope, model.is_active.is_(True))


def _available(scope, source_id, product_id):
    return db.session.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
            StockMovement.tenant_id == scope,
            StockMovement.warehouse_id == source_id,
            StockMovement.product_id == product_id,
        )
    )


def prepare(source_code, target_code, sku, quantity, scope):
    if scope is None:
        raise TransferValidationError("اختر الشركة قبل طلب نقل المخزون.")
    source = db.session.scalar(_active(Warehouse, scope).where(Warehouse.code == source_code))
    target = db.session.scalar(_active(Warehouse, scope).where(Warehouse.code == target_code))
    if source is None or target is None or source.id == target.id:
        raise TransferValidationError("حدد مستودعين نشطين ومختلفين في الشركة.")
    product = db.session.scalar(_active(Product, scope).where(Product.sku == sku))
    if product is None:
        raise TransferValidationError("رمز الصنف غير موجود في الشركة.")
    if quantity <= 0 or quantity > _available(scope, source.id, product.id):
        raise TransferValidationError("الكمية المطلوبة تتجاوز الرصيد المتاح في المستودع المصدر.")
    payload = {
        "source_id": source.id, "source": source.name, "target_id": target.id, "target": target.name,
        "product_id": product.id, "product": product.name, "quantity": str(quantity),
    }
    preview = (
        f"معاينة طلب نقل {quantity:g} من {product.name} ({sku}) من {source.name} إلى {target.name}.\n"
        "يحفظ التأكيد طلب النقل قيد الانتظار. تُسجّل حركة المخزون عند إتمام النقل في ERP."
    )
    return payload, preview


def create_request(payload, user, scope):
    ids = sorted((payload["source_id"], payload["target_id"]))
    warehouses = {
        item.id: item.name
        for item in db.session.scalars(
            _active(Warehouse, scope).where(Warehouse.id.in_(ids)).order_by(Warehouse.id).with_for_update()
        )
    }
    if warehouses != {payload["source_id"]: payload["source"], payload["target_id"]: payload["target"]}:
        raise TransferValidationError("تغيّر المستودع بعد المعاينة. أنشئ طلب نقل جديدًا.")
    product = db.session.scalar(
        _active(Product, scope).where(Product.id == payload["product_id"]).with_for_update()
    )
    quantity = Decimal(payload["quantity"])
    if product is None or product.name != payload["product"]:
        raise TransferValidationError("تغيّر الصنف بعد المعاينة. أنشئ طلب نقل جديدًا.")
    if quantity > _available(scope, payload["source_id"], product.id):
        raise TransferValidationError("الكمية المتاحة في المستودع المصدر تغيّرت بعد المعاينة.")
    transfer = StockTransferService.create_transfer(
        from_warehouse_id=payload["source_id"], to_warehouse_id=payload["target_id"],
        lines_data=[{"product_id": product.id, "quantity": quantity}], user_id=user.id,
    )
    if transfer.tenant_id != scope or transfer.status != "pending":
        raise TransferValidationError("تعذّر حفظ طلب النقل ضمن الشركة الحالية.")
    return transfer
