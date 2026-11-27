from functools import wraps

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    current_app,
    abort,
)
from flask_login import login_required, current_user
from extensions import db, limiter
from models import Customer, Sale, SaleLine, Receipt
from utils.decorators import permission_required, get_owned_or_404

from utils.helpers import create_audit_log
from services.payment_service import PaymentService
from decimal import Decimal
from datetime import datetime

customers_bp = Blueprint("customers", __name__, url_prefix="/customers")


def _parse_opening_balance(source):
    """F4: قراءة الرصيد الافتتاحي من النموذج (مبلغ + عملة + سعر صرف + تاريخ).

    حقول النموذج (نفس أسماء أعمدة النموذج models/customer.py):
      ``opening_balance``          — المبلغ بالعملة المدخلة
      ``opening_balance_currency`` — رمز العملة (ثلاثة أحرف)
      ``opening_balance_rate``     — سعر التحويل إلى عملة الأساس
      ``opening_balance_date``     — تاريخ الرصيد (YYYY-MM-DD)

    وتُقبل أيضاً ``initial_balance`` كبديل للمبلغ (الحقل الموجود في
    نموذج المورد الحالي) طلباً للتوافق مع القوالب قبل تعديلها.

    تُرجع قاموساً بالمبلغ/العملة/السعر/التاريخ، أو ``None`` إذا لم يُدخل
    شيء. ترفع ``ValueError`` برسالة عربية عند أي قيمة غير صالحة.
    """
    from datetime import datetime as _datetime
    from decimal import InvalidOperation

    from services.currency_service import CurrencyService

    raw_amount = (
        source.get("opening_balance") or source.get("initial_balance") or ""
    ).strip()
    raw_currency = (source.get("opening_balance_currency") or "").strip().upper()
    raw_rate = (source.get("opening_balance_rate") or "").strip()
    raw_date = (source.get("opening_balance_date") or "").strip()

    if not raw_amount and not raw_currency and not raw_rate and not raw_date:
        return None

    amount = Decimal("0")
    if raw_amount:
        try:
            amount = Decimal(raw_amount)
        except (InvalidOperation, ValueError):
            raise ValueError("الرصيد الافتتاحي يجب أن يكون رقماً صحيحاً.")

    if raw_currency:
        if len(raw_currency) != 3 or not raw_currency.isalpha():
            raise ValueError(
                "عملة الرصيد الافتتاحي يجب أن تكون رمزاً من ثلاثة أحرف (مثل AED)."
            )
        currency = raw_currency
    else:
        try:
            currency = CurrencyService.get_base_currency()
        except Exception:
            currency = "ILS"

    rate = Decimal("1")
    if raw_rate:
        try:
            rate = Decimal(raw_rate)
        except (InvalidOperation, ValueError):
            raise ValueError("سعر صرف الرصيد الافتتاحي يجب أن يكون رقماً صحيحاً.")
        if rate <= 0:
            raise ValueError("سعر صرف الرصيد الافتتاحي يجب أن يكون أكبر من صفر.")

    opening_date = None
    if raw_date:
        try:
            opening_date = _datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("تاريخ الرصيد الافتتاحي يجب أن يكون بالصيغة YYYY-MM-DD.")

    return {
        "amount": amount,
        "currency": currency,
        "rate": rate,
        "date": opening_date,
    }


