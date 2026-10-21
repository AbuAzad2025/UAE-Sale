"""
General Ledger Service — double-entry posting engine.

Fixes for the 10 audit findings (2026-08-30):

1. reverse_entry: new public facade that covers routes/sales.py:392-398.
2. get_customer_credit_account: merchant customers now map to the
   receivable control account (1130), not to the liability 2115.
3. create_journal_entry: entry_type is now persisted; amount_base is
   calculated with the transaction exchange_rate.
4. Same — amount_base uses (debit - credit) * rate.
5. create_manual_entry: now accepts currency / exchange_rate and
   correctly multiplies amount_base by the rate.
6. post_entry / create_journal_entry block postings to header
   accounts (is_header == True) with a clear ValueError.
7. Direct key access line['debit'] replaced with .get(..., 0) +
   Decimal coercion.
8. post_entry validates the debit == credit invariant BEFORE any
   row is added to the session, so a failure leaves no orphans.
9. get_account_statement / get_accounts_tree return Decimal (quantized
   to 3 decimals) instead of float.
10. All multi-step writes are wrapped in a safe try/except that
    calls db.session.rollback() before re-raising.

P0 — general ledger integrity (2026-10)
--------------------------------------
F1  purge_by_reference refuses to delete a POSTED or REVERSED entry and
    never deletes the JournalEntryAudit rows (the audit trail must
    outlive the entry — models/journal_entry_audit.py).
F3  every posting path (post_entry / create_journal_entry /
    create_manual_entry) writes a JournalEntryAudit row containing the
    account codes and the amounts.
F4  the entry-number sequence is GLOBAL (entry_number is UNIQUE across
    the whole table) — see models.gl.next_global_entry_number.
F5  the balance guard is enforced in the service layer for all three
    posting paths: no negative debit/credit, no line carrying both a
    debit and a credit, no empty line list, and the header totals are
    computed from the SAME quantized values that are written to the lines.
F7  reverse_entry no longer swallows failures; it forwards entry_date and
    created_by to the model primitive (which uses the locked number
    generator and writes an audit row).
F8  the posting direction is validated against the account nature
    (models.gl.GLAccount.check_posting_direction).
F9  is_posted is always set explicitly by the posting paths; a draft can
    be created deliberately (is_posted=False) and posted by
    AdvancedJournalEntryManager.approve_entry.
F10 the fiscal period guard (services/fiscal_period_guard) is enforced on
    every posting path: a closed period, or a date covered by NO period,
    rejects the posting.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any

from extensions import db
from models import GLAccount, GLJournalEntry, GLJournalLine
from models.gl import next_global_entry_number
from models.journal_entry_audit import JournalEntryAudit
from services.account_resolution import AccountResolver, AccountRole
from services.currency_service import CurrencyService
from utils.decorators import get_owned_or_raise
from utils.errors import ValidationError
from utils.helpers import generate_number

_PAYMENT_METHOD_ROLES = {
    "cash": AccountRole.CASH,
    "bank_transfer": AccountRole.BANK,
    "card": AccountRole.BANK,
    "cheque": AccountRole.UNDER_COLLECTION,
}

_THREE_DP = Decimal("0.001")
_TWO_DP = Decimal("0.01")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _to_decimal(value: Any) -> Decimal:
    """Coerce *value* to Decimal without ever going through float."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value).strip() or "0")
    except (InvalidOperation, ValueError, AttributeError):
        return Decimal("0")


def _quantize_3(value: Decimal) -> Decimal:
    return value.quantize(_THREE_DP, rounding=ROUND_HALF_UP)


def _unique_entry_number() -> str:
    """Year-scoped JE-YYYY-NNNN with distributed-lock atomicity.

    F4: ``entry_number`` is UNIQUE across the whole table, therefore the
    sequence MUST be global — a tenant-scoped "max existing + 1" makes two
    tenants compute the same number and the second INSERT dies with an
    IntegrityError. ``next_global_entry_number`` suspends the tenant scope
    for the locked lookup only.
    """
    return next_global_entry_number()


def _current_tenant_id() -> int | None:
    """Tenant id of the currently authenticated user, if any."""
    try:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False):
            return getattr(current_user, "tenant_id", None)
    except Exception:
        pass
    return None


