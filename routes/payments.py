from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from werkzeug.exceptions import HTTPException
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app,
    abort,
)
from flask_login import login_required, current_user
from sqlalchemy import func, select

from extensions import db
from models import Receipt, Customer, InvoiceSettings, Supplier
from services.payment_service import PaymentService
from services.currency_service import CurrencyService
from utils.decorators import permission_required, get_owned_or_404
from utils.helpers import create_audit_log
from routes.ledger import reverse_or_purge_gl_entries
from utils.i18n import t as _t

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")


def _resolve_document_rate(currency, submitted_rate, document_currency, document_rate):
    """F7: حماية من سعر صرف محمّل مسبقاً من مستند بعملة أخرى.

    نموذج سند القبض يعرض سعر صرف الفاتورة/الشراء في حقل readonly — فإن
    غيّر المستخدم عملة السند تبقى القيمة القديمة (سعر عملة المستند) وتُسجَّل
    بها عملية بعملة أخرى. هنا نرفض سعر المستند ونأخذ سعر السوق.

    Returns:
        (rate, corrected) — السعر المستخدم وهل تم استبداله بسعر السوق.
    """
    from services.currency_service import CurrencyService

    if not currency or not document_currency:
        return submitted_rate, False

    if str(currency).upper() == str(document_currency).upper():
        if document_rate:
            return Decimal(str(document_rate)), False
        return submitted_rate, False

    try:
        market = CurrencyService.get_exchange_rate(
            currency, CurrencyService.get_base_currency()
        )
    except Exception:
        market = None
    if market:
        return market, True
    return submitted_rate, False


def _archive_payment_record(record_id, reason):
    """أرشف سند صرف أو قبض - تنفيذ واحد يستعمله المساران.

    static/js/payments.js ينادي /payments/archive/<id> بصيغة JSON بينما
    المسارات القائمة /payments/payments/<id>/archive و
    /payments/receipts/<id>/archive تستعمل النموذج. التنفيذ هنا واحد حتى
    لا تختلف النتائج.

    يرفع الاستثناء عند الفشل، ويتولى كل مسار عرض الخطأ بطريقته.
    """
    from models import Payment
    from services.archive_service import ArchiveService

    reason = (reason or "").strip() or "تم الأرشفة من الواجهة"

    from werkzeug.exceptions import NotFound, Forbidden

    try:
        payment = get_owned_or_404(Payment, record_id, code=404)
    except (NotFound, Forbidden):
        payment = None
    except HTTPException:
        db.session.rollback()
        raise
    except Exception:
        raise

    if payment is not None:
        archive_service = ArchiveService()
        archive_service.archive_record("payments", payment, reason=reason, commit=False)
        create_audit_log("archive", "payments", payment.id)

        from models import GLJournalEntry

        gl_entries = GLJournalEntry.query.filter_by(
            reference_type="Payment", reference_id=record_id, is_reversed=False
        ).all()
        for entry in gl_entries:
            entry.reverse_entry(description=f"Reverse Payment {payment.payment_number}")

        db.session.commit()
        return "payments", payment

    try:
        receipt = get_owned_or_404(Receipt, record_id, code=404)
    except (NotFound, Forbidden):
        receipt = None

    if receipt is not None:
        archive_service = ArchiveService()
        archive_service.archive_record("receipts", receipt, reason=reason, commit=False)
        create_audit_log("archive", "receipts", receipt.id)
        db.session.commit()
        return "receipts", receipt

    return None, None


def _recompute_sale_settlement(sale):
    """F5: إعادة احتساب تسوية الفاتورة من المبلغ المسدَّد (عملة الأساس).

    نفس صيغة ``models/sale.py::recalculate_payment_status``: المدفوع
    يُحتسب بعملة الأساس، والمتبقي = قيمة الفاتورة − المدفوع، وحالة الدفع
    تُشتق من المتبقي.
    """
    rate = Decimal(str(sale.exchange_rate or 1))
    paid_base = Decimal(str(sale.paid_amount_base or 0))

    if rate > 0:
        sale.paid_amount = (paid_base / rate).quantize(Decimal("0.001"))

    sale.balance_due = max(
        Decimal("0"), Decimal(str(sale.amount_base or 0)) - paid_base
    )

    if sale.balance_due <= Decimal("0.01"):
        sale.payment_status = "paid"
        sale.balance_due = Decimal("0")
    elif paid_base > 0:
        sale.payment_status = "partial"
    else:
        sale.payment_status = "unpaid"

    return sale


def _reverse_receipt_allocations(receipt):
    """F5: عكس كل تخصيص على فاتورته — من التخصيصات المحفوظة في السند.

    كان يُعكس المبلغ الكلي على أول فاتورة فقط، فتُخصم الفاتورة الأولى
    مرتين وتبقى البقية مُسدَّدة بلا سند. الآن يُعكس كل تخصيص على فاتورته
    (Receipt.allocations_json / Receipt.get_allocations) وتُعاد تسوية كل
    فاتورة من المبلغ المتبقي فيها.

    ملاحظة (F5): التسوية تُحتسب هنا من المبلغ المسدَّد في الفاتورة نفسها
    ولا نستعمل ``models.sale.recompute_sale_settlement``، لأن اشتقاقها
    (``compute_sale_paid_base``) يجمع سندات القبض بـ ``Receipt.sale_id``
    فقط — أي سند تخصَّص لفاتورة ثانوية لا يظهر في اشتقاق تلك الفاتورة،
    فاستعماله هنا يمحو تسوية الفاتورة الثانية ويسبّب تضارباً في الحساب.
    """
    from models import Sale

    # A pending (unconfirmed) receipt never applied its allocations, so there
    # is nothing to subtract — doing so would create a negative settlement.
    if not getattr(receipt, "payment_confirmed", False):
        return []

    touched = []
    for alloc in receipt.get_allocations() or []:
        sale_id = alloc.get("sale_id")
        if not sale_id:
            continue
        try:
            sale = Sale.query.filter_by(id=int(sale_id)).first()
        except (TypeError, ValueError):
            continue
        if sale is None:
            continue

        amount_base = Decimal(str(alloc.get("amount_base") or 0))
        if amount_base <= 0:
            continue

        sale.paid_amount_base = max(
            Decimal("0"), Decimal(str(sale.paid_amount_base or 0)) - amount_base
        )
        _recompute_sale_settlement(sale)
        touched.append(sale)

    return touched


def _reverse_payment_allocation(payment):
    """F5: عكس تخصيص سند الصرف على فاتورته (إن وُجدت فاتورة مرتبطة).

    عكس مساهمة السند في تسوية الفاتورة هو معاكس ما يضيفه الاشتقاق
    (``models/sale.py::compute_sale_paid_base``): الاسترداد (refund) نقص
    المدفوع فيعود، والدفعة العادية زادته فيُنقص.
    """
    from models import Sale

    # A pending outgoing payment was never applied to the invoice.
    if not getattr(payment, "payment_confirmed", False) or not payment.sale_id:
        return None

    sale = Sale.query.filter_by(id=payment.sale_id).first()
    if sale is None:
        return None

    amount_base = Decimal(str(payment.amount_base or 0))
    if amount_base <= 0:
        return sale

    paid_base = Decimal(str(sale.paid_amount_base or 0))
    if (payment.payment_type or "") == "refund":
        sale.paid_amount_base = paid_base + amount_base
    else:
        sale.paid_amount_base = max(Decimal("0"), paid_base - amount_base)

    _recompute_sale_settlement(sale)
    return sale


