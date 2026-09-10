CUSTOMER_TYPES = [
    ('regular', {'ar': 'عادي', 'en': 'Regular'}),
    ('merchant', {'ar': 'تاجر', 'en': 'Merchant'}),
    ('partner', {'ar': 'شريك', 'en': 'Partner'}),
]

CUSTOMER_CLASSIFICATIONS = [
    ('vip', {'ar': 'VIP - عميل مميز', 'en': 'VIP', 'threshold': 100000}),
    ('premium', {'ar': 'ممتاز', 'en': 'Premium', 'threshold': 50000}),
    ('regular', {'ar': 'عادي', 'en': 'Regular', 'threshold': 0}),
    ('inactive', {'ar': 'غير نشط', 'en': 'Inactive', 'threshold': 0}),
]

PAYMENT_METHODS = [
    ('cash', {'ar': 'نقدي', 'en': 'Cash'}),
    ('card', {'ar': 'بطاقة', 'en': 'Card'}),
    ('bank_transfer', {'ar': 'تحويل بنكي', 'en': 'Bank Transfer'}),
    ('cheque', {'ar': 'شيك', 'en': 'Cheque'}),
    ('e_wallet', {'ar': 'محفظة إلكترونية', 'en': 'E-Wallet'}),
]

PAYMENT_STATUSES = [
    ('paid', {'ar': 'مدفوع', 'en': 'Paid'}),
    ('partial', {'ar': 'جزئي', 'en': 'Partial'}),
    ('unpaid', {'ar': 'غير مدفوع', 'en': 'Unpaid'}),
]

SALE_STATUSES = [
    ('confirmed', {'ar': 'مؤكدة', 'en': 'Confirmed'}),
    ('cancelled', {'ar': 'ملغاة', 'en': 'Cancelled'}),
]

PURCHASE_STATUSES = [
    ('confirmed', {'ar': 'مؤكدة', 'en': 'Confirmed'}),
    ('cancelled', {'ar': 'ملغاة', 'en': 'Cancelled'}),
]

STOCK_MOVEMENT_TYPES = [
    ('purchase', {'ar': 'شراء', 'en': 'Purchase'}),
    ('sale', {'ar': 'بيع', 'en': 'Sale'}),
    ('adjustment', {'ar': 'تسوية', 'en': 'Adjustment'}),
    ('return', {'ar': 'إرجاع', 'en': 'Return'}),
    ('damage', {'ar': 'تالف', 'en': 'Damage'}),
]

USER_ROLES = [
    ('super_admin', {'ar': 'سوبر أدمن', 'en': 'Super Admin'}),
    ('manager', {'ar': 'مدير', 'en': 'Manager'}),
    ('seller', {'ar': 'بائع', 'en': 'Seller'}),
]

CURRENCIES = [
    ('ILS', {'ar': 'شيقل', 'en': 'Israeli Shekel', 'symbol': '₪'}),
    ('JOD', {'ar': 'دينار أردني', 'en': 'Jordanian Dinar', 'symbol': 'د.أ'}),
    ('AED', {'ar': 'درهم إماراتي', 'en': 'UAE Dirham', 'symbol': 'د.إ'}),
    ('USD', {'ar': 'دولار أمريكي', 'en': 'US Dollar', 'symbol': '$'}),
    ('EUR', {'ar': 'يورو', 'en': 'Euro', 'symbol': '€'}),
    ('GBP', {'ar': 'جنيه إسترليني', 'en': 'British Pound', 'symbol': '£'}),
    ('SAR', {'ar': 'ريال سعودي', 'en': 'Saudi Riyal', 'symbol': 'ر.س'}),
    ('KWD', {'ar': 'دينار كويتي', 'en': 'Kuwaiti Dinar', 'symbol': 'د.ك'}),
    ('QAR', {'ar': 'ريال قطري', 'en': 'Qatari Riyal', 'symbol': 'ر.ق'}),
    ('OMR', {'ar': 'ريال عماني', 'en': 'Omani Rial', 'symbol': 'ر.ع'}),
    ('BHD', {'ar': 'دينار بحريني', 'en': 'Bahraini Dinar', 'symbol': 'د.ب'}),
]

PRODUCT_UNITS = [
    ('piece', {'ar': 'قطعة', 'en': 'Piece'}),
    ('kg', {'ar': 'كيلوجرام', 'en': 'Kilogram'}),
    ('liter', {'ar': 'لتر', 'en': 'Liter'}),
    ('meter', {'ar': 'متر', 'en': 'Meter'}),
    ('box', {'ar': 'صندوق', 'en': 'Box'}),
    ('set', {'ar': 'مجموعة', 'en': 'Set'}),
]

# ── Tenant profile constants (system constants, like CURRENCIES) ─────────
# Single source of truth for tenant dropdowns (tenant_form + company_info).
# Codes are stable identifiers stored in the DB; labels are display-only.

