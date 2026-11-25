"""Grounded answers for factual questions asked of the AI assistant.

The assistant must answer from the live database of the *current tenant* and
only with figures the current user is allowed to see. This module is called
before the old action/menu matcher so a question such as "كم عدد المبيعات
اليوم؟" is answered with numbers instead of being misread as "create sale".

No external API is needed: every answer is deterministic and auditable.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func

from bot_core.gateway import normalize as normalize_prompt
from services.ai_normalize import normalize

QUESTION_WORDS = (
    "كم", "عدد", "إجمالي", "مجموع", "كيف", "ماذا", "ما هو", "هل ",
    "؟", "?", "how many", "what is", "total", "count", "status",
)

SUMMARY_PERMISSIONS = {
    "customers": ("manage_customers", "view_reports"),
    "inventory": ("manage_products", "view_products", "view_reports"),
    "expenses": ("manage_expenses", "view_ledger"),
    "cheques": ("manage_payments", "view_ledger"),
    "fiscal_periods": ("manage_ledger", "view_ledger"),
}
COMPANY_SELECTION_REQUIRED = "اختر شركة من قائمة الشركات أولًا لعرض بياناتها."
_SUMMARY_PATTERNS = {
    "customers": r"(?:كم )?عدد (?:ال)?(?:عملاء?|زبائن|زباين)|كم (?:عميلا?|زبونا?)|(?:how many |count )?(?:active )?customers(?: count)?",
    "inventory": r"(?:ما )?حال[هة] المخزون|(?:ملخص|وضع) المخزون|(?:inventory|stock) (?:status|summary)",
    "expenses": r"(?:كم )?(?:عدد |مجموع |اجمالي )?(?:ال)?مصروفات (?:هذا الشهر|الشهر الحالي)|(?:count |total )?expenses (?:this month|for this month)",
    "cheques": r"(?:كم )?عدد (?:ال)?شيكات|كم شيكا?|(?:how many |count )?cheques(?: count)?",
    "fiscal_periods": r"(?:ما )?(?:حال[هة] )?الفترات المالي[هة]|ما حال[هة] الفتر[هة] المالي[هة]|(?:fiscal periods?|financial periods?)(?: status)?",
}


def summary_kind(message: str) -> str | None:
    prompt = normalize_prompt(message).strip(" .!?؟")
    return next((kind for kind, pattern in _SUMMARY_PATTERNS.items() if re.fullmatch(pattern, prompt)), None)


def business_summary(kind: str, tenant_id: int | None) -> str:
    """Read an explicitly selected summary from the authenticated scope."""
    if tenant_id is None:
        if kind == "fiscal_periods":
            return "اختر شركة من قائمة الشركات لعرض الفترات المالية."
        return COMPANY_SELECTION_REQUIRED

    from sqlalchemy import select

    from extensions import db
    from models import Cheque, Customer, Expense, Product
    from models.erp_modules import FiscalPeriod
    from services.currency_service import CurrencyService

    scope = "في الشركة الحالية"
    if kind == "customers":
        count = db.session.scalar(select(func.count(Customer.id)).where(
            Customer.tenant_id == tenant_id, Customer.is_active.is_(True),
        ))
        return f"العملاء النشطون {scope}: {count}."
    if kind == "inventory":
        count, low = db.session.execute(select(
            func.count(Product.id), func.count(Product.id).filter(Product.current_stock <= Product.min_stock_alert),
        ).where(Product.tenant_id == tenant_id, Product.is_active.is_(True))).one()
        return f"المخزون {scope}: {count} صنف نشط، منها {low} عند حد التنبيه أو أقل."
    if kind == "expenses":
        today = date.today()
        first = today.replace(day=1)
        next_month = (first + timedelta(days=32)).replace(day=1)
        count, total = db.session.execute(select(func.count(Expense.id), func.sum(Expense.amount_base)).where(
            Expense.tenant_id == tenant_id, Expense.expense_date >= datetime.combine(first, datetime.min.time()),
            Expense.expense_date < datetime.combine(next_month, datetime.min.time()),
        )).one()
        return f"مصروفات هذا الشهر {scope}: {count} عملية بقيمة {_money(total)} {CurrencyService.get_base_currency()}."
    if kind == "cheques":
        count = db.session.scalar(select(func.count(Cheque.id)).where(Cheque.tenant_id == tenant_id))
        return f"الشيكات المسجلة {scope}: {count}."
    if kind == "fiscal_periods":
        opened, closed = db.session.execute(select(
            func.count(FiscalPeriod.id).filter(FiscalPeriod.is_closed.is_(False)),
            func.count(FiscalPeriod.id).filter(FiscalPeriod.is_closed.is_(True)),
        ).where(FiscalPeriod.tenant_id == tenant_id)).one()
        return f"الفترات المالية {scope}: {opened} مفتوحة و{closed} مغلقة."
    raise ValueError("Unknown business summary")


def is_question(message: str) -> bool:
    text = (message or "").strip().lower()
    return any(word in text for word in QUESTION_WORDS)


_SALES_TERMS = re.compile(r"\b(?:المبيعات|مبيعات|المبيع|مبيع|بعنا|sales)\b|\b(?:فاتوره بيع|فواتير البيع|invoices?)\b")
_NON_SALES_INVOICES = re.compile(r"\b(?:مشتريات|purchase|purchases)\s+invoices?\b|\binvoices? for purchases\b")
_SALES_COMPARISON = re.compile(r"\b(?:قارن|مقارنه|compare|versus|vs)\b")
_SALES_SUMMARY = re.compile(r"\b(?:حلل|تحليل|ملخص|قديش|كم|اجمالي|summary|analyze)\b")
_SALES_NON_QUERY = re.compile(
    r"^(?:كيفيه|طريقه|خطوات|ما طريقه|how (?:do|can|to)|"
    r"انش[ي]|اضف|سجل|عدل|احذف|create|add|update|delete)\b"
)
# "كيف كانت المبيعات؟" is a data question; "كيف أنشئ فاتورة؟" is a how-to.
_SALES_HOWTO = re.compile(
    r"^كيف\s+(?:انش[ي]|اضف|اعمل|اسجل|عدل|احذف|تعمل|نعمل|تسوي|تتم|يتم|نفذ)\b"
)
_SALES_PERIODS = (
    (r"الشهر (?:الماضي|السابق)|last month", "الشهر الماضي"),
    (r"هذا الشهر|هالشهر|الشهر الحالي|this month", "هذا الشهر"),
    (r"امس|البارحه|امبارح|مبارح|yesterday", "أمس"),
    (r"اليوم|today", "اليوم"),
    (r"(?:ال)?اسبوع (?:الماضي|السابق)|last week", "الأسبوع الماضي"),
    (r"هذا الاسبوع|هالاسبوع|الاسبوع الحالي|this week", "هذا الأسبوع"),
    (r"(?:اخر )?7 (?:ايام|days)|(?:اخر )?(?:ال)?اسبوع|week", "آخر 7 أيام"),
    (r"(?:اخر |last )?30 (?:يوما?|days)", "آخر 30 يوماً"),
)
_SALES_PERIOD_RE = re.compile(
    r"\b(?:و?ب|و)?(?P<period>" + "|".join(pattern for pattern, _ in _SALES_PERIODS) + r")\b"
)
_SALES_FOLLOW_UP = re.compile(rf"(?:و\s*|طيب\s+|what about\s+|and\s+)?{_SALES_PERIOD_RE.pattern}")
_PRECEDING_SALES_PERIOD = re.compile(
    r"(?:و\s*|طيب\s+)?(?:ما )?قبل(?:ها| ذلك)|(?:and )?(?:the )?(?:period )?before that"
)
_SALES_PERIOD_PREDECESSORS = {
    "اليوم": "أمس",
    "أمس": "اليوم قبل أمس",
    "هذا الشهر": "الشهر الماضي",
    "الشهر الماضي": "الشهر الذي قبل الماضي",
    "هذا الأسبوع": "الأسبوع الماضي",
    "الأسبوع الماضي": "الأسبوع الذي قبل الماضي",
    "آخر 7 أيام": "السبعة أيام السابقة",
    "آخر 30 يوماً": "الثلاثون يوماً السابقة",
}


def is_preceding_sales_period(message: str) -> bool:
    return bool(_PRECEDING_SALES_PERIOD.fullmatch(normalize(message)))


def preceding_sales_period(period: str) -> str | None:
    return _SALES_PERIOD_PREDECESSORS.get(period)


def is_sales_question(message: str, follow_up_topic=None) -> bool:
    text = normalize(message)
    if follow_up_topic == "sales" and (
        _SALES_FOLLOW_UP.fullmatch(text) or is_preceding_sales_period(message)
    ):
        return True
    return bool(
        _SALES_TERMS.search(text)
        and not _SALES_NON_QUERY.match(text)
        and not _SALES_HOWTO.match(text)
        and not _NON_SALES_INVOICES.search(text)
        and (
            is_question(message)
            or _SALES_COMPARISON.search(text)
            or _SALES_SUMMARY.search(text)
        )
    )


def has_sales_subject(message: str) -> bool:
    """Require a sales subject before allowing a neural prediction to run a report."""
    return bool(_SALES_TERMS.search(normalize(message)))


def _sales_answer(query, Sale, message, *, period=None, resolved_periods=None):
    text = normalize(message)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    month_start = today.replace(day=1)
    previous_month = (month_start - timedelta(days=1)).replace(day=1)
    week_start = today - timedelta(days=today.weekday())
    windows = {
        "اليوم": (today, tomorrow),
        "أمس": (today - timedelta(days=1), today),
        "اليوم قبل أمس": (today - timedelta(days=2), today - timedelta(days=1)),
        "هذا الشهر": (month_start, tomorrow),
        "الشهر الماضي": (previous_month, month_start),
        "الشهر الذي قبل الماضي": (
            (previous_month - timedelta(days=1)).replace(day=1),
            previous_month,
        ),
        "هذا الأسبوع": (week_start, tomorrow),
        "الأسبوع الماضي": (week_start - timedelta(days=7), week_start),
        "الأسبوع الذي قبل الماضي": (week_start - timedelta(days=14), week_start - timedelta(days=7)),
        "آخر 7 أيام": (tomorrow - timedelta(days=7), tomorrow),
        "آخر 30 يوماً": (tomorrow - timedelta(days=30), tomorrow),
        "السبعة أيام السابقة": (tomorrow - timedelta(days=14), tomorrow - timedelta(days=7)),
        "الثلاثون يوماً السابقة": (tomorrow - timedelta(days=60), tomorrow - timedelta(days=30)),
    }
    periods = [period] if period in windows else []
    if is_preceding_sales_period(message) and not periods:
        return "أي فترة تقصد؟ اكتب الفترة التي تريد معرفة مبيعاتها."
    for match in _SALES_PERIOD_RE.finditer(text):
        label = next(
            label for pattern, label in _SALES_PERIODS if re.fullmatch(pattern, match["period"])
        )
        if label not in periods:
            periods.append(label)
    if _SALES_COMPARISON.search(text) and len(periods) < 2:
        baseline = {
            "اليوم": "أمس",
            "أمس": "اليوم",
            "هذا الشهر": "الشهر الماضي",
            "الشهر الماضي": "هذا الشهر",
            "هذا الأسبوع": "الأسبوع الماضي",
            "الأسبوع الماضي": "هذا الأسبوع",
        }
        if periods and periods[0] not in baseline:
            return "حدّد فترتين للمقارنة. مثلاً: قارن مبيعات اليوم وأمس."
        periods = periods + [baseline[periods[0]]] if periods else ["اليوم", "أمس"]
    if not periods:
        periods = ["آخر 30 يوماً"]
    if resolved_periods is not None:
        resolved_periods.extend(periods)

    results = []
    invoice_counts = []
    for label in periods:
        start_day, end_day = windows[label]
        start = datetime.combine(start_day, datetime.min.time())
        end = datetime.combine(end_day, datetime.min.time())
        rows = (
            query.filter(Sale.sale_date >= start, Sale.sale_date < end)
            .with_entities(Sale.currency, func.count(Sale.id), func.sum(Sale.total_amount))
            .group_by(Sale.currency)
            .order_by(Sale.currency)
            .all()
        )
        count = sum(row[1] for row in rows)
        invoice_counts.append(count)
        values = " · ".join(f"{_money(total)} {currency}" for currency, _, total in rows)
        totals = f" بقيمة {values}" if values else ""
        results.append(f"المبيعات {label}: {count} فاتورة{totals}.")

    if len(invoice_counts) == 2:
        first, second = invoice_counts
        results.append(f"الفرق في عدد الفواتير بين الفترتين: {abs(first - second)}.")
    return "📊 " + "\n".join(results) + "\nالمصدر: فواتير المبيعات المؤكدة من سجلات شركتك."


def _allowed(user, *permissions):
    if user is None:
        return False
    if getattr(user, "is_owner", False):
        return True
    return any(user.has_permission(code) for code in permissions)


def _denied(*permissions):
    names = ", ".join(permissions)
    return f"⛔ لا يمكنني عرض هذه البيانات بدون صلاحية: {names}. راجع مدير النظام."


def _scope(query, model, user):
    """Restrict to the caller's tenant (owners may see platform-wide rows)."""
    tenant_id = getattr(user, "tenant_id", None)
    if getattr(user, "is_owner", False):
        return query
    if hasattr(model, "tenant_id"):
        return query.filter(model.tenant_id == tenant_id)
    return query


