"""P0 — اختبارات المديونيات المشطوبة (Bad debt write-offs).

المشكلة التي تحلّها هذه الاختبارات: ذمة مدينة لن تُحصَّل أبداً لم يكن
لها كيان، فبقي رصيدها علىBooks كأنّه قابل للتحصيل للأبد. المديونية
المشطوبة كيانها الآن، وتُرحّل إلى دفتر الأستاذ:

    مدين  6960  مديونية مشطوبة
    دائن  1130  الذمم المدينة

المغطّى هنا:

* القيد المرحّل متوازن (مدين = دائن بالعملة الأساسية) ومرتبط بسطر
  المشطوبة عبر ``gl_entry_id``.
* رصيد العميل ينقص بالمبلغ المشطوب (من الاشتقاق الواحد).
* المبلغ لا يتجاوز الرصيد المستحق، والمبلغ غير الموجب مرفوض.
* فشل الترحيل لا يترك سطر مشطوبة معلّقاً (التراجع كامل).
* الإلغاء يعكس القيد ويعيد الرصيد، والإلغاء الثاني مرفوض.
* الفترة المالية المغلقة ترفض المشطوبة.
* عزل المستأجر: مشطوبة مستأجر آخر غير مرئية.
* سجل التدقيق يكتب سطراً للمشطوبة.

كل المبالغ Decimal، وبدون أي طلب HTTP.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from extensions import db
from models import (
    AuditLog,
    Customer,
    GLAccount,
    GLJournalEntry,
    Sale,
    SaleLine,
    Tenant,
)
from models.write_off import WriteOff
from services.gl_service import GLService
from services.writeoff_service import WriteOffService
from utils.errors import ValidationError

BAD_DEBT_CODE = '6960'
AR_CODE = '1130'


# ─────────────────────────── helpers ───────────────────────────

def _sale(db, customer, seller, number='S-WO-1', total='1000.000'):
    """فاتورة بيع مؤكدة — تمنح العميل رصيداً مستحقاً."""
    total_d = Decimal(str(total))
    sale = Sale(
        sale_number=number, customer_id=customer.id, seller_id=seller.id,
        total_amount=total_d, amount_base=total_d,
        paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
        balance_due=total_d,
        currency='ILS', exchange_rate=Decimal('1'),
        payment_status='unpaid', status='confirmed', is_active=True,
        sale_date=datetime.now(timezone.utc),
    )
    db.session.add(sale)
    db.session.commit()
    return sale


def _entry_lines(entry):
    """{(account_code): {'debit': Decimal, 'credit': Decimal, 'base': Decimal}}."""
    out = {}
    for line in entry.lines.all():
        out[line.account.code] = {
            'debit': Decimal(str(line.debit or 0)),
            'credit': Decimal(str(line.credit or 0)),
            'base': Decimal(str(line.amount_base or 0)),
        }
    return out


def _close_current_period(db):
    """يغلق الفترة المالية التي تغطي اليوم."""
    from models.erp_modules import FiscalPeriod

    year = date.today().year
    period = FiscalPeriod.query.filter(
        FiscalPeriod.year == year, FiscalPeriod.period_type == 'annual'
    ).first()
    assert period is not None, 'the fixtures must open the current year'
    period.is_closed = True
    period.closed_at = datetime.now(timezone.utc)
    db.session.commit()
    return period


# ─────────────────────────── fixtures ───────────────────────────

@pytest.fixture(autouse=True)
def _core_accounts(db):
    """دليل الحسابات الأساسي (بما فيه حساب 6960)."""
    GLService.ensure_core_accounts()
    db.session.commit()
    return True


@pytest.fixture
def customer(db, owner_user):
    """عميل له رصيد مستحق 1000 (فاتورة بيع مؤكدة)."""
    c = Customer(
        name='Write-off customer', name_ar='عميل مشطوبة',
        customer_type='regular', balance=Decimal('0'),
        credit_limit=Decimal('100000'), is_active=True,
    )
    db.session.add(c)
    db.session.commit()
    _sale(db, c, owner_user)
    db.session.refresh(c)
    return c


# ─────────────────────── الترحيل والحساب ───────────────────────

class TestWriteOffPosting:

    def test_create_posts_balanced_entry_dr_bad_debt_cr_receivable(
            self, db, customer, owner_user):
        """القيد متوازن: مدين 6960 / دائن 1130، ومربوط بسطر المشطوبة."""
        write_off = WriteOffService.create_writeoff(
            customer, Decimal('100'), reason='العميل هاجر')

        assert write_off.status == WriteOff.STATUS_POSTED
        assert write_off.posted_at is not None
        assert write_off.gl_entry_id is not None

        entry = db.session.get(GLJournalEntry, write_off.gl_entry_id)
        assert entry is not None, 'المشطوبة يجب أن ترتبط بقيدها'
        assert entry.reference_type == 'WriteOff'
        assert entry.reference_id == write_off.id
        assert entry.is_posted is True

        # التوازن في العملة الأساسية
        total_debit = sum(Decimal(str(ln.debit or 0)) for ln in entry.lines.all())
        total_credit = sum(Decimal(str(ln.credit or 0)) for ln in entry.lines.all())
        base_debit = sum(Decimal(str(ln.amount_base or 0)) for ln in entry.lines.all()
                         if Decimal(str(ln.debit or 0)) > 0)
        base_credit = sum(abs(Decimal(str(ln.amount_base or 0))) for ln in entry.lines.all()
                          if Decimal(str(ln.credit or 0)) > 0)
        assert total_debit == total_credit == Decimal('100')
        assert base_debit == base_credit == Decimal('100')

        lines = _entry_lines(entry)
        assert lines[BAD_DEBT_CODE]['debit'] == Decimal('100')
        assert lines[BAD_DEBT_CODE]['credit'] == Decimal('0')
        assert lines[AR_CODE]['credit'] == Decimal('100')
        assert lines[AR_CODE]['debit'] == Decimal('0')

    def test_bad_debt_account_is_seeded_and_locked(self, db, customer):
        """حساب 6960 مُبذَر: مديونية مشطوبة، نوع مصروف، حساب نظام."""
        account = GLAccount.query.filter_by(code=BAD_DEBT_CODE).first()
        assert account is not None, 'حساب المديونية المشطوبة يجب أن يكون في الدليل'
        assert account.name == 'Bad debt expense'
        assert account.name_ar == 'مديونية مشطوبة'
        assert account.type == 'expense'
        assert account.is_system is True
        assert account.is_header is False
        assert account.is_active is True

    def test_amount_base_uses_the_exchange_rate(self, db, customer, monkeypatch):
        """المبلغ يُخزَّن بعملة المعاملة وبعملة الأساس."""
        from services import currency_service

        monkeypatch.setattr(
            currency_service.CurrencyService, 'get_exchange_rate',
            staticmethod(lambda from_currency, to_currency=None, user_rate=None:
                         Decimal('3.67') if from_currency == 'USD' else Decimal('1')))

        write_off = WriteOffService.create_writeoff(
            customer, Decimal('100'), currency='USD', reason='عميل خارجي')

        assert write_off.currency == 'USD'
        assert write_off.amount == Decimal('100')
        assert write_off.amount_base == Decimal('367.000')


class TestCustomerBalance:

    def test_writeoff_reduces_the_customer_balance(self, db, customer):
        """رصيد العميل ينقص بالمبلغ المشطوب."""
        from models.customer import derive_customer_balance

        before = Decimal(str(customer.balance))
        assert before == Decimal('1000.000')

        WriteOffService.create_writeoff(customer, Decimal('250'), reason='مشطوبة')

        db.session.refresh(customer)
        assert Decimal(str(customer.balance)) == before - Decimal('250')
        assert derive_customer_balance(customer.id) == before - Decimal('250')

    def test_amount_may_not_exceed_the_outstanding_balance(self, db, customer):
        """لا يُشطب أكثر من الرصيد المستحق."""
        from models.customer import derive_customer_balance

        with pytest.raises(ValueError):
            WriteOffService.create_writeoff(customer, Decimal('1000.001'), reason='مبالغ')

        db.session.rollback()
        assert WriteOff.query.count() == 0
        assert GLJournalEntry.query.count() == 0
        assert derive_customer_balance(customer.id) == Decimal('1000.000')

    def test_zero_or_negative_amount_is_refused(self, db, customer):
        """المبلغ يجب أن يكون أكبر من صفر."""
        for bad in (Decimal('0'), Decimal('-100'), 0, -5):
            with pytest.raises(ValueError):
                WriteOffService.create_writeoff(customer, bad, reason='مبالغ')

        db.session.rollback()
        assert WriteOff.query.count() == 0
        assert GLJournalEntry.query.count() == 0

    def test_failed_posting_leaves_no_writeoff_row(self, db, customer, monkeypatch):
        """فشل الترحيل يتراجع عن كل شيء — لا سطر مشطوبة بلا قيد."""
        from services import writeoff_service

        def _boom(*args, **kwargs):
            raise RuntimeError('دفتر الأستاذ غير متاح')

        monkeypatch.setattr(writeoff_service.GLService, 'post_entry', _boom)

        with pytest.raises(RuntimeError):
            WriteOffService.create_writeoff(customer, Decimal('100'), reason='مبالغ')

        db.session.rollback()
        assert WriteOff.query.count() == 0
        assert GLJournalEntry.query.count() == 0
        db.session.refresh(customer)
        assert Decimal(str(customer.balance)) == Decimal('1000.000')


class TestVoid:

    def test_void_reverses_the_entry_and_restores_the_balance(self, db, customer):
        """الإلغاء يعكس القيد ويعيد الرصيد."""
        from models.customer import derive_customer_balance

        write_off = WriteOffService.create_writeoff(customer, Decimal('300'), reason='مشطوبة')
        db.session.commit()

        entry = db.session.get(GLJournalEntry, write_off.gl_entry_id)
        entry_number = entry.entry_number

        voided = WriteOffService.void_writeoff(write_off, reason='خطأ في المشطوبة')

        assert voided.status == WriteOff.STATUS_VOID
        assert voided.voided_at is not None

        db.session.refresh(entry)
        assert entry.is_reversed is True
        assert entry.reversed_entry_id is not None

        reversal = db.session.get(GLJournalEntry, entry.reversed_entry_id)
        assert reversal is not None
        assert reversal.entry_type == 'reversing'
        rev_lines = _entry_lines(reversal)
        assert rev_lines[BAD_DEBT_CODE]['credit'] == Decimal('300')
        assert rev_lines[AR_CODE]['debit'] == Decimal('300')

        db.session.refresh(customer)
        assert Decimal(str(customer.balance)) == Decimal('1000.000')
        assert derive_customer_balance(customer.id) == Decimal('1000.000')

    def test_second_void_is_refused(self, db, customer):
        """لا يمكن إلغاء المشطوبة مرتين."""
        write_off = WriteOffService.create_writeoff(customer, Decimal('100'), reason='مشطوبة')
        db.session.commit()

        WriteOffService.void_writeoff(write_off, reason='إلغاء أول')
        db.session.commit()

        with pytest.raises(ValueError):
            WriteOffService.void_writeoff(write_off, reason='إلغاء ثانٍ')

        db.session.rollback()
        assert WriteOff.query.count() == 1


class TestFiscalPeriod:

    def test_closed_period_refuses_the_writeoff(self, db, customer):
        """الفترة المغلقة ترفض المشطوبة ولا يترك أثراً."""
        _close_current_period(db)

        with pytest.raises(ValidationError):
            WriteOffService.create_writeoff(customer, Decimal('100'), reason='مشطوبة')

        db.session.rollback()
        assert WriteOff.query.count() == 0
        assert GLJournalEntry.query.count() == 0


class TestTenantIsolation:

    def test_writeoff_of_another_tenant_is_invisible(self, db, owner_user):
        """مشطوبة مستأجر آخر لا تُرى ولا تُعدَّل."""
        from models.tenant_scope import clear_current_tenant_id, set_current_tenant_id

        t1 = Tenant(name='WO T1', name_ar='WO T1', slug='wo-t1', country='UAE', is_active=True)
        t2 = Tenant(name='WO T2', name_ar='WO T2', slug='wo-t2', country='UAE', is_active=True)
        db.session.add_all([t1, t2])
        db.session.commit()

        c1 = Customer(name='T1 customer', name_ar='T1', customer_type='regular',
                      balance=Decimal('0'), is_active=True, tenant_id=t1.id)
        c2 = Customer(name='T2 customer', name_ar='T2', customer_type='regular',
                      balance=Decimal('0'), is_active=True, tenant_id=t2.id)
        db.session.add_all([c1, c2])
        db.session.commit()

        set_current_tenant_id(t2.id)
        try:
            _sale(db, c2, owner_user, number='S-WO-T2')
            write_off = WriteOffService.create_writeoff(
                c2, Decimal('100'), reason='مشطوبة مستأجر آخر')
            db.session.commit()
            assert write_off.tenant_id == t2.id
        finally:
            clear_current_tenant_id()

        set_current_tenant_id(t1.id)
        try:
            assert WriteOff.query.count() == 0, 'مشطوبة مستأجر آخر لا تُرى'
            assert WriteOffService.get_writeoff(write_off.id) is None
            assert WriteOffService.list_writeoffs() == []
        finally:
            clear_current_tenant_id()


class TestAuditTrail:

    def test_audit_log_row_is_written(self, db, customer, owner_user):
        """كل مشطوبة تترك سطراً في سجل التدقيق."""
        write_off = WriteOffService.create_writeoff(customer, Decimal('100'), reason='مشطوبة')
        db.session.commit()

        logs = AuditLog.query.filter_by(
            table_name='write_offs', record_id=write_off.id).all()
        assert len(logs) >= 1, 'يجب كتابة سجل تدقيق للمشطوبة'
        assert logs[0].action == 'create'
        assert logs[0].changes['customer_id'] == customer.id
        assert logs[0].changes['amount'] == '100'

    def test_void_is_audited(self, db, customer):
        """الإلغاء أيضاً يترك سطراً في سجل التدقيق."""
        write_off = WriteOffService.create_writeoff(customer, Decimal('100'), reason='مشطوبة')
        db.session.commit()

        WriteOffService.void_writeoff(write_off, reason='إلغاء')
        db.session.commit()

        actions = [log.action for log in AuditLog.query.filter_by(
            table_name='write_offs', record_id=write_off.id).all()]
        assert 'void' in actions


class TestQueries:

    def test_list_and_get(self, db, customer):
        """الاستعلامات تحترم الفلترة والحالة."""
        write_off = WriteOffService.create_writeoff(customer, Decimal('100'), reason='مشطوبة')
        db.session.commit()

        assert WriteOffService.get_writeoff(write_off.id) is not None
        assert WriteOffService.get_writeoff(999999) is None
        assert len(WriteOffService.list_writeoffs(customer=customer)) == 1
        assert len(WriteOffService.list_writeoffs(status=WriteOff.STATUS_POSTED)) == 1
        assert WriteOffService.list_writeoffs(status=WriteOff.STATUS_VOID) == []

    def test_to_dict_shape(self, db, customer):
        """التمثيل النصي يحمل المبالغ والحالة."""
        write_off = WriteOffService.create_writeoff(customer, Decimal('100'), reason='مشطوبة')
        data = write_off.to_dict()
        assert data['customer_id'] == customer.id
        assert data['amount'] == 100.0
        assert data['amount_base'] == 100.0
        assert data['status'] == WriteOff.STATUS_POSTED
        assert data['gl_entry_id'] == write_off.gl_entry_id
