"""
Approval Workflow Routes — مسارات سير عمل الموافقة
List, view, approve, reject approval requests. Manage workflow definitions.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from extensions import db
from models import ApprovalWorkflow, ApprovalRequest, ApprovalLevel
from services.approval_service import ApprovalService
from utils.decorators import permission_required

approvals_bp = Blueprint('approvals', __name__, url_prefix='/approvals')


# ── List pending requests ───────────────────────────────────────────────

@approvals_bp.route('/')
@login_required
def index():
    status = request.args.get('status', '', type=str)
    entity_type = request.args.get('entity_type', '', type=str)

    requests = ApprovalService.get_all_requests(
        status=status or None,
        entity_type=entity_type or None,
    )

    # Pending count for the badge
    pending = ApprovalRequest.query.filter_by(status='pending').count()

    return render_template('approvals/index.html',
                           requests=requests, pending_count=pending,
                           selected_status=status, selected_entity=entity_type)


# ── View a specific request ─────────────────────────────────────────────

@approvals_bp.route('/<int:request_id>')
@login_required
def view(request_id):
    req = db.get_or_404(ApprovalRequest, request_id)
    workflow = req.workflow
    levels = ApprovalLevel.query.filter_by(request_id=request_id).order_by(ApprovalLevel.level).all()
    return render_template('approvals/view.html',
                           req=req, workflow=workflow, levels=levels)


# ── Approve ─────────────────────────────────────────────────────────────

@approvals_bp.route('/<int:request_id>/approve', methods=['POST'])
@login_required
def approve(request_id):
    notes = request.form.get('notes', '')
    success, message = ApprovalService.approve(request_id, current_user.id, notes=notes)
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('approvals.view', request_id=request_id))


# ── Reject ──────────────────────────────────────────────────────────────

@approvals_bp.route('/<int:request_id>/reject', methods=['POST'])
@login_required
def reject(request_id):
    notes = request.form.get('notes', '')
    success, message = ApprovalService.reject(request_id, current_user.id, notes=notes)
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('approvals.view', request_id=request_id))


# ── Cancel ──────────────────────────────────────────────────────────────

@approvals_bp.route('/<int:request_id>/cancel', methods=['POST'])
@login_required
def cancel(request_id):
    success, message = ApprovalService.cancel(request_id, current_user.id)
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('approvals.index'))


# ── Manage Workflows (admin/owner only) ────────────────────────────────

@approvals_bp.route('/workflows')
@login_required
@permission_required('manage_settings')
def manage_workflows():
    workflows = ApprovalWorkflow.query.order_by(ApprovalWorkflow.entity_type).all()
    return render_template('approvals/workflows.html', workflows=workflows)


@approvals_bp.route('/workflows/new', methods=['GET', 'POST'])
@login_required
@permission_required('manage_settings')
def new_workflow():
    if request.method == 'POST':
        wf = ApprovalWorkflow(
            name=request.form.get('name', '').strip(),
            name_ar=request.form.get('name_ar', '').strip() or None,
            description=request.form.get('description', '').strip() or None,
            entity_type=request.form.get('entity_type', 'sale'),
            min_amount=float(request.form.get('min_amount', 0) or 0),
            max_amount=float(request.form['max_amount']) if request.form.get('max_amount') else None,
            levels_required=int(request.form.get('levels_required', 1) or 1),
            is_active='is_active' in request.form,
        )
        db.session.add(wf)
        db.session.commit()
        flash(f'تم إنشاء سير العمل: {wf.name}', 'success')
        return redirect(url_for('approvals.manage_workflows'))

    return render_template('approvals/workflow_form.html', workflow=None)


@approvals_bp.route('/workflows/<int:wf_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_settings')
def edit_workflow(wf_id):
    wf = db.get_or_404(ApprovalWorkflow, wf_id)
    if request.method == 'POST':
        wf.name = request.form.get('name', '').strip()
        wf.name_ar = request.form.get('name_ar', '').strip() or None
        wf.description = request.form.get('description', '').strip() or None
        wf.entity_type = request.form.get('entity_type', 'sale')
        wf.min_amount = float(request.form.get('min_amount', 0) or 0)
        wf.max_amount = float(request.form['max_amount']) if request.form.get('max_amount') else None
        wf.levels_required = int(request.form.get('levels_required', 1) or 1)
        wf.is_active = 'is_active' in request.form
        db.session.commit()
        flash(f'تم تحديث سير العمل: {wf.name}', 'success')
        return redirect(url_for('approvals.manage_workflows'))

    return render_template('approvals/workflow_form.html', workflow=wf)