TENANT_BUSINESS_TYPES = [
    ('garage', {'ar': 'كراج', 'en': 'Garage'}),
    ('workshop', {'ar': 'ورشة', 'en': 'Workshop'}),
    ('spare_parts', {'ar': 'قطع غيار', 'en': 'Spare Parts'}),
    ('batteries', {'ar': 'بطاريات', 'en': 'Batteries'}),
    ('retail', {'ar': 'تجزئة', 'en': 'Retail'}),
    ('wholesale', {'ar': 'جملة', 'en': 'Wholesale'}),
    ('maintenance', {'ar': 'صيانة', 'en': 'Maintenance'}),
    ('other', {'ar': 'أخرى', 'en': 'Other'}),
]

TENANT_INDUSTRIES = [
    ('automotive', {'ar': 'سيارات', 'en': 'Automotive'}),
    ('heavy_equipment', {'ar': 'معدات ثقيلة', 'en': 'Heavy Equipment'}),
    ('batteries_energy', {'ar': 'بطاريات وطاقة', 'en': 'Batteries & Energy'}),
    ('retail_trade', {'ar': 'تجارة تجزئة', 'en': 'Retail Trade'}),
    ('maintenance_services', {'ar': 'خدمات صيانة', 'en': 'Maintenance Services'}),
    ('mixed', {'ar': 'مختلط', 'en': 'Mixed'}),
    ('other', {'ar': 'أخرى', 'en': 'Other'}),
]

TENANT_CITIES = [
    ('Dubai', {'ar': 'دبي', 'en': 'Dubai'}),
    ('Abu Dhabi', {'ar': 'أبوظبي', 'en': 'Abu Dhabi'}),
    ('Sharjah', {'ar': 'الشارقة', 'en': 'Sharjah'}),
    ('Ajman', {'ar': 'عجمان', 'en': 'Ajman'}),
    ('Ras Al Khaimah', {'ar': 'رأس الخيمة', 'en': 'Ras Al Khaimah'}),
    ('Fujairah', {'ar': 'الفجيرة', 'en': 'Fujairah'}),
    ('Umm Al Quwain', {'ar': 'أم القيوين', 'en': 'Umm Al Quwain'}),
    ('Ramallah', {'ar': 'رام الله', 'en': 'Ramallah'}),
    ('Nablus', {'ar': 'نابلس', 'en': 'Nablus'}),
    ('Hebron', {'ar': 'الخليل', 'en': 'Hebron'}),
    ('Jerusalem', {'ar': 'القدس', 'en': 'Jerusalem'}),
    ('Amman', {'ar': 'عمّان', 'en': 'Amman'}),
    ('Riyadh', {'ar': 'الرياض', 'en': 'Riyadh'}),
    ('Jeddah', {'ar': 'جدة', 'en': 'Jeddah'}),
    ('Cairo', {'ar': 'القاهرة', 'en': 'Cairo'}),
    ('other', {'ar': 'أخرى', 'en': 'Other'}),
]

TENANT_COUNTRIES = [
    ('UAE', {'ar': 'الإمارات', 'en': 'UAE'}),
    ('Palestine', {'ar': 'فلسطين', 'en': 'Palestine'}),
    ('Jordan', {'ar': 'الأردن', 'en': 'Jordan'}),
    ('Saudi', {'ar': 'السعودية', 'en': 'Saudi Arabia'}),
    ('Egypt', {'ar': 'مصر', 'en': 'Egypt'}),
    ('Kuwait', {'ar': 'الكويت', 'en': 'Kuwait'}),
    ('Qatar', {'ar': 'قطر', 'en': 'Qatar'}),
    ('Bahrain', {'ar': 'البحرين', 'en': 'Bahrain'}),
    ('Oman', {'ar': 'عُمان', 'en': 'Oman'}),
    ('other', {'ar': 'أخرى', 'en': 'Other'}),
]

# ── General display constants (single source of truth) ──────────────────
# Display/choice lists previously hardcoded across templates.  Codes marked
# locked_* in LOOKUP_GROUPS drive application logic and must never be
# renamed/removed by the owner UI (labels may be edited).

WARRANTY_UNITS = [
    ('days', {'ar': 'يوم', 'en': 'Days'}),
    ('months', {'ar': 'شهر', 'en': 'Months'}),
    ('years', {'ar': 'سنة', 'en': 'Years'}),
]

SUPPLIER_TYPES = [
    ('parts', {'ar': 'قطع غيار', 'en': 'Spare Parts'}),
    ('equipment', {'ar': 'معدات', 'en': 'Equipment'}),
    ('services', {'ar': 'خدمات', 'en': 'Services'}),
    ('materials', {'ar': 'مواد خام', 'en': 'Raw Materials'}),
    ('other', {'ar': 'أخرى', 'en': 'Other'}),
]

