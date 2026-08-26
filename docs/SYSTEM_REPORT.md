# التقرير الشامل — مبدأ عمل النظام وكل الوحدات
> توثيق هندسي مستخرج من قراءة الكود فعليًا بواسطة 15 وكيل تحقيق متوازٍ · كل معلومة موثقة بـ `ملف:سطر` · لا افتراضات.
> إصدار الكود: بعد commit التدقيق المالي الثماني (`12a0ea6`) · 1239→1440 اختبارًا أخضر.

---

## 0) بطاقة النظام بالأرقام الحقيقية

| المؤشر | القيمة | المصدر |
|---|---|---|
| نماذج قاعدة بيانات | **64** `class(db.Model)` في 38 ملفًا | `rg "class .*\(db.Model\)" models` |
| نقاط HTTP | **473** مسارًا عبر 35 blueprint | `rg "@.*_bp.route|@app.route" routes app.py` |
| خدمات | **41** ملفًا (~10,175 سطرًا) | عدّ |
| أدوات utils | **29** ملفًا (~3,113 سطرًا) | عدّ |
| وحدات ai_knowledge | **44** (~14,714 سطرًا) | عدّ |
| قوالب HTML | **242** (~49,366 سطرًا) | عدّ |
| اختبارات | **1440** (42 unit + 7 integration ملفات، ~15,500 سطر) | pytest |
| ترحيلات Alembic | **8** مراجعات | migrations/versions |

**طبيعة النظام**: ERP محاسبة مزدوجة متعدد المستأجرين (Flask 3 / SQLAlchemy / AdminLTE3)، عملة قاعدة ديناميكية (افتراضي `ILS`)، بوابة كريبتو NOWPayments، مساعد AI هجين (سحابي Groq/Gemini/OpenAI + محلي heuristic).

---

## 1) الإقلاع ودورة حياة الطلب
- `create_app()` (app.py:88): config → مجلدات runtime → فحص سلامة إنتاج (يرفض SECRET_KEY ضعيف/sqlite/كوكيز غير آمنة) (config.py:238-286) → سجلات منقّاة (extensions.py:120-163 يحقن RequestIdFilter+SanitizeFilter) → تهيئة db/migrate/login/csrf/cache/limiter/compress/babel (+mail شرطي بوجود MAIL_USERNAME) (extensions.py:226-269).
- تسجيل **31 Blueprint** (app.py:106-256) + fallback blueprint لـAI يعيد 503 عند فشل الاستيراد (:145-203).
- Hooks: `before_request` يولّد request_id ويضبط tenant (owner→بلا فلترة) وخروج بعد خمول 30د؛ `after_request` رؤوس أمان CSP/HSTS (:338-359)؛ teardown يمسح tenant context (:361-365).
- تحت `python app.py` فقط: خيط نسخ احتياطي يومي 02:00 (:449-498) + خيط auto-approval كل ساعة — **لا يعملان تحت gunicorn** (مزلاج مؤثر إنتاجيًا).
- Celery worker منفصل بثلاث مهام inline: إصلاح أرصدة كل 6h، قبول تلقائي :15، فحص أمني 02:00 (celery_worker.py:21-62)؛ `celery autodiscover` لحزمة غير موجودة (:65).

## 2) تعدد المستأجرين (Multi-Tenancy)
- آلية thread-local: `set/get_current_tenant_id` (tenant_scope.py:20-34) + مستمع `Query.before_compile` يحقن `tenant_id == X` للكيان الأساسي فقط للجداول المسجلة (69-103).
- **12 نموذجًا مفلتَرًا فقط**: Sale/SaleLine/Purchase/PurchaseLine/Payment/Receipt/Customer/Supplier/Product/StockMovement/Cheque/GLJournalEntry (models/__init__.py:52-54).
- ⚠️ `None` = بلا فلترة وليس رفضًا؛ joins غير مفلترة؛ ProductReturn/Quotation/erp_modules كلها خارج العزل (tenant_scope.py:73-74,96؛ erp_modules.py:22).

