"""معالجات المستخدمين — owner فقط، لا تنفيذ من المساعد العام (Phase 2b)."""

from services.ai_executor import execute_plan


def try_handle(plan, user, confirmed=False):
    if (plan.intent or "") != "user":
        return None
    if user is None or not getattr(user, "is_owner", False):
        return {
            "executed": False,
            "response": "⛔ إدارة المستخدمين للمالك فقط من لوحة المالك.",
            "needs_clarification": False,
        }
    return execute_plan(plan, user, confirmed=confirmed)
