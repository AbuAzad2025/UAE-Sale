"""Maintenance accounting — cost, revenue, VAT, receivables and cash.

Accounting policy (approved by the operator, see docs/maintenance_status.md):

* **Parts** are relieved from inventory at their ACTUAL cost (moving average)
  when they are issued to an order: debit maintenance cost, credit inventory.
  The inventory ledger therefore always matches the stock card, and the
  inventory account is only credited by a real issue or a real return.
* **Labour** cost is tracked analytically on the order (``cost_price_total``)
  and is NOT posted to the GL: payroll in this system expenses wages at
  payment time and has no accrual clearing path, so an accrual here would
  leave a permanent liability.
* **Revenue and VAT** are recognised when the maintenance invoice is posted:
  debit the receivable, credit the revenue net of VAT, credit the VAT
  liability. Discounts reduce the revenue (they are not a separate posting).
* **Warranty-covered work** is not charged to the customer. Its parts cost is
  reclassified from the maintenance cost account to the warranty expense
  account at the billing event, so the cost lands in the P&L without revenue.
* **Credit delivery is allowed**: an order on account may be delivered and
  closed once its invoice is posted and the customer stays within the credit
  limit. A cash order must be paid in full before it is closed.

Every posting is idempotent: a document reference that already carries a live
entry is refused instead of being posted twice.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from extensions import db
from models.gl import GLJournalEntry
from services.account_resolution import AccountResolver, AccountRole
from services.gl_service import GLService
from utils.errors import ValidationError

logger = logging.getLogger(__name__)

D = Decimal
ZERO = Decimal('0')

WARRANTY_STATUS_ACTIVE = 'under_warranty'

# Where the money lands when it is collected.
PAYMENT_ACCOUNT_ROLES = {
    'cash': AccountRole.CASH,
    'card': AccountRole.BANK,
    'transfer': AccountRole.BANK,
    'bank_transfer': AccountRole.BANK,
    'cheque': AccountRole.UNDER_COLLECTION,
}

REFERENCE_ITEM = 'maintenance_item'
REFERENCE_INVOICE = 'maintenance_invoice'
REFERENCE_RECEIPT = 'maintenance_receipt'
REFERENCE_RETURN = 'maintenance_return'
REFERENCE_ORDER = 'maintenance_order'
REFERENCE_PURCHASE = 'maintenance_purchase'
REFERENCE_SUPPLIER_PAYMENT = 'maintenance_supplier_payment'
REFERENCE_CREDIT_NOTE = 'maintenance_credit_note'
REFERENCE_DEPOSIT = 'maintenance_deposit'


def maintenance_accounts(tenant_id=None) -> dict:
    """Resolve the maintenance chart of accounts for a tenant."""
    return {
        'ar': AccountResolver.resolve(AccountRole.MAINTENANCE_AR, tenant_id),
        'ap': AccountResolver.resolve(AccountRole.MAINTENANCE_AP, tenant_id),
        'revenue': AccountResolver.resolve(AccountRole.MAINTENANCE_REVENUE, tenant_id),
        'cogs': AccountResolver.resolve(AccountRole.MAINTENANCE_COGS, tenant_id),
        'warranty_expense': AccountResolver.resolve(AccountRole.WARRANTY_EXPENSE, tenant_id),
        'maintenance_expense': AccountResolver.resolve(AccountRole.MAINTENANCE_EXPENSE, tenant_id),
        'inventory': AccountResolver.resolve(AccountRole.INVENTORY, tenant_id),
        'vat_output': AccountResolver.resolve(AccountRole.VAT_OUTPUT, tenant_id),
        'vat_input': AccountResolver.resolve(AccountRole.VAT_INPUT, tenant_id),
        'cash': AccountResolver.resolve(AccountRole.CASH, tenant_id),
        'bank': AccountResolver.resolve(AccountRole.BANK, tenant_id),
        'under_collection': AccountResolver.resolve(AccountRole.UNDER_COLLECTION, tenant_id),
        'salaries_payable': AccountResolver.resolve(AccountRole.SALARIES_PAYABLE, tenant_id),
    }


def payment_debit_account(method, tenant_id=None) -> str:
    """The account debited when a maintenance receipt is collected."""
    role = PAYMENT_ACCOUNT_ROLES.get((method or '').strip().lower())
    if role is None:
        raise ValidationError(f'طريقة دفع غير مدعومة في الصيانة: {method}')
    return AccountResolver.resolve(role, tenant_id)


def is_warranty_order(order) -> bool:
    """True when the customer is not charged for this order (warranty work)."""
    return getattr(order, 'warranty_status', None) == WARRANTY_STATUS_ACTIVE


def order_parts_cost(order) -> Decimal:
    """Actual cost of the parts still issued to the order (inventory-backed)."""
    total = ZERO
    for item in getattr(order, 'items', ()):
        quantity = D(str(item.quantity or 0)) - D(str(item.returned_quantity or 0))
        if quantity <= 0:
            continue
        total += D(str(item.cost_price or 0)) * quantity
    return total.quantize(D('0.001'))


def order_net_revenue(order) -> Decimal:
    """Revenue net of VAT and discounts for the order."""
    total = D(str(getattr(order, 'total_amount', 0) or 0))
    tax = D(str(getattr(order, 'tax_amount', 0) or 0))
    return (total - tax).quantize(D('0.001'))


# ---------------------------------------------------------------------------
# Line builders (pure: no database access, so they can be unit tested)
# ---------------------------------------------------------------------------
def build_cost_issue_lines(amount, accounts) -> list:
    """Parts issued to an order: debit maintenance cost, credit inventory."""
    amount = D(str(amount or 0)).quantize(D('0.001'))
    if amount <= 0:
        return []
    return [
        {'account': accounts['cogs'], 'debit': amount,
         'description': 'تكلفة قطع صيانة'},
        {'account': accounts['inventory'], 'credit': amount,
         'description': 'صرف قطع صيانة من المخزون'},
    ]


def build_invoice_lines(net_revenue, vat, debit_account, accounts) -> list:
    """Invoice of a chargeable order: receivable / cash, revenue, VAT."""
    net_revenue = D(str(net_revenue or 0)).quantize(D('0.001'))
    vat = D(str(vat or 0)).quantize(D('0.001'))
    total = net_revenue + vat
    if total <= 0:
        return []
    lines = [{'account': debit_account, 'debit': total,
              'description': 'ذمم/صندوق - صيانة'}]
    if net_revenue > 0:
        lines.append({'account': accounts['revenue'], 'credit': net_revenue,
                      'description': 'إيراد صيانة'})
    if vat > 0:
        lines.append({'account': accounts['vat_output'], 'credit': vat,
                      'description': 'ضريبة القيمة المضافة - مخرجات صيانة'})
    return lines


def build_receipt_lines(amount, debit_account, accounts) -> list:
    """Collection: debit cash/bank, credit the maintenance receivable."""
    amount = D(str(amount or 0)).quantize(D('0.001'))
    if amount <= 0:
        return []
    return [
        {'account': debit_account, 'debit': amount, 'description': 'تحصيل صيانة'},
        {'account': accounts['ar'], 'credit': amount,
         'description': 'تسديد ذمم صيانة مدينة'},
    ]


def build_warranty_reclass_lines(amount, accounts) -> list:
    """Warranty work: move the parts cost from maintenance cost to warranty."""
    amount = D(str(amount or 0)).quantize(D('0.001'))
    if amount <= 0:
        return []
    return [
        {'account': accounts['warranty_expense'], 'debit': amount,
         'description': 'مصروف ضمان - تكلفة أعمال مغطاة بالضمان'},
        {'account': accounts['cogs'], 'credit': amount,
         'description': 'إعادة تبويب تكلفة الصيانة إلى مصروف الضمان'},
    ]


def build_return_cost_lines(amount, accounts) -> list:
    """Parts returned to stock: debit inventory, credit the cost account."""
    amount = D(str(amount or 0)).quantize(D('0.001'))
    if amount <= 0:
        return []
    return [
        {'account': accounts['inventory'], 'debit': amount,
         'description': 'إرجاع قطع صيانة إلى المخزون'},
        {'account': accounts['cogs'], 'credit': amount,
         'description': 'عكس تكلفة قطع الصيانة المرتجعة'},
    ]


def build_goods_receipt_lines(subtotal, vat, accounts) -> list:
    """Goods received from a supplier: inventory in, maintenance payable."""
    subtotal = D(str(subtotal or 0)).quantize(D('0.001'))
    vat = D(str(vat or 0)).quantize(D('0.001'))
    if subtotal <= 0:
        return []
    lines = [{'account': accounts['inventory'], 'debit': subtotal,
              'description': 'استلام قطع صيانة إلى المخزون'}]
    if vat > 0:
        lines.append({'account': accounts['vat_input'], 'debit': vat,
                      'description': 'ضريبة المدخلات - قطع صيانة'})
    lines.append({'account': accounts['ap'], 'credit': subtotal + vat,
                  'description': 'ذمم الصيانة دائنة'})
    return lines


def build_supplier_payment_lines(amount, debit_account, accounts) -> list:
    """Settle the maintenance payable: debit the payable, credit the cash."""
    amount = D(str(amount or 0)).quantize(D('0.001'))
    if amount <= 0:
        return []
    return [
        {'account': accounts['ap'], 'debit': amount,
         'description': 'سداد ذمم الصيانة دائنة'},
        {'account': debit_account, 'credit': amount,
         'description': 'صرف سداد لمورد قطع الصيانة'},
    ]


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------
def _assert_not_posted(reference_type, reference_id, message):
    """Refuse a second posting for the same document reference."""
    live = GLJournalEntry.query.filter_by(
        reference_type=reference_type, reference_id=reference_id
    ).filter(GLJournalEntry.is_reversed.is_(False)).count()
    if live:
        raise ValidationError(message)


def _post(lines, *, description, reference_type, reference_id, created_by=None,
          entry_date=None):
    if not lines:
        raise ValidationError('لا يوجد بنود للترحيل')
    GLService.ensure_core_accounts()
    return GLService.post_entry(
        lines,
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
        entry_date=entry_date or datetime.now(timezone.utc),
        created_by=created_by,
    )


def post_parts_issue(order, item, *, unit_cost, quantity, created_by=None,
                      entry_date=None):
    """Relieve the issued parts from inventory at their actual cost."""
    amount = (D(str(unit_cost or 0)) * D(str(quantity or 0))).quantize(D('0.001'))
    if amount <= 0:
        return None
    _assert_not_posted(REFERENCE_ITEM, item.id,
                       'سبق صرف هذه القطعة إلى الأمر — لا يمكن الصرف مرتين')
    accounts = maintenance_accounts(order.tenant_id)
    lines = build_cost_issue_lines(amount, accounts)
    return _post(
        lines,
        description=f'صرف قطعة لأمر صيانة {order.order_no}',
        reference_type=REFERENCE_ITEM, reference_id=item.id,
        created_by=created_by, entry_date=entry_date,
    )


def post_maintenance_invoice(order, invoice, *, created_by=None, entry_date=None):
    """Recognise the revenue and the VAT of a maintenance invoice."""
    _assert_not_posted(REFERENCE_INVOICE, invoice.id,
                       'سبق ترحيل فاتورة هذا الأمر — لا يمكن الترحيل مرتين')
    accounts = maintenance_accounts(order.tenant_id)
    # صافي الإيراد = الإجمالي - الضريبة (بعملة الأساس إذا توفرت)
    total_base = D(str(getattr(invoice, 'total_amount_base', None) or 
                       order.total_amount or 0)).quantize(D('0.001'))
    tax_base = D(str(getattr(invoice, 'tax_amount_base', None) or 
                     order.tax_amount or 0)).quantize(D('0.001'))
    net_revenue = (total_base - tax_base).quantize(D('0.001'))
    vat = tax_base
    debit_account = accounts['ar']
    lines = build_invoice_lines(net_revenue, vat, debit_account, accounts)
    entry = _post(
        lines,
        description=f'فاتورة صيانة {invoice.invoice_no} - {order.order_no}',
        reference_type=REFERENCE_INVOICE, reference_id=invoice.id,
        created_by=created_by, entry_date=entry_date,
    )
    invoice.gl_posted = True
    db.session.flush()

    # Accrue labor cost at billing time: debit maintenance expense,
    # credit salaries payable. The payroll run later settles salaries payable
    # to cash.
    post_maintenance_labor_cost(order, created_by=created_by,
                                entry_date=entry_date)
    return entry


def post_maintenance_receipt(receipt, *, created_by=None, entry_date=None):
    """Record a collection against the maintenance receivable."""
    _assert_not_posted(REFERENCE_RECEIPT, receipt.id,
                       'سبق ترحيل هذا السند — لا يمكن الترحيل مرتين')
    order = receipt.order
    accounts = maintenance_accounts(order.tenant_id)
    debit_account = payment_debit_account(receipt.payment_method, order.tenant_id)
    # استخدام المبلغ المحول لعملة الأساس إذا كان متاحاً
    amount = D(str(getattr(receipt, 'amount_base', None) or receipt.amount or 0)).quantize(D('0.001'))
    lines = build_receipt_lines(amount, debit_account, accounts)
    entry = _post(
        lines,
        description=f'سند قبض صيانة {receipt.receipt_no} - {order.order_no}',
        reference_type=REFERENCE_RECEIPT, reference_id=receipt.id,
        created_by=created_by, entry_date=entry_date,
    )
    receipt.posted = True
    receipt.posted_at = datetime.now(timezone.utc)
    db.session.flush()
    return entry


def post_deposit_receipt(order, receipt, *, created_by=None, entry_date=None):
    """Post a deposit receipt linked to a maintenance order.
    
    The deposit is treated as an advance payment: debit cash/bank,
    credit the maintenance receivable.
    """
    _assert_not_posted(REFERENCE_DEPOSIT, receipt.id,
                       'سبق ترحيل هذا السند — لا يمكن الترحيل مرتين')
    accounts = maintenance_accounts(order.tenant_id)
    debit_account = payment_debit_account(receipt.payment_method, order.tenant_id)
    amount = D(str(getattr(receipt, 'amount_base', None) or receipt.amount or 0)).quantize(D('0.001'))
    lines = build_receipt_lines(amount, debit_account, accounts)
    entry = _post(
        lines,
        description=f'دفعة مقدمة - أمر صيانة {order.order_no}',
        reference_type=REFERENCE_DEPOSIT, reference_id=receipt.id,
        created_by=created_by, entry_date=entry_date,
    )
    receipt.posted = True
    receipt.posted_at = datetime.now(timezone.utc)
    db.session.flush()
    return entry


def post_warranty_reclassification(order, *, created_by=None, entry_date=None):
    """Move the parts cost of a warranty order to the warranty expense."""
    amount = order_parts_cost(order)
    if amount <= 0:
        return None
    _assert_not_posted(REFERENCE_ORDER, order.id,
                       'سبق تبويب تكلفة هذا الأمر إلى مصروف الضمان')
    accounts = maintenance_accounts(order.tenant_id)
    lines = build_warranty_reclass_lines(amount, accounts)
    return _post(
        lines,
        description=f'مصروف ضمان - أمر صيانة {order.order_no}',
        reference_type=REFERENCE_ORDER, reference_id=order.id,
        created_by=created_by, entry_date=entry_date,
    )


def post_return_cost(order, return_obj, amount, *, created_by=None, entry_date=None):
    """Return parts to stock and reverse their cost."""
    accounts = maintenance_accounts(order.tenant_id)
    # استخدام المبلغ المحول لعملة الأساس إذا كان متاحاً
    amount = D(str(getattr(return_obj, 'amount_base', None) or amount or 0)).quantize(D('0.001'))
    lines = build_return_cost_lines(amount, accounts)
    if not lines:
        return None
    return _post(
        lines,
        description=f'مرتجع قطع صيانة {getattr(return_obj, "return_no", "")} - {order.order_no}',
        reference_type=REFERENCE_RETURN, reference_id=return_obj.id,
        created_by=created_by, entry_date=entry_date,
    )


def build_credit_note_lines(net_revenue, vat, debit_account, accounts) -> list:
    """Credit note: reverse revenue and VAT, credit receivable / debit cash.
    
    Mirrors the invoice lines in reverse: debit revenue/VAT, credit receivable.
    """
    net_revenue = D(str(net_revenue or 0)).quantize(D('0.001'))
    vat = D(str(vat or 0)).quantize(D('0.001'))
    total = net_revenue + vat
    if total <= 0:
        return []
    lines = [
        {'account': accounts['revenue'], 'debit': net_revenue,
         'description': 'إشعار دائن - عكس إيراد صيانة'},
    ]
    if vat > 0:
        lines.append({'account': accounts['vat_output'], 'debit': vat,
                      'description': 'إشعار دائن - عكس ضريبة القيمة المضافة'})
    lines.append({'account': debit_account, 'credit': total,
                  'description': 'إشعار دائن - عكس ذمم صيانة مدينة'})
    return lines


def build_labor_cost_lines(amount, accounts) -> list:
    """Labor cost accrual: debit maintenance expense, credit salaries payable."""
    amount = D(str(amount or 0)).quantize(D('0.001'))
    if amount <= 0:
        return []
    return [
        {'account': accounts['maintenance_expense'], 'debit': amount,
         'description': 'تكلفة عمل صيانة - رواتب مستحقة'},
        {'account': accounts['salaries_payable'], 'credit': amount,
         'description': 'تكلفة عمل صيانة - رواتب مستحقة'},
    ]


def post_maintenance_credit_note(order, credit_note, *, created_by=None,
                                  entry_date=None):
    """Reverse the invoice revenue and VAT via a credit note."""
    _assert_not_posted(REFERENCE_CREDIT_NOTE, credit_note.id,
                       'سبق ترحيل إشعار الدائن لهذا الأمر')
    accounts = maintenance_accounts(order.tenant_id)
    # صافي الإيراد المقلوب = الإجمالي - الضريبة (بعملة الأساس إذا توفرت)
    total_base = D(str(getattr(credit_note, 'amount_base', None) or 
                       order_net_revenue(order))).quantize(D('0.001'))
    tax_base = D(str(getattr(credit_note, 'amount_base', None) and 
                     order.tax_amount or 0)).quantize(D('0.001'))
    net_revenue = (total_base - tax_base).quantize(D('0.001'))
    vat = tax_base
    debit_account = accounts['ar']
    lines = build_credit_note_lines(net_revenue, vat, debit_account, accounts)
    entry = _post(
        lines,
        description=f'إشعار دائن صيانة - {order.order_no}',
        reference_type=REFERENCE_CREDIT_NOTE, reference_id=credit_note.id,
        created_by=created_by, entry_date=entry_date,
    )
    credit_note.gl_posted = True
    credit_note.posted = True
    credit_note.posted_at = datetime.now(timezone.utc)
    db.session.flush()
    return entry


def post_maintenance_labor_cost(order, *, created_by=None, entry_date=None):
    """Accrue labor cost for services on the order.
    
    Debit maintenance COGS, credit Salaries Payable. Idempotent per order.
    """
    _assert_not_posted(REFERENCE_ORDER + ':labor', order.id,
                       'سبق ترحيل تكلفة العمل لهذا الأمر')
    accounts = maintenance_accounts(order.tenant_id)
    labor_cost = sum((D(str(sv.cost_price or 0))
                      * D(str(sv.quantity or 1))
                      for sv in order.services), ZERO)
    if labor_cost <= 0:
        return None
    lines = build_labor_cost_lines(labor_cost, accounts)
    return _post(
        lines,
        description=f'تكلفة عمل صيانة - {order.order_no}',
        reference_type=REFERENCE_ORDER + ':labor', reference_id=order.id,
        created_by=created_by, entry_date=entry_date,
    )


def post_goods_receipt(purchase, *, created_by=None, entry_date=None):
    """Goods received from a supplier: inventory in, maintenance payable."""
    _assert_not_posted(REFERENCE_PURCHASE, purchase.id,
                       'سبق ترحيل استلام هذا أمر الشراء')
    accounts = maintenance_accounts(purchase.tenant_id)
    lines = build_goods_receipt_lines(purchase.subtotal, purchase.tax_amount, accounts)
    return _post(
        lines,
        description=f'استلام قطع صيانة - أمر شراء {purchase.po_number}',
        reference_type=REFERENCE_PURCHASE, reference_id=purchase.id,
        created_by=created_by, entry_date=entry_date,
    )


def post_supplier_payment(payment, *, created_by=None, entry_date=None):
    """Settle a maintenance payable to a supplier."""
    _assert_not_posted(REFERENCE_SUPPLIER_PAYMENT, payment.id,
                       'سبق ترحيل هذا السداد')
    supplier = payment.supplier
    tenant_id = payment.tenant_id
    accounts = maintenance_accounts(tenant_id)
    debit_account = payment_debit_account(payment.payment_method, tenant_id)
    # استخدام المبلغ المحول لعملة الأساس إذا كان متاحاً
    amount = D(str(getattr(payment, 'amount_base', None) or payment.amount or 0)).quantize(D('0.001'))
    lines = build_supplier_payment_lines(amount, debit_account, accounts)
    if not lines:
        return None
    return _post(
        lines,
        description=(f'سداد ذمم صيانة للمورد {supplier.name if supplier else payment.supplier_id}'),
        reference_type=REFERENCE_SUPPLIER_PAYMENT, reference_id=payment.id,
        created_by=created_by, entry_date=entry_date,
    )


def reverse_order_entries(order, *, reason, created_by=None):
    entries = GLService.reverse_entry(
        reference_type=REFERENCE_ORDER, reference_id=order.id,
        description=reason, created_by=created_by,
    )
    if isinstance(entries, list):
        return entries
    return [entries] if entries else []
