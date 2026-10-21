"""
Sub-Ledger Reconciliation Service — مطابقة الذمم الفرعية مع الأستاذ العام
=============================================================================

Proves the STRICT MATCH RULE to the cent (0.01):

    Σ(sub-ledger recomputed from source documents)
        == GL control account(s) posted net
        == denormalized entity balance column(s)

F1 — المصدر الواحد للاشتقاق (single source of truth)
----------------------------------------------------
كان هذا الملف يشتقّ الذمم بصيغة خاصة به:

  * AR = Σ(amount_base − paid_amount_base) على الفواتير المؤكدة.
  * AP = Σ(amount_base − paid_amount) على المشتريات المؤكدة.

بينما التطبيق نفسه يستعمل:

  * models.customer.derive_customer_balance — الرصيد الافتتاحي + الفواتير
    المؤكدة النشطة − المرتجعات المعتمدة − الاستردادات المنفصلة + تعديلات
    الشيكات Legacy.
  * models.supplier.derive_supplier_totals — المشتريات المؤكدة − المسدّد
    (على مستوى الفاتورة والمورد) − الاستردادات، + الرصيد الافتتاحي.

النتيجة: فرق دائم (false break) بين هذا التقرير والأرقام التي يعرضها
التطبيق. الآن يستعمل هذا الملف الدالتين نفسها — لا صيغة ثالثة.

  AR:  لكل عميل نشط، models.customer.derive_customer_balance
       vs GLAccount(AR_CONTROL, fallback '1130') مدينة-الطبيعة
       vs عمود Customer.balance.
  AP:  لكل مورد نشط، models.supplier.derive_supplier_totals
       vs GLAccounts('2115' + '2110') دائنة-الطبيعة
       vs Supplier.total_purchases_aed − total_paid_aed (+ الافتتاحي).

Read-only audit service: detects and reports drift; it never mutates ledgers.
Conventions inherited from utils.balance_checker / aging_analysis_service:
active customers/suppliers only; confirmed sales; purchases by status
(Purchase has no is_active column); tolerance |delta| ≤ 0.01 inclusive.

بنود التسوية المعروفة (reconciling_items)
--------------------------------------------
بند التسوية = فرق **متوقّع** بين الأستاذ والذمم الفرعية (توقيت/ترحيل/
نطاق) وليس كسراً حقيقياً. يُعرض كل بند بمبلغه وإشارته ليعرف المحاسب
الفرق الحقيقي من الفرق المتوقع:

  * pending_incoming_cheques (+): الأستاذ يقيّد الدائن على حساب الذمم عند
    استلام الشيك (نقل إلى "شيكات تحت التحصيل") بينما الفاتورة تبقى مفتوحة
    لأن الشيك لم يُصرف ⇒ الفرق يختفي عند صرفه.
  * unallocated_receipts (+): سند قبض يقيّد الدائن على حساب الذمم دون أن
    يسوّي أي فاتورة (دفعة مقدّمة/زائدة).
  * pending_outgoing_cheques (+): إصدار الشيك الصادر يُقيَّد مديناً على حساب
    الذمم الدائنة بينما فاتورة الشراء تبقى مفتوحة حتى صرف الشيك.
  * opening_balances (+): الرصيد الافتتاحي مُرحَّل من نظام سابق — ليس
    قيداً في الأستاذ العام إلا إذا رُحّل يدوياً.
  * inactive_parties (−): الأستاذ يحتفظ بمستندات الأطراف المعطّلة بينما
    نطاق الذمم الفرعية = الأطراف النشطة فقط.

الإشارة +1 تعني: يُضاف المبلغ إلى رصيد حساب الضبط ليطابق الذمم الفرعية.
الإشارة −1 تعني: يُطرح.

معادلة التوازن:
    control_difference    = control_balance − subledger_sum
    adjusted_difference   = control_difference + Σ(sign × amount)
    balanced ⇐ لا كسر على مستوى الكيان
              ∧ |column_sum − subledger_sum| ≤ 0.01
              ∧ (|control_difference| ≤ 0.01            # لا فرق أصلاً
                أو |adjusted_difference| ≤ 0.01)        # الفرق مفهوم بالكامل
"""

import logging
from decimal import Decimal

from extensions import db
from utils.balance_checker import TOLERANCE, get_control_account_balance, to_decimal

