from decimal import Decimal

from extensions import db
from models.cheque import Cheque
from models.gl import GLJournalEntry, GLJournalLine
from utils.decorators import get_owned_or_404


class ChequeAccountingIntegration:
    """تكامل الشيكات مع النظام المحاسبي

    حالة الشيك تتبع قيم النموذج الصالحة فقط (C3): بعد الاستلام/الإصدار تصبح
    الحالة 'deposited' (تحت البنك) — لا حالات مُختلقة مثل 'received'/'issued'.
    """

    CHEQUE_ROLES = {
        "incoming_under_collection": "UNDER_COLLECTION",
        "outgoing_deferred": "DEFERRED_CHEQUES_PAYABLE",
        "bank_account": "BANK",
        "cash_account": "CASH",
        "accounts_receivable": "AR_CONTROL",
        "accounts_payable": "AP_CONTROL",
        "bank_charges": "BANK_CHARGES",
        "exchange_gain": "FX_GAIN",
        "exchange_loss": "FX_LOSS",
    }

    @classmethod
    def cheque_accounts(cls, tenant_id=None):
        from services.account_resolution import AccountResolver

        return {
            key: AccountResolver.resolve(role, tenant_id=tenant_id)
            for key, role in cls.CHEQUE_ROLES.items()
        }

    class _Accounts:
        """Tenant-aware view of the cheque account codes.

        Keeps the historic ``CHEQUE_ACCOUNTS['...']`` call shape working
        while resolving through the role map, so a tenant that remapped an
        account is followed instead of the hardcoded default.
        """

        def __getitem__(self, key):
            return ChequeAccountingIntegration.cheque_accounts()[key]

        def get(self, key, default=None):
            return ChequeAccountingIntegration.cheque_accounts().get(key, default)

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
        if cheque.amount_base in (None, Decimal("0")) and cheque.amount:
            cheque.calculate_amount_base()
            db.session.flush()
        return cheque.amount_base or Decimal("0")

    @staticmethod
    def _locked_cheque(cheque_id):
        cheque = get_owned_or_404(Cheque, cheque_id)
        db.session.refresh(cheque, with_for_update=True)
        return cheque

    @staticmethod
    def _original_entry(cheque):
        if not cheque.gl_journal_entry_id:
            raise ValueError("The cheque has no posted issuance or receipt journal.")
        entry = db.session.get(GLJournalEntry, cheque.gl_journal_entry_id)
        if (
            not entry
            or entry.tenant_id != cheque.tenant_id
            or not entry.is_posted
            or entry.is_reversed
        ):
            raise ValueError(
                "The cheque journal is not a valid posted entry for this tenant."
            )
        expected = (
            "cheque_receive" if cheque.cheque_type == "incoming" else "cheque_issue"
        )
        if (entry.reference_type, entry.reference_id) == (expected, cheque.id):
            return entry
        from models import Payment, Receipt

        document_model = {"Payment": Payment, "Receipt": Receipt}.get(
            entry.reference_type
        )
        source = (
            db.session.get(document_model, entry.reference_id)
            if document_model and entry.reference_id
            else None
        )
        if (
            source is None
            or source.tenant_id != cheque.tenant_id
            or source.cheque_id != cheque.id
        ):
            raise ValueError(
                "The journal does not belong to the cheque or its voucher."
            )
        return entry

    @classmethod
    def receive_cheque(cls, cheque_id, received_by=None):
        cheque = cls._locked_cheque(cheque_id)
        if cheque.cheque_type != "incoming" or cheque.status != "pending":
            raise ValueError("The cheque is not a pending incoming cheque.")
        cls._ensure_amount_base(cheque)
        cheque.receive_cheque(actor_id=received_by)
        entry = cls._original_entry(cheque)
        cheque.deposit_cheque()
        db.session.flush()
        return entry

    @classmethod
    def issue_cheque(cls, cheque_id, issued_by=None):
        cheque = cls._locked_cheque(cheque_id)
        if cheque.cheque_type != "outgoing" or cheque.status != "pending":
            raise ValueError("The cheque is not a pending outgoing cheque.")
        cls._ensure_amount_base(cheque)
        cheque.issue_cheque(actor_id=issued_by)
        entry = cls._original_entry(cheque)
        cheque.deposit_cheque()
        db.session.flush()
        return entry

    @classmethod
    def clear_cheque(
        cls, cheque_id, cleared_by=None, bank_charges=0, exchange_gain_loss=0
    ):
        from services.currency_service import CurrencyService

        cheque = cls._locked_cheque(cheque_id)
        if cheque.status != "deposited" or cheque.gl_clearing_entry_id:
            raise ValueError("The cheque must be deposited and uncleared.")
        cls._original_entry(cheque)
        gain = Decimal(str(exchange_gain_loss))
        if not gain.is_finite():
            raise ValueError("Invalid cheque exchange adjustment.")
        rate = None
        if gain:
            if cheque.currency == CurrencyService.get_base_currency():
                raise ValueError(
                    "A base-currency cheque cannot have an exchange adjustment."
                )
            book = cls._ensure_amount_base(cheque)
            actual = book + gain if cheque.cheque_type == "incoming" else book - gain
            rate = actual / Decimal(str(cheque.amount))
        cheque.clear_cheque(
            clearance_exchange_rate=rate, actor_id=cleared_by, bank_charges=bank_charges
        )
        db.session.flush()
        return db.session.get(GLJournalEntry, cheque.gl_clearing_entry_id)

    @classmethod
    def bounce_cheque(cls, cheque_id, bounced_by=None, bounce_reason=None):
        cheque = cls._locked_cheque(cheque_id)
        cls._original_entry(cheque)
        cheque.bounce_cheque(bounce_reason or "Cheque returned", actor_id=bounced_by)
        db.session.flush()
        return db.session.get(GLJournalEntry, cheque.gl_bounce_entry_id)

    @staticmethod
    def get_cheque_accounting_summary(cheque_id):  # noqa: C901
        """الحصول على ملخص محاسبي للشيك"""
        cheque = get_owned_or_404(Cheque, cheque_id)

        summary = {
            "cheque_info": {
                "id": cheque.id,
                "number": cheque.cheque_bank_number,
                "type": cheque.type_ar,
                "amount": float(cheque.amount_base),
                "status": cheque.status_ar,
                "date": cheque.due_date.isoformat() if cheque.due_date else None,
            },
            "journal_entries": [],
            "account_impact": [],
        }

        accounts = {}
        cheque_entry_ids = set()
        for kind, entry_id in (
            (
                "receive" if cheque.cheque_type == "incoming" else "issue",
                cheque.gl_journal_entry_id,
            ),
            ("clear", cheque.gl_clearing_entry_id),
            ("bounce", cheque.gl_bounce_entry_id),
        ):
            if entry_id is None:
                continue
            entry = GLJournalEntry.query.filter_by(
                id=entry_id, tenant_id=cheque.tenant_id
            ).one()
            cheque_entry_ids.add(entry.id)
            summary["journal_entries"].append(
                {
                    "type": kind,
                    "entry_number": entry.entry_number,
                    "date": entry.entry_date.isoformat(),
                    "description": entry.description,
                }
            )
            for line in entry.lines:
                accounts[line.account_id] = line.account

        # Account impact must describe THIS cheque only — summing every posted
        # line on the account (the old behaviour) reported unrelated vouchers
        # as if they belonged to the cheque.
        for account in sorted(accounts.values(), key=lambda account: account.code):
            balance = (
                db.session.query(db.func.sum(GLJournalLine.amount_base))
                .join(GLJournalEntry, GLJournalLine.entry_id == GLJournalEntry.id)
                .filter(
                    GLJournalEntry.id.in_(cheque_entry_ids),
                    GLJournalEntry.tenant_id == cheque.tenant_id,
                    GLJournalEntry.is_posted.is_(True),
                    GLJournalLine.account_id == account.id,
                )
                .scalar()
                or 0
            )
            summary["account_impact"].append(
                {
                    "code": account.code,
                    "name": account.full_name,
                    "balance": float(balance if account.is_debit_nature else -balance),
                }
            )

        return summary
