"""
AI Flows Registry — سجل التدفقات الموحّد (Phase 2)

الغرض: إزالة نسخ-لصق قوائم العمل الثلاث عشرة من routes/ai.py
بدون تغيير السلوك أو كسر أي تنقل قائم.

كل "تدفق" (flow) يعرّف:
- keywords: كلمات المفتاح بالعربية/الإنجليزية
- menu_title: عنوان القائمة
- options: [(رقم, نص)] — نفس النصوص الحالية تماماً
- example_label: نص المثال (مثال: اكتب "1" لإضافة عميل جديد)
- permission: كود الصلاحية المطلوب للتهيئة (لا يمنع القائمة، يشرح فقط)
- last_action: مفتاح السياق (نفس القيم الحالية 'عميل' إلخ)

الـ handler الفعلي للخطوات يبقى في routes/ai.py (Phase 2b سيستخرجه)
ولكن الـ dispatch (إظهار القائمة) يصبح table-driven.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlowDef:
    key: str
    keywords: tuple
    menu_title: str
    options: tuple  # tuple[tuple[str, str]]
    example_label: str
    permission: str
    last_action: str
    confirm_required: bool = False
    tenant_required: bool = True


FLOWS: tuple[FlowDef, ...] = (
    FlowDef(
        key="balance",
        keywords=("رصيد", "رصيد العميل", "رصيد عميل", "تعديل رصيد"),
        menu_title="تريد التعامل مع رصيد العميل. إليك الخيارات",
        options=(
            ("1", "تعديل رصيد العميل"),
            ("2", "استلام دفعة من العميل"),
            ("3", "إعطاء دفعة للعميل"),
            ("4", "عرض رصيد العميل"),
        ),
        example_label='اكتب "1" لتعديل رصيد العميل',
        permission="manage_customers",
        last_action="رصيد",
        confirm_required=True,
    ),
    FlowDef(
        key="customer",
        keywords=(
            "عميل",
            "عميل جديد",
            "إضافة عميل",
            "إنشاء عميل",
            "زبون",
            "زبونه",
            "زبون جديد",
            "إضافة زبون",
        ),
        menu_title="تريد إضافة عميل جديد. إليك الخيارات",
        options=(
            ("1", "إضافة عميل جديد"),
            ("2", "عرض جميع العملاء"),
            ("3", "البحث عن عميل"),
        ),
        example_label='اكتب "1" لإضافة عميل جديد',
        permission="manage_customers",
        last_action="عميل",
    ),
    FlowDef(
        key="product",
        keywords=("منتج", "منتج جديد", "إضافة منتج", "إنشاء منتج"),
        menu_title="تريد إضافة منتج جديد. إليك الخيارات",
        options=(
            ("1", "إضافة منتج جديد"),
            ("2", "عرض جميع المنتجات"),
            ("3", "البحث عن منتج"),
            ("4", "رفع منتجات من Excel"),
        ),
        example_label='اكتب "1" لإضافة منتج جديد',
        permission="manage_products",
        last_action="منتج",
    ),
    FlowDef(
        key="sale",
        keywords=(
            "فاتورة",
            "بيع",
            "مبيعات",
            "إنشاء فاتورة",
            "بيع فلتر",
            "فلتر",
            "بيع قطعة",
        ),
        menu_title="تريد إنشاء فاتورة مبيعات. إليك الخيارات",
        options=(
            ("1", "إنشاء فاتورة جديدة"),
            ("2", "عرض جميع الفواتير"),
            ("3", "البحث عن فاتورة"),
        ),
        example_label='اكتب "1" لإنشاء فاتورة جديدة',
        permission="manage_sales",
        last_action="فاتورة",
    ),
    FlowDef(
        key="receive",
        keywords=("استلام", "استلم", "دفعة من"),
        menu_title="تريد استلام دفعة من عميل. إليك الخيارات",
        options=(
            ("1", "استلام دفعة من عميل"),
            ("2", "عرض جميع الدفعات"),
            ("3", "البحث عن دفعة"),
        ),
        example_label='اكتب "1" لاستلام دفعة من عميل',
        permission="manage_payments",
        last_action="استلام",
    ),
    FlowDef(
        key="give",
        keywords=("إعطاء", "أعطى", "دفعة لل", "دفعة ل"),
        menu_title="تريد إعطاء دفعة للعميل. إليك الخيارات",
        options=(
            ("1", "إعطاء دفعة للعميل"),
            ("2", "عرض جميع الدفعات المعطاة"),
            ("3", "البحث عن دفعة معطاة"),
        ),
        example_label='اكتب "1" لإعطاء دفعة للعميل',
        permission="manage_payments",
        last_action="إعطاء",
    ),
    FlowDef(
        key="expense",
        keywords=("مصروف", "إضافة مصروف", "إنشاء مصروف"),
        menu_title="تريد إضافة مصروف. إليك الخيارات",
        options=(
            ("1", "إضافة مصروف جديد"),
            ("2", "عرض جميع المصروفات"),
            ("3", "البحث عن مصروف"),
        ),
        example_label='اكتب "1" لإضافة مصروف جديد',
        permission="manage_expenses",
        last_action="مصروف",
    ),
    FlowDef(
        key="supplier",
        keywords=("مورد", "مورد جديد", "إضافة مورد", "إنشاء مورد"),
        menu_title="تريد إضافة مورد جديد. إليك الخيارات",
        options=(
            ("1", "إضافة مورد جديد"),
            ("2", "عرض جميع الموردين"),
            ("3", "البحث عن مورد"),
        ),
        example_label='اكتب "1" لإضافة مورد جديد',
        permission="manage_suppliers",
        last_action="مورد",
    ),
    FlowDef(
        key="purchase",
        keywords=("مشتريات", "شراء", "إضافة مشتريات", "إنشاء مشتريات"),
        menu_title="تريد إضافة مشتريات. إليك الخيارات",
        options=(
            ("1", "إضافة مشتريات جديدة"),
            ("2", "عرض جميع المشتريات"),
            ("3", "البحث عن مشتريات"),
        ),
        example_label='اكتب "1" لإضافة مشتريات جديدة',
        permission="manage_purchases",
        last_action="مشتريات",
    ),
    FlowDef(
        key="cheque",
        keywords=("شيك", "شيكات", "إضافة شيك", "إنشاء شيك"),
        menu_title="تريد إضافة شيك. إليك الخيارات",
        options=(
            ("1", "إضافة شيك جديد"),
            ("2", "عرض جميع الشيكات"),
            ("3", "البحث عن شيك"),
        ),
        example_label='اكتب "1" لإضافة شيك جديد',
        permission="manage_payments",
        last_action="شيك",
    ),
    FlowDef(
        key="ledger",
        keywords=("دفتر", "دفتر الأستاذ", "دفتر استاذ", "قيد"),
        menu_title="تريد التعامل مع دفتر الأستاذ. إليك الخيارات",
        options=(
            ("1", "عرض دفتر الأستاذ"),
            ("2", "البحث في القيود"),
        ),
        example_label='اكتب "1" لعرض دفتر الأستاذ',
        permission="manage_ledger",
        last_action="دفتر",
    ),
    FlowDef(
        key="warehouse",
        keywords=("مستودع", "مستودعات", "مخزون", "إدارة مستودعات"),
        menu_title="تريد إدارة المستودعات. إليك الخيارات",
        options=(
            ("1", "عرض جميع المستودعات"),
            ("2", "عرض المخزون"),
            ("3", "البحث عن مستودع"),
        ),
        example_label='اكتب "1" لعرض جميع المستودعات',
        permission="manage_warehouse",
        last_action="مستودع",
    ),
    FlowDef(
        key="user",
        keywords=("مستخدم", "مستخدمين", "إضافة مستخدم", "إنشاء مستخدم"),
        menu_title="تريد إدارة المستخدمين. إليك الخيارات",
        options=(
            ("1", "إضافة مستخدم جديد"),
            ("2", "عرض جميع المستخدمين"),
            ("3", "البحث عن مستخدم"),
        ),
        example_label='اكتب "1" لإضافة مستخدم جديد',
        permission="manage_users",
        last_action="مستخدم",
    ),
)

FLOWS_BY_KEY: dict[str, FlowDef] = {f.key: f for f in FLOWS}


def find_flow(msg_lower: str) -> FlowDef | None:
    """IVR matching بـ score — الأكثر تخصيصاً يفوز، والأقدم يفوز بالتعادل.

    قبل: first-match صارم كان ينقلب على "فاتورة جديدة لعميل" إلى `customer`
    لأن "عميل" يظهر قبل "فاتورة". الآن: درجة = مجموع أطوال الكلمات
    المطابقة + 5 كلما ظهر عبارة إنشائية؟ لا — نحافظ على البساطة:
    أعلى درجة (مع تجميع متعدد الكلمات) يفوز.
    ملاحظة: الكلمات المفتاحية تُطبَّع (نفس تطبيع الرسالة) حتى يطابق
    "فاتورة" مع "فاتوره" و"العميل" مع "عميل".
    """
    from services.ai_normalize import normalize as _normalize

    best: FlowDef | None = None
    best_score = 0
    for flow in FLOWS:
        score = 0
        for k in flow.keywords:
            nk = _normalize(k)
            if nk and nk in msg_lower:
                score += len(nk)
                if " " in nk:
                    score += 10  # عبارة مخصصة أثقل
        if score > best_score:
            best_score = score
            best = flow
    return best


def render_menu(flow: FlowDef) -> str:
    """إنتاج نص القائمة — نفس الصياغة الحالية (compat)."""
    lines = [f"🤖 فهمت! {flow.menu_title}", "", "📋 **ما الذي تريد فعله؟**"]
    emoji_map = {"1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣"}
    for num, label in flow.options:
        lines.append(f"{emoji_map.get(num, num)} **{label}**")
    n = len(flow.options)
    if n == 2:
        hint_range = "1 أو 2"
    elif n == 3:
        hint_range = "1، 2، أو 3"
    elif n >= 4:
        hint_range = "1، 2، 3، أو 4"
    else:
        hint_range = "1"
    lines.extend(
        [
            "",
            f"💡 **اكتب رقم الخيار ({hint_range}) وسأرشدك خطوة بخطوة!**",
            "",
            f"🤖 مثال: {flow.example_label}",
        ]
    )
    return "\n".join(lines)


def start_context(flow: FlowDef) -> dict:
    return {"last_action": flow.last_action, "step": 0}


__all__ = [
    "FlowDef",
    "FLOWS",
    "FLOWS_BY_KEY",
    "find_flow",
    "render_menu",
    "start_context",
]