## 3) المصادقة والأمان
- `User.set_password` pbkdf2:sha256 (user.py:121-123)؛ قفل حساب بعد `MAX_LOGIN_ATTEMPTS` لمدة `LOGIN_BLOCK_DURATION_MINUTES` (routes/auth.py:52-56) + LoginHistory لكل محاولة (:67,:95).
- صلاحيات مزروعة 14 code (system_init.py:50-68)؛ owner/super_admin/developer يتجاوزون الفحص دائمًا (user.py:150-155).
- **مفتاح مالك دوّار يوميًا**: `<seed>@YYYY@MM@DD` بمقارنة timing-safe (utils/licensing.py:15-37) — seed مشفر بالرموز = "Azad@1983" (:7-17).
- خزانة بطاقات مزدوجة الجودة: CardPayment «تشفير» base64 يشمل CVV! مقابل CardVault Fernet حقيقي بحقول مشفرة + hash SHA256 **غير ملحّ** (card_payment.py:79-80 مقابل card_vault.py:57-78)؛ فك التشفير يتطلب `ALLOW_CARD_DECRYPTION` + is_owner (card_vault.py:114-142).

## 4) الدليل المحاسبي الديناميكي (Dynamic CoA)
- `AccountResolver.resolve(role)` بأولوية: خريطة المستأجر > الخريطة العامة > DEFAULT_ROLE_MAP (= أكواد اليوم) المخزنة في `SystemSettings.custom_settings` JSON — بدون أي schema change (account_resolution.py:125-177) — ~40 دورًا.
- `GLService`: seed ~60 حسابًا هرميًا (1000-6990) (gl_service.py:20) · `post_entry` يفرض التوازن ويحسب `amount_base=(dr−cr)×rate` (255-270) · `create_manual_entry` يرفض الحسابات الرأسية وcommit ذاتي (303-346) · كشف حساب برصيد افتتاحي مضبوط ضد الاحتساب المزدوج (379-394).
- `GLJournalEntry.reverse_entry` ينشئ معكوسًا بربط ثنائي `reversed_entry_id` (models/gl.py:243-280) — **لكن القيد المعكوس بلا tenant_id** (251-263).
- ⚠️ ترقيم JE يقرأ max ثم يكتب — ليس آمن تزامن كامل؛ `_unique_entry_number` مكررة نصيًا 3 مرات (gl_service.py:166,218,279).

## 5) دورة البيع الكاملة (Pipeline حقيقي)
POST /sales/create → SaleService.create_sale:
تحقق أطراف/بنود (sale_service.py:55-62) → **بوابة الفترة المالية** (تفتح إذا لا فترات موجودة!) (64-70, erp_modules_service.py:241-250) → generate_number بقفل موزع fail-open (helpers.py:17-98; distributed_lock.py:88) → سعر صرف → حد اائتمان تقديري → flush → بنود بمخزون وتسعير حسب نوع العميل (partner/merchant نسب خصم وليست أسعارًا! product.py:134-141) → calculate_totals (Decimal HALF_UP) → فرع الدفع: الزائد يذهب لرصيد العميل والدفع يُقصّ لسقف الفاتورة (225-249) → خصم مخزون StockService (257) → Payment+شيك (260) → تصنيف العميل vip/premium (273) → **قيدان GL**: إيراد بعملة الفاتورة + COGS بعملة الأساس (292-369) → commit ذري @tx.

