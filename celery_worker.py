"""Celery Worker Entry Point — نقطة دخول عامل Celery.

The single Celery application instance lives in services/celery_tasks.py
(tasks + beat schedule are defined there); this module only re-exports it
so the worker CLI keeps working:

Usage:
    celery -A celery_worker.celery worker --loglevel=info --concurrency=2

Environment variables:
    CELERY_BROKER_URL  — Redis URL (default: REDIS_URL or redis://localhost:6379/0)
    CELERY_RESULT_BACKEND — Redis URL for results (default: same as broker)
"""
from services.celery_tasks import celery  # noqa: F401  (single shared instance)

__all__ = ['celery']
