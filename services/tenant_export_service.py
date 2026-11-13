"""Tenant-level data portability service.

Exports all data belonging to a single tenant (rows where tenant_id matches)
into a clean ZIP archive of CSV files (one per tenant-scoped table) or a
single JSON document. Provides on-demand data portability for tenants.

Privacy: only rows with tenant_id == target_tenant_id are exported.
Platform-level data (tenants, roles, permissions, settings) is excluded.
"""

import csv
import io
import json
import zipfile
from datetime import datetime, timezone


# Tenant-scoped model classes (must have tenant_id column)
def _tenant_scoped_models():
    """Return list of (model_class, table_name) for tenant-scoped models."""
    from models import (
        Sale,
        SaleLine,
        Purchase,
        PurchaseLine,
        Payment,
        Receipt,
        Customer,
        Supplier,
        Product,
        StockMovement,
        Cheque,
        GLJournalEntry,
        GLJournalLine,
        Warehouse,
        Shipment,
        ShipmentLine,
        InboundShipment,
        InboundShipmentLine,
        WriteOff,
        Expense,
        Department,
        Employee,
        LeaveType,
        LeaveRequest,
        Payslip,
        PayslipLine,
        Quotation,
        QuotationLine,
        PurchaseOrder,
        PurchaseOrderLine,
        StockTransfer,
        StockTransferLine,
        StockTake,
        StockTakeItem,
        DunningLetter,
        RecurringExpense,
        ProductLot,
        WarehouseBin,
        ProductBin,
        EInvoice,
        CustomsTax,
        AdvancedExpense,
        TaxCalculationRule,
        ApprovalWorkflow,
        ApprovalRequest,
        ApprovalLevel,
        BankReconciliation,
        BankReconciliationItem,
        Budget,
        BudgetLine,
        CostCenter,
        FixedAsset,
        DepreciationSchedule,
        ArchivedRecord,
        AuditLog,
        JournalEntryAudit,
        ErrorLog,
    )

    return [
        Sale,
        SaleLine,
        Purchase,
        PurchaseLine,
        Payment,
        Receipt,
        Customer,
        Supplier,
        Product,
        StockMovement,
        Cheque,
        GLJournalEntry,
        GLJournalLine,
        Warehouse,
        Shipment,
        ShipmentLine,
        InboundShipment,
        InboundShipmentLine,
        WriteOff,
        Expense,
        Department,
        Employee,
        LeaveType,
        LeaveRequest,
        Payslip,
        PayslipLine,
        Quotation,
        QuotationLine,
        PurchaseOrder,
        PurchaseOrderLine,
        StockTransfer,
        StockTransferLine,
        StockTake,
        StockTakeItem,
        DunningLetter,
        RecurringExpense,
        ProductLot,
        WarehouseBin,
        ProductBin,
        EInvoice,
        CustomsTax,
        AdvancedExpense,
        TaxCalculationRule,
        ApprovalWorkflow,
        ApprovalRequest,
        ApprovalLevel,
        BankReconciliation,
        BankReconciliationItem,
        Budget,
        BudgetLine,
        CostCenter,
        FixedAsset,
        DepreciationSchedule,
        ArchivedRecord,
        AuditLog,
        JournalEntryAudit,
        ErrorLog,
    ]


def _serialize_value(v):
    """Convert a value to a JSON/CSV-safe representation."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat()
    if hasattr(v, "as_tuple"):  # Decimal
        return str(v)
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    return v


def export_tenant_json(tenant_id):
    """Export all tenant data as a single JSON document.

    Returns: (filename, bytes)
    """
    result = {
        "tenant_id": tenant_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tables": {},
    }
    for model in _tenant_scoped_models():
        table_name = model.__tablename__
        rows = model.query.filter_by(tenant_id=tenant_id).all()
        cols = [c.name for c in model.__table__.columns]
        data = []
        for row in rows:
            data.append(
                {col: _serialize_value(getattr(row, col, None)) for col in cols}
            )
        result["tables"][table_name] = data
    filename = f"tenant_{tenant_id}_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    return filename, json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")


def export_tenant_zip(tenant_id):
    """Export all tenant data as a ZIP of CSV files (one per table).

    Returns: (filename, bytes)
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for model in _tenant_scoped_models():
            table_name = model.__tablename__
            rows = model.query.filter_by(tenant_id=tenant_id).all()
            cols = [c.name for c in model.__table__.columns]
            # Write CSV
            csv_buf = io.StringIO()
            writer = csv.writer(csv_buf)
            writer.writerow(cols)
            for row in rows:
                writer.writerow(
                    [_serialize_value(getattr(row, col, None)) for col in cols]
                )
            zf.writestr(f"{table_name}.csv", csv_buf.getvalue())

    filename = f"tenant_{tenant_id}_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip"
    return filename, buf.getvalue()


def get_tenant_export_stats(tenant_id):
    """Return row counts per table for a tenant (for preview)."""
    stats = {}
    total = 0
    for model in _tenant_scoped_models():
        count = model.query.filter_by(tenant_id=tenant_id).count()
        if count > 0:
            stats[model.__tablename__] = count
            total += count
    return stats, total
