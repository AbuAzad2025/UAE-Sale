from datetime import datetime, timezone
from extensions import db
from models.cheque import Cheque
from models.gl import GLAccount, GLJournalEntry
from services.gl_service import GLService


class ChequeAccountingIntegration:
    """تكامل الشيكات مع النظام المحاسبي"""

    # حسابات الشيكات الافتراضية
    CHEQUE_ACCOUNTS = {
        'incoming_under_collection': '1150',  # شيكات تحت التحصيل
        'outgoing_deferred': '2120',          # شيكات مؤجلة الدفع
        'bank_account': '1120',               # حساب البنك
        'cash_account': '1110',              # صندوق
        'accounts_receivable': '1130',        # الذمم المدينة
        'accounts_payable': '2110',           # الذمم الدائنة
        'exchange_gain': '4200',             # أرباح الصرف
        'exchange_loss': '5200',             # خسائر الصرف
    }

    @staticmethod
    def receive_cheque(cheque_id, received_by=None):
        """تسجيل استلام شيك وارد مع القيود المحاسبية"""
        cheque = db.get_or_404(Cheque, cheque_id)

        if cheque.cheque_type != 'incoming':
            raise ValueError("هذا الشيك ليس شيك وارد")

        if cheque.status != 'pending':
            raise ValueError("الشيك ليس في حالة معلق")

        try:
            # إنشاء القيد المحاسبي
            lines = []

            # المدين: شيكات تحت التحصيل
            lines.append({
                'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['incoming_under_collection'],
                'debit': cheque.amount_base,
                'credit': 0,
                'description': f'استلام شيك وارد رقم {cheque.cheque_bank_number} من {cheque.customer.name if cheque.customer else "غير محدد"}'
            })

            # الدائن: الذمم المدينة
            lines.append({
                'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['accounts_receivable'],
                'debit': 0,
                'credit': cheque.amount_base,
                'description': f'تسوية ذمم مدينة - شيك رقم {cheque.cheque_bank_number}'
            })

            # إنشاء القيد
            entry = GLService.create_manual_entry(
                description=f'استلام شيك وارد رقم {cheque.cheque_bank_number}',
                lines=lines,
                entry_date=cheque.received_date or datetime.now().date(),
                reference_type='cheque_receive',
                reference_id=cheque.id,
                created_by=received_by
            )

            # تحديث حالة الشيك
            cheque.status = 'received'
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
            # إنشاء القيد المحاسبي
            lines = []

            # المدين: الذمم الدائنة
            lines.append({
                'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['accounts_payable'],
                'debit': cheque.amount_base,
                'credit': 0,
                'description': f'تسوية ذمم دائنة - شيك رقم {cheque.cheque_bank_number}'
            })

            # الدائن: شيكات مؤجلة الدفع
            lines.append({
                'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['outgoing_deferred'],
                'debit': 0,
                'credit': cheque.amount_base,
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

            # تحديث حالة الشيك
            cheque.status = 'issued'
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

        if cheque.status not in ['received', 'issued']:
            raise ValueError("الشيك ليس في حالة يمكن صرفه")

        try:
            lines = []

            if cheque.cheque_type == 'incoming':
                # شيك وارد - صرف

                # المدين: حساب البنك
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['bank_account'],
                    'debit': cheque.amount_base - bank_charges + exchange_gain_loss,
                    'credit': 0,
                    'description': f'صرف شيك وارد رقم {cheque.cheque_bank_number}'
                })

                # الدائن: شيكات تحت التحصيل
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['incoming_under_collection'],
                    'debit': 0,
                    'credit': cheque.amount_base,
                    'description': f'صرف شيك تحت التحصيل رقم {cheque.cheque_bank_number}'
                })

                # رسوم البنك (إذا وجدت)
                if bank_charges > 0:
                    lines.append({
                        'account_code': '5300',  # رسوم البنك
                        'debit': bank_charges,
                        'credit': 0,
                        'description': f'رسوم بنك - شيك رقم {cheque.cheque_bank_number}'
                    })

                # أرباح/خسائر الصرف (إذا وجدت)
                if exchange_gain_loss != 0:
                    if exchange_gain_loss > 0:
                        lines.append({
                            'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['exchange_gain'],
                            'debit': 0,
                            'credit': exchange_gain_loss,
                            'description': f'ربح صرف - شيك رقم {cheque.cheque_bank_number}'
                        })
                    else:
                        lines.append({
                            'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['exchange_loss'],
                            'debit': abs(exchange_gain_loss),
                            'credit': 0,
                            'description': f'خسارة صرف - شيك رقم {cheque.cheque_bank_number}'
                        })

            elif cheque.cheque_type == 'outgoing':
                # شيك صادر - صرف

                # المدين: شيكات مؤجلة الدفع
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['outgoing_deferred'],
                    'debit': cheque.amount_base,
                    'credit': 0,
                    'description': f'صرف شيك مؤجل الدفع رقم {cheque.cheque_bank_number}'
                })

                # الدائن: حساب البنك
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['bank_account'],
                    'debit': 0,
                    'credit': cheque.amount_base + bank_charges - exchange_gain_loss,
                    'description': f'صرف شيك صادر رقم {cheque.cheque_bank_number}'
                })

                # رسوم البنك (إذا وجدت)
                if bank_charges > 0:
                    lines.append({
                        'account_code': '5300',  # رسوم البنك
                        'debit': bank_charges,
                        'credit': 0,
                        'description': f'رسوم بنك - شيك رقم {cheque.cheque_bank_number}'
                    })

                # أرباح/خسائر الصرف (إذا وجدت)
                if exchange_gain_loss != 0:
                    if exchange_gain_loss > 0:
                        lines.append({
                            'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['exchange_gain'],
                            'debit': 0,
                            'credit': exchange_gain_loss,
                            'description': f'ربح صرف - شيك رقم {cheque.cheque_bank_number}'
                        })
                    else:
                        lines.append({
                            'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['exchange_loss'],
                            'debit': abs(exchange_gain_loss),
                            'credit': 0,
                            'description': f'خسارة صرف - شيك رقم {cheque.cheque_bank_number}'
                        })

            # إنشاء القيد
            entry = GLService.create_manual_entry(
                description=f'صرف شيك {cheque.cheque_type_ar} رقم {cheque.cheque_bank_number}',
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

        if cheque.status not in ['received', 'issued']:
            raise ValueError("الشيك ليس في حالة يمكن ارتداده")

        try:
            lines = []

            if cheque.cheque_type == 'incoming':
                # شيك وارد - ارتداد

                # المدين: الذمم المدينة (استرداد)
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['accounts_receivable'],
                    'debit': cheque.amount_base,
                    'credit': 0,
                    'description': f'استرداد ذمم مدينة - شيك مرتد رقم {cheque.cheque_bank_number}'
                })

                # الدائن: شيكات تحت التحصيل
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['incoming_under_collection'],
                    'debit': 0,
                    'credit': cheque.amount_base,
                    'description': f'شيك مرتد رقم {cheque.cheque_bank_number}'
                })

            elif cheque.cheque_type == 'outgoing':
                # شيك صادر - ارتداد

                # المدين: شيكات مؤجلة الدفع
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['outgoing_deferred'],
                    'debit': cheque.amount_base,
                    'credit': 0,
                    'description': f'شيك صادر مرتد رقم {cheque.cheque_bank_number}'
                })

                # الدائن: الذمم الدائنة (استرداد)
                lines.append({
                    'account_code': ChequeAccountingIntegration.CHEQUE_ACCOUNTS['accounts_payable'],
                    'debit': 0,
                    'credit': cheque.amount_base,
                    'description': f'استرداد ذمم دائنة - شيك مرتد رقم {cheque.cheque_bank_number}'
                })

            # إنشاء القيد
            entry = GLService.create_manual_entry(
                description=f'ارتداد شيك {cheque.cheque_type_ar} رقم {cheque.cheque_bank_number}',
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
                'type': cheque.cheque_type_ar,
                'amount': float(cheque.amount_base),
                'status': cheque.status_ar,
                'date': cheque.cheque_date.isoformat() if cheque.cheque_date else None
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
