"""ضريبة الشركات (الدخل) لكل تينانت — UAE: 9% على الأرباح > 375,000.

لكل شركة إعدادات مستقلة (مفعّل، نسبة، حد). الربح من دفتر الأستاذ
(إيرادات − مصروفات) للفترة، **باستثناء** مصروف ضريبة الدخل نفسه
(عدم احتساب الضريبة في أساسها).
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP


def compute_ct(net_profit, tenant) -> Decimal:
    """مسؤولية ضريبة الشركات (بعملة القاعدة) أو 0."""
    if tenant is None or not getattr(tenant, 'corp_tax_enabled', False):
        return Decimal('0')
    profit = Decimal(str(net_profit or 0))
    threshold = Decimal(str(getattr(tenant, 'corp_tax_threshold', 375000) or 0))
    rate = Decimal(str(getattr(tenant, 'corp_tax_rate', 9) or 0))
    if profit <= threshold:
        return Decimal('0')
    return ((profit - threshold) * rate / Decimal('100')).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP)


def allowed_currency_list(tenant) -> list[str]:
    """عملات الشركة: قائمة صريحة أو كل Lookup."""
    raw = (getattr(tenant, 'allowed_currencies', None) or '').strip() if tenant else ''
    if raw:
        return [c.strip().upper() for c in raw.split(',') if c.strip()]
    return []


def _existing_accrual(tid, as_of_date):
    """قيد CorporateTax مرحّل (غير معكوسة) لنفس الشركة ونفس التاريخ."""
    from datetime import datetime
    from models.gl import GLJournalEntry

    q = GLJournalEntry.query.filter_by(
        reference_type='CorporateTax',
        reference_id=tid,
        is_posted=True,
        is_reversed=False,
    )
    if as_of_date is not None:
        day = as_of_date
        start = datetime(day.year, day.month, day.day)
        end = start.replace(hour=23, minute=59, second=59)
        q = q.filter(GLJournalEntry.entry_date >= start,
                     GLJournalEntry.entry_date <= end)
    return q.first()


def post_corporate_tax(tenant, net_profit, as_of_date=None, created_by=None) -> dict:
    """ترحيل قيد الاستحقاق: مدين مصروف ضريبة الدخل / دائن ضرائب دخل مستحقة.

    الذرّية والتكرار: يعيد {liability, posted}؛ بلا قيد عندما الضريبة 0.
    يرفض الترحيل المزدوج لنفس الشركة/التاريخ بدل مضاعفة الاستحقاق.
    """
    amount = compute_ct(net_profit, tenant)
    if amount <= 0:
        return {'liability': amount, 'posted': False}

    tid = getattr(tenant, 'id', None)
    if _existing_accrual(tid, as_of_date):
        raise ValueError('تم ترحيل استحقاق ضريبة الدخل لهذه الشركة/التاريخ سابقاً — راجع دفتر الأستاذ أو اعكس القيد ثم رحّل مجدداً.')

    from services.account_resolution import AccountRole, AccountResolver
    from services.gl_service import GLService
    from services.currency_service import CurrencyService

    exp_code = AccountResolver.resolve(AccountRole.INCOME_TAX_EXPENSE, tenant_id=tid)
    liab_code = AccountResolver.resolve(AccountRole.CORP_TAX_PAYABLE, tenant_id=tid)
    GLService.post_entry(
        [
            {'account': exp_code, 'debit': amount,
             'description': 'ضريبة دخل مستحقة'},
            {'account': liab_code, 'credit': amount,
             'description': 'ضرائب دخل مستحقة'},
        ],
        description='Corporate Tax Accrual',
        reference_type='CorporateTax',
        reference_id=tid,
        entry_date=as_of_date,
        currency=CurrencyService.get_base_currency(),
        exchange_rate=Decimal('1'),
        created_by=created_by,
    )
    return {'liability': amount, 'posted': True}
