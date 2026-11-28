from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from extensions import db
from models.gl import GLAccount, GLJournalEntry, GLJournalLine
from models.journal_entry_audit import JournalEntryAudit
from utils.balance_checker import amounts_balanced, is_journal_balanced
from utils.decorators import get_owned_or_404

_THREE_DP = Decimal("0.001")


def _quantize_3(value):
    """تكميم إلى 3 خانات عشرية (ROUND_HALF_UP) — لا حسابات عشوائية أبداً."""
    return Decimal(str(value)).quantize(_THREE_DP, rounding=ROUND_HALF_UP)


class AdvancedJournalEntryManager:
    """مدير القيود المحاسبية المتقدم"""

    @staticmethod
    def create_entry_with_validation(
        description, lines, entry_date=None, notes=None, created_by=None, **kwargs
    ):
        """إنشاء قيد مع التحقق المتقدم"""
        from services.gl_service import GLService

        total_debit = sum(
            (Decimal(str(line.get("debit", 0) or 0)) for line in lines), Decimal("0")
        )
        total_credit = sum(
            (Decimal(str(line.get("credit", 0) or 0)) for line in lines), Decimal("0")
        )

        if not is_journal_balanced(lines):
            raise ValueError(
                f"القيد غير متوازن: المدين {total_debit} ≠ الدائن {total_credit}"
            )

        if created_by is None:
            # Headless callers must still name an actor; never leave the
            # posting (and its audit row) silently unattributed.
            created_by = JournalEntryAudit.resolve_actor_id()

        for line in lines:
            account_code = line.get("account_code")
            if account_code:
                account = GLAccount.query.filter_by(code=account_code).first()
                if account and account.is_header:
                    raise ValueError(
                        f"لا يمكن القيد على الحساب الرئيسي: {account.full_name}"
                    )

        entry_type = kwargs.pop("entry_type", None)
        if entry_type:
            kwargs["entry_type"] = entry_type

        entry = GLService.create_manual_entry(
            description=description,
            lines=lines,
            entry_date=entry_date,
            notes=notes,
            created_by=created_by,
            **kwargs,
        )

        return entry

    @staticmethod
    def update_entry(entry_id, updates, updated_by, reason=None):
        """تحديث قيد محاسبي"""
        entry = get_owned_or_404(GLJournalEntry, entry_id)
        db.session.refresh(entry, with_for_update=True)

        if entry.is_posted:
            raise ValueError(
                "posted entries immutable; post reversal - لا يمكن تعديل قيد مرحل"
            )

        if entry.is_reversed:
            raise ValueError("لا يمكن تعديل قيد معكوس")

        old_values = entry.to_dict()

        rate = Decimal(str(entry.exchange_rate or 1)) or Decimal("1")

        editable = {
            "lines",
            "description",
            "notes",
            "entry_date",
            "currency",
            "exchange_rate",
        }
        if updates.keys() - editable:
            raise ValueError("Only draft financial details can be edited.")
        for field, value in updates.items():
            if field == "lines":
                continue
            if hasattr(entry, field):
                setattr(entry, field, value)

        if "lines" in updates:
            total_debit = sum(
                (Decimal(str(line.get("debit", 0) or 0)) for line in updates["lines"]),
                Decimal("0"),
            )
            total_credit = sum(
                (Decimal(str(line.get("credit", 0) or 0)) for line in updates["lines"]),
                Decimal("0"),
            )

            if not is_journal_balanced(updates["lines"]):
                raise ValueError(
                    f"القيد غير متوازن بعد التحديث: المدين {total_debit} ≠ الدائن {total_credit}"
                )

            # Capture the old party links before the bulk delete so a rebuild
            # does not silently detach customers/partners from the entry.
            old_lines = {
                line.id: line
                for line in GLJournalLine.query.filter_by(entry_id=entry_id).all()
            }

            resolved_lines = []
            seen_accounts = {}
            for line_data in updates["lines"]:
                account_code = line_data.get("account_code") or line_data.get("account")
                account = (
                    GLAccount.query.filter_by(code=account_code).first()
                    if account_code
                    else None
                )
                if not account:
                    raise ValueError(f"الحساب {account_code} غير موجود")
                if account.is_header:
                    raise ValueError(
                        f"لا يمكن القيد على الحساب الرئيسي: {account.full_name}"
                    )
                if account.id in seen_accounts:
                    account = seen_accounts[account.id]
                else:
                    seen_accounts[account.id] = account
                debit = _quantize_3(line_data.get("debit", 0) or 0)
                credit = _quantize_3(line_data.get("credit", 0) or 0)
                if debit < 0 or credit < 0:
                    raise ValueError("المبالغ يجب أن تكون موجبة")
                if debit > 0 and credit > 0:
                    raise ValueError("السطر لا يحمل مديناً ودائناً في آن واحد")
                account.check_posting_direction(debit, credit)
                party_id = line_data.get("party_id")
                if party_id is None:
                    old_line = old_lines.get(line_data.get("id"))
                    if old_line is not None:
                        party_id = old_line.party_id
                resolved_lines.append(
                    {
                        "account": account,
                        "description": line_data.get("description", ""),
                        "debit": debit,
                        "credit": credit,
                        "amount_base": _quantize_3((debit - credit) * rate),
                        "party_id": party_id,
                    }
                )

            GLJournalLine.query.filter_by(entry_id=entry_id).delete()
            for resolved in resolved_lines:
                db.session.add(
                    GLJournalLine(
                        entry_id=entry.id,
                        account_id=resolved["account"].id,
                        description=resolved["description"],
                        debit=resolved["debit"],
                        credit=resolved["credit"],
                        amount_base=resolved["amount_base"],
                        party_id=resolved["party_id"],
                    )
                )
            entry.total_debit = sum((r["debit"] for r in resolved_lines), Decimal("0"))
            entry.total_credit = sum(
                (r["credit"] for r in resolved_lines), Decimal("0")
            )

        entry.updated_at = datetime.now(timezone.utc)

        AdvancedJournalEntryManager._log_audit(
            entry_id,
            "update",
            old_values,
            entry.to_dict(),
            reason or "تحديث القيد",
            updated_by,
        )

        db.session.flush()
        return entry

    @staticmethod
    def reverse_entry_advanced(
        entry_id, reversed_by, reason, create_reversal_entry=True
    ):
        """عكس قيد محاسبي متقدم"""
        entry = get_owned_or_404(GLJournalEntry, entry_id)

        if (
            entry.is_reversed
            or entry.reversed_entry_id is not None
            or entry.entry_type == "reversing"
        ):
            raise ValueError("القيد معكوس مسبقاً")

        if not entry.is_posted:
            raise ValueError("لا يمكن عكس قيد غير مرحل")

        old_values = entry.to_dict()
        actor = JournalEntryAudit.resolve_actor_id(reversed_by, fallback_entry=entry)

        reversal_entry = None
        if create_reversal_entry:
            reversal_entry = entry.reverse_entry(
                description=f"عكس القيد {entry.entry_number}",
                created_by=actor,
                notes=f"سبب العكس: {reason}",
            )
            JournalEntryAudit.record(
                journal_entry_id=reversal_entry.id,
                action=JournalEntryAudit.ACTION_CREATE,
                new_values=JournalEntryAudit.entry_payload(reversal_entry),
                reason=reason,
                performed_by=actor,
                fallback_entry=entry,
            )

        AdvancedJournalEntryManager._log_audit(
            entry_id,
            "reverse",
            old_values,
            entry.to_dict(),
            f"عكس القيد - السبب: {reason}",
            reversed_by,
        )

        db.session.flush()
        return reversal_entry

    @staticmethod
    def delete_entry(entry_id, deleted_by, reason):
        """حذف قيد محاسبي"""
        entry = get_owned_or_404(GLJournalEntry, entry_id)

        if entry.is_posted:
            raise ValueError(
                "posted entries immutable; post reversal - لا يمكن حذف قيد مرحل - استخدم العكس بدلاً من ذلك"
            )

        if entry.is_reversed:
            raise ValueError("لا يمكن حذف قيد معكوس")

        if entry.reversed_entry_id:
            raise ValueError("لا يمكن حذف قيد له قيود عكسية مرتبطة")

        old_values = entry.to_dict()

        AdvancedJournalEntryManager._log_audit(
            entry_id,
            "delete",
            old_values,
            None,
            f"حذف القيد - السبب: {reason}",
            deleted_by,
        )

        GLJournalLine.query.filter_by(entry_id=entry_id).delete()
        db.session.delete(entry)

        db.session.flush()
        return True

    @staticmethod
    def approve_entry(entry_id, approved_by, approval_notes=None):
        """الموافقة على قيد محاسبي"""
        from sqlalchemy import or_, select
        from services.gl_service import (
            _assert_period_open,
            _normalize_lines,
            _normalize_rate,
            _posting_tenant,
        )

        entry = get_owned_or_404(GLJournalEntry, entry_id)
        db.session.refresh(entry, with_for_update=True)
        tenant_id = _posting_tenant(entry.tenant_id)

        if entry.is_posted:
            raise ValueError("القيد مرحل مسبقاً")
        if entry.is_reversed:
            raise ValueError("لا يمكن اعتماد قيد معكوس")

        line_table = GLJournalLine.__table__
        if (
            db.session.scalar(
                select(line_table.c.id)
                .where(
                    line_table.c.entry_id == entry.id,
                    or_(
                        line_table.c.tenant_id.is_(None),
                        line_table.c.tenant_id != tenant_id,
                    ),
                )
                .limit(1)
            )
            is not None
        ):
            raise ValueError("Journal lines must belong to the journal's tenant")
        lines = entry.lines.order_by(GLJournalLine.id).all()
        _assert_period_open(entry.entry_date, tenant_id)
        normalized, total_debit, total_credit = _normalize_lines(
            [
                {
                    "account": line.account,
                    "debit": line.debit,
                    "credit": line.credit,
                    "party_id": line.party_id,
                }
                for line in lines
            ],
            _normalize_rate(entry.exchange_rate),
            tenant_id=tenant_id,
            ensure_accounts=False,
        )

        if not amounts_balanced(total_debit, total_credit):
            raise ValueError(
                f"القيد غير متوازن: المدين {total_debit} ≠ الدائن {total_credit}"
            )

        old_values = entry.to_dict()
        entry.total_debit = total_debit
        entry.total_credit = total_credit
        for line, validated in zip(lines, normalized):
            line.amount_base = validated.amount_base
        entry.is_posted = True
        entry.updated_at = datetime.now(timezone.utc)

        AdvancedJournalEntryManager._log_audit(
            entry_id,
            "approve",
            old_values,
            entry.to_dict(),
            f"الموافقة على القيد - ملاحظات: {approval_notes or 'لا توجد'}",
            approved_by,
        )

        db.session.flush()
        return entry

    @staticmethod
    def get_entry_history(entry_id):
        """الحصول على تاريخ القيد"""
        return (
            JournalEntryAudit.query.filter_by(journal_entry_id=entry_id)
            .order_by(JournalEntryAudit.performed_at.desc())
            .all()
        )

    @staticmethod
    def _log_audit(entry_id, action, old_values, new_values, reason, user_id):
        """تسجيل تدقيق عبر الكاتب الوحيد (JournalEntryAudit.record)."""
        entry = db.session.get(GLJournalEntry, entry_id)
        # An explicit actor is required for headless callers; the entry is
        # passed as a fallback so an unknown user never becomes a NULL insert.
        actor = JournalEntryAudit.resolve_actor_id(user_id, fallback_entry=entry)
        JournalEntryAudit.record(
            journal_entry_id=entry_id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            performed_by=actor,
            fallback_entry=entry,
        )


