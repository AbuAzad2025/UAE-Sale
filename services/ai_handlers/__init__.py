"""معالجات المساعد مقسمة لكل كيان (Phase 2b).

بدل حشو `routes/ai.py` (4,333 سطراً) الذي كان يعالج كل كيان dpi-
ختلف في فروع `if/elif` عملاقة، كل كيان له معالج مستقل يُستدعى
عبر الموزّع من `services.ai_executor`.

المعالجات هنا رفيعة (تحقق + توجيه عبر executor) ولا تكتب مباشرة.
"""
from services.ai_executor import execute_plan


def _run(plan, user, confirmed=False):
    plan.confirmed_note = confirmed  # توسيع Clamped دون كسر dataclass
    return execute_plan(plan, user, confirmed=confirmed)


def customer(plan, user, confirmed=False):
    return _run(plan, user, confirmed)


def product(plan, user, confirmed=False):
    return _run(plan, user, confirmed)


def sale(plan, user, confirmed=False):
    return _run(plan, user, confirmed)


def payment(plan, user, confirmed=False):
    return _run(plan, user, confirmed)


def expense(plan, user, confirmed=False):
    return _run(plan, user, confirmed)


def supplier(plan, user, confirmed=False):
    return _run(plan, user, confirmed)


def purchase(plan, user, confirmed=False):
    return _run(plan, user, confirmed)


def cheque(plan, user, confirmed=False):
    return _run(plan, user, confirmed)


def balance(plan, user, confirmed=False):
    return _run(plan, user, confirmed)


def inventory(plan, user, confirmed=False):
    return _run(plan, user, confirmed)


def ledger(plan, user, confirmed=False):
    return _run(plan, user, confirmed)


_TOOL_TO_HANDLER = {
    'customer': customer,
    'product': product,
    'sale': sale,
    'payment': payment,
    'expense': expense,
    'supplier': supplier,
    'purchase': purchase,
    'cheque': cheque,
    'balance': balance,
    'inventory': inventory,
    'ledger': ledger,
}


def dispatch(plan, user, confirmed=False) -> dict:
    """الموزّع — يختار معالج الكيان من intent."""
    handler = _TOOL_TO_HANDLER.get((plan.intent or '').strip())
    if handler is None:
        # fallback مباشر إلى executor (invalidate للقراءات)
        return execute_plan(plan, user, confirmed=confirmed)
    return handler(plan, user, confirmed=confirmed)
