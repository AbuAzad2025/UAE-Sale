"""
InboundShipmentService — استقبال وفحص وإدخال شحنات البضائع الواردة

Trusted: StockMovement + TenantScopedMixin + PurchaseOrder receive pattern.
Only put_away moves stock (C1: no GL until sale).
"""

from datetime import datetime, timezone, date
from decimal import Decimal

from extensions import db
from models.inbound_shipment import InboundShipment, InboundShipmentLine
from utils.helpers import generate_number


def _gen_number():
    try:
        return generate_number('INB', InboundShipment, 'shipment_number')
    except Exception:
        return f"INB-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


class InboundShipmentService:

    @staticmethod
    def create_shipment(*, warehouse_id, supplier_id=None, purchase_order_id=None,
                        carrier=None, tracking_number=None, expected_at=None,
                        tenant_id=None, created_by_id=None, assigned_to_id=None,
                        lines_data=None, notes=None):
        if not warehouse_id:
            raise ValueError('warehouse_id (المستودع المستقبل) مطلوب')
        if not lines_data:
            raise ValueError('يجب إضافة منتج واحد على الأقل')
        sh = InboundShipment(
            shipment_number=_gen_number(),
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
            carrier=carrier,
            tracking_number=tracking_number,
            expected_at=expected_at,
            status='in_transit',
            notes=notes,
            created_by_id=created_by_id,
            assigned_to_id=assigned_to_id,
        )
        db.session.add(sh)
        db.session.flush()
        for row in lines_data:
            pid = row.get('product_id')
            qty = Decimal(str(row.get('quantity_expected', row.get('quantity', 0))))
            if not pid or qty <= 0:
                raise ValueError('كل بند يحتاج product_id و quantity_expected > 0')
            cost = Decimal(str(row.get('unit_cost', 0) or 0))
            line = InboundShipmentLine(
                inbound_shipment_id=sh.id,
                product_id=int(pid),
                quantity_expected=qty,
                quantity_received=Decimal('0'),
                quantity_accepted=Decimal('0'),
                unit_cost=cost,
                warehouse_bin_id=row.get('warehouse_bin_id'),
                lot_id=row.get('lot_id'),
            )
            line.calculate_line_total()
            db.session.add(line)
        db.session.flush()
        sh.calculate_totals()
        db.session.commit()
        return sh

    @staticmethod
    def arrive(shipment_id, user_id=None):
        sh = db.session.get(InboundShipment, shipment_id)
        if not sh:
            raise ValueError('الشحنة غير موجودة')
        if sh.status != 'in_transit':
            raise ValueError(f'لا يمكن تأكيد الوصول من حالة {sh.status}')
        sh.status = 'arrived'
        sh.arrived_at = datetime.now(timezone.utc)
        # copy expected to received by default
        for line in sh.lines:
            if line.quantity_received == 0:
                line.quantity_received = line.quantity_expected
        db.session.commit()
        return sh

    @staticmethod
    def inspect_shipment(shipment_id, inspection_data=None, user_id=None):
        """
        inspection_data: list of {line_id, quantity_accepted, warehouse_bin_id?, lot_id?}
        If None, accept all received.
        """
        sh = db.session.get(InboundShipment, shipment_id)
        if not sh:
            raise ValueError('الشحنة غير موجودة')
        if sh.status != 'arrived':
            raise ValueError(f'لا يمكن الفحص من حالة {sh.status}')
        if inspection_data is not None:
            for item in inspection_data:
                line = db.session.get(InboundShipmentLine, item.get('line_id'))
                if not line or line.inbound_shipment_id != sh.id:
                    raise ValueError('بند غير صالح')
                acc = Decimal(str(item.get('quantity_accepted', 0)))
                if acc < 0 or acc > line.quantity_received:
                    raise ValueError('quantity_accepted خارج النطاق')
                line.quantity_accepted = acc
                if item.get('warehouse_bin_id'):
                    line.warehouse_bin_id = int(item['warehouse_bin_id'])
                if item.get('lot_id'):
                    line.lot_id = int(item['lot_id'])
        else:
            for line in sh.lines:
                line.quantity_accepted = line.quantity_received
        sh.status = 'inspected'
        sh.inspected_at = datetime.now(timezone.utc)
        db.session.commit()
        return sh

    @staticmethod
    def put_away(shipment_id, user_id=None):
        sh = db.session.get(InboundShipment, shipment_id)
        if not sh:
            raise ValueError('الشحنة غير موجودة')
        if sh.status != 'inspected':
            raise ValueError(f'لا يمكن الإدخال من حالة {sh.status}')
        # Move stock for each accepted line
        from services.stock_service import StockService
        for line in sh.lines:
            qty = line.quantity_accepted
            if qty and qty > 0:
                try:
                    StockService.adjust_stock(
                        line.product_id, qty, notes=f'Inbound {sh.shipment_number}',
                        warehouse_id=sh.warehouse_id, post_gl=False)
                except TypeError:
                    # fallback for older signature without post_gl
                    StockService.adjust_stock(line.product_id, qty)
        # Update linked PO if any
        if sh.purchase_order_id:
            from models.erp_modules import PurchaseOrder
            po = db.session.get(PurchaseOrder, sh.purchase_order_id)
            if po:
                # naive: if all lines accepted, mark received
                total_exp = sum((l.quantity_expected for l in sh.lines), Decimal('0'))
                total_acc = sum((l.quantity_accepted for l in sh.lines), Decimal('0'))
                if total_acc >= total_exp:
                    po.status = 'received'
                elif total_acc > 0:
                    po.status = 'partially_received'
        sh.status = 'put_away'
        sh.put_away_at = datetime.now(timezone.utc)
        db.session.commit()
        return sh

    @staticmethod
    def close(shipment_id, user_id=None):
        sh = db.session.get(InboundShipment, shipment_id)
        if not sh:
            raise ValueError('الشحنة غير موجودة')
        if sh.status != 'put_away':
            raise ValueError(f'لا يمكن الإغلاق من حالة {sh.status}')
        sh.status = 'closed'
        sh.closed_at = datetime.now(timezone.utc)
        db.session.commit()
        return sh

    @staticmethod
    def cancel(shipment_id, user_id=None):
        sh = db.session.get(InboundShipment, shipment_id)
        if not sh:
            raise ValueError('الشحنة غير موجودة')
        if sh.status == 'closed':
            raise ValueError('لا يمكن إلغاء شحنة مغلقة')
        if sh.status == 'put_away':
            raise ValueError('لا يمكن إلغاء شحنة تم إدخالها — استخدم إرجاع مخزني')
        sh.status = 'cancelled'
        db.session.commit()
        return sh
