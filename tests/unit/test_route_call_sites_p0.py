"""P0 — مواقع الاستدعاء المكسورة في المسارات (routes) بعد تغيير سلوك دفتر الأستاذ.

سياق المشكلة
-------------
تغيّر سلوك خدمتين في طبقة الخدمات أثناء جولة التصلّيب الأمني:

* ``GLService.purge_by_reference`` يرفض الآن حذف قيد **مرحَّل** أو معكوس
  ويرفع ``ValidationError``، ولا يحذف صفوف ``JournalEntryAudit`` أبداً.
* ``GLService.reverse_entry`` لم يعد يبتلع الأخطاء، و``GLJournalEntry.reverse_entry``
  يكتب سجل تدقيق ويربط القيدين في الاتجاهين.

الملفات المكسورة (والتي صُلّحت هنا):

* F1  ثمانية مواقع استدعاء كانت تحذف القيود المحاسبية ← صارت تُعكس القيود
      المرحَّلة وتحذف المسودات فقط (routes/sales.py, routes/payments.py,
      routes/expenses.py, routes/cheques.py, routes/purchases.py).
* F2  مساران كانا يبتلعان فشل العكس ← صار الفشل يُعلن ولا يُؤرشف المستند.
* F3  تعديل/حذف حساب محاسبي مُبذَر كانا يظهران "خطأ غير متوقع" ← صار
      خطأ النموذج يُعرض كما هو + التحقق من نوع الحساب في المسار.
* F4  لا وجود لإدخال الرصيد الافتتاحي للعميل/المورد.
* F5  حذف سند قبض كان يخصم المبلغ الكلي من فاتورة واحدة ← صار يعكس كل
      تخصيص على فاتورته.
* F6  مسارا الأرشفة والحذف للفاتورة كانا لا يعيدان البضاعة إلى المخزون.

الاختبارات هنا تغطي السلوك الجديد من طرف المسار (HTTP) لا من طرف الخدمة.
"""
from decimal import Decimal

import pytest

from extensions import db as _db
from models import GLAccount, GLJournalEntry, Sale, Supplier
from services.gl_service import GLService


# ---------------------------------------------------------------------------
# مساعدات
# ---------------------------------------------------------------------------

BALANCED_LINES = [
    {'account': '1110', 'debit': Decimal('100'), 'credit': Decimal('0')},
    {'account': '1130', 'debit': Decimal('0'), 'credit': Decimal('100')},
]


@pytest.fixture
def core_accounts(db):
    """دليل الحسابات الأساسي (يلزم لترحيل أي قيد)."""
    GLService.ensure_core_accounts()
    _db.session.commit()
    return True


def _post_sale_entry(sale_id, owner_user, description='قيد فاتورة اختبار'):
    entry = GLService.post_entry(
        lines=[dict(line) for line in BALANCED_LINES],
        description=description,
        reference_type='Sale',
        reference_id=sale_id,
        created_by=owner_user.id,
    )
    _db.session.commit()
    return entry


def _post_draft_sale_entry(sale_id, owner_user):
    entry = GLService.post_entry(
        lines=[dict(line) for line in BALANCED_LINES],
        description='مسودة فاتورة',
        reference_type='Sale',
        reference_id=sale_id,
        created_by=owner_user.id,
        is_posted=False,
    )
    _db.session.commit()
    return entry


def _entries_for(reference_type, reference_id):
    return GLJournalEntry.query.filter_by(
        reference_type=reference_type, reference_id=reference_id
    ).all()


# ---------------------------------------------------------------------------
# F1 — حذف فاتورة مرحَّلة: تُعكس القيود ولا تُحذف
# ---------------------------------------------------------------------------

