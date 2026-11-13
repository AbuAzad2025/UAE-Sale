# 📦 طرق إدخال المنتجات (Product Entry Flows) — UAE-Sale ERP

> هذا التقرير يشرح **جميع الطرق** التي يمكن بها إدخال/إنشاء منتج في النظام،
> من إدخال منتج واحد يدوياً إلى شحنة كاملة (Inbound Shipment)، ومن استيراد
> Excel إلى إدخال عبر مشتريات/Maintenance. كل طريقة موثّقة بمسار/endpoint،
> الملفات (routes/services/models/templates)، الحقول/الأعمدة، الصلاحيات (RBAC)،
> والأثر على المخزون/المتوسط/القيود المحاسبية (GL).

---

## 0. نموذج المنتج (`Product`) — مرجع

- **الملف:** `models/product.py` → `class Product(TenantScopedMixin, db.Model)`
- **الجدول:** `products`
- **الحقول (أبرزها):**
  - `name` (String, required), `name_ar`, `commercial_name`
  - `sku` (unique, auto `generate_sku()`), `part_number` (indexed), `barcode` (unique, auto `generate_barcode()`)
  - `category_id` → `ProductCategory`
  - `country_of_origin`
  - `cost_price` (reference / last purchase) — Numeric(15,3)
  - `regular_price` (required), `merchant_price`, `partner_price`, `merchant_share` (default 100%)
  - `tax_treatment`: `standard`/`zero`/`exempt`
  - `average_cost` (moving weighted average — basis of inventory valuation)
  - `current_stock` (alias: `stock_quantity`, `quantity_in_stock`)
  - `min_stock_alert`, `unit`, `location`
  - `warranty_period`, `warranty_unit`, `is_returnable`, `return_period_days`
  - `merchant_customer_id` (تاجر), `partner_shares` (ProductPartner)
  - `image_url`, `description`, `notes`, `is_active`
- **القيود (CHECK):** stock/price/cost/avg_cost ≥ 0
- **العزل (Multi-tenant):** TenantScopedMixin — `tenant_id` إلزامي
- **ProductPartner:** `product_id`, `partner_customer_id`, `percentage` (≤100% مجموع)

---

## 1. إدخال منتج واحد (Manual Single Product)

### 1.1 عبر واجهة الويب (Form)

- **Endpoint:** `GET/POST /products/create` → `routes/products.py::create()`
- **Blueprint:** `products_bp` (prefix `/products`)
- **Permission:** `manage_products`
- **Rate limit:** `10 per minute` (POST)
- **Form:** `forms/product.py::ProductForm`
- **Template:** `templates/products/create.html`

**الحقول (Form + Request):**
| الحقل | Type | Required | ملاحظة |
|------|------|----------|--------|
| `name` | string | ✅ | اسم المنتج |
| `name_ar` | string | ❌ | اسم عربي |
| `sku` | string | ❌ | auto-generate إذا فارغ |
| `part_number` | string | ❌ | |
| `barcode` | string | ❌ | auto-generate إذا فارغ |
| `category_id` | int | ❌ | 0 = بلا |
| `regular_price` | float | ✅ | |
| `merchant_price` / `partner_price` | float | ❌ | |
| `merchant_share` | float | ❌ | default 100 |
| `cost_price` | float | ❌ | فقط لمن يملك `can_see_costs()` |
| `current_stock` | float | ❌ | initial stock |
| `min_stock_alert` | float | ❌ | |
| `unit` | string | ❌ | lookup `product_units` |
| `tax_treatment` | enum | ❌ | standard/zero/exempt |
| `location` | string | ❌ | |
| `description`, `notes` | text | ❌ | |
| `warehouse_id` | int | ✅ | must be active |
| `merchant_customer_id` | int | ❌ | customer_type='merchant' |
| `partner_customer_id[]` + `partner_percentage[]` | arrays | ❌ | شركاء (≤100%) |
| `image` | file | ❌ | upload to `products/` |

**التدفق (Workflow):**
1. Validate form (`form.validate_on_submit()`)
2. Validate warehouse active (`get_owned_or_404(Warehouse, ...)`)
3. Validate merchant (if provided)
4. Parse partner rows (`_parse_product_partners`)
5. Security gate: `cost_price` only if `current_user.can_see_costs()`
6. Create `Product` with `current_stock=0`
7. Flush → get `product.id`
8. Add `ProductPartner` rows
9. If `initial_stock > 0`: `StockService.create_movement(... movement_type='adjustment', reference_type='Product Creation', warehouse_id=...)` — يُحدّث `average_cost`
10. Audit log: `create_audit_log('create', 'products', ...)`
11. Commit → redirect `/products`

