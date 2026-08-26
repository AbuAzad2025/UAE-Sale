"""Single Celery application instance + task definitions — نقطة مركزية لـ Celery.

All Celery tasks in the project share THIS instance. The worker entry point
(celery_worker.py) simply re-exports it so both of these work:

    celery -A services.celery_tasks.celery worker
    celery -A celery_worker.celery worker

Tasks build their own Flask app context internally (pattern: ``from app
import create_app`` inside the task body) so they stay independent from the
web process.
"""
import os

from celery import Celery
from celery.schedules import crontab

from extensions import db

celery = Celery(
    'uae_sale',
    broker=os.environ.get('CELERY_BROKER_URL',
                          os.environ.get('REDIS_URL', 'redis://localhost:6379/0')),
    backend=os.environ.get('CELERY_RESULT_BACKEND',
                           os.environ.get('REDIS_URL', 'redis://localhost:6379/0')),
)

celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Dubai',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,         # 10 min hard limit per task
    task_soft_time_limit=540,    # 9 min soft limit
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    result_expires=3600,         # Results expire after 1 hour
)

# ── Periodic Tasks (Beat Schedule) ──────────────────────────────────────
# Every entry references a task name registered on THIS instance below.
celery.conf.beat_schedule = {
    # Balance repair: every 6 hours
    'balance-repair-every-6h': {
        'task': 'celery_tasks.run_balance_repair',
        'schedule': crontab(minute=0, hour='*/6'),  # 00:00, 06:00, 12:00, 18:00
        'options': {'queue': 'default'},
    },
    # Auto-approval check: every hour
    'auto-approval-hourly': {
        'task': 'celery_tasks.run_auto_approval',
        'schedule': crontab(minute=15),  # Every hour at :15
        'options': {'queue': 'default'},
    },
    # Security alerts scan: daily at 02:00
    'security-scan-daily': {
        'task': 'celery_tasks.run_security_scan',
        'schedule': crontab(minute=0, hour=2),
        'options': {'queue': 'default'},
    },
    # Automatic database backup: daily at 03:00
    'auto-backup-daily': {
        'task': 'celery_tasks.auto_backup_database',
        'schedule': crontab(minute=30, hour=3),
        'options': {'queue': 'default'},
    },
}


@celery.task(name='celery_tasks.generate_monthly_report')
def generate_monthly_report(month: int, year: int):
    from app import create_app
    from services.report_service import ReportService

    app = create_app()
    with app.app_context():
        report = ReportService.generate_monthly_report(month, year)
        return {'success': True, 'report_id': report.id if report else None}


@celery.task(name='celery_tasks.send_invoice_email')
def send_invoice_email(sale_id: int):
    from app import create_app
    from models import Sale
    from flask_mail import Message
    from extensions import mail

    app = create_app()
    with app.app_context():
        sale = db.session.get(Sale, sale_id)
        if sale and sale.customer and sale.customer.email:
            msg = Message(
                subject=f'فاتورة رقم {sale.sale_number}',
                recipients=[sale.customer.email],
                body=f'تجدون في المرفق فاتورتكم رقم {sale.sale_number}'
            )
            mail.send(msg)
            return {'success': True}
        return {'success': False}


@celery.task(name='celery_tasks.auto_backup_database')
def auto_backup_database():
    from app import create_app
    from services.backup_service import BackupService

    app = create_app()
    with app.app_context():
        backup = BackupService.auto_backup_daily()
        return {'success': bool(backup), 'backup': backup}


@celery.task(name='celery_tasks.update_exchange_rates')
def update_exchange_rates():
    from app import create_app
    from services.currency_service import CurrencyService

    app = create_app()
    with app.app_context():
        result = CurrencyService.update_all_rates()
        return result


@celery.task(name='celery_tasks.train_neural_models')
def train_neural_models():
    from app import create_app
    from ai_knowledge.neural_engine import get_neural_engine

    app = create_app()
    with app.app_context():
        neural = get_neural_engine()
        results = neural.train_all_models()
        return results


@celery.task(name='celery_tasks.send_payment_reminders')
def send_payment_reminders():
    from app import create_app
    from models import Customer
    from services.whatsapp_service import WhatsAppService
    from decimal import Decimal

    app = create_app()
    with app.app_context():
        customers = Customer.query.filter_by(is_active=True).all()
        sent = 0

        for customer in customers:
            balance = customer.get_balance_aed()
            if balance > Decimal('1000') and customer.phone:
                result = WhatsAppService.send_payment_reminder(
                    customer.phone,
                    customer.name,
                    float(balance)
                )
                if result.get('success'):
                    sent += 1

        return {'sent': sent, 'total_checked': len(customers)}


@celery.task(name='celery_tasks.cleanup_old_cache')
def cleanup_old_cache():
    from extensions import cache

    try:
        cache.clear()
        return {'success': True, 'message': 'Cache cleared'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ── Scheduled maintenance tasks (referenced by beat_schedule above) ─────


@celery.task(name='celery_tasks.run_balance_repair', bind=True, max_retries=2)
def run_balance_repair(self):
    """Scheduled task: run balance consistency check + repair."""
    try:
        from app import create_app
        app = create_app()
        with app.app_context():
            from services.balance_repair_scheduler import BalanceRepairScheduler
            result = BalanceRepairScheduler.run_scheduled_repair(auto_repair=True)
            return result
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


@celery.task(name='celery_tasks.run_auto_approval', bind=True, max_retries=2)
def run_auto_approval(self):
    """Scheduled task: auto-approve pending donations/purchases."""
    try:
        from app import create_app
        app = create_app()
        with app.app_context():
            from services.auto_approval_service import AutoApprovalService
            donation_result = AutoApprovalService.approve_pending_donations(hours_threshold=1)
            purchase_result = AutoApprovalService.approve_pending_purchases(hours_threshold=1)
            return {
                'donations': donation_result,
                'purchases': purchase_result,
            }
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


@celery.task(name='celery_tasks.run_security_scan', bind=True, max_retries=1)
def run_security_scan(self):
    """Scheduled task: daily security checks."""
    try:
        from app import create_app
        app = create_app()
        with app.app_context():
            from models import LoginHistory
            from datetime import datetime, timedelta, timezone

            # Check for users with too many failed logins
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            suspicious = db.session.query(
                LoginHistory.user_id,
                db.func.count().label('fail_count')
            ).filter(
                LoginHistory.success is False,
                LoginHistory.timestamp >= cutoff
            ).group_by(
                LoginHistory.user_id
            ).having(
                db.func.count() >= 10
            ).all()

            return {
                'suspicious_users': len(suspicious),
                'user_ids': [s[0] for s in suspicious],
            }
    except Exception as exc:
        return {'error': str(exc)}