@payments_bp.route("/archive/<int:id>", methods=["POST"])
@login_required
@permission_required("manage_payments")
def archive_payment_json(id):
    """أرشفة سند صرف/قبض بصيغة JSON.

    static/js/payments.js يستدعي هذا المسار_handle لكنه لم يكن موجوداً،
    فكان زر الأرشفة يعيد 404. يقرأ السبب من النموذج أو من JSON.
    """
    from flask import jsonify

    reason = (
        request.form.get("reason")
        or (request.get_json(silent=True) or {}).get("reason")
        or ""
    )

    try:
        table, record = _archive_payment_record(id, reason)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to archive payment {id}: {e}")
        current_app.logger.exception("handler failed")
        return jsonify(
            {
                "status": "error",
                "ok": False,
                "message": "فشلت الأرشفة: حدث خطأ غير متوقع",
            }
        ), 500

    if record is None:
        return jsonify(
            {
                "status": "error",
                "ok": False,
                "message": "السجل غير موجود",
            }
        ), 404

    return jsonify(
        {
            "status": "success",
            "ok": True,
            "id": record.id,
            "type": table,
            "message": "تمت الأرشفة بنجاح",
        }
    )


@payments_bp.route("/search-entities")
@login_required
@permission_required("manage_payments")
def search_entities():
    """اقتراح كيانات للبحث في نموذج الدفع.

    static/js/payment_form.js و static/js/payments.js يستدعيان
    /payments/search-entities?type=<type>&q=<query> ويتوقعان مصفوفة
    عناصر، كل عنصر فيه id و display و phone اختياري.
    """
    from flask import jsonify
    from models import Customer, Supplier

    entity_type = (request.args.get("type") or "customers").lower()
    query = (request.args.get("q") or "").strip()

    if entity_type in ("suppliers", "supplier"):
        if not query:
            return jsonify([])
        rows = (
            Supplier.query.filter(
                Supplier.is_active == True,  # noqa: E712
                db.or_(
                    Supplier.name.ilike(f"%{query}%"),
                    Supplier.company_name.ilike(f"%{query}%"),
                    Supplier.phone.ilike(f"%{query}%"),
                ),
            )
            .order_by(Supplier.name)
            .limit(20)
            .all()
        )
        return jsonify(
            [
                {
                    "id": s.id,
                    "display": s.name,
                    "name": s.name,
                    "phone": s.phone,
                }
                for s in rows
            ]
        )

    if not query:
        return jsonify([])

    rows = (
        Customer.query.filter(
            Customer.is_active == True,  # noqa: E712
            db.or_(
                Customer.name.ilike(f"%{query}%"),
                Customer.phone.ilike(f"%{query}%"),
            ),
        )
        .order_by(Customer.name)
        .limit(20)
        .all()
    )
    return jsonify(
        [
            {
                "id": c.id,
                "display": c.name,
                "name": c.name,
                "phone": c.phone,
            }
            for c in rows
        ]
    )


@payments_bp.route("/receipts")
@login_required
@permission_required("manage_payments")
def receipts():
    """عرض جميع المدفوعات (سندات القبض والصرف) في قائمة موحدة"""
    from models import Payment

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search = request.args.get("search", "", type=str)
    direction_filter = request.args.get(
        "direction", "", type=str
    )  # incoming, outgoing, all

    receipts_query = Receipt.query
    payments_query = Payment.query

    if search:
        search_filter = f"%{search}%"
        receipts_query = receipts_query.join(Customer).filter(
            db.or_(
                Receipt.receipt_number.ilike(search_filter),
                Customer.name.ilike(search_filter),
            )
        )
        payments_query = payments_query.filter(
            db.or_(
                Payment.payment_number.ilike(search_filter),
                Payment.supplier_name.ilike(search_filter),
            )
        )

    if direction_filter == "incoming":
        receipts_query = receipts_query.filter(Receipt.direction == "incoming")
        payments_query = payments_query.filter(Payment.direction == "incoming")
    elif direction_filter == "outgoing":
        receipts_query = receipts_query.filter(Receipt.direction == "outgoing")
        payments_query = payments_query.filter(Payment.direction == "outgoing")

    from models import ArchivedRecord

    archived_receipts_select = select(ArchivedRecord.record_id).where(
        ArchivedRecord.table_name == "receipts"
    )
    archived_payments_select = select(ArchivedRecord.record_id).where(
        ArchivedRecord.table_name == "payments"
    )

    receipts_query = receipts_query.filter(Receipt.id.notin_(archived_receipts_select))
    payments_query = payments_query.filter(Payment.id.notin_(archived_payments_select))

    if current_user.is_seller():
        receipts_query = receipts_query.filter(Receipt.user_id == current_user.id)
        payments_query = payments_query.filter(Payment.user_id == current_user.id)

    all_receipts = receipts_query.all()
    all_payments = payments_query.all()

    combined_items = []

    for receipt in all_receipts:
        combined_items.append(
            {
                "id": receipt.id,
                "number": receipt.receipt_number,
                "date": receipt.receipt_date,
                "amount": receipt.amount,
                "currency": receipt.currency,
                "amount_base": receipt.amount_base,
                "direction": receipt.direction,
                "type": "receipt",
                "customer_name": receipt.customer.name if receipt.customer else "-",
                "supplier_name": None,
                "payment_method": receipt.payment_method,
                "payment_confirmed": receipt.payment_confirmed,
                "source_type": receipt.source_type,
                "notes": receipt.notes,
            }
        )

    for payment in all_payments:
        combined_items.append(
            {
                "id": payment.id,
                "number": payment.payment_number,
                "date": payment.payment_date,
                "amount": payment.amount,
                "currency": payment.currency,
                "amount_base": payment.amount_base,
                "direction": payment.direction,
                "type": "payment",
                "customer_name": payment.customer.name if payment.customer else None,
                "supplier_name": payment.supplier_name,
                "payment_method": payment.payment_method,
                "payment_confirmed": payment.payment_confirmed,
                "source_type": payment.payment_type,
                "notes": payment.notes,
            }
        )

    combined_items.sort(key=lambda x: x["date"], reverse=True)

    start = (page - 1) * per_page
    end = start + per_page
    paginated_items = combined_items[start:end]

    class SimplePagination:
        def __init__(self, page, per_page, total, items):
            self.page = page
            self.per_page = per_page
            self.total = total
            self.items = items
            self.pages = (total + per_page - 1) // per_page
            self.has_prev = page > 1
            self.has_next = page < self.pages
            self.prev_num = page - 1 if self.has_prev else None
            self.next_num = page + 1 if self.has_next else None

    pagination = SimplePagination(
        page=page, per_page=per_page, total=len(combined_items), items=paginated_items
    )

    return render_template(
        "payments/receipts.html",
        receipts=paginated_items,
        pagination=pagination,
        direction_filter=direction_filter,
    )


@payments_bp.route("/payments/<int:id>")
@login_required
@permission_required("manage_payments")
def view_payment(id):
    """عرض سند صرف - يستخدم نفس قالب سندات القبض"""
    from models import Payment

    payment = get_owned_or_404(Payment, id)
    return render_template(
        "payments/view_receipt.html", receipt=payment, is_payment=True
    )


def _receipt_party(doc, is_payment):
    """Return the counterparty shown on a receipt/payment print."""
    if is_payment:
        supplier = getattr(doc, "supplier", None)
        name = (
            (supplier.name if supplier else None)
            or getattr(doc, "supplier_name", None)
            or "-"
        )
        phone = supplier.phone if supplier else ""
        email = supplier.email if supplier else ""
        label = _t("Supplier Details")
    else:
        cust = getattr(doc, "customer", None)
        name = (
            (cust.name if cust else None) or getattr(doc, "customer_name", None) or "-"
        )
        phone = cust.phone if cust else ""
        email = cust.email if cust else ""
        label = _t("Customer Details")
    return {"label": label, "name": name, "phone": phone, "email": email}


