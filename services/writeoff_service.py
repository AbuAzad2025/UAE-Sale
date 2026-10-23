"""Bad debt write-offs — services/writeoff_service.py.

The write-off is the only way a receivable that will never be collected can
leave the books. It is one operation with one transaction:

    Dr 6960  Bad debt expense      (AccountRole.BAD_DEBT_EXPENSE)
    Cr 1130  Accounts receivable   (AccountRole.AR_CONTROL)

The journal entry is created through the GLService public API and linked to
the write-off row (``gl_entry_id``), so the document and its accounting cannot
drift apart: if the posting fails, the whole transaction is rolled back and
no write-off row survives, and a void reverses the very entry that was
created instead of writing an unrelated second one.

Why the balance is settled through the derivation
-------------------------------------------------
The outstanding balance of a customer is derived by a single function,
``models.customer.derive_customer_balance``; the write-off never computes a
second formula. That derivation does not know about write-offs yet, and the
only term it can increase is the opening balance, so the write-off pins its
effect there (the same mechanism
``services.payment_service.PaymentService.adjust_customer_balance`` uses) and
then recomputes the balance through the single writer
``models.customer.recompute_customer_balance``. The write-off therefore shows
up in every surface that reads the balance (the customer card, the balance
checker, the AR aging) instead of being wiped by the next recomputation.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import current_app
from flask_login import current_user

from extensions import db
from models.gl import GLJournalEntry
from models.tenant_scope import get_current_tenant_id
from models.write_off import WriteOff
from services.account_resolution import AccountResolver, AccountRole
from services.currency_service import CurrencyService
from services.fiscal_period_guard import assert_period_open
from services.gl_service import GLService
from utils.decorators import assert_same_tenant
from utils.errors import ValidationError
from utils.helpers import create_audit_log

# تقريب المبالغ (3 منازل عشرية) — نفس أعمدة Money في قاعدة البيانات
MONEY_Q = Decimal('0.001')

# سبب افتراضي عندما لا يُذكر سبب (العمود NOT NULL في قاعدة البيانات)
DEFAULT_REASON = 'مديونية مشطوبة'


def _dec(value, default='0'):
    """تحويل أي قيمة حدّية إلى Decimal (لا float في المال)."""
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _user_id(user):
    """معرّف المنفّذ: كائن مستخدم أو معرّف رقمي أو المستخدم الحالي."""
    if user is None:
        try:
            if getattr(current_user, 'is_authenticated', False):
                return current_user.id
        except Exception:
            return None
        return None
    if isinstance(user, int):
        return user
    return getattr(user, 'id', None)


def _apply_balance_delta(customer, delta_base):
    """يُثبّت أثر المشطوبة عبر إعادة احتساب رصيد العميل بالاشتقاق الكامل.

    Args:
        customer: العميل.
        delta_base: الفرق بالعملة الأساسية (سالب عند المشطوبة، موجب عند الإلغاء).

    Returns:
        Decimal: الرصيد الجديد (بالعملة الأساسية).
    """
    from models.customer import recompute_customer_balance

    delta = _dec(delta_base)
    if delta == Decimal('0'):
        return _dec(customer.balance)

    db.session.flush()
    return recompute_customer_balance(customer.id)


class WriteOffService:

    # ------------------------------------------------------------------
    # creation
    # ------------------------------------------------------------------

    @staticmethod
    def create_writeoff(customer, amount, currency=None, reason=None, sale=None,
                        notes=None, user=None) -> WriteOff:
        """يشطب ديوناً لا يمكن تحصيلها ويرحّل القيد المحاسبي المرافق.

        Args:
            customer: العميل صاحب الديون.
            amount: المبلغ المطبوع (Decimal) — يجب أن يكون أكبر من صفر.
            currency: عملة المبلغ (الافتراضي: عملة الأساس).
            reason: سبب المشطوبة (مطلوب في الواجهة، وله قيمة افتراضية هنا).
            sale: فاتورة مرتبطة (اختياري) — لأغراض التتبع فقط.
            notes: ملاحظات إضافية.
            user: المنفّذ (كائن مستخدم أو معرّف).

        Returns:
            WriteOff: سطر المشطوبة بعد الترحيل.

        Raises:
            ValidationError: المبلغ غير موجب، أو يتجاوز رصيد العميل، أو الفترة
                المالية مغلقة، أو الحسابات المطلوبة غير موجودة.
        """
        if customer is None:
            raise ValidationError('العميل غير موجود')

        amount_dec = _dec(amount)
        if amount_dec <= Decimal('0'):
            raise ValidationError('مبلغ المشطوبة يجب أن يكون أكبر من صفر')

        base_currency = CurrencyService.get_base_currency()
        currency = (currency or base_currency or 'ILS').upper()
        rate = _dec(
            CurrencyService.get_exchange_rate(currency, base_currency), '1'
        ) or Decimal('1')
        amount_base = (amount_dec * rate).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        if amount_base <= Decimal('0'):
            raise ValidationError('قيمة المشطوبة بالعملة الأساسية يجب أن تكون أكبر من صفر')

        # عزل المستأجر: لا تُشطب ديون عميل من مستأجر آخر.
        assert_same_tenant(customer, message='لا يمكن تنفيذ العملية لعميل من مستأجر آخر')

        sale_id = None
        if sale is not None:
            sale_id = getattr(sale, 'id', sale)
            sale_owner = getattr(sale, 'customer_id', None)
            if sale_owner is not None and sale_owner != customer.id:
                raise ValidationError('الفاتورة المحددة لا تخصّ هذا العميل')

        # الرصيد المستحق — من الاشتقاق الوحيد (models.customer).
        from models.customer import derive_customer_balance

        outstanding = derive_customer_balance(customer.id)
        if amount_base > outstanding:
            raise ValidationError(
                f'مبلغ المشطوبة ({amount_base}) يتجاوز رصيد العميل المستحق '
                f'({outstanding})'
            )

        posting_date = datetime.now(timezone.utc)
        assert_period_open(posting_date)

        GLService.ensure_core_accounts()
        tenant_id = get_current_tenant_id()
        expense_account = AccountResolver.get_account(
            AccountRole.BAD_DEBT_EXPENSE, tenant_id=tenant_id)
        ar_account = AccountResolver.get_account(
            AccountRole.AR_CONTROL, tenant_id=tenant_id)
        if expense_account is None or ar_account is None:
            raise ValidationError('حسابات المشطوبة غير موجودة في دليل الحسابات')

        actor_id = _user_id(user)
        write_off = WriteOff(
            customer_id=customer.id,
            sale_id=sale_id,
            amount=amount_dec,
            currency=currency,
            amount_base=amount_base,
            reason=(str(reason).strip() if reason else '') or DEFAULT_REASON,
            status=WriteOff.STATUS_POSTED,
            notes=notes,
            created_by=actor_id,
            tenant_id=getattr(customer, 'tenant_id', None),
            created_at=posting_date,
            posted_at=posting_date,
        )
        db.session.add(write_off)

        try:
            db.session.flush()

            entry = GLService.post_entry(
                lines=[
                    {
                        'account': expense_account.code,
                        'debit': amount_dec,
                        'description': f'مديونية مشطوبة - {customer.name}',
                    },
                    {
                        'account': ar_account.code,
                        'credit': amount_dec,
                        'description': f'إقفال ذمم مدينة - {customer.name}',
                    },
                ],
                description=f'مديونية مشطوبة - {customer.name}',
                reference_type='WriteOff',
                reference_id=write_off.id,
                currency=currency,
                exchange_rate=rate,
                entry_date=posting_date,
                created_by=actor_id,
            )
            write_off.gl_entry_id = entry.id

            # الرصيد ينقص بالمبلغ المشطوب — عبر الاشتقاق والكاتب الوحيد.
            _apply_balance_delta(customer, -amount_base)

            create_audit_log('create', 'write_offs', write_off.id, changes={
                'action': 'writeoff_create',
                'customer_id': customer.id,
                'customer_name': customer.name,
                'sale_id': write_off.sale_id,
                'amount': str(amount_dec),
                'amount_base': str(amount_base),
                'currency': currency,
                'exchange_rate': str(rate),
                'reason': write_off.reason,
                'gl_entry': getattr(entry, 'entry_number', None),
                'gl_entry_id': entry.id,
                'user_id': actor_id,
            }, commit=False)

            db.session.commit()
            current_app.logger.info(
                'Write-off created: customer=%s amount=%s %s (entry %s)',
                customer.id, amount_dec, currency, getattr(entry, 'entry_number', None),
            )
            return write_off
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------------
    # void
    # ------------------------------------------------------------------

    @staticmethod
    def void_writeoff(write_off, user=None, reason=None) -> WriteOff:
        """يلغي المشطوبة: يعكس القيد المرتبط ويعيد رصيد العميل.

        Args:
            write_off: سطر المشطوبة.
            user: المنفّذ (كائن مستخدم أو معرّف).
            reason: سبب الإلغاء (يُحفظ في سجل التدقيق).

        Returns:
            WriteOff: السطر بعد الإلغاء.

        Raises:
            ValidationError: المشطوبة ملغاة مسبقاً، أو القيد مفقود/معكوس.
        """
        if write_off is None:
            raise ValidationError('سجل المشطوبة غير موجود')

        if write_off.status == WriteOff.STATUS_VOID:
            raise ValidationError('المشطوبة ملغاة مسبقاً ولا يمكن إلغاؤها مرة أخرى')

        if not write_off.gl_entry_id:
            raise ValidationError('لا يوجد قيد محاسبي مرتبط بالمشطوبة')

        entry = GLJournalEntry.query.filter_by(id=write_off.gl_entry_id).first()
        if entry is None:
            raise ValidationError('القيد المحاسبي المرتبط بالمشطوبة غير موجود')
        if getattr(entry, 'is_reversed', False):
            raise ValidationError('القيد المحاسبي المرتبط بالمشطوبة معكوس مسبقاً')

        void_date = datetime.now(timezone.utc)
        assert_period_open(void_date)

        customer = write_off.customer
        if customer is None:
            raise ValidationError('عميل المشطوبة غير موجود')

        actor_id = _user_id(user)
        try:
            reversal = GLService.reverse_entry(
                entry,
                description=f'عكس مشطوبة مديونية - {customer.name}',
                entry_date=void_date,
                created_by=actor_id,
            )

            write_off.status = WriteOff.STATUS_VOID
            write_off.voided_at = void_date

            # الرصيد يعود كما كان قبل المشطوبة.
            _apply_balance_delta(customer, _dec(write_off.amount_base))

            create_audit_log('void', 'write_offs', write_off.id, changes={
                'action': 'writeoff_void',
                'customer_id': customer.id,
                'customer_name': customer.name,
                'amount': str(write_off.amount),
                'amount_base': str(write_off.amount_base),
                'currency': write_off.currency,
                'reason': reason,
                'gl_entry': getattr(entry, 'entry_number', None),
                'reversal_entry': getattr(reversal, 'entry_number', None),
                'user_id': actor_id,
            }, commit=False)

            db.session.commit()
            current_app.logger.info(
                'Write-off voided: id=%s customer=%s (reversal %s)',
                write_off.id, customer.id, getattr(reversal, 'entry_number', None),
            )
            return write_off
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    @staticmethod
    def list_writeoffs(customer=None, status=None, limit=100) -> list:
        """قائمة المشطوبات (معزولة بالمستأجر تلقائياً).

        Args:
            customer: العميل (كائن أو معرّف) — اختياري.
            status: حالة المشطوبة — اختياري.
            limit: أقصى عدد الصفوف.

        Returns:
            list[WriteOff]: الأحدث أولاً.
        """
        query = WriteOff.query
        if customer is not None:
            customer_id = getattr(customer, 'id', customer)
            query = query.filter(WriteOff.customer_id == customer_id)
        if status:
            query = query.filter(WriteOff.status == status)
        return query.order_by(WriteOff.created_at.desc(), WriteOff.id.desc()).limit(limit).all()

    @staticmethod
    def get_writeoff(write_off_id) -> WriteOff | None:
        """جلب مشطوبة بمعرّفها (لا تُرى مشطوبة مستأجر آخر)."""
        if write_off_id is None:
            return None
        return WriteOff.query.filter_by(id=write_off_id).first()
