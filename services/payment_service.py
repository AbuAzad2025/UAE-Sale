from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from flask import current_app
from flask_login import current_user
from extensions import db
from models import Receipt, Sale
from services.currency_service import CurrencyService
from services.gl_service import GLService
from utils.decorators import tx, get_owned_or_raise
from utils.errors import ValidationError
from utils.helpers import generate_number

# تقريب المبالغ (3 منازل عشرية) — نفس أعمدة Money
MONEY_Q = Decimal('0.001')


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


def resolve_audit_actor():
    """(user_id, actor_label) resolved defensively; headless jobs get 'system'."""
    try:
        from flask_login import current_user
        if current_user and getattr(current_user, 'is_authenticated', False):
            label = getattr(current_user, 'username', None) or f'user-{current_user.id}'
            return current_user.id, label
    except Exception:
        pass
    return None, 'system'


def json_safe_changes(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe_changes(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe_changes(v) for v in value]
    return value


def write_receipt_audit(action, record_id, changes):
    from utils.helpers import create_audit_log

    _, actor = resolve_audit_actor()
    payload = json_safe_changes(changes)
    payload['actor'] = actor
    payload['occurred_at'] = datetime.now(timezone.utc).isoformat()
    create_audit_log(action, table_name='receipts', record_id=record_id, changes=payload)


class PaymentService:

    # ------------------------------------------------------------------
    # F2: التخصيص بالعملة الأساسية (سعر السند الفعلي)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_allocation(sale, receipt, remaining_base, remaining_txn, requested_txn=None):
        """حساب نصيب الفاتورة من السند — **كل الحسابات بالعملة الأساسية**.

        عقد الصرف (F2):
          * النقد يدخل بسعر السند (receipt.exchange_rate) لا بسعر الفاتورة.
          * إن غطّى السند كامل مبلغ الفاتورة بعملتها → تُسوّى الفاتورة كاملة
            ويُسجَّل فرق العملة (سعر الفاتورة − سعر السند) كأرباح/خسائر صرف.
          * التسوية الجزئية تُسجَّل بقيمتها النقدية فقط ويبقى الفرق تعرضاً
            مفتوحاً (services/fx_revaluation.py يعيد تقييمه).

        Returns:
            dict: allocated_base, allocated_txn, fx_amount
        """
        sale_rate = _dec(getattr(sale, 'exchange_rate', None), '1') or Decimal('1')
        receipt_rate = _dec(getattr(receipt, 'exchange_rate', None), '1') or Decimal('1')

        sale_remaining_base = max(
            _dec(getattr(sale, 'amount_base', None)) - _dec(getattr(sale, 'paid_amount_base', None)),
            Decimal('0'),
        )
        if sale_remaining_base <= Decimal('0'):
            return {'allocated_base': Decimal('0'), 'allocated_txn': Decimal('0'),
                    'fx_amount': Decimal('0')}

        sale_remaining_txn = (sale_remaining_base / sale_rate).quantize(
            MONEY_Q, rounding=ROUND_HALF_UP)

        # أقصى نقد متاح من السند (بالعملة الأساسية)
        cash_base = min(remaining_base,
                        (remaining_txn * receipt_rate).quantize(MONEY_Q, rounding=ROUND_HALF_UP))
        cash_txn = (cash_base / receipt_rate).quantize(MONEY_Q, rounding=ROUND_HALF_UP)

        if requested_txn is not None:
            cash_txn = min(cash_txn, _dec(requested_txn))
            cash_base = (cash_txn * receipt_rate).quantize(MONEY_Q, rounding=ROUND_HALF_UP)

        if cash_txn >= sale_remaining_txn:
            # السند يغطي كامل الفاتورة → الفاتورة تُسوّى بسعرها وتُسجَّل
            # فروق العملة على حسابات الربح/الخسارة.
            allocated_base = sale_remaining_base
            allocated_txn = sale_remaining_txn
            cash_consumed = (allocated_txn * receipt_rate).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
            fx_amount = (allocated_base - cash_consumed).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        else:
            # تسوية جزئية: يُسجَّل النقد الفعلي فقط
            allocated_base = min(cash_base, sale_remaining_base)
            allocated_txn = (allocated_base / receipt_rate).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
            fx_amount = Decimal('0')

        return {
            'allocated_base': allocated_base.quantize(MONEY_Q, rounding=ROUND_HALF_UP),
            'allocated_txn': allocated_txn,
            'fx_amount': fx_amount,
        }

    @staticmethod
    def post_fx_difference(sale, fx_amount, receipt):
        """F2: قيد فروق العملة — يُرحَّل على حساب الذمم المدينة وحساب الربح/الخسارة.

        fx_amount > 0 → خسارة صرف (الدين المُسوّى أكبر من النقد الوارد):
            مدين  أرباح/خسائر الصرف   | دائن  الذمم المدينة
        fx_amount < 0 → ربح صرف:
            مدين  الذمم المدينة       | دائن  أرباح صرف
        """
        fx_amount = _dec(fx_amount)
        if fx_amount == Decimal('0'):
            return None

        try:
            from services.account_resolution import AccountResolver, AccountRole
        except Exception:  # pragma: no cover
            AccountResolver = None
            AccountRole = None

        def _role(name, fallback):
            try:
                if AccountResolver is not None and AccountRole is not None:
                    return AccountResolver.resolve(getattr(AccountRole, name))
            except Exception:
                pass
            return fallback

        ar_account = GLService.get_customer_credit_account(sale.customer)
        fx_gain_account = _role('FX_GAIN', '4400')
        fx_loss_account = _role('FX_LOSS', '6900')

        if fx_amount > Decimal('0'):
            lines = [
                {'account': fx_loss_account, 'debit': fx_amount,
                 'description': f'خسارة صرف - سند {receipt.receipt_number}'},
                {'account': ar_account, 'credit': fx_amount,
                 'description': f'فرق صرف على الذمم المدينة - سند {receipt.receipt_number}'},
            ]
        else:
            gain = abs(fx_amount)
            lines = [
                {'account': ar_account, 'debit': gain,
                 'description': f'فرق صرف على الذمم المدينة - سند {receipt.receipt_number}'},
                {'account': fx_gain_account, 'credit': gain,
                 'description': f'ربح صرف - سند {receipt.receipt_number}'},
            ]

        try:
            GLService.ensure_core_accounts()
            return GLService.post_entry(
                lines,
                description=f'FX difference Receipt {receipt.receipt_number}',
                reference_type='Receipt',
                reference_id=receipt.id,
                currency=CurrencyService.get_base_currency(),
                exchange_rate=1,
            )
        except Exception as e:
            current_app.logger.error(f'FX posting failed for receipt {receipt.receipt_number}: {e}')
            return None

    @staticmethod
    def apply_allocation_to_sale(sale, receipt, allocated_amount, allocated_base=None,
                                  post_fx=True):
        """F2: تطبيق تخصيص (بالعملة الأساسية) على الفاتورة.

        Args:
            sale: الفاتورة.
            receipt: سند القبض.
            allocated_amount: المبلغ المخصص بعملة السند.
            allocated_base: المبلغ المخصص بالعملة الأساسية (يُحسب من الأرقام
                المتبقية إن لم يُمرَّر).
        """
        receipt_rate = _dec(getattr(receipt, 'exchange_rate', None), '1') or Decimal('1')
        sale_rate = _dec(getattr(sale, 'exchange_rate', None), '1') or Decimal('1')

        if allocated_base is None:
            allocated_base = (_dec(allocated_amount) * receipt_rate).quantize(
                MONEY_Q, rounding=ROUND_HALF_UP)

        allocated_base = _dec(allocated_base)
        if allocated_base <= Decimal('0'):
            return Decimal('0')

        sale_remaining_base = max(
            _dec(getattr(sale, 'amount_base', None)) - _dec(getattr(sale, 'paid_amount_base', None)),
            Decimal('0'),
        )

        allocated_base = min(allocated_base, sale_remaining_base) if sale_remaining_base > 0 else Decimal('0')
        if allocated_base <= Decimal('0'):
            return Decimal('0')

        # المدفوع بعملة الأساس (F2) + ما يقابله بعملة الفاتورة
        sale.paid_amount_base = _dec(sale.paid_amount_base) + allocated_base
        if sale_rate > 0:
            sale.paid_amount = (sale.paid_amount_base / sale_rate).quantize(
                MONEY_Q, rounding=ROUND_HALF_UP)

        # المرتجعات المعتمدة تُخصم (تُلغي قيمة الفاتورة)
        from models.sale import compute_sale_returns_base
        returns_base = compute_sale_returns_base(sale.id)

        balance_due = (_dec(sale.amount_base) - sale.paid_amount_base - returns_base).quantize(
            MONEY_Q, rounding=ROUND_HALF_UP)
        if balance_due < Decimal('0'):
            balance_due = Decimal('0')
        sale.balance_due = balance_due

        if balance_due <= Decimal('0.01'):
            sale.payment_status = 'paid'
            sale.balance_due = Decimal('0')
        elif sale.paid_amount_base > Decimal('0'):
            sale.payment_status = 'partial'
        else:
            sale.payment_status = 'unpaid'

        return allocated_base

    @staticmethod
    def _plan_allocation(sale, receipt, remaining_base, remaining_txn, requested_txn=None):
        """حساب نصيب الفاتورة من السند + الكمية المستهلكة (بلا تطبيق)."""
        plan = PaymentService.compute_allocation(
            sale, receipt, remaining_base, remaining_txn, requested_txn=requested_txn)
        consumed_base = (plan['allocated_txn'] * _dec(receipt.exchange_rate, '1')).quantize(
            MONEY_Q, rounding=ROUND_HALF_UP)
        plan['consumed_base'] = consumed_base
        plan['consumed_txn'] = plan['allocated_txn']
        return plan

    @staticmethod
    def _commit_allocation(sale, receipt, plan):
        """تطبيق التخصيص على الفاتورة + قيد فرق العملة (F2)."""
        allocated_base = PaymentService.apply_allocation_to_sale(
            sale=sale, receipt=receipt,
            allocated_amount=plan['allocated_txn'],
            allocated_base=plan['allocated_base'],
        )
        fx_amount = plan['fx_amount']
        if fx_amount != Decimal('0'):
            PaymentService.post_fx_difference(sale, fx_amount, receipt)
        return allocated_base

    @staticmethod
    def _apply_allocation(sale, receipt, allocated_amount, remaining_base, remaining_txn,
                           requested_txn=None):
        """تخصيص جزء من السند لفاتورة + قيد فرق العملة (F2)."""
        plan = PaymentService._plan_allocation(
            sale, receipt, remaining_base, remaining_txn, requested_txn=requested_txn)

        if plan['allocated_base'] <= Decimal('0'):
            return {'allocated_base': Decimal('0'), 'allocated_txn': Decimal('0'),
                    'fx_amount': Decimal('0'), 'consumed_base': Decimal('0'),
                    'consumed_txn': Decimal('0')}

        allocated_base = PaymentService._commit_allocation(sale, receipt, plan)

        return {
            'allocated_base': allocated_base,
            'allocated_txn': plan['consumed_txn'],
            'fx_amount': plan['fx_amount'],
            'consumed_base': plan['consumed_base'],
            'consumed_txn': plan['consumed_txn'],
        }

    @staticmethod
    @tx
    def create_receipt(payment_data):  # noqa: C901
        """
        Create receipt from payment data dict

        Args:
            payment_data (dict): {
                'customer_id': int,
                'amount': Decimal,
                'currency': str,
                'payment_method': str,
                'notes': str (optional),
                ...
            }

        Allocation contract (C4):
            * ``allocate_to_sales`` falsy (None/False) → auto-FIFO allocation
              against the customer's oldest open sales when any exist.
            * ``allocate_to_sales == {}`` (explicit empty dict) → forced
              UNALLOCATED receipt, even when open sales exist.
            * non-empty mapping → explicit allocation to those sales.

        F2: كل التخصيصات تُحسب بالعملة **الأساسية** بسعر السند الفعلي،
        وفرق العملة يُرحَّل على حسابات الربح/الخسارة.
        F8: شيك تحت التحصيل يُنشأ غير مؤكَّد ولا يُسوّي الفاتورة إلا بعد
        تأكيده (confirm_receipt).
        F9: تُحفظ التخصيصات لكل فاتورة (Receipt.allocations_json) لعكسها
        بدقّة عند حذف السند.
        """
        from models import Customer

        customer_id = payment_data.get('customer_id')
        amount = payment_data.get('amount')
        currency = payment_data.get('currency', 'ILS')
        payment_method = payment_data.get('payment_method', 'cash')
        notes = payment_data.get('notes')
        user_exchange_rate = payment_data.get('user_exchange_rate')
        reference_number = payment_data.get('reference_number')
        cheque_number = payment_data.get('cheque_number')
        cheque_date = payment_data.get('cheque_date')
        bank_name = payment_data.get('bank_name')
        allocate_to_sales = payment_data.get('allocate_to_sales')
        purchase_id = payment_data.get('purchase_id')

        customer = get_owned_or_raise(Customer, customer_id, missing_message='العميل غير موجود')
        receipt = None
        gl_posted = None
        gl_entry_ref = None
        gl_warning = None
        allocation_summary = []
        auto_fifo = False

        # C4: resolve the allocation mode up-front (before the receipt row is
        # built) so source_type and audit flags reflect the real behavior.
        allocate_requested = payment_data.get('allocate_to_sales')
        if allocate_requested == {}:
            # explicit empty dict → force-unallocated
            allocate_to_sales = None
        elif not allocate_requested:
            allocate_to_sales = None
            auto_fifo = bool(PaymentService.get_unpaid_sales(customer))
        else:
            allocate_to_sales = allocate_requested

        try:
            # Convert cheque_date to date object if it's a string
            if cheque_date and isinstance(cheque_date, str):
                try:
                    cheque_date = datetime.strptime(cheque_date, '%Y-%m-%d').date()
                except ValueError:
                    raise ValueError('تاريخ الشيك غير صالح')

            receipt_number = generate_number('RCV', Receipt, 'receipt_number')

            exchange_rate = CurrencyService.get_exchange_rate(
                currency,
                CurrencyService.get_base_currency(),
                user_rate=user_exchange_rate
            )

            # F8: شيك تحت التحصيل ليس مؤكَّداً — لا يُسوّي الفاتورة قبل صرفه
            is_cheque = (payment_method == 'cheque' and bool(cheque_number))
            payment_confirmed = not is_cheque

            # تحديد نوع المصدر والاتجاه
            source_type = 'manual'  # افتراضي
            source_id = None
            direction = 'incoming'  # سندات القبض دائماً وارد

            if allocate_to_sales:
                # إذا كان مرتبط بفاتورة بيع
                source_type = 'sale'
                source_id = list(allocate_to_sales.keys())[0]  # أول فاتورة

            receipt = Receipt(
                receipt_number=receipt_number,
                source_type=source_type,
                source_id=source_id,
                direction=direction,
                customer_id=customer.id,
                # F4: ربط السند بالفاتورة (sale_id) — بدونه كان ارتداد الشيك
                # لا يعكس الفاتورة إطلاقاً. (sale_id و purchase_id mutually
                # exclusive — قيد ck_receipt_xor_parent)
                sale_id=(int(source_id) if source_type == 'sale' and source_id
                         and not purchase_id else None),
                purchase_id=int(purchase_id) if purchase_id else None,
                amount=Decimal(str(amount)),
                currency=currency,
                exchange_rate=exchange_rate,
                amount_base=(Decimal(str(amount)) * exchange_rate).quantize(
                    MONEY_Q, rounding=ROUND_HALF_UP),
                payment_method=payment_method,
                reference_number=reference_number,
                cheque_number=cheque_number,
                cheque_date=cheque_date,
                bank_name=bank_name,
                notes=notes,
                payment_confirmed=payment_confirmed,
                # Explicit actor wins; session user next; headless callers
                # get NULL (never a magic user_id=1 that may not exist).
                user_id=payment_data.get('user_id')
                or (current_user.id
                    if getattr(current_user, 'is_authenticated', False)
                    else None)
            )

            db.session.add(receipt)
            db.session.flush()

            # إنشاء سجل الشيك إذا كانت طريقة الدفع شيك
            if is_cheque:
                from models import Cheque
                cheque = Cheque(
                    cheque_number=cheque_number,
                    cheque_bank_number=cheque_number,  # نفس رقم الشيك
                    cheque_type='incoming',
                    customer_id=customer.id,
                    amount=Decimal(str(amount)),
                    currency=currency,
                    exchange_rate=exchange_rate,
                    amount_base=(Decimal(str(amount)) * exchange_rate).quantize(
                        MONEY_Q, rounding=ROUND_HALF_UP),
                    issue_date=receipt.receipt_date.date(),  # تاريخ الإصدار = تاريخ السند
                    due_date=cheque_date,  # تاريخ الاستحقاق
                    bank_name=bank_name,
                    status='pending',
                    notes=notes
                )
                db.session.add(cheque)
                db.session.flush()

                # ربط الشيك بالسند
                receipt.cheque_id = cheque.id
                gl_posted = True

                # استخدام منطق الشيك المحاسبي (شيكات تحت التحصيل -> ذمم مدينة)
                cheque.receive_cheque()

            else:
                # GL Entry for Standard Receipt (Cash/Bank)
                try:
                    GLService.ensure_core_accounts()
                    payment_account = GLService.get_payment_debit_account(receipt.payment_method)
                    credit_account = GLService.get_customer_credit_account(customer)

                    # Create GL entries
                    lines = [
                        {'account': payment_account, 'debit': receipt.amount, 'description': f'قبض من {customer.name}'},
                        {'account': credit_account, 'credit': receipt.amount, 'description': f'سند قبض {receipt.receipt_number}'}
                    ]
                    entry = GLService.post_entry(lines, description=f'Receipt {receipt.receipt_number}', reference_type='Receipt', reference_id=receipt.id, currency=receipt.currency, exchange_rate=receipt.exchange_rate)  # noqa: E501
                    gl_posted = True
                    gl_entry_ref = entry.entry_number
                except Exception as e:
                    # Orphan-prevention contract: a saved receipt must always be
                    # either linked to a GL entry or carry an explicit warning.
                    gl_posted = False
                    gl_warning = str(e)
                    current_app.logger.warning(
                        f'ORPHAN RECEIPT WARNING: receipt {receipt.receipt_number} '
                        f'(id={receipt.id}) saved without GL entry: {e}'
                    )

            # Allocation Logic (Restored) — F2/F8/F9
            remaining_base = _dec(receipt.amount_base)
            remaining_txn = _dec(receipt.amount)
            stored_allocations = []

            def _allocate(sale, requested_txn):
                nonlocal remaining_base, remaining_txn
                plan = PaymentService._plan_allocation(
                    sale=sale,
                    receipt=receipt,
                    remaining_base=remaining_base,
                    remaining_txn=remaining_txn,
                    requested_txn=requested_txn,
                )
                if plan['allocated_base'] > Decimal('0'):
                    remaining_base -= plan['consumed_base']
                    remaining_txn -= plan['consumed_txn']
                    if remaining_base < Decimal('0'):
                        remaining_base = Decimal('0')
                    if remaining_txn < Decimal('0'):
                        remaining_txn = Decimal('0')
                    # F8: السند غير المؤكّد (شيك تحت التحصيل) لا يُسوّي
                    # الفاتورة الآن — يُحفظ التخصيص ليُطبَّق عند التأكيد.
                    if payment_confirmed:
                        PaymentService._commit_allocation(sale, receipt, plan)
                    stored_allocations.append({
                        'sale_id': sale.id,
                        'amount': str(plan['allocated_txn']),
                        'amount_base': str(plan['allocated_base']),
                        'currency': receipt.currency,
                        'exchange_rate': str(receipt.exchange_rate),
                        'fx_amount': str(plan['fx_amount']),
                    })
                    allocation_summary.append({
                        'sale_id': sale.id,
                        'allocated': plan['allocated_base'],
                        'allocated_txn': plan['allocated_txn'],
                        'fx_amount': plan['fx_amount'],
                        'deferred': not payment_confirmed,
                    })
                return plan

            if allocate_to_sales:
                for sale_id, allocated in allocate_to_sales.items():
                    if remaining_txn <= 0:
                        break

                    sale = get_owned_or_raise(Sale, sale_id, missing_message='الفاتورة غير موجودة')

                    if not sale or sale.customer_id != customer.id:
                        continue

                    # F7: تحذير عند اختلاف عملة السند عن عملة الفاتورة —
                    # التخصيص يتم بسعر السند (النقد الفعلي) ويُرحَّل فرق
                    # العملة على حسابات الربح/الخسارة.
                    if sale.currency and currency and sale.currency.upper() != currency.upper():
                        current_app.logger.warning(
                            f'FX allocation: receipt {receipt.receipt_number} '
                            f'({currency} @ {exchange_rate}) settles invoice '
                            f'{sale.sale_number} ({sale.currency} @ {sale.exchange_rate}) '
                            f'— difference posted to the FX accounts.')

                    _allocate(sale, Decimal(str(allocated)))

            elif auto_fifo:
                # C4 auto-FIFO: oldest open sales first, same internal loop.
                for sale in PaymentService.get_unpaid_sales(customer):
                    if remaining_txn <= 0:
                        break

                    if _dec(sale.balance_due) <= 0:
                        continue

                    _allocate(sale, None)

            # F9: حفظ التخصيصات (JSON) لكل فاتورة — تُستعمل لعكس التخصيصات
            # عند حذف السند وتطبيقها عند تأكيد شيك تحت التحصيل.
            receipt.set_allocations(stored_allocations)

            # F4: اربط السند بأول فاتورة تخصّص لها (مهم في التخصيص التلقائي
            # FIFO حيث لا يوجد مصدر مسبق) — بدونه لا يعكس ارتداد الشيك الفاتورة.
            # (source_type يبقى كما هو: 'manual' يعني "تخصيص تلقائي" وليس
            #  تخصيصاً صريحاً — عقد C4)
            if receipt.sale_id is None and stored_allocations:
                receipt.sale_id = int(stored_allocations[0]['sale_id'])

            db.session.commit()

            # F1: رصيد العميل يُشتق من مصدره الواحد (المستمع يعيد الاحتساب
            # بعد تحديث الفاتورة) — لا زيادة تدريجية هنا.
            from models.customer import recompute_customer_balance
            recompute_customer_balance(customer.id)
            db.session.commit()

            current_app.logger.info(f'Receipt created: {receipt.receipt_number}')

            write_receipt_audit('receipt_create', receipt.id, {
                'receipt_number': receipt.receipt_number,
                'customer_id': customer.id,
                'amount': receipt.amount,
                'amount_base': receipt.amount_base,
                'currency': currency,
                'exchange_rate': exchange_rate,
                'payment_method': payment_method,
                'source_type': source_type,
                'source_id': source_id,
                'sale_id': receipt.sale_id,
                'purchase_id': receipt.purchase_id,
                'payment_confirmed': receipt.payment_confirmed,
                'cheque_id': receipt.cheque_id,
                'gl_posted': gl_posted,
                'gl_entry': gl_entry_ref,
                'gl_warning': gl_warning,
                'auto_fifo': auto_fifo,
                'unallocated_base': remaining_base,
                'allocations': allocation_summary,
            })

            return receipt

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Receipt creation failed: {e}')
            write_receipt_audit('receipt_create_failed', receipt.id if receipt else None, {
                'customer_id': customer_id,
                'amount': amount,
                'payment_method': payment_method,
                'error_type': type(e).__name__,
                'error': str(e),
            })
            raise

    # ------------------------------------------------------------------
    # F8 — استرداد نقدي للعميل + ضبط يدوي للرصيد
    # ------------------------------------------------------------------

    @staticmethod
    def create_refund(customer, amount, reason=None, payment_method='cash', user_id=None,
                      currency=None, exchange_rate=None, notes=None, sale_id=None):
        """صرف مبلغ للعميل (استرداد) — استرداد حقيقي لا تعديل يدوي.

        F8: كان المسار الذكي (routes/ai.py::_ai_record_refund) يبني سند
        الصرف بنفسه ويكتب ``customer.balance`` بيده — فلا مرجع واحد
        للرصيد ولا مسار واحد للخدمة. الآن كل شيء يمرّ من هنا:
          * سند صرف (Payment) بقيمة **موجبة** واتجاه ``outgoing`` — أثره
            على رصيد العميل يأتي من الاشتقاق (سند صادر بلا فاتورة ⇒
            يُخصم من رصيد العميل)، والقيدان الموجبان للنقد هما ما
            يفرضه قيد قاعدة البيانات (amount/amount_base > 0)،
          * قيد محاسبي متوازن: مدين الذمم المدينة / دائن الصندوق أو
            البنك (بعملة السند وسعره)،
          * إعادة اشتقاق رصيد العميل من مصدره الوحيد،
          * صف تدقيق يحمل المبلغ والسبب والطرف.

        Args:
            customer: العميل المستردّ له.
            amount: المبلغ بعملة السند (Decimal) — يجب أن يكون > 0.
            reason: سبب الاسترداد (يُحفظ في الملاحظات وصف التدقيق).
            payment_method: طريقة الصرف (cash/card/bank_transfer/...).
            user_id: من نفّذ العملية.
            currency / exchange_rate: عملة السند وسعره (الافتراضي:
                عملة الأساس وسعر السوق).
            notes: ملاحظات إضافية.
            sale_id: فاتورة مرتبطة بالاسترداد (اختياري).

        Returns:
            Payment: سند الصرف.
        """
        from models import Payment
        from utils.helpers import create_audit_log

        if customer is None:
            raise ValidationError('العميل غير موجود')

        amount_decimal = _dec(amount)
        if amount_decimal <= Decimal('0'):
            raise ValidationError('المبلغ يجب أن يكون أكبر من صفر')

        if not currency:
            try:
                currency = CurrencyService.get_base_currency()
            except Exception:
                currency = 'ILS'

        if exchange_rate is None:
            try:
                exchange_rate = CurrencyService.get_exchange_rate(
                    currency, CurrencyService.get_base_currency())
            except Exception:
                exchange_rate = Decimal('1')
        rate = _dec(exchange_rate, '1') or Decimal('1')

        amount_base = (amount_decimal * rate).quantize(
            MONEY_Q, rounding=ROUND_HALF_UP)

        payment = Payment(
            payment_number=generate_number('PAY', Payment, 'payment_number'),
            payment_type='refund',
            direction='outgoing',
            customer_id=customer.id,
            sale_id=sale_id,
            amount=amount_decimal,
            currency=currency,
            exchange_rate=rate,
            amount_base=amount_base,
            payment_method=payment_method or 'cash',
            notes=notes or f'استرداد: {reason or "—"}',
            user_id=user_id,
            payment_confirmed=True,
        )
        db.session.add(payment)
        db.session.flush()

        try:
            GLService.ensure_core_accounts()
            ar_account = GLService.get_customer_credit_account(customer)
            cash_account = GLService.get_payment_debit_account(
                payment_method or 'cash')

            entry = GLService.post_entry(
                [
                    {'account': ar_account, 'debit': amount_decimal,
                     'description': f'صرف مسترد للعميل {customer.name}'},
                    {'account': cash_account, 'credit': amount_decimal,
                     'description': f'صرف مسترد {payment.payment_number}'},
                ],
                description=f'Refund {payment.payment_number}',
                reference_type='Payment',
                reference_id=payment.id,
                currency=currency,
                exchange_rate=rate,
            )
        except Exception as e:
            # fail-closed: لا سند بلا قيد (وإلا نقد بلا أثر محاسبي).
            db.session.rollback()
            current_app.logger.error(
                f'Refund posting failed for customer {customer.id}: {e}')
            raise

        # F1: رصيد العميل من مصدره الواحد (لا زيادة يدوية).
        from models.customer import recompute_customer_balance
        recompute_customer_balance(customer.id)

        create_audit_log('create', 'payments', payment.id, changes={
            'action': 'create_refund',
            'customer_id': customer.id,
            'customer_name': customer.name,
            'payment_number': payment.payment_number,
            'amount': str(amount_decimal),
            'amount_base': str(amount_base),
            'currency': currency,
            'exchange_rate': str(rate),
            'payment_method': payment.payment_method,
            'direction': 'outgoing',
            'reason': reason,
            'gl_entry': getattr(entry, 'entry_number', None),
            'user_id': user_id,
        }, commit=False)

        db.session.commit()
        current_app.logger.info(
            f'Refund created: {payment.payment_number} '
            f'({amount_decimal} {currency}) for customer {customer.id}')
        return payment

    @staticmethod
    def adjust_customer_balance(customer, new_balance, reason=None, user_id=None):
        """ضبط/تصحيح يدوي لرصيد العميل — مُوثَّق بالسبب + صف تدقيق.

        F8: لا يُكتب ``customer.balance`` أبداً هنا. التصحيح يُثبَّت
        **داخل الاشتقاق** — في بند الرصيد الافتتاحي
        (``opening_balance``)، وهو البند الوحيد القابل للزيادة في
        اشتقاق رصيد العميل — ثم يُعاد اشتقاق الرصيد من مصدره الوحيد
        (``models.customer.recompute_customer_balance``).

        لماذا لا نكتفي بكتابة العمود؟ لأن أول إعادة احتساب قادم (سند
        قبض، مرتجع، دفعة، شيك) كانت ستمسح التصحيح بصمت — وهو بالضبط
        ما كان يحدث في المسار الذكي.

        Args:
            customer: العميل.
            new_balance: الرصيد المستهدف (بالعملة الأساسية).
            reason: سبب الضبط — **مطلوب** (يُحفظ في سجل التدقيق).
            user_id: من نفّذ العملية.

        Returns:
            Customer: العميل بعد إعادة الاشتقاق.
        """
        from models.customer import derive_customer_balance, recompute_customer_balance
        from utils.helpers import create_audit_log

        if customer is None:
            raise ValidationError('العميل غير موجود')

        if not reason or not str(reason).strip():
            raise ValidationError(
                'سبب تعديل الرصيد مطلوب — لا يُعدَّل رصيد عميل بلا سبب مسجَّل.')

        target = _dec(new_balance)
        old_derived = derive_customer_balance(customer.id)
        difference = (target - old_derived).quantize(
            MONEY_Q, rounding=ROUND_HALF_UP)

        if difference != Decimal('0'):
            # التثبيت داخل الاشتقاق: يُضاف الفرق (بالعملة الأساسية)
            # إلى الرصيد الافتتاحي — وهو البند القابل للزيادة.
            rate = _dec(customer.opening_balance_rate, '1') or Decimal('1')
            if rate <= 0:
                rate = Decimal('1')
            customer.opening_balance = (
                _dec(customer.opening_balance) + (difference / rate)
            ).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
            # flush: الاشتقاق يقرأ من القاعدة (Core).
            db.session.flush()

        new_value = recompute_customer_balance(customer.id)

        create_audit_log('update', 'customers', customer.id, changes={
            'action': 'manual_balance_adjustment',
            'customer_id': customer.id,
            'customer_name': customer.name,
            'old_balance': str(old_derived),
            'new_balance': str(target),
            'difference': str(difference),
            'reason': reason,
            'user_id': user_id,
        }, commit=False)

        db.session.commit()
        current_app.logger.info(
            f'Customer {customer.id} balance adjusted: {old_derived} → '
            f'{new_value} (difference {difference})')
        return customer

    @staticmethod
    def get_customer_balance(customer):
        """F12: رصيد العميل — المصدر الوحيد (models/customer.derive_customer_balance)."""
        from models.customer import derive_customer_balance
        return derive_customer_balance(customer.id)

    @staticmethod
    def get_customer_balance_aed(customer):
        """F12: نفس الدالة (alias تاريخي) — يشمل المرتجعات المعتمدة."""
        from models.customer import derive_customer_balance
        return derive_customer_balance(customer.id)

    @staticmethod
    def get_unpaid_sales(customer):
        return Sale.query.filter(
            Sale.customer_id == customer.id,
            Sale.status == 'confirmed',
            Sale.balance_due > 0
        ).order_by(Sale.sale_date.asc()).all()

    @staticmethod
    @tx
    def allocate_receipt_to_oldest_sales(receipt, customer):
        allocations = []
        remaining_after = None
        try:
            remaining_base = _dec(receipt.amount_base)
            remaining_txn = _dec(receipt.amount)
            stored = []

            unpaid_sales = PaymentService.get_unpaid_sales(customer)

            for sale in unpaid_sales:
                if remaining_txn <= 0:
                    break

                if _dec(sale.balance_due) <= 0:
                    continue

                result = PaymentService._plan_allocation(
                    sale=sale,
                    receipt=receipt,
                    remaining_base=remaining_base,
                    remaining_txn=remaining_txn,
                    requested_txn=None,
                )
                if result['allocated_base'] > Decimal('0'):
                    remaining_base -= result['consumed_base']
                    remaining_txn -= result['consumed_txn']
                    if remaining_base < Decimal('0'):
                        remaining_base = Decimal('0')
                    if remaining_txn < Decimal('0'):
                        remaining_txn = Decimal('0')
                    # F8: لا تخصيص فعلي قبل التأكيد
                    if receipt.payment_confirmed:
                        PaymentService._commit_allocation(sale, receipt, result)
                    stored.append({
                        'sale_id': sale.id,
                        'amount': str(result['allocated_txn']),
                        'amount_base': str(result['allocated_base']),
                        'currency': receipt.currency,
                        'exchange_rate': str(receipt.exchange_rate),
                        'fx_amount': str(result['fx_amount']),
                    })
                    allocations.append({'sale_id': sale.id, 'allocated': result['allocated_base']})

            remaining_after = remaining_txn

            # F9: حفظ التخصيصات
            receipt.set_allocations(stored)

            db.session.commit()

            from models.customer import recompute_customer_balance
            recompute_customer_balance(customer.id)
            db.session.commit()

            current_app.logger.info(f'Receipt {receipt.receipt_number} allocated to sales')

            write_receipt_audit('receipt_allocation', receipt.id, {
                'receipt_number': receipt.receipt_number,
                'customer_id': customer.id,
                'amount': receipt.amount,
                'allocations': allocations,
                'unallocated': remaining_after,
            })

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Receipt allocation failed: {e}')
            write_receipt_audit('receipt_allocation_failed', receipt.id if receipt else None, {
                'customer_id': getattr(customer, 'id', None),
                'error_type': type(e).__name__,
                'error': str(e),
            })
            raise
