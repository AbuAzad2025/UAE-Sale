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

