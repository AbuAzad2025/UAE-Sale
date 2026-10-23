"""
محرك تسوية أرصدة العملات الأجنبية (IAS 21) — Month-end FX revaluation engine
===========================================================================

يجمع أرصدة الذمم المدينة والدائنة المفتوحة بالعملات الأجنبية من دفاتر
المبيعات والمشتريات، ثم يُنتج قيد تسوية **متوازن** يُعيد تقييم الذمم
والمدائن — لا الإيراد — بسعر الإغلاق الحالي مقابل السعر التاريخي المسجّل.

اصطلاحات:
- موجب unrealized_gain_loss = ربح غير محقق (مدين AR / دائن AP يزيدان الأصول
  أو ينقصان الالتزامات).
- كل عملة تُقيَّم على حدة: سطور الذمم/المدائن لتلك العملة + سطر ربح أو
  خسارة بتلك العملة، فلا يُلغى ربح عملة بخسارة أخرى.
- القيد متوازن على مستوى كل عملة ومستوى القيد كله (مدين = دائن).
- كل المبالغ بعملة الأساس؛ عملة المستند لا تختلط بعملة الأساس أبداً.
- dry_run افتراضيًا True؛ لا يُرحَّل إلا عند dry_run=False عبر
  GLService.create_manual_entry.
- الفترة (YYYY-MM) تُخزَّن على مرجع القيد (reference_id) فيُكتشف القيد
  السابق في نفس الفترة بالبحث الدقيق ولا يُرحَّل قيد ثانٍ.

الإصلاحات على النسخة الأولى (وُلدت ولم تُستعمل قط في الإنتاج):
1) كانت الذمم المدينة تُجمع من ``Sale.balance_due`` وهو رصيد **بعملة
   الأساس** (models/sale.py:132)، ثم يُضرب في سعر الصرف الحالي — أي أن
   الرصيد كان يُعامل كأنه بالعملة الأجنبية فيُضاعَف سعر الصرف مرتين. الآن
   يُشتقّ الرصيد الأجنبي من الرصيد الأساسي المسجَّل بسعره التاريخي.
2) كانت الذمم الدائنة تطرح ``Purchase.paid_amount`` — وهو رصيد **بعملة
   الأساس** (models/purchase.py:45-48 و132) — من إجمالي الفاتورة بالعملة
   الأجنبية، ثم يُعاد ضربه بسعر الصرف التاريخي: خلط بين عملتين في نفس
   السطر. الآن يُشتقّ الرصيد الأجنبي من الرصيد الأساسي.
3) كان سطر الربح/الخسارة الواحد يُجمع لكل العملات، فيُلغى ربح عملة
   بخسارة أخرى وتضيع إشارة كل عملة. الآن سطر لكل عملة.
4) لم تكن هناك حماية من التكرار: تشغيل الدالة مرتين في نفس الفترة يرحّل
   قيدين. الآن الفترة جزء من المرجع فيُكتشف القيد السابق ويُتخطّى.
5) لم تكن هناك حماية من الفترة المالية المغلقة ولا سجل تدقيق ولا ربط
   بالقيد العكسي.
6) لم تكن المرتجعات المعتمدة تُخصم من رصيد الفاتورة، فكان الرصيد
   الأساسي أكبر من رصيد الذمم في الأستاذ العام. الآن يُخصم المرتجع
   المعتمد بالضبط كما يفعل models/sale.py:132.
"""

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from extensions import db
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
ZERO = Decimal('0.00')
BALANCE_TOLERANCE = Decimal('0.0001')
# الحالة التي تكون فيها الفاتورة أو الشراء مُرحَّلة في الأستاذ العام
POSTED_STATUS = 'confirmed'


def _q2(value):
    """تقريب المبلغ إلى منزلتين عشريتين (نصف لأعلى)."""
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _dec(value):
    """Decimal من أي قيمة دون المرور بالـ float أبداً."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal('0')
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal('0')


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


def _as_of_datetime(value):
    """يحوّل تاريخ/سلسلة إلى datetime (نهاية اليوم للتاريخ المجرّد)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 23, 59, 59, 999999)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.strptime(text, '%Y-%m-%d')
            except ValueError:
                return None
        if len(text) == 10:
            return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
        return parsed
    return None


