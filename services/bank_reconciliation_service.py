"""
خدمة مطابقة البنك - Bank Reconciliation Service
"""

from decimal import Decimal
from extensions import db
from models import (
    BankReconciliation,
    BankReconciliationItem,
    GLAccount,
    Cheque,
    GLJournalEntry,
    GLJournalLine,
)
from services.account_resolution import AccountResolver, AccountRole
from services.gl_service import GLService, _posting_tenant
from utils.decorators import get_owned_or_404
from utils.helpers import generate_number


class BankReconciliationService:
    @staticmethod
    def _bank_account(account_id, tenant_id):
        account = db.get_or_404(GLAccount, account_id)
        codes = AccountResolver.resolve_codes(
            AccountRole.BANK, AccountRole.BANK_SAVINGS, tenant_id=tenant_id
        )
        if (
            account.code not in codes.values()
            or account.type != "asset"
            or not account.is_active
            or account.is_header
        ):
            raise ValueError("Choose a postable bank account mapped to this tenant.")
        return account

    @staticmethod
    def create_reconciliation(
        bank_account_id,
        period_start,
        period_end,
        closing_balance_per_bank,
        created_by=None,
    ):
        """
        إنشاء مطابقة بنك جديدة
        """
        from flask_login import current_user

        tenant_id = _posting_tenant(None)
        if period_end < period_start:
            raise ValueError("Bank reconciliation end date must not precede its start.")
        BankReconciliationService._bank_account(bank_account_id, tenant_id)

        statement = GLService.get_account_statement(
            bank_account_id, date_from=period_start, date_to=period_end
        )

        closing_balance_per_books = Decimal(str(statement["closing_balance"]))
        opening_balance = Decimal(str(statement["opening_balance"]))

        reconciliation_number = generate_number(
            "BR", BankReconciliation, "reconciliation_number"
        )

        reconciliation = BankReconciliation(
            reconciliation_number=reconciliation_number,
            bank_account_id=bank_account_id,
            period_start=period_start,
            period_end=period_end,
            opening_balance_per_books=opening_balance,
            closing_balance_per_books=closing_balance_per_books,
            closing_balance_per_bank=Decimal(str(closing_balance_per_bank)),
            tenant_id=tenant_id,
            created_by=created_by
            or (
                current_user.id
                if (getattr(current_user, "is_authenticated", False))
                else None
            ),
        )

        db.session.add(reconciliation)
        db.session.flush()

        BankReconciliationService._auto_populate_items(reconciliation)

        reconciliation.calculate_reconciliation()

        db.session.flush()
        return reconciliation

    @staticmethod
    def _outstanding(bank_account_id, period_end, tenant_id):
        """Outstanding cheques from the register plus their posted control lines.

        Cheques may post to the bank account directly (legacy) or to the
        Under Collection / Deferred Cheques control accounts (production).
        Register-only cheques with no posted line are not bank items.
        """
        from datetime import date as _date
        from sqlalchemy import func

        control_codes = {"1150", "2120"}
        rows = (
            db.session.query(Cheque, GLJournalLine.account_id, GLAccount.code,
                             func.sum(GLJournalLine.amount_base))
            .join(GLJournalEntry, GLJournalEntry.id == Cheque.gl_journal_entry_id)
            .join(GLJournalLine, GLJournalLine.entry_id == GLJournalEntry.id)
            .join(GLAccount, GLAccount.id == GLJournalLine.account_id)
            .filter(
                Cheque.tenant_id == tenant_id,
                Cheque.is_active.is_(True),
                Cheque.status.in_(("pending", "deposited", "under_collection", "overdue")),
                Cheque.gl_clearing_entry_id.is_(None),
                Cheque.issue_date <= period_end,
                GLJournalEntry.is_posted.is_(True),
                GLJournalEntry.is_reversed.is_(False),
                func.date(GLJournalEntry.entry_date) <= period_end,
            )
            .group_by(Cheque.id, GLJournalLine.account_id, GLAccount.code)
            .all()
        )
        out, seen = [], set()
        for cheque, account_id, code, signed_amount in rows:
            if account_id != bank_account_id and (code or "") not in control_codes:
                continue
            if cheque.id in seen or not signed_amount:
                continue
            if (signed_amount > 0) != (cheque.cheque_type == "incoming"):
                continue
            seen.add(cheque.id)
            d = cheque.issue_date
            if not isinstance(d, _date) and hasattr(d, "date"):
                d = d.date()
            out.append((cheque, d, abs(signed_amount)))
        return out

    @staticmethod
    def _auto_populate_items(reconciliation):
        for cheque, posting_date, amount in BankReconciliationService._outstanding(
            reconciliation.bank_account_id,
            reconciliation.period_end,
            reconciliation.tenant_id,
        ):
            incoming = cheque.cheque_type == "incoming"
            party = cheque.drawer_name if incoming else cheque.payee_name
            db.session.add(
                BankReconciliationItem(
                    reconciliation_id=reconciliation.id,
                    item_type="outstanding_deposit"
                    if incoming
                    else "outstanding_withdrawal",
                    transaction_date=posting_date,
                    description=f"شيك رقم {cheque.cheque_bank_number} - {party or ''}",
                    amount=amount,
                    cheque_id=cheque.id,
                    tenant_id=reconciliation.tenant_id,
                )
            )
            if incoming:
                reconciliation.outstanding_deposits += amount
            else:
                reconciliation.outstanding_withdrawals += amount

    @staticmethod
    def add_bank_charge(reconciliation_id, amount, description, transaction_date=None):
        """
        إضافة مصروف بنكي
        """
        reconciliation = get_owned_or_404(BankReconciliation, reconciliation_id)

        if reconciliation.status != "draft":
            raise ValueError("لا يمكن تعديل مطابقة معتمدة")

        item = BankReconciliationItem(
            reconciliation_id=reconciliation_id,
            item_type="bank_charge",
            transaction_date=transaction_date or reconciliation.period_end,
            description=description,
            amount=abs(Decimal(str(amount))),
        )
        db.session.add(item)

        reconciliation.bank_charges += abs(Decimal(str(amount)))
        reconciliation.calculate_reconciliation()

        db.session.flush()
        return item

    @staticmethod
    def add_bank_interest(
        reconciliation_id, amount, description, transaction_date=None
    ):
        """
        إضافة فائدة بنكية
        """
        reconciliation = get_owned_or_404(BankReconciliation, reconciliation_id)

        if reconciliation.status != "draft":
            raise ValueError("لا يمكن تعديل مطابقة معتمدة")

        item = BankReconciliationItem(
            reconciliation_id=reconciliation_id,
            item_type="bank_interest",
            transaction_date=transaction_date or reconciliation.period_end,
            description=description,
            amount=abs(Decimal(str(amount))),
        )
        db.session.add(item)

        reconciliation.bank_interest += abs(Decimal(str(amount)))
        reconciliation.calculate_reconciliation()

        db.session.flush()
        return item

    @staticmethod
    def complete_reconciliation(reconciliation_id):
        """
        إكمال المطابقة وإنشاء القيود التسوية
        """
        reconciliation = get_owned_or_404(BankReconciliation, reconciliation_id)
        db.session.refresh(reconciliation, with_for_update=True)

        if reconciliation.status != "draft":
            raise ValueError("المطابقة معتمدة مسبقاً")

        result = reconciliation.calculate_reconciliation()

        if not result["is_balanced"]:
            raise ValueError(f"المطابقة غير متوازنة - الفرق: {result['difference']}")

        lines = []

        if reconciliation.bank_charges > 0:
            lines.append(
                {
                    "account": AccountResolver.resolve(
                        AccountRole.BANK_CHARGES, tenant_id=reconciliation.tenant_id
                    ),
                    "debit": reconciliation.bank_charges,
                    "credit": 0,
                    "description": "مصاريف بنكية",
                }
            )
            lines.append(
                {
                    "account": str(reconciliation.bank_account.code),  # البنك
                    "debit": 0,
                    "credit": reconciliation.bank_charges,
                    "description": "مصاريف بنكية",
                }
            )

        if reconciliation.bank_interest > 0:
            lines.append(
                {
                    "account": str(reconciliation.bank_account.code),  # البنك
                    "debit": reconciliation.bank_interest,
                    "credit": 0,
                    "description": "فوائد بنكية",
                }
            )
            lines.append(
                {
                    "account": AccountResolver.resolve(
                        AccountRole.OTHER_REVENUE, tenant_id=reconciliation.tenant_id
                    ),
                    "debit": 0,
                    "credit": reconciliation.bank_interest,
                    "description": "فوائد بنكية",
                }
            )

        if lines:
            GLService.post_entry(
                lines=lines,
                description=f"قيد تسوية بنك - {reconciliation.reconciliation_number}",
                reference_type="bank_reconciliation",
                reference_id=reconciliation.id,
                tenant_id=reconciliation.tenant_id,
                entry_date=reconciliation.period_end,
                idempotency_key=f"bank-reconciliation:{reconciliation.id}",
            )

        reconciliation.status = "completed"

        db.session.flush()
        return reconciliation

    @staticmethod
    def get_reconciliation_summary(bank_account_id, period_start, period_end):
        """
        ملخص المطابقة قبل الإنشاء
        """
        tenant_id = _posting_tenant(None)
        BankReconciliationService._bank_account(bank_account_id, tenant_id)
        statement = GLService.get_account_statement(
            bank_account_id, date_from=period_start, date_to=period_end
        )

        rows = BankReconciliationService._outstanding(
            bank_account_id, period_end, tenant_id
        )
        deposits = [
            (cheque, amount)
            for cheque, _, amount in rows
            if cheque.cheque_type == "incoming"
        ]
        withdrawals = [
            (cheque, amount)
            for cheque, _, amount in rows
            if cheque.cheque_type == "outgoing"
        ]

        return {
            "closing_balance_per_books": statement["closing_balance"],
            "outstanding_deposits_count": len(deposits),
            "outstanding_deposits_amount": float(sum(amount for _, amount in deposits)),
            "outstanding_withdrawals_count": len(withdrawals),
            "outstanding_withdrawals_amount": float(
                sum(amount for _, amount in withdrawals)
            ),
            "outstanding_cheques_in": [cheque for cheque, _ in deposits],
            "outstanding_cheques_out": [cheque for cheque, _ in withdrawals],
        }
