"""معالجات المساعد مقسمة لكل كيان (Phase 2b — مكتمل).

كل كيان له ملف مستقل (balance/customer/product/sale/payment/expense/
supplier/purchase/cheque/inventory/ledger/user). الموزّع هنا يختار
المعالج حسب `intent` ثم يفوّض إلى `services.ai_executor`.
"""
from services.ai_handlers import (
    balance,
    cheque,
    customer,
    expense,
    inventory,
    ledger,
    payment,
    product,
    purchase,
    sale,
    supplier,
    user,
)
from services.ai_executor import execute_plan

_HANDLERS = {
    'balance': balance.try_handle,
    'customer': customer.try_handle,
    'product': product.try_handle,
    'sale': sale.try_handle,
    'receive': payment.try_handle,
    'give': payment.try_handle,
    'expense': expense.try_handle,
    'supplier': supplier.try_handle,
    'purchase': purchase.try_handle,
    'cheque': cheque.try_handle,
    'warehouse': inventory.try_handle,
    'ledger': ledger.try_handle,
    'user': user.try_handle,
}


def dispatch(plan, user, confirmed=False) -> dict:
    """الموزّع حسب intent — يختار معالج الكيان المناسب."""
    handler = _HANDLERS.get((plan.intent or '').strip())
    if handler is None:
        return execute_plan(plan, user, confirmed=confirmed)
    result = handler(plan, user, confirmed=confirmed)
    if result is None:
        return execute_plan(plan, user, confirmed=confirmed)
    return result


def dispatch_for_action(message: str, user, confirmed=False):
    """نقطة دخول لـ routes/ai._process_user_action.

    تُصفّي «نفعل هنا أم نمضي للقديم؟»:
    - فقط الرسائل التي تحمل بيانات (':' أو مبلغ/اسم) تُحاول هنا.
    - القائمة الرقمية المجردة ('1'/'2'/'عودة') تُترك للقديم (يحمل الحالة).
    تُرجع str عندما حُسم الرد، و None ليفول إلى القديم.
    """
    if not message or not str(message).strip():
        return None
    text = str(message).strip()
    if text in ('1', '2', '3', '4', 'عودة', 'رجوع', 'إلغاء', 'نعم', 'لا', 'yes', 'no', 'ok'):
        return None
    # رفض سريع: «بدون بيانات» (قائمة) تُترك للمستوى القديم
    if ':' not in text and not any(ch.isdigit() for ch in text):
        return None
    try:
        from services.ai_planner import plan as _plan
        _p = _plan(text, user)
        if _p is None or not getattr(_p, 'tool', None):
            return None
        # confirmed للتأكيد عبر رسالة «نعم» الصريحة فقط
        _conf = bool(confirmed) or ('نعم' in text and (_p.needs_confirm or False))
        _res = dispatch(_p, user, confirmed=_conf)
        if _res and (_res.get('executed') or _res.get('needs_clarification')):
            return str(_res.get('response', ''))
    except Exception:
        return None
    return None
