"""Grounded answers for factual questions asked of the AI assistant.

The assistant must answer from the live database of the *current tenant* and
only with figures the current user is allowed to see. This module is called
before the old action/menu matcher so a question such as "كم عدد المبيعات
اليوم؟" is answered with numbers instead of being misread as "create sale".

No external API is needed: every answer is deterministic and auditable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func

QUESTION_WORDS = (
    "كم", "عدد", "إجمالي", "مجموع", "كيف", "ماذا", "ما هو", "هل ",
    "؟", "?", "how many", "what is", "total", "count", "status",
)


def is_question(message: str) -> bool:
    text = (message or "").strip().lower()
    return any(word in text for word in QUESTION_WORDS)


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
    if getattr(user, "is_owner", False) or not tenant_id:
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


def answer(message: str, user):
    """Return a grounded Arabic answer string, or None when not a data question."""
    if not is_question(message):
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

        # --- sales -------------------------------------------------------
        if any(w in text for w in ("مبيع", "فاتورة مبيع", "sales", "invoice")):
            if not _allowed(user, "manage_sales", "view_reports"):
                return _denied("manage_sales", "view_reports")
            q, label = _period(Sale.query, Sale, Sale.sale_date, message, user)
            q = _scope(q, Sale, user)
            count = q.count()
            total = db.session.query(func.sum(Sale.total_amount)).select_from(Sale).filter(
                Sale.id.in_(q.with_entities(Sale.id))
            ).scalar()
            return (
                f"📊 المبيعات {label}: {count} فاتورة بقيمة {_money(total)} شيقل. "
                "الأرقام من بيانات شركتك الحالية."
            )

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
        # A grounded answer must never break chat; fall through to the old flow.
        return None

    return None
