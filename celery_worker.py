"""
Celery Worker Entry Point — نقطة دخول عامل Celery
Configure and start the Celery worker for background tasks.

Usage:
    celery -A celery_worker worker --loglevel=info --concurrency=2

Environment variables:
    CELERY_BROKER_URL  — Redis URL (default: redis://localhost:6379/1)
    CELERY_RESULT_BACKEND — Redis URL for results (default: same as broker)
"""
import os
from celery import Celery
from celery.schedules import crontab

# ── Broker / Backend ─────────────────────────────────────────────────────
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_BROKER = os.environ.get('CELERY_BROKER_URL', REDIS_URL)
CELERY_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', REDIS_URL)

celery = Celery(
    'uae_sale',
    broker=CELERY_BROKER,
    backend=CELERY_BACKEND,
)

# ── Celery Configuration ────────────────────────────────────────────────
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
celery.conf.beat_schedule = {
    # Balance repair: every 6 hours
    'balance-repair-every-6h': {
        'task': 'celery_worker.run_balance_repair',
        'schedule': crontab(minute=0, hour='*/6'),  # 00:00, 06:00, 12:00, 18:00
        'options': {'queue': 'default'},
    },
    # Auto-approval check: every hour
    'auto-approval-hourly': {
        'task': 'celery_worker.run_auto_approval',
        'schedule': crontab(minute=15),  # Every hour at :15
        'options': {'queue': 'default'},
    },
    # Security alerts scan: daily at 02:00
    'security-scan-daily': {
        'task': 'celery_worker.run_security_scan',
        'schedule': crontab(minute=0, hour=2),
        'options': {'queue': 'default'},
    },
}

# ── Auto-discover tasks from the tasks module ───────────────────────────
celery.autodiscover_tasks(['celery_tasks'])


# ── Inline Tasks ────────────────────────────────────────────────────────
# These create a Flask app context so they can use SQLAlchemy models.

@celery.task(name='celery_worker.run_balance_repair', bind=True, max_retries=2)
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
        self.retry(exc=exc, countdown=60)


@celery.task(name='celery_worker.run_auto_approval', bind=True, max_retries=2)
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
        self.retry(exc=exc, countdown=60)


@celery.task(name='celery_worker.run_security_scan', bind=True, max_retries=1)
def run_security_scan(self):
    """Scheduled task: daily security checks."""
    try:
        from app import create_app
        app = create_app()
        with app.app_context():
            from models import LoginHistory
            from extensions import db
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