**الأثر على المخزون:**
- `current_stock` يبدأ من 0، ثم StockMovement يضيف initial stock
- `average_cost` يُحدّث عبر `CostingService.apply_inbound` (إذا initial_stock > 0)
- GL: لا قيد GL عند إنشاء منتج (create_movement لا يُرحّل GL؛ GL فقط في adjust_stock مع post_gl=True)

### 1.2 عبر Assistant (Chat)

- **Endpoint:** `services/ai_executor.py::execute_tool('create_product', ...)`
- **Permission:** `manage_products` (via ToolDef)
- **Command:** `services/ai_commands.py::create_product(name, part_number=None, regular_price=0, current_stock=0, cost_price=0)`
- **AI Tool:** `services/ai_tools.py::ToolDef('create_product', ...)`
- **Fields:** `name` (required), `part_number`, `price`/`regular_price`, `quantity`/`current_stock`, `cost_price` (optional)
- **ملاحظة:** لا يُحدّث `average_cost` (لا StockMovement) — current_stock يُخزّن مباشرة. audit log via `_ai_audit`.

### 1.3 عبر API (Inline Edit)

- **Endpoint:** `routes/api.py` (inline edit service) — generic product edit, not creation.

---

## 2. استيراد دفعة (Bulk Import via Excel)

### 2.1 Excel Upload (AI Handler)

- **Endpoint:** `POST /ai/upload-excel` → `routes/ai.py::upload_excel()`
- **Permission:** `@login_required` (no explicit permission check in route — weak gate)
- **Form fields:** `file` (xlsx/xls), `warehouse_id` (optional → defaults to main warehouse)
- **Processing:** `routes/ai.py::_process_excel_intelligently(file, warehouse_id, user)`
- **Column detection:** `routes/ai.py::_intelligent_column_detector(df)` — يكتشف الأعمدة ذكياً:
  - `name`: keywords `اسم, name, product, منتج, item, description, وصف`
  - `part_number`: keywords `رقم, part, code, كود, sku, id, reference, مرجع`
  - `price`: keywords `سعر, price, cost, تكلفة, value, قيمة, amount, مبلغ`
  - `quantity`: keywords `كمية, qty, quantity, stock, مخزون, عدد, count`
- **Fallback:** إذا لم يُكتشف عمود، يُستخدم positional (0=name, 1=part, 2=price, 3=qty)
- **الحد الأدنى:** ≥3 أعمدة مطلوبة
- **منطق التحديث:**
  - البحث عن منتج موجود بـ `part_number` → تحديث `regular_price` + `current_stock += quantity`
  - غير موجود → إنشاء `Product(name, part_number, regular_price, current_stock, is_active=True)` (لا warehouse, لا category, لا cost_price)
- **Audit:** `_ai_audit('products', None, {'method':'excel_import', 'created':..., 'updated':...})`
- **AI Training:** `_train_ai_from_excel(df, ...)`
- **Template:** `/static/template_products.xlsx` (referenced in `templates/ai/assistant.html::openExcelTemplate()`) — **أُعيد إنشاؤه** (template مثالي مع header + 5 صفوف نموذجية + ملاحظات).
- **ملاحظة:** لا يُحدّث `average_cost` (لا StockMovement) — current_stock يُضاف مباشرة. لا GL.

### 2.2 AI Handler Flow (UI)

- **Template:** `templates/ai/assistant.html` — Excel uploader form
- **JS:** `static/js/import_upload.js` — client-side validation (ext: csv/xls/xlsx, max 5MB)

---

## 3. إدخال عبر المشتريات (Purchase Flow)

### 3.1 فاتورة شراء (Purchase Invoice) — الطريقة الرئيسية

