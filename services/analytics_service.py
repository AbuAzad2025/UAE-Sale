"""
Analytics Service - خدمة التحليلات
تحليلات متقدمة للمدفوعات والعملاء
"""

from datetime import datetime, timezone, timedelta
from models import Donation
import logging

logger = logging.getLogger(__name__)


class AnalyticsService:
    """خدمة التحليلات المتقدمة"""


    @staticmethod
    def get_daily_stats():
        """إحصائيات اليوم — من التبرعات (النظام الموحد بلا باقات)."""
        from datetime import datetime, timezone

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)
        today_donations = Donation.query.filter(
            Donation.created_at >= today_start).all()
        today_revenue = sum(float(d.amount_usd or 0) for d in today_donations
                            if d.status == "completed")
        return {
            "today_revenue": round(today_revenue, 2),
            "today_transactions": len(today_donations),
            "pending_today": sum(1 for d in today_donations if d.status == "pending"),
            "completed_today": sum(1 for d in today_donations if d.status == "completed"),
        }

    @staticmethod
    def get_revenue_by_period(period="month", months=6):  # noqa: C901
        """
        الحصول على الإيرادات حسب الفترة

        Args:
            period (str): الفترة (day, week, month, year)
            months (int): عدد الأشهر للتحليل

        Returns:
            dict: بيانات الإيرادات
        """
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=30 * months)

        donations = Donation.query.filter(
            Donation.status == "completed", Donation.created_at >= start_date
        ).all()

        _ = {}
        labels = []
        purchases_data = []
        donations_data = []

        for i in range(months):
            month_start = end_date - timedelta(days=30 * (months - i))
            month_end = month_start + timedelta(days=30)
            month_label = month_start.strftime("%b %Y")

            month_purchases = 0
            for d in donations:
                if d.transaction_type == "purchase" and d.created_at:
                    try:
                        dt = (
                            d.created_at.replace(tzinfo=None)
                            if d.created_at.tzinfo
                            else d.created_at
                        )
                        if (
                            month_start.replace(tzinfo=None)
                            <= dt
                            < month_end.replace(tzinfo=None)
                        ):
                            month_purchases += float(d.amount_usd or 0)
                    except Exception:
                        pass

            month_donations = 0
            for d in donations:
                if d.transaction_type == "donation" and d.created_at:
                    try:
                        dt = (
                            d.created_at.replace(tzinfo=None)
                            if d.created_at.tzinfo
                            else d.created_at
                        )
                        if (
                            month_start.replace(tzinfo=None)
                            <= dt
                            < month_end.replace(tzinfo=None)
                        ):
                            month_donations += float(d.amount_usd or 0)
                    except Exception:
                        pass

            labels.append(month_label)
            purchases_data.append(round(month_purchases, 2))
            donations_data.append(round(month_donations, 2))

        return {
            "labels": labels,
            "purchases": purchases_data,
            "donations": donations_data,
            "total_revenue": sum(purchases_data) + sum(donations_data),
        }

    @staticmethod
    def get_payment_method_stats():
        """إحصائيات طرق الدفع"""
        donations = Donation.query.filter_by(status="completed").all()

        methods = {}
        for donation in donations:
            method = donation.payment_method or "unknown"
            if method not in methods:
                methods[method] = {"count": 0, "total": 0}

            methods[method]["count"] += 1
            methods[method]["total"] += float(donation.amount_usd or 0)

        return {
            "methods": list(methods.keys()),
            "counts": [methods[m]["count"] for m in methods],
            "totals": [round(methods[m]["total"], 2) for m in methods],
        }

