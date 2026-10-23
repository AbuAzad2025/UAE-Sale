from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, abort, current_app
from flask_login import login_required, current_user
from sqlalchemy import and_, case, func
from extensions import db
from models import GLAccount, GLJournalEntry, GLJournalLine, Cheque, PaymentVault
from services.gl_service import GLService
from services.cash_flow_service import CashFlowService
from utils.decorators import admin_required, permission_required, get_owned_or_404
from utils.helpers import create_audit_log
from decimal import Decimal
from datetime import datetime, date, timedelta
from services.aging_analysis_service import AGING_BUCKETS, OVERDUE_BUCKETS

ledger_bp = Blueprint('ledger', __name__, url_prefix='/ledger')


# ═══════════════════════════════════════════════════════════════════════════
# مساعدات مشتركة للقوائم المالية (ميزان المراجعة / قائمة الدخل / الميزانية)
# ═══════════════════════════════════════════════════════════════════════════
# سياسة واحدة تُطبَّق على كل القوائم حتى لا تختلف بينها:
#   1) الحسابات المعروضة: is_active = True و is_header = False.
#      الحسابات الرئيسية (is_header) لا تقبل قيود مباشرة، والحسابات غير
#      النشطة لا تدخل القوائم — لذلك تُستبعد بالطريقة نفسها في كل القوائم.
#   2) الأرقام بعملة الأساس دائماً:
#      GLJournalLine.amount_base هو المبلغ المخزّن بعملة الأساس، بينما
#      debit/credit هما المبلغان بعملة المعاملة. لذلك يُقرأ اتجاه الحركة من
#      debit/credit ويُقرأ مقدارها من amount_base (أو من
#      (debit − credit) × سعر صرف القيد إن لم يكن amount_base مسجّلاً).
#   3) القيود المرحّلة فقط (is_posted = True)، والربط بسطر القيد إلزامي
#      لاستبعاد السطور اليتيمة (قيد حُذف) والمسودات.
#   4) إشارة الرصيد تأتي من طبيعة الحساب (GLAccount.type) لا من بادئة الكود.