- **Endpoint:** `GET/POST /purchases/create` → `routes/purchases.py::create()`
- **Permission:** `manage_purchases`
- **Rate limit:** `10 per minute` (POST)
- **Template:** `templates/purchases/create.html`
- **Model:** `Purchase`, `PurchaseLine`
- **Fields (Purchase header):** `supplier_id` (optional), `supplier_name` (required), `warehouse_id` (required), `currency`, `exchange_rate`, `discount_amount`, `tax_rate`, `tax_inclusive`, `tax_treatment` (standard/zero/exempt), `vat_recoverable`, `reverse_charge`, `notes`, `due_date`, `purchase_date`
- **Fields (PurchaseLine):** `product_id` (required), `quantity` (>0), `unit_cost` (>0), `discount_percent`, `tax_treatment`
- **التدفق:**
  1. Create `Purchase` (flush → id)
  2. For each line: create `PurchaseLine`, `calculate_line_total()`
  3. `purchase.calculate_totals()` (subtotal, tax, total, amount_base)
  4. `StockService.process_purchase_lines(purchase, warehouse_id)`:
     - For each line: `StockService.add_stock(... movement_type='purchase'/'adjustment', reference_type='Purchase')`
     - `CostingService.net_unit_cost(line, purchase)` → average_cost update
     - `product.cost_price` updated to last purchase cost (base currency)
  5. GL: `build_purchase_gl_lines(purchase)` → `GLService.post_entry(...)` — Dr 1140 (Inventory) / Cr 2110 (AP) / VAT
  6. Update supplier statistics
  7. Commit + audit log

**الأثر على المخزون:** ✅ `current_stock += quantity` + `average_cost` updated + GL posted

### 3.2 أمر شراء (Purchase Order) — ERP Module

- **Endpoint:** `routes/erp_modules.py` → PurchaseOrder create/approve/receive
- **Service:** `services/erp_modules_service.py::PurchaseOrderService`
  - `create_po(supplier_id, warehouse_id, lines_data, user_id, ...)`
  - `approve_po(po_id, approver_id)`
  - `receive_po(po_id, user_id)` → creates a `Purchase` (PurchaseLine per PO line with received qty)
- **⚠️ Gap:** `receive_po` ينشئ Purchase invoice but does NOT call `StockService.process_purchase_lines` or GL. Stock movement happens only via direct `/purchases/create`.

### 3.3 AI Command: create_purchase

- **Endpoint:** `services/ai_executor.py::execute_tool('create_purchase', ...)`
- **Command:** `services/ai_commands.py::create_purchase(supplier_id, product_id, quantity, unit_cost, user_id)`
- **Fields:** `supplier_name` (required), `product_name` (required), `quantity`, `unit_cost` (optional)
- **ملاحظة:** creates Purchase with single line, calculates totals, but does NOT call StockService.process_purchase_lines or GL. (Simplified path.)

---

## 4. إدخال عبر شحنات واردة (Inbound Shipment) — Full Chain

### 4.1 Inbound Shipment (استقبال شحنة بضائع واردة)

- **Blueprint:** `inbound_bp` (prefix `/inbound-shipments`)
- **Permission:** `manage_warehouse`
- **Lifecycle:** `in_transit` → `arrived` → `inspected` → `put_away` → `closed` (or `cancelled`)
- **Service:** `services/inbound_shipment_service.py::InboundShipmentService`

**Endpoints:**
| Method | URL | Function | Action |
|--------|-----|----------|--------|
| GET | `/inbound-shipments` | `list_inbound()` | list (filter by status) |
| GET | `/inbound-shipments/<id>` | `view_inbound(id)` | view |
| GET/POST | `/inbound-shipments/create` | `create_inbound()` | create draft |
| POST | `/inbound-shipments/<id>/arrive` | `arrive_inbound(id)` | confirm arrival |
| POST | `/inbound-shipments/<id>/inspect` | `inspect_inbound(id)` | inspect/accept |
| POST | `/inbound-shipments/<id>/put-away` | `put_away_inbound(id)` | move stock to warehouse |
| POST | `/inbound-shipments/<id>/close` | `close_inbound(id)` | close |
| POST | `/inbound-shipments/<id>/cancel` | `cancel_inbound(id)` | cancel |

**Create form fields:**
- `warehouse_id` (required), `supplier_id` (optional), `purchase_order_id` (optional)
- `carrier`, `tracking_number`, `expected_at`, `notes`
- Lines: `lines[i][product_id]`, `lines[i][quantity_expected]`, `lines[i][unit_cost]`

**التدفق (put_away):**
1. For each accepted line: `StockService.adjust_stock(product_id, qty, notes='Inbound ...', warehouse_id=sh.warehouse_id, post_gl=False)`
   - → `StockService.create_movement(...)` → updates `current_stock` + `average_cost`
   - `post_gl=False` → NO GL entry (per plan: "no GL until sale")
2. Update linked PO status (received/partially_received)
3. Set shipment status = `put_away`

**الأثر على المخزون:** ✅ `current_stock += quantity_accepted` + `average_cost` updated (via StockMovement) — but **NO GL** (post_gl=False)