@payments_bp.route("/payments/<int:id>/print")
@login_required
@permission_required("manage_payments")
def print_payment(id):
    """طباعة سند صرف - يستخدم نفس قالب طباعة سندات القبض"""
    from models import Payment

    payment = get_owned_or_404(Payment, id)
    from flask import current_app

    company = {
        "name_ar": current_app.config.get("COMPANY_NAME_AR"),
        "address": current_app.config.get("COMPANY_ADDRESS"),
        "phone": current_app.config.get("COMPANY_PHONE"),
    }

    settings = InvoiceSettings.get_active()
    from utils.invoice_header import document_tenant, with_tenant_header

    try:
        settings = with_tenant_header(settings, document_tenant(payment))
    except ValueError:
        abort(409, description="لا يمكن الطباعة: الشركة المالكة للمستند غير محددة")

    template = request.args.get("template", "modern")
    _ALLOWED_TEMPLATES = ("modern", "classic", "gulf", "minimal", "simple")
    template = request.args.get("template") or "modern"
    if template not in _ALLOWED_TEMPLATES:
        template = "modern"

    template_labels = {
        "modern": _t("Modern"),
        "classic": _t("Classic"),
        "gulf": _t("Gulf"),
        "minimal": _t("Simple"),
        "simple": _t("Basic"),
    }
    available_templates = [
        (k, v) for k, v in template_labels.items() if k in _ALLOWED_TEMPLATES
    ]

    from utils.amount_in_words import amount_in_words
    from services.currency_service import CurrencyService

    try:
        _base_curr_pay = CurrencyService.get_base_currency()
    except Exception:
        _base_curr_pay = "ILS"
    receipt_amount_words_ar = amount_in_words(
        getattr(payment, "amount_base", 0), _base_curr_pay, "ar"
    )
    receipt_amount_words_en = amount_in_words(
        getattr(payment, "amount_base", 0), _base_curr_pay, "en"
    )

    return render_template(
        f"receipts/{template}.html",
        receipt=payment,
        is_payment=True,
        party=_receipt_party(payment, True),
        settings=settings,
        company=company,
        printed_at=datetime.now(),
        available_templates=available_templates,
        current_template=template,
        document_type="payment",
        document_id=payment.id,
        amount_words_ar=receipt_amount_words_ar,
        amount_words_en=receipt_amount_words_en,
    )


@payments_bp.route("/payments/<int:id>/archive", methods=["POST"])
@login_required
@permission_required("manage_payments")
def archive_payment(id):
    """أرشفة سند صرف"""
    from models import Payment
    from services.archive_service import ArchiveService

    payment = get_owned_or_404(Payment, id)

    try:
        archive_service = ArchiveService()

        archive_service.archive_record(
            "payments", payment, reason="تم أرشفة سند الصرف", commit=False
        )
        create_audit_log("archive", "payments", payment.id)

        from models import GLJournalEntry

        gl_entries = GLJournalEntry.query.filter_by(
            reference_type="Payment", reference_id=id, is_reversed=False
        ).all()
        for entry in gl_entries:
            entry.reverse_entry(description=f"Reverse Payment {payment.payment_number}")

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to archive payment {id}: {e}")
        current_app.logger.exception("handler failed")
        flash("فشلت الأرشفة: حدث خطأ غير متوقع", "danger")
        return redirect(url_for("payments.receipts"))

    return redirect(url_for("payments.receipts"))


@payments_bp.route("/payments/<int:id>/restore", methods=["POST"])
@login_required
@permission_required("manage_payments")
def restore_payment(id):
    """استعادة سند صرف من الأرشيف"""
    from models import ArchivedRecord
    from models import Payment

    get_owned_or_404(Payment, id, code=404)

    archived = ArchivedRecord.query.filter_by(
        table_name="payments", record_id=id
    ).first_or_404()

    try:
        db.session.delete(archived)
        db.session.commit()
        create_audit_log("restore", "payments", id)
    except Exception:
        db.session.rollback()

    return redirect(url_for("payments.archived_receipts"))


@payments_bp.route("/create_from_sale/<int:sale_id>", methods=["GET", "POST"])
@login_required
@permission_required("manage_payments")
def create_from_sale(sale_id):
    """إنشاء سند دفع من فاتورة بيع معينة"""
    from models import Sale

    sale = get_owned_or_404(Sale, sale_id)

    if request.method == "POST":
        try:
            try:
                _base_curr = CurrencyService.get_base_currency()
            except Exception:
                _base_curr = "ILS"
            amount = request.form.get("amount", type=float)
            currency = request.form.get("currency") or _base_curr
            user_exchange_rate = request.form.get("exchange_rate", type=float)
            payment_method_value = (request.form.get("payment_method") or "").strip()

            user_exchange_rate, rate_corrected = _resolve_document_rate(
                currency, user_exchange_rate, sale.currency, sale.exchange_rate
            )
            if rate_corrected:
                flash(
                    "تم اعتماد سعر صرف السوق لأن عملة السند تختلف عن عملة الفاتورة.",
                    "warning",
                )

            if not payment_method_value:
                flash("يرجى اختيار طريقة الدفع.", "warning")
                exchange_rates = CurrencyService.get_all_rates(_base_curr)
                suggested_amount = sale.balance_due
                return render_template(
                    "payments/create_receipt.html",
                    customers=[sale.customer],
                    preselected_customer=sale.customer,
                    suggested_amount=suggested_amount,
                    exchange_rates=exchange_rates,
                    sale=sale,
                    form_data=request.form,
                )

            reference_number = request.form.get("reference_number")
            cheque_number = request.form.get("cheque_number")
            cheque_date = request.form.get("cheque_date") or None
            bank_name = request.form.get("bank_name")
            notes = request.form.get("notes")

            allocate_to_sales = {sale.id: amount}

            receipt_data = {
                "customer_id": sale.customer_id,
                "amount": amount,
                "currency": currency,
                "user_exchange_rate": user_exchange_rate,
                "payment_method": payment_method_value,
                "reference_number": reference_number,
                "cheque_number": cheque_number,
                "cheque_date": cheque_date,
                "bank_name": bank_name,
                "notes": notes,
                "allocate_to_sales": allocate_to_sales,
            }

            receipt = PaymentService.create_receipt(receipt_data)

            create_audit_log("create", "receipts", receipt.id)

            flash("تم إنشاء سند القبض بنجاح", "success")
            return redirect(url_for("payments.view_receipt", id=receipt.id))

        except Exception:
            current_app.logger.exception("handler failed")
            flash(
                "حدث خطأ: حدث خطأ غير متوقع\nتحقق من البيانات المدخلة وحاول مرة أخرى.",
                "danger",
            )

    customers = [sale.customer]  # العميل من الفاتورة
    suggested_amount = sale.balance_due
    try:
        _base_curr_get = CurrencyService.get_base_currency()
    except Exception:
        _base_curr_get = "ILS"
    exchange_rates = CurrencyService.get_all_rates(_base_curr_get)

    return render_template(
        "payments/create_receipt.html",
        customers=customers,
        preselected_customer=sale.customer,
        suggested_amount=suggested_amount,
        exchange_rates=exchange_rates,
        sale=sale,
    )  # تمرير بيانات الفاتورة


@payments_bp.route("/voucher/create", methods=["GET"])
@login_required
@permission_required("manage_payments")
def create_voucher():
    """عرض صفحة إنشاء سند مالي موحد (قبض/صرف)"""
    from models import Supplier

    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()

    customers_data = [
        {"id": c.id, "name": c.name, "type": c.customer_type} for c in customers
    ]

    suppliers_data = [{"id": s.id, "name": s.name} for s in suppliers]

    return render_template(
        "payments/voucher.html",
        customers=customers_data,
        suppliers=suppliers_data,
        today_date=datetime.now().date().isoformat(),
    )


