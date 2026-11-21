"""
🌍 Internationalization (i18n) Utilities
دوال مساعدة للترجمة
"""

from flask import session
from flask_babel import gettext, lazy_gettext


def _(text):
    """دالة الترجمة المختصرة"""
    return gettext(text)


def _l(text):
    """دالة الترجمة الكسولة (للاستخدام في النماذج)"""
    return lazy_gettext(text)


def get_current_language():
    """الحصول على اللغة الحالية"""
    try:
        return session.get("language", "ar")
    except RuntimeError:
        return "ar"


def is_rtl():
    """هل اللغة الحالية من اليمين لليسار؟"""
    return get_current_language() == "ar"


TRANSLATIONS = {
    "Save": {"ar": "حفظ", "en": "Save"},
    "Cancel": {"ar": "إلغاء", "en": "Cancel"},
    "Delete": {"ar": "حذف", "en": "Delete"},
    "Edit": {"ar": "تعديل", "en": "Edit"},
    "View": {"ar": "عرض", "en": "View"},
    "Back": {"ar": "رجوع", "en": "Back"},
    "Search": {"ar": "بحث", "en": "Search"},
    "Filter": {"ar": "فلترة", "en": "Filter"},
    "Export": {"ar": "تصدير", "en": "Export"},
    "Print": {"ar": "طباعة", "en": "Print"},
    "Actions": {"ar": "إجراءات", "en": "Actions"},
    "Status": {"ar": "الحالة", "en": "Status"},
    "Active": {"ar": "نشط", "en": "Active"},
    "Inactive": {"ar": "غير نشط", "en": "Inactive"},
    "Yes": {"ar": "نعم", "en": "Yes"},
    "No": {"ar": "لا", "en": "No"},
    "Dashboard": {"ar": "لوحة التحكم", "en": "Dashboard"},
    "Sales": {"ar": "المبيعات", "en": "Sales"},
    "Purchases": {"ar": "المشتريات", "en": "Purchases"},
    "Customers": {"ar": "الزبائن", "en": "Customers"},
    "Suppliers": {"ar": "الموردين", "en": "Suppliers"},
    "Products": {"ar": "المنتجات", "en": "Products"},
    "Warehouse": {"ar": "المستودع", "en": "Warehouse"},
    "Payments": {"ar": "المدفوعات", "en": "Payments"},
    "Expenses": {"ar": "المصروفات", "en": "Expenses"},
    "Reports": {"ar": "التقارير", "en": "Reports"},
    "Ledger": {"ar": "دفتر الأستاذ", "en": "Ledger"},
    "Settings": {"ar": "الإعدادات", "en": "Settings"},
    "Login": {"ar": "تسجيل الدخول", "en": "Login"},
    "Sign In": {"ar": "دخول", "en": "Sign In"},
    "Sign in to start your session": {
        "ar": "تسجيل الدخول للنظام",
        "en": "Sign in to start your session",
    },
    "Username": {"ar": "اسم المستخدم", "en": "Username"},
    "Password": {"ar": "كلمة المرور", "en": "Password"},
    "Remember Me": {"ar": "تذكرني", "en": "Remember Me"},
    "Logout": {"ar": "تسجيل خروج", "en": "Logout"},
    "Name": {"ar": "الاسم", "en": "Name"},
    "Email": {"ar": "البريد الإلكتروني", "en": "Email"},
    "Phone": {"ar": "الهاتف", "en": "Phone"},
    "Address": {"ar": "العنوان", "en": "Address"},
    "Description": {"ar": "الوصف", "en": "Description"},
    "Notes": {"ar": "ملاحظات", "en": "Notes"},
    "Date": {"ar": "التاريخ", "en": "Date"},
    "Amount": {"ar": "المبلغ", "en": "Amount"},
    "Quantity": {"ar": "الكمية", "en": "Quantity"},
    "Price": {"ar": "السعر", "en": "Price"},
    "Total": {"ar": "المجموع", "en": "Total"},
    "Discount": {"ar": "الخصم", "en": "Discount"},
    "Tax": {"ar": "الضريبة", "en": "Tax"},
    "Grand Total": {"ar": "الإجمالي النهائي", "en": "Grand Total"},
    "Success": {"ar": "نجح", "en": "Success"},
    "Error": {"ar": "خطأ", "en": "Error"},
    "Warning": {"ar": "تحذير", "en": "Warning"},
    "Info": {"ar": "معلومة", "en": "Info"},
    "Saved Successfully": {"ar": "تم الحفظ بنجاح", "en": "Saved Successfully"},
    "Deleted Successfully": {"ar": "تم الحذف بنجاح", "en": "Deleted Successfully"},
    "Updated Successfully": {"ar": "تم التحديث بنجاح", "en": "Updated Successfully"},
    "Are you sure?": {"ar": "هل أنت متأكد؟", "en": "Are you sure?"},
    "This action cannot be undone": {
        "ar": "لا يمكن التراجع عن هذا الإجراء",
        "en": "This action cannot be undone",
    },
    "Add": {"ar": "إضافة", "en": "Add"},
    "New": {"ar": "جديد", "en": "New"},
    "Details": {"ar": "تفاصيل", "en": "Details"},
    "Update": {"ar": "تحديث", "en": "Update"},
    "Submit": {"ar": "إرسال", "en": "Submit"},
    "Confirm": {"ar": "تأكيد", "en": "Confirm"},
    "Close": {"ar": "إغلاق", "en": "Close"},
    "New Invoice": {"ar": "فاتورة جديدة", "en": "New Invoice"},
    "Sales List": {"ar": "قائمة المبيعات", "en": "Sales List"},
    "New Customer": {"ar": "زبون جديد", "en": "New Customer"},
    "New Supplier": {"ar": "مورد جديد", "en": "New Supplier"},
    "New Product": {"ar": "منتج جديد", "en": "New Product"},
    "Stock Movements": {"ar": "حركات المخزون", "en": "Stock Movements"},
    "Low Stock": {"ar": "منتجات منخفضة", "en": "Low Stock"},
    "Out of Stock": {"ar": "منتجات نفذت", "en": "Out of Stock"},
    "Sales Report": {"ar": "تقرير المبيعات", "en": "Sales Report"},
    "Trial Balance": {"ar": "ميزان المراجعة", "en": "Trial Balance"},
    "Income Statement": {"ar": "قائمة الدخل", "en": "Income Statement"},
    "Balance Sheet": {"ar": "الميزانية", "en": "Balance Sheet"},
    "Reverse Charge VAT": {"ar": "ضريبة الشحن العكسي", "en": "Reverse Charge VAT"},
    # Keys added by the language recheck pass
    "Owner Mode": {"ar": "وضع المالك", "en": "Owner Mode"},
    "SSL Encrypted": {"ar": "مشفر بـ SSL", "en": "SSL Encrypted"},
    "JSON Payload": {"ar": "بيانات JSON", "en": "JSON Payload"},
    "Reverse Charge": {"ar": "شحن عكسي", "en": "Reverse Charge"},
    "IBAN": {"ar": "رقم الحساب الدولي", "en": "IBAN"},
    "Workshop": {"ar": "ورشة العمل", "en": "Workshop"},
    "API Keys": {"ar": "مفاتيح API", "en": "API Keys"},
    "Audit Trail": {"ar": "سجل التدقيق", "en": "Audit Trail"},
    "Company Logo": {"ar": "شعار الشركة", "en": "Company Logo"},
    "PostgreSQL Connection URI": {"ar": "رابط اتصال PostgreSQL", "en": "PostgreSQL Connection URI"},
    "IPs": {"ar": "عناوين IP", "en": "IPs"},
    "God Mode": {"ar": "وضع المالك", "en": "God Mode"},
    "Dry run": {"ar": "معاينة", "en": "Dry run"},
    "Execute": {"ar": "تنفيذ", "en": "Execute"},
    "IP Address": {"ar": "عنوان IP", "en": "IP Address"},
    "Publishable Key": {"ar": "المفتاح العام", "en": "Publishable Key"},
    "Client ID": {"ar": "معرف العميل", "en": "Client ID"},
    "Client Secret": {"ar": "سر العميل", "en": "Client Secret"},
    "Secret Key": {"ar": "المفتاح السري", "en": "Secret Key"},
    "Super Admin": {"ar": "مدير عام", "en": "Super Admin"},
    "API URL": {"ar": "رابط API", "en": "API URL"},
    "Debug": {"ar": "تشخيص", "en": "Debug"},
    "Aging Report": {"ar": "تقرير الأعمار", "en": "Aging Report"},
    "Company Name LLC": {"ar": "اسم الشركة ذ.م.م", "en": "Company Name LLC"},
    "Bank Details": {"ar": "بيانات البنك", "en": "Bank Details"},
    "Anonymous": {"ar": "مجهول", "en": "Anonymous"},
    "Instant": {"ar": "فوري", "en": "Instant"},
    "Urgent": {"ar": "عاجل", "en": "Urgent"},
    "High": {"ar": "مرتفع", "en": "High"},
    "Normal": {"ar": "عادي", "en": "Normal"},
    "Piece": {"ar": "قطعة", "en": "Piece"},
    "Not specified": {"ar": "غير محدد", "en": "Not specified"},
    "Incoming": {"ar": "وارد", "en": "Incoming"},
    "Outgoing": {"ar": "صادر", "en": "Outgoing"},
    # Keys added by the deep i18n audit pass
    "Payment terms: cash or bank transfer": {"ar": "شروط الدفع: نقداً أو بالتحويل البنكي", "en": "Payment terms: cash or bank transfer"},
    "Payment in cash or by bank transfer": {"ar": "الدفع نقداً أو بالتحويل البنكي", "en": "Payment in cash or by bank transfer"},
    "Please adhere to the specified payment deadlines": {"ar": "نرجو الالتزام بمواعيد الدفع المحددة", "en": "Please adhere to the specified payment deadlines"},
    "Please adhere to the payment deadlines": {"ar": "نرجو الالتزام بمواعيد الدفع", "en": "Please adhere to the payment deadlines"},
    "Thank you for your trust": {"ar": "شكراً لثقتكم", "en": "Thank you for your trust"},
    "Receipt": {"ar": "إيصال", "en": "Receipt"},
    "CR:": {"ar": "السجل التجاري:", "en": "CR:"},
    "Lic:": {"ar": "الرخصة:", "en": "Lic:"},
    "My API Key": {"ar": "مفتاح API الخاص بي", "en": "My API Key"},
    "SMTP Server": {"ar": "خادم SMTP", "en": "SMTP Server"},
    "SMTP Port": {"ar": "منفذ SMTP", "en": "SMTP Port"},
    "From Email": {"ar": "البريد المرسل", "en": "From Email"},
    "API Endpoint URL": {"ar": "رابط نقطة API", "en": "API Endpoint URL"},
    "Redis Host": {"ar": "مضيف Redis", "en": "Redis Host"},
    "Redis Port": {"ar": "منفذ Redis", "en": "Redis Port"},
    "API Provider": {"ar": "مزود API", "en": "API Provider"},
    "API Token / Access Key": {"ar": "رمز API / مفتاح الوصول", "en": "API Token / Access Key"},
    "Payment Terms (English)": {"ar": "شروط الدفع (إنجليزي)", "en": "Payment Terms (English)"},
    "Company Name (English)": {"ar": "اسم الشركة (إنجليزي)", "en": "Company Name (English)"},
    "Address (English)": {"ar": "العنوان (إنجليزي)", "en": "Address (English)"},
    "30-60 days": {"ar": "30-60 يوم", "en": "30-60 days"},
    "60-90 days": {"ar": "60-90 يوم", "en": "60-90 days"},
    "90-120 days": {"ar": "90-120 يوم", "en": "90-120 days"},
    "61-90 days": {"ar": "61-90 يوم", "en": "61-90 days"},
    "31-60 days": {"ar": "31-60 يوم", "en": "31-60 days"},
    "0-30 days": {"ar": "0-30 يوم", "en": "0-30 days"},
    "Aging Analysis": {"ar": "تحليل الأعمار", "en": "Aging Analysis"},
    "IP Whitelist": {"ar": "قائمة عناوين IP المسموحة", "en": "IP Whitelist"},
    "Arabic": {"ar": "العربية", "en": "Arabic"},
    "Moving average cost": {"ar": "متوسط التكلفة المتحرك", "en": "Moving average cost"},
    "Due to supplier": {"ar": "مستحق للمورد", "en": "Due to supplier"},
    "Due to us": {"ar": "مستحق لنا", "en": "Due to us"},
    "Due to customer": {"ar": "مستحق للعميل", "en": "Due to customer"},
    "Back to statement": {"ar": "رجوع للكشف", "en": "Back to statement"},
    "Retained Earnings (cumulative net profit)": {
        "ar": "الأرباح المبقاة (صافي الربح التراكمي)",
        "en": "Retained Earnings (cumulative net profit)",
    },
    "AI Assistant": {"ar": "المساعد الذكي", "en": "AI Assistant"},
    "Pending": {"ar": "معلق", "en": "Pending"},
    "Completed": {"ar": "مكتمل", "en": "Completed"},
    "Cancelled": {"ar": "ملغي", "en": "Cancelled"},
    "Balance": {"ar": "الرصيد", "en": "Balance"},
    "Paid": {"ar": "المدفوع", "en": "Paid"},
    "Remaining": {"ar": "المتبقي", "en": "Remaining"},
    "Code": {"ar": "الكود", "en": "Code"},
    "Today": {"ar": "اليوم", "en": "Today"},
    "All": {"ar": "الكل", "en": "All"},
    "List": {"ar": "قائمة", "en": "List"},
    "Loading": {"ar": "جاري التحميل", "en": "Loading"},
    "Features": {"ar": "المميزات", "en": "Features"},
    "Products Management": {"ar": "إدارة المنتجات", "en": "Products Management"},
    "Sales Management": {"ar": "إدارة المبيعات", "en": "Sales Management"},
    "Complete inventory for all products and parts": {
        "ar": "مخزون شامل لجميع المنتجات والقطع",
        "en": "Complete inventory for all products and parts",
    },
}


# Per-area translation dictionaries live in utils/i18n_keys/agent_*.py.
# They are auto-loaded so several independent contributors can add keys
# without ever editing this shared file (no merge conflicts).
import os as _os
import importlib as _importlib

_KEYS_DIR = _os.path.join(_os.path.dirname(__file__), "i18n_keys")
if _os.path.isdir(_KEYS_DIR):
    for _fn in sorted(_os.listdir(_KEYS_DIR)):
        if _fn.startswith("agent_") and _fn.endswith(".py"):
            _mod = _importlib.import_module(f"utils.i18n_keys.{_fn[:-3]}")
            TRANSLATIONS.update(getattr(_mod, "TRANSLATIONS", {}))


def t(key, **kwargs):
    """
    ترجمة سريعة من القاموس

    Usage:
        t('Save')  # → حفظ (if Arabic) or Save (if English)
        t('Hello {name}', name='Ahmad')
    """
    lang = get_current_language()

    if key in TRANSLATIONS:
        text = TRANSLATIONS[key].get(lang, key)
    else:
        text = key

    if kwargs:
        text = text.format(**kwargs)

    return text
