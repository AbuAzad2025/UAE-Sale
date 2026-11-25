"""Validate and prepare one-line quotation drafts using the ERP's pricing rules."""

from decimal import Decimal
import re

from sqlalchemy import func, select

from extensions import db
from models import Currency, Customer, Product, Tenant, Warehouse
from models.erp_modules import Quotation, QuotationLine
from services.currency_service import CurrencyService
from services.erp_modules_service import QuotationService
from services.tax_engine import resolve

_REFERENCE_ID = re.compile(r"^#([0-9٠-٩]{1,9})$")
_QUANTITY = re.compile(r"^\d{1,9}(?:[.٫]\d{1,3})?$")
_MAX_MONEY = Decimal("999999999999.999")


class QuoteValidationError(ValueError):
    def __init__(self, message, entities=None):
        super().__init__(message)
        self.entities = entities or {}


def _active(model, scope):
    return select(model).where(model.tenant_id == scope, model.is_active.is_(True))


def _currency_allowed(code):
    return code == CurrencyService.get_base_currency() and db.session.scalar(
        select(Currency.id).where(Currency.code == code, Currency.is_active.is_(True))
    ) is not None


def prepare(fields, scope):
    parts = [part.strip() for part in fields.split("|")]
    if len(parts) != 5 or not all(parts):
        raise QuoteValidationError(
            "اكتب «عرض سعر: اسم العميل أو #رقمه | رمز الصنف | الكمية | رمز المستودع | العملة»."
        )
    name, sku, quantity_text, warehouse_code, currency = parts
    currency = currency.upper()
    if not _QUANTITY.fullmatch(quantity_text):
        raise QuoteValidationError("الكمية يجب أن تكون رقمًا موجبًا بثلاث منازل عشرية كحد أقصى.")
    quantity = Decimal(quantity_text.replace("٫", "."))
    if quantity <= 0:
        raise QuoteValidationError("الكمية يجب أن تكون أكبر من صفر.")
    if not _currency_allowed(currency):
        raise QuoteValidationError(
            "اختر العملة الأساسية المفعّلة للشركة، أو أنشئ العرض بعملة أخرى من نموذج النظام."
        )

    match = _REFERENCE_ID.fullmatch(name)
    customer_query = _active(Customer, scope)
    if match:
        customer_query = customer_query.where(Customer.id == int(match[1]))
    else:
        customer_query = customer_query.where(func.lower(Customer.name) == name.lower())
    customers = db.session.scalars(customer_query.order_by(Customer.id).limit(11)).all()
    if not customers:
        raise QuoteValidationError("لم أجد عميلًا نشطًا مطابقًا في نطاق الشركة.")
    if len(customers) > 1:
        identities = "، ".join(f"#{customer.id}" for customer in customers[:10])
        raise QuoteValidationError(
            f"يوجد أكثر من عميل مطابق. أعد الطلب مستخدمًا رقم العميل {identities}.",
            {"customer_ids": [customer.id for customer in customers]},
        )
    customer = customers[0]

    product = db.session.scalar(_active(Product, scope).where(Product.sku == sku))
    if product is None:
        raise QuoteValidationError("لم أجد صنفًا نشطًا بهذا الرمز في نطاق الشركة.")
    warehouse = db.session.scalar(_active(Warehouse, scope).where(Warehouse.code == warehouse_code))
    if warehouse is None:
        raise QuoteValidationError("لم أجد مستودعًا نشطًا بهذا الرمز في نطاق الشركة.")

    unit_price = Decimal(str(product.get_price_for_customer(customer.customer_type) or 0))
    if unit_price <= 0 or quantity * unit_price > _MAX_MONEY:
        raise QuoteValidationError("راجع سعر الصنف والكمية في نموذج عروض الأسعار.")
    tenant = db.session.get(Tenant, scope) if scope is not None else None
    tax_rate, tax_inclusive = resolve(tenant)
    treatment = (product.tax_treatment or "standard").strip().lower()
    if treatment not in ("standard", "zero", "exempt"):
        treatment = "standard"

    line = QuotationLine(quantity=quantity, unit_price=unit_price, tax_treatment=treatment)
    line.calculate_line_total()
    preview = Quotation(
        currency=currency, exchange_rate=1, tax_rate=tax_rate,
        tax_inclusive=tax_inclusive, lines=[line],
    )
    preview.calculate_totals()
    if preview.total_amount > _MAX_MONEY:
        raise QuoteValidationError("قيمة عرض السعر تتجاوز الحد المسموح.")

    payload = {
        "customer_id": customer.id,
        "product_id": product.id,
        "warehouse_id": warehouse.id,
        "currency": currency,
        "quantity": str(quantity),
        "unit_price": str(unit_price),
        "tax_rate": str(tax_rate),
        "tax_inclusive": tax_inclusive,
        "tax_treatment": treatment,
        "total": str(preview.total_amount),
    }
    response = (
        f"معاينة مسودة عرض سعر\nالعميل: {customer.name}\n"
        f"الصنف: {product.name} ({sku})\nالمستودع: {warehouse.name} ({warehouse_code})\n"
        f"الكمية: {quantity:g}\nسعر الوحدة: {unit_price:,.3f} {currency}\n"
        f"الضريبة: {preview.tax_amount:,.3f} {currency}\n"
        f"الإجمالي: {preview.total_amount:,.3f} {currency}\n"
        "يحفظ التأكيد عرض السعر كمسودة من دون حركة مخزون أو قيد مالي."
    )
    return payload, response


def create_draft(payload, user, scope):
    entities = (
        (Customer, payload["customer_id"]),
        (Product, payload["product_id"]),
        (Warehouse, payload["warehouse_id"]),
    )
    for model, record_id in entities:
        record = db.session.scalar(
            _active(model, scope).where(model.id == record_id).with_for_update()
        )
        if record is None:
            raise QuoteValidationError("تغيّر أحد عناصر العرض. أرسل طلبًا جديدًا للمراجعة.")
    currency = payload["currency"]
    if not _currency_allowed(currency):
        raise QuoteValidationError("تغيّرت العملة المعتمدة. أرسل طلبًا جديدًا للمراجعة.")

    quote = QuotationService.create_quotation(
        customer_id=payload["customer_id"],
        seller_id=user.id,
        warehouse_id=payload["warehouse_id"],
        currency=currency,
        user_exchange_rate=1,
        tax_rate=Decimal(payload["tax_rate"]),
        tax_inclusive=payload["tax_inclusive"],
        lines_data=[{
            "product_id": payload["product_id"],
            "quantity": Decimal(payload["quantity"]),
            "unit_price": Decimal(payload["unit_price"]),
            "tax_treatment": payload["tax_treatment"],
        }],
    )
    if quote.tenant_id != scope or quote.total_amount != Decimal(payload["total"]):
        raise QuoteValidationError("تعذّر حفظ العرض بالقيم التي تمت مراجعتها.")
    return quote
