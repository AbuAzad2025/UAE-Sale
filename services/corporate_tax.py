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