def sales_or_customers_required(f):
    """Dual-check guard: customer lookups are shared by the sales form and the
    customers screens, so either manage_sales OR manage_customers grants access.
    Mirrors utils.decorators.permission_required semantics (302 anon / 403 denied).
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("الرجاء تسجيل الدخول أولاً", "warning")
            return redirect(url_for("auth.login"))
        if not (
            current_user.has_permission("manage_sales")
            or current_user.has_permission("manage_customers")
        ):
            abort(403)
        return f(*args, **kwargs)

    return decorated_function


@customers_bp.route("/")
@login_required
@permission_required("manage_customers")
def index():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search = request.args.get("search", "", type=str)
    customer_type = request.args.get("type", "", type=str)

    query = Customer.query

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            db.or_(
                Customer.name.ilike(search_filter),
                Customer.phone.ilike(search_filter),
                Customer.email.ilike(search_filter),
            )
        )

    if customer_type:
        query = query.filter_by(customer_type=customer_type)

    query = query.filter_by(is_active=True)

    pagination = query.order_by(Customer.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template(
        "customers/index.html", customers=pagination.items, pagination=pagination
    )


@customers_bp.route("/create", methods=["GET", "POST"])
@login_required
@permission_required("manage_customers")
@limiter.limit("10 per minute", methods=["POST"])
def create():
    from forms.customer import CustomerForm

    form = CustomerForm()
    try:
        from services.lookup_service import get_lookup

        form.customer_type.choices = [
            (c, m.get("ar", c)) for c, m in get_lookup("customer_types")
        ]
        form.preferred_currency.choices = [
            (c, m.get("ar", c)) for c, m in get_lookup("currencies")
        ]
        form.is_active.choices = [
            (c, m.get("ar", c)) for c, m in get_lookup("active_flags")
        ]
    except Exception:
        pass

    if form.validate_on_submit():
        try:
            from utils.trn import trn_verdict, current_tenant_country_code

            _ok, _msg = trn_verdict(form.tax_number.data, current_tenant_country_code())
            if not _ok and _msg:
                flash(f"⚠️ {_msg}", "warning")

            opening = _parse_opening_balance(request.form)

            payment_terms_days = int(request.form.get("payment_terms_days", 0) or 0)

            customer = Customer(
                name=form.name.data,
                name_ar=form.name_ar.data,
                customer_type=form.customer_type.data,
                phone=form.phone.data,
                email=form.email.data,
                address=form.address.data,
                tax_number=form.tax_number.data,
                preferred_currency=form.preferred_currency.data,
                payment_terms_days=payment_terms_days,
                notes=form.notes.data,
            )

            if opening:
                customer.opening_balance = opening["amount"]
                customer.opening_balance_currency = opening["currency"]
                customer.opening_balance_rate = opening["rate"]
                customer.opening_balance_date = opening["date"]

            db.session.add(customer)
            db.session.commit()

            from models.customer import recompute_customer_balance

            recompute_customer_balance(customer.id)
            db.session.commit()

            create_audit_log("create", "customers", customer.id)

            flash("✅ تم إضافة الزبون بنجاح!", "success")
            return redirect(url_for("customers.index"))

        except ValueError as e:
            db.session.rollback()
            flash(f"❌ {e}", "danger")
        except Exception as e:
            db.session.rollback()
            from utils.error_messages import ErrorMessages

            flash(ErrorMessages.database_error(str(e)), "danger")

    return render_template("customers/create.html", form=form)


@customers_bp.route("/<int:id>")
@login_required
@permission_required("manage_customers")
def view(id):
    customer = get_owned_or_404(Customer, id)

    sales = (
        Sale.query.filter_by(customer_id=id)
        .order_by(Sale.sale_date.desc())
        .limit(20)
        .all()
    )

    balance = PaymentService.get_customer_balance_aed(customer)

    unpaid_sales = PaymentService.get_unpaid_sales(customer)

    return render_template(
        "customers/view.html",
        customer=customer,
        sales=sales,
        balance=balance,
        unpaid_sales=unpaid_sales,
    )


@customers_bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_customers")
def edit(id):
    customer = get_owned_or_404(Customer, id)

    if request.method == "POST":
        try:
            name = (request.form.get("name") or "").strip()
            customer_type = (request.form.get("customer_type") or "").strip()
            preferred_currency = (request.form.get("preferred_currency") or "").strip()
            payment_terms_days = int(request.form.get("payment_terms_days", 0) or 0)

            try:
                from services.lookup_service import get_lookup

                _allowed_types = {c for c, _m in get_lookup("customer_types")}
                _allowed_currencies = {c for c, _m in get_lookup("currencies")}
            except Exception:
                from utils.constants import CUSTOMER_TYPES, CURRENCIES

                _allowed_types = {c for c, _m in CUSTOMER_TYPES}
                _allowed_currencies = {c for c, _m in CURRENCIES}

            if not name:
                flash(
                    "❌ اسم الزبون مطلوب.\n💡 أدخل اسم الزبون وحاول مرة أخرى.", "danger"
                )
                return render_template("customers/edit.html", customer=customer)
            if customer_type not in _allowed_types:
                flash(
                    "❌ نوع الزبون غير صالح.\n💡 اختر النوع من القائمة وحاول مرة أخرى.",
                    "danger",
                )
                return render_template("customers/edit.html", customer=customer)
            if preferred_currency and preferred_currency not in _allowed_currencies:
                flash(
                    "❌ العملة المفضلة غير صالحة.\n💡 اختر العملة من القائمة وحاول مرة أخرى.",
                    "danger",
                )
                return render_template("customers/edit.html", customer=customer)

            from utils.trn import trn_verdict, current_tenant_country_code

            _ok, _msg = trn_verdict(
                request.form.get("tax_number"), current_tenant_country_code()
            )
            if not _ok and _msg:
                flash(f"⚠️ {_msg}", "warning")

            customer.name = name
            # Preserve optional fields when the form does not submit them,
            # otherwise a plain edit silently erases the Arabic name/currency.
            if request.form.get("name_ar") is not None:
                customer.name_ar = request.form.get("name_ar")
            customer.customer_type = customer_type
            customer.phone = request.form.get("phone")
            customer.email = request.form.get("email")
            customer.address = request.form.get("address")
            customer.tax_number = request.form.get("tax_number")
            # The edit form submits default_currency; accept either name and
            # preserve the current value if neither is present.
            _cur = (
                request.form.get("preferred_currency")
                or request.form.get("default_currency")
                or ""
            ).strip()
            if _cur:
                customer.preferred_currency = _cur
            customer.payment_terms_days = payment_terms_days
            customer.notes = request.form.get("notes")

            opening = _parse_opening_balance(request.form)
            if opening:
                customer.opening_balance = opening["amount"]
                customer.opening_balance_currency = opening["currency"]
                customer.opening_balance_rate = opening["rate"]
                customer.opening_balance_date = opening["date"]

            db.session.commit()

            from models.customer import recompute_customer_balance

            recompute_customer_balance(customer.id)
            db.session.commit()

            create_audit_log("update", "customers", customer.id)

            flash("✅ تم تحديث بيانات الزبون بنجاح!", "success")
            return redirect(url_for("customers.view", id=customer.id))

        except ValueError as e:
            db.session.rollback()
            flash(f"❌ {e}", "danger")
        except Exception as e:
            db.session.rollback()
            from utils.error_messages import ErrorMessages

            flash(ErrorMessages.database_error(str(e)), "danger")

    return render_template("customers/edit.html", customer=customer)


@customers_bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_customers")
def delete(id):
    customer = get_owned_or_404(Customer, id)

    try:
        sales_count = Sale.query.filter_by(customer_id=id).count()
        from models import Payment, Receipt

        payments_count = Payment.query.filter_by(customer_id=id).count()
        receipts_count = Receipt.query.filter_by(customer_id=id).count()

        if sales_count > 0 or payments_count > 0 or receipts_count > 0:
            customer.is_active = False
            db.session.commit()
            flash(
                f'⚠️ تم إلغاء تفعيل العميل "{customer.name}" بدلاً من حذفه لوجود ({sales_count} فاتورة، {payments_count} دفعة، {receipts_count} سند قبض) مرتبطة به.',
                "warning",
            )  # noqa: E501
        else:
            db.session.delete(customer)
            db.session.commit()
            flash(f'✅ تم حذف العميل "{customer.name}" نهائياً!', "success")

        create_audit_log("delete", "customers", id)

    except Exception as e:
        db.session.rollback()
        try:
            customer = get_owned_or_404(Customer, id)
            if customer:
                customer.is_active = False
                db.session.add(customer)
                db.session.commit()
                flash(
                    f'⚠️ تعذر الحذف النهائي للعميل "{customer.name}" بسبب ارتباطات في قاعدة البيانات. تم إلغاء تفعيله بدلاً من ذلك.',
                    "warning",
                )
        except Exception:
            current_app.logger.exception("handler failed")
            flash("❌ حدث خطأ أثناء حذف العميل: حدث خطأ غير متوقع", "danger")
            current_app.logger.error(f"Error deleting customer {id}: {e}")

    return redirect(url_for("customers.index"))


@customers_bp.route("/<int:id>/statement")
@login_required
@permission_required("manage_customers", "manage_ledger")
def statement(id):
    return _customer_statement(id)


def _customer_statement(id, *, export=False):
    customer = get_owned_or_404(Customer, id)

    date_from = request.args.get("date_from", type=str)
    date_to = request.args.get("date_to", type=str)
    transaction_type = request.args.get("transaction_type", "all")

    from sqlalchemy import func
    from models import Payment, ProductReturn
    from models.customer import (
        derive_customer_balance,
        maintenance_receivable_movements,
    )
    from models.cheque import Cheque
    from models.write_off import WriteOff

    sales_query = Sale.query.filter_by(
        customer_id=id, status="confirmed", is_active=True
    )
    payments_query = Payment.query.filter_by(customer_id=id)
    returns_query = ProductReturn.query.filter_by(customer_id=id, status="approved")
    cheques_query = Cheque.query.filter(
        Cheque.customer_id == id,
    )
    receipts_query = Receipt.query.filter(
        Receipt.customer_id == id,
        Receipt.sale_id.is_(None),
        Receipt.purchase_id.is_(None),
    )
    writeoffs_query = WriteOff.query.filter(
        WriteOff.customer_id == id,
        WriteOff.status == "posted",
    )

    # Period filtering is applied to assembled transactions below so that
    # balances brought forward can be derived from the full history.
    sales = sales_query.order_by(Sale.sale_date).all()
    payments = payments_query.order_by(Payment.payment_date).all()
    returns = returns_query.order_by(ProductReturn.return_date).all()
    cheques = cheques_query.all()
    receipts = receipts_query.order_by(Receipt.receipt_date).all()
    writeoffs = writeoffs_query.all()

    sales_ids = [s.id for s in sales]
    from sqlalchemy.orm import joinedload

    sales_with_relations = (
        Sale.query.options(joinedload(Sale.lines).joinedload(SaleLine.product))
        .filter(Sale.id.in_(sales_ids or [0]))
        .all()
    )
    sales_dict = {s.id: s for s in sales_with_relations}

    transactions = []
    opening = customer.get_opening_balance_base()
    opening_date = customer.opening_balance_date
    opening_day = opening_date.isoformat() if opening_date else ""
    if opening:
        transactions.append(
            {
                "date": opening_date,
                "type": "opening_balance",
                "reference": "-",
                "description": "الرصيد الافتتاحي",
                "currency": customer.opening_balance_currency,
                "debit": float(max(opening, 0)),
                "credit": float(max(-opening, 0)),
            }
        )

    for sale in sales:
        loaded_sale = sales_dict.get(sale.id, sale)
        sale_lines_data = []
        for idx, line in enumerate(loaded_sale.lines, start=1):
            quantity = Decimal(str(line.quantity or 0))
            unit_price = Decimal(str(line.unit_price or 0))
            discount_percent = Decimal(str(line.discount_percent or 0))
            gross_amount = quantity * unit_price
            discount_value = (
                (gross_amount * discount_percent / Decimal("100"))
                if discount_percent
                else Decimal("0")
            )
            sale_lines_data.append(
                {
                    "index": idx,
                    "product_name": line.product.get_display_name("ar")
                    if line.product
                    else "بند غير معرف",
                    "product_sku": line.product.sku
                    if line.product and line.product.sku
                    else None,
                    "unit": line.product.unit
                    if line.product and hasattr(line.product, "unit")
                    else None,
                    "quantity": float(quantity),
                    "unit_price": float(unit_price),
                    "discount_percent": float(discount_percent),
                    "discount_value": float(discount_value),
                    "gross_amount": float(gross_amount),
                    "line_total": float(line.line_total or 0),
                    "notes": line.notes or "",
                }
            )

        sale_payments = sale.payments.order_by(Payment.payment_date.asc()).all()
        sale_payments_data = []
        last_payment_date = None

        for payment in sale_payments:
            if last_payment_date is None or payment.payment_date > last_payment_date:
                last_payment_date = payment.payment_date

            cheque = payment.cheque if hasattr(payment, "cheque") else None
            sale_payments_data.append(
                {
                    "id": payment.id,
                    "payment_number": payment.payment_number,
                    "payment_date": payment.payment_date,
                    "amount_base": float(payment.amount_base or 0),
                    "amount_original": float(payment.amount or 0),
                    "currency": payment.currency or "AED",
                    "exchange_rate": float(payment.exchange_rate or 1),
                    "reference_number": payment.reference_number or "-",
                    "payment_method": payment.payment_method,
                    "payment_method_display": payment.get_method_display("ar")
                    if hasattr(payment, "get_method_display")
                    else payment.payment_method,
                    "status_ar": payment.status_ar
                    if hasattr(payment, "status_ar")
                    else ("مؤكدة ✅" if payment.payment_confirmed else "معلقة ⏳"),
                    "payment_confirmed": payment.payment_confirmed,
                    "user": payment.user.get_display_name("ar")
                    if payment.user and hasattr(payment.user, "get_display_name")
                    else (payment.user.full_name if payment.user else None),  # noqa: E501
                    "notes": payment.notes or "",
                    "direction": payment.direction,
                    "cheque_number": cheque.cheque_number
                    if cheque
                    else payment.cheque_number,
                    "cheque_bank": cheque.bank_name if cheque else payment.bank_name,
                    "cheque_due_date": cheque.due_date if cheque else None,
                }
            )

        sale_data = {
            "id": sale.id,
            "number": sale.sale_number,
            "date": sale.sale_date,
            "status": sale.payment_status,
            "subtotal": float(sale.subtotal or 0),
            "discount_amount": float(sale.discount_amount or 0),
            "shipping_cost": float(sale.shipping_cost or 0),
            "tax_rate": float(sale.tax_rate or 0),
            "tax_amount": float(sale.tax_amount or 0),
            "total_amount": float(sale.total_amount or sale.amount_base or 0),
            "amount_base": float(sale.amount_base or 0),
            "paid_amount": float(sale.paid_amount_base or 0),
            "balance_due": float(sale.balance_due or 0),
            "currency": sale.currency or "AED",
            "exchange_rate": float(sale.exchange_rate or 1),
            "seller": sale.seller.get_display_name("ar")
            if sale.seller and hasattr(sale.seller, "get_display_name")
            else (sale.seller.full_name if sale.seller else None),  # noqa: E501
            "notes": sale.notes or "",
            "lines": sale_lines_data,
            "payments": sale_payments_data,
            "last_payment_date": last_payment_date,
        }

        transactions.append(
            {
                "date": sale.sale_date,
                "type": "sale",
                "reference": sale.sale_number,
                "debit": float(sale.amount_base or 0),
                "credit": float(sale.paid_amount_base or 0),
                "balance": 0,
                "description": "فاتورة بيع",
                "currency": sale.currency or "AED",
                "exchange_rate": float(sale.exchange_rate or 1),
                "paid_amount": float(sale.paid_amount_base or 0),
                "balance_due": float(sale.balance_due or 0),
                "status": sale.payment_status,
                "sale": sale_data,
            }
        )

    # Product returns (credit to customer)
    for prod_return in returns:
        transactions.append(
            {
                "date": prod_return.return_date,
                "type": "return",
                "reference": prod_return.return_number,
                "debit": 0,
                "credit": float(
                    (prod_return.refund_amount or 0) * (prod_return.exchange_rate or 1)
                ),
                "balance": 0,
                "description": "مرتجع بضاعة",
                "currency": prod_return.currency or "AED",
                "exchange_rate": float(prod_return.exchange_rate or 1),
                "paid_amount": 0,
                "balance_due": 0,
                "status": prod_return.status,
                "return": {
                    "id": prod_return.id,
                    "return_number": prod_return.return_number,
                    "return_date": prod_return.return_date,
                    "total_amount": float(prod_return.total_amount or 0),
                    "amount_base": float(prod_return.amount_base or 0),
                    "currency": prod_return.currency or "AED",
                    "exchange_rate": float(prod_return.exchange_rate or 1),
                    "return_reason": prod_return.return_reason or "",
                    "status": prod_return.status,
                    "notes": prod_return.notes or "",
                },
            }
        )

    for movement in maintenance_receivable_movements(id):
        movement_date = movement["date"]
        day = movement_date.date().isoformat() if movement_date else ""
        transactions.append(
            {
                **movement,
                "debit": float(movement["debit"]),
                "credit": float(movement["credit"]),
                "paid_amount": 0,
                "balance_due": 0,
                "status": "posted",
            }
        )

    # Cheques (all cheques for this customer - standalone and linked)
    for cheque in cheques:
        amount = float(cheque.amount_base or 0)
        status = cheque.status
        is_active = cheque.is_active if hasattr(cheque, "is_active") else True
        is_linked = bool(
            cheque.receipt_id
            or cheque.payment_id
            or cheque.sale_id
            or cheque.receipt_record
            or cheque.payment_record
        )
        linked_ref = ""
        if cheque.receipt_id:
            linked_ref = f" (مرتبط بإشعار #{cheque.receipt_id})"
        elif cheque.payment_id:
            linked_ref = f" (مرتبط بدفع #{cheque.payment_id})"
        elif cheque.sale_id:
            linked_ref = f" (مرتبط ببيع #{cheque.sale_id})"

        if status in ("bounced", "cancelled"):
            label = "شيك مرتد" if status == "bounced" else "شيك ملغى"
            transactions.append(
                {
                    "date": cheque.issue_date,
                    "type": "cheque",
                    "reference": cheque.cheque_number,
                    "debit": 0,
                    "credit": 0,
                    "balance": 0,
                    "description": label + linked_ref,
                    "currency": cheque.currency or "AED",
                    "exchange_rate": float(cheque.exchange_rate or 1),
                    "paid_amount": 0,
                    "balance_due": 0,
                    "status": status,
                }
            )
        elif not is_active and status in ("pending", "deposited", "under_collection"):
            if is_linked:
                transactions.append(
                    {
                        "date": cheque.issue_date
                        if hasattr(cheque, "issue_date")
                        else None,
                        "type": "cheque",
                        "reference": cheque.cheque_number,
                        "debit": 0,
                        "credit": 0,
                        "balance": 0,
                        "description": f"شيك غير نشط{linked_ref} - التأثير في الدفعة/الإشعار المرتبط",
                        "currency": cheque.currency or "AED",
                        "exchange_rate": float(cheque.exchange_rate or 1),
                        "paid_amount": 0,
                        "balance_due": 0,
                        "status": status,
                    }
                )
            else:
                transactions.append(
                    {
                        "date": cheque.issue_date
                        if hasattr(cheque, "issue_date")
                        else None,
                        "type": "cheque",
                        "reference": cheque.cheque_number,
                        "debit": 0,
                        "credit": amount,
                        "balance": 0,
                        "description": "شيك غير نشط",
                        "currency": cheque.currency or "AED",
                        "exchange_rate": float(cheque.exchange_rate or 1),
                        "paid_amount": 0,
                        "balance_due": 0,
                        "status": status,
                    }
                )
        elif (
            status == "cleared"
            and is_active
            and not is_linked
            and cheque.cheque_type == "incoming"
            and cheque.gl_journal_entry_id
        ):
            transactions.append(
                {
                    "date": cheque.clearance_date or cheque.issue_date,
                    "type": "cheque",
                    "reference": cheque.cheque_number,
                    "debit": 0,
                    "credit": amount,
                    "description": "تحصيل شيك وارد غير مرتبط بفاتورة",
                    "currency": cheque.currency,
                    "exchange_rate": float(cheque.exchange_rate or 1),
                    "paid_amount": 0,
                    "balance_due": 0,
                    "status": status,
                }
            )
        else:
            # Show all other cheques (pending, deposited, under_collection, cleared) as informational
            transactions.append(
                {
                    "date": cheque.issue_date
                    if hasattr(cheque, "issue_date")
                    else None,
                    "type": "cheque",
                    "reference": cheque.cheque_number,
                    "debit": 0,
                    "credit": 0,
                    "balance": 0,
                    "description": f"شيك ({status}){linked_ref}",
                    "currency": cheque.currency or "AED",
                    "exchange_rate": float(cheque.exchange_rate or 1),
                    "paid_amount": 0,
                    "balance_due": 0,
                    "status": status,
                }
            )

    # Receipts (standalone, not linked to sale/purchase)
    for receipt in receipts:
        amount = float(receipt.amount_base or 0)
        if receipt.rejection_reason:
            transactions.append(
                {
                    "date": receipt.receipt_date,
                    "type": "receipt",
                    "reference": receipt.receipt_number,
                    "debit": amount,
                    "credit": 0,
                    "balance": 0,
                    "description": "إشعار مرفوض",
                    "currency": receipt.currency or "AED",
                    "exchange_rate": float(receipt.exchange_rate or 1),
                    "paid_amount": 0,
                    "balance_due": 0,
                    "status": "rejected",
                }
            )
        elif receipt.payment_confirmed:
            transactions.append(
                {
                    "date": receipt.receipt_date,
                    "type": "receipt",
                    "reference": receipt.receipt_number,
                    "debit": 0,
                    "credit": amount,
                    "balance": 0,
                    "description": "إشعار مؤكد",
                    "currency": receipt.currency or "AED",
                    "exchange_rate": float(receipt.exchange_rate or 1),
                    "paid_amount": 0,
                    "balance_due": 0,
                    "status": "confirmed",
                }
            )

    # Write-offs (posted)
    for woff in writeoffs:
        amount = float(woff.amount_base or 0)
        transactions.append(
            {
                "date": woff.posted_at or woff.created_at,
                "type": "write_off",
                "reference": f"WO-{woff.id}",
                "debit": 0,
                "credit": amount,
                "balance": 0,
                "description": "إطفاء دين (شطب)",
                "currency": woff.currency or "AED",
                "exchange_rate": 1,
                "paid_amount": 0,
                "balance_due": 0,
                "status": woff.status,
            }
        )

    for payment in payments:
        refund_amount = (
            float(payment.amount_base or 0)
            if payment.payment_confirmed
            and not payment.sale_id
            and payment.direction == "outgoing"
            else 0.0
        )

        cheque = payment.cheque if hasattr(payment, "cheque") else None

        transactions.append(
            {
                "date": payment.payment_date,
                "type": "payment",
                "reference": payment.reference_number
                or payment.payment_number
                or f"دفع #{payment.id}",
                "debit": refund_amount,
                "credit": 0,
                "balance": 0,
                "description": f"دفعة - {payment.get_method_display('ar') if hasattr(payment, 'get_method_display') else payment.payment_method}",
                "currency": payment.currency or "AED",
                "exchange_rate": float(payment.exchange_rate or 1),
                "paid_amount": refund_amount,
                "balance_due": 0,
                "status": payment.status_ar
                if hasattr(payment, "status_ar")
                else ("مؤكدة ✅" if payment.payment_confirmed else "معلقة ⏳"),
                "payment": {
                    "id": payment.id,
                    "payment_number": payment.payment_number,
                    "payment_date": payment.payment_date,
                    "amount_base": float(payment.amount_base or 0),
                    "amount_original": float(payment.amount or 0),
                    "currency": payment.currency or "AED",
                    "exchange_rate": float(payment.exchange_rate or 1),
                    "payment_method": payment.payment_method,
                    "payment_method_display": payment.get_method_display("ar")
                    if hasattr(payment, "get_method_display")
                    else payment.payment_method,
                    "reference_number": payment.reference_number or "-",
                    "direction": payment.direction,
                    "payment_confirmed": payment.payment_confirmed,
                    "status_ar": payment.status_ar
                    if hasattr(payment, "status_ar")
                    else ("مؤكدة ✅" if payment.payment_confirmed else "معلقة ⏳"),
                    "user": payment.user.get_display_name("ar")
                    if payment.user and hasattr(payment.user, "get_display_name")
                    else (payment.user.full_name if payment.user else None),  # noqa: E501
                    "notes": payment.notes or "",
                    "cheque_number": cheque.cheque_number
                    if cheque
                    else payment.cheque_number,
                    "cheque_bank": cheque.bank_name if cheque else payment.bank_name,
                    "cheque_due_date": cheque.due_date
                    if cheque
                    else payment.cheque_date,
                    "cheque_clearance_date": cheque.clearance_date if cheque else None,
                },
            }
        )

    def _transaction_date_key(trans):
        trans_date = trans["date"]
        if trans_date is None:
            return datetime.min
        if isinstance(trans_date, datetime):
            return trans_date.replace(tzinfo=None)
        return datetime.combine(trans_date, datetime.min.time())

    transactions.sort(key=_transaction_date_key)

    if transaction_type in {
        "sale",
        "payment",
        "return",
        "maintenance_invoice",
        "maintenance_receipt",
        "maintenance_credit_note",
        "cheque",
        "receipt",
        "write_off",
    }:
        transactions = [
            trans for trans in transactions if trans["type"] == transaction_type
        ]

    # ---- chronological order + balance carried into the selected period ----
    def _row_day(row):
        value = row.get("date")
        if hasattr(value, "date"):
            return value.date().isoformat()
        return value.isoformat() if value else ""

    transactions = sorted(
        transactions, key=lambda row: (_row_day(row), str(row.get("reference", "")))
    )
    opening_balance = Decimal("0")
    if date_from:
        for row in transactions:
            if _row_day(row) < date_from:
                opening_balance += Decimal(str(row["debit"])) - Decimal(str(row["credit"]))
        transactions = [
            row for row in transactions
            if _row_day(row) >= date_from and (not date_to or _row_day(row) <= date_to)
        ]
    elif date_to:
        transactions = [row for row in transactions if _row_day(row) <= date_to]

    running_balance = opening_balance
    for trans in transactions:
        running_balance += Decimal(str(trans["debit"])) - Decimal(str(trans["credit"]))
        trans["balance"] = running_balance

    if export:
        return _export_customer_statement(customer, transactions)

    system_balance = derive_customer_balance(id)

    # Partner entitlements: all GL lines booked to the partner current account
    # with this customer as the party. Credits = profit shares owed to
    # them, debits = draws/losses. This covers BOTH product-level shares (posted
    # per sale) and company-level distributions in one authoritative place.
    from models import GLAccount, GLJournalEntry, GLJournalLine, Product, ProductPartner
    from services.account_resolution import AccountResolver, AccountRole

    partner_gl = (
        db.session.query(
            GLJournalEntry.entry_number,
            GLJournalEntry.description,
            GLJournalEntry.entry_date,
            GLJournalLine.debit,
            GLJournalLine.credit,
        )
        .join(GLJournalLine, GLJournalLine.entry_id == GLJournalEntry.id)
        .join(GLAccount, GLAccount.id == GLJournalLine.account_id)
        .filter(
            GLJournalLine.party_id == id,
            GLAccount.code
            == AccountResolver.resolve(
                AccountRole.PARTNERS_CURRENT, tenant_id=customer.tenant_id
            ),
            GLJournalEntry.tenant_id == customer.tenant_id,
            GLJournalLine.tenant_id == customer.tenant_id,
            GLJournalEntry.is_posted.is_(True),
        )
        .order_by(GLJournalEntry.entry_date, GLJournalEntry.id)
        .all()
    )
    partner_movements = []
    partner_entitlement = Decimal("0")
    for num, desc, edate, debit, credit in partner_gl:
        amount = (credit or Decimal("0")) - (debit or Decimal("0"))
        partner_entitlement += amount
        partner_movements.append(
            {
                "entry_number": num,
                "description": desc or "-",
                "date": edate,
                "amount": amount,
                "kind": "حصة ربح" if amount > 0 else "مسحوبات/تسوية",
            }
        )

    partner_links = (
        db.session.query(Product.name, ProductPartner.percentage)
        .join(Product, Product.id == ProductPartner.product_id)
        .filter(ProductPartner.partner_customer_id == id)
        .all()
    )

    return render_template(
        "customers/statement.html",
        partner_movements=partner_movements,
        partner_entitlement=partner_entitlement,
        partner_links=partner_links,
        customer=customer,
        transactions=transactions,
        final_balance=running_balance,
        opening_balance=opening_balance,
        system_balance=system_balance,
        filters={
            "date_from": date_from or "",
            "date_to": date_to or "",
            "transaction_type": transaction_type,
        },
    )


@customers_bp.route("/api/search")
@login_required
@sales_or_customers_required
def api_search():
    query = request.args.get("q", "")
    _ = request.args.get("page", 1, type=int)
    per_page = 20

    if query and len(query) >= 1:
        customers = (
            Customer.query.filter(
                Customer.is_active.is_(True),
                db.or_(
                    Customer.name.ilike(f"%{query}%"),
                    Customer.phone.ilike(f"%{query}%"),
                    Customer.email.ilike(f"%{query}%"),
                ),
            )
            .order_by(Customer.name)
            .limit(per_page)
            .all()
        )
    else:
        customers = (
            Customer.query.filter_by(is_active=True)
            .order_by(Customer.name)
            .limit(per_page)
            .all()
        )

    results = [
        {
            "id": c.id,
            "name": c.name,
            "phone": c.phone or "",
            "text": f"{c.name} - {c.phone}" if c.phone else c.name,
            "customer_type": c.customer_type,
            "customer_classification": c.customer_classification,
            "balance": float(c.get_balance()),
        }
        for c in customers
    ]

    return jsonify(results)


@customers_bp.route("/<int:id>/balance")
@login_required
@sales_or_customers_required
def customer_balance(id):
    """Get customer balance and unpaid sales - API for payment receipts"""
    customer = get_owned_or_404(Customer, id)

    unpaid_sales = (
        Sale.query.filter(
            Sale.customer_id == id, Sale.balance_due > 0, Sale.is_active.is_(True)
        )
        .order_by(Sale.sale_date.desc())
        .all()
    )

    return jsonify(
        {
            "balance": float(customer.get_balance()),
            "unpaid_sales": [
                {
                    "id": s.id,
                    "sale_number": s.sale_number,
                    "total_amount": float(s.total_amount),
                    "paid_amount": float(s.paid_amount),
                    "balance_due": float(s.balance_due),
                    "payment_status": s.payment_status,
                    "sale_date": s.sale_date.strftime("%Y-%m-%d"),
                }
                for s in unpaid_sales
            ],
        }
    )


@customers_bp.route("/<int:id>/sales")
@login_required
@permission_required("manage_customers")
def customer_sales(id):
    _ = get_owned_or_404(Customer, id)

    sales = (
        Sale.query.filter_by(customer_id=id, status="confirmed")
        .order_by(Sale.sale_date.desc())
        .all()
    )

    sales_data = []
    for sale in sales:
        balance = sale.amount_base - sale.paid_amount_base
        if balance > 0:
            sales_data.append(
                {
                    "id": sale.id,
                    "invoice_number": sale.sale_number or f"#{sale.id}",
                    "sale_date": sale.sale_date.strftime("%Y-%m-%d"),
                    "amount_base": float(sale.amount_base),
                    "paid_amount_base": float(sale.paid_amount_base),
                    "balance": float(balance),
                }
            )

    return jsonify({"sales": sales_data})


@customers_bp.route("/<int:id>/statement/export")
@login_required
@permission_required("manage_customers", "manage_ledger")
def statement_export(id):
    return _customer_statement(id, export=True)


def _export_customer_statement(customer, transactions):
    """Export the same filtered and chronologically ordered rows as the statement."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from flask import send_file

    wb = Workbook()
    ws = wb.active
    ws.title = f"كشف {customer.name}"[:31]

    # Header
    ws.append(["كشف حساب العميل: " + customer.name])
    ws.append(["العميل:", customer.name, "ID:", customer.id])
    ws.append(["التاريخ:", datetime.now().strftime("%Y-%m-%d")])
    ws.append([])
    ws.append(["التاريخ", "النوع", "المرجع", "الوصف", "مدين", "دائن", "الرصيد"])

    for row in transactions:
        ws.append(
            [
                row["date"].strftime("%Y-%m-%d") if row["date"] else "-",
                row["type"],
                row["reference"],
                row["description"],
                row["debit"],
                row["credit"],
                row["balance"],
            ]
        )

    # Style
    for cell in ws[5]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill(
            start_color="D9E2F3", end_color="D9E2F3", fill_type="solid"
        )

    # Column widths
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 25
    ws.column_dimensions["E"].width = 12
    ws.column_dimensions["F"].width = 12
    ws.column_dimensions["G"].width = 12

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    from datetime import datetime as _dt

    filename = f"statement_{customer.name}_{_dt.now().strftime('%Y%m%d')}.xlsx"
    return send_file(
        output,
        download_name=filename,
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