logger = logging.getLogger(__name__)

# CENTRAL CONTRACT — dynamic CoA resolution (Agent 1's module consumed defensively).
# If services.account_resolution is not importable yet, literal codes are used as
# FALLBACK DEFAULTS so parallel rollout never blocks. Defaults equal today's codes.
try:
    from services.account_resolution import AccountResolver, AccountRole
except ImportError:  # pragma: no cover - resolver ships in Agent 1's turn
    AccountResolver = None  # type: ignore[assignment,misc]
    AccountRole = None  # type: ignore[assignment,misc]

DEFAULT_AR_CONTROL_CODES = ['1130']
DEFAULT_AP_CONTROL_CODES = ['2115', '2110']
# Merchant ('2115') and partner ('3350') invoices bypass the plain AR control;
# the AR proof must include those buckets or merchant/partner customers always
# look like breaks.
DEFAULT_AR_MERCHANT_BUCKETS = ['2115', '3350']

# حالات الشيك التي تعني: استُلم الشيك ولم يُصرف بعد (بلا تسوية للفاتورة).
_PENDING_CHEQUE_STATUSES = ('pending', 'under_collection', 'deposited')


def _resolve_role_codes(role_value, fallback_codes):
    """
    Resolve a role to its account code via the central resolver contract,
    keeping any additional fallback control codes that are still distinct.
    """
    if AccountResolver is not None and AccountRole is not None:
        try:
            code = AccountResolver.resolve(AccountRole(role_value))
            if code:
                return [code] + [c for c in fallback_codes if c != code]
        except Exception as exc:
            logger.warning(
                f'AccountResolver failed for role {role_value}: {exc} — using literal fallback'
            )
    return list(fallback_codes)


def _ar_control_codes():
    """AR scope = plain control ('1130') + partner/merchant buckets.

    Consumes sale_service.merchant_receivable_codes() defensively so both
    sides of the contract stay in sync; falls back to today's literals.
    """
    try:
        from services.sale_service import merchant_receivable_codes
        buckets = [str(c) for c in merchant_receivable_codes() if c]
    except Exception as exc:
        logger.warning(
            f'merchant_receivable_codes unavailable ({exc}) — using literal buckets'
        )
        buckets = []

    codes = []
    for code in (
        _resolve_role_codes('AR_CONTROL', DEFAULT_AR_CONTROL_CODES)
        + buckets
        + DEFAULT_AR_MERCHANT_BUCKETS
    ):
        if code not in codes:
            codes.append(code)
    return codes


def _ap_control_codes():
    """AP scope per audit mandate: merchants payable ('2115') + AP control ('2110')."""
    codes = []
    for code in (
        _resolve_role_codes('MERCHANTS_PAYABLE', ['2115'])
        + _resolve_role_codes('AP_CONTROL', ['2110'])
    ):
        if code not in codes:
            codes.append(code)
    return codes


def _q2(value):
    """Quantize reported money to 0.01."""
    return Decimal(value).quantize(Decimal('0.01'))


def _ar_debit_normal_balance(account_codes):
    """Σ(debit − credit) across the AR control scope (base currency).

    Merchant ('2115') and partner ('3350') buckets are DEBITED by the sale
    flow even though the seeded CoA types them liability/equity. Treating the
    entire AR scope debit-normal matches the receivable direction of both the
    sub-ledger and Customer.balance; plain AR control ('1130', asset) is
    numerically identical to the generic signed helper.
    """
    from sqlalchemy import func

    from models import GLAccount, GLJournalLine

    wanted = [str(c) for c in (account_codes or []) if c]
    if not wanted:
        return Decimal('0')

    rows = (
        db.session.query(
            GLAccount.code,
            func.coalesce(func.sum(GLJournalLine.amount_base), 0),
        )
        .outerjoin(GLJournalLine, GLJournalLine.account_id == GLAccount.id)
        .filter(GLAccount.code.in_(wanted))
        .group_by(GLAccount.code)
        .all()
    )

    total = Decimal('0')
    found = set()
    for code, raw_net in rows:
        found.add(code)
        total += to_decimal(raw_net)

    missing = [c for c in wanted if c not in found]
    if missing:
        logger.warning(f'AR control account(s) missing from CoA: {missing}')

    return total


# ═══════════════════════════════════════════════════════════════════════════
# بنود التسوية المعروفة (reconciling items)
# ═══════════════════════════════════════════════════════════════════════════

