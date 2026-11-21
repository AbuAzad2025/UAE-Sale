"""
Auto Approval Service
خدمة القبول التلقائي للتبرعات والمشتريات بعد ساعة
"""

from datetime import datetime, timezone, timedelta
from extensions import db
from models import Donation
from utils.helpers import create_audit_log
import logging

logger = logging.getLogger(__name__)


class AutoApprovalService:
    """خدمة القبول التلقائي"""

    @staticmethod
    def approve_pending_donations(hours_threshold=1):
        """
        قبول التبرعات المعلقة بعد ساعة واحدة

        Args:
            hours_threshold (int): عدد الساعات قبل القبول التلقائي (افتراضي: 1)

        Returns:
            dict: نتائج العملية
        """
        try:
            threshold_time = datetime.now(timezone.utc) - timedelta(
                hours=hours_threshold
            )

            pending_donations = Donation.query.filter(
                Donation.status == "pending",
                Donation.transaction_type == "donation",
                Donation.created_at <= threshold_time,
            ).all()

            approved_count = 0
            approved_amount = 0

            for donation in pending_donations:
                donation.status = "completed"
                donation.completed_at = datetime.now(timezone.utc)

                create_audit_log(
                    action=f"auto_approved_donation: ${donation.amount_usd}",
                    table_name="donations",
                    record_id=donation.id,
                    changes={
                        "old_status": "pending",
                        "new_status": "completed",
                        "auto": True,
                    },
                )

                approved_count += 1
                approved_amount += float(donation.amount_usd or 0)

            db.session.flush()

            if approved_count > 0:
                logger.info(
                    f"✅ Auto-approved {approved_count} donations, total: ${approved_amount}"
                )

            return {
                "success": True,
                "approved_count": approved_count,
                "approved_amount": approved_amount,
                "message": f"تم قبول {approved_count} تبرع تلقائياً",
            }

        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Error in auto-approval: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def run_auto_approval():
        """تشغيل القبول التلقائي للتبرعات"""
        logger.info("🔄 Running auto-approval service...")
        donations_result = AutoApprovalService.approve_pending_donations(
            hours_threshold=1)
        return {
            "donations": donations_result,
            "total_approved": donations_result.get("approved_count", 0),
            "total_amount": donations_result.get("approved_amount", 0),
        }


def schedule_auto_approval(app):
    """جدولة القبول التلقائي كل ساعة"""
    import threading
    import time

    def approval_task():
        while True:
            try:
                with app.app_context():
                    from models import run_in_platform_context

                    result = run_in_platform_context(
                        AutoApprovalService.run_auto_approval
                    )
                    logger.info(f"✅ Auto-approval completed: {result}")

            except Exception as e:
                logger.error(f"❌ Error in auto-approval task: {str(e)}")
            finally:
                time.sleep(3600)  # 3600 ثانية = 1 ساعة

    thread = threading.Thread(target=approval_task, daemon=True)
    thread.start()
    logger.info("✅ Auto-approval scheduler started")