class TestDeletePostedSale:

    def test_deleting_posted_sale_reverses_entries_and_does_not_raise(
            self, client, db, login_owner, owner_user, test_sale, core_accounts):
        """F1: حذف فاتورة مرحَّلة يعكس القيود ولا يرفع خطأ."""
        entry = _post_sale_entry(test_sale.id, owner_user)
        entry_id = entry.id
        sale_id = test_sale.id

        response = client.post(f'/sales/{sale_id}/delete', follow_redirects=True)
        assert response.status_code == 200

        db.session.expire_all()
        original = db.session.get(GLJournalEntry, entry_id)
        assert original is not None, 'F1: القيد المرحَّل لا يُحذف أبداً'
        assert original.is_reversed is True, 'F1: القيد المرحَّل يجب أن يُعكس'

        reversals = [
            e for e in _entries_for('Sale', sale_id)
            if (e.entry_type or '') == 'reversing'
        ]
        assert len(reversals) == 1, 'F1: يجب إنشاء قيد عكسي واحد'
        assert reversals[0].reversed_entry_id == entry_id, 'F1: ربط القيد العكسي بالأصل'
        # القيد العكسي يحمل نفس المرجع (أثر المحاسبي محفوظ ومُفسَّر)
        assert reversals[0].reference_type == 'Sale'
        assert reversings_are_balanced(reversals[0]), 'F1: القيد العكسي متوازن'

        # الفاتورة نفسها حُذفت (لا ارتباطات مالية)
        assert db.session.get(Sale, sale_id) is None

    def test_draft_sale_is_still_purged(
            self, client, db, login_owner, owner_user, test_sale, core_accounts):
        """F1: مسودة (غير مرحَّلة) تُحذف كما كانت — لا قيد عكسي."""
        entry = _post_draft_sale_entry(test_sale.id, owner_user)
        entry_id = entry.id
        sale_id = test_sale.id

        response = client.post(f'/sales/{sale_id}/delete', follow_redirects=True)
        assert response.status_code == 200

        db.session.expire_all()
        assert db.session.get(GLJournalEntry, entry_id) is None, \
            'F1: مسودة غير مرحَّلة يجوز حذفها'
        assert not [
            e for e in _entries_for('Sale', sale_id)
            if (e.entry_type or '') == 'reversing'
        ], 'F1: المسودة لا تُنتج قيداً عكسياً'
        assert db.session.get(Sale, sale_id) is None

    def test_delete_message_reports_the_reversal(
            self, client, db, login_owner, owner_user, test_sale, core_accounts):
        """F1: المستخدم يُبلَّغ بأن القيود عُكست (لم تُحذف)."""
        _post_sale_entry(test_sale.id, owner_user)

        page = client.post(f'/sales/{test_sale.id}/delete', follow_redirects=True)
        body = page.get_data(as_text=True)
        assert 'عُكست' in body or 'عكس' in body, \
            'F1: الرسالة يجب أن تذكر عكس القيود'


def reversings_are_balanced(entry):
    """القيد العكسي متوازن (مدين = دائن)."""
    debit = sum((line.debit or Decimal('0')) for line in entry.lines)
    credit = sum((line.credit or Decimal('0')) for line in entry.lines)
    return debit == credit


# ---------------------------------------------------------------------------
# F2 — فشل العكس: المستند يبقى كما هو والخطأ يُعلن
# ---------------------------------------------------------------------------

class TestFailedReversal:

    def test_failed_reversal_keeps_sale_and_reports_failure(
            self, client, db, login_owner, owner_user, test_sale, core_accounts,
            monkeypatch):
        """F2: إذا فشل العكس لا تُحذف الفاتورة ويُقال للمستخدم why."""
        entry = _post_sale_entry(test_sale.id, owner_user)
        sale_id = test_sale.id

        def _boom(*args, **kwargs):
            raise RuntimeError('فشل العكس للاختبار')

        monkeypatch.setattr(GLService, 'reverse_entry', staticmethod(_boom))

        page = client.post(f'/sales/{sale_id}/delete', follow_redirects=True)
        body = page.get_data(as_text=True)

        db.session.expire_all()
        assert db.session.get(Sale, sale_id) is not None, \
            'F2: الفاتورة لا تُحذف إذا لم يُعكس القيد'
        original = db.session.get(GLJournalEntry, entry.id)
        assert original is not None and original.is_reversed is False, \
            'F2: القيد لا يُعكس جزئياً'

        assert 'تعذّر' in body, 'F2: يجب إعلان فشل العكس للمستخدم'

    def test_archive_of_sale_with_failed_reversal_keeps_sale(
            self, client, db, login_owner, owner_user, test_sale, core_accounts,
            monkeypatch):
        """F2: الأرشفة لا تكمل إذا فشل العكس."""
        _post_sale_entry(test_sale.id, owner_user)
        sale_id = test_sale.id

        def _boom(*args, **kwargs):
            raise RuntimeError('فشل العكس للاختبار')

        monkeypatch.setattr(GLService, 'reverse_entry', staticmethod(_boom))

        page = client.post(f'/sales/{sale_id}/archive', follow_redirects=True)
        body = page.get_data(as_text=True)

        db.session.expire_all()
        assert db.session.get(Sale, sale_id) is not None, \
            'F2: لا أرشفة عند فشل العكس'
        from models import ArchivedRecord
        archived = ArchivedRecord.query.filter_by(
            table_name='sales', record_id=sale_id).first()
        assert archived is None, 'F2: لا سجل أرشفة عند فشل العكس'
        assert 'تعذّر' in body


