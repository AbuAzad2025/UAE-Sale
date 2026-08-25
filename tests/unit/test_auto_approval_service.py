"""Unit tests for AutoApprovalService — القبول التلقائي للتبرعات والمشتريات."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from models import Donation, Package, PackagePurchase
from services.auto_approval_service import AutoApprovalService


def _old_donation(**kwargs):
    defaults = dict(
        amount_usd=Decimal('25.00'), payment_method='crypto',
        status='pending', transaction_type='donation',
        created_at=datetime.now(timezone.utc) - timedelta(hours=3),
    )
    defaults.update(kwargs)
    return Donation(**defaults)


@pytest.fixture
def package(db):
    pkg = Package(
        name_ar='باقة احترافية', name_en='Professional', slug='professional',
        price=99.0,
    )
    db.session.add(pkg)
    db.session.commit()
    return pkg


class TestApprovePendingDonations:
    def test_approves_old_pending_donations(self, db):
        old = _old_donation(amount_usd=Decimal('50.00'))
        fresh = _old_donation(created_at=datetime.now(timezone.utc))
        other_status = _old_donation(status='failed')
        purchase_type = _old_donation(transaction_type='purchase')
        db.session.add_all([old, fresh, other_status, purchase_type])
        db.session.commit()

        result = AutoApprovalService.approve_pending_donations(hours_threshold=1)

        assert result['success'] is True
        assert result['approved_count'] == 1
        assert result['approved_amount'] == 50.0
        db.session.refresh(old)
        assert old.status == 'completed'
        assert old.completed_at is not None

    def test_nothing_to_approve(self, db):
        result = AutoApprovalService.approve_pending_donations()
        assert result['success'] is True
        assert result['approved_count'] == 0


class TestApprovePendingPurchases:
    def test_approves_old_purchase_and_related_donation(self, db, package):
        old_purchase = PackagePurchase(
            package_id=package.id, customer_name='شريف', customer_email='sharif@test.com',
            payment_method='card', payment_status='pending', amount_paid=99.0,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        related_donation = Donation(
            amount_usd=Decimal('99.00'), payment_method='card',
            status='pending', transaction_type='purchase',
            package='professional', customer_email='sharif@test.com',
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        db.session.add_all([old_purchase, related_donation])
        db.session.commit()

        result = AutoApprovalService.approve_pending_purchases(hours_threshold=1)

        assert result['success'] is True
        assert result['approved_count'] == 1
        assert result['approved_amount'] == 99.0
        db.session.refresh(old_purchase)
        assert old_purchase.payment_status == 'completed'
        assert old_purchase.activation_status == 'activated'
        assert old_purchase.activation_date is not None
        db.session.refresh(related_donation)
        assert related_donation.status == 'completed'

    def test_recent_purchase_not_approved(self, db, package):
        fresh = PackagePurchase(
            package_id=package.id, customer_name='جديد', customer_email='new@test.com',
            payment_method='card', payment_status='pending', amount_paid=99.0,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(fresh)
        db.session.commit()

        result = AutoApprovalService.approve_pending_purchases(hours_threshold=1)

        assert result['approved_count'] == 0
        db.session.refresh(fresh)
        assert fresh.payment_status == 'pending'


class TestRunAutoApproval:
    def test_combined_run(self, db, package):
        db.session.add(_old_donation(amount_usd=Decimal('10.00')))
        db.session.add(PackagePurchase(
            package_id=package.id, customer_name='عميل', customer_email='c@test.com',
            payment_method='bank', payment_status='pending', amount_paid=200.0,
            created_at=datetime.now(timezone.utc) - timedelta(hours=5),
        ))
        db.session.commit()

        result = AutoApprovalService.run_auto_approval()

        assert result['donations']['success'] is True
        assert result['purchases']['success'] is True
        assert result['total_approved'] == 2
        assert result['total_amount'] == 210.0