def _dec(value):
    """تحويل آمن لنتيجة تجميع (Decimal/float/None) إلى Decimal."""
    if value is None:
        return Decimal('0')
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _as_date(value):
    """تحويل تاريخ/نص إلى date (أو None)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), '%Y-%m-%d').date()
        except ValueError:
            return None
    return None


def reverse_or_purge_gl_entries(reference_type, reference_id, description=None):
    """F1 — مصير القيود المحاسبية المرتبطة بمستند: عكس المرحَّل، وحذف المسودة.

    ``GLService.purge_by_reference`` يرفض حذف قيد مرحَّل (أو معكوس) ويرفع
    ValidationError — وهذا هو السلوك الصحيح: القيد المرحَّل لا يُحذف أبداً
    (فقدان الإيراد أو الذمم بلا أثر يبقى متوازناً فلا ينتبه أحد)، بل يُعكس.
    هذه الدالة هي السياسة الواحدة التي تُطبَّق على كل مسارات حذف/أرشفة
    المستندات (مبيعات، مشتريات، سندات قبض/صرف، مصروفات، شيكات):

    * القيود المرحَّلة (is_posted) → تُعكس عبر ``GLService.reverse_entry``
      (قيد عكسي + سجل تدقيق + ربط في الاتجاهين)، فيبقى ميزان المراجعة
      متوازناً ومُبرَّراً، ولا يفقد المستند أثره المحاسبي.
    * القيود المسودة (is_posted=False) → تُحذف (لم تُرحَّل بعد فلا أثر لها).

    الأخطاء لا تُبتلع: أي فشل في العكس يُرفع إلى المستدعي الذي يلغي
    العملية كلّها (لا يُحذف مستند وتبقى قيوده، ولا يُحذف قيد مرحَّل).

    Args:
        reference_type: نوع المرجع ('Sale', 'Purchase', 'Receipt', 'Payment',
            'Expense', 'cheque_receive', 'Cheque', ...).
        reference_id: معرّف المستند المرتبط بالقيود.
        description: وصف القيد العكسي (يظهر في اليومية).

    Returns:
        dict: ``{'reversed': n, 'purged': m, 'posted': bool}``.
    """
    from models import GLJournalLine
    from services.gl_service import GLService

    entries = GLJournalEntry.query.filter_by(
        reference_type=reference_type, reference_id=reference_id
    ).all()
    if not entries:
        return {'reversed': 0, 'purged': 0, 'posted': False}

    # القيود المرحَّلة الأصلية فقط: القيد العكسي (entry_type='reversing')
    # لا يُعكس أبداً — عكسه يُبطل العكس الأول (صافي الأثر = صفر).
    posted = [
        e for e in entries
        if getattr(e, 'is_posted', False)
        and not getattr(e, 'is_reversed', False)
        and (e.entry_type or '') != 'reversing'
    ]
    drafts = [e for e in entries if not getattr(e, 'is_posted', False)]

    # 1) المسودات: تُحذف (سطوراً ثم رؤوساً — بأمان FK).
    purged = 0
    if drafts:
        draft_ids = [e.id for e in drafts]
        GLJournalLine.query.filter(
            GLJournalLine.entry_id.in_(draft_ids)
        ).delete(synchronize_session='fetch')
        purged = GLJournalEntry.query.filter(
            GLJournalEntry.id.in_(draft_ids)
        ).delete(synchronize_session='fetch')

    # 2) القيود المرحَّلة: تُعكس (ولا تُحذف أبداً).
    for entry in posted:
        GLService.reverse_entry(entry, description=description)

    return {'reversed': len(posted), 'purged': purged, 'posted': bool(posted)}


def _statement_accounts(account_type=None):
    """الحسابات التي تدخل القوائم المالية (نشطة + غير رئيسية).

    policy: is_active=True و is_header=False — نفس القاعدة في ميزان المراجعة
    وقائمة الدخل والميزانية العمومية.
    """
    query = GLAccount.query.filter(
        GLAccount.is_active.is_(True),
        GLAccount.is_header.is_(False),
    )
    if account_type is not None:
        query = query.filter(GLAccount.type == account_type)
    return query.order_by(GLAccount.code).all()


def _gl_signed_base_expression():
    """المبلغ الصافي الموقّع لسطر القيد بعملة الأساس (موجب = حركة مدينة).

    amount_base = (debit − credit) × سعر صرف القيد (العقد المحاسبي في
    services/gl_service.py)، فهو الصافي الموقّع بعملة الأساس. لكنه لا يفصل
    الحركة المدينة عن الدائنة، لذلك:
      • الاتجاه يُقرأ من debit/credit (دائماً معبّأة)،
      • المقدار يُقرأ من amount_base عند وجوده، وإلا يُشتق من
        (debit − credit) × سعر صرف القيد.
    كل القوائم المالية تمرّ من هذه الدالة فلا تتناقض.
    """
    fallback = (GLJournalLine.debit - GLJournalLine.credit) * GLJournalEntry.exchange_rate
    return case(
        (GLJournalLine.amount_base.is_(None), fallback),
        (GLJournalLine.amount_base == 0, fallback),
        (and_(GLJournalLine.debit > 0, GLJournalLine.credit == 0),
         func.abs(GLJournalLine.amount_base)),
        (and_(GLJournalLine.credit > 0, GLJournalLine.debit == 0),
         -func.abs(GLJournalLine.amount_base)),
        else_=fallback,
    )


def _gl_base_debit_expression():
    """حركة المدينة لسطر القيد بعملة الأساس."""
    signed = _gl_signed_base_expression()
    return case((signed > 0, signed), else_=0)


def _gl_base_credit_expression():
    """حركة الدائنة لسطر القيد بعملة الأساس."""
    signed = _gl_signed_base_expression()
    return case((signed < 0, -signed), else_=0)


def _gl_natural_base_expression():
    """الرصيد الطبيعي لسطر القيد بعملة الأساس حسب طبيعة الحساب.

    الأصول والمصروفات مدينة الطبيعة (مدين − دائن)، والخصوم وحقوق الملكية
    والإيرادات دائنة الطبيعة (دائن − مدين).
    """
    signed = _gl_signed_base_expression()
    return case(
        (GLAccount.type.in_(GLAccount.CREDIT_NATURE_TYPES), -signed),
        else_=signed,
    )


def _statement_balances(date_from=None, date_to=None, as_of_date=None):
    """حركة كل حساب ورصيده الطبيعي — بعملة الأساس.

    يعيد قاموساً: {account_id: {'debit': Decimal, 'credit': Decimal,
                                'balance': Decimal}}
    debit/credit = حركتا المدينة والدائنة (مجموع كل منهما)،
    balance = الرصيد الطبيعي بعدّل طبيعة الحساب.
    """
    query = (
        db.session.query(
            GLJournalLine.account_id.label('account_id'),
            func.sum(_gl_base_debit_expression()).label('debit_sum'),
            func.sum(_gl_base_credit_expression()).label('credit_sum'),
            func.sum(_gl_natural_base_expression()).label('balance_sum'),
        )
        .join(GLJournalEntry, GLJournalLine.entry_id == GLJournalEntry.id)
        .join(GLAccount, GLJournalLine.account_id == GLAccount.id)
        .filter(GLJournalEntry.is_posted.is_(True))
    )
    lower = _as_date(date_from)
    upper = _as_date(date_to) or _as_date(as_of_date)
    if lower is not None:
        query = query.filter(func.date(GLJournalEntry.entry_date) >= lower)
    if upper is not None:
        query = query.filter(func.date(GLJournalEntry.entry_date) <= upper)

    query = query.group_by(GLJournalLine.account_id)

    return {
        row.account_id: {
            'debit': _dec(row.debit_sum),
            'credit': _dec(row.credit_sum),
            'balance': _dec(row.balance_sum),
        }
        for row in query.all()
    }


# ═══════════════════════════════════════════════════════════════════════════
# تحليل عمر الذمم — مصدر واحد لصفحتَي دفتر الأستاذ والتقارير
# ═══════════════════════════════════════════════════════════════════════════
# السياسة الموحّدة (تطبَّق على الذمم المدينة والدائنة):
#   • العملة: عملة الأساس دائماً (amount_base − paid_amount_base).
#   • النطاق: مستندات مؤكدة ونشطة وغير مؤرشفة، تاريخها ≤ تاريخ التقرير،
#     والطرف المقابل (عميل/مورد) نشط.
#   • الرصيد: الفرق بين الإجمالي والمستحق، ويشمل فقط ما هو أكبر من صفر.
#   • الشرائح: 0-30 / 31-60 / 61-90 / 91-120 / +120 يوم.

AGING_BUCKETS = ('0-30', '31-60', '61-90', '91-120', 'over_120')

# مفاتيح قالب صفحة التقارير (current / days_30 / ...) ← الشرائح الدقيقة.
# ملاحظة: مفتاح 'over_90' في قالب التقارير يحتوي فعلياً على 121 يوم
# (وأكثر) — والحدود الدقيقة موثّقة هنا وفي AGING_BUCKETS.
_REPORT_BUCKET_KEYS = {
    '0-30': 'current',
    '31-60': 'days_30',
    '61-90': 'days_60',
    '91-120': 'days_90',
    'over_120': 'over_90',
}


def _aging_bucket(days_old):
    """تصنيف عمر المستند إلى شريحة."""
    if days_old <= 30:
        return '0-30'
    if days_old <= 60:
        return '31-60'
    if days_old <= 90:
        return '61-90'
    if days_old <= 120:
        return '91-120'
    return 'over_120'


def _archived_record_ids(table_name):
    """معرّفات السجلات المؤرشفة.

    الأرشفة تعكس القيود المحاسبية وتترك حالة المستند 'confirmed'، لذلك
    يجب استبعادها صراحةً من كل تقرير مالي.
    """
    from models import ArchivedRecord
    from sqlalchemy import select
    return select(ArchivedRecord.record_id).where(
        ArchivedRecord.table_name == table_name)


def _receivables_aging(as_of_date=None):
    """تحليل عمر الذمم المدينة — مصدر واحد لصفحتي دفتر الأستاذ والتقارير.

    الآن يستند إلى تاريخ الاستحقاق (due_date) لا تاريخ الفاتورة،
    بحيث تُقسَم الأرصدة حسب المتأخرات الحقيقية (overdue) لا العمر.

    Returns:
        dict: {
            'as_of_date': date,
            'buckets': {bucket: Decimal},      # الشرائح القديمة (للتوافق)
            'total': Decimal,
            'overdue_buckets': {bucket: Decimal},  # الشرائح الجديدة (الحقيقية)
            'overdue_total': Decimal,
            'invoices': [Sale, ...],
            'customers': [{'customer': Customer, '0-30': float, ...,
                           'total': float, 'invoices': [...],
                           'overdue_buckets': {...}, 'overdue_total': float}],
            'customer_count': int,
        }
    """
    from services.aging_analysis_service import AgingAnalysisService

    as_of = _as_date(as_of_date) or date.today()
    service_report = AgingAnalysisService.get_receivables_aging(as_of_date=as_of)

    # تحويل إجماليات الخدمة (floats) إلى Decimal للحسابات الداخلية
    buckets = {bucket: Decimal(str(service_report['buckets'].get(bucket, 0)))
               for bucket in AGING_BUCKETS}
    total = Decimal(str(service_report['totals'].get('total', 0)))
    overdue_buckets = {bucket: Decimal(str(service_report['overdue_buckets'].get(bucket, 0)))
                       for bucket in OVERDUE_BUCKETS}
    overdue_total = Decimal(str(service_report.get('overdue_total', 0)))

    # بناء قائمة الفواتير بالشكل المتوقع من الكود القديم
    invoices = []
    for customer_data in service_report['customers']:
        for inv in customer_data.get('invoices', []):
            # إضافة الحقول المتوقعة للكود القديم
            inv_obj = type('InvoiceProxy', (), {
                'sale_number': inv.get('sale_number'),
                'sale_date': inv.get('sale_date'),
                'due_date': inv.get('due_date'),
                'total': Decimal(str(inv.get('total_base', 0))),
                'paid_amount_base': Decimal(str(inv.get('paid_base', 0))),
                'balance': Decimal(str(inv.get('balance', 0))),
                'calculated_balance': Decimal(str(inv.get('balance', 0))),
                'id': inv.get('id'),  # Database ID for URL generation
                'currency': inv.get('currency'),
                'days_old': inv.get('days_old'),
                'aging_bucket': inv.get('age_category'),
                'days_overdue': inv.get('days_overdue'),
                'overdue_bucket': inv.get('overdue_bucket'),
            })()
            invoices.append(inv_obj)

    # بناء بيانات العملاء بالتنسيق المتوقع
    customers_list = []
    for customer_data in service_report['customers']:
        cust = customer_data['customer']
        customer_entry = {
            'customer': cust,
            '0-30': customer_data.get('0-30', 0),
            '31-60': customer_data.get('31-60', 0),
            '61-90': customer_data.get('61-90', 0),
            '91-120': customer_data.get('91-120', 0),
            'over_120': customer_data.get('over_120', 0),
            'total': customer_data.get('total', 0),
            'overdue_buckets': customer_data.get('overdue_buckets', {}),
            'overdue_total': customer_data.get('overdue_total', 0),
            'invoices': [
                type('InvoiceProxy', (), inv)()
                for inv in customer_data.get('invoices', [])
            ],
        }
        customers_list.append(customer_entry)

    return {
        'as_of_date': as_of,
        'buckets': buckets,
        'total': total,
        'overdue_buckets': overdue_buckets,
        'overdue_total': overdue_total,
        'invoices': invoices,
        'customers': customers_list,
        'customer_count': len(customers_list),
    }


def _payables_aging(as_of_date=None):
    """تحليل عمر الذمم الدائنة — الآن بالاستحقاق (due_date) لا بتاريخ الشراء.

    Returns:
        dict: {
            'as_of_date': date,
            'buckets': {bucket: Decimal},
            'total': Decimal,
            'overdue_buckets': {bucket: Decimal},
            'overdue_total': Decimal,
            'suppliers': [{'supplier': Supplier, '0-30': float, ...,
                           'total': float, 'overdue_buckets': {...}, 'overdue_total': float}],
            'supplier_count': int,
        }
    """
    from services.aging_analysis_service import AgingAnalysisService

    as_of = _as_date(as_of_date) or date.today()
    service_report = AgingAnalysisService.get_payables_aging(as_of_date=as_of)

    buckets = {bucket: Decimal(str(service_report['buckets'].get(bucket, 0)))
               for bucket in AGING_BUCKETS}
    total = Decimal(str(service_report['totals'].get('total', 0)))
    overdue_buckets = {bucket: Decimal(str(service_report['overdue_buckets'].get(bucket, 0)))
                       for bucket in OVERDUE_BUCKETS}
    overdue_total = Decimal(str(service_report.get('overdue_total', 0)))

    suppliers_list = []
    for supplier_data in service_report.get('suppliers', []):
        sup = supplier_data['supplier']
        supplier_entry = {
            'supplier': sup,
            '0-30': supplier_data.get('0-30', 0),
            '31-60': supplier_data.get('31-60', 0),
            '61-90': supplier_data.get('61-90', 0),
            '91-120': supplier_data.get('91-120', 0),
            'over_120': supplier_data.get('over_120', 0),
            'total': supplier_data.get('total', 0),
            'overdue_buckets': supplier_data.get('overdue_buckets', {}),
            'overdue_total': supplier_data.get('overdue_total', 0),
        }
        suppliers_list.append(supplier_entry)

    return {
        'as_of_date': as_of,
        'buckets': buckets,
        'total': total,
        'overdue_buckets': overdue_buckets,
        'overdue_total': overdue_total,
        'suppliers': suppliers_list,
        'supplier_count': len(suppliers_list),
    }


@ledger_bp.route('/')
@login_required
@permission_required('view_ledger')
def index():
    accounts = GLAccount.query.filter_by(is_active=True).order_by(GLAccount.code).all()
    # Dashboard stats (merged from the admin twin — single ledger home).
    total_accounts = GLAccount.query.count()
    total_entries = GLJournalEntry.query.count()
    posted_entries = GLJournalEntry.query.filter_by(is_posted=True).count()
    cash_accounts = GLAccount.query.filter(GLAccount.code.like('11%')).all()
    total_cash = sum((a.get_balance() for a in cash_accounts), Decimal('0'))
    recent_entries = GLJournalEntry.query.order_by(
        GLJournalEntry.created_at.desc()).limit(10).all()
    stats = {
        'total_accounts': total_accounts,
        'active_accounts': len(accounts),
        'total_entries': total_entries,
        'posted_entries': posted_entries,
        'total_cash': float(total_cash),
    }
    return render_template('ledger/index.html', accounts=accounts,
                           stats=stats, recent_entries=recent_entries)


@ledger_bp.route('/account/<int:id>')
@login_required
@permission_required('view_ledger')
def account_ledger(id):
    account = db.get_or_404(GLAccount, id)

    date_from = request.args.get('date_from', type=str)
    date_to = request.args.get('date_to', type=str)

    query = GLJournalLine.query.filter_by(account_id=id).join(GLJournalEntry)

    if date_from:
        query = query.filter(func.date(GLJournalEntry.entry_date) >= date_from)

    if date_to:
        query = query.filter(func.date(GLJournalEntry.entry_date) <= date_to)

    lines = query.order_by(GLJournalEntry.entry_date).all()

    running_balance = Decimal('0')
    transactions = []

    for line in lines:
        # debit/credit بعملة المعاملة — تُحوَّل إلى عملة الأساس بسعر صرف
        # القيد، لأن القالب يعرض المبالغ بعملة الأساس.
        rate = _dec(getattr(line.entry, 'exchange_rate', 1) or 1)
        base_debit = _dec(line.debit) * rate
        base_credit = _dec(line.credit) * rate
        running_balance += base_debit - base_credit

        transactions.append({
            'date': line.entry.entry_date,
            'entry_number': line.entry.entry_number,
            'description': line.description or line.entry.description,
            'reference': f'{line.entry.reference_type} #{line.entry.reference_id}' if line.entry.reference_type else '',
            'debit': float(base_debit),
            'credit': float(base_credit),
            'balance': float(running_balance)
        })

    summary = {
        'total_debit': sum(t['debit'] for t in transactions),
        'total_credit': sum(t['credit'] for t in transactions),
        'final_balance': float(running_balance)
    }

    return render_template('ledger/account_ledger.html',
                           account=account,
                           transactions=transactions,
                           summary=summary)


@ledger_bp.route('/trial-balance')
@login_required
@permission_required('view_ledger')
def trial_balance():
    # Optional date window (merged from the admin twin): absent = all-time.
    date_from = request.args.get('date_from', type=str) or None
    date_to = request.args.get('date_to', type=str) or None
    try:
        df = datetime.strptime(date_from, '%Y-%m-%d').date() if date_from else None
        dt = datetime.strptime(date_to, '%Y-%m-%d').date() if date_to else None
    except (ValueError, TypeError):
        flash('⚠️ صيغة التاريخ غير صالحة — تم تجاهل فلتر التاريخ.', 'warning')
        df = dt = None
        date_from = date_to = None

    # مجاميع واحدة لكل الحسابات: الحركة المدينة والدائنة بالأساس + الرصيد.
    # نفس الاستعلام يُستخدم مع أو بدون فلتر التاريخ (انظر _statement_balances)
    # فلا يختلف الميزان عن نفسه، ولا تُحتسب سطور يتيمة أو قيود مسودة.
    balances = _statement_balances(date_from=df, date_to=dt)

    accounts = _statement_accounts()

    trial_data = []
    total_debit = Decimal('0')
    total_credit = Decimal('0')
    total_debit_balance = Decimal('0')
    total_credit_balance = Decimal('0')

    for account in accounts:
        account_balances = balances.get(account.id)
        debit_sum = account_balances['debit'] if account_balances else Decimal('0')
        credit_sum = account_balances['credit'] if account_balances else Decimal('0')

        balance = debit_sum - credit_sum

        if balance != 0 or debit_sum != 0 or credit_sum != 0:
            debit_bal = balance if balance > 0 else Decimal('0')
            credit_bal = abs(balance) if balance < 0 else Decimal('0')

            trial_data.append({
                'account': account,
                'debit': float(debit_sum),
                'credit': float(credit_sum),
                'balance': float(balance),
                'debit_balance': float(debit_bal),
                'credit_balance': float(credit_bal)
            })

            total_debit += debit_sum
            total_credit += credit_sum
            total_debit_balance += debit_bal
            total_credit_balance += credit_bal

    is_balanced = (total_debit == total_credit)
    is_net_balanced = (total_debit_balance == total_credit_balance)

    return render_template('ledger/trial_balance.html',
                           trial_data=trial_data,
                           total_debit=float(total_debit),
                           total_credit=float(total_credit),
                           total_debit_balance=float(total_debit_balance),
                           total_credit_balance=float(total_credit_balance),
                           is_balanced=is_balanced,
                           is_net_balanced=is_net_balanced,
                           date_from=date_from or '',
                           date_to=date_to or '')


@ledger_bp.route('/journal-entries')
@login_required
@permission_required('view_ledger')
def journal_entries():
    page = request.args.get('page', 1, type=int)
    status = (request.args.get('status') or '').strip()
    entry_type = (request.args.get('entry_type') or '').strip()
    q = (request.args.get('q') or '').strip()

    query = GLJournalEntry.query
    if status == 'posted':
        query = query.filter_by(is_posted=True, is_reversed=False)
    elif status == 'draft':
        query = query.filter_by(is_posted=False)
    elif status == 'reversed':
        query = query.filter_by(is_reversed=True)
    if entry_type in ('manual', 'auto', 'reversing', 'closing'):
        query = query.filter_by(entry_type=entry_type)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            GLJournalEntry.entry_number.ilike(like),
            GLJournalEntry.description.ilike(like),
        ))

    pagination = query.order_by(GLJournalEntry.entry_date.desc()).paginate(
        page=page,
        per_page=50,
        error_out=False
    )

    return render_template('ledger/journal_entries.html',
                           entries=pagination.items,
                           pagination=pagination,
                           status=status,
                           entry_type=entry_type,
                           q=q)


@ledger_bp.route('/income-statement')
@login_required
@permission_required('view_ledger')
def income_statement():
    date_from = request.args.get('date_from', type=str)
    date_to = request.args.get('date_to', type=str)

    # نفس مصدر البيانات Policy لكل القوائم: حسابات نشطة غير رئيسية + قيود
    # مرحّلة + مبالغ بعملة الأساس.
    balances = _statement_balances(date_from=date_from, date_to=date_to)

    revenues = {}
    total_revenue = Decimal('0')

    # الإيرادات دائنة الطبيعة: الرصيد الطبيعي موجب = إيراد.
    for acc in _statement_accounts(account_type='revenue'):
        account_balances = balances.get(acc.id)
        balance = account_balances['balance'] if account_balances else Decimal('0')

        if balance != 0:
            revenues[acc.name] = float(balance)
            total_revenue += balance

    expenses = {}
    total_expense = Decimal('0')

    # المصروفات مدينة الطبيعة: الرصيد الطبيعي موجب = مصروف.
    for acc in _statement_accounts(account_type='expense'):
        account_balances = balances.get(acc.id)
        balance = account_balances['balance'] if account_balances else Decimal('0')

        if balance != 0:
            expenses[acc.name] = float(balance)
            total_expense += balance

    net_profit = total_revenue - total_expense

    return render_template('ledger/income_statement.html',
                           revenues=revenues,
                           expenses=expenses,
                           total_revenue=float(total_revenue),
                           total_expense=float(total_expense),
                           net_profit=float(net_profit))


@ledger_bp.route('/balance-sheet')
@login_required
@permission_required('view_ledger')
def balance_sheet():
    # Optional as-of date (merged from the admin twin): absent = all-time.
    as_of_raw = request.args.get('as_of_date', type=str) or None
    try:
        as_of_date = datetime.strptime(as_of_raw, '%Y-%m-%d').date() if as_of_raw else None
    except (ValueError, TypeError):
        from flask import current_app
        current_app.logger.warning(f'Ledger balance-sheet: ignoring unparsable as_of_date={as_of_raw!r}')
        flash('⚠️ صيغة التاريخ غير صالحة — تم تجاهل فلتر التاريخ.', 'warning')
        as_of_date = None
        as_of_raw = None

    # نفس مصدر البيانات Policy لكل القوائم: حسابات نشطة غير رئيسية + قيود
    # مرحّلة + أرصدة بعملة الأساس.
    balances = _statement_balances(as_of_date=as_of_date)

    def _balance(account_id):
        account_balances = balances.get(account_id)
        return account_balances['balance'] if account_balances else Decimal('0')

    assets = {}
    liabilities = {}
    equity = {}

    total_assets = Decimal('0')
    for acc in _statement_accounts(account_type='asset'):
        balance = _balance(acc.id)
        if balance != 0:
            assets[acc.name] = float(balance)
            total_assets += balance

    total_liabilities = Decimal('0')
    for acc in _statement_accounts(account_type='liability'):
        balance = _balance(acc.id)
        if balance != 0:
            liabilities[acc.name] = float(balance)
            total_liabilities += balance

    total_equity = Decimal('0')
    for acc in _statement_accounts(account_type='equity'):
        balance = _balance(acc.id)
        if balance != 0:
            equity[acc.name] = float(balance)
            total_equity += balance

    # الأرباح المبقاة = صافي ربح الفترة التراكمي (إيرادات − مصروفات).
    # هذا هو "قيد الإقفال" الافتراضي: لم يقفل النظام الأرباح في حساب
    # حقوق ملكية فعلي، لذلك تُضاف هنا ليقفل الميزان.
    total_revenue_period = Decimal('0')
    for acc in _statement_accounts(account_type='revenue'):
        total_revenue_period += _balance(acc.id)

    total_expense_period = Decimal('0')
    for acc in _statement_accounts(account_type='expense'):
        total_expense_period += _balance(acc.id)

    net_profit_period = total_revenue_period - total_expense_period

    if net_profit_period != 0:
        equity['الأرباح المبقاة (صافي الربح التراكمي)'] = float(net_profit_period)
        total_equity += net_profit_period

    # المعادلة المحاسبية: الأصول = الخصوم + حقوق الملكية.
    # الفارق يُعرض كتنبيه أحمر — لا يُخفى ولا يُسوّى.
    delta = total_assets - (total_liabilities + total_equity)
    balanced = abs(delta) <= Decimal('0.01')

    return render_template('ledger/balance_sheet.html',
                           assets=assets,
                           liabilities=liabilities,
                           equity=equity,
                           total_assets=float(total_assets),
                           total_liabilities=float(total_liabilities),
                           total_equity=float(total_equity),
                           delta=float(delta),
                           balanced=balanced,
                           as_of_date=as_of_raw or '')


@ledger_bp.route('/accounts-tree')
@login_required
@permission_required('view_ledger')
def accounts_tree():
    """عرض شجرة الحسابات"""
    tree = GLService.get_accounts_tree()
    return render_template('ledger/accounts_tree.html', accounts_tree=tree)


@ledger_bp.route('/account/<int:id>/statement')
@login_required
@permission_required('view_ledger')
def account_statement(id):
    """كشف حساب تفصيلي"""
    date_from = request.args.get('date_from', type=str)
    date_to = request.args.get('date_to', type=str)

    statement = GLService.get_account_statement(id, date_from, date_to)

    return render_template('ledger/account_statement.html',
                           statement=statement,
                           date_from=date_from,
                           date_to=date_to)


@ledger_bp.route('/manual-entry', methods=['GET', 'POST'])
@login_required
@permission_required('manage_ledger')
def manual_entry():  # noqa: C901
    """إضافة قيد يدوي"""
    if request.method == 'POST':
        try:
            description = request.form.get('description')
            entry_date = request.form.get('entry_date')
            notes = request.form.get('notes')

            # تحويل التاريخ
            if entry_date:
                entry_date = datetime.strptime(entry_date, '%Y-%m-%d')

            # جمع السطور
            lines = []

            # جمع جميع السطور من الفورم
            i = 0
            while True:
                account_code = request.form.get(f'line_{i}_account')
                if not account_code:
                    break

                debit = request.form.get(f'line_{i}_debit', 0)
                credit = request.form.get(f'line_{i}_credit', 0)
                line_description = request.form.get(f'line_{i}_description', '')

                # تحويل القيم الفارغة إلى صفر
                try:
                    debit_value = float(str(debit).strip()) if debit and str(debit).strip() else 0
                    credit_value = float(str(credit).strip()) if credit and str(credit).strip() else 0
                except (ValueError, AttributeError, TypeError):
                    raise ValueError(f'❌ قيمة غير صالحة في السطر {i + 1}: تحقق من المدين/الدائن.')

                # إضافة السطر فقط إذا كان فيه قيمة
                if debit_value > 0 or credit_value > 0:
                    lines.append({
                        'account_code': account_code,
                        'debit': debit_value,
                        'credit': credit_value,
                        'description': line_description
                    })

                i += 1

            # رفض القيد الفارغ: بدون هذا التحقق كان create_manual_entry
            # يقبل lines=[] ويخزّن قيداً بقيمة صفر داخل دفتر الأستاذ.
            if not lines:
                raise ValueError(
                    '❌ القيد فارغ: أضف سطراً واحداً على الأقل بقيمة مدين أو دائن.\n'
                    '💡 لا يمكن حفظ قيد بلا سطور مؤثرة.'
                )

            # إنشاء القيد
            entry = GLService.create_manual_entry(
                description=description,
                lines=lines,
                entry_date=entry_date,
                notes=notes,
                created_by=current_user.id
            )

            create_audit_log('create', 'gl_journal_entries', entry.id)

            flash(f'✅ تم إنشاء القيد {entry.entry_number} بنجاح', 'success')
            return redirect(url_for('ledger.view_entry', id=entry.id))

        except ValueError as e:
            current_app.logger.exception('handler failed')
            flash(f'❌ خطأ: {e}', 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('handler failed')
            flash(f'❌ خطأ: حدث خطأ غير متوقع\n💡 تحقق من البيانات المدخلة وحاول مرة أخرى.', 'danger')

    # الحصول على الحسابات النشطة (غير رئيسية)
    accounts = GLAccount.query.filter_by(is_active=True, is_header=False).order_by(GLAccount.code).all()

    return render_template('ledger/manual_entry.html', accounts=accounts, today=date.today())


@ledger_bp.route('/entry/<int:id>')
@login_required
@permission_required('view_ledger')
def view_entry(id):
    """عرض تفاصيل القيد"""
    entry = get_owned_or_404(GLJournalEntry, id)
    lines = entry.lines.all()

    return render_template('ledger/view_entry.html', entry=entry, lines=lines)


@ledger_bp.route('/entry/<int:id>/reverse', methods=['POST'])
@login_required
@permission_required('manage_ledger')
def reverse_entry(id):
    """عكس القيد (عبر مدير القيود المتقدم: موثق ومحمي من العكس المزدوج)"""
    from services.advanced_journal_manager import AdvancedJournalEntryManager
    entry = get_owned_or_404(GLJournalEntry, id)
    try:
        reason = request.form.get('description') or request.form.get('reason') or 'عكس القيد'
        reversed_entry = AdvancedJournalEntryManager.reverse_entry_advanced(
            entry.id, current_user.id, reason)

        create_audit_log('create', 'gl_journal_entries', reversed_entry.id,
                         changes={'reversed_from': entry.entry_number})

        flash(f'✅ تم عكس القيد بنجاح - القيد الجديد: {reversed_entry.entry_number}', 'success')
        return redirect(url_for('ledger.view_entry', id=reversed_entry.id))

    except ValueError as e:
        current_app.logger.exception('handler failed')
        flash(f'❌ خطأ: حدث خطأ غير متوقع', 'danger')
        return redirect(url_for('ledger.view_entry', id=id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('handler failed')
        flash(f'❌ خطأ: حدث خطأ غير متوقع', 'danger')
        return redirect(url_for('ledger.view_entry', id=id))


@ledger_bp.route('/entry/<int:id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_entry(id):
    """الموافقة على قيد مسودة وترحيله"""
    from services.advanced_journal_manager import AdvancedJournalEntryManager
    try:
        approval_notes = request.form.get('approval_notes', 'موافقة على القيد')

        AdvancedJournalEntryManager.approve_entry(
            entry_id=id,
            approved_by=current_user.id,
            approval_notes=approval_notes
        )

        flash('✅ تم الموافقة على القيد وترحيله بنجاح', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('handler failed')
        flash(f'❌ خطأ: حدث خطأ غير متوقع', 'danger')

    return redirect(url_for('ledger.view_entry', id=id))


@ledger_bp.route('/entry/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_entry(id):
    """حذف قيد مسودة (المرحّل محمي: مرفوض)"""
    from services.advanced_journal_manager import AdvancedJournalEntryManager
    try:
        reason = request.form.get('reason', 'حذف القيد')

        AdvancedJournalEntryManager.delete_entry(
            entry_id=id,
            deleted_by=current_user.id,
            reason=reason
        )

        flash('✅ تم حذف القيد بنجاح', 'success')
        return redirect(url_for('ledger.journal_entries'))

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('handler failed')
        flash(f'❌ خطأ: حدث خطأ غير متوقع', 'danger')

    return redirect(url_for('ledger.view_entry', id=id))


@ledger_bp.route('/api/accounts/search')
@login_required
@permission_required('view_ledger')
def api_search_accounts():
    """API للبحث عن الحسابات"""
    query = request.args.get('q', '').strip()

    accounts = GLAccount.query.filter(
        GLAccount.is_active.is_(True),
        GLAccount.is_header.is_(False),
        db.or_(
            GLAccount.code.ilike(f'%{query}%'),
            GLAccount.name.ilike(f'%{query}%'),
            GLAccount.name_ar.ilike(f'%{query}%')
        )
    ).order_by(GLAccount.code).limit(20).all()

    return jsonify([{
        'id': acc.id,
        'code': acc.code,
        'name': acc.name,
        'name_ar': acc.name_ar,
        'full_name': acc.full_name,
        'type': acc.type,
        'balance': float(acc.get_balance())
    } for acc in accounts])


@ledger_bp.route('/api/calculate-journal-balance', methods=['POST'])
@login_required
@permission_required('view_ledger')
def api_calculate_journal_balance():
    """API لحساب توازن القيد اليدوي - Backend Calculation"""
    # Dual-check: read-only calculation serves ledger viewers and editors alike
    if not (current_user.has_permission('view_ledger') or current_user.has_permission('manage_ledger')):
        abort(403)
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        lines = data.get('lines', [])

        total_debit = Decimal('0')
        total_credit = Decimal('0')

        for line in lines:
            debit = Decimal(str(line.get('debit', 0) or 0))
            credit = Decimal(str(line.get('credit', 0) or 0))
            total_debit += debit
            total_credit += credit

        difference = abs(total_debit - total_credit)
        is_balanced = difference < Decimal('0.01') and total_debit > 0 and total_credit > 0

        return jsonify({
            'success': True,
            'total_debit': float(total_debit),
            'total_credit': float(total_credit),
            'difference': float(difference),
            'is_balanced': is_balanced
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ غير متوقع'
        }), 400


@ledger_bp.route('/cash-flow')
@login_required
@permission_required('view_ledger')
def cash_flow():
    """قائمة التدفقات النقدية"""
    # الحصول على الفترة (آخر شهر افتراضياً)
    today = date.today()
    default_start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    default_end = today.strftime('%Y-%m-%d')

    date_from = request.args.get('date_from', default_start, type=str)
    date_to = request.args.get('date_to', default_end, type=str)

    try:
        # المصدر الوحيد: قائمة التدفقات من دفتر الأستاذ — نفس البيانات
        # التي تعرضها صفحة التقارير (/reports/cash-flow) وتصديرها.
        gl_report = CashFlowService.generate_gl_cash_flow(date_from, date_to)
        report = CashFlowService.build_ledger_report(gl_report)

        return render_template('ledger/cash_flow.html',
                               report=report,
                               date_from=date_from,
                               date_to=date_to)
    except Exception as e:
        current_app.logger.exception('handler failed')
        flash(f'❌ فشل إنشاء قائمة التدفقات: حدث خطأ غير متوقع\n💡 تحقق من الفترة المحددة وحاول مرة أخرى.', 'danger')
        return redirect(url_for('ledger.index'))


@ledger_bp.route('/aging-analysis')
@login_required
@permission_required('view_ledger')
def aging_analysis():
    """تحليل عمر الذمم"""
    analysis_type = request.args.get('type', 'receivables', type=str)  # receivables or payables
    as_of_date = request.args.get('as_of_date', type=str)

    try:
        # نفس المصدر المستخدم في صفحة التقارير (/reports/receivables):
        # عملة الأساس، نفس الفلاتر، ونفس حدود الشرائح.
        if analysis_type == 'receivables':
            aging = _receivables_aging(as_of_date)
            title = 'تحليل عمر الذمم المدينة'
            report = {
                'as_of_date': aging['as_of_date'],
                'customers': aging['customers'],
                'customer_count': aging['customer_count'],
                'totals': {
                    **{bucket: float(aging['buckets'][bucket]) for bucket in AGING_BUCKETS},
                    'total': float(aging['total']),
                },
            }
        else:
            aging = _payables_aging(as_of_date)
            title = 'تحليل عمر الذمم الدائنة'
            report = {
                'as_of_date': aging['as_of_date'],
                'suppliers': aging['suppliers'],
                'supplier_count': aging['supplier_count'],
                'totals': {
                    **{bucket: float(aging['buckets'][bucket]) for bucket in AGING_BUCKETS},
                    'total': float(aging['total']),
                },
            }

        return render_template('ledger/aging_analysis.html',
                               report=report,
                               analysis_type=analysis_type,
                               title=title,
                               as_of_date=as_of_date or date.today().strftime('%Y-%m-%d'))
    except Exception as e:
        current_app.logger.exception('handler failed')
        flash(f'❌ فشل إنشاء تحليل الأعمار: حدث خطأ غير متوقع\n💡 تحقق من البيانات وحاول مرة أخرى.', 'danger')
        return redirect(url_for('ledger.index'))


# ==================== إدارة الحسابات والخزائن والتقارير ====================
# Canonical homes (merged from the retired admin_ledger blueprint):
# accounts CRUD, vaults, reports hub, settings, account JSON APIs.


@ledger_bp.route('/accounts')
@login_required
@admin_required
def accounts():
    """إدارة الحسابات المحاسبية"""
    accounts = GLAccount.query.order_by(GLAccount.code).all()
    return render_template('ledger/accounts.html', accounts=accounts)


@ledger_bp.route('/accounts/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_account():
    """إضافة حساب محاسبي جديد"""
    parent_accounts = GLAccount.query.filter_by(is_header=True).order_by(GLAccount.code).all()
    default_form = {'is_active': 'on'}

    if request.method == 'POST':
        try:
            code = (request.form.get('code') or '').strip()
            name = (request.form.get('name') or '').strip()
            name_ar = (request.form.get('name_ar') or '').strip()
            account_type = (request.form.get('type') or '').strip()
            parent_id_raw = (request.form.get('parent_id') or '').strip()
            parent_id = int(parent_id_raw) if parent_id_raw else None
            # NOTE: الفاصلة الزائدة داخل القوس كانت تُنتج tuple ('ILS',)
            # فيفشل حفظ الحساب على SQLite ("type 'tuple' is not supported").
            currency = (request.form.get('currency') or __import__('services.currency_service', fromlist=['CurrencyService']).CurrencyService.get_base_currency())
            is_header = 'on' in request.form.getlist('is_header')
            is_active = 'on' in request.form.getlist('is_active')
            description = request.form.get('description')

            if not account_type:
                flash('⚠️ يرجى اختيار نوع الحساب.', 'warning')
                form_values = request.form.to_dict()
                form_values['is_header'] = 'on' if is_header else 'off'
                form_values['is_active'] = 'on' if is_active else 'off'
                return render_template('ledger/add_account.html',
                                       parent_accounts=parent_accounts,
                                       form_data=form_values)

            # F3: نوع الحساب يُتحقَّق منه في المسار قبل الإسناد (نفس قائمة
            # النموذج models/gl.py::GLAccount.VALID_TYPES) — وإلا رفضه
            # مُتحقِّق النموذج برسالة "خطأ غير متوقع".
            account_type = account_type.lower()
            if account_type not in GLAccount.VALID_TYPES:
                valid_types = ', '.join(sorted(GLAccount.VALID_TYPES))
                flash(
                    f'❌ نوع حساب غير صالح. الأنواع المسموحة: {valid_types}',
                    'danger')
                form_values = request.form.to_dict()
                form_values['is_header'] = 'on' if is_header else 'off'
                form_values['is_active'] = 'on' if is_active else 'off'
                return render_template('ledger/add_account.html',
                                       parent_accounts=parent_accounts,
                                       form_data=form_values)

            # التحقق من عدم تكرار الكود
            existing = GLAccount.query.filter_by(code=code).first()
            if existing:
                flash('❌ كود الحساب موجود مسبقاً', 'danger')
                form_values = request.form.to_dict()
                form_values['is_header'] = 'on' if is_header else 'off'
                form_values['is_active'] = 'on' if is_active else 'off'
                return render_template('ledger/add_account.html',
                                       parent_accounts=parent_accounts,
                                       form_data=form_values)

            # حساب المستوى
            level = 0
            if parent_id:
                parent = db.session.get(GLAccount, parent_id)
                level = parent.level + 1 if parent else 0

            account = GLAccount(
                code=code,
                name=name,
                name_ar=name_ar,
                type=account_type,
                parent_id=parent_id,
                currency=currency,
                is_header=is_header,
                is_active=is_active,
                level=level,
                description=description
            )

            db.session.add(account)
            db.session.commit()

            create_audit_log('create', 'gl_accounts', account.id)
            flash(f'✅ تم إنشاء الحساب {account.full_name} بنجاح', 'success')
            return redirect(url_for('ledger.accounts'))

        except ValueError as e:
            # F3: رسائل النموذج مكتوبة للمستخدم (نوع غير صالح) — تُعرض كما
            # هي بدل "حدث خطأ غير متوقع".
            db.session.rollback()
            current_app.logger.info('GL account create rejected: %s', e)
            flash(f'❌ {e}', 'danger')
            form_values = request.form.to_dict()
            form_values['is_header'] = 'on' if 'on' in request.form.getlist('is_header') else 'off'
            form_values['is_active'] = 'on' if 'on' in request.form.getlist('is_active') else 'off'
            return render_template('ledger/add_account.html',
                                   parent_accounts=parent_accounts,
                                   form_data=form_values)
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('handler failed')
            flash(f'❌ خطأ: حدث خطأ غير متوقع', 'danger')
            form_values = request.form.to_dict()
            form_values['is_header'] = 'on' if 'on' in request.form.getlist('is_header') else 'off'
            form_values['is_active'] = 'on' if 'on' in request.form.getlist('is_active') else 'off'
            return render_template('ledger/add_account.html',
                                   parent_accounts=parent_accounts,
                                   form_data=form_values)

    return render_template('ledger/add_account.html',
                           parent_accounts=parent_accounts,
                           form_data=default_form)


@ledger_bp.route('/accounts/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_account(id):
    """تعديل حساب محاسبي"""
    account = db.get_or_404(GLAccount, id)
    parent_accounts = GLAccount.query.filter_by(is_header=True).order_by(GLAccount.code).all()

    if request.method == 'POST':
        try:
            # F3: نوع الحساب يُتحقَّق منه في المسار قبل إسناده، تماماً كما
            # يفعل النموذج (models/gl.py::_validate_type) — وإلا ظهر خطأ
            # "غير متوقع" بدل رسالة تشرح الأنواع المسموحة.
            account_type = (request.form.get('type') or '').strip().lower()
            if account_type not in GLAccount.VALID_TYPES:
                valid_types = ', '.join(sorted(GLAccount.VALID_TYPES))
                flash(
                    f'❌ نوع حساب غير صالح. الأنواع المسموحة: {valid_types}',
                    'danger')
                return render_template('ledger/edit_account.html',
                                       account=account,
                                       parent_accounts=parent_accounts)

            account.code = request.form.get('code')
            account.name = request.form.get('name')
            account.name_ar = request.form.get('name_ar')
            account.type = account_type
            account.parent_id = request.form.get('parent_id') or None
            account.currency = (request.form.get('currency') or __import__('services.currency_service', fromlist=['CurrencyService']).CurrencyService.get_base_currency())
            account.is_header = bool(request.form.get('is_header'))
            account.description = request.form.get('description')
            account.is_active = bool(request.form.get('is_active'))

            # حساب المستوى
            if account.parent_id:
                parent = db.session.get(GLAccount, account.parent_id)
                account.level = parent.level + 1 if parent else 0
            else:
                account.level = 0

            db.session.commit()

            create_audit_log('update', 'gl_accounts', account.id)
            flash(f'✅ تم تحديث الحساب {account.full_name} بنجاح', 'success')
            return redirect(url_for('ledger.accounts'))

        except ValueError as e:
            # F3: حارس النموذج (models/gl.py::_guard_system_account_update)
            # يرفض تعديل كود/نوع حساب مُبذَر — الرسالة مكتوبة للمستخدم
            # ف تُعرض كما هي بدل "حدث خطأ غير متوقع".
            db.session.rollback()
            current_app.logger.info('GL account update rejected: %s', e)
            flash(f'❌ {e}', 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('handler failed')
            flash(f'❌ خطأ: حدث خطأ غير متوقع', 'danger')

    parent_accounts = GLAccount.query.filter_by(is_header=True).order_by(GLAccount.code).all()
    return render_template('ledger/edit_account.html', account=account, parent_accounts=parent_accounts)


@ledger_bp.route('/accounts/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_account(id):
    """حذف حساب محاسبي"""
    account = db.get_or_404(GLAccount, id)

    try:
        # التحقق من وجود قيود مرتبطة
        has_entries = GLJournalLine.query.filter_by(account_id=id).first()
        if has_entries:
            flash('❌ لا يمكن حذف الحساب لوجود قيود مرتبطة به', 'danger')
            return redirect(url_for('ledger.accounts'))

        # التحقق من وجود حسابات فرعية
        has_children = GLAccount.query.filter_by(parent_id=id).first()
        if has_children:
            flash('❌ لا يمكن حذف الحساب لوجود حسابات فرعية مرتبطة به', 'danger')
            return redirect(url_for('ledger.accounts'))

        db.session.delete(account)
        db.session.commit()

        create_audit_log('delete', 'gl_accounts', id)
        flash(f'✅ تم حذف الحساب {account.full_name} بنجاح', 'success')

    except ValueError as e:
        # F3: حارس النموذج (models/gl.py::_guard_system_account_delete) يرفض
        # حذف حساب مُبذَر من دليل الحسابات الأساسي — تُعرض رسالته كما هي.
        db.session.rollback()
        current_app.logger.info('GL account delete rejected: %s', e)
        flash(f'❌ {e}', 'danger')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('handler failed')
        flash(f'❌ خطأ: حدث خطأ غير متوقع', 'danger')

    return redirect(url_for('ledger.accounts'))


@ledger_bp.route('/vaults')
@login_required
@admin_required
def vaults():
    """إدارة الصناديق والمحافظ"""
    vaults = PaymentVault.query.all()
    return render_template('ledger/vaults.html', vaults=vaults)


@ledger_bp.route('/reports')
@login_required
@permission_required('view_ledger')
def reports():
    """مركز التقارير المالية"""
    return render_template('ledger/reports.html')


@ledger_bp.route('/settings')
@login_required
@admin_required
def settings():
    """إعدادات النظام المحاسبي"""
    return render_template('ledger/settings.html')


@ledger_bp.route('/api/account-balance/<int:account_id>')
@login_required
@admin_required
def api_account_balance(account_id):
    """API للحصول على رصيد حساب"""
    account = db.get_or_404(GLAccount, account_id)
    balance = account.get_balance()

    return jsonify({
        'account_code': account.code,
        'account_name': account.full_name,
        'balance': float(balance),
        'balance_formatted': f"{balance:,.2f}"
    })


@ledger_bp.route('/api/account-statement/<int:account_id>')
@login_required
@admin_required
def api_account_statement(account_id):
    """API لكشف حساب"""
    account = db.get_or_404(GLAccount, account_id)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    statement = GLService.get_account_statement(account_id, date_from, date_to)

    # get_account_statement includes the ORM object itself for templates;
    # strip it before serializing to JSON.
    statement.pop('account', None)

    return jsonify({
        'account': {
            'code': account.code,
            'name': account.full_name
        },
        'statement': statement
    })
