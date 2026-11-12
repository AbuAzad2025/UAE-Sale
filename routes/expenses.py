from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app,
    jsonify,
    abort,
)
from flask_login import login_required, current_user
from extensions import db, limiter
from models import Expense, ExpenseCategory, Cheque
from models import InvoiceSettings
from services.currency_service import CurrencyService
from services.gl_service import GLService
from utils.decorators import permission_required, get_owned_or_404
from routes.ledger import reverse_or_purge_gl_entries

from utils.helpers import create_audit_log, generate_number
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime

expenses_bp = Blueprint("expenses", __name__, url_prefix="/expenses")


@expenses_bp.route("/")
@login_required
@permission_required("manage_expenses")
def index():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    category_id = request.args.get("category", type=int)

    query = Expense.query.filter_by(status="confirmed")

    # إخفاء المصروفات المؤرشفة
    from models import ArchivedRecord
    from sqlalchemy import select

    archived_expenses = (
        select(ArchivedRecord.record_id)
        .filter(ArchivedRecord.table_name == "expenses")
        .scalar_subquery()
    )
    query = query.filter(~Expense.id.in_(archived_expenses))

    if category_id:
        query = query.filter_by(category_id=category_id)

    pagination = query.order_by(Expense.expense_date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    categories = ExpenseCategory.query.filter_by(is_active=True).all()

    return render_template(
        "expenses/index.html",
        expenses=pagination.items,
        pagination=pagination,
        categories=categories,
    )


@expenses_bp.route("/create", methods=["GET", "POST"])
@login_required
@permission_required("manage_expenses")
@limiter.limit("10 per minute", methods=["POST"])
def create():  # noqa: C901
    if request.method == "POST":
        try:
            expense_number = generate_number("EXP", Expense, "expense_number")

            try:
                _base_curr_e = CurrencyService.get_base_currency()
            except Exception:
                _base_curr_e = "ILS"
            currency = request.form.get("currency") or _base_curr_e
            user_exchange_rate = request.form.get("exchange_rate", type=float)

            exchange_rate = CurrencyService.get_exchange_rate(
                currency, _base_curr_e, user_rate=user_exchange_rate
            )

            amount = Decimal(str(request.form.get("amount")))

            # رفض المبلغ غير الموجب: بدون هذا التحقق كان المبلغ صفراً أو سالباً
            # يُخزَّن ويُرحَّل، فتنقلب سطور القيد المحاسبي على حساب المصروف.
            if amount <= 0:
                flash("❌ المبلغ يجب أن يكون أكبر من صفر.", "danger")
                return redirect(url_for("expenses.index"))

            tax_treatment = (
                (request.form.get("tax_treatment") or "standard").strip().lower()
            )
            if tax_treatment not in ("standard", "zero", "exempt"):
                tax_treatment = "standard"
            tax_rate = request.form.get("tax_rate", type=float, default=0) or 0
            tax_inclusive = request.form.get("tax_inclusive") in ("on", "1", "true")
            _vals = request.form.getlist("vat_recoverable")
            vat_recoverable = (
                ("on" in _vals or "1" in _vals or "true" in _vals) if _vals else True
            )
            reverse_charge = request.form.get("reverse_charge") in ("on", "1", "true")
            from services.expense_gl import compute_expense_tax

            _net, _tax, _total = compute_expense_tax(
                amount, tax_rate, tax_inclusive, tax_treatment
            )

            cheque_date_str = request.form.get("cheque_date")
            cheque_date_obj = None
            if cheque_date_str:
                try:
                    cheque_date_obj = datetime.strptime(
                        cheque_date_str, "%Y-%m-%d"
                    ).date()
                except ValueError:
                    pass

            # المدفوع فعليًا: صافي للـ RC، إجمالي لغيره
            _payment_amount = _net if reverse_charge else _total
            # تقريب بعملة المعاملة ثم بسعر الصرف
            _payment_amount = _payment_amount.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            _amount_base = (_payment_amount * Decimal(str(exchange_rate))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            expense = Expense(
                expense_number=expense_number,
                category_id=request.form.get("category_id", type=int),
                description=request.form.get("description"),
                description_ar=request.form.get("description_ar"),
                amount=amount,
                currency=currency,
                exchange_rate=exchange_rate,
                amount_base=_amount_base,
                tax_treatment=tax_treatment,
                tax_rate=tax_rate,
                tax_inclusive=tax_inclusive,
                vat_recoverable=vat_recoverable,
                reverse_charge=reverse_charge,
                tax_amount=_tax,
                payment_method=request.form.get("payment_method"),
                reference_number=request.form.get("reference_number"),
                cheque_number=request.form.get("cheque_number"),
                cheque_date=cheque_date_obj,
                bank_name=request.form.get("bank_name"),
                supplier_name=request.form.get("supplier_name"),
                notes=request.form.get("notes"),
                user_id=current_user.id,
            )

            db.session.add(expense)
            db.session.flush()

            # Handle Cheque Creation
            cheque = None
            if expense.payment_method == "cheque":
                cheque_date_str = request.form.get("cheque_date")
                cheque_date_val = (
                    datetime.strptime(cheque_date_str, "%Y-%m-%d").date()
                    if cheque_date_str
                    else datetime.now().date()
                )

                cheque = Cheque(
                    cheque_number=expense.cheque_number
                    or f"CHQ-{expense.expense_number}",
                    cheque_bank_number=expense.cheque_number
                    or f"CHQ-{expense.expense_number}",
                    cheque_type="outgoing",
                    bank_name=expense.bank_name or "Unknown",
                    amount=_payment_amount,
                    currency=expense.currency,
                    exchange_rate=expense.exchange_rate,
                    amount_base=_amount_base,
                    issue_date=datetime.now().date(),
                    due_date=cheque_date_val,
                    status="pending",
                    payee_name=expense.supplier_name or "Expense Payment",
                    expense_id=expense.id,
                    notes=expense.notes,
                    user_id=current_user.id,
                )
                db.session.add(cheque)
                db.session.flush()

            # معاملات كاملة مع مصروف + قيد + شيك: أي فشل يُرجع الكل
            GLService.ensure_core_accounts()
            # الضريبة: إضافية/شاملة، غير قابلة للاسترداد (تُحمّل التكلفة)،
            # وعكس الضريبة (RC: الدافع يسجّل ضريبة ذاتية متوازنة، والمورد بالصافي)
            from services.expense_gl import build_expense_gl_lines

            lines = build_expense_gl_lines(expense)

            GLService.post_entry(
                lines,
                description=f"Expense {expense.expense_number}",
                reference_type="Expense",
                reference_id=expense.id,
                currency=expense.currency,
                exchange_rate=expense.exchange_rate,
            )

            # If Cheque, issue it (GL: Debit 2110, Credit 2120)
            if cheque:
                cheque.issue_cheque()

            db.session.commit()

            create_audit_log("create", "expenses", expense.id)

            flash("✅ تم إضافة المصروف بنجاح!", "success")
            return redirect(url_for("expenses.view", id=expense.id))

        except InvalidOperation:
            db.session.rollback()
            flash(
                "❌ مبلغ المصروف غير صالح.\n💡 أدخل رقماً صحيحاً وحاول مرة أخرى.",
                "danger",
            )
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("handler failed")
            flash(
                f"❌ حدث خطأ: حدث خطأ غير متوقع\n💡 تحقق من البيانات المدخلة وحاول مرة أخرى.",
                "danger",
            )

    categories = ExpenseCategory.query.filter_by(is_active=True).all()
    try:
        _base_curr_e2 = CurrencyService.get_base_currency()
    except Exception:
        _base_curr_e2 = "ILS"
    exchange_rates = CurrencyService.get_all_rates(_base_curr_e2)

    return render_template(
        "expenses/create.html", categories=categories, exchange_rates=exchange_rates
    )


@expenses_bp.route("/<int:id>")
@login_required
@permission_required("manage_expenses")
def view(id):
    expense = get_owned_or_404(Expense, id)
    return render_template("expenses/view.html", expense=expense)


@expenses_bp.route("/<int:id>/print")
@login_required
@permission_required("manage_expenses")
def print_expense(id):
    expense = get_owned_or_404(Expense, id)
    from utils.invoice_header import document_tenant, with_tenant_header

    try:
        settings = with_tenant_header(
            InvoiceSettings.get_active(), document_tenant(expense)
        )
    except ValueError:
        abort(409, description="لا يمكن الطباعة: الشركة المالكة للمستند غير محددة")

    # Template selection (expenses use simple template for now, can add more later)
    template = request.args.get("template", "simple")
    _ALLOWED_TEMPLATES = ("simple",)
    if template not in _ALLOWED_TEMPLATES:
        template = "simple"

    template_labels = {"simple": "مبسط"}
    available_templates = [(k, v) for k, v in template_labels.items()]

    from utils.amount_in_words import amount_in_words
    from services.expense_gl import expense_payment_amount

    _payment = expense_payment_amount(expense)
    amount_words_ar = amount_in_words(_payment, expense.currency, "ar")
    amount_words_en = amount_in_words(_payment, expense.currency, "en")

    return render_template(
        "expenses/print.html",
        expense=expense,
        settings=settings,
        available_templates=available_templates,
        current_template=template,
        document_type="expense",
        document_id=expense.id,
        amount_words_ar=amount_words_ar,
        amount_words_en=amount_words_en,
    )


def _repost_expense_gl(expense):
    """C5: when an edited expense changes amount/category (or payment method),
    reverse the prior GL entry (reference_type='Expense') then post the
    corrected one. Any failure is logged with an ORPHAN EXPENSE WARNING and
    flashed — never silent.

    Returns the entry_number of the reversed entry, or None when nothing was
    reversed.
    """
    from models import GLJournalEntry

    try:
        prior_entry = (
            GLJournalEntry.query.filter_by(
                reference_type="Expense",
                reference_id=expense.id,
                is_reversed=False,
            )
            .order_by(GLJournalEntry.entry_date.desc())
            .first()
        )
    except Exception as e:
        current_app.logger.error(
            f"ORPHAN EXPENSE WARNING: could not look up prior GL entry for "
            f"{expense.expense_number}: {e}"
        )
        flash(
            "⚠️ تعذر التحقق من القيد المحاسبي للمصروف؛ راجع دفتر اليومية يدوياً.",
            "warning",
        )
        return None

    if prior_entry is None:
        current_app.logger.warning(
            f"ORPHAN EXPENSE WARNING: no active GL entry found for edited expense {expense.expense_number}"
        )
        flash(
            "⚠️ لا يوجد قيد محاسبي أصلي لهذا المصروف؛ تم تحديث البيانات دون إعادة ترحيل.",
            "warning",
        )
        return None

    try:
        prior_entry.reverse_entry(f"Reverse Expense {expense.expense_number} (edited)")
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"ORPHAN EXPENSE WARNING: GL reversal failed for {expense.expense_number}: {e}"
        )
        flash(
            "⚠️ فشل عكس القيد المحاسبي القديم؛ لم يتم ترحيل القيمة المصححة.", "warning"
        )
        return None

    try:
        GLService.ensure_core_accounts()
        # نفس منطق القيد في create — بما في ذلك الضريبة
        from services.expense_gl import build_expense_gl_lines

        line_set = build_expense_gl_lines(expense)
        GLService.post_entry(
            line_set,
            description=f"Expense {expense.expense_number} (corrected)",
            reference_type="Expense",
            reference_id=expense.id,
            currency=expense.currency,
            exchange_rate=expense.exchange_rate,
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"ORPHAN EXPENSE WARNING: corrected GL repost failed for {expense.expense_number}: {e}"
        )
        flash(
            "⚠️ تم عكس القيد القديم لكن فشل ترحيل القيمة المصححة؛ يلزم قيد يدوي.",
            "warning",
        )

    return prior_entry.entry_number


@expenses_bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("manage_expenses")
def edit(id):  # noqa: C901
    """تعديل مصروف"""
    expense = db.get_or_404(Expense, id)
    categories = ExpenseCategory.query.filter_by(is_active=True).all()

    if request.method == "POST":
        try:
            # Snapshot GL-relevant values before mutation (C5 trigger set)
            old_amount = Decimal(str(expense.amount or 0))
            old_category_id = expense.category_id
            old_payment_method = expense.payment_method
            old_tax = Decimal(str(getattr(expense, "tax_amount", 0) or 0))
            old_treatment = getattr(expense, "tax_treatment", "standard")
            old_rate = Decimal(str(getattr(expense, "tax_rate", 0) or 0))
            old_recoverable = bool(getattr(expense, "vat_recoverable", True))
            old_rc = bool(getattr(expense, "reverse_charge", False))
            old_inclusive = bool(getattr(expense, "tax_inclusive", False))

            # تحديث البيانات
            new_category_raw = request.form.get("category_id")
            expense.category_id = int(new_category_raw) if new_category_raw else None
            expense.description = request.form.get("description")
            expense.description_ar = request.form.get("description_ar")
            expense.amount = Decimal(str(request.form.get("amount") or 0))
            try:
                _base_curr_edit = CurrencyService.get_base_currency()
            except Exception:
                _base_curr_edit = "ILS"
            expense.currency = request.form.get("currency") or _base_curr_edit
            expense.supplier_name = request.form.get("supplier_name")
            expense.notes = request.form.get("notes")

            # F12: assign the method from the form when present, otherwise the
            # snapshot comparison below can never fire the GL repost.
            new_payment_method = request.form.get("payment_method")
            if new_payment_method:
                expense.payment_method = new_payment_method

            # الضريبة (إن وُجدت في النموذج)
            new_treatment = (
                (
                    request.form.get("tax_treatment")
                    or expense.tax_treatment
                    or "standard"
                )
                .strip()
                .lower()
            )
            if new_treatment in ("standard", "zero", "exempt"):
                expense.tax_treatment = new_treatment
            new_rate_raw = request.form.get("tax_rate")
            if new_rate_raw is not None:
                try:
                    expense.tax_rate = Decimal(str(new_rate_raw))
                except Exception:
                    pass
            new_inclusive = request.form.get("tax_inclusive")
            if new_inclusive is not None:
                expense.tax_inclusive = new_inclusive in ("on", "1", "true")
            new_recoverable = request.form.getlist("vat_recoverable")
            if request.form.get("vat_recoverable_submitted") is not None:
                expense.vat_recoverable = (
                    "on" in new_recoverable
                    or "1" in new_recoverable
                    or "true" in new_recoverable
                )
            new_rc = request.form.get("reverse_charge")
            if new_rc is not None:
                expense.reverse_charge = new_rc in ("on", "1", "true")
            from services.expense_gl import compute_expense_tax, expense_payment_amount

            _n, _t, _tot = compute_expense_tax(
                expense.amount,
                expense.tax_rate,
                bool(expense.tax_inclusive),
                expense.tax_treatment,
            )
            expense.tax_amount = _t

            # حساب المبلغ بعملة الأساس
            exchange_rate = CurrencyService.get_exchange_rate(
                expense.currency, _base_curr_edit
            )
            expense.exchange_rate = exchange_rate
            _payment = expense_payment_amount(expense)
            expense.amount_base = (_payment * exchange_rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            db.session.commit()

            gl_relevant_change = (
                Decimal(str(expense.amount or 0)) != old_amount
                or expense.category_id != old_category_id
                or expense.payment_method != old_payment_method
                or Decimal(str(getattr(expense, "tax_amount", 0) or 0)) != old_tax
                or getattr(expense, "tax_treatment", "standard") != old_treatment
                or Decimal(str(getattr(expense, "tax_rate", 0) or 0)) != old_rate
                or bool(getattr(expense, "vat_recoverable", True)) != old_recoverable
                or bool(getattr(expense, "reverse_charge", False)) != old_rc
                or bool(getattr(expense, "tax_inclusive", False)) != old_inclusive
            )

            gl_reversed_entry_number = None
            if gl_relevant_change:
                gl_reversed_entry_number = _repost_expense_gl(expense)

            audit_changes = {}
            if gl_relevant_change:
                audit_changes["amount"] = float(old_amount)
                audit_changes["new_amount"] = float(expense.amount or 0)
                if gl_reversed_entry_number:
                    audit_changes["gl_reversed"] = gl_reversed_entry_number
            create_audit_log("update", "expenses", id, changes=audit_changes or None)

            # F52: never report a silent success when a GL-relevant edit
            # could not be reposted — the repost helper already flashed the
            # specific warning, this surfaces the error outcome.
            if gl_relevant_change and gl_reversed_entry_number is None:
                flash(
                    "❌ تم حفظ التعديل لكن تعذر إعادة ترحيل القيد المحاسبي؛ راجع دفتر اليومية يدوياً.",
                    "danger",
                )
            else:
                flash("✅ تم تحديث المصروف بنجاح!", "success")
            return redirect(url_for("expenses.view", id=id))

        except InvalidOperation:
            db.session.rollback()
            flash(
                "❌ مبلغ المصروف غير صالح.\n💡 أدخل رقماً صحيحاً وحاول مرة أخرى.",
                "danger",
            )
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("handler failed")
            flash(
                f"❌ حدث خطأ: حدث خطأ غير متوقع\n💡 تحقق من البيانات المدخلة وحاول مرة أخرى.",
                "danger",
            )

    return render_template("expenses/edit.html", expense=expense, categories=categories)


@expenses_bp.route("/<int:id>/delete", methods=["POST"])
@login_required
@permission_required("manage_expenses")
def delete(id):
    """حذف (أرشفة) المصروف"""
    from models import Cheque
    from services.archive_service import ArchiveService

    expense = db.get_or_404(Expense, id)

    # التحقق من الارتباطات
    has_links = False

    # 1. التحقق من الشيكات
    cheque = Cheque.query.filter_by(expense_id=expense.id).first()
    if cheque and cheque.status in ["cleared", "deposited", "bounced", "cancelled"]:
        has_links = True

    try:
        if has_links:
            # أرشفة (Soft Delete)
            # عكس القيد المحاسبي إجباري (F2): فشله يُعلن ولا يُؤرشف
            # المصروف (الصمت كان يخفي أن دفتر الأستاذ لم يُعكس).
            try:
                reverse_or_purge_gl_entries(
                    "Expense",
                    expense.id,
                    description=f"عكس مصروف {expense.expense_number}",
                )
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f"Failed to reverse GL entries for expense {expense.id}: {e}"
                )
                flash(
                    f"❌ تعذّر عكس القيود المحاسبية للمصروف "
                    f'"{expense.expense_number}" — لم تُؤرشف.\n💡 {e}',
                    "danger",
                )
                return redirect(url_for("expenses.view", id=id))

            archive_service = ArchiveService()
            archive_service.archive_record(
                "expenses",
                expense,
                reason="تم أرشفة المصروف لوجود ارتباطات",
                commit=False,
            )

            if cheque:
                archive_service.archive_record(
                    "cheques",
                    cheque,
                    reason="تم أرشفة الشيك لارتباطه بمصروف مؤرشف",
                    commit=False,
                )

            create_audit_log("archive", "expenses", id)
            db.session.commit()
            flash(
                f'✅ تم أرشفة المصروف "{expense.expense_number}" (لوجود ارتباطات)',
                "warning",
            )

        else:
            # حذف نهائي (Hard Delete)
            # 1. القيود المحاسبية للمصروف: المرحَّلة تُعكس (لا تُحذف
            #    أبداً) والمسودات فقط تُحذف.
            try:
                gl_result = reverse_or_purge_gl_entries(
                    "Expense",
                    expense.id,
                    description=f"عكس مصروف {expense.expense_number} (حذف نهائي)",
                )
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f"Failed to reverse GL entries for expense {expense.id}: {e}"
                )
                flash(
                    f"❌ تعذّر عكس القيود المحاسبية للمصروف "
                    f'"{expense.expense_number}" — لم يُحذف.\n💡 {e}',
                    "danger",
                )
                return redirect(url_for("expenses.view", id=id))

            # 2. حذف الشيك إن وُجد وحذف قيوده (المرحَّلة تُعكس)
            if cheque:
                cheque.gl_journal_entry_id = None
                cheque.gl_clearing_entry_id = None
                cheque.gl_bounce_entry_id = None
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
                        cheque.id,
                        description=f"عكس قيد شيك {cheque.cheque_bank_number} (حذف مصروف)",
                    )

                db.session.delete(cheque)

            # 3. حذف المصروف
            db.session.delete(expense)
            create_audit_log("delete", "expenses", id)
            db.session.commit()
            if gl_result["reversed"]:
                flash(
                    f'✅ تم حذف المصروف "{expense.expense_number}" نهائياً — '
                    f"وعُكست قيوده المحاسبية ({gl_result['reversed']} قيد) "
                    f"بدل حذفها حفاظاً على الأثر المحاسبي.",
                    "success",
                )
            else:
                flash(f'✅ تم حذف المصروف "{expense.expense_number}" نهائياً', "success")

        return redirect(url_for("expenses.index"))

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("handler failed")
        flash(
            f"❌ خطأ في الحذف: حدث خطأ غير متوقع\n💡 راجع البيانات المدخلة.", "danger"
        )
        return redirect(url_for("expenses.view", id=id))


