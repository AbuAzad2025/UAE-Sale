from datetime import datetime, timezone
from decimal import Decimal
from extensions import db
from models.gl import GLAccount, GLJournalEntry, GLJournalLine
from utils.decorators import get_owned_or_404


class JournalEntryAudit(db.Model):
    """سجل تدقيق القيود المحاسبية"""
    __tablename__ = 'journal_entry_audits'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    journal_entry_id = db.Column(db.Integer,
                                 db.ForeignKey('gl_journal_entries.id', ondelete='CASCADE'),
                                 nullable=False)
    action = db.Column(db.String(50), nullable=False)  # create, update, reverse, delete, approve
    old_values = db.Column(db.Text)  # JSON للقيم القديمة
    new_values = db.Column(db.Text)  # JSON للقيم الجديدة
    reason = db.Column(db.Text)
    performed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)

    journal_entry = db.relationship('GLJournalEntry')
    user = db.relationship('User')

    def __repr__(self):
        return f'<JournalEntryAudit {self.action} - {self.journal_entry_id}>'


class AdvancedJournalEntryManager:
    """مدير القيود المحاسبية المتقدم"""

    @staticmethod
    def create_entry_with_validation(description, lines, entry_date=None, notes=None, created_by=None, **kwargs):
        """إنشاء قيد مع التحقق المتقدم"""
        from services.gl_service import GLService

        # التحقق من التوازن (Decimal إلزامي — ممنوع الحساب العشري float)
        total_debit = sum(
            (Decimal(str(line.get('debit', 0) or 0)) for line in lines), Decimal('0')
        )
        total_credit = sum(
            (Decimal(str(line.get('credit', 0) or 0)) for line in lines), Decimal('0')
        )

        if abs(total_debit - total_credit) > Decimal('0.01'):
            raise ValueError(f"القيد غير متوازن: المدين {total_debit} ≠ الدائن {total_credit}")

        # التحقق من الحسابات الرئيسية
        for line in lines:
            account_code = line.get('account_code')
            if account_code:
                account = GLAccount.query.filter_by(code=account_code).first()
                if account and account.is_header:
                    raise ValueError(f"لا يمكن القيد على الحساب الرئيسي: {account.full_name}")

        entry_type = kwargs.pop('entry_type', None)
        # إنشاء القيد
        entry = GLService.create_manual_entry(
            description=description,
            lines=lines,
            entry_date=entry_date,
            notes=notes,
            created_by=created_by,
            **kwargs
        )
        if entry_type:
            entry.entry_type = entry_type

        # تسجيل التدقيق
        AdvancedJournalEntryManager._log_audit(
            entry.id, 'create', None, entry.to_dict(),
            f"إنشاء قيد جديد: {description}", created_by
        )

        return entry

    @staticmethod
    def update_entry(entry_id, updates, updated_by, reason=None):
        """تحديث قيد محاسبي"""
        entry = get_owned_or_404(GLJournalEntry, entry_id)

        if entry.is_posted:
            raise ValueError("posted entries immutable; post reversal - لا يمكن تعديل قيد مرحل")

        if entry.is_reversed:
            raise ValueError("لا يمكن تعديل قيد معكوس")

        # حفظ القيم القديمة
        old_values = entry.to_dict()

        # تطبيق التحديثات
        for field, value in updates.items():
            if field == 'lines':
                continue
            if hasattr(entry, field):
                setattr(entry, field, value)

        # التحقق من التوازن إذا تم تحديث السطور
        if 'lines' in updates:
            total_debit = sum((Decimal(str(line.get('debit', 0) or 0)) for line in updates['lines']), Decimal('0'))
            total_credit = sum((Decimal(str(line.get('credit', 0) or 0)) for line in updates['lines']), Decimal('0'))

            if abs(total_debit - total_credit) > Decimal('0.01'):
                raise ValueError(f"القيد غير متوازن بعد التحديث: المدين {total_debit} ≠ الدائن {total_credit}")

            # VALIDATE ALL LINES FIRST (before mutating): كل حساب يجب أن
            # يوجد قبل حذف السطور القديمة — لو فشل التحقق، لا يتأثر أي شيء.
            resolved_lines = []
            seen_accounts = {}
            for line_data in updates['lines']:
                account_code = line_data.get('account_code') or line_data.get('account')
                account = GLAccount.query.filter_by(code=account_code).first() if account_code else None
                if not account:
                    raise ValueError(f'الحساب {account_code} غير موجود')
                if account.is_header:
                    raise ValueError(f"لا يمكن القيد على الحساب الرئيسي: {account.full_name}")
                if account.id in seen_accounts:
                    account = seen_accounts[account.id]
                else:
                    seen_accounts[account.id] = account
                debit = Decimal(str(line_data.get('debit', 0) or 0))
                credit = Decimal(str(line_data.get('credit', 0) or 0))
                if debit < 0 or credit < 0:
                    raise ValueError('المبالغ يجب أن تكون موجبة')
                resolved_lines.append({
                    'account': account,
                    'description': line_data.get('description', ''),
                    'debit': debit,
                    'credit': credit,
                    'amount_base': debit - credit,
                })

            # All validations passed — now atomically replace lines.
            GLJournalLine.query.filter_by(entry_id=entry_id).delete()
            for resolved in resolved_lines:
                db.session.add(GLJournalLine(
                    entry_id=entry.id,
                    account_id=resolved['account'].id,
                    description=resolved['description'],
                    debit=resolved['debit'],
                    credit=resolved['credit'],
                    amount_base=resolved['amount_base'],
                ))
            entry.total_debit = total_debit
            entry.total_credit = total_credit

        entry.updated_at = datetime.now(timezone.utc)

        # تسجيل التدقيق
        AdvancedJournalEntryManager._log_audit(
            entry_id, 'update', old_values, entry.to_dict(),
            reason or "تحديث القيد", updated_by
        )

        db.session.commit()
        return entry

    @staticmethod
    def reverse_entry_advanced(entry_id, reversed_by, reason, create_reversal_entry=True):
        """عكس قيد محاسبي متقدم"""
        entry = get_owned_or_404(GLJournalEntry, entry_id)

        if entry.is_reversed:
            raise ValueError("القيد معكوس مسبقاً")

        if not entry.is_posted:
            raise ValueError("لا يمكن عكس قيد غير مرحل")

        # حفظ القيم القديمة
        old_values = entry.to_dict()

        # إنشاء قيد عكسي إذا طُلب
        reversal_entry = None
        if create_reversal_entry:
            reversal_lines = []
            for line in entry.lines:
                reversal_lines.append({
                    'account_code': line.account.code,
                    'debit': line.credit,  # عكس الاتجاه
                    'credit': line.debit,  # عكس الاتجاه
                    'description': f"عكس: {line.description or ''}"
                })

            reversal_entry = AdvancedJournalEntryManager.create_entry_with_validation(
                description=f"عكس القيد {entry.entry_number}",
                lines=reversal_lines,
                entry_date=datetime.now().date(),
                notes=f"سبب العكس: {reason}",
                created_by=reversed_by,
                entry_type='reversing'
            )

            # ربط القيد العكسي بالمصدر الأصلي (نفس أسلوب إلغاء الشيكات)
            reversal_entry.reference_type = entry.reference_type
            reversal_entry.reference_id = entry.reference_id

            # ربط القيود
            entry.is_reversed = True
            entry.reversed_entry_id = reversal_entry.id
            reversal_entry.reversed_entry_id = entry.id

        # تسجيل التدقيق
        AdvancedJournalEntryManager._log_audit(
            entry_id, 'reverse', old_values, entry.to_dict(),
            f"عكس القيد - السبب: {reason}", reversed_by
        )

        db.session.commit()
        return reversal_entry

    @staticmethod
    def delete_entry(entry_id, deleted_by, reason):
        """حذف قيد محاسبي"""
        entry = get_owned_or_404(GLJournalEntry, entry_id)

        if entry.is_posted:
            raise ValueError("posted entries immutable; post reversal - لا يمكن حذف قيد مرحل - استخدم العكس بدلاً من ذلك")

        if entry.is_reversed:
            raise ValueError("لا يمكن حذف قيد معكوس")

        # التحقق من وجود قيود مرتبطة
        if entry.reversed_entry_id:
            raise ValueError("لا يمكن حذف قيد له قيود عكسية مرتبطة")

        # حفظ القيم القديمة
        old_values = entry.to_dict()

        # تسجيل التدقيق أولاً (يشير للقيد وهو ما زال موجوداً؛
        # CASCADE يحافظ على السجل بعد الحذف)
        AdvancedJournalEntryManager._log_audit(
            entry_id, 'delete', old_values, None,
            f"حذف القيد - السبب: {reason}", deleted_by
        )

        # حذف السطور ثم القيد
        GLJournalLine.query.filter_by(entry_id=entry_id).delete()
        db.session.delete(entry)

        db.session.commit()
        return True

    @staticmethod
    def approve_entry(entry_id, approved_by, approval_notes=None):
        """الموافقة على قيد محاسبي"""
        entry = get_owned_or_404(GLJournalEntry, entry_id)

        if entry.is_posted:
            raise ValueError("القيد مرحل مسبقاً")

        # التحقق من التوازن مرة أخرى
        total_debit = sum((line.debit for line in entry.lines), Decimal('0'))
        total_credit = sum((line.credit for line in entry.lines), Decimal('0'))

        if abs(total_debit - total_credit) > Decimal('0.01'):
            raise ValueError(f"القيد غير متوازن: المدين {total_debit} ≠ الدائن {total_credit}")

        # الموافقة
        entry.is_posted = True
        entry.updated_at = datetime.now(timezone.utc)

        # تسجيل التدقيق
        AdvancedJournalEntryManager._log_audit(
            entry_id, 'approve', entry.to_dict(), entry.to_dict(),
            f"الموافقة على القيد - ملاحظات: {approval_notes or 'لا توجد'}",
            approved_by
        )

        db.session.commit()
        return entry

    @staticmethod
    def get_entry_history(entry_id):
        """الحصول على تاريخ القيد"""
        return JournalEntryAudit.query.filter_by(journal_entry_id=entry_id)\
            .order_by(JournalEntryAudit.performed_at.desc()).all()

    @staticmethod
    def _log_audit(entry_id, action, old_values, new_values, reason, user_id):
        """تسجيل تدقيق"""
        audit = JournalEntryAudit(
            journal_entry_id=entry_id,
            action=action,
            old_values=str(old_values) if old_values else None,
            new_values=str(new_values) if new_values else None,
            reason=reason,
            performed_by=user_id,
            performed_at=datetime.now(timezone.utc)
        )
        db.session.add(audit)