# ---------------------------------------------------------------------------
# F3 — تعديل/حذف حساب محاسبي: رسالة النموذج تظهر كما هي
# ---------------------------------------------------------------------------

class TestLedgerAccountGuards:

    def _seeded_account(self, db):
        GLService.ensure_core_accounts()
        db.session.commit()
        account = GLAccount.query.filter_by(code='1110').first()
        assert account is not None
        return account

    def test_edit_seeded_account_shows_model_message(
            self, client, db, login_owner, core_accounts):
        """F3: تغيير كود/نوع حساب مُبذَر — رسالة النموذج لا رسالة "غير متوقع"."""
        account = self._seeded_account(db)
        account_id = account.id

        page = client.post(f'/ledger/accounts/{account_id}/edit', data={
            'code': '9999',
            'name': 'الصندوق',
            'name_ar': 'الصندوق',
            'type': 'asset',
            'currency': 'ILS',
        }, follow_redirects=True)
        body = page.get_data(as_text=True)

        assert 'مُبذَر' in body, 'F3: يجب عرض رسالة حارس النموذج'
        assert 'حدث خطأ غير متوقع' not in body, \
            'F3: الرسالة العامة لا تُعرض مكان رسالة النموذج'

        db.session.expire_all()
        still = db.session.get(GLAccount, account_id)
        assert still is not None and still.code == '1110', \
            'F3: لم يُعدَّل الحساب المُبذَر'

    def test_delete_seeded_account_shows_model_message(
            self, client, db, login_owner, core_accounts):
        """F3: حذف حساب مُبذَر مرفوض برسالة واضحة."""
        account = self._seeded_account(db)
        account_id = account.id

        page = client.post(f'/ledger/accounts/{account_id}/delete',
                           follow_redirects=True)
        body = page.get_data(as_text=True)

        assert 'مُبذَر' in body, 'F3: يجب عرض رسالة حارس النموذج'
        db.session.expire_all()
        assert db.session.get(GLAccount, account_id) is not None, \
            'F3: الحساب المُبذَر لم يُحذف'

    def test_unknown_account_type_is_rejected_with_valid_types(
            self, client, db, login_owner, core_accounts):
        """F3: نوع غير معروف يُرفض برسالة تسرد الأنواع المسموحة."""
        account = self._seeded_account(db)

        page = client.post(f'/ledger/accounts/{account.id}/edit', data={
            'code': '1110',
            'name': 'الصندوق',
            'name_ar': 'الصندوق',
            'type': 'banana',
            'currency': 'ILS',
        }, follow_redirects=True)
        body = page.get_data(as_text=True)

        assert 'نوع حساب غير صالح' in body
        for valid_type in sorted(GLAccount.VALID_TYPES):
            assert valid_type in body, \
                'F3: الرسالة يجب أن تسرد الأنواع المسموحة'


# ---------------------------------------------------------------------------
# F4 — الرصيد الافتتاحي للعميل والمورد
# ---------------------------------------------------------------------------