@expenses_bp.route("/categories")
@login_required
@permission_required("manage_expenses")
def categories():
    categories = (
        ExpenseCategory.query.filter_by(is_active=True)
        .order_by(ExpenseCategory.name)
        .all()
    )
    return render_template("expenses/categories.html", categories=categories)


@expenses_bp.route("/categories/create", methods=["POST"])
@login_required
@permission_required("manage_expenses")
def create_category():
    try:
        # دعم JSON و Form Data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form

        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("اسم الفئة مطلوب")
        if ExpenseCategory.query.filter_by(name=name).first():
            raise ValueError(f'فئة المصروف "{name}" موجودة مسبقاً')

        category = ExpenseCategory(
            name=name,
            name_ar=data.get("name_ar"),
            gl_account_code=data.get("gl_account_code"),
        )

        db.session.add(category)
        db.session.commit()

        # إرجاع JSON إذا كان الطلب JSON
        if request.is_json:
            return jsonify(
                {
                    "success": True,
                    "message": "تم إضافة الفئة بنجاح",
                    "category": {
                        "id": category.id,
                        "name": category.name,
                        "name_ar": category.name_ar,
                    },
                }
            )

        flash("✅ تم إضافة فئة المصروف بنجاح!", "success")
        return redirect(url_for("expenses.categories"))

    except Exception as e:
        db.session.rollback()

        if request.is_json:
            return jsonify({"success": False, "error": "حدث خطأ غير متوقع"}), 400

        current_app.logger.exception("handler failed")
        flash(
            f"❌ حدث خطأ: حدث خطأ غير متوقع\n💡 تحقق من البيانات المدخلة وحاول مرة أخرى.",
            "danger",
        )
        return redirect(url_for("expenses.categories"))


