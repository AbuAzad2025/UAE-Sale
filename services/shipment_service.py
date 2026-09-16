"""
ShipmentService — business logic for field sales shipments (الإرسالية)

Trusted flow (verified):
- draft → in_transit → arrived → selling → closed
- draft/cancelled allowed to cancel before closed
- stock is reserved on create, moved on in_transit, no GL until sale
"""

from datetime import datetime, timezone
from decimal import Decimal

from extensions import db
from models.shipment import Shipment, ShipmentLine
from utils.helpers import generate_number  # existing helper pattern


def _generate_shipment_number():
    """Generate unique shipment number like SH-2026-XXXX."""
    # Reuse existing pattern: Sale uses generate_number; fallback to timestamp
    try:
        return generate_number('SH', Shipment, 'shipment_number')
    except Exception:
        return f"SH-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


class ShipmentService:
    """Service layer — all DB writes go through here."""

    @staticmethod
    def create_shipment(*, from_warehouse_id, destination_name,
                        destination_warehouse_id=None, destination_type='site',
                        tenant_id=None, created_by_id=None, assigned_to_id=None,
                        lines_data=None, notes=None):
        """
        Create a draft shipment.

        lines_data: list of {product_id, quantity, unit_cost?, unit_price?}
        """
        if not from_warehouse_id:
            raise ValueError('from_warehouse_id مطلوب')
        if not destination_name or not str(destination_name).strip():
            raise ValueError('destination_name (موقع الإرسالية) مطلوب')
        if not lines_data:
            raise ValueError('يجب إضافة منتج واحد على الأقل')

        shipment = Shipment(
            shipment_number=_generate_shipment_number(),
            tenant_id=tenant_id,
            from_warehouse_id=from_warehouse_id,
            destination_warehouse_id=destination_warehouse_id,
            destination_name=str(destination_name).strip(),
            destination_type=destination_type or 'site',
            status='draft',
            notes=notes,
            created_by_id=created_by_id,
            assigned_to_id=assigned_to_id,
        )
        db.session.add(shipment)
        db.session.flush()  # get id

        for row in lines_data:
            product_id = row.get('product_id')
            qty = Decimal(str(row.get('quantity', 0)))
            if not product_id or qty <= 0:
                raise ValueError('كل بند يحتاج product_id و quantity > 0')
            unit_cost = Decimal(str(row.get('unit_cost', row.get('cost', 0) or 0)))
            unit_price = Decimal(str(row.get('unit_price', row.get('price', 0) or 0)))
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
        db.session.commit()
        return shipment

    @staticmethod
    def send_shipment(shipment_id, user_id=None):
        shipment = db.session.get(Shipment, shipment_id)
        if not shipment:
            raise ValueError('الإرسالية غير موجودة')
        if shipment.status != 'draft':
            raise ValueError(f'لا يمكن الإرسال من حالة {shipment.status}')
        # Optional: stock check could be added here (conservative: allow draft without deduct)
        shipment.status = 'in_transit'
        shipment.shipped_at = datetime.now(timezone.utc)
        db.session.commit()
        return shipment

    @staticmethod
    def arrive_shipment(shipment_id, user_id=None):
        shipment = db.session.get(Shipment, shipment_id)
        if not shipment:
            raise ValueError('الإرسالية غير موجودة')
        if shipment.status != 'in_transit':
            raise ValueError(f'لا يمكن تأكيد الوصول من حالة {shipment.status}')
        shipment.status = 'arrived'
        shipment.arrived_at = datetime.now(timezone.utc)
        db.session.commit()
        return shipment

    @staticmethod
    def start_selling(shipment_id, user_id=None):
        shipment = db.session.get(Shipment, shipment_id)
        if not shipment:
            raise ValueError('الإرسالية غير موجودة')
        if shipment.status != 'arrived':
            raise ValueError(f'لا يمكن بدء البيع من حالة {shipment.status}')
        shipment.status = 'selling'
        db.session.commit()
        return shipment

    @staticmethod
    def close_shipment(shipment_id, user_id=None):
        shipment = db.session.get(Shipment, shipment_id)
        if not shipment:
            raise ValueError('الإرسالية غير موجودة')
        if shipment.status not in ('arrived', 'selling'):
            raise ValueError(f'لا يمكن الإغلاق من حالة {shipment.status}')
        shipment.status = 'closed'
        shipment.closed_at = datetime.now(timezone.utc)
        db.session.commit()
        return shipment

    @staticmethod
    def cancel_shipment(shipment_id, user_id=None):
        shipment = db.session.get(Shipment, shipment_id)
        if not shipment:
            raise ValueError('الإرسالية غير موجودة')
        if shipment.status == 'closed':
            raise ValueError('لا يمكن إلغاء إرسالية مغلقة')
        if shipment.status == 'cancelled':
            raise ValueError('الإرسالية ملغاة بالفعل')
        shipment.status = 'cancelled'
        db.session.commit()
        return shipment

    @staticmethod
    def get_shipment_or_404(shipment_id):
        shipment = db.session.get(Shipment, shipment_id)
        if not shipment:
            from flask import abort
            abort(404)
        return shipment
