"""التحقق من صيغة الرقم الضريبي (TRN) حسب الدولة — إرشادي فقط (لا يمنع الحفظ).

يحذر المستخدم ولا يمنع الحفظ؛ الأنظمة لا تُعيد هيكلة المنطق القانوني لكل دولة.
قواعد مهيأة كأهم الشائعة: AE السعودية مصر الأردن تركيا بريطانيا ألمانيا.
كل دولة: يُقارن النمط (طول/بادئة) فقط بدون أي تحقق من checksum ضد السلطة.
"""

import re

_TRN_PATTERNS = {
    "AE": re.compile(r"^\d{15}$"),  # الهوية الضريبية: 15 رقم
    "SA": re.compile(r"^3\d{14}$"),  # السعودية: 15 رقم تبدأ بـ 3
    "EG": re.compile(r"^\d{9}$"),  # مصر: 9 أرقام
    "JO": re.compile(r"^\d{10}$"),  # الأردن: 10 أرقام (TIN)
    "TR": re.compile(r"^\d{10}$"),  # تركيا: 10 أرقام
    "GB": re.compile(r"^\d{9}$|^GB\d{9}$"),  # UK: 9 أرقام عادةً
    "DE": re.compile(r"^DE\d{9}$|^\d{10,11}$"),  # ألمانيا: DE+9 أو 10/11 رقم داخلي
    "OM": re.compile(r"^\d{10,11}$"),  # عمان: 10-11 رقم
    "BH": re.compile(r"^\d{15}$"),  # البحرين: 15 رقم
    "KW": re.compile(r"^\d*$"),  # غير مُفعّلة — غير مقيم
    "QA": re.compile(r"^\d*$"),  # غير مُفعّلة
}


def current_tenant_country_code():
    """ISO-2 للدولة الحالية (أو AE كافتراضي). للاستخدام في تحذيرات TRN."""
    try:
        from extensions import db as _db
        from models import Tenant
        from models.tenant_scope import get_current_tenant_id

        tid = get_current_tenant_id()
        tenant = _db.session.get(Tenant, tid) if tid else None
        return (
            (
                getattr(tenant, "tax_country", None)
                or getattr(tenant, "country", None)
                or "AE"
            )
            .strip()
            .upper()[:2]
        )
    except Exception:
        return "AE"


def trn_verdict(trn, country_code):
    """يعيد (ok: bool, message: str). True للامتثال للنمط أو لعدم وجود قاعدة."""
    trn = (trn or "").strip().upper().replace(" ", "")
    if not trn:
        return True, ""
    code = (country_code or "").strip().upper()[:2]
    pattern = _TRN_PATTERNS.get(code)
    if pattern is None:
        return True, ""
    if pattern.match(trn):
        return True, f"صيغة TRN لـ {code} تبدو صحيحة"
    return False, (
        f'تنبيه: الرقم الضريبي "{trn}" لا يطابق صيغة {code} المتوقعة — '
        "يُحفظ رغم ذلك، والمراجعة بمحاسب الدولة النهائية مطلوبة"
    )
