"""
ShipmentService — business logic for field sales shipments (الإرسالية)

Trusted flow (verified):
- draft → in_transit → arrived → selling → closed
- draft/cancelled allowed to cancel before closed
- stock is deducted from the source warehouse on send (in_transit),
- restored on cancel; no GL until sale (goods remain company-owned in transit)
"""

from datetime import datetime, timezone
from decimal import Decimal

from extensions import db
from models.shipment import Shipment, ShipmentLine
from models.warehouse import StockMovement
from services.stock_service import StockService
from utils.helpers import generate_number  # existing helper pattern


def _generate_shipment_number():
    """Generate unique shipment number like SH-2026-XXXX."""
    try:
        return generate_number("SH", Shipment, "shipment_number")
    except Exception:
        return f"SH-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def _shipment_stock_movement(shipment, sign):
    """Create (or reverse) the stock movements for a shipment exactly once.

    sign = -1 on send (goods leave the warehouse), +1 on cancel (goods return).
    The reference_type/reference_id pair makes the operation idempotent.
    """
    expected_type = "shipment"
    for line in shipment.lines:
        existing = StockMovement.query.filter_by(
            reference_type=expected_type,
            reference_id=shipment.id,
            product_id=line.product_id,
            movement_type=("shipment" if sign < 0 else "shipment_return"),
        ).first()
        if existing:
            continue  # already applied — idempotent
        StockService.create_movement(
            product_id=line.product_id,
            quantity=sign * Decimal(str(line.quantity)),
            movement_type=("shipment" if sign < 0 else "shipment_return"),
            reference_type=expected_type,
            reference_id=shipment.id,
            notes=f"إرسالية {shipment.shipment_number} — {'صرف' if sign < 0 else 'إرجاع'}",
            warehouse_id=shipment.from_warehouse_id,
        )


class ShipmentService:
    """Service layer — all DB writes go through here."""

    @staticmethod
    def create_shipment(
        *,
        from_warehouse_id,
        destination_name,
        destination_warehouse_id=None,
        destination_type="site",
        tenant_id=None,
        created_by_id=None,
        assigned_to_id=None,
        lines_data=None,
        notes=None,
    ):
        """
        Create a draft shipment.

        lines_data: list of {product_id, quantity, unit_cost?, unit_price?}
        """
        if not from_warehouse_id:
            raise ValueError("from_warehouse_id مطلوب")
        if not destination_name or not str(destination_name).strip():
            raise ValueError("destination_name (موقع الإرسالية) مطلوب")
        if not lines_data:
            raise ValueError("يجب إضافة منتج واحد على الأقل")

        shipment = Shipment(
            shipment_number=_generate_shipment_number(),
            tenant_id=tenant_id,
            from_warehouse_id=from_warehouse_id,
            destination_warehouse_id=destination_warehouse_id,
            destination_name=str(destination_name).strip(),
            destination_type=destination_type or "site",
            status="draft",
            notes=notes,
            created_by_id=created_by_id,
            assigned_to_id=assigned_to_id,
        )
        db.session.add(shipment)
        db.session.flush()  # get id

        for row in lines_data:
            product_id = row.get("product_id")
            qty = Decimal(str(row.get("quantity", 0)))
            if not product_id or qty <= 0:
                raise ValueError("كل بند يحتاج product_id و quantity > 0")
            unit_cost = Decimal(str(row.get("unit_cost", row.get("cost", 0) or 0)))
            unit_price = Decimal(str(row.get("unit_price", row.get("price", 0) or 0)))
            line = ShipmentLine(
                shipment_id=shipment.id,
                product_id=int(product_id),
                quantity=qty,
                unit_cost=unit_cost,
                unit_price=unit_price,
            )
            line.calculate_line_total()
            db.session.add(line)

        db.session.flush()
        shipment.calculate_totals()
        db.session.flush()
        return shipment

    @staticmethod
    def send_shipment(shipment_id, user_id=None):
        shipment = db.session.get(Shipment, shipment_id)
        if not shipment:
            raise ValueError("الإرسالية غير موجودة")
        if shipment.status != "draft":
            raise ValueError(f"لا يمكن الإرسال من حالة {shipment.status}")
        shipment.status = "in_transit"
        shipment.shipped_at = datetime.now(timezone.utc)
        db.session.flush()
        _shipment_stock_movement(shipment, -1)  # deduct goods from source warehouse
        db.session.flush()
        return shipment

    @staticmethod
    def arrive_shipment(shipment_id, user_id=None):
        shipment = db.session.get(Shipment, shipment_id)
        if not shipment:
            raise ValueError("الإرسالية غير موجودة")
        if shipment.status != "in_transit":
            raise ValueError(f"لا يمكن تأكيد الوصول من حالة {shipment.status}")
        shipment.status = "arrived"
        shipment.arrived_at = datetime.now(timezone.utc)
        db.session.flush()
        return shipment

    @staticmethod
    def start_selling(shipment_id, user_id=None):
        shipment = db.session.get(Shipment, shipment_id)
        if not shipment:
            raise ValueError("الإرسالية غير موجودة")
        if shipment.status != "arrived":
            raise ValueError(f"لا يمكن بدء البيع من حالة {shipment.status}")
        shipment.status = "selling"
        db.session.flush()
        return shipment

    @staticmethod
    def close_shipment(shipment_id, user_id=None):
        shipment = db.session.get(Shipment, shipment_id)
        if not shipment:
            raise ValueError("الإرسالية غير موجودة")
        if shipment.status not in ("arrived", "selling"):
            raise ValueError(f"لا يمكن الإغلاق من حالة {shipment.status}")
        shipment.status = "closed"
        shipment.closed_at = datetime.now(timezone.utc)
        db.session.flush()
        return shipment

    @staticmethod
    def cancel_shipment(shipment_id, user_id=None):
        shipment = db.session.get(Shipment, shipment_id)
        if not shipment:
            raise ValueError("الإرسالية غير موجودة")
        if shipment.status == "closed":
            raise ValueError("لا يمكن إلغاء إرسالية مغلقة")
        if shipment.status == "cancelled":
            raise ValueError("الإرسالية ملغاة بالفعل")
        if shipment.status in ("in_transit", "arrived", "selling"):
            _shipment_stock_movement(shipment, 1)  # return goods to source warehouse
        shipment.status = "cancelled"
        db.session.flush()
        return shipment

    @staticmethod
    def get_shipment_or_404(shipment_id):
        shipment = db.session.get(Shipment, shipment_id)
        if not shipment:
            from flask import abort

            abort(404)
        return shipment