def add_helper_methods():
    """إضافة دوال مساعدة لـ GLJournalEntry"""

    def to_dict(self):
        """تحويل القيد إلى قاموس"""
        return {
            "id": self.id,
            "entry_number": self.entry_number,
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "description": self.description,
            "entry_type": self.entry_type,
            "total_debit": float(self.total_debit),
            "total_credit": float(self.total_credit),
            "is_posted": self.is_posted,
            "is_reversed": self.is_reversed,
            "notes": self.notes,
            "lines": [
                {
                    "account_code": line.account.code,
                    "account_name": line.account.full_name,
                    "debit": float(line.debit),
                    "credit": float(line.credit),
                    "description": line.description,
                }
                for line in self.lines
            ],
        }

    def get_balance_status(self):
        """الحصول على حالة التوازن"""
        difference = abs(
            Decimal(str(self.total_debit or 0)) - Decimal(str(self.total_credit or 0))
        )
        if amounts_balanced(self.total_debit, self.total_credit):
            return "balanced"
        elif difference < Decimal("10"):
            return "minor_imbalance"
        else:
            return "major_imbalance"

    def can_be_modified(self):
        """فحص إمكانية التعديل"""
        return not self.is_posted and not self.is_reversed

    def can_be_reversed(self):
        """فحص إمكانية العكس"""
        return self.is_posted and not self.is_reversed

    def can_be_deleted(self):
        """فحص إمكانية الحذف"""
        return (
            not self.is_posted and not self.is_reversed and not self.reversed_entry_id
        )

    GLJournalEntry.to_dict = to_dict
    GLJournalEntry.get_balance_status = get_balance_status
    GLJournalEntry.can_be_modified = can_be_modified
    GLJournalEntry.can_be_reversed = can_be_reversed
    GLJournalEntry.can_be_deleted = can_be_deleted


add_helper_methods()