@payments_bp.route("/voucher/submit", methods=["POST"])
@login_required
@permission_required("manage_payments")
def create_voucher_submit():  # noqa: C901
    """معالجة حفظ السند المالي الموحد"""
    try:
        try:
            _base_curr_v = CurrencyService.get_base_currency()
        except Exception:
            _base_curr_v = "ILS"
        direction = request.form.get("direction")  # incoming, outgoing
        party_type = request.form.get("party_type")  # customer, supplier
        party_id = request.form.get("party_id", type=int)
        amount_raw = request.form.get("amount")
        amount = None
        if amount_raw and str(amount_raw).strip():
            try:
                amount = Decimal(str(amount_raw).strip())
            except Exception:
                amount = None
        payment_method = request.form.get("payment_method")
        date_str = request.form.get("date")
        notes = request.form.get("notes")

        currency = request.form.get("currency") or _base_curr_v
        user_exchange_rate = request.form.get("exchange_rate", type=float, default=1.0)

        cheque_number = request.form.get("cheque_number")
        cheque_date = request.form.get("cheque_date")
        bank_name = request.form.get("bank_name")

        cheque_due = None
        if cheque_date:
            try:
                cheque_due = datetime.strptime(cheque_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                cheque_due = None

        if not party_id or not amount:
            flash("يرجى تعبئة جميع الحقول الإلزامية", "warning")
            return redirect(url_for("payments.create_voucher"))

        if direction == "incoming":
            if party_type == "customer":
                receipt_data = {
                    "customer_id": party_id,
                    "amount": amount,
                    "currency": currency,
                    "user_exchange_rate": user_exchange_rate,
                    "payment_method": payment_method,
                    "notes": notes,
                    "cheque_number": cheque_number
                    if payment_method == "cheque"
                    else None,
                    "cheque_date": cheque_date if payment_method == "cheque" else None,
                    "bank_name": bank_name if payment_method == "cheque" else None,
                }
                receipt = PaymentService.create_receipt(receipt_data)
                flash(
                    f"تم إنشاء سند القبض رقم {receipt.receipt_number} بنجاح", "success"
                )
                return redirect(url_for("payments.receipts"))

            elif party_type == "supplier":
                from models import Payment
                from utils.helpers import generate_number

                exchange_rate = CurrencyService.get_exchange_rate(
                    currency, _base_curr_v, user_rate=user_exchange_rate
                )
                amount_decimal = Decimal(str(amount))
                amount_base = amount_decimal * exchange_rate

                supplier = get_owned_or_404(Supplier, party_id)
                is_cheque = payment_method == "cheque"
                received_on = (
                    datetime.strptime(date_str, "%Y-%m-%d").date()
                    if date_str
                    else datetime.now().date()
                )
                if is_cheque:
                    if (
                        not cheque_number
                        or not bank_name
                        or not cheque_due
                        or cheque_due < received_on
                    ):
                        raise ValueError(
                            "أدخل رقم الشيك والبنك وتاريخ استحقاق لا يسبق الاستلام."
                        )
                    if amount_decimal != amount_decimal.quantize(Decimal("0.01")):
                        raise ValueError("مبلغ الشيك يقبل منزلتين عشريتين.")
                    amount_base = amount_base.quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    if amount_base <= 0:
                        raise ValueError("يجب أن يكون مبلغ الشيك موجبًا.")
                payment = Payment(
                    payment_number=generate_number(
                        "PAY", Payment, "payment_number"
                    ),  # ربما نحتاج تسلسل منفصل؟
                    payment_type="refund",  # استرداد
                    direction="incoming",
                    supplier_id=supplier.id,
                    supplier_name=supplier.name,
                    amount=amount_decimal,
                    currency=currency,
                    exchange_rate=exchange_rate,
                    amount_base=amount_base,
                    payment_method=payment_method,
                    notes=notes,
                    cheque_number=cheque_number if payment_method == "cheque" else None,
                    cheque_date=cheque_due if payment_method == "cheque" else None,
                    bank_name=bank_name if payment_method == "cheque" else None,
                    user_id=current_user.id,
                    payment_confirmed=not is_cheque,
                    payment_date=datetime.combine(received_on, datetime.min.time()),
                    tenant_id=supplier.tenant_id,
                )
                db.session.add(payment)
                db.session.flush()

                from services.gl_service import GLService
                from services.account_resolution import AccountResolver, AccountRole

                GLService.ensure_core_accounts()
                if is_cheque:
                    from models import Cheque

                    cheque = Cheque(
                        cheque_number=generate_number("CHQ", Cheque, "cheque_number"),
                        cheque_bank_number=cheque_number,
                        cheque_type="incoming",
                        bank_name=bank_name,
                        supplier_id=supplier.id,
                        payment_id=payment.id,
                        amount=amount_decimal,
                        amount_base=amount_base,
                        currency=currency,
                        exchange_rate=exchange_rate,
                        issue_date=received_on,
                        due_date=cheque_due,
                        user_id=current_user.id,
                        tenant_id=supplier.tenant_id,
                    )
                    db.session.add(cheque)
                    db.session.flush()
                    payment.cheque_id = cheque.id
                    cheque.receive_cheque()
                    db.session.commit()
                    flash("تم تسجيل شيك المورد تحت التحصيل", "success")
                    return redirect(url_for("payments.receipts"))

                debit_account = GLService.get_payment_debit_account(
                    payment_method, tenant_id=supplier.tenant_id
                )
                lines = [
                    {
                        "account": debit_account,
                        "debit": amount_decimal,
                        "description": f"استرداد من المورد {supplier.name}",
                    },
                    {
                        "account": AccountResolver.resolve(
                            AccountRole.AP_CONTROL, tenant_id=supplier.tenant_id
                        ),
                        "credit": amount_decimal,
                        "description": f"سند قبض من مورد {payment.payment_number}",
                    },
                ]
                GLService.post_entry(
                    lines,
                    description=f"Supplier Refund {payment.payment_number}",
                    reference_type="Payment",
                    reference_id=payment.id,
                    idempotency_key=f"Payment:{payment.id}",
                    currency=currency,
                    exchange_rate=exchange_rate,
                    entry_date=payment.payment_date,
                    tenant_id=supplier.tenant_id,
                )

                db.session.commit()
                flash("تم إنشاء سند قبض من مورد بنجاح", "success")
                return redirect(url_for("payments.receipts"))

        elif direction == "outgoing":
            from models import Payment
            from utils.helpers import generate_number

            exchange_rate = CurrencyService.get_exchange_rate(
                currency, _base_curr_v, user_rate=user_exchange_rate
            )
            amount_decimal = Decimal(str(amount))
            amount_base = amount_decimal * exchange_rate

            issued_on = (
                datetime.strptime(date_str, "%Y-%m-%d").date()
                if date_str
                else datetime.now().date()
            )
            if payment_method == "cheque":
                if (
                    not cheque_number
                    or not bank_name
                    or not cheque_due
                    or cheque_due < issued_on
                ):
                    raise ValueError(
                        "أدخل رقم الشيك والبنك وتاريخ استحقاق لا يسبق الإصدار."
                    )
                if amount_decimal != amount_decimal.quantize(Decimal("0.01")):
                    raise ValueError("مبلغ الشيك يقبل منزلتين عشريتين.")
                amount_base = amount_base.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            if not amount_base.is_finite() or amount_base <= 0:
                raise ValueError("يجب أن يكون مبلغ السند موجبًا.")

            if party_type == "supplier":
                supplier = get_owned_or_404(Supplier, party_id)
                payment = Payment(
                    payment_number=generate_number("PAY", Payment, "payment_number"),
                    payment_type="bill_payment",
                    direction="outgoing",
                    tenant_id=supplier.tenant_id,
                    payment_date=datetime.combine(issued_on, datetime.min.time()),
                    supplier_id=supplier.id,
                    supplier_name=supplier.name,
                    amount=amount_decimal,
                    currency=currency,
                    exchange_rate=exchange_rate,
                    amount_base=amount_base,
                    payment_method=payment_method,
                    payment_confirmed=payment_method != "cheque",
                    notes=notes,
                    cheque_number=cheque_number if payment_method == "cheque" else None,
                    cheque_date=cheque_due if payment_method == "cheque" else None,
                    bank_name=bank_name if payment_method == "cheque" else None,
                    user_id=current_user.id,
                )
                db.session.add(payment)
                db.session.flush()  # Flush to get ID

                if payment_method == "cheque" and cheque_number:
                    from models import Cheque

                    cheque = Cheque(
                        cheque_number=cheque_number,
                        cheque_bank_number=cheque_number,
                        cheque_type="outgoing",
                        supplier_id=supplier.id,
                        payment_id=payment.id,
                        amount=payment.amount,
                        currency=payment.currency,
                        exchange_rate=payment.exchange_rate,
                        amount_base=payment.amount_base,
                        issue_date=issued_on,
                        due_date=cheque_due or datetime.now().date(),
                        bank_name=bank_name,
                        payee_name=supplier.name,
                        status="pending",
                        notes=notes,
                        user_id=current_user.id,
                    )
                    db.session.add(cheque)
                    db.session.flush()

                    payment.cheque_id = cheque.id
                    cheque.issue_cheque(actor_id=current_user.id)

                else:
                    from services.gl_service import GLService
                    from services.account_resolution import AccountResolver, AccountRole

                    GLService.ensure_core_accounts()

                    credit_account = GLService.get_payment_debit_account(
                        payment_method, tenant_id=supplier.tenant_id
                    )
                    lines = [
                        {
                            "account": AccountResolver.resolve(
                                AccountRole.AP_CONTROL, tenant_id=supplier.tenant_id
                            ),
                            "debit": payment.amount,
                            "description": f"سداد للمورد {payment.supplier_name}",
                        },
                        {
                            "account": credit_account,
                            "credit": payment.amount,
                            "description": f"سند صرف {payment.payment_number}",
                        },
                    ]
                    GLService.post_entry(
                        lines,
                        description=f"Payment {payment.payment_number}",
                        reference_type="Payment",
                        reference_id=payment.id,
                        idempotency_key=f"Payment:{payment.id}",
                        currency=currency,
                        exchange_rate=exchange_rate,
                        tenant_id=payment.tenant_id,
                        entry_date=payment.payment_date,
                        created_by=current_user.id,
                    )

                db.session.commit()
                flash("تم إنشاء سند صرف لمورد بنجاح", "success")
                return redirect(url_for("payments.receipts"))

            elif party_type == "customer":
                customer = get_owned_or_404(Customer, party_id)
                payment = Payment(
                    payment_number=generate_number("PAY", Payment, "payment_number"),
                    payment_type="refund",
                    direction="outgoing",
                    tenant_id=customer.tenant_id,
                    payment_date=datetime.combine(issued_on, datetime.min.time()),
                    customer_id=customer.id,
                    amount=amount_decimal,
                    currency=currency,
                    exchange_rate=exchange_rate,
                    amount_base=amount_base,
                    payment_method=payment_method,
                    payment_confirmed=payment_method != "cheque",
                    notes=notes,
                    cheque_number=cheque_number if payment_method == "cheque" else None,
                    cheque_date=cheque_due if payment_method == "cheque" else None,
                    bank_name=bank_name if payment_method == "cheque" else None,
                    user_id=current_user.id,
                )
                db.session.add(payment)
                db.session.flush()  # Flush to get ID

                if payment_method == "cheque" and cheque_number:
                    from models import Cheque

                    cheque = Cheque(
                        cheque_number=cheque_number,
                        cheque_bank_number=cheque_number,
                        cheque_type="outgoing",
                        customer_id=customer.id,
                        payment_id=payment.id,
                        amount=payment.amount,
                        currency=payment.currency,
                        exchange_rate=payment.exchange_rate,
                        amount_base=payment.amount_base,
                        issue_date=issued_on,
                        due_date=cheque_due or datetime.now().date(),
                        bank_name=bank_name,
                        payee_name=customer.name,
                        status="pending",
                        notes=notes,
                        user_id=current_user.id,
                    )
                    db.session.add(cheque)
                    db.session.flush()

                    payment.cheque_id = cheque.id
                    cheque.issue_cheque(actor_id=current_user.id)

                else:
                    from services.gl_service import GLService

                    GLService.ensure_core_accounts()

                    credit_account = GLService.get_payment_debit_account(
                        payment_method, tenant_id=customer.tenant_id
                    )

                    debit_account = GLService.get_customer_credit_account(customer)

                    lines = [
                        {
                            "account": debit_account,
                            "debit": payment.amount,
                            "description": f"سداد/سحب {customer.name}",
                            "party_id": customer.id
                            if customer.customer_type == "partner"
                            else None,
                        },
                        {
                            "account": credit_account,
                            "credit": payment.amount,
                            "description": f"سند صرف {payment.payment_number}",
                        },
                    ]
                    GLService.post_entry(
                        lines,
                        description=f"Payment {payment.payment_number}",
                        reference_type="Payment",
                        reference_id=payment.id,
                        idempotency_key=f"Payment:{payment.id}",
                        currency=currency,
                        exchange_rate=exchange_rate,
                        tenant_id=payment.tenant_id,
                        entry_date=payment.payment_date,
                        created_by=current_user.id,
                    )

                db.session.commit()
                flash("تم إنشاء سند صرف لعميل/شريك بنجاح", "success")
                return redirect(url_for("payments.receipts"))

    except HTTPException:
        db.session.rollback()
        raise
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Voucher creation error: {e}")
        current_app.logger.exception("handler failed")
        flash("حدث خطأ أثناء حفظ السند: حدث خطأ غير متوقع", "danger")
        return redirect(url_for("payments.create_voucher"))

    return redirect(url_for("payments.receipts"))


@payments_bp.route("/receipts/create", methods=["GET", "POST"])
@login_required
@permission_required("manage_payments")
def create_receipt():
    return redirect(url_for("payments.create_voucher"))


@payments_bp.route("/receipts/<int:id>")
@login_required
@permission_required("manage_payments")
def view_receipt(id):
    receipt = get_owned_or_404(Receipt, id)

    if (
        current_user.is_seller()
        and not current_user.is_owner
        and receipt.user_id != current_user.id
    ):
        flash("ليس لديك صلاحية لعرض هذا السند", "danger")
        return redirect(url_for("payments.receipts"))

    return render_template("payments/view_receipt.html", receipt=receipt)


@payments_bp.route("/receipts/<int:id>/print")
@login_required
@permission_required("manage_payments")
def print_receipt(id):
    receipt = get_owned_or_404(Receipt, id)

    if (
        current_user.is_seller()
        and not current_user.is_owner
        and receipt.user_id != current_user.id
    ):
        flash("ليس لديك صلاحية لطباعة هذا السند", "danger")
        return redirect(url_for("payments.receipts"))

    settings = InvoiceSettings.get_active()
    from utils.invoice_header import document_tenant, with_tenant_header

    try:
        settings = with_tenant_header(settings, document_tenant(receipt))
    except ValueError:
        abort(409, description="لا يمكن الطباعة: الشركة المالكة للمستند غير محددة")

    import re

    _ALLOWED_TEMPLATES = ("modern", "classic", "gulf", "minimal", "simple")
    template = request.args.get("template") or (
        settings.active_template if settings and settings.active_template else "modern"
    )
    if template not in _ALLOWED_TEMPLATES and not re.fullmatch(
        r"[A-Za-z0-9_-]+", template or ""
    ):
        template = "modern"
    if template not in _ALLOWED_TEMPLATES:
        template = "modern"

    template_labels = {
        "modern": _t("Modern"),
        "classic": _t("Classic"),
        "gulf": _t("Gulf"),
        "minimal": _t("Simple"),
        "simple": _t("Basic"),
    }
    available_templates = [
        (k, v) for k, v in template_labels.items() if k in _ALLOWED_TEMPLATES
    ]

    from flask import current_app

    company = {
        "name_ar": current_app.config.get("COMPANY_NAME_AR"),
        "address": current_app.config.get("COMPANY_ADDRESS"),
        "phone": current_app.config.get("COMPANY_PHONE"),
    }

    from utils.amount_in_words import amount_in_words
    from services.currency_service import CurrencyService

    try:
        _base_curr_rcp = CurrencyService.get_base_currency()
    except Exception:
        _base_curr_rcp = "ILS"
    receipt_amount_words_ar = amount_in_words(
        getattr(receipt, "amount_base", 0), _base_curr_rcp, "ar"
    )
    receipt_amount_words_en = amount_in_words(
        getattr(receipt, "amount_base", 0), _base_curr_rcp, "en"
    )

    try:
        return render_template(
            f"receipts/{template}.html",
            receipt=receipt,
            party=_receipt_party(receipt, False),
            settings=settings,
            company=company,
            printed_at=datetime.now(),
            available_templates=available_templates,
            current_template=template,
            document_type="receipt",
            document_id=receipt.id,
            amount_words_ar=receipt_amount_words_ar,
            amount_words_en=receipt_amount_words_en,
        )
    except Exception:
        return render_template(
            "receipts/modern.html",
            receipt=receipt,
            party=_receipt_party(receipt, False),
            settings=settings,
            company=company,
            printed_at=datetime.now(),
            available_templates=available_templates,
            current_template="modern",
            document_type="receipt",
            document_id=receipt.id,
            amount_words_ar=receipt_amount_words_ar,
            amount_words_en=receipt_amount_words_en,
        )


@payments_bp.route("/archived")
@login_required
@permission_required("manage_payments")
def archived_receipts():
    """عرض السندات المؤرشفة"""
    from models import ArchivedRecord

    archived_receipts_query = db.session.query(ArchivedRecord).filter(
        ArchivedRecord.table_name == "receipts"
    )
    archived_payments_query = db.session.query(ArchivedRecord).filter(
        ArchivedRecord.table_name == "payments"
    )

    archived_items = []

    for archived in archived_receipts_query.all():
        data = archived.data
        archived_items.append(
            {
                "id": archived.record_id,
                "number": data.get("receipt_number"),
                "date": datetime.fromisoformat(
                    data.get("receipt_date").replace("Z", "+00:00")
                )
                if isinstance(data.get("receipt_date"), str)
                else data.get("receipt_date"),  # noqa: E501
                "amount": float(data.get("amount", 0)),
                "currency": data.get("currency"),
                "amount_base": float(data.get("amount_base", 0)),
                "type": "receipt",
                "customer_name": data.get("customer_name"),
                "supplier_name": None,
                "source_type": data.get("source_type"),
                "archived_at": archived.archived_at,
            }
        )

    for archived in archived_payments_query.all():
        data = archived.data
        archived_items.append(
            {
                "id": archived.record_id,
                "number": data.get("payment_number"),
                "date": datetime.fromisoformat(
                    data.get("payment_date").replace("Z", "+00:00")
                )
                if isinstance(data.get("payment_date"), str)
                else data.get("payment_date"),  # noqa: E501
                "amount": float(data.get("amount", 0)),
                "currency": data.get("currency"),
                "amount_base": float(data.get("amount_base", 0)),
                "type": "payment",
                "customer_name": None,
                "supplier_name": data.get("supplier_name"),
                "source_type": data.get("payment_type"),
                "archived_at": archived.archived_at,
            }
        )

    archived_items.sort(key=lambda x: x["archived_at"], reverse=True)

    return render_template("payments/archived.html", archived_items=archived_items)


@payments_bp.route("/receipts/<int:id>/archive", methods=["POST"])
@login_required
@permission_required("manage_payments")
def archive_receipt(id):
    """أرشفة سند قبض"""
    from services.archive_service import ArchiveService

    receipt = get_owned_or_404(Receipt, id)

    try:
        archive_service = ArchiveService()
        archive_service.archive_record("receipts", receipt, reason="تم أرشفة سند القبض")
        create_audit_log("archive", "receipts", receipt.id)
    except Exception:
        db.session.rollback()

    return redirect(url_for("payments.receipts"))


@payments_bp.route("/receipts/<int:id>/restore", methods=["POST"])
@login_required
@permission_required("manage_payments")
def restore_receipt(id):
    """استعادة سند قبض من الأرشيف"""
    from models import ArchivedRecord

    archived = ArchivedRecord.query.filter_by(
        table_name="receipts", record_id=id
    ).first_or_404()

    try:
        db.session.delete(archived)
        db.session.commit()
        create_audit_log("restore", "receipts", id)
    except Exception:
        db.session.rollback()

    return redirect(url_for("payments.archived_receipts"))


@payments_bp.route("/receipts/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_payments")
def delete_receipt(id):  # noqa: C901
    """حذف أو أرشفة سند قبض"""
    from models import Receipt
    from services.archive_service import ArchiveService

    receipt = get_owned_or_404(Receipt, id)
    from models import Cheque

    linked_cheques = Cheque.query.filter_by(receipt_id=receipt.id).all()

    has_links = False
    if receipt.source_type == "sale" and receipt.source_id:
        has_links = True
    if receipt.sale_id or receipt.purchase_id or receipt.get_allocations():
        has_links = True
    if receipt.cheque_id:
        has_links = True
    if linked_cheques:  # التحقق من الشيكات المرتبطة
        has_links = True

    try:
        _reverse_receipt_allocations(receipt)

        if has_links:
            try:
                reverse_or_purge_gl_entries(
                    "Receipt",
                    receipt.id,
                    description=f"عكس سند قبض {receipt.receipt_number}",
                )
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f"Failed to reverse GL entries for receipt {receipt.id}: {e}"
                )
                flash(
                    f"❌ تعذّر عكس القيود المحاسبية لسند القبض "
                    f'"{receipt.receipt_number}" — لم تُؤرشف السند.\n💡 {e}',
                    "danger",
                )
                return redirect(url_for("payments.view_receipt", id=id))

            archive_service = ArchiveService()
            archive_service.archive_record(
                "receipts",
                receipt,
                reason="تم أرشفة السند لوجود ارتباطات",
                commit=False,
            )

            for cheque in linked_cheques:
                archive_service.archive_record(
                    "cheques",
                    cheque,
                    reason="تم أرشفة الشيك لارتباطه بسند مؤرشف",
                    commit=False,
                )

            if receipt.customer_id:
                from models.customer import recompute_customer_balance

                recompute_customer_balance(receipt.customer_id)

            create_audit_log("archive", "receipts", id)
            db.session.commit()
            flash(
                f'تم أرشفة سند القبض "{receipt.receipt_number}" (لوجود حركات مرتبطة)',
                "warning",
            )
        else:
            try:
                gl_result = reverse_or_purge_gl_entries(
                    "Receipt",
                    receipt.id,
                    description=f"عكس سند قبض {receipt.receipt_number} (حذف نهائي)",
                )
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f"Failed to reverse GL entries for receipt {receipt.id}: {e}"
                )
                flash(
                    f"❌ تعذّر عكس القيود المحاسبية لسند القبض "
                    f'"{receipt.receipt_number}" — لم يُحذف السند.\n💡 {e}',
                    "danger",
                )
                return redirect(url_for("payments.view_receipt", id=id))
            for ch in linked_cheques:
                ch.gl_journal_entry_id = None
                ch.gl_clearing_entry_id = None
                ch.gl_bounce_entry_id = None
                db.session.flush()
                for ref in (
                    "cheque_receive",
                    "cheque_issue",
                    "cheque_cancel",
                    "cheque_clear",
                    "cheque_bounce",
                    "Cheque",
                ):
                    reverse_or_purge_gl_entries(
                        ref,
                        ch.id,
                        description=f"عكس قيد شيك {ch.cheque_bank_number} (حذف سند)",
                    )

            for cheque in linked_cheques:
                db.session.delete(cheque)

            db.session.delete(receipt)

            if receipt.customer_id:
                from models.customer import recompute_customer_balance

                recompute_customer_balance(receipt.customer_id)

            create_audit_log("delete", "receipts", id)
            db.session.commit()
            if gl_result["reversed"]:
                flash(
                    f'تم حذف سند القبض "{receipt.receipt_number}" نهائياً — '
                    f"وعُكست قيوده المحاسبية ({gl_result['reversed']} قيد) "
                    f"بدل حذفها حفاظاً على الأثر المحاسبي.",
                    "success",
                )
            else:
                flash(f'تم حذف سند القبض "{receipt.receipt_number}" نهائياً', "success")

        return redirect(url_for("payments.receipts"))

    except Exception:
        db.session.rollback()
        current_app.logger.exception("handler failed")
        flash("فشل الحذف: حدث خطأ غير متوقع", "danger")
        return redirect(url_for("payments.view_receipt", id=id))