## 6) المدفوعات والشيكات
- Receipt (@tx) بثلاثة مصادر manual/sale/cheque؛ شيك ينشئ Cheque+receive_cheque؛ تخصيص FIFO للأقدم مع تسجيل غير الموزع؛ تدقيق شامل actor=user/system + عقد ORPHAN RECEIPT WARNING عند فشل GL (payment_service.py:49-247,177-185).
- Cheque آلة حالات: pending→deposited→cleared/bounced/cancelled مع قيود استلام/إصدار/مقاصة/ارتداد وفروق عملة بتوقيع صحيح (وارد: موجب=ربح؛ صادر: موجب=خسارة) (cheque.py:233-464) وأعمدة روابط GL الثلاثة (97-99).
- ⚠️ سند الشيك يضع gl_posted=True دون ترحيل (payment_service.py:157)؛ حذف سند يخصم paid_amount بعملة السند لا الفاتورة (routes/payments.py:786-792).

## 7) المشتريات والمصروفات والموردون
- Purchase: أسطر → مخزون → قيد 1140/2110/2130 → supplier.update_statistics (routes/purchases.py:60-236)؛ أعمدة السداد paid_amount/payment_status أُضيفا بالترحيل 8 (migrations 8).
- Expense: GL على حساب الفئة وإلا '6990' مقابل طريقة الدفع (routes/expenses.py:129-152)؛ **تعديل المصروف لا يولّد قيدًا عكسيًا** (:210-226) — بلا tenant_id أيضًا.
- 🐛 `Purchase.get_paid_amount` يفلتر على أعمدة غير موجودة في Payment → crash مسار كشف المورد (purchase.py:71-73).

## 8) الموارد البشرية
Employee 1:1 User، أرصدة إجازات 30/15/5، خصم عند approve واسترداد عند cancel-approved (hr.py:273-309)؛ Payslip أوفر‌تايم=(base/30/8)×rate ومنع تكرار الفترة (hr_service.py:240-294)؛ bulk payroll يجمع النجاح والأخطاء (:297). ⚠️ Payslip.gl_journal_entry_id موجود ولا يُكتب أبدًا — رابط GL ميت (hr.py:368).

## 9) وحدات ERP الموسعة (erp_modules_service)
Quotation (تحويل لبيع حقيقي) · PurchaseOrder (استلام جزئي ينشئ Purchase) · FiscalPeriod (إغلاق/فتح) · StockTransfer (خصم/إضافة عبر adjust_stock → ⚠️ يلوّث قيود تسوية 5150) · StockTake (⚠️ يلتقط كل المنتجات متجاهلاً المستودع) · Dunning (مستويات 1-4 عند ≥15 يومًا) · RecurringExpense (⚠️ user_id=1 ثابت) · EInvoice EN16931 XML/JSON.

## 10) التحليلات والتقارير
18 تقريرًا + 4 تصديرات (xlsx يدوي openpyxl بـRTL، pdf weasyprint بسلسلة HTML داخل الكود) (routes/reports.py) · cash_flow تشغيلي/استثماري/تمويلي من GL (cash_flow_service.py:26-71) · aging بشرائح 0-30…+120 مع `_day_end` ضد خلل منتصف الليل (aging_analysis_service.py:10) · advanced_analytics نسب مالية من بادئات الأكواد.
⚠️ تقريران مختلفان لنفس الميزان: ledger trial-balance بلا فترات مقابل admin-trial-balance بيوم واحد (ledger.py:72 vs :692).

## 11) التكاملات الخارجية
NOWPayments (إنشاء دفعة/IPN SHA256-json-مرتب) مقابل webhook Stripe/NowPayments HMAC-SHA512 خام — **توقيعان متعاردان للبوابة نفسها** (webhook_service.py:37 vs nowpayments_service.py:263) · WhatsApp Ultramsg يرجع success دون فحص جسم الرد (whatsapp_service.py:55-62) · CurrencyService TTL 300s عبر 3 APIs + forex_python + fallback ساكن بمحور ILS.