def _period(query, model, column, message, user):
    text = (message or "").lower()
    today = date.today()
    if "اليوم" in text or "today" in text:
        start = datetime.combine(today, datetime.min.time())
        return query.filter(column >= start), "اليوم"
    if "الشهر" in text or "شهر" in text or "month" in text:
        start = datetime.combine(today.replace(day=1), datetime.min.time())
        return query.filter(column >= start), "هذا الشهر"
    if "أسبوع" in text or "اسبوع" in text or "week" in text:
        start = datetime.now() - timedelta(days=7)
        return query.filter(column >= start), "آخر 7 أيام"
    start = datetime.now() - timedelta(days=30)
    return query.filter(column >= start), "آخر 30 يوماً"


def _money(value):
    return f"{(Decimal(str(value or 0))):,.2f}"


def answer(message: str, user, *, follow_up_topic=None, enforce_company_scope: bool = False):
    """Return a grounded Arabic answer string, or None when not a data question."""
    sales_question = is_sales_question(message, follow_up_topic)
    summary = summary_kind(message)
    if not sales_question and summary is None and not is_question(message):
        return None
    text = (message or "").lower()
    try:
        from extensions import db
        from models import (
            Cheque,
            Customer,
            Employee,
            Expense,
            Payment,
            Product,
            Purchase,
            Sale,
            Supplier,
            User,
        )
        from models.erp_modules import FiscalPeriod

        if sales_question:
            if not _allowed(user, "manage_sales", "view_reports"):
                return _denied("manage_sales", "view_reports")
            from services.assistant_actions import _scope as authenticated_scope

            query = Sale.query.filter_by(status="confirmed")
            if enforce_company_scope:
                tenant_id = authenticated_scope(user)
                if tenant_id is None:
                    return COMPANY_SELECTION_REQUIRED
                query = query.filter(Sale.tenant_id == tenant_id)
            else:
                query = _scope(query, Sale, user)
            return _sales_answer(query, Sale, message)

        if summary:
            from services.assistant_actions import _scope as authenticated_scope

            permissions = SUMMARY_PERMISSIONS[summary]
            if not _allowed(user, *permissions):
                return _denied(*permissions)
            return business_summary(summary, authenticated_scope(user))

        # --- customers ----------------------------------------------------
        if any(w in text for w in ("عميل", "زبون", "عملاء", "customer")):
            if not _allowed(user, "manage_customers", "view_reports"):
                return _denied("manage_customers", "view_reports")
            q = _scope(Customer.query.filter_by(is_active=True), Customer, user)
            count = q.count()
            return f"👥 العملاء النشطون في شركتك: {count} عميلاً."

        # --- inventory ----------------------------------------------------
        if any(w in text for w in ("مخزون", "منتج", "قطعة", "inventory", "stock")):
            if not _allowed(user, "manage_products", "view_products", "view_reports"):
                return _denied("view_products", "view_reports")
            q = _scope(Product.query.filter_by(is_active=True), Product, user)
            total = q.count()
            low = q.filter(Product.current_stock <= Product.min_stock_alert).count()
            tail = ""
            if _allowed(user, "view_costs"):
                value = db.session.query(
                    func.sum(Product.current_stock * Product.cost_price)
                ).select_from(Product).filter(
                    Product.id.in_(q.with_entities(Product.id))
                ).scalar()
                tail = f" بقيمة {_money(value)} شيقل بالتكلفة."
            return (
                f"📦 المخزون: {total} منتجاً نشطاً، {low} تحت حد التنبيه.{tail} "
                "البيانات خاصة بشركتك."
            )

        # --- purchases ----------------------------------------------------
        if any(w in text for w in ("مشتري", "مورد", "purchase", "supplier")):
            if not _allowed(user, "manage_purchases", "manage_suppliers", "view_reports"):
                return _denied("manage_purchases", "view_reports")
            if "مورد" in text or "supplier" in text:
                count = _scope(Supplier.query.filter_by(is_active=True), Supplier, user).count()
                return f"🚚 الموردون المسجلون في شركتك: {count} مورداً."
            q, label = _period(Purchase.query, Purchase, Purchase.purchase_date, message, user)
            count = _scope(q, Purchase, user).count()
            return f"🛒 المشتريات {label}: {count} فاتورة في شركتك."

        # --- payments / cheques ------------------------------------------
        if any(w in text for w in ("دفع", "تحصيل", "سند", "payment", "receipt")):
            if not _allowed(user, "manage_payments", "view_ledger"):
                return _denied("manage_payments", "view_ledger")
            q, label = _period(Payment.query, Payment, Payment.payment_date, message, user)
            count = _scope(q, Payment, user).count()
            return f"💳 السندات {label}: {count} سنداً مسجلاً في شركتك."

        if "شيك" in text or "cheque" in text:
            if not _allowed(user, "manage_payments", "view_ledger"):
                return _denied("manage_payments", "view_ledger")
            count = _scope(Cheque.query, Cheque, user).count()
            return f"🧾 الشيكات المسجلة في شركتك: {count} شيكاً."

        # --- expenses -----------------------------------------------------
        if "مصروف" in text or "expense" in text:
            if not _allowed(user, "manage_expenses", "view_ledger"):
                return _denied("manage_expenses", "view_ledger")
            q, label = _period(Expense.query, Expense, Expense.expense_date, message, user)
            q = _scope(q, Expense, user)
            count = q.count()
            total = db.session.query(func.sum(Expense.amount)).select_from(Expense).filter(
                Expense.id.in_(q.with_entities(Expense.id))
            ).scalar()
            return f"💸 المصروفات {label}: {count} عملية بقيمة {_money(total)} شيقل."

        # --- HR -----------------------------------------------------------
        if any(w in text for w in ("موظف", "راتب", "employee", "payroll")):
            if not _allowed(user, "manage_hr"):
                return _denied("manage_hr")
            count = _scope(Employee.query, Employee, user).count()
            return f"👷 الموظفون المسجلون في شركتك: {count} موظفاً."

        # --- users --------------------------------------------------------
        if any(w in text for w in ("مستخدم", "حساب", "user")):
            if not _allowed(user, "manage_users"):
                return _denied("manage_users")
            q = User.query.filter_by(is_active=True)
            if not getattr(user, "is_owner", False) and getattr(user, "tenant_id", None):
                q = q.filter(User.tenant_id == user.tenant_id)
            return f"👤 المستخدمون النشطون في شركتك: {q.count()} حساباً."

        # --- fiscal periods ----------------------------------------------
        if any(w in text for w in ("فترة مالية", "فترات مالية", "الفترات", "fiscal")):
            if not _allowed(user, "manage_ledger", "view_ledger"):
                return _denied("view_ledger")
            q = FiscalPeriod.query
            if not getattr(user, "is_owner", False) and getattr(user, "tenant_id", None):
                q = q.filter(FiscalPeriod.tenant_id == user.tenant_id)
            closed = q.filter_by(is_closed=True).count()
            opened = q.filter_by(is_closed=False).count()
            return f"🗓 الفترات المالية: {opened} مفتوحة و{closed} مغلقة في شركتك."

    except Exception:
        if sales_question:
            from flask import current_app

            current_app.logger.exception("Could not load assistant sales summary")
            return "تعذّر تحميل أرقام المبيعات الآن. حاول مرة أخرى."
        return None

    return None
