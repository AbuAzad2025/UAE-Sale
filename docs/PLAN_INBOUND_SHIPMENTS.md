# خطة شاملة — استقبال شحنات البضائع وتتبعها وإدخالها للمستودعات (100%)

> **مصادر موثوقة فقط:** `models/warehouse.py:7` `StockMovement:57`، `models/erp_modules.py:114` `StockTransfer:252`، `routes/erp_modules.py:226` `receive_purchase_order`، `services/erp_modules_service.py:216` `receive_po`، `models/purchase.py:1` `Purchase/PurchaseLine`، `docs/MIGRATIONS.md:1` (20 مراجعة، رأس `20_shipment_module`)، `.github/workflows/ci.yml:127` (PostgreSQL `azad_test`).

## 1) الهدف — تعريف 100%
شحنة وارد **مرتبطة أو غير مرتبطة بطلب شراء** تُستقبل من مورد/ناقل برقم تتبع، تُفحص، ثم **تُدخل فعلياً لمخازن محددة** (موقع/بن) مع حركة مخزنية، وتُغلق الطلب جزئياً/كلياً، وتُظهر في التقارير والمدفوعات. لا تُعتبر مستلمة حتى `put_away`.

## 2) النطاق
**داخل:** `InboundShipment` + `InboundShipmentLine`، استقبال/فحص/إدخال، تتبع، ربط `PurchaseOrder`، تحديث `Product.current_stock` عبر `StockMovement`، دعم `ProductLot`/`WarehouseBin`، صلاحيات، عزل مستأجر، تقارير، اختبارات. **خارج:** فوترة جمركية معقدة (تُترك للمرحلة 2).

## 3) نموذج البيانات — PostgreSQL-native (تهجير 21)
**جدول `inbound_shipments`** (`models/inbound_shipment.py:1`):
- `id` PK, `tenant_id` FK `tenants.id` (TenantScopedMixin), `shipment_number` unique `ix_inbound_shipments_number`
- `supplier_id` FK `suppliers.id` nullable, `purchase_order_id` FK `purchase_orders.id` nullable (شحنة حرة أو مرتبطة)
- `warehouse_id` FK `warehouses.id` NOT NULL (المستودع الرئيسي المستقبل) — تفاصيل بن/موقع على مستوى البنود
- `carrier` String(100), `tracking_number` String(100) index, `expected_at` Date, `arrived_at`/`inspected_at`/`put_away_at` timestamptz
- `status` enum `in_transit→arrived→inspected→put_away→closed / cancelled` مع `ck_inbound_status_valid`
- `total_quantity`/`total_value` Numeric(15,3) `ck_..._non_negative`
- `created_by_id`/`assigned_to_id` FK `users.id`, `notes` Text, `created_at`/`updated_at` timestamptz
- Indexes: `(tenant_id,status)`, `warehouse_id`, `supplier_id`, `purchase_order_id`, `tracking_number`, `status`

**جدول `inbound_shipment_lines`**:
- `id` PK, `inbound_shipment_id` FK `shipments.id` CASCADE, `product_id` FK `products.id` RESTRICT, `quantity_expected`/`quantity_received`/`quantity_accepted` Numeric(15,3) `>0`/`>=0`, `unit_cost`/`line_total`, `warehouse_bin_id` FK `warehouse_bins.id` nullable, `lot_id` FK `product_lots.id` nullable, `notes`
- Indexes: `shipment_id`, `product_id`, `bin_id`

**تعديل غير كاسر:** لا تعديل على `sales`; ربط `Purchase` المُنشأ عند `put_away` عبر `purchase.inbound_shipment_id` nullable (إضافة عمود واحد إن لزم، مع فحص idempotency `if column not in inspector`).