## 12) الذكاء الاصطناعي — الحقيقة المجردة من الكود
- **حقيقي**: NeuralEngine شبكات sklearn MLP فعلية تُدرَّب وتُحفظ joblib — لكن مجلد neural_models غير موجود على القرص ⇒ كل توقع يسقط لقواعد يدوية حاليًا (neural_engine.py:1998-2038; L851). SemanticMatcher TF-IDF+cosine صادق. MemorySystem JSON بحد 1000.
- **تمثيلي**: TransformersBrain feed_forward=x·4·0.25=هوية! بلا أوزان متعلَّمة (transformers_brain.py:192-204) · MasterBrain ثقة مثبتة 0.9 · ReasoningEngine if/else · AzadResponses راوتر نصي ضخم بـ45 معالجًا · VisionProcessor ستوب كامل يرجع `'INV-XXXX'`.
- **مسار التعلم**: كل رسالة شات + مستمعات DB (في dev/testing فقط) تكتب interactions_log.json (سقف 1000) وlearned_knowledge.json وpatterns.pkl (pickle!). ⚠️ `get_enhanced_response` no-op — «التعلم» لا يحسّن الردود (learning_system.py:440-457)؛ success=True افتراضيًا فمعدل النجاح بلا معنى (:101).
- 🐛 البرومبت يُرسل للمزود **بدون format**: `{message}` حرفيًا ولا تُمرر رسالة المستخدم أبدًا (ai_service.py:861-893)؛ سياق المعرفة يُرمى في `_` (:835).
- 🔴 **Telemetry خارجي**: بصمة جهاز SHA256 + IP عام عبر ipify تُرسل لformsubmit.co مرة/جهاز — تعطيل بـDISABLE_TELEMETRY فقط (utils/telemetry.py:154-189).

## 13) الواجهة
AdminLTE3 + Jinja، قالب أم base.html (1141 سطرًا) يرثه 215 قالبًا · i18n قاموس Python يدوي + dict JS مطابق (لا .po/.mo) (utils/i18n.py:32; static/js/i18n.js) · فلاتر money/num/status_badge بـDecimal+LRM ضد اضطراب Bidi (app.py:47-85) · 112 ملف JS (الأكبر warehouses.js) · 🐛 payment_vault/purchase_detail.html يرث layout.html غير الموجود → TemplateNotFound (:1) · pagination ميت في customers (DataTables عميلًا).

## 14) البنية التحتية والجودة
CI سبع وظائف: lint/security/boot/test(SQLite)/integration(PG+alembic)/repo-security(gitleaks+trivy SARIF)/alembic-smoke (ci.yml:43-378) — **الجات الصارمة 4 فقط؛ lint/security continue-on-error** · تغطية بدون بوابة (fail_under=0) لكن تقارير ظاهرة في Step Summary + artifacts HTML/XML · ترحيلات 1a6dadd0ddb4→8_purchase_payment_tracking · سكربت QA يثبت Trial Balance Δ=0.0000 · ⚠️ chaos test: إدخال قيد غير متوازن مباشرة بالنماذج **يُحفظ صامتًا** — الحماية في طبقة الخدمة فقط (qa_master_reconciliation §5).

## 15) أعلى المزالق الحرجة المتبقية (مرتبة)
1. 🔴 مستمع المورّد يضاعف total_paid (N+1) — events.py:226-253
2. 🔴 سندات غير موزعة تنحرف GL عن Sub-ledger بالتصميم — payment_service.py:120-135
3. 🔴 Purchase.get_paid_amount على أعمدة غير موجودة — purchase.py:71-73
4. 🔴 برومبت AI بلا format — ai_service.py:861
5. 🟠 توزيع سندات يستخدم سعر سند لا سعر فاتورة — payment_service.py:148-152
6. 🟠 merchant يُدين 2115 بدل AR — sale_service.py:239-243
7. 🟠 تعارض توقيعي NOWPayments SHA512/SHA256
8. 🟠 CardPayment base64+CVV / card_hash غير ملحّ
9. 🟠 telemetry خارجي افتراضي
10. 🟡 قفل موزع fail-open + cached() hash() غير مستقر + KEYS حاجبة
