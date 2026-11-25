"""Prepare and post verified catalog and stock imports through the assistant."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import func, or_, select

from extensions import db
from models import Currency, Product, ProductCategory, Warehouse
from services.costing_service import CostingService
from services.currency_service import CurrencyService
from services.stock_service import StockService

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_EXPANDED_BYTES = 40 * 1024 * 1024
MAX_ROWS = 1000
MAX_AMOUNT = Decimal("999999999999.999")
PRECISION = Decimal("0.001")
_CATALOG_IMPORT_LOCK_NAMESPACE = 18741

_HEADERS = {
    "name": ("اسم المنتج", "اسم", "الاسم", "name", "product", "product name", "item"),
    "name_ar": ("اسم المنتج (عربي)", "اسم عربي", "name ar", "arabic"),
    "part_number": ("رقم القطعة", "رقم المنتج", "كود", "part number", "part", "code", "reference"),
    "sku": ("sku", "رمز الصنف"),
    "barcode": ("الباركود", "باركود", "barcode", "bar code"),
    "regular_price": ("السعر", "سعر", "price", "regular price"),
    "cost_price": ("التكلفة", "تكلفة", "cost", "cost price"),
    "merchant_price": ("سعر التاجر", "سعر تاجر", "merchant price"),
    "partner_price": ("سعر الشريك", "سعر شريك", "partner price"),
    "quantity": ("الكمية", "كمية", "مخزون", "عدد", "quantity", "qty", "stock"),
    "min_stock_alert": ("الحد الأدنى للتنبيه", "حد أدنى", "تنبيه", "min stock", "min stock alert"),
    "unit": ("الوحدة", "وحدة", "unit"),
    "category": ("التصنيف", "تصنيف", "فئة", "category"),
    "tax_treatment": ("الضريبة", "معاملة ضريبية", "tax", "tax treatment"),
    "location": ("الموقع", "موقع", "location"),
    "description": ("وصف", "الوصف", "ملاحظات", "description", "notes"),
}
_BY_HEADER = {alias: key for key, aliases in _HEADERS.items() for alias in aliases}
_IDENTIFIERS = ("sku", "part_number", "barcode")
_NUMBERS = ("quantity", "regular_price", "cost_price", "min_stock_alert", "merchant_price", "partner_price")
_TEXT_LIMITS = {
    "name": 200, "name_ar": 200, "sku": 50, "part_number": 100, "barcode": 100,
    "unit": 20, "location": 50, "category": 100, "description": 4000, "tax_treatment": 10,
}


class ImportValidationError(ValueError):
    def __init__(self, message, entities=None):
        super().__init__(message)
        self.entities = entities or {}


def _read_workbook(content):
    try:
        with ZipFile(BytesIO(content)) as zipped:
            if sum(member.file_size for member in zipped.infolist()) > MAX_EXPANDED_BYTES:
                raise ImportValidationError("حجم ورقة Excel بعد فتحها يتجاوز الحد المتاح للاستيراد.")
        workbook = load_workbook(BytesIO(content), read_only=True, keep_links=False)
    except (BadZipFile, InvalidFileException, KeyError, ValueError, OSError, SyntaxError) as error:
        if isinstance(error, ImportValidationError):
            raise
        raise ImportValidationError("تعذّر قراءة ملف Excel. احفظه بصيغة XLSX.") from error

    try:
        worksheet = workbook.active
        if worksheet is None or not hasattr(worksheet, "iter_rows"):
            raise ImportValidationError("لا توجد ورقة عمل قابلة للاستيراد.")
        if worksheet.max_row and worksheet.max_row > MAX_ROWS + 1:
            raise ImportValidationError("يمكن مراجعة حتى 1000 سطر في طلب استيراد واحد.")
        if worksheet.max_column and worksheet.max_column > 100:
            raise ImportValidationError("ورقة الاستيراد تحتوي على أكثر من 100 عمود.")
        records = worksheet.iter_rows(max_row=MAX_ROWS + 2, max_col=worksheet.max_column or 100)
        sheet_headers = next(records, ())
        columns = {}
        for index, cell in enumerate(sheet_headers):
            header = str(cell.value or "").strip().casefold().replace("_", " ")
            field = _BY_HEADER.get(header)
            if field in columns.values():
                raise ImportValidationError(f"يوجد أكثر من عمود بعنوان «{cell.value}».")
            if field:
                columns[index] = field
        if "name" not in columns.values() or not set(_IDENTIFIERS).intersection(columns.values()):
            raise ImportValidationError("استخدم قالب المنتجات بعناوين الاسم ورمز الصنف أو رقم القطعة أو الباركود.")

        result = []
        for row_index, cells in enumerate(records, start=2):
            selected = {field: cells[index] for index, field in columns.items()}
            if not any(cell.value is not None for cell in selected.values()):
                continue
            if row_index > MAX_ROWS + 1:
                raise ImportValidationError("يمكن مراجعة حتى 1000 سطر في طلب استيراد واحد.")
            fields = _parse_row(row_index, selected)
            result.append({"line": row_index, "fields": fields})
        if not result:
            raise ImportValidationError("ملف Excel لا يحتوي على بيانات منتجات.")
        return result
    except (SyntaxError, TypeError, KeyError) as error:
        raise ImportValidationError("تعذّر قراءة بيانات ورقة Excel.") from error
    finally:
        workbook.close()


def _parse_row(line, selected):
    fields = {}
    for field, cell in selected.items():
        value = cell.value
        if value is None or str(value).strip() == "":
            continue
        if cell.data_type in ("f", "e") or isinstance(value, bool):
            raise ImportValidationError(f"السطر {line}: استخدم قيمة مباشرة بدل الصيغة أو خطأ الخلية.")
        if field in _NUMBERS:
            try:
                number = Decimal(str(value).strip().replace("٫", "."))
                if not number.is_finite() or not 0 <= number <= MAX_AMOUNT or number != number.quantize(PRECISION):
                    raise InvalidOperation
            except (InvalidOperation, ValueError) as error:
                raise ImportValidationError(
                    f"السطر {line}: قيمة «{_HEADERS[field][0]}» يجب أن تكون رقمًا غير سالب بثلاث منازل عشرية كحد أقصى."
                ) from error
            fields[field] = str(number)
        else:
            if field in _IDENTIFIERS and isinstance(value, float) and value.is_integer():
                value = int(value)
            value = str(value).strip()
            if len(value) > _TEXT_LIMITS[field]:
                raise ImportValidationError(f"السطر {line}: قيمة «{_HEADERS[field][0]}» أطول من الحد المسموح.")
            fields[field] = value
    if not fields.get("name") or not any(fields.get(key) for key in _IDENTIFIERS):
        raise ImportValidationError(f"السطر {line}: يلزم اسم الصنف وأحد رموزه.")
    tax = fields.get("tax_treatment")
    if tax:
        tax = tax.lower()
        if tax not in ("standard", "zero", "exempt"):
            raise ImportValidationError(f"السطر {line}: المعاملة الضريبية المدخلة غير معتمدة.")
        fields["tax_treatment"] = tax
    return fields


def _warehouse(warehouse_id, scope, *, lock=False):
    query = select(Warehouse).where(Warehouse.tenant_id == scope, Warehouse.is_active.is_(True))
    if warehouse_id is not None:
        query = query.where(Warehouse.id == warehouse_id)
    query = query.order_by(Warehouse.is_main.desc(), Warehouse.id).limit(1)
    if lock:
        query = query.with_for_update()
    warehouse = db.session.scalar(query)
    if warehouse is None:
        raise ImportValidationError("اختر مستودعًا نشطًا ضمن الشركة الحالية.")
    return warehouse


def _resolve_products(rows, scope, *, lock=False):
    codes = {key: {row["fields"][key] for row in rows if key in row["fields"]} for key in _IDENTIFIERS}
    tests = [getattr(Product, key).in_(values) for key, values in codes.items() if values]
    query = select(Product).where(Product.tenant_id == scope, or_(*tests)).order_by(Product.id)
    if lock:
        query = query.with_for_update()
    indexed = {}
    for product in db.session.scalars(query):
        for key in _IDENTIFIERS:
            value = getattr(product, key)
            if value in codes[key]:
                indexed.setdefault((key, value), []).append(product)
    products = []
    seen_ids = set()
    seen_codes = set()
    for row in rows:
        fields = row["fields"]
        references = {(key, fields[key]) for key in _IDENTIFIERS if key in fields}
        matches = {product.id: product for reference in references for product in indexed.get(reference, ())}
        line = row["line"]
        if len(matches) > 1:
            raise ImportValidationError(
                f"السطر {line}: الرموز تطابق أكثر من صنف. استخدم رمزًا فريدًا.",
                {"product_ids": sorted(matches)},
            )
        product = next(iter(matches.values()), None)
        if references.intersection(seen_codes) or (product and product.id in seen_ids):
            raise ImportValidationError(f"السطر {line}: الصنف مكرر في الملف.")
        if product:
            if not product.is_active:
                raise ImportValidationError(f"السطر {line}: الصنف المطابق غير نشط.", {"product_id": product.id})
            seen_ids.add(product.id)
        seen_codes.update(references)
        products.append(product)
    return products


def _review_currency(rows, scope):
    currency = CurrencyService.get_base_currency()
    if any(Decimal(row["fields"].get("quantity", "0")) > 0 for row in rows):
        if scope is None:
            raise ImportValidationError("اختر شركة قبل استيراد كميات المخزون وقيد قيمتها.")
        active = db.session.scalar(
            select(Currency.id).where(Currency.code == currency, Currency.is_active.is_(True))
        )
        if active is None:
            raise ImportValidationError("العملة الأساسية للشركة تحتاج إلى تفعيل قبل الاستيراد.")
    return currency


def prepare(content, warehouse_id, scope):
    rows = _read_workbook(content)
    warehouse = _warehouse(warehouse_id, scope)
    products = _resolve_products(rows, scope)
    currency = _review_currency(rows, scope)
    categories = {row["fields"]["category"] for row in rows if "category" in row["fields"]}
    for name in sorted(categories):
        _category(name, create=False)
    total_cost = Decimal("0")
    movements = 0
    review = []
    for row, product in zip(rows, products):
        fields = row["fields"]
        line = row["line"]
        quantity = Decimal(fields.get("quantity", "0"))
        if product is None and "regular_price" not in fields:
            raise ImportValidationError(f"السطر {line}: أدخل سعر البيع للصنف الجديد.")
        cost = Decimal(fields.get("cost_price", "0"))
        if quantity > 0:
            if "cost_price" not in fields and product:
                cost = CostingService.current_unit_cost(product)
            if cost <= 0:
                raise ImportValidationError(f"السطر {line}: يلزم تسجيل تكلفة موجبة لإضافة كمية إلى المخزون.")
            value = (quantity * cost).quantize(PRECISION, rounding=ROUND_HALF_UP)
            if not value:
                raise ImportValidationError(f"السطر {line}: قيمة الحركة أصغر من دقة سجل المخزون.")
            if value > MAX_AMOUNT or (product and product.current_stock + quantity > MAX_AMOUNT):
                raise ImportValidationError(f"السطر {line}: الكمية أو قيمة الحركة تتجاوز سعة السجل.")
            total_cost += value
            movements += 1
        row["product_id"] = product.id if product else None
        row["unit_cost"] = str(cost)
        name = product.name if product else fields["name"]
        row["name"] = name
        identifier = next(fields[key] for key in _IDENTIFIERS if key in fields)
        label = f"تحديث الصنف #{product.id}" if product else "صنف جديد"
        if "regular_price" in fields:
            label += f" | سعر البيع {Decimal(fields['regular_price']):,.3f} {currency}"
        impact = f" | المخزون +{quantity:g} | القيمة {value:,.3f} {currency}" if quantity else ""
        review.append(f"• {name} ({identifier}) — {label}{impact}")
    created = sum(product is None for product in products)
    preview = (
        f"معاينة استيراد المنتجات\nالمستودع: {warehouse.name}\n"
        f"الأصناف الجديدة: {created} | التحديثات: {len(rows) - created} | حركات المخزون: {movements}\n"
        f"قيمة الزيادة في المخزون: {total_cost:,.3f} {currency}\n"
        + "\n".join(review)
    )
    return {"warehouse_id": warehouse.id, "warehouse": warehouse.name, "currency": currency, "rows": rows}, preview


def _category(name, *, create=True):
    categories = db.session.scalars(
        select(ProductCategory).where(func.lower(ProductCategory.name) == name.lower()).limit(2)
    ).all()
    if len(categories) > 1 or (categories and not categories[0].is_active):
        raise ImportValidationError(f"التصنيف «{name}» غير متاح.")
    if categories:
        return categories[0]
    if not create:
        return None
    category = ProductCategory(name=name, name_ar=name, is_active=True)
    db.session.add(category)
    db.session.flush()
    return category


def apply(payload, scope, *, actor_id=None):
    # The import is atomic. Reporting and learning hooks need no per-row snapshots
    # of a transaction that is still being assembled.
    if len(payload["rows"]) < 2 or actor_id is None:
        return _apply_rows(payload, scope, actor_id=actor_id)
    db.session.info["assistant_bulk_stock_import"] = True
    try:
        return _apply_rows(payload, scope, actor_id=actor_id, batch=True)
    finally:
        db.session.info.pop("assistant_bulk_stock_import", None)


def _apply_rows(payload, scope, *, actor_id=None, batch=False):
    from bot_core.agent.deadline import check_tool_deadline

    if db.engine.dialect.name == "postgresql":
        # Serialize identity resolution for newly created parts across warehouses in the same company.
        db.session.execute(select(func.pg_advisory_xact_lock(_CATALOG_IMPORT_LOCK_NAMESPACE, scope or 0)))
    warehouse = _warehouse(payload["warehouse_id"], scope, lock=True)
    rows = payload["rows"]
    if warehouse.name != payload["warehouse"] or _review_currency(rows, scope) != payload["currency"]:
        raise ImportValidationError("تغيّر المستودع أو العملة الأساسية. أعد رفع الملف للمراجعة.")
    products = _resolve_products(rows, scope, lock=True)
    product_ids = []
    movement_ids = []
    pending = []
    categories = {}
    for row, product in zip(rows, products):
        check_tool_deadline()
        fields = row["fields"]
        product_id = product.id if product else None
        if product_id != row["product_id"] or (product and product.name != row["name"]):
            raise ImportValidationError(f"السطر {row['line']}: تغيّر الصنف المطابق. أعد رفع الملف للمراجعة.")
        quantity = Decimal(fields.get("quantity", "0"))
        cost = Decimal(row["unit_cost"])
        if quantity and product and "cost_price" not in fields and CostingService.current_unit_cost(product) != cost:
            raise ImportValidationError(f"السطر {row['line']}: تغيّرت تكلفة الصنف. أعد رفع الملف للمراجعة.")
        updates = {
            key: Decimal(value) if key in _NUMBERS else value
            for key, value in fields.items()
            if key not in ("name", "quantity", "category")
        }
        if "category" in fields:
            name = fields["category"]
            if name not in categories:
                categories[name] = _category(name).id
            updates["category_id"] = categories[name]
        if not product:
            product = Product(name=fields["name"], tenant_id=scope, is_active=True, current_stock=0)
            db.session.add(product)
        for key, value in updates.items():
            setattr(product, key, value)
        if batch:
            pending.append((product, quantity, cost))
            continue
        db.session.flush()
        product_ids.append(product.id)
        if quantity:
            movement = StockService.create_movement(
                product.id, quantity, "adjustment", reference_type="Excel Import",
                reference_id=product.id, warehouse_id=warehouse.id, unit_cost_base=cost, actor_id=actor_id,
            )
            if movement.tenant_id != scope:
                raise ImportValidationError("تعذّر تسجيل حركة المخزون ضمن الشركة الحالية.")
            journal = StockService.post_adjustment_gl(
                product, quantity, movement, unit_cost_base=cost, actor_id=actor_id
            )
            if journal is None or journal.tenant_id != scope:
                raise ImportValidationError("تعذّر إثبات القيمة المالية لحركة الاستيراد.")
            movement_ids.append(movement.id)

    if batch:
        db.session.flush()
        product_ids = [product.id for product, _, _ in pending]
        adjustments = []
        for product, quantity, cost in pending:
            check_tool_deadline()
            if quantity:
                movement = StockService.stage_import_adjustment(product, warehouse, quantity, cost, actor_id)
                adjustments.append((product, movement, quantity, cost))
        db.session.flush()
        journals = StockService.post_import_adjustments(adjustments, scope, payload["currency"], actor_id)
        if len(journals) != len(adjustments):
            raise ImportValidationError("تعذّر إثبات القيمة المالية لحركة الاستيراد.")
        movement_ids = [movement.id for _, movement, _, _ in adjustments]

    return {"product_ids": product_ids, "movement_ids": movement_ids, "warehouse_id": warehouse.id}