## 4) العزل — Multi-Tenancy
- `InboundShipment(TenantScopedMixin)` + `register_tenant_scoped(InboundShipment)` في `models/__init__.py:62` — كل `query` يُفلتر تلقائياً بـ `tenant_id` (`models/tenant_scope.py:205`).
- `Warehouse` يتحقق `tenant_id == manager.tenant_id` (`models/warehouse.py:32` `validate_tenant_consistency`) — يمنع إدخال شحنة لمستودع بمستأجر مختلف.
- اختبارات عزل تُثبت: مستأجر A لا يرى شحنات B (`TestMultiTenancyIsolation` نمط `tests/security/test_zero_trust_isolation.py:297`).

## 5) الإدارة والصلاحيات — مصفوفة صريحة
| الدور | إنشاء | عرض | استلام/فحص/إدخال | إلغاء | إغلاق |
|------|------|-----|----------------|------|------|
| `owner`/`super_admin` | ✅ | ✅ (كل المستأجرين) | ✅ | ✅ | ✅ |
| `manager` (`manage_warehouse`+`manage_purchases`) | ✅ | ✅ (مستأجره) | ✅ | ✅ | ✅ |
| `seller` (`manage_sales`) | ❌ | ❌ | ❌ | ❌ | ❌ |
| `viewer` | ❌ | ❌ | ❌ | ❌ | ❌ |
- تنفيذ عبر `@permission_required('manage_warehouse')` و `@permission_required('manage_purchases')` في `routes/inbound_shipments.py:1` (مثل `routes/erp_modules.py:292`). `admin_required` للإغلاق النهائي إن احتاج.

## 6) منطق الخدمة — `services/inbound_shipment_service.py:1`
```
create_inbound_shipment(warehouse_id, supplier_id?, purchase_order_id?, carrier?, tracking_number?, expected_at?, lines_data=[{product_id, quantity_expected, unit_cost}], tenant_id, user_id) -> draft
  - تحقق: warehouse موجود و tenant متطابق، supplier وجوده اختياري، quantity>0، product موجود و active

arrive(shipment_id, user_id)  draft/in_transit -> arrived  (يضبط arrived_at)

inspect(shipment_id, lines_inspection=[{line_id, quantity_accepted}], user_id)  arrived -> inspected
  - quantity_accepted <= quantity_received، لو كل البنود 0 -> تبقى inspected لإعادة الفحص

put_away(shipment_id, user_id)  inspected -> put_away  (الحركة المخزنية الحقيقية)
  - لكل بند: StockService.adjust_stock(product_id, +quantity_accepted, warehouse_id, post_gl=False)  // نفس عقد C1 في `services/erp_modules_service.py:268` (لا GL حتى البيع)
  - إن مرتبط بـ PurchaseOrder: حدّث `received_quantity`، احسب `is_fully_received`، إن اكتمل -> `status=received`، وإلا `partially_received`
  - إن أنشأ `ProductLot`/`ProductBin` حسب الحاجة
  - تسجيل `StockMovement(reference_type='inbound_shipment', reference_id=...)`

close / cancel  put_away/inspected -> closed | any non-closed -> cancelled
```
- كل انتقال يتحقق من `status` الحالي ويرمي `ValueError` برسالة عربية واضحة.
- `calculate_totals()` يجمع الكميات/القيم.

## 7) المسارات والواجهة — `routes/inbound_shipments.py:1`
- `GET /inbound-shipments` (list, فلتر `status`/`warehouse`/`supplier`/`tracking`)
- `GET /inbound-shipments/<id>` (view + بنود + حركات مخزنية + فواتير شراء مرتبطة)
- `GET+POST /inbound-shipments/create` (نموذج: مستودع/مورد/طلب شراء/ناقل/تتبع/متوقع + بنود Ajax `select2-ajax` نفس `static/js/shipments.js:42`)
- `POST /inbound-shipments/<id>/arrive|inspect|put-away|close|cancel`
- `GET /api/warehouses|products|suppliers` للـ Select2 (مثل `routes/shipments.py:120`)
- `templates/inbound_shipments/list.html|view.html|create.html` + رابط `templates/base.html:662` بجانب `الإرساليات`.
- CSRF، `create_audit_log`، رسائل `flash` عربية.

