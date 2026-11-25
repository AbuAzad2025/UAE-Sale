"""Deterministic collection and validation for assistant purchase order drafts."""

from datetime import date
from decimal import Decimal
import re

from sqlalchemy import func, or_, select

from extensions import db
from models import Currency, Product, Supplier, Tenant, Warehouse
from models.erp_modules import PurchaseOrder, PurchaseOrderLine
from services.currency_service import CurrencyService
from services.erp_modules_service import PurchaseOrderService
from services.tax_engine import resolve

STEPS = {
    "po_supplier": "اكتب اسم المورد أو رقمه مسبوقًا بـ #.",
    "po_warehouse": "اكتب رمز المستودع الذي سيستلم الأصناف.",
    "po_lines": "أدخل كل صنف في سطر بصيغة «رمز الصنف | الكمية | تكلفة الوحدة».",
    "po_delivery": "أدخل تاريخ التسليم بصيغة YYYY-MM-DD، أو اكتب «تخطي».",
}
_ID = re.compile(r"^#([0-9٠-٩]{1,9})$")
_NUMBER = re.compile(r"^\d{1,9}(?:[.٫]\d{1,3})?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_AMOUNT = Decimal("999999999999.999")


class PurchaseValidationError(ValueError):
    def __init__(self, message, entities=None):
        super().__init__(message)
        self.entities = entities or {}


def _active(model, scope):
    return select(model).where(model.tenant_id == scope, model.is_active.is_(True))


def _supplier(text, scope):
    query = _active(Supplier, scope)
    match = _ID.fullmatch(text)
    if match:
        query = query.where(Supplier.id == int(match[1]))
    else:
        query = query.where(
            or_(func.lower(Supplier.name) == text.lower(), func.lower(Supplier.company_name) == text.lower())
        )
    suppliers = db.session.scalars(query.order_by(Supplier.id).limit(11)).all()
    if not suppliers:
        raise PurchaseValidationError("لم أجد موردًا نشطًا بهذا الاسم أو الرقم ضمن الشركة.")
    if len(suppliers) > 1:
        options = "، ".join(f"{supplier.name} (#{supplier.id})" for supplier in suppliers[:10])
        raise PurchaseValidationError(
            f"وجدت أكثر من مورد. أرسل الرقم المطلوب مسبوقًا بـ #: {options}",
            {"supplier_ids": [supplier.id for supplier in suppliers]},
        )
    return {"supplier_id": suppliers[0].id, "supplier": suppliers[0].name}


def _warehouse(text, scope):
    warehouse = db.session.scalar(_active(Warehouse, scope).where(Warehouse.code == text))
    if warehouse is None:
        raise PurchaseValidationError("لم أجد مستودعًا نشطًا بهذا الرمز ضمن الشركة.")
    return {"warehouse_id": warehouse.id, "warehouse": warehouse.name}


def _positive_number(text):
    if not _NUMBER.fullmatch(text):
        return None
    number = Decimal(text.replace("٫", "."))
    return number if number > 0 else None


def _lines(text, scope):
    parsed = []
    seen = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        values = [value.strip() for value in line.split("|")]
        if len(values) != 3:
            raise PurchaseValidationError(STEPS["po_lines"])
        sku, quantity_text, cost_text = values
        quantity = _positive_number(quantity_text)
        cost = _positive_number(cost_text)
        if not sku or len(sku) > 50 or quantity is None or cost is None:
            raise PurchaseValidationError("حدد رمز صنف وكمية وتكلفة وحدة موجبتين، بثلاث منازل عشرية كحد أقصى.")
        if sku in seen:
            raise PurchaseValidationError(f"الصنف «{sku}» مكرر. اجمع الكمية في سطر واحد.")
        seen.add(sku)
        parsed.append((sku, quantity, cost))
    if not parsed:
        raise PurchaseValidationError(STEPS["po_lines"])
    products = {
        product.sku: product
        for product in db.session.scalars(_active(Product, scope).where(Product.sku.in_(seen)))
    }
    lines = []
    for sku, quantity, cost in parsed:
        product = products.get(sku)
        if product is None:
            raise PurchaseValidationError(f"لم أجد الصنف النشط «{sku}» ضمن الشركة.")
        lines.append({
            "product_id": product.id, "sku": sku, "name": product.name,
            "quantity": str(quantity), "unit_cost": str(cost),
        })
    return {"lines": lines}


def _date(text):
    if text.lower() in ("تخطي", "تخطى", "skip"):
        return None
    try:
        value = date.fromisoformat(text) if _DATE.fullmatch(text) else None
    except ValueError:
        value = None
    if not value or value < date.today():
        raise PurchaseValidationError("أدخل تاريخ تسليم صالحًا من اليوم فصاعدًا بصيغة YYYY-MM-DD، أو اكتب «تخطي».")
    return value.isoformat()


def _currency():
    code = CurrencyService.get_base_currency()
    active = db.session.scalar(select(Currency.id).where(Currency.code == code, Currency.is_active.is_(True)))
    if active is None:
        raise PurchaseValidationError("العملة الأساسية للشركة تحتاج إلى تفعيل قبل حفظ أمر الشراء.")
    return code


def _preview(payload, scope):
    currency = _currency()
    tenant = db.session.get(Tenant, scope) if scope is not None else None
    tax_rate, _ = resolve(tenant)
    quote = PurchaseOrder(currency=currency, tax_rate=tax_rate)
    items = []
    for item in payload["lines"]:
        line = PurchaseOrderLine(quantity=Decimal(item["quantity"]), unit_cost=Decimal(item["unit_cost"]))
        line.calculate_line_total()
        quote.lines.append(line)
        items.append(f"• {item['name']} ({item['sku']}) × {line.quantity:g} بسعر {line.unit_cost:,.3f} {currency}")
    quote.calculate_totals()
    if not 0 < quote.total_amount <= _MAX_AMOUNT:
        raise PurchaseValidationError("قيمة أمر الشراء خارج السعة المالية المسموح بها.")
    payload.update(currency=currency, tax_rate=str(tax_rate), total=str(quote.total_amount))
    delivery = payload["delivery"] or "غير محدد"
    return (
        f"معاينة أمر شراء\nالمورد: {payload['supplier']}\nالمستودع: {payload['warehouse']}\n"
        f"التسليم المتوقع: {delivery}\n" + "\n".join(items)
        + f"\nالضريبة: {quote.tax_amount:,.3f} {currency}\nالإجمالي: {quote.total_amount:,.3f} {currency}\n"
        "يحفظ التأكيد أمر الشراء كمسودة قابلة للمراجعة الرسمية."
    )


def advance(step, text, fields, scope):
    payload = dict(fields)
    if step == "po_supplier":
        payload.update(_supplier(text, scope))
        return "po_warehouse", payload, STEPS["po_warehouse"]
    if step == "po_warehouse":
        payload.update(_warehouse(text, scope))
        return "po_lines", payload, STEPS["po_lines"]
    if step == "po_lines":
        payload.update(_lines(text, scope))
        return "po_delivery", payload, STEPS["po_delivery"]
    if step == "po_delivery":
        payload["delivery"] = _date(text)
        return "pending", payload, _preview(payload, scope)
    raise PurchaseValidationError("خطوة أمر الشراء غير متاحة.")


def matched_entities(payload):
    matched = {key: payload[key] for key in ("supplier_id", "warehouse_id") if key in payload}
    if "lines" in payload:
        matched["product_ids"] = [line["product_id"] for line in payload["lines"]]
    return matched


def create_draft(payload, user, scope):
    supplier = db.session.scalar(
        _active(Supplier, scope).where(Supplier.id == payload["supplier_id"]).with_for_update()
    )
    warehouse = db.session.scalar(
        _active(Warehouse, scope).where(Warehouse.id == payload["warehouse_id"]).with_for_update()
    )
    ids = [line["product_id"] for line in payload["lines"]]
    products = {
        product.id: product
        for product in db.session.scalars(
            _active(Product, scope).where(Product.id.in_(ids)).order_by(Product.id).with_for_update()
        )
    }
    if supplier is None or supplier.name != payload["supplier"]:
        raise PurchaseValidationError("تغيّر المورد بعد المعاينة. ابدأ أمر شراء جديدًا.")
    if warehouse is None or warehouse.name != payload["warehouse"]:
        raise PurchaseValidationError("تغيّر المستودع بعد المعاينة. ابدأ أمر شراء جديدًا.")
    for item in payload["lines"]:
        product = products.get(item["product_id"])
        if product is None or product.sku != item["sku"] or product.name != item["name"]:
            raise PurchaseValidationError("تغيّر أحد الأصناف بعد المعاينة. ابدأ أمر شراء جديدًا.")
    if _currency() != payload["currency"]:
        raise PurchaseValidationError("تغيّرت العملة الأساسية. ابدأ أمر شراء جديدًا.")
    delivery = date.fromisoformat(payload["delivery"]) if payload["delivery"] else None
    if delivery and delivery < date.today():
        raise PurchaseValidationError("تاريخ التسليم أصبح في الماضي. ابدأ أمر شراء جديدًا.")

    order = PurchaseOrderService.create_po(
        supplier_id=supplier.id, warehouse_id=warehouse.id, user_id=user.id,
        expected_delivery=delivery, tax_rate=Decimal(payload["tax_rate"]),
        currency=payload["currency"], lines_data=payload["lines"],
    )
    if order.tenant_id != scope or order.total_amount != Decimal(payload["total"]) or order.status != "draft":
        raise PurchaseValidationError("تعذّر حفظ أمر الشراء بالمبالغ التي تمت مراجعتها.")
    return order
