"""المخطط (Planner) — نية + كيانات + أداة + اكتمال + تأكيد.

يُحوّل `رسالة` إلى `Plan` منظم، حتى يمكن التنفيذ مباشرة (بلا Groq خطوة أولى)
أو تكليف Groq بثغرة محددة.

الأولوية (نفس ترتيب أنواع النية في النظام):
 1) ai_flows (تدفقات كلمات مفتاحية — نفس مصدر القوائم)
 2) semantic_matcher (TF-IDF مُطبَّع)
 3) context_engine (fallback)

ثم استخراج الكيانات، ثم تقرير اكتمال (حقول ناقصة → سؤال محدد)
وملاحظة التأكيد للعمليات المدمّرة.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.ai_normalize import normalize


@dataclass
class Plan:
    intent: str
    tool: str | None
    params: dict = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    needs_confirm: bool = False
    confidence: float = 0.0
    source: str = "unknown"


# ربط النية → أداة
_INTENT_TO_TOOL = {
    "balance": "set_customer_balance",
    "customer": "create_customer",
    "product": "create_product",
    "sale": "create_sale",
    "receive": "record_payment",
    "give": "record_payment",
    "expense": "create_expense",
    "supplier": "create_supplier",
    "purchase": "create_purchase",
    "cheque": "create_cheque",
    "warehouse": "inventory_status",
    "ledger": "sales_summary",
    "user": None,
    # intents من semantic_matcher
    "create_invoice": "create_sale",
    "create_receipt": "record_payment",
    "customer_balance": "get_customer_balance",
    "inventory_check": "inventory_status",
    "sales_analysis": "sales_summary",
}

# حقول مطلوبة لكل أداة (لاكتشاف النقص)
_REQUIRED = {
    "create_customer": ["name"],
    "create_product": ["name"],
    "create_sale": ["customer_name", "product_name"],
    "record_payment": ["customer_name", "amount"],
    "create_expense": ["description", "amount"],
    "create_supplier": ["name"],
    "create_purchase": ["supplier_name", "product_name"],
    "create_cheque": ["cheque_number", "amount"],
    "set_customer_balance": ["customer_name", "new_balance"],
    "get_customer_balance": ["customer_name"],
    "search_customers": ["query"],
}


def extract_entities(message: str) -> dict:
    """استخراج كيانات محسن (عربي): أسماء متعددة الكلمات، مبالغ، هواتف، SKUs، تواريخ."""
    from services.ai_normalize import normalize as _n  # noqa

    text = message or ""
    norm = normalize(text)
    ents: dict = {
        "numbers": [],
        "amounts": [],
        "phones": [],
        "skus": [],
        "dates": [],
        "names": [],
        "product_name": None,
        "supplier_name": None,
        "expense_description": None,
    }

    # أرقام + مبالغ
    for m in re.finditer(
        r"(\d+(?:,\d+)*(?:\.\d+)?)\s*(درهم|دولار|ريال|aed|usd|sar)?", norm
    ):
        try:
            ents["numbers"].append(float(m.group(1).replace(",", "")))
        except ValueError:
            continue
    for m in re.finditer(
        r"(\d+(?:,\d+)*(?:\.\d+)?)\s*(درهم|دولار|ريال|aed|usd|sar)", norm
    ):
        ents["amounts"].append(
            {"value": float(m.group(1).replace(",", "")), "currency": m.group(2)}
        )
    if not ents["amounts"] and ents["numbers"]:
        ents["amounts"] = [{"value": n, "currency": "aed"} for n in ents["numbers"][:2]]

    # هواتف إماراتية (0xxxxxxxx / +971)
    for m in re.finditer(r"(\+?(?:971|0)5\d{7,8})", norm.replace(" ", "")):
        ents["phones"].append(m.group(1))

    # SKUs قطع غيار: حرف/رقم/شرطة (مثل 1R0716, C-123, فلتر-99)
    for m in re.finditer(r"\b([A-Za-z0-9]{2,4}[-\w]{2,12})\b", text):
        token = m.group(1)
        if any(c.isdigit() for c in token) and any(c.isalpha() for c in token):
            ents["skus"].append(token)

    # تواريخ مرقمة yyyy-mm-dd / dd/mm/yyyy
    for m in re.finditer(
        r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", text
    ):
        ents["dates"].append(m.group(1))

    # أسماء بعد مؤشرات (أسماء متعددة الكلمات)
    for m in re.finditer(
        r"(?:للعميل|العميل|عميل|زبون|customer)\s+([\u0600-\u06FF\w\s]{2,40}?)(?:\s+[,،]|$)",
        text,
        re.IGNORECASE,
    ):
        raw = re.sub(r"\s+", " ", m.group(1)).strip()
        if raw and len(raw) >= 2:
            # قصّ عند أدوات حشو
            raw = re.split(r"\s+(?:بمبلغ|بقيمة|بـ|مبلغ|عليه|له)\b", raw)[0].strip()
            if raw:
                ents["names"].append(raw)

    # منتج/قطعة بعد مؤشرات + SKU اختياري
    for m in re.finditer(
        r"(?:لـ?لمنتج|المنتج|منتج|قطعة|فلتر|بضاعة|product)\s+([\u0600-\u06FF\w\-\s]{2,40}?)(?:\s+[,،]|$)",
        text,
        re.IGNORECASE,
    ):
        raw = re.sub(r"\s+", " ", m.group(1)).strip()
        raw = re.split(r"\s+(?:بمبلغ|بقيمة|بـ|مبلغ|سعر|تكلفة|درهم|دولار)\b", raw)[
            0
        ].strip()
        if raw and len(raw) >= 2:
            ents["product_name"] = raw
            if raw not in ents["names"]:
                ents["names"].append(raw)
            break
    # مورد بعد مؤشرات
    for m in re.finditer(
        r"(?:للمورد|المورد|مورد|supplier)\s+([\u0600-\u06FF\w\s]{2,40}?)(?:\s+[,،]|$)",
        text,
        re.IGNORECASE,
    ):
        raw = re.sub(r"\s+", " ", m.group(1)).strip()
        raw = re.split(r"\s+(?:بمبلغ|بقيمة|بـ|مبلغ|له|عليه)\b", raw)[0].strip()
        if raw and len(raw) >= 2:
            ents["supplier_name"] = raw
            break
    # وصف مصروف: بعد "مصروف" أو "نفقات" أو "إضافة مصروف"
    for m in re.finditer(
        r"(?:مصروف|نفقات?|نفقات)\s+([\u0600-\u06FF\w\s]{3,50}?)(?:\s+(?:بمبلغ|بقيمة|بـ|مبلغ|\d)|$)",
        text,
        re.IGNORECASE,
    ):
        raw = re.sub(r"\s+", " ", m.group(1)).strip()
        if raw and len(raw) >= 3 and not raw.lower().startswith(("جديد", "جديده")):
            ents["expense_description"] = raw
            break
    # تواريخ نسبية
    if "اليوم" in norm or "اليوم" in text:
        ents["relative_dates"].append(
            "today"
        ) if "relative_dates" in ents else ents.__setitem__("relative_dates", ["today"])
    if "أمس" in text or "امس" in norm:
        ents.setdefault("relative_dates", []).append("yesterday")
    return ents


def plan(message: str, user=None) -> Plan:
    """إنتاج خطة منظمة من رسالة حرة."""
    from services.ai_flows import find_flow
    from services.ai_normalize import normalize as _norm

    msg = message or ""
    norm = _norm(msg)
    ents = extract_entities(msg)

    # 1) تدفقات كلمات مفتاحية (نفس القوائم)
    flow = find_flow(norm)
    if flow:
        tool = _INTENT_TO_TOOL.get(flow.key)
        params: dict = {}
        if tool == "create_customer":
            if ents.get("names"):
                params["name"] = ents["names"][0]
            elif ents.get("supplier_name"):
                params["name"] = ents["supplier_name"]
        elif tool == "create_product":
            if ents.get("product_name"):
                params["name"] = ents["product_name"]
            elif ents.get("names"):
                params["name"] = ents["names"][0]
        elif tool == "create_supplier":
            if ents.get("supplier_name"):
                params["name"] = ents["supplier_name"]
            elif ents.get("names"):
                params["name"] = ents["names"][0]
        elif tool == "create_sale":
            if ents.get("names") and len(ents["names"]) >= 1:
                params["customer_name"] = ents["names"][0]
            if ents.get("product_name"):
                params["product_name"] = ents["product_name"]
            elif len(ents.get("names") or []) >= 2:
                params["product_name"] = ents["names"][1]
        elif tool == "create_purchase":
            if ents.get("supplier_name"):
                params["supplier_name"] = ents["supplier_name"]
            if ents.get("product_name"):
                params["product_name"] = ents["product_name"]
            if ents.get("amounts"):
                params["unit_cost"] = ents["amounts"][0]["value"]
        elif tool == "set_customer_balance":
            if ents["names"]:
                params["customer_name"] = ents["names"][0]
            if ents["amounts"]:
                params["new_balance"] = ents["amounts"][0]["value"]
        elif tool == "get_customer_balance" and ents["names"]:
            params["customer_name"] = ents["names"][0]
        elif tool == "record_payment":
            if ents["names"]:
                params["customer_name"] = ents["names"][0]
            if ents["amounts"]:
                params["amount"] = ents["amounts"][0]["value"]
        elif tool == "create_expense":
            if ents.get("expense_description"):
                params["description"] = ents["expense_description"]
            if ents["amounts"]:
                params["amount"] = ents["amounts"][0]["value"]
        elif tool == "create_cheque":
            if ents.get("skus"):
                params["cheque_number"] = ents["skus"][0]
            if ents["amounts"]:
                params["amount"] = ents["amounts"][0]["value"]
        needs_confirm = bool(tool == "set_customer_balance") if tool else False
        missing = (
            [f for f in _REQUIRED.get(tool or "", []) if f not in params]
            if tool
            else []
        )
        return Plan(
            intent=flow.key,
            tool=tool,
            params=params,
            missing_fields=missing,
            needs_confirm=needs_confirm,
            confidence=0.9,
            source="ai_flows",
        )

    # 2) semantic matcher
    try:
        from ai_knowledge.semantic_matcher import understand_message

        res = understand_message(msg)
        if res.get("intent") and (res.get("confidence") or 0) >= 0.30:
            intent = res["intent"]
            tool = _INTENT_TO_TOOL.get(intent)
            # حماية: فقط القراءات تُسمح من الـ semantic (الكتابة من الـ flows أقوى)
            if tool in ("get_customer_balance", "inventory_status", "sales_summary"):
                params = {}
                if ents["names"]:
                    params["customer_name"] = ents["names"][0]
                missing = [f for f in _REQUIRED.get(tool, []) if f not in params]
                return Plan(
                    intent=intent,
                    tool=tool,
                    params=params,
                    missing_fields=missing,
                    needs_confirm=False,
                    confidence=res.get("confidence", 0.5),
                    source="semantic",
                )
    except Exception:
        pass

    return Plan(
        intent="chat",
        tool=None,
        params={},
        missing_fields=[],
        needs_confirm=False,
        confidence=0.4,
        source="fallback",
    )
