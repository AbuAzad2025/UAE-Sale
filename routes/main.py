from datetime import datetime, timedelta, timezone
from decimal import Decimal
from flask import (
    flash,
    jsonify,
    Blueprint,
    render_template,
    current_app,
    redirect,
    request,
    url_for,
)
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from extensions import db, cache
from utils.decorators import permission_required
from models import (
    Sale,
    Customer,
    Product,
    GLAccount,
    GLJournalLine,
    Tenant,
    get_current_tenant_id,
)
from services.stock_service import StockService

DASHBOARD_CACHE_TTL = 60

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Root URL entry point.

    Behaviour depends on auth state:
    - Logged-out visitor: show the public marketing landing page.
    - Logged-in owner / super_admin: send to the platform owner console.
    - Any other logged-in user: send to the main dashboard.
    """
    if not current_user.is_authenticated:
        from flask import session

        if session.get("language") == "en":
            return render_template("public/landing_en.html")
        return render_template("public/landing.html")
    if getattr(current_user, "is_owner", False) or current_user.is_super_admin():
        return redirect(url_for("owner.dashboard"))
    return redirect(url_for("main.dashboard"))


@main_bp.route("/dashboard")
@login_required
def dashboard():  # noqa: C901
    try:
        today = datetime.now(timezone.utc).date()
        month_start = today.replace(day=1)

        stats = {}

        can_sales = current_user.has_permission("manage_sales")
        can_reports = current_user.has_permission("view_reports")
        can_customers = current_user.has_permission("manage_customers")
        can_products = current_user.has_permission("manage_products")
        can_view_products = current_user.has_permission("view_products")
        can_warehouse = current_user.has_permission("manage_warehouse")
        can_payments = current_user.has_permission("manage_payments")
        can_ledger = current_user.has_permission("view_ledger")

        show_sales_card = can_sales or can_reports
        show_customers_card = can_customers or can_reports
        show_receivables_card = can_payments or can_reports or can_ledger
        show_products_card = can_products or can_view_products or can_warehouse
        show_recent_table = can_sales

        tenant_key = get_current_tenant_id()
        cache_key_prefix = f"dashboard:{tenant_key}:{today}"

        _cache_failed = False

        def _cached(key, fn):
            """Return cached value or compute, store, and return.

            Fail-open design: if the cache backend (e.g. Redis) is unreachable
            for any reason we silently bypass the cache and compute the value
            directly.  The dashboard stays fully functional even when Redis is
            down / misconfigured / pending restart — instead of hard-500.
            We flip a module-level flag on first failure and stop talking to
            cache for the rest of the request to avoid repeated TCP RSTs.
            """
            nonlocal _cache_failed
            if _cache_failed:
                return fn()
            full_key = f"{cache_key_prefix}:{key}"
            try:
                val = cache.get(full_key)
            except Exception as exc:  # noqa: BLE001 — broad catch is intentional
                current_app.logger.warning(
                    "Dashboard cache.get(%s) failed (%s: %s). "
                    "Bypassing cache for this request.",
                    full_key,
                    type(exc).__name__,
                    exc,
                )
                _cache_failed = True
                return fn()
            if val is not None:
                return val
            val = fn()
            try:
                cache.set(full_key, val, timeout=DASHBOARD_CACHE_TTL)
            except Exception as exc:  # noqa: BLE001
                current_app.logger.warning(
                    "Dashboard cache.set(%s) failed (%s: %s). "
                    "Value computed successfully but not persisted.",
                    full_key,
                    type(exc).__name__,
                    exc,
                )
                _cache_failed = True
            return val

        if show_customers_card:
            stats["customers_count"] = _cached(
                "customers", lambda: Customer.query.filter_by(is_active=True).count()
            )

        if show_products_card:
            stats["products_count"] = _cached(
                "products", lambda: Product.query.filter_by(is_active=True).count()
            )

            low_stock = _cached(
                "low_stock",
                lambda: (
                    []
                    if not hasattr(StockService, "get_low_stock_products")
                    else StockService.get_low_stock_products(limit=10)
                ),
            )
            stats["low_stock_count"] = len(low_stock)
            stats["low_stock_products"] = low_stock

            out_of_stock = _cached(
                "out_of_stock",
                lambda: (
                    []
                    if not hasattr(StockService, "get_out_of_stock_products")
                    else StockService.get_out_of_stock_products()
                ),
            )  # noqa: E501
            stats["out_of_stock_count"] = len(out_of_stock)

        if show_sales_card:

            def _today_sales():
                return (
                    db.session.query(func.count(Sale.id), func.sum(Sale.amount_base))
                    .filter(
                        func.date(Sale.sale_date) == today, Sale.status == "confirmed"
                    )
                    .first()
                )

            today_sales = _cached("today_sales", _today_sales)
            stats["today_sales_count"] = today_sales[0] or 0
            stats["today_sales_amount"] = float(today_sales[1] or 0)

            def _month_sales():
                return (
                    db.session.query(func.count(Sale.id), func.sum(Sale.amount_base))
                    .filter(
                        func.date(Sale.sale_date) >= month_start,
                        Sale.status == "confirmed",
                    )
                    .first()
                )

            month_sales = _cached("month_sales", _month_sales)
            stats["month_sales_count"] = month_sales[0] or 0
            stats["month_sales_amount"] = float(month_sales[1] or 0)

        if current_user.can_see_costs():

            def _month_profit():
                """True profit: sum of sale.get_profit() over last-30d confirmed sales."""
                cutoff = today - timedelta(days=30)
                try:
                    recent_sales = (
                        Sale.query.options(joinedload(Sale.lines))
                        .filter(
                            func.date(Sale.sale_date) >= cutoff,
                            Sale.status == "confirmed",
                        )
                        .all()
                    )
                    total = Decimal("0")
                    for sale in recent_sales:
                        try:
                            total += Decimal(str(sale.get_profit()))
                        except Exception as exc:
                            current_app.logger.warning(
                                "Dashboard month-profit: skipping sale %s: %s",
                                getattr(sale, "id", "?"),
                                exc,
                            )
                            continue
                    return total
                except Exception as exc:
                    current_app.logger.error(
                        "Dashboard month-profit aggregate failed: %s",
                        exc,
                        exc_info=True,
                    )
                    return Decimal("0")

            stats["month_profit"] = float(_cached("month_profit", _month_profit))

        if show_receivables_card:

            def _receivables():
                return db.session.query(
                    func.sum(Sale.amount_base - Sale.paid_amount_base)
                ).filter(
                    Sale.status == "confirmed", Sale.balance_due > 0
                ).scalar() or Decimal("0")

            stats["total_receivables"] = float(_cached("receivables", _receivables))

        if current_user.can_see_costs():

            def _gl_balances():
                result = {}
                for code, key in [
                    ("1000", "cash_balance"),
                    ("1010", "bank_balance"),
                    ("1200", "inventory_value_gl"),
                ]:
                    acc = GLAccount.query.filter_by(code=code).first()
                    if acc:
                        # Use the account's authoritative posted, base-currency
                        # balance instead of raw debit-credit (which included
                        # drafts and mixed transaction currencies).
                        result[key] = float(acc.get_balance())
                return result

            gl_balances = _cached("gl_balances", _gl_balances)
            stats.update(gl_balances)

        if show_recent_table:

            def _recent_sales():
                return [
                    s.to_dict()
                    if hasattr(s, "to_dict")
                    else {
                        "id": s.id,
                        "sale_number": s.sale_number,
                        "amount": float(s.amount_base or 0),
                        "date": s.sale_date.strftime("%Y-%m-%d") if s.sale_date else "",
                        "customer": s.customer.name if s.customer else "عميل نقدي",
                        "seller": s.seller.username if s.seller else "",
                    }
                    for s in Sale.query.options(
                        joinedload(Sale.customer), joinedload(Sale.seller)
                    )
                    .filter_by(status="confirmed")
                    .order_by(Sale.sale_date.desc())
                    .limit(10)
                    .all()
                ]

            stats["recent_sales_data"] = _cached("recent_sales", _recent_sales)

        if current_user.is_seller():

            def _my_today():
                return (
                    db.session.query(func.count(Sale.id), func.sum(Sale.amount_base))
                    .filter(
                        func.date(Sale.sale_date) == today,
                        Sale.seller_id == current_user.id,
                        Sale.status == "confirmed",
                    )
                    .first()
                )

            my_today = _cached(f"my_today:{current_user.id}", _my_today)
            stats["my_today_sales_count"] = my_today[0] or 0
            stats["my_today_sales_amount"] = float(my_today[1] or 0)

        if show_recent_table:
            stats["recent_sales"] = (
                Sale.query.options(joinedload(Sale.customer), joinedload(Sale.seller))
                .filter_by(status="confirmed")
                .order_by(Sale.sale_date.desc())
                .limit(10)
                .all()
            )

        return render_template("dashboard.html", stats=stats)

    except Exception as e:
        current_app.logger.error(f"Dashboard Error: {e}", exc_info=True)
        return render_template("errors/500.html", error=str(e)), 500


@main_bp.route("/export-data", methods=["GET"])
@login_required
def tenant_data_export():
    """Export current tenant's data as ZIP (CSV per table) or JSON."""
    from services.tenant_export_service import (
        export_tenant_zip,
        export_tenant_json,
        get_tenant_export_stats,
    )

    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        flash("No tenant context available.", "danger")
        return redirect(url_for("main.dashboard"))

    fmt = request.args.get("format", "zip").lower()

    if fmt == "json":
        filename, data = export_tenant_json(tenant_id)
        mimetype = "application/json"
    elif fmt == "stats":
        stats, total = get_tenant_export_stats(tenant_id)
        return jsonify({"stats": stats, "total_rows": total})
    else:
        filename, data = export_tenant_zip(tenant_id)
        mimetype = "application/zip"

    from flask import Response

    return Response(
        data,
        mimetype=mimetype,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )



