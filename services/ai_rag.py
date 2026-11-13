"""RAG هجين — الدليل + بيانات نظام بوّابية النية + ذاكرة، بميزانية محدودة.

بدل الوضع القديم (إجمالي 30 يوم دائماً): نجمع فقط ما تحتاجه النية.
الترتيب: دليل (GuideLoader) → ذاكرة المستخدم → بيانات محددة بالنية.
الميزانية تُحترم حتى لا ينفجر الـ prompt.
"""

from __future__ import annotations


def retrieve(message: str, user, max_chars: int = 6000) -> str:
    """استرجاع هجين بحد أقصى max_chars. user للعزل (نطاق دليل + ذاكرة)."""
    is_owner = bool(getattr(user, "is_owner", False)) if user else False
    parts: list[str] = []
    used = 0

    def _add(block: str, budget: int):
        nonlocal used
        if used >= max_chars:
            return
        b = block[: max(0, max_chars - used)]
        if b:
            parts.append(b)
            used += len(b) + 8

    try:
        from ai_knowledge.guide_loader import get_guide_loader

        ctx = get_guide_loader().get_context(message or "", is_owner, max_chars=3000)
        if ctx:
            _add(f"📖 **دليل الاستخدام:**\n{ctx}", 3000)
    except Exception:
        pass

    try:
        if user and getattr(user, "id", None):
            from ai_knowledge.memory_system import get_memory_system

            mem = get_memory_system()
            similar = mem.recall_similar_conversations(message or "", limit=3)
            if similar:
                lines = []
                for m in similar[:3]:
                    txt = f"- {str(m.get('user_message', ''))[:120]}"
                    lines.append(txt)
                _add("🧠 **ذاكرة (محادثات سابقة):**\n" + "\n".join(lines), 1200)
    except Exception:
        pass

    _add(_db_context(message or "", user), max_chars)

    return ("\n\n".join(parts)).strip()


def _db_context(message: str, user) -> str:
    """بيانات محددة بالنية — ليست كل جداول النظام."""
    msg = (message or "").lower()
    is_balance = "رصيد" in msg or "balance" in msg
    is_sales = "فاتورة" in msg or "بيع" in msg or "sales" in msg or "مبيعات" in msg
    is_inventory = "مخزون" in msg or "inventory" in msg or "stock" in msg
    is_create = any(
        w in msg
        for w in (
            "انشئ",
            "انشاء",
            "إنشاء",
            "add",
            "create",
            "سجل",
            "جديد",
            "اضافة",
            "إضافة",
        )
    )

    try:
        from models import Customer, Product, Sale
        from datetime import datetime, timedelta
        from sqlalchemy import func
        from extensions import db

        _tid = None
        try:
            from models.tenant_scope import get_current_tenant_id

            _tid = get_current_tenant_id()
            if user is not None:
                if getattr(user, "is_owner", False):
                    _tid = None  # المالك يرى الكل
                elif getattr(user, "tenant_id", None) is not None:
                    _tid = user.tenant_id
        except Exception:
            pass

        def _scoped(model):
            if _tid is None:
                return model.query
            if _tid == -1:
                return model.query.filter(model.tenant_id.is_(None))
            return model.query.filter(model.tenant_id == _tid)

        lines: list[str] = []
        if is_balance:
            count = _scoped(Customer).filter_by(is_active=True).count()
            lines.append(
                f"- عملاء نشطون: {count} (للأرصدة التفصيلية اسأل عن عميل محدد)"
            )
        if is_sales:
            since = datetime.now() - timedelta(days=30)
            n = _scoped(Sale).filter(Sale.sale_date >= since).count()
            total = (
                db.session.query(func.sum(Sale.total_amount))
                .filter(Sale.sale_date >= since)
                .scalar()
                or 0
            )
            lines.append(f"- مبيعات 30 يوم: {n} فاتورة ({total} درهم)")
        if is_inventory:
            low = (
                _scoped(Product)
                .filter(
                    Product.current_stock <= Product.min_stock_alert,
                    Product.is_active.is_(True),
                )
                .count()
            )
            total_p = _scoped(Product).filter_by(is_active=True).count()
            lines.append(f"- منتجات: {total_p}، مخزون منخفض: {low}")
        if is_create:
            lines.append(
                "- لإنشاء كيان جديد يلزم الاسم (+ الهاتف للعميل، التكلفة للمنتج)"
            )
        if lines:
            return "📊 **بيانات النظام (مرتبطة بسؤالك):**\n" + "\n".join(lines)
        return ""
    except Exception:
        return ""
