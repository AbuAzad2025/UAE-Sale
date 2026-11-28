"""
Notification Service - خدمة الإشعارات
إرسال إشعارات فورية للمستخدمين
"""

from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    """خدمة الإشعارات"""

    _notifications = []

    @staticmethod
    def send_notification(title, message, notification_type="info", data=None):
        """
        إرسال إشعار

        Args:
            title (str): عنوان الإشعار
            message (str): نص الإشعار
            notification_type (str): نوع الإشعار (info, success, warning, danger)
            data (dict): بيانات إضافية
        """
        import json
        from extensions import db
        from models.notification import Notification
        from models.tenant_scope import get_current_tenant_id
        from flask_login import current_user

        row = None
        try:
            row = Notification(
                tenant_id=get_current_tenant_id(),
                user_id=getattr(current_user, "id", None)
                if getattr(current_user, "is_authenticated", False) else None,
                title=str(title or "")[:200],
                body=str(message or ""),
                type=str(notification_type or "info")[:20],
                data_json=json.dumps(data or {}, ensure_ascii=False),
            )
            db.session.add(row)
            db.session.commit()
        except Exception as exc:
            logger.warning("Persisted notification failed: %s", exc)
            try:
                db.session.rollback()
            except Exception:
                pass
            row = None

        if row is not None:
            return row.to_dict()

        notification = {
            "id": len(NotificationService._notifications) + 1,
            "title": title,
            "message": message,
            "type": notification_type,
            "data": data or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "read": False,
        }
        NotificationService._notifications.append(notification)
        logger.info(f"🔔 Notification sent: {title} - {message}")
        return notification

    @staticmethod
    def get_recent_notifications(limit=10):
        """جلب آخر الإشعارات"""
        try:
            from models.notification import Notification
            from flask_login import current_user
            q = Notification.query
            if getattr(current_user, "is_authenticated", False) and not getattr(current_user, "is_owner", False):
                q = q.filter(Notification.user_id == current_user.id)
            rows = q.order_by(Notification.created_at.desc()).limit(max(1, min(limit, 100))).all()
            return [r.to_dict() for r in rows]
        except Exception as exc:
            logger.warning("Notification query failed: %s", exc)
            return NotificationService._notifications[-limit:]

    @staticmethod
    def mark_as_read(notification_id):
        """تعليم الإشعار كمقروء"""
        try:
            from models.notification import Notification
            from extensions import db
            from datetime import datetime as _dt, timezone as _tz
            from flask_login import current_user
            q = Notification.query.filter(Notification.id == notification_id)
            if getattr(current_user, "is_authenticated", False) and not getattr(current_user, "is_owner", False):
                q = q.filter(Notification.user_id == current_user.id)
            row = q.first()
            if row is not None:
                row.read_at = _dt.now(_tz.utc)
                db.session.commit()
                return True
        except Exception as exc:
            logger.warning("mark_as_read failed: %s", exc)
            try:
                db.session.rollback()
            except Exception:
                pass
        for notif in NotificationService._notifications:
            if notif["id"] == notification_id:
                notif["read"] = True
                return True
        return False

    @staticmethod
    def notify_payment_received(amount, customer_name, payment_method):
        """إشعار باستلام دفعة"""
        return NotificationService.send_notification(
            title="💰 دفعة جديدة",
            message=f"تم استلام ${amount} من {customer_name} عبر {payment_method}",
            notification_type="success",
            data={"amount": amount, "customer": customer_name},
        )

    @staticmethod
    def notify_security_alert(alert_type, details):
        """إشعار بتنبيه أمني"""
        return NotificationService.send_notification(
            title="🚨 تنبيه أمني",
            message=f"{alert_type}: {details}",
            notification_type="danger",
            data={"alert_type": alert_type, "details": details},
        )


    @staticmethod
    def notify_auto_approval(count, total_amount):
        """إشعار بالقبول التلقائي"""
        return NotificationService.send_notification(
            title="⚡ قبول تلقائي",
            message=f"تم قبول {count} عملية تلقائياً بمبلغ ${total_amount}",
            notification_type="success",
            data={"count": count, "amount": total_amount},
        )


class SecurityService:
    """خدمة الأمان والتنبيهات"""

    _blacklist = set()

    _failed_attempts = {}

    @staticmethod
    def detect_suspicious_activity(ip_address, user_agent, action):
        """
        كشف النشاط المشبوه

        Args:
            ip_address (str): عنوان IP
            user_agent (str): User Agent
            action (str): الإجراء المنفذ

        Returns:
            dict: نتيجة الفحص
        """
        if ip_address in SecurityService._blacklist:
            NotificationService.notify_security_alert(
                "IP محظور", f"محاولة وصول من IP محظور: {ip_address}"
            )
            return {"suspicious": True, "reason": "blacklisted_ip"}

        if ip_address in SecurityService._failed_attempts:
            attempts = SecurityService._failed_attempts[ip_address]
            if attempts["count"] >= 5:
                SecurityService._blacklist.add(ip_address)
                NotificationService.notify_security_alert(
                    "IP محظور تلقائياً",
                    f"تم حظر IP {ip_address} بسبب محاولات فاشلة متكررة",
                )
                return {"suspicious": True, "reason": "too_many_failed_attempts"}

        suspicious_agents = ["bot", "crawler", "scraper", "scanner"]
        if any(agent in user_agent.lower() for agent in suspicious_agents):
            NotificationService.notify_security_alert(
                "User Agent مشبوه", f"كشف user agent مشبوه: {user_agent[:100]}"
            )
            return {"suspicious": True, "reason": "suspicious_user_agent"}

        return {"suspicious": False}

    @staticmethod
    def log_failed_attempt(ip_address):
        """تسجيل محاولة فاشلة"""
        if ip_address not in SecurityService._failed_attempts:
            SecurityService._failed_attempts[ip_address] = {
                "count": 0,
                "first_attempt": datetime.now(timezone.utc),
                "last_attempt": None,
            }

        SecurityService._failed_attempts[ip_address]["count"] += 1
        SecurityService._failed_attempts[ip_address]["last_attempt"] = datetime.now(
            timezone.utc
        )

    @staticmethod
    def reset_failed_attempts(ip_address):
        """إعادة تعيين المحاولات الفاشلة"""
        if ip_address in SecurityService._failed_attempts:
            del SecurityService._failed_attempts[ip_address]

    @staticmethod
    def get_security_status():
        """الحصول على حالة الأمان"""
        return {
            "blacklisted_ips": len(SecurityService._blacklist),
            "failed_attempts": len(SecurityService._failed_attempts),
            "total_failed_count": sum(
                data["count"] for data in SecurityService._failed_attempts.values()
            ),
            "security_level": SecurityService._calculate_security_level(),
        }

    @staticmethod
    def _calculate_security_level():
        """حساب مستوى الأمان"""
        failed_count = len(SecurityService._failed_attempts)
        blacklisted = len(SecurityService._blacklist)

        if blacklisted > 10 or failed_count > 20:
            return "low"
        elif blacklisted > 5 or failed_count > 10:
            return "medium"
        else:
            return "high"
