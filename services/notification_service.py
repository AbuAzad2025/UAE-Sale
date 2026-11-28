"""
Notification Service - خدمة الإشعارات
إرسال إشعارات فورية للمستخدمين
"""

from datetime import datetime, timezone
import logging
import os
import re

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _as_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_VALUES
    return bool(value)


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
    def _db_settings():
        """Current SystemSettings, or None when no DB/app context is available."""
        try:
            from flask import has_app_context

            if has_app_context():
                from models.system_settings import SystemSettings

                return SystemSettings.query.filter_by(is_active=True).first()
        except Exception as exc:
            logger.debug("Notification settings lookup unavailable: %s", exc)
        return None

    @staticmethod
    def get_setting(name, env_name=None, default=None):
        """Read a channel setting from DB first, then the environment."""
        settings = NotificationService._db_settings()
        value = getattr(settings, name, None) if settings is not None else None
        if value is None or value == "":
            value = os.environ.get(env_name) if env_name else None
        if value is None or value == "":
            return default
        if isinstance(default, bool):
            return _as_bool(value)
        return value

    @staticmethod
    def render_template(template_key, default_template, **placeholders):
        """Render a saved notification template with ``{name}`` placeholders.

        Saved templates live in ``SystemSettings.notification_templates``;
        the caller's ``default_template`` is used when no saved text exists.
        Unknown placeholders are left intact instead of raising KeyError.
        """
        template = default_template or ""
        if template_key:
            settings = NotificationService._db_settings()
            if settings is not None:
                try:
                    import json

                    saved = json.loads(settings.notification_templates or "{}")
                    if isinstance(saved, dict) and isinstance(
                        saved.get(template_key), str
                    ):
                        if saved[template_key].strip():
                            template = saved[template_key]
                except Exception as exc:
                    logger.debug("Invalid notification template JSON: %s", exc)
        if not template:
            return ""
        return re.sub(
            r"\{([A-Za-z_][A-Za-z0-9_]*)\}",
            lambda match: str(
                placeholders.get(match.group(1), match.group(0))
            ),
            template,
        )

    @staticmethod
    def channel_enabled(channel):
        """Honour the owner's per-channel enable flags (DB first, env fallback)."""
        settings = NotificationService._db_settings()

        def _flag(attr, env_name):
            value = getattr(settings, attr, None) if settings is not None else None
            if value is None:
                value = os.environ.get(env_name)
            return _as_bool(value) if value is not None else False

        if channel == "email":
            return _flag("enable_email_notifications", "ENABLE_EMAIL_NOTIFICATIONS")
        if channel == "sms":
            return _flag("sms_enabled", "ENABLE_SMS_NOTIFICATIONS") or _flag(
                "enable_sms_notifications", "ENABLE_SMS_NOTIFICATIONS"
            )
        if channel == "whatsapp":
            return _flag("whatsapp_enabled", "ENABLE_WHATSAPP_NOTIFICATIONS")
        return False

    @staticmethod
    def send_email(to, template_key, default_template, subject=None, **placeholders):
        """Send a templated email when email notifications are enabled."""
        message = NotificationService.render_template(
            template_key, default_template, **placeholders
        )
        result = {
            "channel": "email",
            "sent": False,
            "skipped": False,
            "error": None,
            "contact": to,
            "message": message,
        }
        if not to:
            result["error"] = "لا يوجد بريد إلكتروني للمستلم"
            return result
        if not NotificationService.channel_enabled("email"):
            result["skipped"] = True
            result["error"] = "Email notifications are disabled"
            return result
        host = NotificationService.get_setting("smtp_server", "SMTP_SERVER")
        if not host:
            result["error"] = "SMTP server is not configured"
            return result
        sender = NotificationService.get_setting(
            "email_from", "DEFAULT_MAIL_SENDER"
        ) or "no-reply@localhost"
        try:
            import smtplib
            from email.message import EmailMessage

            port = int(
                NotificationService.get_setting("smtp_port", "SMTP_PORT", 587)
            )
            msg = EmailMessage()
            msg["Subject"] = subject or "Notification"
            msg["From"] = sender
            msg["To"] = to
            msg.set_content(message)
            with smtplib.SMTP(str(host), port, timeout=15) as smtp:
                if _as_bool(
                    NotificationService.get_setting("smtp_use_tls", "SMTP_USE_TLS", True)
                ):
                    smtp.starttls()
                username = NotificationService.get_setting(
                    "smtp_username", "SMTP_USERNAME"
                )
                password = NotificationService.get_setting(
                    "smtp_password", "SMTP_PASSWORD"
                )
                if username and password:
                    smtp.login(str(username), str(password))
                smtp.send_message(msg)
            result["sent"] = True
        except Exception as exc:
            logger.warning("Email delivery failed: %s", exc)
            result["error"] = str(exc)[:300]
        return result

    @staticmethod
    def send_sms(to, template_key, default_template, **placeholders):
        """Send a templated SMS when SMS notifications are enabled."""
        message = NotificationService.render_template(
            template_key, default_template, **placeholders
        )
        result = {
            "channel": "sms",
            "sent": False,
            "skipped": False,
            "error": None,
            "contact": to,
            "message": message,
        }
        if not to:
            result["error"] = "لا يوجد رقم هاتف للمستلم"
            return result
        if not NotificationService.channel_enabled("sms"):
            result["skipped"] = True
            result["error"] = "SMS notifications are disabled"
            return result
        api_url = os.environ.get("SMS_API_URL")
        api_key = NotificationService.get_setting("sms_api_key", "SMS_API_KEY")
        if not api_url or not api_key:
            result["error"] = "SMS provider is not configured"
            return result
        try:
            import requests

            response = requests.post(
                api_url,
                data={
                    "token": str(api_key),
                    "to": to,
                    "message": message,
                    "text": message,
                    "sender": NotificationService.get_setting(
                        "sms_sender_name", "SMS_SENDER_NAME", ""
                    ),
                },
                timeout=15,
            )
            if 200 <= response.status_code < 300:
                result["sent"] = True
            else:
                result["error"] = f"SMS API HTTP {response.status_code}"
        except Exception as exc:
            logger.warning("SMS delivery failed: %s", exc)
            result["error"] = str(exc)[:300]
        return result

    @staticmethod
    def send_whatsapp(to, template_key, default_template, **placeholders):
        """Send a templated WhatsApp message when WhatsApp is enabled."""
        message = NotificationService.render_template(
            template_key, default_template, **placeholders
        )
        result = {
            "channel": "whatsapp",
            "sent": False,
            "skipped": False,
            "error": None,
            "contact": to,
            "message": message,
        }
        if not to:
            result["error"] = "لا يوجد رقم هاتف للمستلم"
            return result
        if not NotificationService.channel_enabled("whatsapp"):
            result["skipped"] = True
            result["error"] = "WhatsApp notifications are disabled"
            return result
        try:
            from services.whatsapp_service import WhatsAppService

            response = WhatsAppService.send_custom_message(to, message)
            result["sent"] = bool(response.get("success"))
            result["error"] = response.get("error")
        except Exception as exc:
            logger.warning("WhatsApp delivery failed: %s", exc)
            result["error"] = str(exc)[:300]
        return result

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
    def _failed_login_counts():
        """Return (distinct IPs, total failures) from durable login history.

        Failed logins are persisted by the auth route in ``login_history``;
        reading them makes the security status survive restarts instead of
        depending on the process-local throttling dict. The dict is only a
        fallback for contexts where the DB is unavailable.
        """
        try:
            from flask import has_app_context

            if has_app_context():
                from sqlalchemy import func

                from extensions import db
                from models.login_history import LoginHistory

                rows = (
                    db.session.query(
                        LoginHistory.ip_address, func.count(LoginHistory.id)
                    )
                    .filter(LoginHistory.success.is_(False))
                    .group_by(LoginHistory.ip_address)
                    .all()
                )
                if rows:
                    return len(rows), sum(int(count or 0) for _, count in rows)
        except Exception as exc:
            logger.debug("Failed-login history query unavailable: %s", exc)
        return len(SecurityService._failed_attempts), sum(
            int(data.get("count", 0)) for data in SecurityService._failed_attempts.values()
        )

    @staticmethod
    def get_security_status():
        """الحصول على حالة الأمان"""
        failed_ips, total_failed = SecurityService._failed_login_counts()
        return {
            "blacklisted_ips": len(SecurityService._blacklist),
            "failed_attempts": failed_ips,
            "total_failed_count": total_failed,
            "security_level": SecurityService._calculate_security_level(),
        }

    @staticmethod
    def _calculate_security_level():
        """حساب مستوى الأمان"""
        failed_count, _ = SecurityService._failed_login_counts()
        blacklisted = len(SecurityService._blacklist)

        if blacklisted > 10 or failed_count > 20:
            return "low"
        elif blacklisted > 5 or failed_count > 10:
            return "medium"
        else:
            return "high"