def _current_user_id() -> int | None:
    try:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False):
            return getattr(current_user, "id", None)
    except Exception:
        pass
    return None


def _base_currency() -> str:
    try:
        return CurrencyService.get_base_currency()
    except Exception:
        return "ILS"


def _assert_period_open(entry_date: datetime | None) -> None:
    """F10: يمنع الترحيل إلى فترة مغلقة أو إلى تاريخ بلا فترة مالية.

    الاستدعاء يتم قبل أي كتابة في قاعدة البيانات حتى لا يُترك أثر جزئي.
    """
    from services.fiscal_period_guard import assert_period_open

    assert_period_open(entry_date)


class _NormalizedLine:
    """سطر مُطبَّع: حساب + مبالغ مُكمَّاة (Decimal)."""

    __slots__ = ("account", "debit", "credit", "description", "amount_base")

    def __init__(self, account, debit, credit, description, amount_base):
        self.account = account
        self.debit = debit
        self.credit = credit
        self.description = description
        self.amount_base = amount_base


def _normalize_lines(
    lines: list[dict],
    rate: Decimal,
    *,
    ensure_accounts: bool = True,
    missing_message=None,
    unknown_account_message=None,
) -> tuple[list[_NormalizedLine], Decimal, Decimal]:
    """Resolve, validate and quantize the lines of a journal entry.

    F5: enforces the invariants that used to live (partially) in a single
    path only:

    * an empty line list is rejected (it used to create a POSTED entry
      with zero lines),
    * a negative debit or credit is rejected,
    * a line carrying BOTH a debit and a credit is rejected,
    * the direction of the movement is validated against the account
      nature (F8),
    * the returned totals are computed from the SAME quantized values that
      are written to the lines, so the header can never disagree with the
      lines.

    Returns ``(normalized_lines, total_debit, total_credit)``.
    """
    if not lines:
        raise ValidationError(
            'لا يمكن ترحيل قيد بدون سطور — أضف سطراً واحداً على الأقل.'
        )

    total_debit = Decimal("0")
    total_credit = Decimal("0")
    normalized: list[_NormalizedLine] = []

    for ln in lines:
        raw = ln.get("account") or ln.get("account_code")
        if raw is None:
            raise ValidationError("GL line: missing 'account' / 'account_code'")

        if isinstance(raw, GLAccount):
            account = raw
        else:
            code = str(raw).strip()
            account = GLAccount.query.filter_by(code=code).first()
            if account is None and ensure_accounts:
                GLService.ensure_core_accounts()
                account = GLAccount.query.filter_by(code=code).first()
            if account is None:
                if unknown_account_message is not None:
                    raise ValueError(unknown_account_message(raw))
                raise ValueError(
                    f"GL account '{raw}' not found while posting"
                )

        # FIX 6 — block postings to header accounts
        if getattr(account, "is_header", False):
            raise ValueError(
                f"لا يمكن القيد على الحساب الرئيسي: {account.full_name}"
            )
        if not getattr(account, "is_active", True):
            raise ValueError(f"GL account {account.code} is inactive")

        debit = _quantize_3(_to_decimal(ln.get("debit", 0)))
        credit = _quantize_3(_to_decimal(ln.get("credit", 0)))

        if debit < Decimal("0") or credit < Decimal("0"):
            raise ValueError("GL line: debit/credit must be >= 0")
        if debit > Decimal("0") and credit > Decimal("0"):
            raise ValueError(
                "GL line: a line cannot carry both a debit and a credit"
            )

        # F8 — اتجاه الحركة مقابل طبيعة الحساب
        account.check_posting_direction(debit, credit)

        amount_base = _quantize_3((debit - credit) * rate)
        total_debit += debit
        total_credit += credit
        normalized.append(
            _NormalizedLine(
                account=account,
                debit=debit,
                credit=credit,
                description=ln.get("description"),
                amount_base=amount_base,
            )
        )

    return normalized, total_debit, total_credit


def _audit_payload(entry: GLJournalEntry, normalized: list[_NormalizedLine]) -> dict:
    """F3: حمولة التدقيق — رأس القيد + أكواد الحسابات والمبالغ."""
    return JournalEntryAudit.entry_payload(
        entry,
        lines=[
            {
                'account_code': item.account.code,
                'debit': item.debit,
                'credit': item.credit,
                'amount_base': item.amount_base,
                'description': item.description,
            }
            for item in normalized
        ],
    )


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------

