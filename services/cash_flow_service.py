"""
خدمة قائمة التدفقات النقدية - Cash Flow Statement Service

مصدر واحد لقائمة التدفقات النقدية:
  • CashFlowService.generate_gl_cash_flow() — قائمة التدفقات من دفتر الأستاذ
    (GL). هذه هي القائمة المعروضة في صفحة دفتر الأستاذ وصفحة التقارير وفي
    ملفات التصدير، فتتطابق الأرقام في الثلاثة.
  • CashFlowService.generate_cash_flow() — النسخة القديمة المبنية على
    جداول التشغيل (المقبوضات/المدفوعات/المصروفات). أُبقيت للتوافق مع
    المستهلكين الخارجيين فقط، ولا تُستخدم في أي صفحة؛ وكل مبالغها
    محوّرة إلى عملة الأساس.

F4: لا أكواد حسابات ثابتة في هذه الخدمة. كل حساب يُطلب بدوره
(AccountRole) من services/account_resolution.py فيُرَجَع الكود الذي
يستخدمه دليل الحسابات فعلاً في هذه المنشأة/المستأجر.

رصيد النقدية في نهاية الفترة حقيقة تُقرأ من دفتر الأستاذ، لا رقم يُستنتج
من جمع الأقسام: ``cash_ending`` يقرأ من الدفتر، و``cash_ending_computed``
هو الناتج الحسابي (البداية + صافي التغير)، و``tie_out`` يفصل بينهما ويعلن
الفرق. القائمة لا تستطيع أن تخفي اختلافاً بين الدفتر وحسابها.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime
from types import SimpleNamespace
from sqlalchemy import func, and_
from extensions import db
from models import (
    GLAccount, GLJournalEntry, GLJournalLine,
    Payment, Receipt, Expense
)


# ---------------------------------------------------------------------------
# F4 — الأدوار المحاسبية (AccountRole) التي تستعملها قائمة التدفقات النقدية
# ---------------------------------------------------------------------------
# كل سطر يوثّق: الكود القديم ← دوره المحاسبي في DEFAULT_ROLE_MAP.
#   '1110' ← CASH           الصندوق
#   '1120' ← BANK           البنك - حساب جاري
#   '6100' ← SALARY_EXPENSE رواتب وأجور
#   '3100' ← CAPITAL        رأس المال
#   '3300' ← OWNER_DRAWS    جاري المالك
#   '2210' ← LOANS          قروض
#   '1210'..'1250' ← LAND / BUILDINGS / VEHICLES / EQUIPMENT / FURNITURE
#                      (الأصول الثابتة — كانت تُلتقط بالبادئة '12%')
#
# كل هذه الأدوار موجودة في AccountRole (services/account_resolution.py)،
# فلا يوجد كود بلا دور مقابل.
CASH_FLOW_ROLE_MAP = {
    'CASH': 'CASH',
    'BANK': 'BANK',
    'SALARY_EXPENSE': 'SALARY_EXPENSE',
    'CAPITAL': 'CAPITAL',
    'OWNER_DRAWS': 'OWNER_DRAWS',
    'LOANS': 'LOANS',
}

# الأدوار التي تمثّل الأصول الثابتة (كانت تُلتقط بالبادئة '12%').
FIXED_ASSET_ROLES = ('LAND', 'BUILDINGS', 'VEHICLES', 'EQUIPMENT', 'FURNITURE')

# دقّة النقود المعروضة في القائمة: الموازنة بين رصيد الدفتر والرصيد
# المحسوب تُحكم على الفرق بعد تقريبه إلى منزلتين — فارق أصغر من نصف
# قرش فرق عرضٍ لا فرق حقيقي.
MONEY_PRECISION = Decimal('0.01')


def _parse_date(value):
    """تحويل تاريخ (نص/date/datetime) إلى date، أو None لبلا حدّ."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return datetime.strptime(text, '%Y-%m-%d').date()
    raise ValueError(f'Unsupported date value for the cash flow statement: {value!r}')


def _current_tenant_id():
    """معرّف المستأجر الحالي (None = بلا سياق مستأجر)."""
    try:
        from models.tenant_scope import get_current_tenant_id

        return get_current_tenant_id()
    except Exception:
        return None