def _reconciling_item(code, label, amount, sign, note=''):
    """بند تسوية معروف: فرق متوقّع بين الأستاذ والذمم الفرعية.

    sign = +1 ⇒ يُضاف المبلغ إلى رصيد حساب الضبط ليطابق الذمم الفرعية،
                sign = −1 ⇒ يُطرح منه.
    """
    return {
        'code': code,
        'label': label,
        'amount': _q2(amount),
        'sign': int(sign),
        'note': note,
    }


def _reconciling_total(items):
    """Σ(sign × amount) — الأثر الصافي لبنود التسوية على رصيد الحساب."""
    total = Decimal('0')
    for item in items or []:
        total += Decimal(str(item.get('sign', 1))) * to_decimal(item.get('amount'))
    return total


def _pending_cheques(cheque_type, tenant_id=None):
    """Σ مبلغ الشيكات (وارد/صادر) المستلَمة التي لم تُصرف بعد.

    الأستاذ يقيّد هذه الشيكات على حساب الذمم وقت الاستلام/الإصدار بينما
    المستند الأصلي يبقى مفتوحاً ⇒ فرق توقّع معروف حتى صرف الشيك.

    يُشترط وجود قيد محاسبي فعلي (gl_journal_entry_id) حتى لا يُحسب شيك لم
    يُقيَّد أصلاً، ويُستبعد الشيك المرتد/الملغي/المؤرشف لأن عكس قيده
    أعاد الذمم إلى حساب الضبط.
    """
    from sqlalchemy import func

    from models import Cheque

    query = db.session.query(
        func.coalesce(func.sum(Cheque.amount_base), 0)
    ).filter(
        Cheque.cheque_type == cheque_type,
        Cheque.status.in_(_PENDING_CHEQUE_STATUSES),
        Cheque.is_active.is_(True),
        Cheque.gl_journal_entry_id.isnot(None),
    )
    if tenant_id is not None:
        query = query.filter(Cheque.tenant_id == tenant_id)

    return to_decimal(query.scalar())


def _unallocated_receipts(tenant_id=None):
    """Σ جزء السندات المؤكدة الذي لم يُوزَّع على أي فاتورة.

    السند المؤكد يُقيَّد دائناً على حساب الذمم، فإن لم يوزَّع على فاتورة
    (دفعة مقدّمة/زائدة) بقي الفرق بين الأستاذ والذمم الفرعية.
    """
    from models import Receipt

    query = Receipt.query.filter(
        Receipt.payment_confirmed.is_(True),
        Receipt.direction == 'incoming',
        Receipt.customer_id.isnot(None),
    )
    if tenant_id is not None:
        query = query.filter(Receipt.tenant_id == tenant_id)

    total = Decimal('0')
    for receipt in query.all():
        try:
            allocations = receipt.get_allocations() or []
        except Exception:
            allocations = []
        allocated = Decimal('0')
        for alloc in allocations:
            try:
                allocated += to_decimal(alloc.get('amount_base'))
            except Exception:
                continue
        leftover = to_decimal(receipt.amount_base) - allocated
        if leftover > 0:
            total += leftover
    return total


