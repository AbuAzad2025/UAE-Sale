"""
Approval Workflow Service — خدمة سير عمل الموافقة
Submit, approve, reject approval requests with audit trail.
"""
from datetime import datetime, timezone
from extensions import db
from models import ApprovalWorkflow, ApprovalRequest, ApprovalLevel
from utils.helpers import generate_number, create_audit_log
import logging

logger = logging.getLogger(__name__)


class ApprovalService:
    """Configurable multi-level approval workflow service."""

    # ── Find matching workflow ───────────────────────────────────────────

    @staticmethod
    def find_workflow(entity_type, amount):
        """
        Find the first active workflow that matches the entity type and amount.
        Returns None if no workflow matches (item doesn't need approval).
        """
        workflows = ApprovalWorkflow.query.filter_by(
            entity_type=entity_type, is_active=True
        ).order_by(ApprovalWorkflow.min_amount.desc()).all()

        for wf in workflows:
            if wf.matches(entity_type, amount):
                return wf
        return None

    # ── Submit a new approval request ────────────────────────────────────

    @staticmethod
    def submit(entity_type, entity_id, amount, requested_by,
               description=None, currency='AED'):
        """
        Submit an approval request if a matching workflow exists.
        Returns the ApprovalRequest or None (if no workflow matches).
        """
        workflow = ApprovalService.find_workflow(entity_type, amount)
        if workflow is None:
            return None  # No approval needed

        request_number = generate_number('APR', ApprovalRequest, 'request_number')
        request = ApprovalRequest(
            request_number=request_number,
            workflow_id=workflow.id,
            entity_type=entity_type,
            entity_id=entity_id,
            amount=amount,
            currency=currency,
            status='pending',
            current_level=1,
            requested_by=requested_by,
            description=description,
        )
        db.session.add(request)
        db.session.flush()

        # Create approval level entries based on workflow levels
        role_map = {1: 'manager', 2: 'owner'}
        for level_num in range(1, workflow.levels_required + 1):
            role = role_map.get(level_num, 'admin')
            approval_level = ApprovalLevel(
                request_id=request.id,
                level=level_num,
                required_role=role,
                status='pending',
            )
            db.session.add(approval_level)

        db.session.flush()

        create_audit_log(
            action=f'approval_submitted:{entity_type}#{entity_id} amount={amount}',
            table_name='approval_requests',
            record_id=request.id,
            changes={'entity_type': entity_type, 'entity_id': entity_id,
                     'amount': float(amount), 'workflow': workflow.name}
        )

        logger.info(f'Approval request {request_number} submitted for {entity_type}#{entity_id}')
        return request

    # ── Approve at current level ─────────────────────────────────────────

    @staticmethod
    def approve(request_id, approver_id, notes=None):
        """
        Approve the current level of an approval request.
        If all levels are approved, the request is fully approved.
        Returns (success, message).
        """
        request = db.session.get(ApprovalRequest, request_id)
        if not request:
            return False, 'طلب الموافقة غير موجود'
        if request.status != 'pending':
            return False, f'الطلب {request.status_ar}'

        # Find the current pending level
        current_level = ApprovalLevel.query.filter_by(
            request_id=request_id, status='pending'
        ).order_by(ApprovalLevel.level).first()

        if not current_level:
            return False, 'لا توجد خطوة معلقة'

        # Update the level
        current_level.approved_by = approver_id
        current_level.status = 'approved'
        current_level.approved_at = datetime.now(timezone.utc)
        if notes:
            current_level.notes = notes

        db.session.flush()

        create_audit_log(
            action=f'approval_level_approved:L{current_level.level} by user#{approver_id}',
            table_name='approval_requests',
            record_id=request_id,
            changes={'level': current_level.level, 'approver_id': approver_id}
        )

        # Check if all levels are now approved
        workflow = request.workflow
        required = workflow.levels_required if workflow else 1
        approved_count = sum(
            1 for a in ApprovalLevel.query.filter_by(request_id=request_id).all()
            if a.status == 'approved'
        )

        if approved_count >= required:
            # Fully approved
            request.status = 'approved'
            request.resolved_at = datetime.now(timezone.utc)
            db.session.flush()
            logger.info(f'Approval request {request.request_number} fully approved')
            ApprovalService._on_approved(request)
            return True, 'تمت الموافقة على الطلب بالكامل ✅'
        else:
            # Move to next level
            request.current_level = current_level.level + 1
            db.session.flush()
            return True, f'تمت الموافقة على الخطوة {current_level.level} — في انتظار الخطوة {request.current_level}'

    # ── Reject ───────────────────────────────────────────────────────────

    @staticmethod
    def reject(request_id, approver_id, notes=None):
        """Reject an approval request at any level."""
        request = db.session.get(ApprovalRequest, request_id)
        if not request:
            return False, 'طلب الموافقة غير موجود'
        if request.status != 'pending':
            return False, f'الطلب {request.status_ar}'

        current_level = ApprovalLevel.query.filter_by(
            request_id=request_id, status='pending'
        ).order_by(ApprovalLevel.level).first()

        if current_level:
            current_level.approved_by = approver_id
            current_level.status = 'rejected'
            current_level.approved_at = datetime.now(timezone.utc)
            if notes:
                current_level.notes = notes

        request.status = 'rejected'
        request.resolved_at = datetime.now(timezone.utc)

        db.session.flush()

        create_audit_log(
            action=f'approval_rejected by user#{approver_id}: {notes or ""}',
            table_name='approval_requests',
            record_id=request_id,
            changes={'approver_id': approver_id, 'notes': notes}
        )

        ApprovalService._on_rejected(request)
        return True, 'تم رفض الطلب ❌'

    # ── Cancel ───────────────────────────────────────────────────────────

    @staticmethod
    def cancel(request_id, user_id):
        """Cancel a pending request (requester or admin only)."""
        request = db.session.get(ApprovalRequest, request_id)
        if not request:
            return False, 'طلب الموافقة غير موجود'
        if request.status != 'pending':
            return False, 'لا يمكن إلغاء طلب تم البت فيه'

        request.status = 'cancelled'
        request.resolved_at = datetime.now(timezone.utc)
        db.session.flush()
        return True, 'تم إلغاء الطلب'

    # ── Hooks: what happens after approval/rejection ─────────────────────

    @staticmethod
    def _on_approved(request):
        """Post-approval actions. Called after full approval."""
        # For sales: the sale can now proceed normally
        # For payments: the payment can be confirmed
        # Currently just logs — hooks can be extended per entity type
        logger.info(f'Approval flow completed for {request.entity_type}#{request.entity_id}')

    @staticmethod
    def _on_rejected(request):
        """Post-rejection actions."""
        logger.info(f'Approval rejected for {request.entity_type}#{request.entity_id}')

    # ── Query helpers ────────────────────────────────────────────────────

    @staticmethod
    def get_pending_for_user(user):
        """Get all pending approval requests the user can approve."""
        roles = [r.name for r in user.roles] if hasattr(user, 'roles') else []
        level_query = ApprovalLevel.query.filter(
            ApprovalLevel.status == 'pending',
            ApprovalLevel.required_role.in_(roles)
        ).subquery()

        requests = db.session.query(ApprovalRequest).join(
            level_query, ApprovalRequest.id == level_query.c.request_id
        ).filter(
            ApprovalRequest.status == 'pending'
        ).all()
        return requests

    @staticmethod
    def get_all_requests(status=None, entity_type=None):
        """Get all approval requests with optional filters."""
        query = ApprovalRequest.query
        if status:
            query = query.filter_by(status=status)
        if entity_type:
            query = query.filter_by(entity_type=entity_type)
        return query.order_by(ApprovalRequest.created_at.desc()).all()
