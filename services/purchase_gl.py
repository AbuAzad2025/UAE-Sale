"""قيد الشراء الذري (GL) — ضريبة إضافية/شاملة + غير قابلة للاسترداد + Reverse Charge.

حالتان إضافيتان فوق السلوك القياسي (المخزون قبل الضريبة، المورد بالإجمالي،
المدخل ضريبة مدخلات مدين):

1) ``vat_recoverable=False`` (ضريبة غير قابلة للاسترداد — سيارات، ترفيه...):
   لا حساب ضريبة مدخلات في القيد؛ الضريبة تُضاف لتكلفة المخزون والمورد
   يُسجَّل بالإجمالي. لا يمكن المطالبة بها لاحقًا في إقرار VAT.

2) ``reverse_charge=True`` (خدمات من مورد أجنبي لم يُحصِّل ضريبة):
   المورد يُسجَّل بالمبلغ الصافي فقط؛ المشتري يُسجِّل ضريبة ذاتية كمدين
   (ضريبة مدخلات في 1141) ودائن (ضريبة مخرجات في 2131) في نفس الوقت —
   صافي الأثر صفر على الرصيد النقدي، لكن الإقرار يُظهرها في كلا الجانبين.

3) كلا الخيارين معًا: الضريبة ذاتية كدائن "مخرجات" فقط، وتُضاف للتكلفة.

المنطق لا يفترض أي حساب محدد بل يحل الأدوار عبر ``AccountResolver``
(نفس نمط بقية القيود في كل النظام).
"""
from decimal import Decimal, ROUND_HALF_UP

from services.account_resolution import AccountResolver, AccountRole

_MONEY_Q = Decimal('0.001')


def _d(value):
    return Decimal(str(value or 0))


def build_purchase_gl_lines(purchase):
    """يبني سطور القيد من كائن الشراء. يعيد قائمة dictionaries جاهزة لـ post_entry."""
    tid = getattr(purchase, 'tenant_id', None)
    num = getattr(purchase, 'purchase_number', '') or ''
    total = _d(getattr(purchase, 'total_amount', 0)).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
    tax = _d(getattr(purchase, 'tax_amount', 0)).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
    net = (total - tax)
    if net < Decimal('0'):
        net = Decimal('0.000')
    net = net.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)

    recoverable = bool(getattr(purchase, 'vat_recoverable', True))
    reverse_charge = bool(getattr(purchase, 'reverse_charge', False))

    inventory = AccountResolver.resolve(AccountRole.INVENTORY, tenant_id=tid)
    ap = AccountResolver.resolve(AccountRole.AP_CONTROL, tenant_id=tid)
    vat_input = AccountResolver.resolve(AccountRole.VAT_INPUT, tenant_id=tid)
    vat_output = AccountResolver.resolve(AccountRole.VAT_OUTPUT, tenant_id=tid)

    supplier = getattr(purchase, 'supplier_name', '') or 'مورد'

    if reverse_charge and recoverable:
        return [
            {'account': inventory, 'debit': net,
             'description': f'شراء بضاعة (RC) {num}'},
            {'account': vat_input, 'debit': tax,
             'description': f'عكس ضريبة المدخلات (Reverse Charge) {num}'},
            {'account': vat_output, 'credit': tax,
             'description': f'عكس ضريبة المخرجات (Reverse Charge) {num}'},
            {'account': ap, 'credit': net,
             'description': f'ذمم دائنة - مورد: {supplier}'},
        ] if tax > 0 else [
            {'account': inventory, 'debit': net,
             'description': f'شراء بضاعة (RC) {num}'},
            {'account': ap, 'credit': net,
             'description': f'ذمم دائنة - مورد: {supplier}'},
        ]
    if reverse_charge and not recoverable:
        gross = (net + tax).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
        return [
            {'account': inventory, 'debit': gross,
             'description': f'شراء بضاعة (تكلفة شاملة للضريبة، RC) {num}'},
            {'account': vat_output, 'credit': tax,
             'description': f'عكس ضريبة المخرجات (Reverse Charge) {num}'},
            {'account': ap, 'credit': net,
             'description': f'ذمم دائنة - مورد: {supplier}'},
        ] if tax > 0 else [
            {'account': inventory, 'debit': net,
             'description': f'شراء بضاعة (RC) {num}'},
            {'account': ap, 'credit': net,
             'description': f'ذمم دائنة - مورد: {supplier}'},
        ]
    if not recoverable:
        # ضريبة تُحمّل على تكلفة البضاعة: لا حسابات ضريبة إطلاقًا
        gross = (net + tax).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
        return [
            {'account': inventory, 'debit': gross,
             'description': f'شراء بضاعة (ضريبة غير قابلة للاسترداد) {num}'},
            {'account': ap, 'credit': gross,
             'description': f'ذمم دائنة - مورد: {supplier}'},
        ]
    # القياسي: ضريبة مدخلات قابلة للاسترداد
    lines = [
        {'account': inventory, 'debit': net,
         'description': f'شراء بضاعة {num}'},
        {'account': ap, 'credit': total,
         'description': f'ذمم دائنة - مورد: {supplier}'},
    ]
    if tax > 0:
        lines.append({'account': vat_input, 'debit': tax,
                      'description': f'ضريبة القيمة المضافة (شراء) {num}'})
    return lines