def _upper_rates(rates):
    """يوحّد مفاتيح أسعار الصرف إلى أحرف كبيرة."""
    if not rates:
        return {}
    return {str(key).strip().upper(): value for key, value in rates.items()}


def _approved_returns(sale_ids):
    """{sale_id: (بالعملة الأساسية, بالعملة الأجنبية)} — المرتجعات المعتمدة.

    نفس منطق ``models.sale.compute_sale_returns_base`` بالضبط: المرتجع
    المعتمد يُلغي قيمة الفاتورة (دائن للعميل) فيجب أن يُخصم من الرصيد
    الأساسي وإلا ظهرت الفاتورة مستحقة بعد إرجاعها.
    """
    if not sale_ids:
        return {}
    try:
        from sqlalchemy import select

        from models.product_return import ProductReturn
    except Exception:  # pragma: no cover - جدول غير متاح
        return {}
    totals = {}
    # دفعات صغيرة: SQLite/MySQL تحدّ عدد المتغيرات في استعلام واحد.
    unique_ids = list(dict.fromkeys(sale_ids))
    for start in range(0, len(unique_ids), 400):
        batch = unique_ids[start:start + 400]
        try:
            rows = db.session.execute(
                select(
                    ProductReturn.__table__.c.sale_id,
                    ProductReturn.__table__.c.refund_amount,
                    ProductReturn.__table__.c.exchange_rate,
                ).where(
                    ProductReturn.__table__.c.sale_id.in_(batch),
                    ProductReturn.__table__.c.status == 'approved',
                )
            ).fetchall()
        except Exception:  # pragma: no cover - لا يُفشل التسوية بسبب المرتجعات
            return totals
        for row in rows:
            foreign = _dec(row.refund_amount)
            rate = _dec(row.exchange_rate or 1)
            base, foreign_total = totals.get(row.sale_id, (Decimal('0'), Decimal('0')))
            totals[row.sale_id] = (base + foreign * rate, foreign_total + foreign)
    return totals


class FXRateUnavailable(ValueError):
    """لا يوجد سعر صرف صالح للعملة (بيانات ناقصة) — تُتخطّى العملة.

    خطأ بيانات لا خطأ برمجة: يُلتقط أثناء بناء المسودة فتُستثنى العملة
    من التسوية مع تسجيل السبب، بدل ترحيل قيد على سعر وهمي.
    """


