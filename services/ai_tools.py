"""سجل الأدوات المنظم (Tool Registry) — التنفيذ بدل `regex JSON`.

كل أداة: `name + وصف + معاملات + permission + destructive(confirm) + handler`
تُستدعى عبر Services الرسمية فقط (محاسبة/مخزون/تنانتي/تدقيق محفوظ).

يُستخدم من:
- services/ai_planner.py (تخطيط نية → أداة)
- services/ai_service.py (تنفيذ Groq action منظم — بدل `_execute_ai_action`)
- routes/ai.py (تحويل لم يحدث؟ لا: routes تبقى compat؛ الأخطاء هنا للأدوات الجديدة)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    permission: str
    destructive: bool = False  # يتطلب تأكيداً صريحاً قبل التنفيذ
    required_params: tuple = ()
    optional_params: tuple = ()


TOOLS: tuple[ToolDef, ...] = (
    ToolDef(
        "search_customers",
        "بحث عن عميل بالاسم (READ)",
        "manage_customers",
        destructive=False,
        required_params=("query",),
    ),
    ToolDef(
        "get_customer_balance",
        "عرض رصيد عميل (READ)",
        "manage_customers",
        destructive=False,
        required_params=("customer_name",),
    ),
    ToolDef(
        "create_customer",
        "إنشاء عميل جديد",
        "manage_customers",
        destructive=False,
        required_params=("name",),
        optional_params=("phone", "address"),
    ),
    ToolDef(
        "create_product",
        "إنشاء منتج جديد",
        "manage_products",
        destructive=False,
        required_params=("name",),
        optional_params=("part_number", "price", "quantity", "cost_price"),
    ),
    ToolDef(
        "create_sale",
        "إنشاء فاتورة بيع",
        "manage_sales",
        destructive=False,
        required_params=("customer_name", "product_name"),
        optional_params=("quantity",),
    ),
    ToolDef(
        "record_payment",
        "تسجيل دفعة (استلام/إعطاء)",
        "manage_payments",
        destructive=False,
        required_params=("customer_name", "amount"),
        optional_params=("direction", "method"),
    ),
    ToolDef(
        "create_expense",
        "إضافة مصروف",
        "manage_expenses",
        destructive=False,
        required_params=("description", "amount"),
    ),
    ToolDef(
        "create_supplier",
        "إضافة مورد",
        "manage_suppliers",
        destructive=False,
        required_params=("name",),
        optional_params=("phone", "address"),
    ),
    ToolDef(
        "create_purchase",
        "إضافة مشتريات",
        "manage_purchases",
        destructive=False,
        required_params=("supplier_name", "product_name"),
        optional_params=("quantity", "unit_cost"),
    ),
    ToolDef(
        "create_cheque",
        "إضافة شيك",
        "manage_payments",
        destructive=False,
        required_params=("cheque_number", "amount"),
        optional_params=("due_date", "cheque_type"),
    ),
    ToolDef(
        "set_customer_balance",
        "تعديل رصيد عميل (تدميري — تأكيد إجباري)",
        "manage_customers",
        destructive=True,
        required_params=("customer_name", "new_balance"),
        optional_params=("reason",),
    ),
    ToolDef(
        "inventory_status",
        "حالة المخزون/منخفض (READ)",
        "manage_warehouse",
        destructive=False,
    ),
    ToolDef(
        "sales_summary",
        "ملخص مبيعات (READ)",
        "manage_sales",
        destructive=False,
        optional_params=("days",),
    ),
)

TOOLS_BY_NAME: dict[str, ToolDef] = {t.name: t for t in TOOLS}


def describe_tools() -> str:
    """وصف مضغوط للـ prompt (Groq function-calling نصي بديل)."""
    lines = []
    for t in TOOLS:
        req = ", ".join(t.required_params)
        lines.append(
            f"- {t.name}: {t.description} [permission={t.permission}"
            + (f", params=({req})" if req else "")
            + "]"
        )
    return "\n".join(lines)