@payments_bp.route("/payments/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_payments")
def delete_payment(id):
    """حذف أو أرشفة سند صرف"""
    from models import Payment
    from services.archive_service import ArchiveService

    payment = get_owned_or_404(Payment, id)
    from models import Cheque as _Cheque

    linked_cheques = _Cheque.query.filter_by(payment_id=payment.id).all()

    has_links = False
    if payment.cheque_id:
        has_links = True
    if linked_cheques:  # التحقق من الشيكات المرتبطة
        has_links = True

    try:
        _reverse_payment_allocation(payment)

        if has_links:
            try:
                reverse_or_purge_gl_entries(
                    "Payment",
                    payment.id,
                    description=f"عكس سند صرف {payment.payment_number}",
                )
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f"Failed to reverse GL entries for payment {payment.id}: {e}"
                )
                flash(
                    f"❌ تعذّر عكس القيود المحاسبية لسند الصرف "
                    f'"{payment.payment_number}" — لم تُؤرشف السند.\n💡 {e}',
                    "danger",
                )
                return redirect(url_for("payments.view_payment", id=id))

            archive_service = ArchiveService()
            archive_service.archive_record(
                "payments",
                payment,
                reason="تم أرشفة السند لوجود ارتباطات",
                commit=False,
            )

            for cheque in linked_cheques:
                archive_service.archive_record(
                    "cheques",
                    cheque,
                    reason="تم أرشفة الشيك لارتباطه بسند مؤرشف",
                    commit=False,
                )

            if payment.customer_id:
                from models.customer import recompute_customer_balance

                recompute_customer_balance(payment.customer_id)

            create_audit_log("archive", "payments", id)
            db.session.commit()
            flash(
                f'تم أرشفة سند الصرف "{payment.payment_number}" (لوجود حركات مرتبطة)',
                "warning",
            )
        else:
            try:
                gl_result = reverse_or_purge_gl_entries(
                    "Payment",
                    payment.id,
                    description=f"عكس سند صرف {payment.payment_number} (حذف نهائي)",
                )
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f"Failed to reverse GL entries for payment {payment.id}: {e}"
                )
                flash(
                    f"❌ تعذّر عكس القيود المحاسبية لسند الصرف "
                    f'"{payment.payment_number}" — لم يُحذف السند.\n💡 {e}',
                    "danger",
                )
                return redirect(url_for("payments.view_payment", id=id))
            for ch in linked_cheques:
                ch.gl_journal_entry_id = None
                ch.gl_clearing_entry_id = None
                ch.gl_bounce_entry_id = None
                db.session.flush()
                for ref in (
                    "cheque_receive",
                    "cheque_issue",
                    "cheque_cancel",
                    "cheque_clear",
                    "cheque_bounce",
                ):
                    reverse_or_purge_gl_entries(
                        ref,
                        ch.id,
                        description=f"عكس قيد شيك {ch.cheque_bank_number} (حذف سند)",
                    )

            for cheque in linked_cheques:
                db.session.delete(cheque)

            db.session.delete(payment)

            if payment.customer_id:
                from models.customer import recompute_customer_balance

                recompute_customer_balance(payment.customer_id)

            create_audit_log("delete", "payments", id)
            db.session.commit()
            if gl_result["reversed"]:
                flash(
                    f'تم حذف سند الصرف "{payment.payment_number}" نهائياً — '
                    f"وعُكست قيوده المحاسبية ({gl_result['reversed']} قيد) "
                    f"بدل حذفها حفاظاً على الأثر المحاسبي.",
                    "success",
                )
            else:
                flash(f'تم حذف سند الصرف "{payment.payment_number}" نهائياً', "success")

        return redirect(url_for("payments.receipts"))

    except Exception:
        db.session.rollback()
        current_app.logger.exception("handler failed")
        flash("فشل الحذف: حدث خطأ غير متوقع", "danger")
        return redirect(url_for("payments.view_payment", id=id))


