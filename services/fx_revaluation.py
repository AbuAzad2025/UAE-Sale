"""
محرك تسوية أرصدة العملات الأجنبية في نهاية الشهر
Month-end unrealized FX revaluation engine

يحسب أرصدة الذمم المدينة والدائنة المفتوحة بالعملات الأجنبية من دفاتر
المبيعات والمشتريات، ثم يُنتج مسودة قيد تسوية متوازن يُعيد تقييمها بسعر
الإغلاق الحالي مقابل السعر التاريخي المسجّل.

اصطلاحات:
- موجب unrealized_gain_loss = ربح غير محقق (مدين AR / دائن AP يزيدان الأصول أو ينقصان الالتزامات).
- القيد متوازن دائمًا: مجموع الفروق على ميزان المراجعة = صفر، والفرق الصافي
  يُوجَّه إلى أرباح/خسائر فرق العملة عبر الحل الديناميكي للحسابات.
- dry_run افتراضيًا True؛ لا يتم الترحيل إلا عند dry_run=False عبر GLService.create_manual_entry.
"""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from services.currency_service import CurrencyService

# حل ديناميكي لحسابات GL (عقد Agent 1) مع سقوط آمن إلى الرموز الحرفية الحالية
try:
    from services.account_resolution import AccountResolver, AccountRole
except Exception:  # pragma: no cover - الوحدة تُسلَّم بالتوازي
    AccountRole = None  # type: ignore[assignment,misc]
    AccountResolver = None  # type: ignore[assignment,misc]

FALLBACK_ACCOUNT_CODES = {
    'AR_CONTROL': '1130',
    'AP_CONTROL': '2110',
    'FX_GAIN': '4400',
    'FX_LOSS': '6900',
}

MONEY_QUANTUM = Decimal('0.01')


def _q2(value):
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _resolve_account(role_value, fallback_code):
    try:
        if AccountRole is not None and AccountResolver is not None:
            code = AccountResolver.resolve(AccountRole(role_value))
            if code:
                return code
    except Exception:
        pass
    return FALLBACK_ACCOUNT_CODES.get(role_value, fallback_code)


def _clamp_non_negative(value):
    value = Decimal(str(value))
    return value if value > 0 else Decimal('0.00')


def _balance_sheet_line(code, role_label, delta):
    """مدين/دائن سطر ميزانية حسب إشارة الفرق (None إذا لا فرق)."""
    if delta > 0:
        return {'account_code': code, 'account_role': role_label,
                'debit': delta, 'credit': Decimal('0.00')}
    if delta < 0:
        return {'account_code': code, 'account_role': role_label,
                'debit': Decimal('0.00'), 'credit': -delta}
    return None


