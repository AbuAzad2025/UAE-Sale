from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from extensions import db
from models.cheque import Cheque
from models.gl import GLAccount, GLJournalEntry
from services.gl_service import GLService
from utils.decorators import get_owned_or_404

_MONEY_Q3 = Decimal("0.001")


def _coerce_decimal(value) -> Decimal:
    """Coerce boundary input to Decimal without ever going through float."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value).strip() or "0")
    except (InvalidOperation, ValueError, AttributeError):
        return Decimal("0")


def _quantize_3(value: Decimal) -> Decimal:
    return _coerce_decimal(value).quantize(_MONEY_Q3, rounding=ROUND_HALF_UP)

# Dynamic CoA resolution (contract C3/Agent 1) with literal fallbacks equal to
# today's codes when the resolver is unavailable or the role is unmapped.
try:
    from services.account_resolution import AccountResolver, AccountRole
except Exception:  # pragma: no cover - resolver ships in parallel
    AccountRole = None  # type: ignore[assignment,misc]
    AccountResolver = None  # type: ignore[assignment,misc]


def _resolve_role_code(role_value, fallback_code):
    """Resolve an AccountRole to its live code, falling back to the literal."""
    try:
        if AccountRole is not None and AccountResolver is not None:
            code = AccountResolver.resolve(AccountRole(role_value))
            if code:
                return str(code)
    except Exception:
        pass
    return fallback_code


class ChequeAccountingIntegration:
    """تكامل الشيكات مع النظام المحاسبي

    حالة الشيك تتبع قيم النموذج الصالحة فقط (C3): بعد الاستلام/الإصدار تصبح
    الحالة 'deposited' (تحت البنك) — لا حالات مُختلقة مثل 'received'/'issued'.
    """

    # Semantic ROLES for the accounts the cheque flow posts to. The codes
    # themselves are resolved through AccountResolver, so a tenant that
    # remapped an account gets a statement that follows the mapping instead of
    # hardcoded literals.
    CHEQUE_ROLES = {
        'incoming_under_collection': 'UNDER_COLLECTION',
        'outgoing_deferred': 'DEFERRED_CHEQUES_PAYABLE',
        'bank_account': 'BANK',
        'cash_account': 'CASH',
        'accounts_receivable': 'AR_CONTROL',
        'accounts_payable': 'AP_CONTROL',
        'bank_charges': 'BANK_CHARGES',
        'exchange_gain': 'FX_GAIN',
        'exchange_loss': 'FX_LOSS',
    }

    # The seeded default codes, used when the resolver cannot answer.
    CHEQUE_DEFAULT_CODES = {
        'incoming_under_collection': '1150',
        'outgoing_deferred': '2120',
        'bank_account': '1120',
        'cash_account': '1110',
        'accounts_receivable': '1130',
        'accounts_payable': '2110',
        'bank_charges': '6950',
        'exchange_gain': '4400',
        'exchange_loss': '6900',
    }

    @classmethod
    def cheque_accounts(cls, tenant_id=None):
        """Resolve the cheque account codes for the current tenant.

        Falls back to the seeded default codes when the resolver cannot
        answer, so a tenant with no custom mapping still gets a working
        (and correct) statement.
        """
        from services.account_resolution import AccountResolver

        resolved = {}
        for key, role in cls.CHEQUE_ROLES.items():
            code = None
            try:
                code = AccountResolver.resolve(role, tenant_id=tenant_id)
            except Exception:
                code = None
            resolved[key] = code or cls.CHEQUE_DEFAULT_CODES[key]
        return resolved

    class _Accounts:
        """Tenant-aware view of the cheque account codes.

        Keeps the historic ``CHEQUE_ACCOUNTS['...']`` call shape working
        while resolving through the role map, so a tenant that remapped an
        account is followed instead of the hardcoded default.
        """

        def __getitem__(self, key):
            return ChequeAccountingIntegration.cheque_accounts()[key]

        def get(self, key, default=None):
            return ChequeAccountingIntegration.cheque_accounts().get(key,
                                                                      default)

        def __contains__(self, key):
            return key in ChequeAccountingIntegration.cheque_accounts()

        def keys(self):
            return ChequeAccountingIntegration.cheque_accounts().keys()

        def items(self):
            return ChequeAccountingIntegration.cheque_accounts().items()

    CHEQUE_ACCOUNTS = _Accounts()

    @staticmethod
    def _ensure_amount_base(cheque):
        """ضمان وجود المبلغ الأساسي — منع قيود صفرية صامتة"""
        if cheque.amount_base in (None, Decimal('0')) and cheque.amount:
            cheque.calculate_amount_base()
            db.session.flush()
        return cheque.amount_base or Decimal('0')

    @staticmethod
    def receive_cheque(cheque_id, received_by=None):
        """تسجيل استلام شيك وارد مع القيود المحاسبية"""
        cheque = get_owned_or_404(Cheque, cheque_id)

        if cheque.cheque_type != 'incoming':
            raise ValueError("هذا الشيك ليس شيك وارد")

        if cheque.status != 'pending':
            raise ValueError("الشيك ليس في حالة معلق")

        try:
            amount_base = ChequeAccountingIntegration._ensure_amount_base(cheque)
            # إنشاء القيد المحاسبي
            lines = []

            # المدين: شيكات تحت التحصيل
            lines.append({
                'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['incoming_under_collection'],
                'debit': amount_base,
                'credit': 0,
                'description': f'استلام شيك وارد رقم {cheque.cheque_bank_number} من {cheque.customer.name if cheque.customer else "غير محدد"}'
            })

            # الدائن: الذمم المدينة
            lines.append({
                'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['accounts_receivable'],
                'debit': 0,
                'credit': amount_base,
                'description': f'تسوية ذمم مدينة - شيك رقم {cheque.cheque_bank_number}'
            })

            # إنشاء القيد
            entry = GLService.create_manual_entry(
                description=f'استلام شيك وارد رقم {cheque.cheque_bank_number}',
                lines=lines,
                entry_date=datetime.now().date(),
                reference_type='cheque_receive',
                reference_id=cheque.id,
                created_by=received_by
            )

            # تحديث حالة الشيك — C3: حالة نموذج صالحة (تحت البنك)
            cheque.status = 'deposited'
            cheque.gl_journal_entry_id = entry.id
            cheque.updated_at = datetime.now(timezone.utc)

            db.session.commit()

            return entry

        except Exception as e:
            db.session.rollback()
            raise Exception(f"فشل في تسجيل استلام الشيك: {str(e)}")

    @staticmethod
    def issue_cheque(cheque_id, issued_by=None):
        """تسجيل إصدار شيك صادر مع القيود المحاسبية"""
        cheque = get_owned_or_404(Cheque, cheque_id)

        if cheque.cheque_type != 'outgoing':
            raise ValueError("هذا الشيك ليس شيك صادر")

        if cheque.status != 'pending':
            raise ValueError("الشيك ليس في حالة معلق")

        try:
            amount_base = ChequeAccountingIntegration._ensure_amount_base(cheque)
            # إنشاء القيد المحاسبي
            lines = []

            # المدين: الذمم الدائنة
            lines.append({
                'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['accounts_payable'],
                'debit': amount_base,
                'credit': 0,
                'description': f'تسوية ذمم دائنة - شيك رقم {cheque.cheque_bank_number}'
            })

            # الدائن: شيكات مؤجلة الدفع
            lines.append({
                'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['outgoing_deferred'],
                'debit': 0,
                'credit': amount_base,
                'description': f'إصدار شيك صادر رقم {cheque.cheque_bank_number} لـ {cheque.supplier.name if cheque.supplier else "غير محدد"}'
            })

            # إنشاء القيد
            entry = GLService.create_manual_entry(
                description=f'إصدار شيك صادر رقم {cheque.cheque_bank_number}',
                lines=lines,
                entry_date=cheque.issue_date or datetime.now().date(),
                reference_type='cheque_issue',
                reference_id=cheque.id,
                created_by=issued_by
            )

            # تحديث حالة الشيك — C3: حالة نموذج صالحة (تحت البنك)
            cheque.status = 'deposited'
            cheque.gl_journal_entry_id = entry.id
            cheque.updated_at = datetime.now(timezone.utc)

            db.session.commit()

            return entry

        except Exception as e:
            db.session.rollback()
            raise Exception(f"فشل في تسجيل إصدار الشيك: {str(e)}")

    @staticmethod
    def clear_cheque(cheque_id, cleared_by=None, bank_charges=0, exchange_gain_loss=0):  # noqa: C901
        """تسجيل صرف شيك مع القيود المحاسبية"""
        cheque = get_owned_or_404(Cheque, cheque_id)

        if cheque.status not in ['deposited']:
            raise ValueError("الشيك ليس في حالة يمكن صرفه")

        try:
            # F5: coerce + quantize every leg to 3dp BEFORE posting so the
            # entry balances exactly even when callers pass str/float or
            # >3dp values. The bank leg is derived from the quantized
            # components (amount - charges + fx), so debit == credit holds
            # exactly at 3dp and GLService never sees a 0.001 rounding break.
            amount_base = _quantize_3(ChequeAccountingIntegration._ensure_amount_base(cheque))
            bank_charges = _quantize_3(_coerce_decimal(bank_charges))
            exchange_gain_loss = _quantize_3(_coerce_decimal(exchange_gain_loss))
            bank_charges_account = _resolve_role_code('BANK_CHARGES', '6950')
            fx_gain_account = _resolve_role_code('FX_GAIN', '4400')
            fx_loss_account = _resolve_role_code('FX_LOSS', '6900')
            lines = []

            if cheque.cheque_type == 'incoming':
                # شيك وارد - صرف

                # المدين: حساب البنك
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['bank_account'],
                    'debit': _quantize_3(amount_base - bank_charges + exchange_gain_loss),
                    'credit': 0,
                    'description': f'صرف شيك وارد رقم {cheque.cheque_bank_number}'
                })

                # الدائن: شيكات تحت التحصيل
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['incoming_under_collection'],
                    'debit': 0,
                    'credit': amount_base,
                    'description': f'صرف شيك تحت التحصيل رقم {cheque.cheque_bank_number}'
                })

                # رسوم البنك (إذا وجدت)
                if bank_charges > 0:
                    lines.append({
                        'account_code': bank_charges_account,  # مصروفات بنكية (BANK_CHARGES)
                        'debit': bank_charges,
                        'credit': 0,
                        'description': f'رسوم بنك - شيك رقم {cheque.cheque_bank_number}'
                    })

                # أرباح/خسائر الصرف (إذا وجدت)
                if exchange_gain_loss != 0:
                    if exchange_gain_loss > 0:
                        lines.append({
                            'account_code': fx_gain_account,
                            'debit': 0,
                            'credit': exchange_gain_loss,
                            'description': f'ربح صرف - شيك رقم {cheque.cheque_bank_number}'
                        })
                    else:
                        lines.append({
                            'account_code': fx_loss_account,
                            'debit': abs(exchange_gain_loss),
                            'credit': 0,
                            'description': f'خسارة صرف - شيك رقم {cheque.cheque_bank_number}'
                        })

            elif cheque.cheque_type == 'outgoing':
                # شيك صادر - صرف

                # المدين: شيكات مؤجلة الدفع
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['outgoing_deferred'],
                    'debit': amount_base,
                    'credit': 0,
                    'description': f'صرف شيك مؤجل الدفع رقم {cheque.cheque_bank_number}'
                })

                # الدائن: حساب البنك
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['bank_account'],
                    'debit': 0,
                    'credit': _quantize_3(amount_base + bank_charges - exchange_gain_loss),
                    'description': f'صرف شيك صادر رقم {cheque.cheque_bank_number}'
                })

                # رسوم البنك (إذا وجدت)
                if bank_charges > 0:
                    lines.append({
                        'account_code': bank_charges_account,  # مصروفات بنكية (BANK_CHARGES)
                        'debit': bank_charges,
                        'credit': 0,
                        'description': f'رسوم بنك - شيك رقم {cheque.cheque_bank_number}'
                    })

                # أرباح/خسائر الصرف (إذا وجدت)
                if exchange_gain_loss != 0:
                    if exchange_gain_loss > 0:
                        lines.append({
                            'account_code': fx_gain_account,
                            'debit': 0,
                            'credit': exchange_gain_loss,
                            'description': f'ربح صرف - شيك رقم {cheque.cheque_bank_number}'
                        })
                    else:
                        lines.append({
                            'account_code': fx_loss_account,
                            'debit': abs(exchange_gain_loss),
                            'credit': 0,
                            'description': f'خسارة صرف - شيك رقم {cheque.cheque_bank_number}'
                        })

            # إنشاء القيد
            entry = GLService.create_manual_entry(
                description=f'صرف شيك {cheque.type_ar} رقم {cheque.cheque_bank_number}',
                lines=lines,
                entry_date=cheque.cleared_date or datetime.now().date(),
                reference_type='cheque_clear',
                reference_id=cheque.id,
                created_by=cleared_by
            )

            # تحديث حالة الشيك
            cheque.status = 'cleared'
            cheque.cleared_date = datetime.now().date()
            cheque.gl_clearing_entry_id = entry.id
            cheque.updated_at = datetime.now(timezone.utc)

            db.session.commit()

            return entry

        except Exception as e:
            db.session.rollback()
            raise Exception(f"فشل في تسجيل صرف الشيك: {str(e)}")

    @staticmethod
    def bounce_cheque(cheque_id, bounced_by=None, bounce_reason=None):
        """تسجيل ارتداد شيك مع القيود المحاسبية"""
        cheque = get_owned_or_404(Cheque, cheque_id)

        if cheque.status not in ['deposited']:
            raise ValueError("الشيك ليس في حالة يمكن ارتداده")

        try:
            amount_base = ChequeAccountingIntegration._ensure_amount_base(cheque)
            lines = []

            if cheque.cheque_type == 'incoming':
                # شيك وارد - ارتداد

                # المدين: الذمم المدينة (استرداد)
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['accounts_receivable'],
                    'debit': amount_base,
                    'credit': 0,
                    'description': f'استرداد ذمم مدينة - شيك مرتد رقم {cheque.cheque_bank_number}'
                })

                # الدائن: شيكات تحت التحصيل
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['incoming_under_collection'],
                    'debit': 0,
                    'credit': amount_base,
                    'description': f'شيك مرتد رقم {cheque.cheque_bank_number}'
                })

            elif cheque.cheque_type == 'outgoing':
                # شيك صادر - ارتداد

                # المدين: شيكات مؤجلة الدفع
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['outgoing_deferred'],
                    'debit': amount_base,
                    'credit': 0,
                    'description': f'شيك صادر مرتد رقم {cheque.cheque_bank_number}'
                })

                # الدائن: الذمم الدائنة (استرداد)
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['accounts_payable'],
                    'debit': 0,
                    'credit': amount_base,
                    'description': f'استرداد ذمم دائنة - شيك مرتد رقم {cheque.cheque_bank_number}'
                })

            # إنشاء القيد
            entry = GLService.create_manual_entry(
                description=f'ارتداد شيك {cheque.type_ar} رقم {cheque.cheque_bank_number}',
                lines=lines,
                entry_date=datetime.now().date(),
                reference_type='cheque_bounce',
                reference_id=cheque.id,
                created_by=bounced_by,
                notes=f'سبب الارتداد: {bounce_reason or "غير محدد"}'
            )

            # تحديث حالة الشيك — تُثبَّت في القاعدة قبل إعادة احتساب
            # الأرصدة (الاشتقاق يقرأ الحالة من القاعدة).
            cheque.status = 'bounced'
            cheque.bounced_date = datetime.now().date()
            cheque.bounce_reason = bounce_reason
            cheque.gl_bounce_entry_id = entry.id
            cheque.updated_at = datetime.now(timezone.utc)

            db.session.flush()

            # F4: ارتداد الشيك يجب أن يعكس الفاتورة المرتبطة (سند القبض
            # أو سند الصرف المرتبط بالشيك) — وإلا بقيت الفاتورة "مدفوعة"
            # والمال لم يصل.
            from models.payment import Payment, Receipt

            linked_receipt = Receipt.query.filter_by(cheque_id=cheque.id).first()
            if linked_receipt is not None:
                linked_receipt.reject_receipt(bounce_reason or 'ارتداد شيك')

            linked_payment = Payment.query.filter_by(cheque_id=cheque.id).first()
            if linked_payment is not None:
                linked_payment.reject_payment(bounce_reason or 'ارتداد شيك')

            # F1: رصيد العميل يُشتق من مصدره الواحد — الزيادة اليدوية القديمة
            # (+ amount_base) كانت تُطبَّق فوق قيمة مشتقة فتُضاعف الفرق.
            if cheque.cheque_type == 'incoming' and cheque.customer_id:
                from models.customer import recompute_customer_balance
                recompute_customer_balance(cheque.customer_id)
            elif cheque.cheque_type == 'outgoing' and cheque.supplier_id:
                from models import Supplier as _Supp
                supplier = _Supp.query.get(cheque.supplier_id)
                if supplier:
                    supplier.total_purchases_aed = (supplier.total_purchases_aed or Decimal('0')) - amount_base

            db.session.commit()

            return entry

        except Exception as e:
            db.session.rollback()
            raise Exception(f"فشل في تسجيل ارتداد الشيك: {str(e)}")

    @staticmethod
    def get_cheque_accounting_summary(cheque_id):  # noqa: C901
        """الحصول على ملخص محاسبي للشيك"""
        cheque = get_owned_or_404(Cheque, cheque_id)

        summary = {
            'cheque_info': {
                'id': cheque.id,
                'number': cheque.cheque_bank_number,
                'type': cheque.type_ar,
                'amount': float(cheque.amount_base),
                'status': cheque.status_ar,
                'date': cheque.due_date.isoformat() if cheque.due_date else None
            },
            'journal_entries': [],
            'account_impact': []
        }

        # جمع القيود المحاسبية المرتبطة
        if cheque.gl_journal_entry_id:
            entry = db.session.get(GLJournalEntry, cheque.gl_journal_entry_id)
            if entry:
                summary['journal_entries'].append({
                    'type': 'receive' if cheque.cheque_type == 'incoming' else 'issue',
                    'entry_number': entry.entry_number,
                    'date': entry.entry_date.isoformat(),
                    'description': entry.description
                })

        if cheque.gl_clearing_entry_id:
            entry = db.session.get(GLJournalEntry, cheque.gl_clearing_entry_id)
            if entry:
                summary['journal_entries'].append({
                    'type': 'clear',
                    'entry_number': entry.entry_number,
                    'date': entry.entry_date.isoformat(),
                    'description': entry.description
                })

        if cheque.gl_bounce_entry_id:
            entry = db.session.get(GLJournalEntry, cheque.gl_bounce_entry_id)
            if entry:
                summary['journal_entries'].append({
                    'type': 'bounce',
                    'entry_number': entry.entry_number,
                    'date': entry.entry_date.isoformat(),
                    'description': entry.description
                })

        # حساب التأثير على الحسابات
        accounts_affected = set()
        for entry_info in summary['journal_entries']:
            entry = GLJournalEntry.query.filter_by(entry_number=entry_info['entry_number']).first()
            if entry:
                for line in entry.lines:
                    accounts_affected.add(line.account.code)

        for account_code in accounts_affected:
            account = GLAccount.query.filter_by(code=account_code).first()
            if account:
                summary['account_impact'].append({
                    'code': account.code,
                    'name': account.full_name,
                    'balance': float(account.get_balance())
                })

        return summary