@expenses_bp.route("/archived")
@login_required
@permission_required("manage_expenses")
def archived():
    """عرض المصروفات المؤرشفة"""
    from models import ArchivedRecord
    from datetime import datetime

    archived_expenses_query = db.session.query(ArchivedRecord).filter(
        ArchivedRecord.table_name == "expenses"
    )

    archived_items = []

    for archived in archived_expenses_query.all():
        data = archived.data
        archived_items.append(
            {
                "id": archived.record_id,
                "expense_number": data.get("expense_number"),
                "expense_date": datetime.fromisoformat(
                    data.get("expense_date").replace("Z", "+00:00")
                )
                if isinstance(data.get("expense_date"), str)
                else data.get("expense_date"),  # noqa: E501
                "category_name": data.get("category_name"),
                "description": data.get("description"),
                "amount": float(data.get("amount", 0)),
                "currency": data.get("currency"),
                "payment_method": data.get("payment_method"),
                "archived_at": archived.archived_at,
            }
        )

    archived_items.sort(key=lambda x: x["archived_at"], reverse=True)

    return render_template("expenses/archived.html", expenses=archived_items)


@expenses_bp.route("/<int:id>/archive", methods=["POST"])
@login_required
@permission_required("manage_expenses")
def archive(id):
    """أرشفة مصروف"""
    from services.archive_service import ArchiveService

    expense = db.get_or_404(Expense, id)

    try:
        archive_service = ArchiveService()
        archive_service.archive_record("expenses", expense, reason="تم أرشفة المصروف")
        create_audit_log("archive", "expenses", expense.id)
    except Exception:
        db.session.rollback()

    return redirect(url_for("expenses.index"))


@expenses_bp.route("/<int:id>/restore", methods=["POST"])
@login_required
@permission_required("manage_expenses")
def restore(id):
    """استعادة مصروف من الأرشيف"""
    from models import ArchivedRecord

    archived = ArchivedRecord.query.filter_by(
        table_name="expenses", record_id=id
    ).first_or_404()

    try:
        db.session.delete(archived)
        db.session.commit()
        create_audit_log("restore", "expenses", id)
    except Exception:
        db.session.rollback()

    return redirect(url_for("expenses.archived"))
