from .user import User, Role, Permission
from .customer import Customer
from .supplier import Supplier
from .cheque import Cheque
from .product import Product, ProductCategory, ProductPartner
from .warehouse import Warehouse, StockMovement
from .sale import Sale, SaleLine
from .purchase import Purchase, PurchaseLine
from .payment import Payment, Receipt
from .currency import Currency, ExchangeRate
from .audit import AuditLog
from .assistant_action import AssistantAction
from . import bot_event
from .archive import ArchivedRecord
from .product_return import ProductReturn, ProductReturnLine
from .card_vault import CardVault
from .gl import GLAccount, GLJournalEntry, GLJournalLine
from .expense import Expense, ExpenseCategory
from .invoice_settings import InvoiceSettings
from .tenant import Tenant
from .system_settings import SystemSettings
from .integration_settings import IntegrationSettings
from .tax_ruleset import TaxRuleset, seed_default_rulesets, ruleset_for_tenant
from .compliance_credential import ComplianceCredential
from .support_ticket import SupportTicket
from .incident import Incident
from .backup_verification import BackupVerification
from .donation import Donation
from .payment_vault import PaymentVault, PaymentTransaction, PaymentLog
from .card_payment import CardPayment
from .bank_reconciliation import BankReconciliation, BankReconciliationItem
from .budget import Budget, BudgetLine
from .cost_center import CostCenter
from .fixed_asset import FixedAsset, DepreciationSchedule
from .advanced_accounting import CustomsTax, AdvancedExpense, TaxCalculationRule
from .login_history import LoginHistory
from .security_alert import SecurityAlert
from .api_key import APIKey
from .approval_workflow import ApprovalWorkflow, ApprovalRequest, ApprovalLevel
from .journal_entry_audit import JournalEntryAudit
from .error_log import ErrorLog
from .write_off import WriteOff
from .shipment import Shipment, ShipmentLine
from .inbound_shipment import InboundShipment, InboundShipmentLine
from .tenant_scope import (  # noqa: F401
    TenantScopedMixin,
    set_current_tenant_id,
    get_current_tenant_id,
    clear_current_tenant_id,
    register_tenant_scoped,
    install_tenant_filter_events,
    install_builtin_tenant_scoping,
    install_tenant_loader_criteria,
    run_in_tenant_context,
    run_in_platform_context,
)
from .hr import (
    Department,
    Employee,
    LeaveType,
    LeaveRequest,
    Payslip,
    PayslipLine,
)
from .erp_modules import (
    Quotation,
    QuotationLine,
    PurchaseOrder,
    PurchaseOrderLine,
    FiscalPeriod,
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
)
from .maintenance import (
    MaintenanceOrder,
    MaintenanceOrderItem,
    MaintenanceOrderService,
    MaintenanceOrderStatusLog,
    MaintenanceReceipt,
    MaintenanceInvoice,
    MaintenanceReturn,
    MaintenanceReturnLine,
    MaintenanceSetting,
    MaintenanceService,
    MaintenanceWarrantyAudit,
    MaintenanceDeviceRegistry,
    MaintenanceSupplierPayment,
    MaintenanceCreditNote,
)
from .validators import (
    single_parent_validator,
    direction_fk_validator,
    tenant_consistency_validator,
)

for _model_cls in [
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
    InvoiceSettings,
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
    ProductReturn,
    ProductReturnLine,
    # Tenant-scoped models that were missing from registration (data-leak fix).
    # Role/TaxRuleset/FiscalPeriod carry global (tenant_id=NULL) rows that
    # must stay visible to every tenant; tenant_scope handles those with a
    # (tenant_id == current OR IS NULL) load criterion.
    SupportTicket,
    ComplianceCredential,
    TaxRuleset,
    FiscalPeriod,
    Role,
    # Maintenance tables that carry an explicit tenant_id.
    MaintenanceOrder,
    MaintenanceSetting,
    MaintenanceService,
    MaintenanceWarrantyAudit,
    MaintenanceSupplierPayment,
    MaintenanceDeviceRegistry,
    # Maintenance child tables (now carry tenant_id backfilled from order).
    MaintenanceOrderItem,
    MaintenanceOrderService,
    MaintenanceOrderStatusLog,
    MaintenanceReceipt,
    MaintenanceInvoice,
    MaintenanceReturn,
    MaintenanceReturnLine,
    MaintenanceCreditNote,
]:
    register_tenant_scoped(_model_cls)

__all__ = [
    "User",
    "Role",
    "Permission",
    "Customer",
    "Supplier",
    "Cheque",
    "Product",
    "ProductCategory",
    "ProductPartner",
    "Warehouse",
    "StockMovement",
    "Sale",
    "SaleLine",
    "Purchase",
    "PurchaseLine",
    "Payment",
    "Receipt",
    "Currency",
    "ExchangeRate",
    "AuditLog",
    "AssistantAction",
    "ArchivedRecord",
    "ProductReturn",
    "ProductReturnLine",
    "CardVault",
    "GLAccount",
    "GLJournalEntry",
    "GLJournalLine",
    "Expense",
    "ExpenseCategory",
    "InvoiceSettings",
    "Tenant",
    "SystemSettings",
    "TaxRuleset",
    "seed_default_rulesets",
    "ruleset_for_tenant",
    "ComplianceCredential",
    "SupportTicket",
    "Incident",
    "BackupVerification",
    "IntegrationSettings",
    "Donation",
    "CardPayment",
    "PaymentVault",
    "PaymentTransaction",
    "PaymentLog",
    "BankReconciliation",
    "BankReconciliationItem",
    "Budget",
    "BudgetLine",
    "CostCenter",
    "FixedAsset",
    "DepreciationSchedule",
    "CustomsTax",
    "AdvancedExpense",
    "TaxCalculationRule",
    "LoginHistory",
    "SecurityAlert",
    "APIKey",
    "ApprovalWorkflow",
    "ApprovalRequest",
    "ApprovalLevel",
    "JournalEntryAudit",
    "ErrorLog",
    "WriteOff",
    "Shipment",
    "ShipmentLine",
    "InboundShipment",
    "InboundShipmentLine",
    "Department",
    "Employee",
    "LeaveType",
    "LeaveRequest",
    "Payslip",
    "PayslipLine",
    "Quotation",
    "QuotationLine",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "FiscalPeriod",
    "StockTransfer",
    "StockTransferLine",
    "StockTake",
    "StockTakeItem",
    "DunningLetter",
    "RecurringExpense",
    "ProductLot",
    "WarehouseBin",
    "ProductBin",
    "EInvoice",
    "MaintenanceService",
    "MaintenanceWarrantyAudit",
    "MaintenanceDeviceRegistry",
    "MaintenanceSetting",
    "MaintenanceOrder",
    "MaintenanceOrderItem",
    "MaintenanceOrderService",
    "MaintenanceOrderStatusLog",
    "MaintenanceReceipt",
    "MaintenanceInvoice",
    "MaintenanceReturn",
    "MaintenanceReturnLine",
    "single_parent_validator",
    "direction_fk_validator",
    "tenant_consistency_validator",
]