### 4.2 Outbound Shipment — NOT product entry

- `routes/shipments.py` — outbound shipments (move stock OUT). Not product entry.

---

## 5. إدخال عبر صيانة (Maintenance Module) — Consumption, NOT Entry

> **ملاحظة:** وحدة الصيانة **لا تُدخل** منتجات جديدة إلى النظام. هي **تستهلك**
> قطع غيار existing (تخفيض المخزون) وتُسجّل قيوداً محاسبية. إدخال قطع الغيار
> يتم عبر الطرق 1-4 (خاصة Purchases/Inbound Shipment).

### 5.1 Maintenance Purchase (شراء قطع صيانة)

- **Endpoint:** `routes/maintenance.py::create_maintenance_purchase`
- **Service:** `services/maintenance_service.py::create_maintenance_purchase(tenant_id, supplier_id, warehouse_id, lines_data, user_id, ...)`
- **Permission:** `maintenance_purchase`
- **Model:** `PurchaseOrder` (MN-PO prefix), `PurchaseOrderLine`
- **Fields:** supplier_id, warehouse_id, lines (product_id, quantity, unit_cost), expected_delivery, notes, tax_rate
- **التدفق:** creates PurchaseOrder (status='approved') + lines. NO stock movement (PO only).

### 5.2 Receive Maintenance Purchase (استلام قطع)

- **Service:** `services/maintenance_service.py::receive_maintenance_purchase(purchase_id, user_id)`
- **Permission:** `maintenance_purchase`
- **التدفق:**
  1. For each line with remaining qty: `StockService.create_movement(product_id, +remaining, movement_type='purchase', reference_type='maintenance_purchase', unit_cost_base=line.unit_cost)` → **increases stock** + updates average_cost
  2. Set PO status = 'received'
  3. `accounting.post_goods_receipt(purchase, ...)` → GL entry

**الأثر على المخزون:** ✅ `current_stock += quantity` + `average_cost` updated + GL posted (Dr 1140 / Cr 2110)

### 5.3 Maintenance Order Parts Issue (صرف قطع لأمر صيانة)

- **Service:** `services/maintenance_service.py::add_order_item(order_id, product_id, quantity, unit_price, ...)`
- **Permission:** `maintenance_work`
- **التدفق:**
  1. Check availability: `StockService.check_availability(product.id, quantity, warehouse_id)`
  2. Actual cost: `CostingService.cost_for_sale(product, quantity)` (moving average)
  3. Create `MaintenanceOrderItem` (cost_price=unit_cost, cost_source='inventory')
  4. `StockService.create_movement(product_id, -quantity, movement_type='maintenance', reference_type='maintenance_order')` → **decreases stock**
  5. `accounting.post_parts_issue(order, line, unit_cost=unit_cost, quantity=quantity, ...)` → GL

**الأثر على المخزون:** ❌ `current_stock -= quantity` (issue reduces stock) + GL posted (parts expense)

---

## 6. مصفوفة الصلاحيات (RBAC) — Product Entry

| الطريقة | Permission | من يمكنه |
|---------|------------|----------|
| Manual single (Web) | `manage_products` | admin, manager |
| Manual single (AI) | `manage_products` | admin, manager |
| Excel bulk import | `@login_required` only | أي مستخدم مصادق (⚠️ weak gate) |
| Purchase invoice | `manage_purchases` | admin, manager |
| Purchase Order (ERP) | `manage_purchases` | admin, manager |
| Inbound Shipment | `manage_warehouse` | admin, manager, warehouse |
| Maintenance Purchase | `maintenance_purchase` | maintenance roles |
| Maintenance Parts Issue | `maintenance_work` | maintenance roles |

---

## 7. ملخص — مصفوفة الطرق (Summary Matrix)