SUPPLIER_RATINGS = [
    ('1', {'ar': '⭐', 'en': '1 star'}),
    ('2', {'ar': '⭐⭐', 'en': '2 stars'}),
    ('3', {'ar': '⭐⭐⭐', 'en': '3 stars'}),
    ('4', {'ar': '⭐⭐⭐⭐', 'en': '4 stars'}),
    ('5', {'ar': '⭐⭐⭐⭐⭐', 'en': '5 stars'}),
]

CONTRACT_TYPES = [
    ('full_time', {'ar': 'دوام كامل', 'en': 'Full Time'}),
    ('part_time', {'ar': 'دوام جزئي', 'en': 'Part Time'}),
    ('contract', {'ar': 'عقد مؤقت', 'en': 'Contract'}),
    ('intern', {'ar': 'تدريب', 'en': 'Intern'}),
]

EMPLOYMENT_STATUSES = [
    ('active', {'ar': 'نشط', 'en': 'Active'}),
    ('on_leave', {'ar': 'في إجازة', 'en': 'On Leave'}),
    ('terminated', {'ar': 'منتهي الخدمة', 'en': 'Terminated'}),
    ('resigned', {'ar': 'مستقيل', 'en': 'Resigned'}),
]

GENDERS = [
    ('male', {'ar': 'ذكر', 'en': 'Male'}),
    ('female', {'ar': 'أنثى', 'en': 'Female'}),
]

MARITAL_STATUSES = [
    ('single', {'ar': 'أعزب', 'en': 'Single'}),
    ('married', {'ar': 'متزوج', 'en': 'Married'}),
    ('divorced', {'ar': 'مطلق', 'en': 'Divorced'}),
    ('widowed', {'ar': 'أرمل', 'en': 'Widowed'}),
]

PAYMENT_FREQUENCIES = [
    ('monthly', {'ar': 'شهري', 'en': 'Monthly'}),
    ('bi_weekly', {'ar': 'نصف شهري', 'en': 'Bi-weekly'}),
    ('weekly', {'ar': 'أسبوعي', 'en': 'Weekly'}),
]

LEAVE_STATUSES = [
    ('pending', {'ar': 'قيد المراجعة', 'en': 'Pending'}),
    ('approved', {'ar': 'موافق عليه', 'en': 'Approved'}),
    ('rejected', {'ar': 'مرفوض', 'en': 'Rejected'}),
    ('cancelled', {'ar': 'ملغي', 'en': 'Cancelled'}),
]

CHEQUE_TYPES = [
    ('incoming', {'ar': 'وارد', 'en': 'Incoming'}),
    ('outgoing', {'ar': 'صادر', 'en': 'Outgoing'}),
]

CHEQUE_STATUSES = [
    ('pending', {'ar': 'قيد الانتظار', 'en': 'Pending'}),
    ('deposited', {'ar': 'مودع', 'en': 'Deposited'}),
    ('cleared', {'ar': 'محصّل', 'en': 'Cleared'}),
    ('bounced', {'ar': 'مرتجع', 'en': 'Bounced'}),
    ('cancelled', {'ar': 'ملغي', 'en': 'Cancelled'}),
    ('under_collection', {'ar': 'تحت التحصيل', 'en': 'Under Collection'}),
]

RECURRING_FREQUENCIES = [
    ('monthly', {'ar': 'شهري', 'en': 'Monthly'}),
    ('quarterly', {'ar': 'ربع سنوي', 'en': 'Quarterly'}),
    ('annual', {'ar': 'سنوي', 'en': 'Annual'}),
]

INVOICE_TEMPLATES = [
    ('modern', {'ar': 'عصري', 'en': 'Modern'}),
    ('classic', {'ar': 'كلاسيكي', 'en': 'Classic'}),
    ('minimal', {'ar': 'بسيط', 'en': 'Minimal'}),
    ('gulf', {'ar': 'خليجي', 'en': 'Gulf'}),
    ('simple', {'ar': 'مبسط', 'en': 'Simple'}),
]

PAPER_SIZES = [
    ('A4', {'ar': 'A4', 'en': 'A4'}),
    ('A5', {'ar': 'A5', 'en': 'A5'}),
    ('Letter', {'ar': 'Letter', 'en': 'Letter'}),
]

ORIENTATIONS = [
    ('portrait', {'ar': 'عمودي', 'en': 'Portrait'}),
    ('landscape', {'ar': 'أفقي', 'en': 'Landscape'}),
]

LANGUAGES = [
    ('ar', {'ar': 'العربية', 'en': 'Arabic'}),
    ('en', {'ar': 'الإنجليزية', 'en': 'English'}),
]

INVOICE_LANGUAGES = [
    ('ar', {'ar': 'عربي', 'en': 'Arabic'}),
    ('en', {'ar': 'إنجليزي', 'en': 'English'}),
    ('both', {'ar': 'ثنائي اللغة', 'en': 'Bilingual'}),
]