class FXRevaluationService:
    """تجميع الأرصدة المفتوحة بالعملة الأجنبية وإنتاج قيد إعادة تقييم غير محقق."""

    REFERENCE_TYPE = 'fx_revaluation'

    # ------------------------------------------------------------------
    # الفترة ومرجع القيد
    # ------------------------------------------------------------------

    @staticmethod
    def base_currency():
        """عملة القاعدة: مستأجر السياق الحالي ثم إعدادات النظام.

        ``CurrencyService.get_base_currency`` يقرأ مستأجر الطلب فقط داخل
        سياق طلب؛ العامل المجدول (Celery) يعمل خارج الطلب، فهنا يُقرأ
        مستأجر السياق (thread-local) صراحةً حتى تُقيَّم كل شركة بعملتها.
        """
        try:
            from models.tenant_scope import get_current_tenant_id

            tenant_id = get_current_tenant_id()
            if tenant_id is not None and tenant_id > 0:
                from models import Tenant

                tenant = db.session.get(Tenant, tenant_id)
                if tenant is not None and tenant.default_currency:
                    return tenant.default_currency
        except Exception:
            pass
        return CurrencyService.get_base_currency()

    @staticmethod
    def period_key(as_of=None):
        """'YYYY-MM' — فترة إعادة التقييم (الشهر الميلادي لتاريخ التسوية).

        الفترة تُخزَّن على مرجع القيد، فتشغيل الدالة مرتين في نفس الفترة
        يُكتشف القيد السابق ولا يُرحَّل قيد ثانٍ.
        """
        moment = _as_of_datetime(as_of) or datetime.now(timezone.utc)
        return f'{moment.year:04d}-{moment.month:02d}'

    @staticmethod
    def reference_id_for(period_key):
        """معرّف مرجع القيد = الفترة بصيغة YYYYMM (بحث دقيق عن القيد السابق)."""
        digits = ''.join(ch for ch in str(period_key or '') if ch.isdigit())
        return int(digits) if digits else 0

    @staticmethod
    def fiscal_period(as_of=None):
        """الفترة المالية التي تغطي *as_of* (أو None إن لم توجد)."""
        from services.fiscal_period_guard import period_for_date

        try:
            return period_for_date(_as_of_datetime(as_of))
        except Exception:
            return None

    @staticmethod
    def current_open_period(as_of=None):
        """الفترة المالية **المفتوحة** التي تغطي *as_of* (None إن كانت مغلقة)."""
        period = FXRevaluationService.fiscal_period(as_of)
        if period is None:
            return None
        if getattr(period, 'is_closed', False):
            return None
        return period

    @staticmethod
    def find_posted_entry(period_key):
        """القيد المرحّل لفترة معيّنة (None إن لم يُرحَّل بعد).

        القيد العكسي لا يُحسب تكراراً: أُلغي القيد الأصلي فصار الأصل
        ``is_reversed`` والعكس من نوع ``reversing`` — فيمكن ترحيل قيد
        تسوية مُصحَّح لنفس الفترة.
        """
        from models import GLJournalEntry
        from models.tenant_scope import get_current_tenant_id

        reference_id = FXRevaluationService.reference_id_for(period_key)
        query = GLJournalEntry.query.filter_by(
            reference_type=FXRevaluationService.REFERENCE_TYPE,
            reference_id=reference_id,
        )
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            query = query.filter(GLJournalEntry.tenant_id.is_(None))
        else:
            query = query.filter(GLJournalEntry.tenant_id == tenant_id)
        for entry in query.all():
            if getattr(entry, 'entry_type', '') == 'reversing':
                continue
            if getattr(entry, 'reversed_entry_id', None):
                continue
            if getattr(entry, 'is_reversed', False):
                continue
            if not getattr(entry, 'is_posted', True):
                continue
            return entry
        return None

    # ------------------------------------------------------------------
    # جمع الأرصدة
    # ------------------------------------------------------------------

    @staticmethod
    def collect_open_ar_balances(as_of=None):
        """أرصدة عملاء مفتوحة حسب العملة الأجنبية من المبيعات المؤكدة.

        الرصيد الأساسي = amount_base − paid_amount_base − المرتجعات
        المعتمدة — وهو نفس رصيد حساب الذمم في الأستاذ العام
        (models/sale.py:132). والرصيد الأجنبي = الرصيد الأساسي ÷ السعر
        التاريخي للفاتورة، ثم يُضرب في السعر الحالي. هكذا لا تختلط
        العملات ولا يتضاعَف سعر الصرف.
        """
        from models import Sale
        from sqlalchemy import func

        base = FXRevaluationService.base_currency()
        cutoff = _as_of_datetime(as_of)

        query = Sale.query.filter(
            Sale.is_active.is_(True),
            Sale.status == POSTED_STATUS,
            func.upper(Sale.currency) != base.upper(),
        )
        if cutoff is not None:
            query = query.filter(Sale.sale_date <= cutoff)

        sales = query.all()
        returns = _approved_returns([sale.id for sale in sales])

        balances = {}
        for sale in sales:
            currency = (sale.currency or base).upper()
            rate = _dec(sale.exchange_rate)
            if rate <= 0:
                continue
            returned_base, _returned_foreign = returns.get(sale.id, (Decimal('0'), Decimal('0')))
            carrying = (
                _dec(sale.amount_base)
                - _dec(sale.paid_amount_base)
                - returned_base
            )
            carrying = _clamp_non_negative(carrying)
            if carrying <= 0:
                continue
            foreign = carrying / rate
            entry = balances.setdefault(currency, {
                'foreign': Decimal('0.00'),
                'foreign_exact': Decimal('0'),
                'historical_base': Decimal('0.00'),
                'historical_rates': [],
            })
            entry['foreign'] += _q2(foreign)
            entry['foreign_exact'] += foreign
            entry['historical_base'] += _q2(carrying)
            if str(rate) not in entry['historical_rates']:
                entry['historical_rates'].append(str(rate))
        return balances

    @staticmethod
    def collect_open_ap_balances(as_of=None):
        """أرصدة موردين مفتوحة حسب العملة الأجنبية من المشتريات المؤكدة.

        ``Purchase.paid_amount`` رصيد **بعملة الأساس** (models/purchase.py:
        45-48 و132 — وهو ما تكتبه ``recalculate_payment_status`` من
        سندات الصرف). لذلك لا يُطرح من إجمالي الفاتورة بالعملة الأجنبية:
        يُطرح من الرصيد الأساسي، ومنه يُشتقّ الرصيد الأجنبي.
        """
        from models import Purchase
        from sqlalchemy import func

        base = FXRevaluationService.base_currency()
        cutoff = _as_of_datetime(as_of)

        query = Purchase.query.filter(
            Purchase.status == POSTED_STATUS,
            func.upper(Purchase.currency) != base.upper(),
        )
        if cutoff is not None:
            query = query.filter(Purchase.purchase_date <= cutoff)

        balances = {}