## 8) التهجير — `migrations/versions/21_inbound_shipment.py:1`
- `revision='21_inbound_shipment'` `down_revision='20_shipment_module'` (رأس واحد خطي).
- `op.create_table`原生 بدون `batch` (التزام `docs/MIGRATIONS.md:6`).
- `CheckConstraint` للحالة والكميات، `Index` و `ForeignKey(ondelete=RESTRICT/SET NULL/CASCADE)` صريحة.
- `if 'inbound_shipments' in inspector.get_table_names(): return` و `if 'shipment_id' in cols: skip` للـ idempotency.
- `downgrade` يزيل بالعكس مع `try/except`.

## 9) الاختبارات والتكامل — 100% بدون Mock للمنطق
- **Unit model** `tests/unit/test_inbound_shipment_model.py:1`: defaults/status_ar/totals/validation/unique number.
- **Unit service** `tests/unit/test_inbound_shipment_service.py:1`: create success/validations, lifecycle `draft→arrived→inspected→put_away→closed`, invalid transitions, cancel, put_away ينشئ `StockMovement` ويحدّث `PurchaseOrder`.
- **Integration routes** `tests/integration/test_inbound_shipments.py:1`: `login_required`, `owner` list/create, workflow عبر routes (`arrive→inspect→put_away`), `seller` محجوب، `productLot/bin` إن وجد.
- **عزل** `tests/security/test_zero_trust_isolation.py` نمط: مستأجر A لا يرى شحنات B، `is_active` scope.
- المتوقع: `pytest`  ~16 اختبار جديد 14+2، كلها على `sqlite:///:memory:` عبر `tests/conftest.py:52` (`create_all` + `clear_current_tenant_id` + `engine.dispose`).
- **Integration PostgreSQL** `tests/integration/test_wave_finance_pages.py` نمط: `put_away` لا ينشئ GL (يُفحص `gl_journal_entries` لم تتغير).

## 10) التكامل مع الموجود
- `PurchaseOrder` يبقى مصدر الطلب، `InboundShipment` هو التنفيذ اللوجستي؛ لا كسر للواجهة الحالية `receive_purchase_order` (يُبقى كاختصار يستدعي الخدمة الجديدة).
- `StockMovement` مرجع `inbound_shipment` يظهر في `reports/inventory`.
- `Payment/Receipt` تبقى على `Purchase`، لكن `view_shipment` يعرض الفواتير المرتبطة.
- `AuditLog` و `JournalEntryAudit` لكل انتقال.

## 11) الأداء والأمان
- Indexes أعلاه + `tenant_id` في كل استعلام (العزل يضيفه تلقائياً).
- Validation: `quantity>0`, `unit_cost>=0`, `destination_name` مطلوب، `warehouse_id` يتطابق مع `tenant`.
- CSRF `csrf_token`, `permission_required`, لا `batch` هش، `try/except` حول `flush` مع `rollback`.

## 12) التسليم والتحقق — ثقة 100% من مصادر موثوقة
1. `flask db upgrade head` على `audit_fresh` جديدة → 84 جدول (83+2) نظيف.
2. `flask db downgrade 20_shipment_module` → `upgrade head` round-trip نظيف.
3. `python -m pytest new tests -v` 16/16، `python -m flake8 --select=E9,F63,F7,F82` 0، `bandit -c .bandit.yml -r . -ll -ii` Medium 0 High 0.
4. `pytest tests/unit tests/security` كامل يبقى ~2928 pass (بعد إصلاح `test_zero_trust_isolation` السابق).
5. تحديث `docs/MIGRATIONS.md:1` إلى 21 مراجعة، رأس `21_inbound_shipment`.

**معيار 100%:** عندما تمر 1-4 أعلاه + `app boot` يطبع `83→84 tables` + `Alembic Round-Trip` أخضر، تكون الميزة **مغلقة** بلا تخبط — تاريخ تهجيرات واحد خطي، عزل tenant صحيح، صلاحيات واضحة، وكل حقل منقول بلا فقدان.