TIMEZONES = [
    ('Asia/Dubai', {'ar': 'دبي', 'en': 'Dubai (UTC+4)'}),
    ('Asia/Riyadh', {'ar': 'الرياض', 'en': 'Riyadh (UTC+3)'}),
    ('Asia/Jerusalem', {'ar': 'القدس', 'en': 'Jerusalem (UTC+2)'}),
    ('Asia/Amman', {'ar': 'عمّان', 'en': 'Amman (UTC+2)'}),
    ('Asia/Qatar', {'ar': 'قطر', 'en': 'Qatar (UTC+3)'}),
    ('Asia/Kuwait', {'ar': 'الكويت', 'en': 'Kuwait (UTC+3)'}),
    ('Africa/Cairo', {'ar': 'القاهرة', 'en': 'Cairo (UTC+2)'}),
    ('UTC', {'ar': 'التوقيت العالمي', 'en': 'UTC'}),
]

SUBSCRIPTION_PLANS = [
    ('basic', {'ar': 'أساسية', 'en': 'Basic'}),
    ('pro', {'ar': 'احترافية', 'en': 'Pro'}),
    ('enterprise', {'ar': 'مؤسسات', 'en': 'Enterprise'}),
]

APPROVAL_ENTITY_TYPES = [
    ('sale', {'ar': 'مبيعات', 'en': 'Sales'}),
    ('payment', {'ar': 'مدفوعات', 'en': 'Payments'}),
    ('purchase', {'ar': 'مشتريات', 'en': 'Purchases'}),
]

APPROVAL_STATUSES = [
    ('pending', {'ar': 'معلق', 'en': 'Pending'}),
    ('approved', {'ar': 'موافق عليه', 'en': 'Approved'}),
    ('rejected', {'ar': 'مرفوض', 'en': 'Rejected'}),
]

TENANT_STATUSES = [
    ('active', {'ar': 'نشط', 'en': 'Active'}),
    ('suspended', {'ar': 'موقوف', 'en': 'Suspended'}),
    ('inactive', {'ar': 'غير نشط', 'en': 'Inactive'}),
]

STATEMENT_FILTERS = [
    ('all', {'ar': 'كل الحركات', 'en': 'All'}),
    ('sale', {'ar': 'الفواتير فقط', 'en': 'Sales only'}),
    ('payment', {'ar': 'الدفعات فقط', 'en': 'Payments only'}),
]

PARTY_TYPES = [
    ('customer', {'ar': 'عميل', 'en': 'Customer'}),
    ('supplier', {'ar': 'مورد', 'en': 'Supplier'}),
]

EWALLETS = [
    ('paypal', {'ar': 'PayPal', 'en': 'PayPal'}),
    ('apple_pay', {'ar': 'Apple Pay', 'en': 'Apple Pay'}),
    ('google_pay', {'ar': 'Google Pay', 'en': 'Google Pay'}),
    ('samsung_pay', {'ar': 'Samsung Pay', 'en': 'Samsung Pay'}),
    ('other', {'ar': 'أخرى', 'en': 'Other'}),
]

CARD_TYPES = [
    ('visa', {'ar': 'فيزا', 'en': 'Visa'}),
    ('mastercard', {'ar': 'ماستركارد', 'en': 'Mastercard'}),
    ('amex', {'ar': 'أمريكان إكسبريس', 'en': 'Amex'}),
    ('other', {'ar': 'أخرى', 'en': 'Other'}),
]

CRYPTO_TYPES = [
    ('btc', {'ar': 'بيتكوين', 'en': 'Bitcoin'}),
    ('eth', {'ar': 'إيثيريوم', 'en': 'Ethereum'}),
    ('usdt', {'ar': 'تيثر', 'en': 'Tether'}),
    ('usdc', {'ar': 'يو إس دي كوين', 'en': 'USD Coin'}),
    ('bnb', {'ar': 'بي إن بي', 'en': 'BNB'}),
]

AUDIT_ACTIONS = [
    ('create', {'ar': 'إنشاء', 'en': 'Create'}),
    ('update', {'ar': 'تعديل', 'en': 'Update'}),
    ('delete', {'ar': 'حذف', 'en': 'Delete'}),
    ('archive', {'ar': 'أرشفة', 'en': 'Archive'}),
    ('restore', {'ar': 'استعادة', 'en': 'Restore'}),
    ('login', {'ar': 'دخول', 'en': 'Login'}),
    ('logout', {'ar': 'خروج', 'en': 'Logout'}),
]

SMTP_ENCRYPTIONS = [
    ('tls', {'ar': 'TLS', 'en': 'TLS'}),
    ('ssl', {'ar': 'SSL', 'en': 'SSL'}),
    ('none', {'ar': 'بدون', 'en': 'None'}),
]