class FXRevaluationService:
    """تجميع الأرصدة المفتوحة بالعملة الأجنبية وإنتاج قيد إعادة تقييم غير محقق."""

    REFERENCE_TYPE = 'fx_revaluation'

    @staticmethod
    def collect_open_ar_balances(as_of=None):
        """أرصدة عملاء مفتوحة حسب العملة الأجنبية من المبيعات غير المسددة."""
        from models import Sale
        base = CurrencyService.get_base_currency()

        query = Sale.query.filter(
            Sale.is_active.is_(True),
            Sale.status != 'cancelled',
            Sale.balance_due > 0,
            Sale.currency != base,
        )
        if as_of is not None:
            query = query.filter(Sale.sale_date <= as_of)

        balances = {}
        for sale in query.all():
            currency = (sale.currency or base).upper()
            open_foreign = _clamp_non_negative(sale.balance_due)
            historical = _clamp_non_negative(
                Decimal(str(sale.amount_base or 0)) - Decimal(str(sale.paid_amount_base or 0)))
            entry = balances.setdefault(currency, {
                'foreign': Decimal('0.00'), 'historical_base': Decimal('0.00')})
            entry['foreign'] += open_foreign
            entry['historical_base'] += historical
        return balances

    @staticmethod
    def collect_open_ap_balances(as_of=None):
        """أرصدة موردين مفتوحة حسب العملة الأجنبية من المشتريات غير المسددة.

        لا يوجد عمود paid_amount_base في المشتريات، فيُحتسب الجزء المدفوع
        بسعر الصرف التاريخي نفسه (بما يطابق منطق المبيعات).
        """
        from models import Purchase
        base = CurrencyService.get_base_currency()

        query = Purchase.query.filter(
            Purchase.status != 'cancelled',
            Purchase.currency != base,
        )
        if as_of is not None:
            query = query.filter(Purchase.purchase_date <= as_of)

        balances = {}
        for purchase in query.all():
            currency = (purchase.currency or base).upper()
            total = Decimal(str(purchase.total_amount or 0))
            paid = Decimal(str(purchase.paid_amount or 0))
            open_foreign = _clamp_non_negative(total - paid)
            if open_foreign <= 0:
                continue
            rate = purchase.exchange_rate if purchase.exchange_rate else Decimal('1')
            paid_base = (paid * Decimal(str(rate))).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
            historical = _clamp_non_negative(Decimal(str(purchase.amount_base or 0)) - paid_base)
            entry = balances.setdefault(currency, {
                'foreign': Decimal('0.00'), 'historical_base': Decimal('0.00')})
            entry['foreign'] += open_foreign
            entry['historical_base'] += historical
        return balances

    @staticmethod
    def build_revaluation(rates=None, as_of=None):
        """بناء مسودة قيد إعادة التقييم دون أي ترحيل (نقية قابلة للاختبار).

        rates: تجاوز اختياري {currency: price} لأغراض الإعادة/التقارير؛
               وإلا يُستخدم CurrencyService.get_exchange_rate نحو عملة القاعدة.
        """
        base = CurrencyService.get_base_currency()
        ar_balances = FXRevaluationService.collect_open_ar_balances(as_of=as_of)
        ap_balances = FXRevaluationService.collect_open_ap_balances(as_of=as_of)
        currencies = sorted(set(ar_balances) | set(ap_balances))

        ar_code = _resolve_account('AR_CONTROL', FALLBACK_ACCOUNT_CODES['AR_CONTROL'])
        ap_code = _resolve_account('AP_CONTROL', FALLBACK_ACCOUNT_CODES['AP_CONTROL'])
        gain_code = _resolve_account('FX_GAIN', FALLBACK_ACCOUNT_CODES['FX_GAIN'])
        loss_code = _resolve_account('FX_LOSS', FALLBACK_ACCOUNT_CODES['FX_LOSS'])

        per_currency = []
        lines = []
        total_unrealized = Decimal('0.00')

        for currency in currencies:
            ar = ar_balances.get(currency, {'foreign': Decimal('0'), 'historical_base': Decimal('0')})
            ap = ap_balances.get(currency, {'foreign': Decimal('0'), 'historical_base': Decimal('0')})

            if rates and currency in rates:
                current_rate = Decimal(str(rates[currency]))
                if current_rate <= 0:
                    raise ValueError(f'Invalid override rate for {currency}')
            else:
                current_rate = CurrencyService.get_exchange_rate(currency, base)

            hist_ar = _q2(ar['historical_base'])
            hist_ap = _q2(ap['historical_base'])
            cur_ar = _q2(Decimal(str(ar['foreign'])) * current_rate)
            cur_ap = _q2(Decimal(str(ap['foreign'])) * current_rate)

            delta_ar = cur_ar - hist_ar   # زيادة أصل = مكسب
            delta_ap = cur_ap - hist_ap   # زيادة التزام = خسارة
            unrealized = delta_ar - delta_ap

            per_currency.append({
                'currency': currency,
                'open_foreign_ar': _q2(ar['foreign']),
                'open_foreign_ap': _q2(ap['foreign']),
                'historical_base_ar': hist_ar,
                'historical_base_ap': hist_ap,
                'current_base_ar': cur_ar,
                'current_base_ap': cur_ap,
                'current_rate': current_rate,
                'historical_base': hist_ar - hist_ap,
                'current_base': cur_ar - cur_ap,
                'unrealized_gain_loss': unrealized,
            })
            total_unrealized += unrealized

            line_ar = _balance_sheet_line(ar_code, 'AR_CONTROL', delta_ar)
            if line_ar:
                line_ar['description'] = f'إعادة تقييم ذمم مدينة مفتوحة بعملة {currency}'
                lines.append(line_ar)
            # الالتزام عكس الأصل: زيادة الذمة الدائنة تُسجل دائنًا
            line_ap = _balance_sheet_line(ap_code, 'AP_CONTROL', -delta_ap)
            if line_ap:
                line_ap['description'] = f'إعادة تقييم ذمم دائنة مفتوحة بعملة {currency}'
                lines.append(line_ap)

        if total_unrealized > 0:
            lines.append({'account_code': gain_code, 'account_role': 'FX_GAIN',
                          'debit': Decimal('0.00'), 'credit': total_unrealized,
                          'description': 'أرباح فرق عملة غير محققة'})
        elif total_unrealized < 0:
            lines.append({'account_code': loss_code, 'account_role': 'FX_LOSS',
                          'debit': -total_unrealized, 'credit': Decimal('0.00'),
                          'description': 'خسائر فرق عملة غير محققة'})

        total_debit = sum((ln['debit'] for ln in lines), Decimal('0.00'))
        total_credit = sum((ln['credit'] for ln in lines), Decimal('0.00'))

        return {
            'base_currency': base,
            'as_of': as_of,
            'generated_at': datetime.now(timezone.utc),
            'dry_run': True,
            'per_currency': per_currency,
            'total_unrealized_gain_loss': total_unrealized,
            'lines': lines,
            'total_debit': total_debit,
            'total_credit': total_credit,
            'balanced': abs(total_debit - total_credit) <= Decimal('0.0001'),
            'journal_entry_id': None,
        }

    @staticmethod
    def run_revaluation(rates=None, as_of=None, dry_run=True, created_by=None):
        """تشغيل دورة إعادة التقييم؛ dry_run=True يعيد المسودة فقط دون ترحيل."""
        result = FXRevaluationService.build_revaluation(rates=rates, as_of=as_of)
        if dry_run:
            return result
        return FXRevaluationService.post_revaluation(result, created_by=created_by)

    @staticmethod
    def post_revaluation(result, created_by=None):
        """ترحيل مسودة صالحة عبر GLService.create_manual_entry (يرحّل ويلتزم بنفسه)."""
        from services.gl_service import GLService

        if not result.get('lines'):
            result['dry_run'] = False
            return result
        if not result.get('balanced'):
            raise ValueError('Refusing to post unbalanced FX revaluation entry')

        as_of = result.get('as_of')
        description = 'تسوية أرصدة العملات غير المحققة'
        if as_of is not None:
            description = f'{description} حتى {as_of}'

        entry = GLService.create_manual_entry(
            description=description,
            lines=result['lines'],
            created_by=created_by,
            reference_type=FXRevaluationService.REFERENCE_TYPE,
        )
        result['dry_run'] = False
        result['journal_entry_id'] = entry.id
        return result