class TestOpeningBalance:

    def test_customer_opening_balance_is_persisted_and_derived(
            self, client, db, login_owner):
        """F4: رصيد افتتاحي للعميل يُحفظ ويدخل في اشتقاق الرصيد."""
        response = client.post('/customers/create', data={
            'name': 'عميل مُرحَّل',
            'name_ar': 'عميل مُرحَّل',
            'customer_type': 'regular',
            'phone': '+971500000001',
            'email': 'migrated@example.com',
            'preferred_currency': 'AED',
            'opening_balance': '500',
            'opening_balance_currency': 'USD',
            'opening_balance_rate': '3.5',
            'opening_balance_date': '2026-01-01',
        }, follow_redirects=True)
        assert response.status_code == 200

        from models import Customer
        customer = Customer.query.filter_by(name='عميل مُرحَّل').first()
        assert customer is not None, 'F4: لم يُنشأ العميل'
        assert Decimal(str(customer.opening_balance)) == Decimal('500')
        assert customer.opening_balance_currency == 'USD'
        assert Decimal(str(customer.opening_balance_rate)) == Decimal('3.5')
        assert customer.opening_balance_date is not None
        assert customer.opening_balance_date.isoformat() == '2026-01-01'

        # الرصيد المشتق يحوي الرصيد الافتتاحي (500 × 3.5 = 1750)
        from models.customer import derive_customer_balance
        balance = derive_customer_balance(customer.id)
        assert balance == Decimal('1750.000'), \
            'F4: الرصيد الافتتاحي يجب أن يدخل في اشتقاق رصيد العميل'

    def test_customer_opening_balance_can_be_edited(
            self, client, db, login_owner):
        """F4: التعديل لاحقاً يغيّر الرصيد الافتتاحي."""
        from models import Customer

        client.post('/customers/create', data={
            'name': 'عميل قابل للتعديل',
            'customer_type': 'regular',
            'phone': '+971500000002',
            'email': 'edit@example.com',
            'preferred_currency': 'AED',
            'opening_balance': '100',
            'opening_balance_currency': 'AED',
            'opening_balance_rate': '1',
            'opening_balance_date': '2026-01-01',
        }, follow_redirects=True)
        customer = Customer.query.filter_by(name='عميل قابل للتعديل').first()
        assert customer is not None

        client.post(f'/customers/{customer.id}/edit', data={
            'name': 'عميل قابل للتعديل',
            'customer_type': 'regular',
            'phone': '+971500000002',
            'email': 'edit@example.com',
            'preferred_currency': 'AED',
            'opening_balance': '250',
            'opening_balance_currency': 'AED',
            'opening_balance_rate': '1',
            'opening_balance_date': '2026-02-01',
        }, follow_redirects=True)

        db.session.expire_all()
        customer = db.session.get(Customer, customer.id)
        assert Decimal(str(customer.opening_balance)) == Decimal('250')
        assert customer.opening_balance_date.isoformat() == '2026-02-01'

    def test_supplier_initial_balance_is_not_a_purchase_statistic(
            self, client, db, login_owner):
        """F4: الرصيد الافتتاحي للمورد لا يُخزَّن في total_purchases_aed."""
        response = client.post('/suppliers/create', data={
            'name': 'مورد مُرحَّل',
            'supplier_type': 'parts',
            'phone': '+971500000003',
            'country': 'UAE',
            'preferred_currency': 'AED',
            'opening_balance': '1000',
            'opening_balance_currency': 'AED',
            'opening_balance_rate': '1',
            'opening_balance_date': '2026-01-01',
        }, follow_redirects=True)
        assert response.status_code == 200

        supplier = Supplier.query.filter_by(name='مورد مُرحَّل').first()
        assert supplier is not None, 'F4: لم يُنشأ المورد'
        assert Decimal(str(supplier.opening_balance)) == Decimal('1000')
        assert Decimal(str(supplier.total_purchases_aed or 0)) == Decimal('0'), \
            'F4: الرصيد الافتتاحي ليس إحصائية مشتريات'
        assert Decimal(str(supplier.get_balance_aed())) == Decimal('1000.000'), \
            'F4: رصيد المورد يشمل الرصيد الافتتاحي'


# ---------------------------------------------------------------------------
# F5 — عكس تخصيصات السند على الفواتير نفسها
# ---------------------------------------------------------------------------