CURRENCY_API_PROVIDERS = [
    ('exchangerate', {'ar': 'ExchangeRate', 'en': 'ExchangeRate'}),
    ('fixer', {'ar': 'Fixer', 'en': 'Fixer'}),
    ('currencyapi', {'ar': 'CurrencyAPI', 'en': 'CurrencyAPI'}),
    ('custom', {'ar': 'مخصص', 'en': 'Custom'}),
]

UPDATE_FREQUENCIES = [
    ('hourly', {'ar': 'كل ساعة', 'en': 'Hourly'}),
    ('daily', {'ar': 'يومي', 'en': 'Daily'}),
    ('manual', {'ar': 'يدوي', 'en': 'Manual'}),
]

BACKUP_FREQUENCIES = [
    ('hourly', {'ar': 'كل ساعة', 'en': 'Hourly'}),
    ('daily', {'ar': 'يومي', 'en': 'Daily'}),
    ('weekly', {'ar': 'أسبوعي', 'en': 'Weekly'}),
    ('monthly', {'ar': 'شهري', 'en': 'Monthly'}),
]

SMS_PROVIDERS = [
    ('twilio', {'ar': 'Twilio', 'en': 'Twilio'}),
    ('nexmo', {'ar': 'Nexmo', 'en': 'Nexmo'}),
    ('local', {'ar': 'محلي', 'en': 'Local'}),
]

API_KEY_SERVICES = [
    ('api', {'ar': 'API', 'en': 'API'}),
    ('integration', {'ar': 'تكامل', 'en': 'Integration'}),
    ('webhook', {'ar': 'ويبهوك', 'en': 'Webhook'}),
    ('mobile', {'ar': 'جوال', 'en': 'Mobile'}),
]

DATE_FORMATS = [
    ('dd/mm/yyyy', {'ar': 'يوم/شهر/سنة', 'en': 'DD/MM/YYYY'}),
    ('mm/dd/yyyy', {'ar': 'شهر/يوم/سنة', 'en': 'MM/DD/YYYY'}),
    ('yyyy-mm-dd', {'ar': 'سنة-شهر-يوم', 'en': 'YYYY-MM-DD'}),
]

NUMBER_FORMATS = [
    ('1,234.56', {'ar': '1,234.56', 'en': '1,234.56'}),
    ('1.234,56', {'ar': '1.234,56', 'en': '1.234,56'}),
    ('1 234,56', {'ar': '1 234,56', 'en': '1 234,56'}),
]

DECIMAL_PLACES = [
    ('2', {'ar': '2', 'en': '2'}),
    ('3', {'ar': '3', 'en': '3'}),
    ('4', {'ar': '4', 'en': '4'}),
]

ACCOUNT_TYPES = [
    ('asset', {'ar': 'أصول', 'en': 'Assets'}),
    ('liability', {'ar': 'خصوم', 'en': 'Liabilities'}),
    ('equity', {'ar': 'حقوق ملكية', 'en': 'Equity'}),
    ('revenue', {'ar': 'إيرادات', 'en': 'Revenue'}),
    ('expense', {'ar': 'مصروفات', 'en': 'Expenses'}),
]

TAX_TYPES = [
    ('customs', {'ar': 'جمارك', 'en': 'Customs'}),
    ('vat', {'ar': 'ضريبة القيمة المضافة', 'en': 'VAT'}),
    ('excise', {'ar': 'انتقائية', 'en': 'Excise'}),
    ('other', {'ar': 'أخرى', 'en': 'Other'}),
]

STOCK_ADJUSTMENT_TYPES = [
    ('add', {'ar': 'إضافة', 'en': 'Add'}),
    ('subtract', {'ar': 'خصم', 'en': 'Subtract'}),
    ('set', {'ar': 'تعيين', 'en': 'Set'}),
]

STOCK_ADJUSTMENT_REASONS = [
    ('purchase', {'ar': 'شراء', 'en': 'Purchase'}),
    ('return', {'ar': 'إرجاع', 'en': 'Return'}),
    ('adjustment', {'ar': 'تسوية', 'en': 'Adjustment'}),
    ('damage', {'ar': 'تلف', 'en': 'Damage'}),
    ('other', {'ar': 'أخرى', 'en': 'Other'}),
]

FISCAL_YEARS = [
    ('calendar', {'ar': 'سنة ميلادية', 'en': 'Calendar year'}),
    ('fiscal', {'ar': 'سنة مالية', 'en': 'Fiscal year'}),
]

NUMBERING_MODES = [
    ('auto', {'ar': 'تلقائي', 'en': 'Auto'}),
    ('manual', {'ar': 'يدوي', 'en': 'Manual'}),
]

CODE_LENGTHS = [
    ('4', {'ar': '4', 'en': '4'}),
    ('6', {'ar': '6', 'en': '6'}),
    ('8', {'ar': '8', 'en': '8'}),
]

ACCOUNT_LEVELS = [
    ('3', {'ar': '3', 'en': '3'}),
    ('4', {'ar': '4', 'en': '4'}),
    ('5', {'ar': '5', 'en': '5'}),
]