# Tenant-facing alias for the letterhead settings page. The canonical view
# lives in routes.owner but is really per-tenant data (see b50); expose it at
# a neutral URL so tenant managers don't see "/owner/" in their address bar.
# The decorators on the view itself (login_required + permission_required) are
# preserved because we call the decorated function object.
@main_bp.route("/settings/letterheads", methods=["GET", "POST"])
def letterheads_settings():
    from routes.owner import invoice_settings as _invoice_settings

    return _invoice_settings()



@main_bp.route("/settings/company", methods=["GET", "POST"])
@login_required
@permission_required("manage_settings")
def company_settings():
    """مركز إعدادات الشركة الخاص بالمستأجر — يعزل تماماً عبر tenant_id.

    يجمع البيانات التي يملك مدير المستأجر تعديلها (الاسم، العملة، الشعارات،
    الألوان، العنوان، الهاتف، الضريبة). المعرّفات الحساسة (slug، نوع النشاط،
    حالة الاشتراك) تُدار من مالك المنصة فقط.
    """
    from flask import abort

    tid = getattr(current_user, "tenant_id", None)
    if not tid:
        flash("هذه الصفحة خاصة بمديري المستأجرين.", "danger")
        return redirect(url_for("main.dashboard"))
    tenant = db.session.get(Tenant, tid)
    if tenant is None:
        abort(404)

    editable = [
        "name_ar", "name_en", "address_ar", "address_en", "city", "country",
        "phone_1", "phone_2", "mobile", "email", "website",
        "tax_number", "commercial_register", "license_number",
        "logo_url", "logo_dark_url", "favicon_url",
        "brand_color_primary", "brand_color_secondary",
        "default_currency", "default_language", "timezone",
        "enable_tax", "default_tax_rate", "tax_country", "tax_inclusive",
        "bank_name", "bank_account_number", "iban", "swift_code",
        "payment_terms_ar", "footer_text_ar", "default_invoice_note_ar",
        "enable_multi_currency",
    ]
    if request.method == "POST":
        try:
            for field in editable:
                if field in ("enable_tax", "tax_inclusive", "enable_multi_currency"):
                    setattr(tenant, field, request.form.get(field) == "on")
                elif field == "default_tax_rate":
                    setattr(tenant, field, Decimal(request.form.get(field, "0") or "0"))
                else:
                    setattr(tenant, field, (request.form.get(field, "") or "").strip() or None)
            tenant.name = tenant.name_en or tenant.name_ar
            db.session.commit()
            flash("تم حفظ إعدادات الشركة بنجاح", "success")
            return redirect(url_for("main.company_settings"))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("company settings save failed")
            flash("حدث خطأ أثناء الحفظ", "danger")

    return render_template("main/company_settings.html", tenant=tenant, editable=editable)



@main_bp.route("/settings/partners", methods=["GET", "POST"])
@login_required
@permission_required("manage_customers")
def company_partners():
    """شركاء/مساهمو المستأجر ونسبهم — صفحة محايدة للمدير.

    تعيد استخدام منطق صفحة الشركاء نفسه، لكن المستأجر يُؤخذ دائماً من
    current_user.tenant_id (لا من مبدّل شركات المالك) — عزل تام.
    """
    from flask import abort

    tid = getattr(current_user, "tenant_id", None)
    if not tid:
        flash("هذه الصفحة خاصة بمديري المستأجرين.", "danger")
        return redirect(url_for("main.dashboard"))
    tenant = db.session.get(Tenant, tid)
    if tenant is None:
        abort(404)
    from routes.owner import _partners_view

    return _partners_view(tenant, post_endpoint="main.company_partners")