class TestReceiptAllocationReversal:

    def _two_sales(self, db, owner_user, test_customer):
        from utils.helpers import generate_number

        sales = []
        for amount in (Decimal('100.000'), Decimal('200.000')):
            sale = Sale(
                sale_number=generate_number('S', Sale, 'sale_number'),
                customer_id=test_customer.id, seller_id=owner_user.id,
                total_amount=amount, amount_base=amount,
                paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
                balance_due=amount, currency='AED', exchange_rate=Decimal('1'),
                payment_status='unpaid', status='confirmed', is_active=True,
            )
            db.session.add(sale)
            sales.append(sale)
        db.session.commit()
        return sales

    def test_deleting_receipt_reverses_each_allocation_on_its_own_invoice(
            self, client, db, login_owner, owner_user, test_customer,
            core_accounts):
        """F5: سند موزَّع على فاتورتين — يُعكس كل تخصيص على فاتورته."""
        from services.payment_service import PaymentService

        first, second = self._two_sales(db, owner_user, test_customer)

        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'user_id': owner_user.id,
            'amount': Decimal('150'),
            'currency': 'AED',
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
            'allocate_to_sales': {first.id: Decimal('60'), second.id: Decimal('90')},
        })
        db.session.commit()
        receipt_id = receipt.id

        db.session.refresh(first)
        db.session.refresh(second)
        assert Decimal(str(first.paid_amount_base)) == Decimal('60.000')
        assert Decimal(str(second.paid_amount_base)) == Decimal('90.000')

        client.post(f'/payments/receipts/{receipt_id}/delete', follow_redirects=True)

        db.session.expire_all()
        first = db.session.get(Sale, first.id)
        second = db.session.get(Sale, second.id)
        assert Decimal(str(first.paid_amount_base)) == Decimal('0.000'), \
            'F5: تخصيص الفاتورة الأولى لم يُعكس'
        assert Decimal(str(second.paid_amount_base)) == Decimal('0.000'), \
            'F5: تخصيص الفاتورة الثانية لم يُعكس'
        assert first.payment_status == 'unpaid'
        assert second.payment_status == 'unpaid'
        assert Decimal(str(first.balance_due)) == Decimal('100.000')
        assert Decimal(str(second.balance_due)) == Decimal('200.000')


# ---------------------------------------------------------------------------
# F6 — عكس مخزون الفاتورة عند الحذف/الأرشفة
# ---------------------------------------------------------------------------

class TestSaleStockReversal:

    def test_deleting_sale_returns_stock_to_warehouse(
            self, client, db, login_owner, owner_user, test_sale, test_product,
            core_accounts):
        """F6: حذف الفاتورة يعيد البضاعة إلى المخزون."""
        from services.stock_service import StockService

        # خصم المخزون كما لو أُنشئت الفاتورة عبر الخدمة
        StockService.process_sale_lines(test_sale)
        db.session.commit()
        db.session.refresh(test_product)
        assert Decimal(str(test_product.current_stock)) == Decimal('98.000')

        client.post(f'/sales/{test_sale.id}/delete', follow_redirects=True)

        db.session.expire_all()
        product = db.session.get(type(test_product), test_product.id)
        assert Decimal(str(product.current_stock)) == Decimal('100.000'), \
            'F6: لم تُعَد البضاعة إلى المخزون'


# ---------------------------------------------------------------------------
# F1 (تابع) — سند قبض مرحَّل: يُعكس ولا يُحذف
# ---------------------------------------------------------------------------

class TestDeletePostedReceipt:

    def test_deleting_receipt_with_posted_entry_reverses_it(
            self, client, db, login_owner, owner_user, test_customer,
            core_accounts):
        """F1: سند قبض مرحَّل — القيود تُعكس ولا تُحذف."""
        from services.payment_service import PaymentService

        receipt = PaymentService.create_receipt({
            'customer_id': test_customer.id,
            'user_id': owner_user.id,
            'amount': Decimal('50'),
            'currency': 'AED',
            'payment_method': 'cash',
            'user_exchange_rate': Decimal('1'),
        })
        db.session.commit()
        receipt_id = receipt.id

        entries = _entries_for('Receipt', receipt_id)
        assert entries, 'F1: السند يجب أن يكون له قيد مرحَّل'
        entry_ids = [e.id for e in entries]

        client.post(f'/payments/receipts/{receipt_id}/delete', follow_redirects=True)

        db.session.expire_all()
        for entry_id in entry_ids:
            entry = db.session.get(GLJournalEntry, entry_id)
            assert entry is not None, 'F1: القيد المرحَّل لا يُحذف'
            assert entry.is_reversed is True, 'F1: القيد المرحَّل يجب أن يُعكس'