PAYPAL_MODES = [
    ('sandbox', {'ar': 'تجريبي', 'en': 'Sandbox'}),
    ('live', {'ar': 'حي', 'en': 'Live'}),
]

DB_TARGETS = [
    ('postgresql', {'ar': 'PostgreSQL', 'en': 'PostgreSQL'}),
    ('mysql', {'ar': 'MySQL', 'en': 'MySQL'}),
]

CLEANUP_SCOPES = [
    ('logs', {'ar': 'السجلات', 'en': 'Logs'}),
    ('archived', {'ar': 'المؤرشف', 'en': 'Archived'}),
]

QUOTATION_STATUSES = [
    ('sent', {'ar': 'مرسلة', 'en': 'Sent'}),
    ('accepted', {'ar': 'مقبولة', 'en': 'Accepted'}),
    ('rejected', {'ar': 'مرفوضة', 'en': 'Rejected'}),
]

PAYROLL_STATUSES = [
    ('draft', {'ar': 'مسودة', 'en': 'Draft'}),
    ('approved', {'ar': 'معتمدة', 'en': 'Approved'}),
    ('paid', {'ar': 'مدفوعة', 'en': 'Paid'}),
]

DONATION_STATUSES = [
    ('completed', {'ar': 'مكتملة', 'en': 'Completed'}),
    ('pending', {'ar': 'معلقة', 'en': 'Pending'}),
    ('failed', {'ar': 'فاشلة', 'en': 'Failed'}),
]

VAULT_REPORT_SCOPES = [
    ('all', {'ar': 'الكل', 'en': 'All'}),
    ('purchases', {'ar': 'المشتريات فقط', 'en': 'Purchases only'}),
    ('donations', {'ar': 'التبرعات فقط', 'en': 'Donations only'}),
]

SEARCH_PARTNER_TYPES = [
    ('supplier', {'ar': 'مورد', 'en': 'Supplier'}),
    ('customer', {'ar': 'عميل', 'en': 'Customer'}),
    ('partner', {'ar': 'شريك', 'en': 'Partner'}),
    ('merchant', {'ar': 'تاجر', 'en': 'Merchant'}),
]

ACTIVE_FLAGS = [
    ('1', {'ar': 'نشط', 'en': 'Active'}),
    ('0', {'ar': 'غير نشط', 'en': 'Inactive'}),
]

AI_PROVIDERS = [
    ('openai', {'ar': 'OpenAI', 'en': 'OpenAI (GPT-4)'}),
    ('gemini', {'ar': 'جيميناي', 'en': 'Google Gemini'}),
]

PROFESSIONAL_REPORT_TYPES = [
    ('all', {'ar': 'جميع التقارير', 'en': 'All reports'}),
    ('revenue', {'ar': 'الإيرادات', 'en': 'Revenue'}),
    ('expenses', {'ar': 'المصروفات', 'en': 'Expenses'}),
    ('profit', {'ar': 'الأرباح', 'en': 'Profit'}),
    ('comparison', {'ar': 'المقارنات', 'en': 'Comparison'}),
]

YES_NO_FLAGS = [
    ('1', {'ar': 'نعم', 'en': 'Yes'}),
    ('0', {'ar': 'لا', 'en': 'No'}),
]