# إضافة دالة مساعدة لـ GLJournalEntry


def add_helper_methods():
    """إضافة دوال مساعدة لـ GLJournalEntry"""

    def to_dict(self):
        """تحويل القيد إلى قاموس"""
        return {
            'id': self.id,
            'entry_number': self.entry_number,
            'entry_date': self.entry_date.isoformat() if self.entry_date else None,
            'description': self.description,
            'entry_type': self.entry_type,
            'total_debit': float(self.total_debit),
            'total_credit': float(self.total_credit),
            'is_posted': self.is_posted,
            'is_reversed': self.is_reversed,
            'notes': self.notes,
            'lines': [
                {
                    'account_code': line.account.code,
                    'account_name': line.account.full_name,
                    'debit': float(line.debit),
                    'credit': float(line.credit),
                    'description': line.description
                }
                for line in self.lines
            ]
        }

    def get_balance_status(self):
        """الحصول على حالة التوازن"""
        difference = abs(Decimal(str(self.total_debit)) - Decimal(str(self.total_credit)))
        if difference < Decimal('0.01'):
            return 'balanced'
        elif difference < Decimal('10'):
            return 'minor_imbalance'
        else:
            return 'major_imbalance'

    def can_be_modified(self):
        """فحص إمكانية التعديل"""
        return not self.is_posted and not self.is_reversed

    def can_be_reversed(self):
        """فحص إمكانية العكس"""
        return self.is_posted and not self.is_reversed

    def can_be_deleted(self):
        """فحص إمكانية الحذف"""
        return not self.is_posted and not self.is_reversed and not self.reversed_entry_id

    # إضافة الدوال للكلاس
    GLJournalEntry.to_dict = to_dict
    GLJournalEntry.get_balance_status = get_balance_status
    GLJournalEntry.can_be_modified = can_be_modified
    GLJournalEntry.can_be_reversed = can_be_reversed
    GLJournalEntry.can_be_deleted = can_be_deleted


# استدعاء الدوال المساعدة
add_helper_methods()