| # | الطريقة | Endpoint/Service | يُنشئ منتج جديد؟ | يُحدّث المخزون؟ | يُحدّث average_cost؟ | GL؟ |
|---|---------|------------------|-------------------|-----------------|----------------------|-----|
| 1 | Manual single (Web) | `/products/create` | ✅ | ✅ (initial stock) | ✅ | ❌ (no GL on creation) |
| 2 | Manual single (AI) | `ai_commands.create_product` | ✅ | ✅ (current_stock) | ✅ (fixed) | ❌ |
| 3 | Excel bulk import | `/ai/upload-excel` | ✅ (or update) | ✅ (current_stock +=) | ✅ (fixed) | ❌ |
| 4a | Purchase invoice | `/purchases/create` | ❌ (existing only) | ✅ (+qty) | ✅ | ✅ |
| 4b | Purchase Order → receive | `PurchaseOrderService.receive_po` | ❌ (existing only) | ✅ (+qty) (fixed) | ✅ (fixed) | ✅ (fixed) |
| 4c | AI create_purchase | `ai_commands.create_purchase` | ❌ (existing only) | ✅ (+qty) (fixed) | ✅ (fixed) | ❌ |
| 5 | Inbound Shipment | `/inbound-shipments/*` | ❌ (existing only) | ✅ (+qty accepted) | ✅ | ❌ (post_gl=False) |
| 6 | Maintenance Purchase | maintenance routes | ❌ (existing only) | ✅ (+qty on receive) | ✅ | ✅ |
| 7 | Maintenance Parts Issue | maintenance routes | ❌ | ❌ (-qty) | ❌ (consumption) | ✅ |

---

## 8. ✅ الثغرات التي تم إصلاحها (Fixed Gaps)

1. **Excel import — average_cost** ✅ **تم الإصلاح**: الآن يستخدم `StockService.create_movement(...)` (movement_type='adjustment', reference_type='Excel Import') مع warehouse_id، لذا `current_stock` و `average_cost` يُحدّثان (CostingService.apply_inbound). لا GL (consistent with manual create).
2. **Excel import — warehouse_id** ✅ **تم الإصلاح**: `warehouse_id` يُمرَّر إلى `StockService.create_movement(warehouse_id=...)`، لذا حركة المخزون ترتبط بالمستودع.
3. **Excel import — cost_price** ✅ **تم الإصلاح (جزئياً)**: `cost_price=0` افتراضياً (consistent with manual create security gate)، مع تحذير في رسالة النتيجة عن المنتجات بدون تكلفة. المستخدم puede ضبط التكلفة عبر تعديل المنتج.
4. **Purchase Order receive (4b)** ✅ **تم الإصلاح**: `receive_po` الآن calls `StockService.process_purchase_lines(purchase, po.warehouse_id)` + `build_purchase_gl_lines` + `GLService.post_entry(...)`. Stock movement + GL posted (Dr 1140 / Cr 2110 / VAT).
5. **AI create_purchase (4c)** ✅ **تم الإصلاح**: الآن uses `StockService.create_movement(...)` (movement_type='purchase', reference_type='Purchase') with `unit_cost_base=unit_cost` → updates `current_stock` + `average_cost`. (GL not posted in AI path due to missing currency/warehouse context — simplified path.)
6. **Inbound Shipment put_away uses `post_gl=False`** — no GL entry (per plan: "no GL until sale"). This is by design. (لم يتغير)
7. **Excel import permission gate** ✅ **تم الإصلاح**: أُضيف `@permission_required('manage_products')` إلى route `upload_excel`.
8. **AI create_product** ✅ **تم الإصلاح**: الآن uses `StockService.create_movement(...)` (movement_type='adjustment', reference_type='AI Product Creation') with `unit_cost_base=cost_price` → updates `current_stock` + `average_cost` (was: direct `current_stock=current_stock` without StockMovement).
9. **`template_products.xlsx`** — was referenced in `templates/ai/assistant.html` but deleted. The Excel import uses intelligent column detection, so a fixed template is not strictly required. (لم يتغير)

---

## 9. ملفات مرجعية (Key Files)

| Purpose | File |
|---------|------|
| Product model | `models/product.py` |
| Product form | `forms/product.py` |
| Product routes (manual) | `routes/products.py` |
| Purchase routes | `routes/purchases.py` |
| Inbound shipment routes | `routes/inbound_shipments.py` |
| Inbound shipment service | `services/inbound_shipment_service.py` |
| Purchase Order service | `services/erp_modules_service.py::PurchaseOrderService` |
| Stock service | `services/stock_service.py` |
| Costing service | `services/costing_service.py` |
| AI excel import | `routes/ai.py::upload_excel`, `_process_excel_intelligently`, `_intelligent_column_detector` |
| AI commands | `services/ai_commands.py::create_product`, `create_purchase` |
| AI executor | `services/ai_executor.py` |
| AI tools | `services/ai_tools.py` |
| Maintenance service | `services/maintenance_service.py` |
| Maintenance accounting | `services/maintenance_accounting.py` |
| Templates | `templates/products/create.html`, `templates/purchases/create.html`, `templates/inbound_shipments/create.html`, `templates/ai/assistant.html` |