# ── Lookup group registry ────────────────────────────────────────────────
# Each group points at a constant above and declares owner-UI capabilities:
#   locked_codes : codes drive application logic — never rename/remove/disable
#   allow_add    : owner may append new codes
#   allow_disable: owner may hide codes from dropdowns
# Labels (ar/en) are always editable — display only, never logic.
LOOKUP_GROUPS = {
    'product_units': {'title_ar': 'وحدات المنتج', 'source': 'PRODUCT_UNITS',
                      'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'warranty_units': {'title_ar': 'وحدات الضمان', 'source': 'WARRANTY_UNITS',
                       'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'customer_types': {'title_ar': 'أنواع العملاء', 'source': 'CUSTOMER_TYPES',
                       'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'payment_methods': {'title_ar': 'طرق الدفع', 'source': 'PAYMENT_METHODS',
                        'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'supplier_types': {'title_ar': 'أنواع الموردين', 'source': 'SUPPLIER_TYPES',
                       'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'supplier_ratings': {'title_ar': 'تقييم الموردين', 'source': 'SUPPLIER_RATINGS',
                         'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'contract_types': {'title_ar': 'أنواع العقود', 'source': 'CONTRACT_TYPES',
                       'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'employment_statuses': {'title_ar': 'الحالات الوظيفية', 'source': 'EMPLOYMENT_STATUSES',
                            'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'genders': {'title_ar': 'الجنس', 'source': 'GENDERS',
                'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'marital_statuses': {'title_ar': 'الحالة الاجتماعية', 'source': 'MARITAL_STATUSES',
                         'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'payment_frequencies': {'title_ar': 'دورية صرف الرواتب', 'source': 'PAYMENT_FREQUENCIES',
                            'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'leave_statuses': {'title_ar': 'حالات الإجازات', 'source': 'LEAVE_STATUSES',
                       'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'cheque_types': {'title_ar': 'أنواع الشيكات', 'source': 'CHEQUE_TYPES',
                     'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'cheque_statuses': {'title_ar': 'حالات الشيكات', 'source': 'CHEQUE_STATUSES',
                        'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'recurring_frequencies': {'title_ar': 'تكرار المصروفات', 'source': 'RECURRING_FREQUENCIES',
                              'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'invoice_templates': {'title_ar': 'قوالب الفواتير', 'source': 'INVOICE_TEMPLATES',
                          'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'paper_sizes': {'title_ar': 'أحجام الورق', 'source': 'PAPER_SIZES',
                    'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'orientations': {'title_ar': 'اتجاه الصفحة', 'source': 'ORIENTATIONS',
                     'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'languages': {'title_ar': 'اللغات', 'source': 'LANGUAGES',
                  'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'invoice_languages': {'title_ar': 'لغات الفواتير', 'source': 'INVOICE_LANGUAGES',
                          'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'timezones': {'title_ar': 'المناطق الزمنية', 'source': 'TIMEZONES',
                  'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'subscription_plans': {'title_ar': 'خطط الاشتراك', 'source': 'SUBSCRIPTION_PLANS',
                           'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'approval_entities': {'title_ar': 'كيانات الاعتماد', 'source': 'APPROVAL_ENTITY_TYPES',
                          'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'approval_statuses': {'title_ar': 'حالات الاعتماد', 'source': 'APPROVAL_STATUSES',
                          'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'tenant_statuses': {'title_ar': 'حالات المستأجرين', 'source': 'TENANT_STATUSES',
                        'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'statement_filters': {'title_ar': 'مرشحات الكشوفات', 'source': 'STATEMENT_FILTERS',
                          'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'party_types': {'title_ar': 'أنواع الأطراف', 'source': 'PARTY_TYPES',
                    'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'currencies': {'title_ar': 'العملات', 'source': 'CURRENCIES',
                   'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'ewallets': {'title_ar': 'المحافظ الإلكترونية', 'source': 'EWALLETS',
                 'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'card_types': {'title_ar': 'أنواع البطاقات', 'source': 'CARD_TYPES',
                   'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'crypto_types': {'title_ar': 'العملات الرقمية', 'source': 'CRYPTO_TYPES',
                     'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'audit_actions': {'title_ar': 'إجراءات التدقيق', 'source': 'AUDIT_ACTIONS',
                      'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'smtp_encryptions': {'title_ar': 'تشفير SMTP', 'source': 'SMTP_ENCRYPTIONS',
                         'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'currency_providers': {'title_ar': 'مزودو أسعار الصرف', 'source': 'CURRENCY_API_PROVIDERS',
                           'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'update_frequencies': {'title_ar': 'تكرار التحديث', 'source': 'UPDATE_FREQUENCIES',
                           'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'backup_frequencies': {'title_ar': 'تكرار النسخ الاحتياطي', 'source': 'BACKUP_FREQUENCIES',
                           'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'sms_providers': {'title_ar': 'مزودو SMS', 'source': 'SMS_PROVIDERS',
                      'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'api_key_services': {'title_ar': 'خدمات مفاتيح API', 'source': 'API_KEY_SERVICES',
                         'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'date_formats': {'title_ar': 'صيغ التاريخ', 'source': 'DATE_FORMATS',
                     'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'number_formats': {'title_ar': 'صيغ الأرقام', 'source': 'NUMBER_FORMATS',
                       'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'decimal_places': {'title_ar': 'الخانات العشرية', 'source': 'DECIMAL_PLACES',
                       'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'account_types': {'title_ar': 'أنواع الحسابات', 'source': 'ACCOUNT_TYPES',
                      'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'tax_types': {'title_ar': 'أنواع الضرائب', 'source': 'TAX_TYPES',
                  'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'stock_adjustment_types': {'title_ar': 'أنواع تسوية المخزون', 'source': 'STOCK_ADJUSTMENT_TYPES',
                               'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'stock_adjustment_reasons': {'title_ar': 'أسباب تسوية المخزون', 'source': 'STOCK_ADJUSTMENT_REASONS',
                                 'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'fiscal_years': {'title_ar': 'السنة المالية', 'source': 'FISCAL_YEARS',
                     'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'numbering_modes': {'title_ar': 'أنماط الترقيم', 'source': 'NUMBERING_MODES',
                        'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'code_lengths': {'title_ar': 'أطوال الأكواد', 'source': 'CODE_LENGTHS',
                     'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'account_levels': {'title_ar': 'مستويات الحسابات', 'source': 'ACCOUNT_LEVELS',
                       'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'paypal_modes': {'title_ar': 'وضع PayPal', 'source': 'PAYPAL_MODES',
                     'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'db_targets': {'title_ar': 'قواعد التحويل', 'source': 'DB_TARGETS',
                   'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'cleanup_scopes': {'title_ar': 'نطاقات التنظيف', 'source': 'CLEANUP_SCOPES',
                       'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'quotation_statuses': {'title_ar': 'حالات عروض الأسعار', 'source': 'QUOTATION_STATUSES',
                           'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'payroll_statuses': {'title_ar': 'حالات الرواتب', 'source': 'PAYROLL_STATUSES',
                         'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'donation_statuses': {'title_ar': 'حالات التبرعات', 'source': 'DONATION_STATUSES',
                          'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'vault_report_scopes': {'title_ar': 'نطاقات تقارير الخزنة', 'source': 'VAULT_REPORT_SCOPES',
                            'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'search_partner_types': {'title_ar': 'أنواع البحث', 'source': 'SEARCH_PARTNER_TYPES',
                             'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'business_types': {'title_ar': 'أنواع النشاط', 'source': 'TENANT_BUSINESS_TYPES',
                       'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'industries': {'title_ar': 'المجالات', 'source': 'TENANT_INDUSTRIES',
                   'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'cities': {'title_ar': 'المدن', 'source': 'TENANT_CITIES',
               'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'countries': {'title_ar': 'الدول', 'source': 'TENANT_COUNTRIES',
                  'locked_codes': False, 'allow_add': True, 'allow_disable': True},
    'active_flags': {'title_ar': 'حالات النشاط', 'source': 'ACTIVE_FLAGS',
                     'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'ai_providers': {'title_ar': 'مزودو الذكاء الاصطناعي', 'source': 'AI_PROVIDERS',
                     'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'professional_report_types': {'title_ar': 'أنواع التقارير الاحترافية', 'source': 'PROFESSIONAL_REPORT_TYPES',
                                  'locked_codes': True, 'allow_add': False, 'allow_disable': False},
    'yes_no_flags': {'title_ar': 'نعم/لا', 'source': 'YES_NO_FLAGS',
                     'locked_codes': True, 'allow_add': False, 'allow_disable': False},
}