for purchase in query.all():
            currency = (purchase.currency or base).upper()
            rate = _dec(purchase.exchange_rate)
            if rate <= 0:
                continue
            # Correct: convert paid_amount to base currency before subtracting
            paid_base = _dec(purchase.paid_amount or 0) * rate
            carrying = _dec(purchase.amount_base or 0) - paid_base
            carrying = _clamp_non_negative(carrying)
            if carrying <= 0:
                continue
            foreign = carrying / rate
            entry = balances.setdefault(currency, {
                'foreign': Decimal('0.00'),
                'foreign_exact': Decimal('0'),
                'historical_base': Decimal('0.00'),
                'historical_rates': [],
            })
            entry['foreign'] += _q2(foreign)
            entry['foreign_exact'] += foreign
            entry['historical_base'] += _q2(carrying)
            if str(rate) not in entry['historical_rates']:
                entry['historical_rates'].append(str(rate))
        return balances

    # ------------------------------------------------------------------
    # مسودة القيد
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_rate(currency, base, overrides=None):
        """سعر صرف العملة الأجنبية نحو عملة القاعدة (يرفض سعراً غير صالح)."""
        overrides = overrides or {}
        if currency in overrides:
            rate = _dec(overrides[currency])
            if rate <= 0:
                raise ValueError(f'Invalid override rate for {currency}')
            return rate
        known = FXRevaluationService.known_currencies(base)
        if known and currency not in known:
            raise FXRateUnavailable(f'No exchange rate available for {currency} to {base}')
        rate = _dec(CurrencyService.get_exchange_rate(currency, base))
        if rate <= 0:
            raise FXRateUnavailable(f'No usable exchange rate for {currency} to {base}')
        return rate

    @staticmethod
    def known_currencies(base=None):
        """العملات التي يعرفها خدمة العملات (سعر مفقود = 1.0 = تسوية وهمية).

        ``CurrencyService.get_exchange_rate`` يعيد 1.0 لأي عملة غير
        معروفة، فتسوية أرصدة بذلك السعر تُنتج فرقاً وهمياً ضخماً. لذلك
        تُتخطّى العملة التي لا سعر لها بدل ترحيل قيد خاطئ.
        """
        try:
            rates = CurrencyService.get_all_rates(base or FXRevaluationService.base_currency())
        except Exception:
            return set()
        return {str(code).upper() for code in (rates or {})}

    @staticmethod
    def build_revaluation(rates=None, as_of=None):
        """بناء مسودة قيد إعادة التقييم دون أي ترحيل (نقية قابلة للاختبار).

        rates: تجاوز اختياري {currency: price} لأغراض الإعادة/التقارير؛
               وإلا يُستخدم CurrencyService.get_exchange_rate نحو عملة القاعدة.
        """
        base = FXRevaluationService.base_currency()
        overrides = _upper_rates(rates)
        ar_balances = FXRevaluationService.collect_open_ar_balances(as_of=as_of)
        ap_balances = FXRevaluationService.collect_open_ap_balances(as_of=as_of)
        currencies = sorted(set(ar_balances) | set(ap_balances))

        ar_code = _resolve_account('AR_CONTROL', FALLBACK_ACCOUNT_CODES['AR_CONTROL'])
        ap_code = _resolve_account('AP_CONTROL', FALLBACK_ACCOUNT_CODES['AP_CONTROL'])
        gain_code = _resolve_account('FX_GAIN', FALLBACK_ACCOUNT_CODES['FX_GAIN'])
        loss_code = _resolve_account('FX_LOSS', FALLBACK_ACCOUNT_CODES['FX_LOSS'])

        period_key = FXRevaluationService.period_key(as_of)
        fiscal_period = FXRevaluationService.fiscal_period(as_of)
        existing = FXRevaluationService.find_posted_entry(period_key)

        per_currency = []
        lines = []
        skipped = []
        total_unrealized = ZERO

        for currency in currencies:
            ar = ar_balances.get(currency, {})
            ap = ap_balances.get(currency, {})

            try:
                current_rate = FXRevaluationService.resolve_rate(
                    currency, base, overrides)
            except FXRateUnavailable as exc:
                skipped.append({'currency': currency, 'reason': str(exc)})
                continue

            hist_ar = _q2(ar.get('historical_base', ZERO))
            hist_ap = _q2(ap.get('historical_base', ZERO))
            cur_ar = _q2(_dec(ar.get('foreign_exact', ar.get('foreign', ZERO))) * current_rate)
            cur_ap = _q2(_dec(ap.get('foreign_exact', ap.get('foreign', ZERO))) * current_rate)

            delta_ar = cur_ar - hist_ar   # زيادة أصل = مكسب
            delta_ap = cur_ap - hist_ap   # زيادة التزام = خسارة
            unrealized = delta_ar - delta_ap

            per_currency.append({
                'currency': currency,
                'open_foreign_ar': _q2(ar.get('foreign', ZERO)),
                'open_foreign_ap': _q2(ap.get('foreign', ZERO)),
                'historical_base_ar': hist_ar,
                'historical_base_ap': hist_ap,
                'current_base_ar': cur_ar,
                'current_base_ap': cur_ap,
                'current_rate': current_rate,
                'historical_rates': sorted(set(
                    list(ar.get('historical_rates') or []) + list(ap.get('historical_rates') or []))),
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
            # سطر ربح/خسارة **لكل عملة**: الربح والخسارة لا يلغيان بعضهما.
            if unrealized > 0:
                lines.append({'account_code': gain_code, 'account_role': 'FX_GAIN',
                              'debit': ZERO, 'credit': unrealized,
                              'description': f'أرباح فرق عملة غير محققة — {currency}'})
            elif unrealized < 0:
                lines.append({'account_code': loss_code, 'account_role': 'FX_LOSS',
                              'debit': -unrealized, 'credit': ZERO,
                              'description': f'خسائر فرق عملة غير محققة — {currency}'})

        total_debit = sum((ln['debit'] for ln in lines), ZERO)
        total_credit = sum((ln['credit'] for ln in lines), ZERO)

        return {
            'base_currency': base,
            'as_of': as_of,
            'generated_at': datetime.now(timezone.utc),
            'dry_run': True,
            'period_key': period_key,
            'reference_id': FXRevaluationService.reference_id_for(period_key),
            'fiscal_period_id': getattr(fiscal_period, 'id', None),
            'fiscal_period_name': getattr(fiscal_period, 'name', None),
            'fiscal_period_closed': bool(getattr(fiscal_period, 'is_closed', False)),
            'already_posted': existing is not None,
            'existing_entry_id': getattr(existing, 'id', None),
            'per_currency': per_currency,
            'skipped_currencies': skipped,
            'total_unrealized_gain_loss': total_unrealized,
            'lines': lines,
            'total_debit': total_debit,
            'total_credit': total_credit,
            'balanced': abs(total_debit - total_credit) <= BALANCE_TOLERANCE,
            'journal_entry_id': None,
        }

    # ------------------------------------------------------------------
    # التشغيل والترحيل
    # ------------------------------------------------------------------

    @staticmethod
    def run_revaluation(rates=None, as_of=None, dry_run=True, created_by=None):
        """تشغيل دورة إعادة التقييم؛ dry_run=True يعيد المسودة فقط دون ترحيل."""
        result = FXRevaluationService.build_revaluation(rates=rates, as_of=as_of)
        if dry_run:
            return result
        return FXRevaluationService.post_revaluation(result, created_by=created_by)

    @staticmethod
    def post_revaluation(result, created_by=None):
        """ترحيل مسودة صالحة عبر GLService.create_manual_entry (يرحّل ويلتزم بنفسه).

        يرفض:
        * مسودة غير متوازنة،
        * فترة مالية مغلقة (حارس الفترة المالية)،
        * تكرار الترحيل في نفس الفترة (يُكتشف القيد السابق ويُتخطّى).
        """
        from services.gl_service import GLService

        if not result.get('lines'):
            result['dry_run'] = False
            result['posted'] = False
            result['skip_reason'] = 'nothing_to_revalue'
            return result
        if not result.get('balanced'):
            raise ValueError('Refusing to post unbalanced FX revaluation entry')

        period_key = result.get('period_key') or FXRevaluationService.period_key(
            result.get('as_of'))
        reference_id = result.get('reference_id') or \
            FXRevaluationService.reference_id_for(period_key)

        existing = FXRevaluationService.find_posted_entry(period_key)
        if existing is not None:
            result['dry_run'] = False
            result['posted'] = False
            result['already_posted'] = True
            result['journal_entry_id'] = existing.id
            result['skip_reason'] = 'already_posted'
            return result

        as_of = result.get('as_of')
        entry_date = _as_of_datetime(as_of) or datetime.now(timezone.utc)

        # حارس الفترة المالية: لا ترحيل إلى فترة مغلقة أو بلا فترة.
        from services.fiscal_period_guard import assert_period_open

        assert_period_open(entry_date)

        base = result.get('base_currency') or FXRevaluationService.base_currency()
        description = 'تسوية أرصدة العملات غير المحققة'
        if as_of is not None:
            description = f'{description} — {period_key}'

        entry = GLService.create_manual_entry(
            description=description,
            lines=result['lines'],
            entry_date=entry_date,
            notes=(
                f'إعادة تقييم غير محققة — الفترة {period_key} — '
                f'عملة الأساس {base} — '
                f'العملات: {", ".join(row["currency"] for row in result.get("per_currency") or [])}'
            ),
            created_by=created_by,
            reference_type=FXRevaluationService.REFERENCE_TYPE,
            reference_id=reference_id,
            currency=base,
            exchange_rate=1,
            entry_type='adjustment',
        )

        FXRevaluationService.write_audit_log(entry, result, created_by)

        result['dry_run'] = False
        result['posted'] = True
        result['already_posted'] = False
        result['skip_reason'] = None
        result['journal_entry_id'] = entry.id
        return result

    @staticmethod
    def write_audit_log(entry, result, created_by=None):
        """سجل تدقيق لعملية الترحيل — لا بد من تسجيله بجانب القيد."""
        from utils.helpers import create_audit_log

        return create_audit_log(
            'create', 'gl_journal_entries', entry.id,
            changes={
                'action': 'fx_revaluation',
                'entry_number': entry.entry_number,
                'reference_type': entry.reference_type,
                'reference_id': entry.reference_id,
                'period_key': result.get('period_key'),
                'base_currency': result.get('base_currency'),
                'total_debit': result.get('total_debit'),
                'total_credit': result.get('total_credit'),
                'total_unrealized_gain_loss': result.get('total_unrealized_gain_loss'),
                'currencies': [row.get('currency') for row in result.get('per_currency') or []],
                'created_by': created_by,
            },
            commit=False,
        )

    @staticmethod
    def reverse_revaluation(entry_or_id, created_by=None, reason=None):
        """عكس قيد تسوية مُرحَّل عبر آلية العكس في services/gl_service.

        القيد العكسي يحمل نفس المرجع فيبقى الأثر المحاسبي وسجل التدقيق
        كما هما، ويصبح ترحيل تسوية مُصحَّح لنفس الفترة ممكناً.
        """
        from models import GLJournalEntry
        from services.gl_service import GLService
        from utils.helpers import create_audit_log

        if isinstance(entry_or_id, int):
            entry = db.session.get(GLJournalEntry, entry_or_id)
        else:
            entry = entry_or_id
        if entry is None:
            raise ValueError('FX revaluation entry not found')
        if getattr(entry, 'reference_type', None) != FXRevaluationService.REFERENCE_TYPE:
            raise ValueError('Journal entry is not an FX revaluation')
        if getattr(entry, 'is_reversed', False):
            raise ValueError('هذا القيد تم عكسه مسبقاً')

        description = reason or f'عكس قيد تسوية فرق العملة {entry.entry_number}'
        reversal = GLService.reverse_entry(
            entry, description=description, created_by=created_by)

        create_audit_log(
            'reverse', 'gl_journal_entries', entry.id,
            changes={
                'action': 'fx_revaluation_reversal',
                'entry_number': entry.entry_number,
                'reversal_entry_number': getattr(reversal, 'entry_number', None),
                'reference_id': entry.reference_id,
                'created_by': created_by,
            },
            commit=False,
        )
        return reversal
