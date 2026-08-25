"""Unit tests for ApprovalService — سير عمل الموافقات متعدد المستويات."""
from decimal import Decimal

import pytest

from extensions import db
from models import ApprovalWorkflow, ApprovalRequest, ApprovalLevel
from services.approval_service import ApprovalService


@pytest.fixture
def two_level_workflow(db):
    wf = ApprovalWorkflow(
        name='Large Sales Approval', entity_type='sale',
        min_amount=Decimal('1000'), max_amount=Decimal('100000'),
        levels_required=2, is_active=True,
    )
    db.session.add(wf)
    db.session.commit()
    return wf


@pytest.fixture
def submitted_request(db, owner_user, two_level_workflow):
    return ApprovalService.submit(
        entity_type='sale', entity_id=42,
        amount=Decimal('5000'), requested_by=owner_user.id,
        description='بيع كبير يحتاج موافقة',
    )


class TestFindWorkflow:
    def test_matches_within_range(self, db, two_level_workflow):
        assert ApprovalService.find_workflow('sale', Decimal('5000')) is two_level_workflow

    def test_below_min_returns_none(self, db, two_level_workflow):
        assert ApprovalService.find_workflow('sale', Decimal('999')) is None

    def test_above_max_returns_none(self, db, two_level_workflow):
        assert ApprovalService.find_workflow('sale', Decimal('100001')) is None

    def test_wrong_entity_type_returns_none(self, db, two_level_workflow):
        assert ApprovalService.find_workflow('purchase', Decimal('5000')) is None

    def test_inactive_workflow_ignored(self, db, two_level_workflow):
        two_level_workflow.is_active = False
        db.session.commit()
        assert ApprovalService.find_workflow('sale', Decimal('5000')) is None

    def test_highest_min_amount_wins(self, db, two_level_workflow):
        strict = ApprovalWorkflow(
            name='VIP Sales Approval', entity_type='sale',
            min_amount=Decimal('4000'), levels_required=1, is_active=True,
        )
        db.session.add(strict)
        db.session.commit()
        assert ApprovalService.find_workflow('sale', Decimal('5000')) is strict


class TestSubmit:
    def test_no_matching_workflow_returns_none(self, db, owner_user):
        result = ApprovalService.submit('sale', 1, Decimal('5'), owner_user.id)
        assert result is None

    def test_submit_creates_request_with_levels(self, db, owner_user, two_level_workflow):
        request = ApprovalService.submit('sale', 7, Decimal('2000'), owner_user.id)
        assert request is not None
        assert request.request_number.startswith('APR')
        assert request.status == 'pending'
        assert request.current_level == 1
        levels = (ApprovalLevel.query.filter_by(request_id=request.id)
                  .order_by(ApprovalLevel.level).all())
        assert [lv.level for lv in levels] == [1, 2]
        assert levels[0].required_role == 'manager'
        assert levels[1].required_role == 'owner'
        assert all(lv.status == 'pending' for lv in levels)


class TestApprove:
    def test_approve_nonexistent_request(self, db, owner_user):
        ok, msg = ApprovalService.approve(999999, owner_user.id)
        assert ok is False

    def test_multi_level_approval_flow(self, db, manager_user, owner_user, submitted_request):
        request = submitted_request

        ok, msg = ApprovalService.approve(request.id, manager_user.id)
        assert ok is True
        db.session.refresh(request)
        assert request.status == 'pending'
        assert request.current_level == 2

        ok, msg = ApprovalService.approve(request.id, owner_user.id)
        assert ok is True
        db.session.refresh(request)
        assert request.status == 'approved'
        assert request.resolved_at is not None

    def test_approve_already_resolved_fails(self, db, owner_user, submitted_request):
        request = submitted_request
        ApprovalService.reject(request.id, owner_user.id)
        ok, msg = ApprovalService.approve(request.id, owner_user.id)
        assert ok is False


class TestReject:
    def test_reject_pending_request(self, db, manager_user, submitted_request):
        request = submitted_request
        ok, msg = ApprovalService.reject(request.id, manager_user.id, notes='سعر خاطئ')
        assert ok is True
        db.session.refresh(request)
        assert request.status == 'rejected'
        assert request.resolved_at is not None
        level = ApprovalLevel.query.filter_by(request_id=request.id, level=1).first()
        assert level.status == 'rejected'
        assert level.notes == 'سعر خاطئ'

    def test_reject_nonexistent_request(self, db, owner_user):
        ok, msg = ApprovalService.reject(999999, owner_user.id)
        assert ok is False


class TestCancel:
    def test_cancel_pending_request(self, db, owner_user, submitted_request):
        ok, msg = ApprovalService.cancel(submitted_request.id, owner_user.id)
        assert ok is True
        db.session.refresh(submitted_request)
        assert submitted_request.status == 'cancelled'

    def test_cancel_resolved_request_fails(self, db, owner_user, submitted_request):
        ApprovalService.reject(submitted_request.id, owner_user.id)
        ok, msg = ApprovalService.cancel(submitted_request.id, owner_user.id)
        assert ok is False

    def test_cancel_nonexistent(self, db, owner_user):
        ok, msg = ApprovalService.cancel(999999, owner_user.id)
        assert ok is False


class TestQueries:
    def test_get_all_requests_filters(self, db, owner_user, submitted_request):
        all_reqs = ApprovalService.get_all_requests()
        assert len(all_reqs) >= 1
        pending = ApprovalService.get_all_requests(status='pending')
        assert all(r.status == 'pending' for r in pending)
        sales = ApprovalService.get_all_requests(entity_type='sale')
        assert all(r.entity_type == 'sale' for r in sales)

    def test_get_pending_for_user_without_roles_attr(self, db, owner_user, submitted_request):
        if hasattr(owner_user, 'roles'):
            pytest.skip('User model exposes roles relationship')
        result = ApprovalService.get_pending_for_user(owner_user)
        assert isinstance(result, list)