COUNTRIES = [
    ('AE', {'ar': 'الإمارات', 'en': 'UAE'}),
    ('SA', {'ar': 'السعودية', 'en': 'Saudi Arabia'}),
    ('DE', {'ar': 'ألمانيا', 'en': 'Germany'}),
    ('JP', {'ar': 'اليابان', 'en': 'Japan'}),
    ('US', {'ar': 'أمريكا', 'en': 'USA'}),
    ('KR', {'ar': 'كوريا', 'en': 'South Korea'}),
    ('CN', {'ar': 'الصين', 'en': 'China'}),
    ('IT', {'ar': 'إيطاليا', 'en': 'Italy'}),
    ('FR', {'ar': 'فرنسا', 'en': 'France'}),
    ('GB', {'ar': 'بريطانيا', 'en': 'United Kingdom'}),
]

PERMISSIONS = {
    'manage_users': {'ar': 'إدارة المستخدمين', 'en': 'Manage Users'},
    'manage_customers': {'ar': 'إدارة الزبائن', 'en': 'Manage Customers'},
    'manage_products': {'ar': 'إدارة المنتجات', 'en': 'Manage Products'},
    'manage_sales': {'ar': 'إدارة المبيعات', 'en': 'Manage Sales'},
    'manage_purchases': {'ar': 'إدارة المشتريات', 'en': 'Manage Purchases'},
    'manage_payments': {'ar': 'إدارة المدفوعات', 'en': 'Manage Payments'},
    'manage_warehouse': {'ar': 'إدارة المستودع', 'en': 'Manage Warehouse'},
    'manage_expenses': {'ar': 'إدارة المصروفات', 'en': 'Manage Expenses'},
    'view_ledger': {'ar': 'عرض دفتر الأستاذ', 'en': 'View Ledger'},
    'manage_ledger': {'ar': 'إدارة دفتر الأستاذ', 'en': 'Manage Ledger'},
    'view_reports': {'ar': 'عرض التقارير', 'en': 'View Reports'},
    'view_costs': {'ar': 'عرض التكاليف', 'en': 'View Costs'},
    'manage_settings': {'ar': 'إدارة الإعدادات', 'en': 'Manage Settings'},
    'manage_currencies': {'ar': 'إدارة العملات', 'en': 'Manage Currencies'},
    'manage_archive': {'ar': 'إدارة الأرشيف', 'en': 'Manage Archive'},
    'manage_hr': {'ar': 'إدارة الموارد البشرية', 'en': 'Manage HR'},
    'view_hr': {'ar': 'عرض الموارد البشرية', 'en': 'View HR'},
}