class SubLedgerReconciliation:
    """Three-way sub-ledger ↔ GL control ↔ balance-column proof (AR & AP)."""

    # ------------------------------------------------------------------ AR

    @staticmethod
    def reconcile_receivables(tenant_id=None):
        """
        Reconcile customer receivables.

        المصدر الوحيد: models.customer.derive_customer_balance — فلا تُحسب
        الذمم بصيغة ثانية تختلف عن التطبيق.

        Returns dict: {section:'AR', control_accounts, control_breakdown,
        control_balance, subledger_sum, column_sum, control_difference,
        reconciling_items, reconciling_total, adjusted_control_balance,
        adjusted_control_difference, breaks:[{entity, entity_id, expected,
        stored, delta}], balanced}
        """
        from models import Customer
        from models.customer import derive_customer_balance

        codes = _ar_control_codes()

        # populate_existing: model listeners mutate balances via raw SQL outside
        # the identity map — force a fresh read so stored columns are current.
        customers = (
            Customer.query
            .order_by(Customer.id)
            .populate_existing()
            .all()
        )
        if tenant_id is not None:
            customers = [c for c in customers if c.tenant_id == tenant_id]

        connection = db.session.connection()

        subledger_sum = Decimal('0')
        column_sum = Decimal('0')
        opening_sum = Decimal('0')
        inactive_sum = Decimal('0')
        breaks = []
        for customer in customers:
            expected = derive_customer_balance(customer.id, connection=connection)

            if not customer.is_active:
                # خارج نطاق الذمم الفرعية (نشط فقط) — يُعرض كبند تسوية
                inactive_sum += expected
                continue

            stored = to_decimal(customer.balance)
            subledger_sum += expected
            column_sum += stored
            opening_sum += customer.get_opening_balance_base()

            delta = stored - expected
            if abs(delta) > TOLERANCE:
                breaks.append({
                    'entity': customer.name,
                    'entity_id': customer.id,
                    'expected': _q2(expected),
                    'stored': _q2(stored),
                    'delta': _q2(delta),
                })
                logger.warning(
                    f'AR break: customer#{customer.id} ({customer.name}) '
                    f'expected={expected} stored={stored} delta={delta}'
                )

        control_balance = _ar_debit_normal_balance(codes)

        # Section detail lines: one entry per control bucket so reviewers can
        # see exactly which bucket carries (or misses) the value.
        breakdown = [
            {'account_code': code, 'balance': _q2(_ar_debit_normal_balance([code]))}
            for code in codes
        ]

        reconciling_items = [
            _reconciling_item(
                'pending_incoming_cheques',
                'شيكات وارد تحت التحصيل (لم تُصرف بعد)',
                _pending_cheques('incoming', tenant_id=tenant_id),
                1,
                'الأستاذ يقيّد الدائن على حساب الذمم عند استلام الشيك '
                'والفاتورة تبقى مفتوحة حتى صرفه.',
            ),
            _reconciling_item(
                'unallocated_receipts',
                'سندات قبض مؤكّدة لم تُوزَّع على فواتير',
                _unallocated_receipts(tenant_id=tenant_id),
                1,
                'السند يقيّد الدائن على حساب الذمم دون أن يسوّي فاتورة.',
            ),
            _reconciling_item(
                'opening_balances',
                'أرصدة افتتاحية مُرحّلة (خارج قيود الأستاذ)',
                opening_sum,
                1,
                'الرصيد الافتتاحي ليس قيداً في الأستاذ إلا إذا رُحّل يدوياً.',
            ),
            _reconciling_item(
                'inactive_customers',
                'ذمم عملاء غير نشطين (خارج نطاق المطابقة)',
                inactive_sum,
                -1,
                'الأستاذ يحتفظ بمستندات العميل المعطّل، والمطابقة على النشطين.',
            ),
        ]
        reconciling_total = _reconciling_total(reconciling_items)

        control_difference = control_balance - subledger_sum
        adjusted_control_balance = control_balance + reconciling_total
        adjusted_control_difference = adjusted_control_balance - subledger_sum

        balanced = (
            not breaks
            and abs(column_sum - subledger_sum) <= TOLERANCE
            and (
                abs(control_difference) <= TOLERANCE
                or abs(adjusted_control_difference) <= TOLERANCE
            )
        )

        return {
            'section': 'AR',
            'control_accounts': codes,
            'control_breakdown': breakdown,
            'control_balance': _q2(control_balance),
            'subledger_sum': _q2(subledger_sum),
            'column_sum': _q2(column_sum),
            'control_difference': _q2(control_difference),
            'reconciling_items': reconciling_items,
            'reconciling_total': _q2(reconciling_total),
            'adjusted_control_balance': _q2(adjusted_control_balance),
            'adjusted_control_difference': _q2(adjusted_control_difference),
            'breaks': breaks,
            'balanced': balanced,
        }

    # ------------------------------------------------------------------ AP

    @staticmethod
    def reconcile_payables(tenant_id=None):
        """
        Mirror reconciliation for suppliers/AP.

        F1: المصدر الوحيد هو models.supplier.derive_supplier_totals
        (المشتريات المؤكدة − المسدّد على مستوى الفاتورة والمورد −
        الاستردادات) + الرصيد الافتتاحي (Supplier.get_opening_balance_base).

        Supplier has no single balance column — its denormalized state is
        (total_purchases_aed − total_paid_aed) ويُقارَن بالرصيد المشتقّ
        + الرصيد الافتتاحي (مُضمَّن في الطرفين حتى لا يُحسب مرتين).
        """
        from models import Supplier
        from models.supplier import derive_supplier_totals

        codes = _ap_control_codes()

        # populate_existing: see reconcile_receivables (raw-SQL listener writes).
        suppliers = (
            Supplier.query
            .order_by(Supplier.id)
            .populate_existing()
            .all()
        )
        if tenant_id is not None:
            suppliers = [s for s in suppliers if s.tenant_id == tenant_id]

        subledger_sum = Decimal('0')
        column_sum = Decimal('0')
        opening_sum = Decimal('0')
        inactive_sum = Decimal('0')
        breaks = []
        for supplier in suppliers:
            total_purchases, total_paid = derive_supplier_totals(supplier.id)
            opening = supplier.get_opening_balance_base()
            expected = total_purchases - total_paid + opening

            if not supplier.is_active:
                # خارج نطاق الذمم الفرعية (نشط فقط) — يُعرض كبند تسوية
                inactive_sum += expected
                continue

            stored = (
                to_decimal(supplier.total_purchases_aed)
                - to_decimal(supplier.total_paid_aed)
            ) + opening
            subledger_sum += expected
            column_sum += stored
            opening_sum += opening

            delta = stored - expected
            if abs(delta) > TOLERANCE:
                breaks.append({
                    'entity': supplier.name,
                    'entity_id': supplier.id,
                    'expected': _q2(expected),
                    'stored': _q2(stored),
                    'delta': _q2(delta),
                })
                logger.warning(
                    f'AP break: supplier#{supplier.id} ({supplier.name}) '
                    f'expected={expected} stored={stored} delta={delta}'
                )

        control_balance = get_control_account_balance(codes)

        # Section detail lines per AP control bucket (merchants vs AP control).
        breakdown = [
            {'account_code': code, 'balance': _q2(get_control_account_balance([code]))}
            for code in codes
        ]

        reconciling_items = [
            _reconciling_item(
                'pending_outgoing_cheques',
                'شيكات صادرة لم تُصرف بعد',
                _pending_cheques('outgoing', tenant_id=tenant_id),
                1,
                'إصدار الشيك يقيّده مديناً على حساب الذمم الدائنة '
                'وفاتورة الشراء تبقى مفتوحة حتى صرفه.',
            ),
            _reconciling_item(
                'opening_balances',
                'أرصدة افتتاحية مُرحّلة (خارج قيود الأستاذ)',
                opening_sum,
                1,
                'الرصيد الافتتاحي ليس قيداً في الأستاذ إلا إذا رُحّل يدوياً.',
            ),
            _reconciling_item(
                'inactive_suppliers',
                'ذمم موردين غير نشطين (خارج نطاق المطابقة)',
                inactive_sum,
                -1,
                'الأستاذ يحتفظ بمستندات المورد المعطّل، والمطابقة على النشطين.',
            ),
        ]
        reconciling_total = _reconciling_total(reconciling_items)

        control_difference = control_balance - subledger_sum
        adjusted_control_balance = control_balance + reconciling_total
        adjusted_control_difference = adjusted_control_balance - subledger_sum

        balanced = (
            not breaks
            and abs(column_sum - subledger_sum) <= TOLERANCE
            and (
                abs(control_difference) <= TOLERANCE
                or abs(adjusted_control_difference) <= TOLERANCE
            )
        )

        return {
            'section': 'AP',
            'control_accounts': codes,
            'control_breakdown': breakdown,
            'control_balance': _q2(control_balance),
            'subledger_sum': _q2(subledger_sum),
            'column_sum': _q2(column_sum),
            'control_difference': _q2(control_difference),
            'reconciling_items': reconciling_items,
            'reconciling_total': _q2(reconciling_total),
            'adjusted_control_balance': _q2(adjusted_control_balance),
            'adjusted_control_difference': _q2(adjusted_control_difference),
            'breaks': breaks,
            'balanced': balanced,
        }

    # ----------------------------------------------------------------- All

    @staticmethod
    def reconcile_all(tenant_id=None):
        """Run both sections; returns [AR report, AP report]."""
        return [
            SubLedgerReconciliation.reconcile_receivables(tenant_id=tenant_id),
            SubLedgerReconciliation.reconcile_payables(tenant_id=tenant_id),
        ]
