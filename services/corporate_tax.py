"""ضريبة الشركات (الدخل) لكل تينانت — UAE: 9% على الأرباح > 375,000.

لكل شركة إعدادات مستقلة (مفعّل، نسبة، حد). الربح من دفتر الأستاذ
(إيرادات − مصروفات) للفترة والسنة المالية للتينانت.
"""
from __future__ import annotations
from decimal import Decimal


def compute_ct(net_profit, tenant) -> Decimal:
    """مسؤولية ضريبة الشركات (بعملة القاعدة) أو 0."""
    if tenant is None or not getattr(tenant, 'corp_tax_enabled', False):
        return Decimal('0')
    profit = Decimal(str(net_profit or 0))
    threshold = Decimal(str(getattr(tenant, 'corp_tax_threshold', 375000) or 0))
    rate = Decimal(str(getattr(tenant, 'corp_tax_rate', 9) or 0))
    if profit <= threshold:
        return Decimal('0')
    return ((profit - threshold) * rate / Decimal('100')).quantize(Decimal('0.01'))


def allowed_currency_list(tenant) -> list[str]:
    """عملات الشركة: قائمة صريحة أو كل Lookup."""
    raw = (getattr(tenant, 'allowed_currencies', None) or '').strip() if tenant else ''
    if raw:
        return [c.strip().upper() for c in raw.split(',') if c.strip()]
    return []


def post_corporate_tax(tenant, net_profit, as_of_date=None) -> dict:
    """ترحيل قيد الاستحقاق: مدين مصروف ضريبة الدخل / دائن ضرائب دخل مستحقة.

    يعيد {liability, posted} — بلا قيد عندما الضريبة 0.
    """
    amount = compute_ct(net_profit, tenant)
    if amount <= 0:
        return {'liability': amount, 'posted': False}
    from services.account_resolution import AccountRole, AccountResolver
    from services.gl_service import GLService
    tid = getattr(tenant, 'id', None)
    exp_code = AccountResolver.resolve(AccountRole.INCOME_TAX_EXPENSE, tenant_id=tid)
    liab_code = AccountResolver.resolve(AccountRole.CORP_TAX_PAYABLE, tenant_id=tid)
    GLService.post_entry(
        [
            {'account': exp_code, 'debit': amount, 'description': 'ضريبة دخل مستحقة'},
            {'account': liab_code, 'credit': amount, 'description': 'ضرائب دخل مستحقة'},
        ],
        description='Corporate Tax Accrual',
        reference_type='CorporateTax',
        entry_date=as_of_date,
        currency=None,
        user_id=None,
    )
    return {'liability': amount, 'posted': True}