def resolve_cash_flow_accounts(tenant_id=None):
    """ترميز أدوار قائمة التدفقات النقدية إلى أكواد الحسابات الحيّة.

    يستعمل AccountResolver (مصدر واحد لأكواد الحسابات) فيستطيع المستأجر
    الذي remap حساباً من دليل الحسابات أن يرى Statement صحيحة.
    """
    from services.account_resolution import AccountResolver, AccountRole

    if tenant_id is None:
        tenant_id = _current_tenant_id()

    roles = list(CASH_FLOW_ROLE_MAP.values()) + list(FIXED_ASSET_ROLES)
    codes = AccountResolver.resolve_codes(*roles, tenant_id=tenant_id)
    resolved = {
        name: codes[AccountRole[role].value]
        for name, role in CASH_FLOW_ROLE_MAP.items()
    }
    resolved['FIXED_ASSETS'] = [codes[AccountRole[r].value] for r in FIXED_ASSET_ROLES]
    return resolved


class CashFlowService:

    # F4: حسابات النقدية (الصندوق + البنك) لا تُثبَّت هنا — تُحلّ عبر
    # AccountResolver في كل استدعاء (see cash_account_codes()).

    # تسميات أقسام قائمة التدفقات (تستخدمها الشاشة والتصدير معاً)
    SECTION_LABELS = {
        'operating': 'تشغيلي',
        'investing': 'استثماري',
        'financing': 'تمويلي',
    }

    @staticmethod
    def cash_account_codes(tenant_id=None):
        """أكواد حسابات النقدية (الصندوق + البنك) عبر AccountResolver."""
        resolved = resolve_cash_flow_accounts(tenant_id=tenant_id)
        return (resolved['CASH'], resolved['BANK'])

    @staticmethod
    def account_code(role_name, tenant_id=None):
        """كود حساب واحد عبر AccountResolver (يرجع الكود الحيّ للدور)."""
        resolved = resolve_cash_flow_accounts(tenant_id=tenant_id)
        return resolved[role_name]

    @staticmethod
    def _dec(value):
        """تحويل آمن لأي نتيجة تجميع (Decimal/float/None) إلى Decimal —
        SQLite يعيد float من func.sum بينما PostgreSQL يعيد Decimal."""
        if value is None:
            return Decimal('0')
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @staticmethod
    def _gl_base_expressions():
        """تعبيرات المبالغ بعملة الأساس — نفس مصدر القوائم المالية.

        استيراد كسول (داخل الدالة) لتفادي الاستيراد الدائري، لأن
        routes/ledger.py يستورد هذه الخدمة على مستوى الوحدة.
        """
        from routes.ledger import (
            _gl_base_credit_expression,
            _gl_base_debit_expression,
            _gl_signed_base_expression,
        )
        return (
            _gl_base_debit_expression(),
            _gl_base_credit_expression(),
            _gl_signed_base_expression(),
        )

    @staticmethod
    def classify_account(account_type):
        """تصنيف الحساب في أقسام قائمة التدفقات حسب طبيعته.

        لا تعتمد على بادئة الكود: كل حساب ينتمي لقسم واحد دائماً، فلا
        تختفي أي حركة من القائمة (بادئة الكود كانت تُسقط أي أصل لا يبدأ
        بـ '1').
        """
        if account_type in ('revenue', 'expense'):
            return 'operating'
        if account_type == 'asset':
            return 'investing'
        if account_type in ('liability', 'equity'):
            return 'financing'
        # أنواع غير معروفة تُعامل كتشغيلي حتى لا تختفي حركتها
        return 'operating'

    @staticmethod
    def _section_amount(account_type, net_base):
        """أثر حركة الحساب على النقدية (بالإشارة المتوافقة مع القسم).

        حركة أي حساب تقابل حركة نقدية معاكسة، فهذا هو التوقيع الصحيح
        لقائمة التدفقات النقدية:
          • أصل (أصول ثابتة/مخزون): زيادته (مدين) خروج نقدي ⇒ سالب،
            ونقصانه (دائن) دخول نقدي ⇒ موجب.
          • إيراد: دائن = بيع = دخول نقدي ⇒ موجب؛ مدين (مرتجع) ⇒ سالب.
          • مصروف: مدين = صرف = خروج نقدي ⇒ سالب؛ دائن ⇒ موجب.
          • خصم/حقوق ملكية: زيادتها (دائن) دخول نقدي ⇒ موجب.

        (``account_type`` يحدّد القسم لا الإشارة — انظر classify_account.)
        """
        return -net_base

    @staticmethod
    def _cash_account_ids():
        """معرّفات حسابات النقدية الحيّة (الصندوق + البنك) بعد حلّ الأدوار."""
        codes = list(CashFlowService.cash_account_codes())
        if not codes:
            return []
        return [
            acc.id for acc in GLAccount.query.filter(
                GLAccount.code.in_(codes)
            ).all()
        ]

    @staticmethod
    def _tie_out(gl_cash_ending, computed_ending):
        """مطابقة رصيد النقدية في نهاية الفترة: الحقيقة من الدفتر مقابل المحسوب.

        ``difference`` = رصيد الدفتر − الرصيد المحسوب، و``balanced`` تُعلن
        هل الفرق صفر (بعد تقريبه إلى دقّة النقود المعروضة) أم لا. الفرق
        لا يُخفى ولا يُسوّى — يُعرض.
        """
        gl_balance = CashFlowService._dec(gl_cash_ending)
        computed = CashFlowService._dec(computed_ending)
        difference = gl_balance - computed
        return {
            'gl_cash_ending': gl_balance,
            'computed_ending': computed,
            'difference': difference,
            'balanced': difference.quantize(
                MONEY_PRECISION, rounding=ROUND_HALF_UP) == Decimal('0'),
        }

    @staticmethod
    def _fiscal_period_facts(period_start, period_end):
        """حالة الفترة المالية للفترة المطلوبة + صحة المدى الزمني.

        القائمة تُقرأ عن فترات مغلقة أيضاً (تقرير تاريخي)، فليس رفضُ
        الفترة المغلقة هو السلوك الصحيح هنا — لكن يجب أن تُعرف حالتها
        وأن يُعلَن المدى غير الصالح بدل ابتلاعه.

        Uses services/fiscal_period_guard.py (the single period contract).
        """
        from services.fiscal_period_guard import period_for_date

        range_valid = True
        if period_start is not None and period_end is not None:
            range_valid = period_start <= period_end

        period = period_for_date(period_end or period_start)
        is_closed = bool(getattr(period, 'is_closed', False)) if period else False
        return {
            'defined': period is not None,
            'is_open': period is not None and not is_closed,
            'is_closed': is_closed,
            'range_valid': range_valid,
        }

    @staticmethod
    def generate_gl_cash_flow(period_start, period_end):
        """قائمة التدفقات النقدية من دفتر الأستاذ — المصدر الوحيد.

        Args:
            period_start: تاريخ البداية (date أو string) — None = بلا حدّ
            period_end: تاريخ النهاية (date أو string) — None = بلا حدّ

        Returns:
            dict: قائمة التدفقات النقدية الكاملة:
                • operating_items/investing_items/financing_items: بنود
                  الأقسام الثلاثة، وoperating_total/investing_total/
                  financing_total: إجمالياتها.
                • net_change: صافي التغير في النقدية (مجموع الأقسام).
                • cash_beginning: رصيد النقدية في بداية الفترة (من الدفتر).
                • cash_ending: رصيد النقدية في نهاية الفترة — حقيقة من
                  دفتر الأستاذ (لا رقم مستنتج).
                • cash_ending_computed: الرصيد نفسه محسوباً
                  (cash_beginning + net_change) — للمطابقة فقط.
                • tie_out: {'gl_cash_ending', 'computed_ending',
                  'difference', 'balanced'} — الفرق يُعلن ولا يُخفى.
                • fiscal_period: حالة الفترة المالية وصحة المدى الزمني.
                • rows: صفوف التصدير.

        ملاحظة المحاسبة: الأقسام تُبنى من الحسابات المقابلة للنقدية
        (طريقة غير مباشرة) — حسابات النقدية نفسها (الصندوق/البنك) هي
        موضوع القائمة فلا تُحتسب بنداً فيها، وإلا احتُسبت حركة النقدية
        مرتين. وإشارات الأقسام تُشتق من أثر الحركة على النقدية (انظر
        ``_section_amount``).
        """

        period_start = _parse_date(period_start)
        period_end = _parse_date(period_end)

        from datetime import time as _time
        period_end_dt = (datetime.combine(period_end, _time.max)
                         if period_end is not None else None)
        period_start_dt = (datetime.combine(period_start, _time.min)
                            if period_start is not None else None)

        base_debit, base_credit, signed_base = CashFlowService._gl_base_expressions()

        # القيود المرحّلة فقط. القيد المعكوس (is_reversed=True) وقيده العاكس
        # (is_reversed=False) يُدرجان معاً فيلغي أثرهما الصافي — استبعاد
        # الأصلي وحده كان يُظهر القيد العاكس بلا أصله.
        query = (
            db.session.query(
                GLJournalLine.account_id.label('account_id'),
                GLAccount.type.label('account_type'),
                GLAccount.code.label('account_code'),
                GLAccount.name.label('account_name'),
                GLAccount.name_ar.label('account_name_ar'),
                func.sum(signed_base).label('net_base'),
                func.sum(base_debit).label('debit_base'),
                func.sum(base_credit).label('credit_base'),
            )
            .select_from(GLJournalLine)
            .join(GLJournalEntry, GLJournalLine.entry_id == GLJournalEntry.id)
            .join(GLAccount, GLJournalLine.account_id == GLAccount.id)
            .filter(GLJournalEntry.is_posted.is_(True))
        )
        if period_start_dt is not None:
            query = query.filter(GLJournalEntry.entry_date >= period_start_dt)
        if period_end_dt is not None:
            query = query.filter(GLJournalEntry.entry_date <= period_end_dt)

        rows = query.group_by(
            GLJournalLine.account_id,
            GLAccount.type,
            GLAccount.code,
            GLAccount.name,
            GLAccount.name_ar,
        ).all()

        sections = {'operating': {}, 'investing': {}, 'financing': {}}
        export_rows = []

        cash_account_ids = CashFlowService._cash_account_ids()
        cash_account_id_set = set(cash_account_ids)

        for row in rows:
            # حسابات النقدية هي موضوع القائمة لا بنود فيها: حركة النقدية
            # هي "صافي التغير" نفسه، فلا تُحتسب مرتين.
            if row.account_id in cash_account_id_set:
                continue

            account_type = row.account_type
            section = CashFlowService.classify_account(account_type)
            net_base = CashFlowService._dec(row.net_base)
            amount = CashFlowService._section_amount(account_type, net_base)
            if amount == 0:
                continue

            label = f"{row.account_code} - {row.account_name_ar or row.account_name}"
            sections[section][label] = sections[section].get(label, Decimal('0')) + amount

            export_rows.append({
                'section': section,
                'section_label': CashFlowService.SECTION_LABELS[section],
                'code': row.account_code,
                'name': row.account_name_ar or row.account_name,
                'label': label,
                'debit': CashFlowService._dec(row.debit_base),
                'credit': CashFlowService._dec(row.credit_base),
                'net': amount,
            })

        operating_total = sum(sections['operating'].values(), Decimal('0'))
        investing_total = sum(sections['investing'].values(), Decimal('0'))
        financing_total = sum(sections['financing'].values(), Decimal('0'))
        net_change = operating_total + investing_total + financing_total

        cash_account_ids = list(cash_account_ids)
        # رصيد النقدية قبل بداية الفترة (أو قبل أول حركة إن لم تُحدَّد فترة)
        opening_cutoff = period_start_dt or datetime(1900, 1, 1)
        cash_beginning = CashFlowService._gl_cash_balance(
            cash_account_ids, opening_cutoff, is_beginning=True)
        # رصيد النقدية في نهاية الفترة — حقيقة من دفتر الأستاذ.
        cash_ending = CashFlowService._gl_cash_balance(
            cash_account_ids, period_end_dt, is_beginning=False)
        # الرقم المحسوب (البداية + صافي التغير) — للمطابقة فقط.
        cash_ending_computed = cash_beginning + net_change
        tie_out = CashFlowService._tie_out(cash_ending, cash_ending_computed)

        return {
            'period_start': period_start,
            'period_end': period_end,
            'operating_items': sections['operating'],
            'investing_items': sections['investing'],
            'financing_items': sections['financing'],
            'operating_total': operating_total,
            'investing_total': investing_total,
            'financing_total': financing_total,
            'net_change': net_change,
            'cash_beginning': cash_beginning,
            'cash_ending': cash_ending,
            'cash_ending_computed': cash_ending_computed,
            'tie_out': tie_out,
            'fiscal_period': CashFlowService._fiscal_period_facts(
                period_start, period_end),
            'rows': export_rows,
        }

    @staticmethod
    def _gl_cash_balance(account_ids, target_date, is_beginning=False):
        """رصيد حسابات النقدية بعملة الأساس حتى تاريخ محدد.

        ``target_date`` = None يعني بلا حدّ (كل القيود المرحّلة).
        """
        if not account_ids:
            return Decimal('0')

        base_debit, base_credit, _ = CashFlowService._gl_base_expressions()

        query = (
            db.session.query(
                func.sum(base_debit),
                func.sum(base_credit),
            )
            .select_from(GLJournalLine)
            .join(GLJournalEntry, GLJournalLine.entry_id == GLJournalEntry.id)
            .filter(GLJournalLine.account_id.in_(account_ids))
            .filter(GLJournalEntry.is_posted.is_(True))
        )
        if is_beginning:
            if target_date is not None:
                query = query.filter(GLJournalEntry.entry_date < target_date)
        elif target_date is not None:
            query = query.filter(GLJournalEntry.entry_date <= target_date)

        debit_sum, credit_sum = query.first() or (None, None)
        return CashFlowService._dec(debit_sum) - CashFlowService._dec(credit_sum)

    @staticmethod
    def _items_from_mapping(mapping):
        """تحويل بنود القسم إلى قائمة (description/amount/type) لقالب
        دفتر الأستاذ."""
        items = []
        for description, amount in mapping.items():
            items.append({
                'description': description,
                'amount': float(abs(amount)),
                'type': 'inflow' if amount >= 0 else 'outflow',
            })
        return items

    @staticmethod
    def build_ledger_report(gl_report):
        """تقرير قائمة التدفقات بالشكل الذي يتوقعه قالب دفتر الأستاذ.

        ملاحظة: الأقسام كائنات (namespace) وليس قواميس — لأن القالب يقرأ
        ``report.operating_activities.items``، وفي القاموس تكون ``items`` هي
        دالة بايثون المدمجة لا مفتاح البيانات.

        المطابقة (``tie_out``) تُنقل كما هي إلى صفحة دفتر الأستاذ حتى
        تُعرض الحقيقة والمحسوب والفرق بينهما.
        """
        today = datetime.now().date()

        def _section(mapping, net_key, net_value):
            return SimpleNamespace(
                items=CashFlowService._items_from_mapping(mapping),
                **{net_key: net_value},
            )

        tie_out = gl_report.get('tie_out') or {}
        return SimpleNamespace(
            period_start=gl_report['period_start'] or today,
            period_end=gl_report['period_end'] or today,
            operating_activities=_section(
                gl_report['operating_items'], 'net_cash_from_operating',
                float(gl_report['operating_total'])),
            investing_activities=_section(
                gl_report['investing_items'], 'net_cash_from_investing',
                float(gl_report['investing_total'])),
            financing_activities=_section(
                gl_report['financing_items'], 'net_cash_from_financing',
                float(gl_report['financing_total'])),
            net_change_in_cash=float(gl_report['net_change']),
            cash_beginning=float(gl_report['cash_beginning']),
            cash_ending=float(gl_report['cash_ending']),
            cash_ending_computed=float(
                gl_report.get('cash_ending_computed', gl_report['cash_ending'])),
            tie_out=SimpleNamespace(
                gl_cash_ending=float(tie_out.get('gl_cash_ending', 0)),
                computed_ending=float(tie_out.get('computed_ending', 0)),
                difference=float(tie_out.get('difference', 0)),
                balanced=bool(tie_out.get('balanced', False)),
            ),
        )

    @staticmethod
    def generate_cash_flow(period_start, period_end):
        """
        إنشاء قائمة التدفقات النقدية (نسخة قديمة مبنية على جداول التشغيل)

        DEPRECATED: استخدم generate_gl_cash_flow() — فهو المصدر الوحيد
        المعروض في الصفحات والتصدير. أُبقيت هذه الدالة للتوافق مع
        المستهلكين الخارجيين فقط.

        بنود هذه النسخة تبقى مبنية على جداول التشغيل (للتوافق مع
        المستهلكين)، لكن رصيد النقدية في نهاية الفترة يُقرأ من دفتر
        الأستاذ كما في ``generate_gl_cash_flow`` — فلا تتناقض النسختان —
        والفرق بين المحسوب والمقروء يُعلَن في ``tie_out``.

        Args:
            period_start: تاريخ البداية (date أو string)
            period_end: تاريخ النهاية (date أو string)

        Returns:
            dict: قائمة التدفقات النقدية الكاملة + cash_ending_computed +
            tie_out (نفس مفاتيح المطابقة في generate_gl_cash_flow)
        """
        # تحويل التواريخ (نص فارغ = بلا حدّ)
        period_start = _parse_date(period_start)
        period_end = _parse_date(period_end)
        if period_start is None:
            period_start = datetime.now().date()
        if period_end is None:
            period_end = datetime.now().date()

        # تطبيع الفترة لتغطية كامل يوم النهاية — مقارنة DateTime بتاريخ
        # مجرد تُسقط كل حركات ما بعد منتصف ليل اليوم الأخير.
        from datetime import time as _time
        period_end_dt = datetime.combine(period_end, _time.max)
        period_start_dt = datetime.combine(period_start, _time.min)

        base_debit, base_credit, _ = CashFlowService._gl_base_expressions()

        # 1. الأنشطة التشغيلية (Operating Activities)
        operating = CashFlowService._get_operating_activities(period_start_dt, period_end_dt)

        # 2. الأنشطة الاستثمارية (Investing Activities)
        investing = CashFlowService._get_investing_activities(period_start_dt, period_end_dt)

        # 3. الأنشطة التمويلية (Financing Activities)
        financing = CashFlowService._get_financing_activities(period_start_dt, period_end_dt)

        # 4. حساب النقدية — رصيد الدفتر هو الحقيقة (نفس مصدر النسخة الجديدة)
        gl_report = CashFlowService.generate_gl_cash_flow(period_start, period_end)

        cash_beginning = gl_report['cash_beginning']

        net_cash_flow = (
            CashFlowService._dec(operating['net_cash_from_operating']) +
            CashFlowService._dec(investing['net_cash_from_investing']) +
            CashFlowService._dec(financing['net_cash_from_financing'])
        )

        cash_ending = gl_report['cash_ending']
        cash_ending_computed = cash_beginning + net_cash_flow
        tie_out = CashFlowService._tie_out(cash_ending, cash_ending_computed)

        return {
            'period_start': period_start,
            'period_end': period_end,
            'operating_activities': operating,
            'investing_activities': investing,
            'financing_activities': financing,
            'net_change_in_cash': float(net_cash_flow),
            'cash_beginning': float(cash_beginning),
            'cash_ending': float(cash_ending),
            'cash_ending_computed': float(cash_ending_computed),
            'tie_out': tie_out,
        }

    @staticmethod
    def _get_operating_activities(period_start, period_end):
        """حساب التدفقات النقدية من الأنشطة التشغيلية"""

        # المقبوضات من العملاء
        receipts = db.session.query(
            func.sum(Receipt.amount_base)
        ).filter(
            and_(
                Receipt.receipt_date >= period_start,
                Receipt.receipt_date <= period_end,
                Receipt.payment_method.in_(['cash', 'bank'])  # نقدي وبنكي فقط
            )
        ).scalar()
        receipts = CashFlowService._dec(receipts)

        # المدفوعات للموردين
        supplier_payments = db.session.query(
            func.sum(Payment.amount_base)
        ).filter(
            and_(
                Payment.payment_date >= period_start,
                Payment.payment_date <= period_end,
                Payment.payment_method.in_(['cash', 'bank']),
                Payment.supplier_id.isnot(None)
            )
        ).scalar()
        supplier_payments = CashFlowService._dec(supplier_payments)

        # المدفوعات للمصروفات
        expense_payments = db.session.query(
            func.sum(Expense.amount_base)
        ).filter(
            and_(
                Expense.expense_date >= period_start,
                Expense.expense_date <= period_end,
                Expense.payment_method.in_(['cash', 'bank'])
            )
        ).scalar()
        expense_payments = CashFlowService._dec(expense_payments)

        # الرواتب (من حساب الرواتب — F4: SALARY_EXPENSE عبر AccountResolver)
        salary_account = GLAccount.query.filter_by(
            code=CashFlowService.account_code('SALARY_EXPENSE')).first()
        salaries = Decimal('0')
        if salary_account:
            salaries = db.session.query(
                func.sum(CashFlowService._base_debit())
            ).select_from(GLJournalLine).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == salary_account.id,
                    GLJournalEntry.is_posted.is_(True),
                    GLJournalEntry.entry_date >= period_start,
                    GLJournalEntry.entry_date <= period_end
                )
            ).scalar()
            salaries = CashFlowService._dec(salaries)

        net_cash_from_operating = receipts - supplier_payments - expense_payments - salaries

        return {
            'receipts_from_customers': float(receipts),
            'payments_to_suppliers': float(supplier_payments),
            'payments_for_expenses': float(expense_payments),
            'payments_for_salaries': float(salaries),
            'net_cash_from_operating': float(net_cash_from_operating),
            'items': [
                {
                    'description': 'مقبوضات من العملاء',
                    'amount': float(receipts),
                    'type': 'inflow'
                },
                {
                    'description': 'مدفوعات للموردين',
                    'amount': float(supplier_payments),
                    'type': 'outflow'
                },
                {
                    'description': 'مدفوعات مصروفات',
                    'amount': float(expense_payments),
                    'type': 'outflow'
                },
                {
                    'description': 'رواتب وأجور',
                    'amount': float(salaries),
                    'type': 'outflow'
                }
            ]
        }

    @staticmethod
    def _base_debit():
        """تعبير حركة المدينة بعملة الأساس (للمبالغ القديمة في هذه الخدمة)."""
        return CashFlowService._gl_base_expressions()[0]

    @staticmethod
    def _base_credit():
        """تعبير حركة الدائنة بعملة الأساس (للمبالغ القديمة في هذه الخدمة)."""
        return CashFlowService._gl_base_expressions()[1]

    @staticmethod
    def _get_investing_activities(period_start, period_end):
        """حساب التدفقات النقدية من الأنشطة الاستثمارية"""

        # شراء أصول ثابتة — F4: الأصول الثابتة عبر أدوارها المحاسبية
        # (LAND/BUILDINGS/VEHICLES/EQUIPMENT/FURNITURE) بدل البادئة '12%'
        # التي تُسقط أي أصل أُعيد ترميزه خارج النطاق 12xx.
        fixed_assets_codes = resolve_cash_flow_accounts()['FIXED_ASSETS']
        fixed_assets_account = GLAccount.query.filter(
            GLAccount.code.in_(fixed_assets_codes)
        ).all()

        purchase_of_assets = Decimal('0')
        for account in fixed_assets_account:
            purchases = db.session.query(
                func.sum(CashFlowService._base_debit())
            ).select_from(GLJournalLine).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == account.id,
                    GLJournalEntry.is_posted.is_(True),
                    GLJournalEntry.entry_date >= period_start,
                    GLJournalEntry.entry_date <= period_end
                )
            ).scalar() or Decimal('0')
            purchase_of_assets += CashFlowService._dec(purchases)

        # بيع أصول ثابتة (credits في نفس الحسابات)
        sale_of_assets = Decimal('0')
        for account in fixed_assets_account:
            sales = db.session.query(
                func.sum(CashFlowService._base_credit())
            ).select_from(GLJournalLine).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == account.id,
                    GLJournalEntry.is_posted.is_(True),
                    GLJournalEntry.entry_date >= period_start,
                    GLJournalEntry.entry_date <= period_end
                )
            ).scalar() or Decimal('0')
            sale_of_assets += CashFlowService._dec(sales)

        net_cash_from_investing = sale_of_assets - purchase_of_assets

        return {
            'purchase_of_fixed_assets': float(purchase_of_assets),
            'sale_of_fixed_assets': float(sale_of_assets),
            'net_cash_from_investing': float(net_cash_from_investing),
            'items': [
                {
                    'description': 'شراء أصول ثابتة',
                    'amount': float(purchase_of_assets),
                    'type': 'outflow'
                },
                {
                    'description': 'بيع أصول ثابتة',
                    'amount': float(sale_of_assets),
                    'type': 'inflow'
                }
            ]
        }

    @staticmethod
    def _get_financing_activities(period_start, period_end):
        """حساب التدفقات النقدية من الأنشطة التمويلية"""

        # رأس المال — F4: CAPITAL عبر AccountResolver
        capital_account = GLAccount.query.filter_by(
            code=CashFlowService.account_code('CAPITAL')).first()
        capital_contributions = Decimal('0')
        if capital_account:
            capital_contributions = db.session.query(
                func.sum(CashFlowService._base_credit())
            ).select_from(GLJournalLine).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == capital_account.id,
                    GLJournalEntry.is_posted.is_(True),
                    GLJournalEntry.entry_date >= period_start,
                    GLJournalEntry.entry_date <= period_end
                )
            ).scalar()
            capital_contributions = CashFlowService._dec(capital_contributions)

        # سحوبات المالك — F4: OWNER_DRAWS عبر AccountResolver
        owner_draw_account = GLAccount.query.filter_by(
            code=CashFlowService.account_code('OWNER_DRAWS')).first()
        owner_withdrawals = Decimal('0')
        if owner_draw_account:
            owner_withdrawals = db.session.query(
                func.sum(CashFlowService._base_debit())
            ).select_from(GLJournalLine).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == owner_draw_account.id,
                    GLJournalEntry.is_posted.is_(True),
                    GLJournalEntry.entry_date >= period_start,
                    GLJournalEntry.entry_date <= period_end
                )
            ).scalar()
            owner_withdrawals = CashFlowService._dec(owner_withdrawals)

        # القروض — F4: LOANS عبر AccountResolver
        loans_account = GLAccount.query.filter_by(
            code=CashFlowService.account_code('LOANS')).first()
        loans_received = Decimal('0')
        loan_repayments = Decimal('0')
        if loans_account:
            loans_received = db.session.query(
                func.sum(CashFlowService._base_credit())
            ).select_from(GLJournalLine).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == loans_account.id,
                    GLJournalEntry.is_posted.is_(True),
                    GLJournalEntry.entry_date >= period_start,
                    GLJournalEntry.entry_date <= period_end
                )
            ).scalar()
            loans_received = CashFlowService._dec(loans_received)

            loan_repayments = db.session.query(
                func.sum(CashFlowService._base_debit())
            ).select_from(GLJournalLine).join(GLJournalEntry).filter(
                and_(
                    GLJournalLine.account_id == loans_account.id,
                    GLJournalEntry.is_posted.is_(True),
                    GLJournalEntry.entry_date >= period_start,
                    GLJournalEntry.entry_date <= period_end
                )
            ).scalar()
            loan_repayments = CashFlowService._dec(loan_repayments)

        net_cash_from_financing = (
            capital_contributions + loans_received - owner_withdrawals - loan_repayments
        )

        return {
            'capital_contributions': float(capital_contributions),
            'owner_withdrawals': float(owner_withdrawals),
            'loans_received': float(loans_received),
            'loan_repayments': float(loan_repayments),
            'net_cash_from_financing': float(net_cash_from_financing),
            'items': [
                {
                    'description': 'إضافات رأس المال',
                    'amount': float(capital_contributions),
                    'type': 'inflow'
                },
                {
                    'description': 'قروض مستلمة',
                    'amount': float(loans_received),
                    'type': 'inflow'
                },
                {
                    'description': 'سحوبات المالك',
                    'amount': float(owner_withdrawals),
                    'type': 'outflow'
                },
                {
                    'description': 'سداد قروض',
                    'amount': float(loan_repayments),
                    'type': 'outflow'
                }
            ]
        }
