"""Bank reconciliation management UI."""
from datetime import date, timedelta
from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from utils.decorators import permission_required, get_owned_or_404
from utils.helpers import create_audit_log
from models import BankReconciliation, GLAccount
from extensions import db

bank_reconciliation_bp = Blueprint(
    "bank_reconciliation", __name__, url_prefix="/bank-reconciliation"
)


@bank_reconciliation_bp.route("/")
@login_required
@permission_required("view_ledger")
def index():
    rows = (BankReconciliation.query
            .order_by(BankReconciliation.period_end.desc())
            .limit(100).all())
    return render_template("bank_reconciliation/index.html", rows=rows)


@bank_reconciliation_bp.route("/create", methods=["GET", "POST"])
@login_required
@permission_required("manage_ledger")
def create():
    from services.bank_reconciliation_service import BankReconciliationService
    accounts = (GLAccount.query.filter_by(is_active=True, is_header=False)
                .order_by(GLAccount.code).all())
    if request.method == "POST":
        try:
            start = date.fromisoformat(request.form["period_start"])
            end = date.fromisoformat(request.form["period_end"])
            closing = Decimal(str(request.form.get("closing_balance_per_bank", "0") or "0"))
            statement_reference = (
                request.form.get("statement_reference") or ""
            ).strip()
            with db.session.begin_nested():
                rec = BankReconciliationService.create_reconciliation(
                    bank_account_id=int(request.form["bank_account_id"]),
                    period_start=start, period_end=end,
                    closing_balance_per_bank=closing,
                )
                # Statement evidence is optional but recorded on the
                # reconciliation itself rather than hidden in free-text notes.
                rec.statement_reference = statement_reference or None
            db.session.commit()
            create_audit_log("create", "bank_reconciliations", rec.id)
            flash("تم إنشاء التسوية البنكية بنجاح.", "success")
            return redirect(url_for("bank_reconciliation.view", id=rec.id))
        except Exception as exc:
            db.session.rollback()
            flash(f"تعذر إنشاء التسوية: {exc}", "danger")
    return render_template("bank_reconciliation/create.html", accounts=accounts,
                           today=date.today().isoformat(),
                           month_start=(date.today() - timedelta(days=30)).isoformat())


@bank_reconciliation_bp.route("/<int:id>")
@login_required
@permission_required("view_ledger")
def view(id):
    rec = get_owned_or_404(BankReconciliation, id)
    return render_template("bank_reconciliation/view.html", rec=rec)


@bank_reconciliation_bp.route("/<int:id>/approve", methods=["POST"])
@login_required
@permission_required("manage_ledger")
def approve(id):
    rec = get_owned_or_404(BankReconciliation, id)
    try:
        # Lock the row so a concurrent approval cannot slip past the
        # creator/approver separation check.
        db.session.refresh(rec, with_for_update=True)
        if rec.created_by is not None and rec.created_by == current_user.id:
            raise ValueError("لا يمكن لمن أنشأ المطابقة أن يعتمدها")
        if not rec.is_balanced:
            rec.calculate_reconciliation()
        rec.approve(current_user.id)
        db.session.commit()
        create_audit_log("approve", "bank_reconciliations", rec.id)
        flash("تم اعتماد التسوية البنكية.", "success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc), "danger")
    return redirect(url_for("bank_reconciliation.view", id=id))


@bank_reconciliation_bp.route("/<int:id>/charge", methods=["POST"])
@login_required
@permission_required("manage_ledger")
def add_charge(id):
    from services.bank_reconciliation_service import BankReconciliationService
    rec = get_owned_or_404(BankReconciliation, id)
    try:
        BankReconciliationService.add_bank_charge(
            id, Decimal(str(request.form.get("amount") or 0)),
            request.form.get("description") or "رسوم بنكية",
        )
        db.session.commit()
        flash("أُضيفت الرسوم البنكية.", "success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc), "danger")
    return redirect(url_for("bank_reconciliation.view", id=id))


@bank_reconciliation_bp.route("/<int:id>/interest", methods=["POST"])
@login_required
@permission_required("manage_ledger")
def add_interest(id):
    from services.bank_reconciliation_service import BankReconciliationService
    get_owned_or_404(BankReconciliation, id)
    try:
        BankReconciliationService.add_bank_interest(
            id, Decimal(str(request.form.get("amount") or 0)),
            request.form.get("description") or "فوائد بنكية",
        )
        db.session.commit()
        flash("أُضيفت الفوائد البنكية.", "success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc), "danger")
    return redirect(url_for("bank_reconciliation.view", id=id))


@bank_reconciliation_bp.route("/<int:id>/complete", methods=["POST"])
@login_required
@permission_required("manage_ledger")
def complete(id):
    from services.bank_reconciliation_service import BankReconciliationService
    rec = get_owned_or_404(BankReconciliation, id)
    try:
        BankReconciliationService.complete_reconciliation(id)
        db.session.commit()
        create_audit_log("approve", "bank_reconciliations", rec.id)
        flash("اكتملت التسوية البنكية واعتمدت.", "success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc), "danger")
    return redirect(url_for("bank_reconciliation.view", id=id))
