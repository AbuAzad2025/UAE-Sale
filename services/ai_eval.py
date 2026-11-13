"""مُقيّم الذكاء (Eval) — رقم قابل للتتبع لقوة الفهم، لا انطباع.

أسئلة مرجعية (عربي/FSA): نية متوقعة + أداة متوقعة (+ حقل مفقود-ية).
التشغيل يحتاج المرشحات الحالية فقط (بدون DB كتابة) — افترض قراءة نية.

الاستخدام:
  python -m services.ai_eval            # طباعة التقرير
  python -m services.ai_eval --json    # JSON للـ CI
"""

from __future__ import annotations

import argparse
import json

_CASES = [
    ("أريد عميل جديد", "customer", "create_customer", []),
    ("عميل جديد: أحمد", "customer", "create_customer", []),
    ("أضف زبون جديد", "customer", "create_customer", []),
    ("منتج جديد", "product", "create_product", []),
    ("منتج جديد: فلتر زيت", "product", "create_product", []),
    ("فاتورة جديدة لعميل", "sale", "create_sale", ["customer_name", "product_name"]),
    ("بيع فلتر", "sale", "create_sale", ["customer_name", "product_name"]),
    ("بيع فلتر لعميل أحمد", "sale", "create_sale", ["product_name"]),
    (
        "كم رصيد العميل",
        "balance",
        "set_customer_balance",
        ["customer_name", "new_balance"],
    ),
    (
        "رصيد العميل أحمد",
        "balance",
        "set_customer_balance",
        ["customer_name", "new_balance"],
    ),
    ("رصيد العميل أحمد ألف درهم", "balance", "set_customer_balance", []),
    ("استلام دفعة من عميل", "receive", "record_payment", ["customer_name", "amount"]),
    ("استلام 500 درهم من عميل أحمد", "receive", "record_payment", ["customer_name"]),
    ("مصروف جديد", "expense", "create_expense", ["amount"]),
    ("مصروف إيجار 2000 درهم", "expense", "create_expense", []),
    ("مورد جديد", "supplier", "create_supplier", []),
    ("مورد جديد: شركة النخبة", "supplier", "create_supplier", []),
    ("مشتريات جديدة", "purchase", "create_purchase", ["supplier_name", "product_name"]),
    ("مشتريات من مورد النخبة لفلتر زيت", "purchase", "create_purchase", []),
    ("شيك جديد", "cheque", "create_cheque", ["cheque_number", "amount"]),
    ("دفتر الأستاذ", "ledger", "sales_summary", []),
    ("ما هي النظم", "chat", None, []),
    ("كيف أعمل فاتورة؟", "sale", "create_sale", ["customer_name", "product_name"]),
    ("حلل المبيعات", "sale", "create_sale", ["customer_name", "product_name"]),
    ("فحص المخزون", "warehouse", "inventory_status", []),
    ("كيف أعمل فاتوره؟", "sale", "create_sale", ["customer_name", "product_name"]),
    ("ابغى عميل جديد", "customer", "create_customer", []),
    ("زبون جديد: محمد علي", "customer", "create_customer", []),
    ("مبيعات اليوم", "sale", "create_sale", ["customer_name", "product_name"]),
    (
        "رصيد الزبون",
        "balance",
        "set_customer_balance",
        ["customer_name", "new_balance"],
    ),
    ("أضف 5000 درهم لرصيد العميل أحمد", "balance", "set_customer_balance", []),
]


def run_eval() -> dict:
    from services.ai_planner import plan

    total = len(_CASES)
    hits = 0
    tool_hits = 0
    rows = []
    for q, exp_intent, exp_tool, _exp_missing in _CASES:
        p = plan(q, user=None)
        ok_intent = p.intent == exp_intent
        ok_tool = p.tool == exp_tool
        hits += int(ok_intent)
        tool_hits += int(ok_tool)
        rows.append(
            {
                "q": q,
                "exp": exp_intent,
                "got": p.intent,
                "exp_tool": exp_tool,
                "got_tool": p.tool,
                "ok": ok_intent,
                "tool_ok": ok_tool,
            }
        )
    return {
        "total": total,
        "intent_accuracy": hits / total if total else 0,
        "tool_accuracy": tool_hits / total if total else 0,
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = run_eval()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"📊 Eval: intent {report['intent_accuracy']:.2%} | tool {report['tool_accuracy']:.2%} ({report['total']} سؤال)"
        )
        for r in report["rows"]:
            mark = "✅" if r["ok"] and r["tool_ok"] else "⚠️"
            print(
                f"{mark} {r['q']!r}: exp={r['exp']}/{r['exp_tool']} got={r['got']}/{r['got_tool']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