class GLService:
    # ------------------------------------------------------------------
    # chart of accounts seeding
    # ------------------------------------------------------------------

    @staticmethod
    def ensure_core_accounts() -> None:
        """Create hierarchical core GL accounts (idempotent)."""
        core: list[tuple] = [
            ("1000", "الأصول", "Assets", "asset", None, True, 0),
            ("1100", "الأصول المتداولة", "Current Assets", "asset", "1000", True, 1),
            ("1110", "الصندوق", "Cash", "asset", "1100", False, 2),
            ("1120", "البنك - حساب جاري", "Bank - Current Account", "asset", "1100", False, 2),
            ("1121", "البنك - حساب توفير", "Bank - Savings Account", "asset", "1100", False, 2),
            ("1130", "الذمم المدينة", "Accounts Receivable", "asset", "1100", False, 2),
            ("1140", "المخزون", "Inventory", "asset", "1100", False, 2),
            ("1150", "شيكات تحت التحصيل", "Cheques Under Collection", "asset", "1100", False, 2),
            ("1200", "الأصول الثابتة", "Fixed Assets", "asset", "1000", True, 1),
            ("1210", "أراضي", "Land", "asset", "1200", False, 2),
            ("1220", "مباني", "Buildings", "asset", "1200", False, 2),
            ("1230", "سيارات", "Vehicles", "asset", "1200", False, 2),
            ("1240", "معدات", "Equipment", "asset", "1200", False, 2),
            ("1250", "أثاث", "Furniture", "asset", "1200", False, 2),
            ("2000", "الخصوم", "Liabilities", "liability", None, True, 0),
            ("2100", "الخصوم المتداولة", "Current Liabilities", "liability", "2000", True, 1),
            ("2110", "الذمم الدائنة", "Accounts Payable", "liability", "2100", False, 2),
            ("2115", "ذمم التجار", "Merchants Payable", "liability", "2100", False, 2),
            ("2120", "شيكات مؤجلة الدفع", "Deferred Cheques Payable", "liability", "2100", False, 2),
            ("2130", "ضرائب مستحقة", "Taxes Payable", "liability", "2100", False, 2),
            ("2140", "رواتب مستحقة", "Salaries Payable", "liability", "2100", False, 2),
            ("2200", "الخصوم طويلة الأجل", "Long-term Liabilities", "liability", "2000", True, 1),
            ("2210", "قروض", "Loans", "liability", "2200", False, 2),
            ("3000", "حقوق الملكية", "Equity", "equity", None, True, 0),
            ("3100", "رأس المال", "Capital", "equity", "3000", False, 1),
            ("3200", "الأرباح المحتجزة", "Retained Earnings", "equity", "3000", False, 1),
            ("3300", "جاري المالك", "Owner Draw", "equity", "3000", False, 1),
            ("3350", "جاري الشركاء", "Partners Current Account", "equity", "3000", False, 1),
            ("3400", "أرباح السنة الحالية", "Current Year Profit", "equity", "3000", False, 1),
            ("4000", "الإيرادات", "Revenues", "revenue", None, True, 0),
            ("4100", "إيرادات المبيعات", "Sales Revenue", "revenue", "4000", False, 1),
            ("4200", "إيرادات الخدمات", "Service Revenue", "revenue", "4000", False, 1),
            ("4300", "إيرادات الشحن", "Shipping Revenue", "revenue", "4000", False, 1),
            ("4400", "أرباح فرق العملة", "Foreign Exchange Gain", "revenue", "4000", False, 1),
            ("4500", "إيرادات أخرى", "Other Revenue", "revenue", "4000", False, 1),
            ("5000", "تكلفة المبيعات", "Cost of Sales", "expense", None, True, 0),
            ("5100", "تكلفة البضاعة المباعة", "Cost of Goods Sold", "expense", "5000", False, 1),
            ("5150", "تعديلات المخزون", "Inventory Adjustments", "expense", "5000", False, 1),
            ("5200", "الخصومات الممنوحة", "Discounts Given", "expense", "5000", False, 1),
            ("5300", "مصروفات الشحن", "Shipping Expense", "expense", "5000", False, 1),
            ("6000", "المصروفات التشغيلية", "Operating Expenses", "expense", None, True, 0),
            ("6100", "رواتب وأجور", "Salaries & Wages", "expense", "6000", False, 1),
            ("6200", "إيجار", "Rent", "expense", "6000", False, 1),
            ("6300", "كهرباء وماء", "Utilities", "expense", "6000", False, 1),
            ("6400", "صيانة", "Maintenance", "expense", "6000", False, 1),
            ("6500", "تسويق وإعلان", "Marketing & Advertising", "expense", "6000", False, 1),
            ("6600", "مواصلات", "Transportation", "expense", "6000", False, 1),
            ("6700", "اتصالات", "Communications", "expense", "6000", False, 1),
            ("6800", "قرطاسية", "Stationery", "expense", "6000", False, 1),
            ("6900", "خسائر فرق العملة", "Foreign Exchange Loss", "expense", "6000", False, 1),
            ("6950", "مصروفات بنكية", "Bank Charges", "expense", "6000", False, 1),
            ("6990", "مصروفات متنوعة", "Miscellaneous Expenses", "expense", "6000", False, 1),
        ]
        created_any = False
        cache: dict[str, GLAccount] = {}
        for code, name_ar, name_en, acc_type, parent_code, is_header, level in core:
            acc = GLAccount.query.filter_by(code=code).first()
            if acc:
                cache[code] = acc
                continue
            parent_id = None
            if parent_code:
                parent = cache.get(parent_code) or GLAccount.query.filter_by(code=parent_code).first()
                if parent:
                    parent_id = parent.id
            acc = GLAccount(
                code=code,
                name=name_en,
                name_ar=name_ar,
                type=acc_type,
                parent_id=parent_id,
                is_header=is_header,
                level=level,
                currency=_base_currency(),
                is_system=True,   # F8 — حساب مُبذَر: لا يُعدَّل كوده/نوعه ولا يُحذف
            )
            db.session.add(acc)
            db.session.flush()
            cache[code] = acc
            created_any = True
        if created_any:
            db.session.flush()

    # ------------------------------------------------------------------
    # purge helper (FK-safe)
    # ------------------------------------------------------------------

    @staticmethod
    def purge_by_reference(ref_type: str, ref_id: int) -> int:
        """Delete the DRAFT journal entries for a given business reference.

        F1: this helper used to delete POSTED entries AND their audit rows,
        which destroyed the ledger history and the audit trail.

        * A POSTED or REVERSED entry is NEVER deleted — it must be reversed
          (a reversing entry keeps the audit trail intact). A clear error
          is raised so the caller can reverse instead of purge.
        * The ``JournalEntryAudit`` rows are NEVER deleted: the audit trail
          must outlive the entry it documents (models/journal_entry_audit.py,
          migration 17_audit_trail_survives.py).

        Returns the number of entries removed.
        """
        entries = GLJournalEntry.query.filter_by(
            reference_type=ref_type, reference_id=ref_id
        ).all()
        if not entries:
            return 0

        protected = [
            e for e in entries
            if getattr(e, 'is_posted', False) or getattr(e, 'is_reversed', False)
        ]
        if protected:
            numbers = ', '.join(sorted(str(e.entry_number) for e in protected))
            raise ValidationError(
                f'لا يمكن حذف قيود مرحّلة ({numbers}). '
                'القيد المرحّل لا يُحذف أبداً — استخدم القيد العكسي (Reverse) '
                'للإلغاء، فيبقى الأثر المحاسبي وسجل التدقيق كما هما.'
            )

        ids = [e.id for e in entries]
        # NOTE: JournalEntryAudit rows are deliberately NOT deleted.
        # synchronize_session='fetch' يبقي الجلسة متسقة مع قاعدة البيانات
        # (الكائنات المحذوفة تُزال من cache الهوية).
        GLJournalLine.query.filter(
            GLJournalLine.entry_id.in_(ids)
        ).delete(synchronize_session='fetch')
        count = GLJournalEntry.query.filter(
            GLJournalEntry.id.in_(ids)
        ).delete(synchronize_session='fetch')
        return count

    # ------------------------------------------------------------------
    # account resolvers
    # ------------------------------------------------------------------

    @staticmethod
    def get_payment_debit_account(method: str | None) -> str:
        m = (method or "").strip()
        role = _PAYMENT_METHOD_ROLES.get(m, AccountRole.CASH)
        return AccountResolver.resolve(role)

    @staticmethod
    def get_customer_credit_account(customer: Any) -> str:
        """Return the receivable account code for *customer*.

        FIX 2: merchant customers previously mapped to ``MERCHANTS_PAYABLE``
        (liability 2115).  A sale to a merchant still creates a *receivable*
        asset — the merchant *owes* us money — so merchant sales must post
        to the receivable control account (1130) just like any other
        customer.  Dedicated merchant sub-ledgers can be introduced later
        without changing the control account mapping.
        """
        ctype = getattr(customer, "customer_type", None)
        if ctype == "partner":
            return AccountResolver.resolve(AccountRole.PARTNERS_CURRENT)
        # FIX 2 — merchant and every other type resolve to AR control.
        return AccountResolver.resolve(AccountRole.AR_CONTROL)

    # ------------------------------------------------------------------
    # PRIMARY POSTING ENGINE — post_entry (FIX 8)
    # ------------------------------------------------------------------

    @staticmethod
    def post_entry(
        lines: list[dict],
        description: str = "",
        reference_type: str | None = None,
        reference_id: int | None = None,
        currency: str | None = None,
        exchange_rate: Any = 1,
        entry_type: str = "auto",
        entry_date: datetime | None = None,
        notes: str | None = None,
        created_by: int | None = None,
        is_posted: bool = True,
    ) -> GLJournalEntry:
        """Post a balanced double-entry journal.

        Args:
            lines: Each element is ``{'account': code|GLAccount,
                                       'debit': Decimal|str|float,
                                       'credit': Decimal|str|float,
                                       'description': str (optional)}``.
            description: Entry narration.
            reference_type / reference_id: Link to the business document.
            currency / exchange_rate: FX metadata for the entry.
            entry_type: ``auto`` / ``manual`` / ``reversing`` / ``closing``.
            entry_date: تاريخ المستند — يجب أن يقع في فترة مالية مفتوحة (F10).
            is_posted: F9 — True (ترحيل فوري) أو False (مسودة تُرحَّل لاحقاً).
        """
        currency = currency or _base_currency()
        rate = _to_decimal(exchange_rate) or Decimal("1")
        effective_date = entry_date or datetime.now(timezone.utc)

        try:
            # ---- 8. BALANCE VALIDATION BEFORE ANY DB MUTATION --------
            # F5: التطبيع والتحقق يحدثان قبل أي كتابة في الجلسة.
            normalized, total_debit, total_credit = _normalize_lines(
                lines,
                rate,
                ensure_accounts=True,
                unknown_account_message=lambda raw: (
                    f"GL account '{raw}' not found while posting '{description}'"
                ),
            )
            if total_debit != total_credit:
                raise ValueError(
                    f"GL entry not balanced: debit={total_debit} credit={total_credit}"
                )

            # ---- F10: الفترة المالية ---------------------------------
            _assert_period_open(effective_date)

            entry_number = _unique_entry_number()

            entry = GLJournalEntry(
                entry_number=entry_number,
                entry_date=effective_date,
                description=description,
                reference_type=reference_type,
                reference_id=reference_id,
                entry_type=entry_type,
                currency=currency,
                exchange_rate=rate,
                total_debit=total_debit,
                total_credit=total_credit,
                is_posted=bool(is_posted),
                notes=notes,
                created_by=created_by if created_by is not None else _current_user_id(),
                tenant_id=_current_tenant_id(),
            )
            db.session.add(entry)
            db.session.flush()

            for item in normalized:
                db.session.add(
                    GLJournalLine(
                        entry=entry,
                        account=item.account,
                        description=item.description or description,
                        debit=item.debit,
                        credit=item.credit,
                        amount_base=item.amount_base,
                    )
                )
            db.session.flush()

            # ---- F3: سجل التدقيق ---------------------------------------
            JournalEntryAudit.record(
                journal_entry_id=entry.id,
                action=JournalEntryAudit.ACTION_CREATE,
                old_values=None,
                new_values=_audit_payload(entry, normalized),
                reason=f'ترحيل قيد: {description or entry_number}',
                performed_by=created_by,
                fallback_entry=entry,
            )
            db.session.flush()
            return entry
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------------
    # create_journal_entry — typed, easiest caller (FIX 3/4/6/7/8)
    # ------------------------------------------------------------------

    @staticmethod
    def create_journal_entry(
        entry_type: str,
        description: str,
        lines: list[dict],
        reference_type: str | None = None,
        reference_id: int | None = None,
        currency: str | None = None,
        exchange_rate: Any = 1,
        entry_date: datetime | None = None,
        notes: str | None = None,
        created_by: int | None = None,
        is_posted: bool = True,
    ) -> GLJournalEntry:
        """Create a typed journal entry.

        Args:
            entry_type: Type of entry (sale, purchase, payment, etc.)
            description: Entry narration.
            lines: ``[{'account_code': str, 'debit': Decimal, 'credit': Decimal}]``.
            reference_type / reference_id: Link to the business document.
            currency / exchange_rate: FX metadata (defaults to base).
            is_posted: F9 — True (ترحيل فوري) أو False (مسودة).
        """
        currency = currency or _base_currency()
        rate = _to_decimal(exchange_rate) or Decimal("1")
        effective_date = entry_date or datetime.now(timezone.utc)

        GLService.ensure_core_accounts()

        try:
            # FIX 7 — use .get() so a missing 'debit' doesn't raise KeyError.
            # F5 — التطبيع والتحقق قبل أي كتابة.
            normalized, total_debit, total_credit = _normalize_lines(
                lines,
                rate,
                ensure_accounts=False,
                unknown_account_message=lambda raw: f"Account {raw} not found",
            )
            if total_debit != total_credit:
                raise ValueError(
                    f"Journal entry is not balanced: Debit={total_debit}, Credit={total_credit}"
                )

            # F10 — الفترة المالية
            _assert_period_open(effective_date)

            entry_number = _unique_entry_number()

            entry = GLJournalEntry(
                entry_number=entry_number,
                description=description,
                entry_type=entry_type,  # FIX 3
                reference_type=reference_type,
                reference_id=reference_id,
                currency=currency,
                exchange_rate=rate,
                entry_date=effective_date,
                notes=notes,
                total_debit=total_debit,
                total_credit=total_credit,
                is_posted=bool(is_posted),
                created_by=created_by if created_by is not None else _current_user_id(),
                tenant_id=_current_tenant_id(),
            )
            db.session.add(entry)
            db.session.flush()

            for item in normalized:
                db.session.add(
                    GLJournalLine(
                        entry_id=entry.id,
                        account_id=item.account.id,
                        debit=item.debit,
                        credit=item.credit,
                        amount_base=item.amount_base,
                        description=item.description or description,
                    )
                )
            db.session.flush()

            # F3 — سجل التدقيق
            JournalEntryAudit.record(
                journal_entry_id=entry.id,
                action=JournalEntryAudit.ACTION_CREATE,
                old_values=None,
                new_values=_audit_payload(entry, normalized),
                reason=f'إنشاء قيد: {description or entry_number}',
                performed_by=created_by,
                fallback_entry=entry,
            )
            db.session.flush()
            return entry
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------------
    # create_manual_entry (FIX 5)
    # ------------------------------------------------------------------

    @staticmethod
    def create_manual_entry(
        description: str,
        lines: list[dict],
        entry_date: datetime | None = None,
        notes: str | None = None,
        created_by: int | None = None,
        reference_type: str | None = None,
        reference_id: int | None = None,
        currency: str | None = None,
        exchange_rate: Any = 1,
        entry_type: str = "manual",
        is_posted: bool = True,
    ) -> GLJournalEntry:
        """Manual entry with full FX support (FIX 5)."""
        from flask_login import current_user

        currency = currency or _base_currency()
        rate = _to_decimal(exchange_rate) or Decimal("1")
        effective_date = entry_date or datetime.now(timezone.utc)

        try:
            # F5 — التطبيع والتحقق قبل أي كتابة؛ الإجماليات من نفس القيم.
            normalized, total_debit, total_credit = _normalize_lines(
                lines,
                rate,
                ensure_accounts=True,
                unknown_account_message=lambda raw: f"الحساب {raw} غير موجود",
            )
            if total_debit != total_credit:
                raise ValueError(
                    f"القيد غير متوازن: مدين={total_debit}, دائن={total_credit}"
                )

            # F10 — الفترة المالية
            _assert_period_open(effective_date)

            entry_number = _unique_entry_number()

            entry = GLJournalEntry(
                entry_number=entry_number,
                entry_date=effective_date,
                description=description,
                entry_type=entry_type,
                notes=notes,
                reference_type=reference_type,
                reference_id=reference_id,
                currency=currency,
                exchange_rate=rate,
                total_debit=total_debit,
                total_credit=total_credit,
                is_posted=bool(is_posted),
                created_by=created_by
                if created_by is not None
                else (current_user.id if getattr(current_user, "is_authenticated", False) else None),
                tenant_id=_current_tenant_id(),
            )
            db.session.add(entry)
            db.session.flush()

            for item in normalized:
                db.session.add(
                    GLJournalLine(
                        entry_id=entry.id,
                        account_id=item.account.id,
                        description=item.description or "",
                        debit=item.debit,
                        credit=item.credit,
                        amount_base=item.amount_base,
                    )
                )
            db.session.flush()

            # F3 — سجل التدقيق
            JournalEntryAudit.record(
                journal_entry_id=entry.id,
                action=JournalEntryAudit.ACTION_CREATE,
                old_values=None,
                new_values=_audit_payload(entry, normalized),
                reason=f"إنشاء قيد جديد: {description or entry_number}",
                performed_by=created_by,
                fallback_entry=entry,
            )
            db.session.flush()
            return entry
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------------
    # reverse_entry (FIX 1)
    # ------------------------------------------------------------------

    @staticmethod
    def reverse_entry(
        entry_or_id: int | GLJournalEntry | None = None,
        description: str | None = None,
        entry_date: datetime | None = None,
        created_by: int | None = None,
        reference_type: str | None = None,
        reference_id: int | None = None,
        **kwargs: Any,
    ) -> GLJournalEntry | list[GLJournalEntry]:
        """Create reversing entry/entries.

        Supports all calling conventions in the codebase:

        - ``GLService.reverse_entry(entry_id)`` — reverse a single entry
          by primary key.
        - ``GLService.reverse_entry(entry_instance)`` — reverse an
          instance.
        - ``GLService.reverse_entry(reference_type='Sale',
          reference_id=sale.id)`` — as used in ``routes/sales.py``
          when archiving a sale: reverses *every* entry linked to that
          business reference and returns the list of reversing entries.
          If no entries are found for the reference, an empty list is
          returned (no-op).

        F7: the failures are NO LONGER swallowed — a caller that archives a
        document must never believe the ledger was reversed when it was
        not. ``entry_date`` and ``created_by`` are forwarded to the model
        primitive (which uses the locked number generator and writes an
        audit row).
        """
        # reference_type / reference_id form used by routes/sales.py
        # when the caller does not have the entry id handy.
        ref_type = kwargs.get("reference_type", reference_type)
        ref_id = kwargs.get("reference_id", reference_id)
        if ref_type is not None and ref_id is not None:
            entries = GLJournalEntry.query.filter_by(
                reference_type=ref_type, reference_id=ref_id
            ).all()
            if not entries:
                return []
            reversed_entries: list[GLJournalEntry] = []
            for ent in entries:
                if getattr(ent, "is_reversed", False):
                    continue
                # F7 — no silent swallow: a failure must reach the caller.
                rev = ent.reverse_entry(
                    description=description or f"Reversal of {ent.entry_number}",
                    entry_date=entry_date,
                    created_by=created_by,
                )
                reversed_entries.append(rev)
            # Return a single entry when only one was reversed to keep
            # the simple caller (routes/sales.py line 392) happy which
            # discards the return value; return the list so batch
            # callers can iterate.
            if len(reversed_entries) == 1:
                return reversed_entries[0]
            return reversed_entries  # type: ignore[return-value]

        # single-entry form
        if entry_or_id is None:
            raise TypeError("GLService.reverse_entry: first argument or reference_type+reference_id is required")
        if isinstance(entry_or_id, int):
            entry = get_owned_or_raise(GLJournalEntry, entry_or_id,
                                       missing_message=f"GL entry id={entry_or_id} not found")
            if entry is None:
                raise ValueError(f"GL entry id={entry_or_id} not found")
        else:
            entry = entry_or_id
        if not isinstance(entry, GLJournalEntry):
            raise TypeError("GLService.reverse_entry: first argument must be an id or GLJournalEntry")
        return entry.reverse_entry(
            description=description,
            entry_date=entry_date,
            created_by=created_by,
        )

    # optional: explicit alias used by older code
    reverse_journal_entry = reverse_entry

    # ------------------------------------------------------------------
    # reporting (FIX 9)
    # ------------------------------------------------------------------

    @staticmethod
    def get_account_statement(
        account_id: int,
        date_from: Any | None = None,
        date_to: Any | None = None,
    ) -> dict:
        """Detailed account statement with Decimal balances (FIX 9)."""
        from sqlalchemy import func

        account = db.get_or_404(GLAccount, account_id)
        query = GLJournalLine.query.filter_by(account_id=account_id).join(GLJournalEntry)
        if date_from:
            query = query.filter(func.date(GLJournalEntry.entry_date) >= date_from)
        if date_to:
            query = query.filter(func.date(GLJournalEntry.entry_date) <= date_to)
        lines = query.order_by(GLJournalEntry.entry_date).all()

        opening_debit_q = (
            db.session.query(func.sum(GLJournalLine.debit))
            .filter(GLJournalLine.account_id == account_id)
            .join(GLJournalEntry)
        )
        opening_credit_q = (
            db.session.query(func.sum(GLJournalLine.credit))
            .filter(GLJournalLine.account_id == account_id)
            .join(GLJournalEntry)
        )
        if date_from:
            opening_debit_q = opening_debit_q.filter(func.date(GLJournalEntry.entry_date) < date_from)
            opening_credit_q = opening_credit_q.filter(func.date(GLJournalEntry.entry_date) < date_from)
        else:
            opening_debit_q = opening_debit_q.filter(db.false())
            opening_credit_q = opening_credit_q.filter(db.false())
        opening_debit = _to_decimal(opening_debit_q.scalar())
        opening_credit = _to_decimal(opening_credit_q.scalar())
        opening_balance = (
            opening_debit - opening_credit
            if account.type in ("asset", "expense")
            else opening_credit - opening_debit
        )
        running = opening_balance
        txns: list[dict] = []
        total_debit = Decimal("0")
        total_credit = Decimal("0")
        for ln in lines:
            if account.type in ("asset", "expense"):
                running += (ln.debit or Decimal("0")) - (ln.credit or Decimal("0"))
            else:
                running += (ln.credit or Decimal("0")) - (ln.debit or Decimal("0"))
            total_debit += ln.debit or Decimal("0")
            total_credit += ln.credit or Decimal("0")
            txns.append(
                {
                    "date": ln.entry.entry_date,
                    "entry_number": ln.entry.entry_number,
                    "entry_type": ln.entry.entry_type_ar,
                    "description": ln.description or ln.entry.description,
                    "reference": f"{ln.entry.reference_type} #{ln.entry.reference_id}"
                    if ln.entry.reference_type
                    else "",
                    # FIX 9
                    "debit": _quantize_3(_to_decimal(ln.debit)),
                    "credit": _quantize_3(_to_decimal(ln.credit)),
                    "balance": _quantize_3(running),
                }
            )
        return {
            "account": account,
            "opening_balance": _quantize_3(opening_balance),
            "transactions": txns,
            "closing_balance": _quantize_3(running),
            "total_debit": _quantize_3(total_debit),
            "total_credit": _quantize_3(total_credit),
        }

    @staticmethod
    def get_accounts_tree() -> list[dict]:
        """Chart-of-accounts tree with Decimal balances and cycle safety."""
        roots = (
            GLAccount.query.filter_by(parent_id=None, is_active=True)
            .order_by(GLAccount.code)
            .all()
        )

        def build(node: GLAccount, seen: set[int]) -> dict:
            bal = node.get_aggregate_balance()
            # FIX 9 — Decimal, not float
            if not isinstance(bal, Decimal):
                bal = _quantize_3(_to_decimal(bal))
            kids = [
                build(c, seen | {node.id})
                for c in sorted(node.children, key=lambda x: x.code)
                if c.id not in seen and c.is_active
            ]
            return {
                "id": node.id,
                "code": node.code,
                "name": node.name,
                "name_ar": node.name_ar,
                "type": node.type,
                "type_ar": node.type_ar,
                "is_header": node.is_header,
                "level": node.level,
                "balance": bal,
                "children": kids,
            }

        return [build(r, set()) for r in roots]