@payments_bp.route("/create_payment/<int:purchase_id>", methods=["GET", "POST"])
@login_required
@permission_required("manage_payments")
def create_payment(purchase_id):  # noqa: C901
    """إنشاء سند صرف لفاتورة مشتريات"""
    from models import Cheque, Purchase, Payment, Supplier
    from utils.errors import ValidationError
    from utils.helpers import generate_number

    purchase = get_owned_or_404(Purchase, purchase_id)
    if request.method == "POST":
        # Lock the invoice before checking its available balance. Lock only
        # the header because Purchase loads line rows using an outer join.
        db.session.execute(
            select(Purchase.id)
            .where(Purchase.id == purchase.id, Purchase.tenant_id == purchase.tenant_id)
            .with_for_update()
        ).scalar_one()
        db.session.refresh(purchase, ["amount_base", "paid_amount", "status"])
    if purchase.status != "confirmed":
        flash("يمكن إنشاء سند صرف لفاتورة شراء مؤكدة فقط.", "warning")
        return redirect(url_for("purchases.view", id=purchase_id))
    supplier = (
        get_owned_or_404(Supplier, purchase.supplier_id)
        if purchase.supplier_id
        else None
    )

    reserved = db.session.scalar(
        select(func.coalesce(func.sum(Payment.amount_base), 0))
        .join(Cheque, Payment.cheque_id == Cheque.id)
        .where(
            Payment.purchase_id == purchase.id,
            Payment.tenant_id == purchase.tenant_id,
            Payment.direction == "outgoing",
            Payment.payment_confirmed.is_(False),
            Cheque.tenant_id == purchase.tenant_id,
            Cheque.is_active.is_(True),
            Cheque.status.in_(("pending", "under_collection", "deposited")),
        )
    )
    balance = (
        (purchase.amount_base or Decimal("0")) - purchase.get_paid_amount() - reserved
    )
    suggested_amount = max(balance, Decimal("0"))

    if request.method == "POST":
        try:
            amount = request.form.get("amount", "")
            payment_method_value = (request.form.get("payment_method") or "").strip()
            if not payment_method_value:
                flash("يرجى اختيار طريقة الدفع.", "warning")
                return render_template(
                    "payments/create_receipt.html",
                    purchase=purchase,
                    supplier=supplier,
                    suggested_amount=suggested_amount,
                    is_payment=True,
                    form_data=request.form,
                )
            notes = request.form.get("notes", "")
            exchange_rate = Decimal(request.form.get("exchange_rate") or "1")
            try:
                _base_curr_pay = CurrencyService.get_base_currency()
            except Exception:
                _base_curr_pay = "ILS"
            currency = request.form.get("currency") or _base_curr_pay

            exchange_rate, rate_corrected = _resolve_document_rate(
                currency, exchange_rate, purchase.currency, purchase.exchange_rate
            )
            if rate_corrected:
                flash(
                    "تم اعتماد سعر صرف السوق لأن عملة السند تختلف عن عملة فاتورة الشراء.",
                    "warning",
                )

            reference_number = request.form.get("reference_number")
            cheque_number = request.form.get("cheque_number")
            cheque_date = request.form.get("cheque_date") or None
            bank_name = request.form.get("bank_name")
            bank_name_transfer = request.form.get("bank_name_transfer")
            reference_number_transfer = request.form.get("reference_number_transfer")
            card_last4 = request.form.get("card_last4")
            reference_number_card = request.form.get("reference_number_card")

            amount_decimal = Decimal(str(amount))
            exchange_rate_decimal = Decimal(str(exchange_rate))
            if any(
                not value.is_finite() or value <= 0
                for value in (amount_decimal, exchange_rate_decimal)
            ):
                raise ValidationError("المبلغ وسعر الصرف يجب أن يكونا أكبر من صفر.")
            pays_by_cheque = payment_method_value == "cheque"
            if pays_by_cheque and amount_decimal != amount_decimal.quantize(
                Decimal("0.01")
            ):
                raise ValidationError("مبلغ الشيك يقبل منزلتين عشريتين.")
            amount_base = (amount_decimal * exchange_rate_decimal).quantize(
                Decimal("0.01" if pays_by_cheque else "0.001"), rounding=ROUND_HALF_UP
            )
            # balance is BASE currency; validate the BASE amount against it.
            if amount_base <= 0 or amount_base > balance:
                flash(
                    "المبلغ غير صحيح. تأكد من إدخال مبلغ ضمن الرصيد المتبقي.", "danger"
                )
                return redirect(
                    url_for("payments.create_payment", purchase_id=purchase_id)
                )

            parsed_cheque_date = None
            if payment_method_value == "cheque":
                cheque_number = (cheque_number or "").strip()
                bank_name = (bank_name or "").strip()
                if not cheque_number or not cheque_date or not bank_name:
                    raise ValidationError(
                        "رقم الشيك وتاريخ الاستحقاق واسم البنك مطلوبة."
                    )
                parsed_cheque_date = datetime.strptime(cheque_date, "%Y-%m-%d").date()

            payment_number = generate_number("PAY", Payment, "payment_number")
            payment = Payment(
                tenant_id=purchase.tenant_id,
                payment_number=payment_number,
                supplier_id=purchase.supplier_id,
                supplier_name=purchase.supplier_name,
                purchase_id=purchase.id,
                amount=amount_decimal,
                currency=currency,
                exchange_rate=exchange_rate_decimal,
                amount_base=amount_base,
                payment_method=payment_method_value,
                notes=notes,
                user_id=current_user.id,
                direction="outgoing",
                payment_type="supplier_payment",
                payment_confirmed=(payment_method_value != "cheque"),
            )

            if payment_method_value == "bank_transfer":
                payment.bank_name = bank_name_transfer or bank_name
                payment.reference_number = reference_number_transfer or reference_number
            elif payment_method_value == "card":
                payment.reference_number = reference_number_card or reference_number
                if card_last4:
                    payment.notes = (
                        f"{payment.notes or ''} بطاقة آخر 4: {card_last4}".strip()
                    )
            elif payment_method_value == "e_wallet":
                from flask import request as _req

                ref_ew = _req.form.get("reference_number_ewallet")
                payment.reference_number = ref_ew or reference_number
            else:
                payment.reference_number = reference_number
                payment.bank_name = bank_name

            db.session.add(payment)
            db.session.flush()

            if payment_method_value == "cheque":
                cheque = Cheque(
                    tenant_id=purchase.tenant_id,
                    cheque_number=cheque_number,
                    cheque_bank_number=cheque_number,
                    cheque_type="outgoing",
                    supplier_id=purchase.supplier_id,
                    amount=amount_decimal,
                    currency=currency,
                    exchange_rate=exchange_rate_decimal,
                    amount_base=amount_base,
                    issue_date=datetime.utcnow().date(),
                    due_date=parsed_cheque_date,
                    bank_name=bank_name,
                    status="pending",
                    notes=notes,
                )
                db.session.add(cheque)
                db.session.flush()
                payment.cheque_id = cheque.id
                payment.cheque_number = cheque_number
                payment.cheque_date = parsed_cheque_date

            try:
                from services.gl_service import GLService
                from services.account_resolution import AccountResolver, AccountRole

                GLService.ensure_core_accounts()
                # Accounting convention (matches Cheque._create_clearing_journal_entry):
                #   cash            -> Dr 2110 / Cr 1110 (Cash)
                #   bank/card/etc   -> Dr 2110 / Cr 1120 (Bank)
                #   pending cheque  -> Dr 2110 / Cr 2120 (Deferred Cheques Payable);
                #                      the Bank is only credited when the cheque clears.
                if payment_method_value == "cheque":
                    settlement_role = AccountRole.DEFERRED_CHEQUES_PAYABLE
                elif payment_method_value == "cash":
                    settlement_role = AccountRole.CASH
                else:
                    settlement_role = AccountRole.BANK
                settlement_account = AccountResolver.resolve(
                    settlement_role, tenant_id=purchase.tenant_id
                )
                # Cheques settle the same two-decimal book amount held by the register.
                posting_amount = amount_base if pays_by_cheque else payment.amount
                lines = [
                    {
                        "account": AccountResolver.resolve(
                            AccountRole.AP_CONTROL, tenant_id=purchase.tenant_id
                        ),
                        "debit": posting_amount,
                        "description": f"سداد للمورد {payment.supplier_name}",
                    },
                    {
                        "account": settlement_account,
                        "credit": posting_amount,
                        "description": f"سند صرف {payment.payment_number}",
                    },
                ]
                entry = GLService.post_entry(
                    lines,
                    description=f"Payment {payment.payment_number}",
                    reference_type="Payment",
                    reference_id=payment.id,
                    idempotency_key=f"Payment:{payment.id}",
                    currency=_base_curr_pay if pays_by_cheque else payment.currency,
                    exchange_rate=1 if pays_by_cheque else payment.exchange_rate,
                    created_by=current_user.id,
                    tenant_id=purchase.tenant_id,
                )
                if payment_method_value == "cheque":
                    cheque.gl_journal_entry_id = entry.id
            except HTTPException:
                db.session.rollback()
                raise
            except Exception:
                # Never record a payment without a balanced GL entry.
                db.session.rollback()
                current_app.logger.exception("GL posting failed for purchase payment")
                flash(
                    "تعذر تسجيل الدفع لعدم اكتمال القيد المحاسبي. لم يُحفظ أي تغيير.",
                    "danger",
                )
                return redirect(
                    url_for("payments.create_payment", purchase_id=purchase_id)
                )

            create_audit_log("create", "payments", payment.id, commit=False)
            db.session.commit()

            flash("تم إنشاء سند الصرف بنجاح", "success")
            return redirect(url_for("purchases.view", id=purchase_id))

        except ValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        except (InvalidOperation, ValueError):
            db.session.rollback()
            flash("تحقق من المبلغ وسعر الصرف وتاريخ الاستحقاق.", "danger")
        except HTTPException:
            db.session.rollback()
            raise
        except Exception:
            db.session.rollback()
            current_app.logger.exception("handler failed")
            flash("حدث خطأ: حدث خطأ غير متوقع", "danger")

    return render_template(
        "payments/create_receipt.html",
        purchase=purchase,
        supplier=supplier,
        suggested_amount=suggested_amount,
        is_payment=True,
    )  # علامة لتمييز سند الصرف


@payments_bp.route("/api/customer-balance/<int:customer_id>")
@login_required
@permission_required("manage_payments")
def api_customer_balance(customer_id):
    customer = get_owned_or_404(Customer, customer_id, code=404)

    balance_aed = PaymentService.get_customer_balance_aed(customer)
    unpaid_sales = PaymentService.get_unpaid_sales(customer)

    return {
        "balance_aed": float(balance_aed),
        "unpaid_sales": [
            {
                "id": sale.id,
                "sale_number": sale.sale_number,
                "sale_date": sale.sale_date.isoformat(),
                "total_amount": float(sale.total_amount),
                "balance_due": float(sale.balance_due),
                "currency": sale.currency,
            }
            for sale in unpaid_sales
        ],
    }
