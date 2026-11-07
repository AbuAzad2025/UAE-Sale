"""معالجات الموردين (Phase 2b)."""
from services.ai_executor import execute_plan


def try_handle(plan, user, confirmed=False):
    if (plan.intent or '') != 'supplier':
        return None
    return execute_plan(plan, user, confirmed=confirmed)
