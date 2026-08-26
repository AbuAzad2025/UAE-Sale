from datetime import datetime, timezone
from decimal import Decimal
from extensions import db
from models.cheque import Cheque
from models.gl import GLAccount, GLJournalEntry
from services.gl_service import GLService

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

    # حسابات الشيكات الافتراضية (fallback literals = DEFAULT_ROLE_MAP)
    CHEQUE_ACCOUNTS = {
        'incoming_under_collection': '1150',  # شيكات تحت التحصيل
        'outgoing_deferred': '2120',          # شيكات مؤجلة الدفع
        'bank_account': '1120',               # حساب البنك
        'cash_account': '1110',              # صندوق
        'accounts_receivable': '1130',        # الذمم المدينة
        'accounts_payable': '2110',           # الذمم الدائنة
        'bank_charges': '6950',              # مصروفات بنكية
        'exchange_gain': '4400',             # أرباح فرق العملة
        'exchange_loss': '6900',             # خسائر فرق العملة
    }

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
        cheque = db.get_or_404(Cheque, cheque_id)

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
        cheque = db.get_or_404(Cheque, cheque_id)

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
        cheque = db.get_or_404(Cheque, cheque_id)

        if cheque.status not in ['deposited']:
            raise ValueError("الشيك ليس في حالة يمكن صرفه")

        try:
            amount_base = ChequeAccountingIntegration._ensure_amount_base(cheque)
            bank_charges_account = _resolve_role_code('BANK_CHARGES', '6950')
            fx_gain_account = _resolve_role_code('FX_GAIN', '4400')
            fx_loss_account = _resolve_role_code('FX_LOSS', '6900')
            lines = []

            if cheque.cheque_type == 'incoming':
                # شيك وارد - صرف

                # المدين: حساب البنك
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['bank_account'],
                    'debit': amount_base - bank_charges + exchange_gain_loss,
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
                    'credit': amount_base + bank_charges - exchange_gain_loss,
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
        cheque = db.get_or_404(Cheque, cheque_id)

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

            # تحديث حالة الشيك
            cheque.status = 'bounced'
            cheque.bounced_date = datetime.now().date()
            cheque.bounce_reason = bounce_reason
            cheque.gl_bounce_entry_id = entry.id
            cheque.updated_at = datetime.now(timezone.utc)

            db.session.commit()

            return entry

        except Exception as e:
            db.session.rollback()
            raise Exception(f"فشل في تسجيل ارتداد الشيك: {str(e)}")

    @staticmethod
    def get_cheque_accounting_summary(cheque_id):  # noqa: C901
        """الحصول على ملخص محاسبي للشيك"""
        cheque = db.get_or_404(Cheque, cheque_id)

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
