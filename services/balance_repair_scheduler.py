"""
Balance Repair Scheduler — جدولة إصلاح أرصدة متأخرة
Automated scheduled job that runs balance_checker on a configurable interval.
Uses the same pattern as the backup scheduler.
"""
from datetime import datetime, timezone, timedelta
from extensions import db
from utils.balance_checker import check_customer_balance, repair_customer_balance
from utils.helpers import create_audit_log
import logging

logger = logging.getLogger(__name__)


class BalanceRepairScheduler:
    """Manages scheduled balance repair runs."""

    SETTINGS_KEY = 'balance_repair_schedule'

    @staticmethod
    def get_schedule_settings():
        """Get current schedule settings from SystemSettings."""
        from models import SystemSettings
        setting = SystemSettings.query.filter_by(key=BalanceRepairScheduler.SETTINGS_KEY).first()
        if setting:
            import json
            try:
                return json.loads(setting.value)
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            'enabled': False,
            'interval_hours': 6,  # Run every 6 hours by default
            'last_run': None,
            'auto_repair': True,  # Auto-repair vs. report-only
        }

    @staticmethod
    def save_schedule_settings(settings):
        """Save schedule settings to SystemSettings."""
        from models import SystemSettings
        import json
        setting = SystemSettings.query.filter_by(
            key=BalanceRepairScheduler.SETTINGS_KEY).first()
        if not setting:
            setting = SystemSettings(key=BalanceRepairScheduler.SETTINGS_KEY)
            db.session.add(setting)
        setting.value = json.dumps(settings)
        db.session.commit()

    @staticmethod
    def run_scheduled_repair(auto_repair=True):
        """
        Execute the balance repair job.
        Returns a summary dict with results.
        """
        logger.info('🔧 Starting scheduled balance repair...')
        start_time = datetime.now(timezone.utc)

        # Detect drifts
        drifts = check_customer_balance()

        repaired_count = 0
        failed_count = 0
        report_only = []

        for drift in drifts:
            if auto_repair:
                success = repair_customer_balance(drift['customer_id'])
                if success:
                    repaired_count += 1
                    create_audit_log(
                        action=f'auto_balance_repair: customer#{drift["customer_id"]}',
                        table_name='customers',
                        record_id=drift['customer_id'],
                        changes={
                            'old_balance': float(drift.get('stored_balance', 0)),
                            'new_balance': float(drift.get('calculated_balance', 0)),
                            'drift': float(drift.get('drift', 0)),
                            'auto': True,
                        }
                    )
                else:
                    failed_count += 1
            else:
                report_only.append(drift)

        # Update last_run timestamp
        settings = BalanceRepairScheduler.get_schedule_settings()
        settings['last_run'] = start_time.isoformat()
        settings['drifts_found'] = len(drifts)
        settings['repaired'] = repaired_count
        settings['failed'] = failed_count
        BalanceRepairScheduler.save_schedule_settings(settings)

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        result = {
            'success': True,
            'drifts_found': len(drifts),
            'repaired': repaired_count,
            'failed': failed_count,
            'elapsed_seconds': round(elapsed, 2),
            'timestamp': start_time.isoformat(),
        }

        if drifts:
            logger.info(
                f'✅ Balance repair: {len(drifts)} drifts found, '
                f'{repaired_count} repaired, {failed_count} failed '
                f'({elapsed:.1f}s)'
            )
        else:
            logger.info('✅ Balance repair: no drifts detected')

        return result

    @staticmethod
    def should_run_now():
        """Check if enough time has passed since the last run."""
        settings = BalanceRepairScheduler.get_schedule_settings()
        if not settings.get('enabled'):
            return False

        last_run_str = settings.get('last_run')
        if not last_run_str:
            return True

        try:
            last_run = datetime.fromisoformat(last_run_str)
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
            interval = timedelta(hours=settings.get('interval_hours', 6))
            return datetime.now(timezone.utc) - last_run >= interval
        except (ValueError, TypeError):
            return True
