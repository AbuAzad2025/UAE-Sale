"""P0 — اختبارات سلامة دفتر الأستاذ العام (General Ledger Integrity).

تغطي هذه الملف الإصلاحات F1..F11 التي تخص دفتر الأستاذ:

* F1  ``purge_by_reference`` يرفض حذف قيد مرحّل، وسجلات التدقيق تنجو.
* F2  عكس القيد: رقم مقفل، ربط في الاتجاهين، سجل تدقيق، إجماليات من السطور.
* F3  القيود المرحَّلة آلياً تكتب سجل تدقيق (أكواد الحسابات + المبالغ).
* F4  تسلسل أرقام القيود عام: مستأجران يحصلان على رقمين مختلفين.
* F5  الحاجز في طبقة الخدمات: لا قيم سالبة، لا سطر بمدين ودائن، لا سطور.
* F8  نوع الحساب مُتحقَّق منه، والحسابات المُبذَرة مُقفلة، واتجاه الحركة.
* F9  القيد المرحّل غير قابل للتعديل عبر ORM.
* F10 الفترة المالية: الفترة المغلقة والتاريخ بلا فترة يُرفضان.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from extensions import db as _db
from models import GLAccount, GLJournalEntry
from models.journal_entry_audit import JournalEntryAudit
from services.gl_service import GLService
from utils.errors import ValidationError

BALANCED = [
    {'account': '1110', 'debit': Decimal('100'), 'credit': Decimal('0')},
    {'account': '1130', 'debit': Decimal('0'), 'credit': Decimal('100')},
]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def core_accounts(db):
    """دليل الحسابات الأساسي (مع commit حتى لا يضيع مع أي rollback)."""
    GLService.ensure_core_accounts()
    _db.session.commit()
    return True


@pytest.fixture
def open_period(db):
    """فترة مالية سنوية مفتوحة تغطي السنة الحالية."""
    from models.erp_modules import FiscalPeriod

    year = date.today().year
    fp = FiscalPeriod(
        name=f'SFY {year}',
        year=year,
        period_type='annual',
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_closed=False,
    )
    _db.session.add(fp)
    _db.session.commit()
    return fp


@pytest.fixture
def two_tenants(db):
    """مستأجران لاختبار العزل والتسلسل العام."""
    from models import Tenant

    t1 = Tenant(name='GL T1', name_ar='GL T1', slug='gl-p0-t1', country='UAE', is_active=True)
    t2 = Tenant(name='GL T2', name_ar='GL T2', slug='gl-p0-t2', country='UAE', is_active=True)
    _db.session.add_all([t1, t2])
    _db.session.commit()
    return t1, t2


@pytest.fixture
def tenant_scope():
    """مساعد لتبديل نطاق المستأجر داخل الاختبار."""
    from models.tenant_scope import set_current_tenant_id, clear_current_tenant_id

    class _Scope:
        @staticmethod
        def use(tenant_id):
            set_current_tenant_id(tenant_id)

        @staticmethod
        def clear():
            clear_current_tenant_id()

    yield _Scope
    clear_current_tenant_id()


def _post(**kwargs):
    """ترحيل قيد متوازن عبر GLService (مسار طبقة الخدمات)."""
    params = dict(lines=list(BALANCED), description='قيد اختبار')
    params.update(kwargs)
    return GLService.post_entry(**params)


# ---------------------------------------------------------------------------
# F1 — purge_by_reference
# ---------------------------------------------------------------------------

class TestPurgeByReference:
    def test_refuses_posted_entry_and_keeps_audit_rows(self, db, core_accounts,
                                                         open_period, owner_user):
        entry = _post(reference_type='Sale', reference_id=77, created_by=owner_user.id)
        db.session.commit()

        audits_before = JournalEntryAudit.query.filter_by(
            journal_entry_id=entry.id
        ).count()
        assert audits_before >= 1, 'F3: القيد المرحّل يجب أن يكتب سجل تدقيق'

        with pytest.raises(ValueError):
            GLService.purge_by_reference('Sale', 77)

        db.session.rollback()
        assert GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=77
        ).count() == 1, 'F1: القيد المرحّل لا يجوز حذفه'
        assert JournalEntryAudit.query.filter_by(
            journal_entry_id=entry.id
        ).count() == audits_before, 'F1: سجلات التدقيق لا تُحذف أبداً'

    def test_refuses_reversed_entry(self, db, core_accounts, open_period, owner_user):
        entry = _post(reference_type='Sale', reference_id=78, created_by=owner_user.id)
        db.session.commit()
        entry.reverse_entry(description='عكس', created_by=owner_user.id)
        db.session.commit()

        with pytest.raises(ValueError):
            GLService.purge_by_reference('Sale', 78)
        db.session.rollback()
        assert GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=78
        ).count() == 2

    def test_draft_purge_keeps_audit_trail(self, db, core_accounts, open_period, owner_user):
        """حذف مسودة ممكن — لكن سجل التدقيق يبقى (F1)."""
        entry = _post(reference_type='Sale', reference_id=79,
                      created_by=owner_user.id, is_posted=False)
        db.session.commit()

        audit_ids = [a.id for a in JournalEntryAudit.query.filter_by(
            journal_entry_id=entry.id).all()]
        assert audit_ids, 'F3: يجب كتابة سجل تدقيق حتى للمسودة'

        removed = GLService.purge_by_reference('Sale', 79)
        db.session.commit()
        assert removed == 1
        assert _db.session.get(GLJournalEntry, entry.id) is None

        survivors = JournalEntryAudit.query.filter(
            JournalEntryAudit.id.in_(audit_ids)
        ).all()
        assert len(survivors) == len(audit_ids), 'F1: سجل التدقيق ينجو من القيد'


# ---------------------------------------------------------------------------
# F4 — تسلسل أرقام القيود عام وليس لكل مستأجر
# ---------------------------------------------------------------------------

class TestGlobalEntryNumberSequence:
    def test_second_tenant_posts_and_gets_distinct_number(
            self, db, core_accounts, open_period, two_tenants, tenant_scope):
        t1, t2 = two_tenants

        tenant_scope.use(t1.id)
        try:
            entry1 = _post(description='مستأجر أول', created_by=None)
            db.session.commit()
        finally:
            tenant_scope.clear()

        tenant_scope.use(t2.id)
        try:
            entry2 = _post(description='مستأجر ثانٍ', created_by=None)
            db.session.commit()
        finally:
            tenant_scope.clear()

        assert entry1.entry_number != entry2.entry_number, (
            'F4: entry_number عالمي — رقمان مختلفان مطلوبان'
        )
        assert entry1.tenant_id == t1.id
        assert entry2.tenant_id == t2.id

    def test_entries_stay_tenant_scoped(self, db, core_accounts, open_period,
                                        two_tenants, tenant_scope):
        t1, t2 = two_tenants

        tenant_scope.use(t1.id)
        try:
            _post(description='مستأجر أول')
            db.session.commit()
        finally:
            tenant_scope.clear()

        tenant_scope.use(t2.id)
        try:
            visible = GLJournalEntry.query.all()
            assert visible == [], 'F4: القيود تبقى معزولة بين المستأجرين'
        finally:
            tenant_scope.clear()


# ---------------------------------------------------------------------------
# F5 — الحاجز في طبقة الخدمات
# ---------------------------------------------------------------------------

INVALID_LINES = {
    'negative_debit': [
        {'account': '1110', 'debit': Decimal('-10'), 'credit': Decimal('0')},
        {'account': '1130', 'debit': Decimal('0'), 'credit': Decimal('10')},
    ],
    'negative_credit': [
        {'account': '1110', 'debit': Decimal('10'), 'credit': Decimal('0')},
        {'account': '1130', 'debit': Decimal('0'), 'credit': Decimal('-10')},
    ],
    'both_sides': [
        {'account': '1110', 'debit': Decimal('10'), 'credit': Decimal('10')},
        {'account': '1130', 'debit': Decimal('0'), 'credit': Decimal('10')},
    ],
    'empty': [],
}


class TestServiceLevelBalanceGuard:
    @pytest.mark.parametrize('case', sorted(INVALID_LINES))
    def test_post_entry_rejects(self, db, core_accounts, open_period, case):
        with pytest.raises(ValueError):
            GLService.post_entry(lines=INVALID_LINES[case], description='مرفوض')

    @pytest.mark.parametrize('case', sorted(INVALID_LINES))
    def test_create_manual_entry_rejects(self, db, core_accounts, open_period, case):
        with pytest.raises(ValueError):
            GLService.create_manual_entry(
                description='مرفوض',
                lines=[
                    {**ln, 'account_code': ln['account']}
                    for ln in INVALID_LINES[case]
                ],
            )

    @pytest.mark.parametrize('case', sorted(INVALID_LINES))
    def test_create_journal_entry_rejects(self, db, core_accounts, open_period, case):
        with pytest.raises(ValueError):
            GLService.create_journal_entry(
                entry_type='manual',
                description='مرفوض',
                lines=[
                    {**ln, 'account_code': ln['account']}
                    for ln in INVALID_LINES[case]
                ],
            )

    def test_no_entry_is_persisted_when_rejected(self, db, core_accounts, open_period):
        before = GLJournalEntry.query.count()
        with pytest.raises(ValueError):
            GLService.post_entry(lines=INVALID_LINES['negative_debit'])
        db.session.rollback()
        assert GLJournalEntry.query.count() == before

    def test_header_totals_match_quantized_lines(self, db, core_accounts, open_period):
        """F5: الإجماليات تُحسب من نفس القيم المُكمّاة التي تُكتب في السطور."""
        entry = GLService.post_entry(
            lines=[
                {'account': '1110', 'debit': Decimal('10.0005'), 'credit': Decimal('0')},
                {'account': '1130', 'debit': Decimal('0'), 'credit': Decimal('10.0005')},
            ],
            description='تكميم',
        )
        db.session.commit()
        lines = entry.lines.all()
        sum_debit = sum((Decimal(str(ln.debit)) for ln in lines), Decimal('0'))
        sum_credit = sum((Decimal(str(ln.credit)) for ln in lines), Decimal('0'))
        assert entry.total_debit == sum_debit
        assert entry.total_credit == sum_credit
        assert sum_debit == sum_credit


# ---------------------------------------------------------------------------
# F2 + F9 — عكس القيد وحماية القيد المرحّل
# ---------------------------------------------------------------------------

class TestReversalAndImmutability:
    def test_draft_can_be_created_and_then_approved(self, db, core_accounts,
                                                    open_period, owner_user):
        """F9: المسودة مسار حقيقي — تُنشأ غير مرحّلة ثم تُرحَّل بالموافقة."""
        from services.advanced_journal_manager import AdvancedJournalEntryManager

        draft = AdvancedJournalEntryManager.create_entry_with_validation(
            description='مسودة قبل الاعتماد',
            lines=[
                {'account_code': '1110', 'debit': Decimal('40'), 'credit': Decimal('0')},
                {'account_code': '1130', 'debit': Decimal('0'), 'credit': Decimal('40')},
            ],
            created_by=owner_user.id,
            is_posted=False,
        )
        db.session.commit()
        assert draft.is_posted is False

        approved = AdvancedJournalEntryManager.approve_entry(
            draft.id, owner_user.id, approval_notes='معتمد')
        assert approved.is_posted is True
        audit = JournalEntryAudit.query.filter_by(
            journal_entry_id=draft.id, action=JournalEntryAudit.ACTION_APPROVE
        ).first()
        assert audit is not None

    def test_posted_entry_cannot_be_mutated_through_orm(
            self, db, core_accounts, open_period, owner_user):
        entry = _post(created_by=owner_user.id)
        db.session.commit()

        entry.description = 'تلاعب'
        with pytest.raises(ValueError):
            db.session.commit()
        db.session.rollback()

        entry = _db.session.get(GLJournalEntry, entry.id)
        assert entry.description != 'تلاعب'

    def test_posted_entry_amounts_cannot_be_mutated(
            self, db, core_accounts, open_period, owner_user):
        entry = _post(created_by=owner_user.id)
        db.session.commit()

        entry.total_debit = Decimal('999')
        with pytest.raises(ValueError):
            db.session.commit()
        db.session.rollback()

    def test_reversal_links_both_directions_and_writes_audit(
            self, db, core_accounts, open_period, owner_user):
        entry = _post(created_by=owner_user.id)
        db.session.commit()

        reversal = entry.reverse_entry(description='قيد عكسي', created_by=owner_user.id)
        db.session.commit()

        assert entry.is_reversed is True
        assert entry.reversed_entry_id == reversal.id
        assert reversal.reversed_entry_id == entry.id
        assert reversal.entry_type == 'reversing'
        assert reversal.entry_number != entry.entry_number
        assert reversal.entry_number.startswith('JE-')

        audits = JournalEntryAudit.query.filter_by(
            journal_entry_id=reversal.id, action=JournalEntryAudit.ACTION_REVERSE
        ).all()
        assert len(audits) == 1, 'F2: القيد العكسي يجب أن يكتب سجل تدقيق'
        assert audits[0].performed_by == owner_user.id

    def test_reversal_totals_derive_from_lines(
            self, db, core_accounts, open_period, owner_user):
        entry = _post(created_by=owner_user.id)
        db.session.commit()

        reversal = entry.reverse_entry(created_by=owner_user.id)
        db.session.commit()

        rev_lines = reversal.lines.all()
        assert len(rev_lines) == 2
        assert reversal.total_debit == sum(
            (Decimal(str(ln.debit)) for ln in rev_lines), Decimal('0'))
        assert reversal.total_credit == sum(
            (Decimal(str(ln.credit)) for ln in rev_lines), Decimal('0'))
        # السطور معكوسة
        for rev in rev_lines:
            src = next(ln for ln in entry.lines if ln.account_id == rev.account_id)
            assert rev.debit == src.credit
            assert rev.credit == src.debit


# ---------------------------------------------------------------------------
# F3 — سجل التدقيق للقيود المرحَّلة آلياً
# ---------------------------------------------------------------------------

class TestAutoPostedEntriesAreAudited:
    def test_post_entry_writes_audit_with_codes_and_amounts(
            self, db, core_accounts, open_period, owner_user):
        entry = _post(created_by=owner_user.id)
        db.session.commit()

        audits = JournalEntryAudit.query.filter_by(
            journal_entry_id=entry.id, action=JournalEntryAudit.ACTION_CREATE
        ).all()
        assert len(audits) == 1
        payload = audits[0].new_values
        assert '1110' in payload and '1130' in payload
        assert '100' in payload
        assert audits[0].performed_by == owner_user.id

    def test_create_journal_entry_writes_audit(self, db, core_accounts, open_period,
                                               owner_user):
        entry = GLService.create_journal_entry(
            entry_type='manual',
            description='قيد مرحّل',
            lines=[
                {'account_code': '1110', 'debit': Decimal('50'), 'credit': Decimal('0')},
                {'account_code': '1130', 'debit': Decimal('0'), 'credit': Decimal('50')},
            ],
            created_by=owner_user.id,
        )
        db.session.commit()
        audits = JournalEntryAudit.query.filter_by(
            journal_entry_id=entry.id, action=JournalEntryAudit.ACTION_CREATE
        ).all()
        assert len(audits) == 1


# ---------------------------------------------------------------------------
# F10 — الفترة المالية
# ---------------------------------------------------------------------------

class TestFiscalPeriodLock:
    def test_posting_into_closed_period_is_rejected(self, db, core_accounts, open_period):
        open_period.is_closed = True
        open_period.closed_at = datetime.now(timezone.utc)
        db.session.commit()

        with pytest.raises(ValidationError):
            GLService.post_entry(lines=list(BALANCED), description='فترة مغلقة')
        db.session.rollback()

    def test_posting_with_no_period_is_rejected(self, db, core_accounts):
        """لا توجد أي فترة مالية → لا ترحيل.

        The date is explicit and far outside the range the fixtures open, so
        the test states the invariant it is about: a date that no period
        covers is NOT open, and posting into it is refused. Posting into
        "today" would no longer prove anything, because the fixtures (and
        the application itself) open the current year.
        """
        from datetime import date as _date

        uncovered = _date(_date.today().year - 6, 6, 1)
        with pytest.raises(ValidationError):
            GLService.post_entry(lines=list(BALANCED), description='بلا فترة',
                                entry_date=uncovered)
        db.session.rollback()

    def test_manual_entry_into_closed_period_is_rejected(self, db, core_accounts,
                                                         open_period):
        open_period.is_closed = True
        db.session.commit()
        with pytest.raises(ValidationError):
            GLService.create_manual_entry(
                description='فترة مغلقة',
                lines=[
                    {'account_code': '1110', 'debit': Decimal('10'), 'credit': Decimal('0')},
                    {'account_code': '1130', 'debit': Decimal('0'), 'credit': Decimal('10')},
                ],
            )
        db.session.rollback()

    def test_journal_entry_into_closed_period_is_rejected(self, db, core_accounts,
                                                          open_period):
        open_period.is_closed = True
        db.session.commit()
        with pytest.raises(ValidationError):
            GLService.create_journal_entry(
                entry_type='manual',
                description='فترة مغلقة',
                lines=[
                    {'account_code': '1110', 'debit': Decimal('10'), 'credit': Decimal('0')},
                    {'account_code': '1130', 'debit': Decimal('0'), 'credit': Decimal('10')},
                ],
            )
        db.session.rollback()

    def test_period_lookup_is_tenant_aware(self, db, core_accounts, open_period,
                                            two_tenants, tenant_scope):
        """F10: الفترة الخاصة بمستأجر لا تسري على مستأجر آخر."""
        from models.erp_modules import FiscalPeriod
        from services.fiscal_period_guard import is_open, period_for_date

        t1, t2 = two_tenants
        # سنة بلا فترة عامة — فترة خاصة بالمستأجر الأول فقط
        private_year = date.today().year - 3
        private = FiscalPeriod(
            name='T1 private FY',
            year=private_year,
            period_type='annual',
            start_date=date(private_year, 1, 1),
            end_date=date(private_year, 12, 31),
            is_closed=False,
        )
        if hasattr(FiscalPeriod, 'tenant_id'):
            private.tenant_id = t1.id
        db.session.add(private)
        db.session.commit()

        target = date(private_year, 6, 1)

        tenant_scope.use(t1.id)
        try:
            assert period_for_date(target).id == private.id
            assert is_open(target) is True
        finally:
            tenant_scope.clear()

        tenant_scope.use(t2.id)
        try:
            # المستأجر الثاني لا يرى الفترة الخاصة بالأول
            assert period_for_date(target) is None
            assert is_open(target) is False
        finally:
            tenant_scope.clear()


# ---------------------------------------------------------------------------
# عزل المستأجرين في الحاجز (توازن القيد)
# ---------------------------------------------------------------------------

class TestBalanceGuardAcrossTenantSwitch:
    def test_unbalanced_entry_rejected_in_both_tenants(self, db, core_accounts,
                                                        open_period, two_tenants,
                                                        tenant_scope):
        t1, t2 = two_tenants
        unbalanced = [
            {'account': '1110', 'debit': Decimal('100'), 'credit': Decimal('0')},
            {'account': '1130', 'debit': Decimal('0'), 'credit': Decimal('90')},
        ]

        for tenant in (t1, t2):
            tenant_scope.use(tenant.id)
            try:
                with pytest.raises(ValueError):
                    GLService.post_entry(lines=unbalanced, description='غير متوازن')
            finally:
                tenant_scope.clear()
            db.session.rollback()

    def test_balanced_entry_passes_in_both_tenants(self, db, core_accounts,
                                                   open_period, two_tenants,
                                                   tenant_scope):
        t1, t2 = two_tenants
        numbers = []
        for tenant in (t1, t2):
            tenant_scope.use(tenant.id)
            try:
                entry = _post(description='متوازن')
                db.session.commit()
                numbers.append(entry.entry_number)
            finally:
                tenant_scope.clear()
        assert len(set(numbers)) == 2


# ---------------------------------------------------------------------------
# F8 — نوع الحساب، حماية الحسابات المُبذَرة، اتجاه الحركة
# ---------------------------------------------------------------------------

class TestAccountIntegrity:
    def test_invalid_account_type_is_rejected(self, db):
        with pytest.raises(ValueError):
            GLAccount(code='9901', name='Bad', name_ar='سيّئ', type='banana')
        db.session.rollback()

    def test_seeded_account_code_and_type_are_locked(self, db, core_accounts):
        account = GLAccount.query.filter_by(code='1110').first()
        assert account is not None

        account.code = '9910'
        with pytest.raises(ValueError):
            db.session.commit()
        db.session.rollback()

        account = GLAccount.query.filter_by(code='1110').first()
        account.type = 'revenue'
        with pytest.raises(ValueError):
            db.session.commit()
        db.session.rollback()

    def test_seeded_account_cannot_be_deleted(self, db, core_accounts):
        account = GLAccount.query.filter_by(code='1110').first()
        db.session.delete(account)
        with pytest.raises(ValueError):
            db.session.commit()
        db.session.rollback()

    def test_wrong_direction_posting_is_rejected(self, db, core_accounts, open_period):
        """مدين على حساب إيراد (طبيعة دائنة) بدون استثناء موثّق."""
        with pytest.raises(ValueError):
            GLService.post_entry(
                lines=[
                    {'account': '4500', 'debit': Decimal('100'), 'credit': Decimal('0')},
                    {'account': '1110', 'debit': Decimal('0'), 'credit': Decimal('100')},
                ],
                description='مدين على إيراد آخر',
            )
        db.session.rollback()

    def test_credit_on_debit_normal_account_is_allowed_when_documented(
            self, db, core_accounts, open_period):
        """نقص المخزون (دائن على 1140) استثناء موثّق."""
        entry = GLService.post_entry(
            lines=[
                {'account': '5100', 'debit': Decimal('100'), 'credit': Decimal('0')},
                {'account': '1140', 'debit': Decimal('0'), 'credit': Decimal('100')},
            ],
            description='تكلفة مبيعات',
        )
        db.session.commit()
        assert entry.total_credit == Decimal('100')

    def test_documented_direction_exceptions_are_allowed(self, db, core_accounts,
                                                          open_period):
        """سداد الموردين (مدين على 2110) استثناء موثّق."""
        entry = GLService.post_entry(
            lines=[
                {'account': '2110', 'debit': Decimal('100'), 'credit': Decimal('0')},
                {'account': '1110', 'debit': Decimal('0'), 'credit': Decimal('100')},
            ],
            description='سداد مورد',
        )
        db.session.commit()
        assert entry.total_debit == Decimal('100')
