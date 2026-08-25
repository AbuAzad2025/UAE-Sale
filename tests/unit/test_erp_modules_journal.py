"""Unit tests for erp_modules_service + advanced_journal_manager."""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from models import (
    Customer, EInvoice, Expense, ExpenseCategory, GLJournalEntry, Product,
    Purchase, PurchaseOrder, Quotation, RecurringExpense, Sale,
    StockMovement, Supplier, Warehouse,
)
from services.advanced_journal_manager import AdvancedJournalEntryManager, JournalEntryAudit
from services.erp_modules_service import (
    DunningService, EInvoiceService, FiscalPeriodService, PurchaseOrderService,
    QuotationService, RecurringExpenseService, StockTakeService,
    StockTransferService,
)
from services.gl_service import GLService


@pytest.fixture
def gl(db):
    GLService.ensure_core_accounts()


@pytest.fixture
def warehouse(db):
    w = Warehouse(name='Main WH Test', name_ar='المستودع الرئيسي', code='WH-T01',
                  is_active=True, is_main=True)
    db.session.add(w)
    db.session.commit()
    return w


@pytest.fixture
def supplier(db):
    s = Supplier(name='مورد الإضاءة', is_active=True)
    db.session.add(s)
    db.session.commit()
    return s


def _make_quotation(db, owner_user, test_customer, test_product, warehouse, **overrides):
    lines = overrides.pop('lines', None) or [
        {'product_id': test_product.id, 'quantity': 2, 'unit_price': 100, 'discount_percent': 10},
    ]
    return QuotationService.create_quotation(
        customer_id=test_customer.id, seller_id=owner_user.id, lines_data=lines,
        warehouse_id=warehouse.id, currency='AED', discount_amount=10,
        shipping_cost=5, tax_rate=5, **overrides,
    )


class TestQuotationService:
    def test_create_quotation_calculates_totals(self, db, owner_user, test_customer, test_product, warehouse):
        q = _make_quotation(db, owner_user, test_customer, test_product, warehouse, notes='عرض تجريبي')
        assert q.quotation_number.startswith('QT-')
        assert q.status == 'draft'
        assert q.subtotal == Decimal('180.000')
        assert q.tax_amount == Decimal('8.75')
        assert q.total_amount == Decimal('183.750')
        assert q.amount_base == Decimal('183.750')
        assert q.valid_until == date.today() + timedelta(days=30)
        assert len(q.lines) == 1
        assert q.lines[0].line_total == Decimal('180.000')

    def test_create_quotation_skips_unknown_product_and_uses_catalog_price(
            self, db, owner_user, test_customer, test_product, warehouse):
        q = _make_quotation(db, owner_user, test_customer, test_product, warehouse, lines=[
            {'product_id': 999999, 'quantity': 5},
            {'product_id': test_product.id, 'quantity': 3},
        ])
        assert len(q.lines) == 1
        assert q.lines[0].unit_price == Decimal('100.000')
        assert q.subtotal == Decimal('300.000')

    def test_convert_to_sale_creates_linked_sale(self, db, owner_user, test_customer, test_product, warehouse):
        stock_before = test_product.current_stock
        q = _make_quotation(db, owner_user, test_customer, test_product, warehouse)
        sale = QuotationService.convert_to_sale(q.id, owner_user.id)

        assert sale.id is not None
        assert sale.customer_id == test_customer.id
        assert f'{q.quotation_number}' in (sale.notes or '')
        db.session.expire_all()
        q2 = db.session.get(Quotation, q.id)
        assert q2.status == 'converted'
        assert q2.converted_sale_id == sale.id
        assert db.session.get(Product, test_product.id).current_stock == stock_before - 2

    def test_convert_rejected_quotation_raises(self, db, owner_user, test_customer, test_product, warehouse):
        q = _make_quotation(db, owner_user, test_customer, test_product, warehouse)
        q.status = 'rejected'
        db.session.commit()
        with pytest.raises(ValueError, match='مرفوضة'):
            QuotationService.convert_to_sale(q.id, owner_user.id)

    def test_convert_expired_quotation_raises(self, db, owner_user, test_customer, test_product, warehouse):
        q = _make_quotation(db, owner_user, test_customer, test_product, warehouse)
        q.valid_until = date.today() - timedelta(days=1)
        db.session.commit()
        with pytest.raises(ValueError, match='منتهي'):
            QuotationService.convert_to_sale(q.id, owner_user.id)


class TestPurchaseOrderService:
    def test_create_po_calculates_totals(self, db, owner_user, test_product, supplier, warehouse):
        po = PurchaseOrderService.create_po(
            supplier_id=supplier.id, warehouse_id=warehouse.id,
            lines_data=[{'product_id': test_product.id, 'quantity': 3, 'unit_cost': 50}],
            user_id=owner_user.id, tax_rate=5,
        )
        assert po.po_number.startswith('PO-')
        assert po.subtotal == Decimal('150.000')
        assert po.tax_amount == Decimal('7.50')
        assert po.total_amount == Decimal('157.500')
        assert po.requested_by_id == owner_user.id

    def test_approve_po_requires_submitted_status(self, db, owner_user, test_product, supplier, warehouse):
        po = PurchaseOrderService.create_po(
            supplier_id=supplier.id, warehouse_id=warehouse.id,
            lines_data=[{'product_id': test_product.id, 'quantity': 1, 'unit_cost': 20}],
            user_id=owner_user.id,
        )
        with pytest.raises(ValueError, match='مقدمة'):
            PurchaseOrderService.approve_po(po.id, owner_user.id)

        po.status = 'submitted'
        db.session.commit()
        approved = PurchaseOrderService.approve_po(po.id, owner_user.id)
        assert approved.status == 'approved'
        assert approved.approved_by_id == owner_user.id
        assert approved.approved_at is not None

    def test_receive_po_creates_purchase_and_marks_received(self, db, owner_user, test_product, supplier, warehouse):
        po = PurchaseOrderService.create_po(
            supplier_id=supplier.id, warehouse_id=warehouse.id,
            lines_data=[{'product_id': test_product.id, 'quantity': 2, 'unit_cost': 50}],
            user_id=owner_user.id,
        )
        po.status = 'approved'
        db.session.commit()

        purchase = PurchaseOrderService.receive_po(po.id, owner_user.id)
        assert isinstance(purchase, Purchase)
        assert purchase.supplier_id == supplier.id
        assert len(purchase.lines) == 1
        assert purchase.lines[0].quantity == Decimal('2')
        assert purchase.total_amount == Decimal('100')

        db.session.expire_all()
        po2 = db.session.get(PurchaseOrder, po.id)
        assert po2.status == 'received'
        assert po2.purchase_id == purchase.id
        assert po2.is_fully_received

    def test_receive_po_wrong_status_raises(self, db, owner_user, test_product, supplier, warehouse):
        po = PurchaseOrderService.create_po(
            supplier_id=supplier.id, warehouse_id=warehouse.id,
            lines_data=[{'product_id': test_product.id, 'quantity': 1, 'unit_cost': 20}],
            user_id=owner_user.id,
        )
        with pytest.raises(ValueError, match='معتمد'):
            PurchaseOrderService.receive_po(po.id, owner_user.id)


class TestFiscalPeriodService:
    def test_create_annual_period_and_duplicate_raises(self, db):
        fp = FiscalPeriodService.create_annual_period(2030)
        assert fp.year == 2030
        assert fp.start_date == date(2030, 1, 1)
        assert fp.end_date == date(2030, 12, 31)
        assert fp.is_closed is False
        assert '2030' in fp.name
        with pytest.raises(ValueError, match='بالفعل'):
            FiscalPeriodService.create_annual_period(2030)

    def test_close_period_then_reclose_raises(self, db, owner_user):
        fp = FiscalPeriodService.create_annual_period(2031)
        closed = FiscalPeriodService.close_period(fp.id, owner_user.id)
        assert closed.is_closed is True
        assert closed.closed_by_id == owner_user.id
        assert closed.closed_at is not None
        with pytest.raises(ValueError, match='مقفلة بالفعل'):
            FiscalPeriodService.close_period(fp.id, owner_user.id)

    def test_is_period_open_respects_closed_periods(self, db, owner_user):
        assert FiscalPeriodService.is_period_open(date(2032, 6, 1)) is True
        fp = FiscalPeriodService.create_annual_period(2032)
        assert FiscalPeriodService.is_period_open(date(2032, 6, 1)) is True
        FiscalPeriodService.close_period(fp.id, owner_user.id)
        assert FiscalPeriodService.is_period_open(date(2032, 6, 1)) is False
        assert FiscalPeriodService.is_period_open(date(2033, 6, 1)) is True

    def test_get_current_period(self, db):
        assert FiscalPeriodService.get_current_period() is None
        fp = FiscalPeriodService.create_annual_period(date.today().year)
        assert FiscalPeriodService.get_current_period().id == fp.id

    def test_closed_period_blocks_new_sales(self, db, owner_user, test_customer, test_product, warehouse):
        fp = FiscalPeriodService.create_annual_period(date.today().year)
        FiscalPeriodService.close_period(fp.id, owner_user.id)
        q = _make_quotation(db, owner_user, test_customer, test_product, warehouse)
        with pytest.raises(ValueError, match='الفترة المالية الحالية مغلقة'):
            QuotationService.convert_to_sale(q.id, owner_user.id)


class TestStockTransferService:
    def test_same_warehouse_transfer_raises(self, db, owner_user, test_product, warehouse):
        with pytest.raises(ValueError, match='نفس المستودع'):
            StockTransferService.create_transfer(
                warehouse.id, warehouse.id,
                [{'product_id': test_product.id, 'quantity': 1}], owner_user.id,
            )

    def test_receive_requires_in_transit_then_moves_stock(self, db, owner_user, test_product, warehouse):
        dest = Warehouse(name='Branch WH', name_ar='مستودع الفرع', code='WH-T02',
                         is_active=True, is_main=False)
        db.session.add(dest)
        db.session.commit()
        stock_before = test_product.current_stock

        transfer = StockTransferService.create_transfer(
            warehouse.id, dest.id,
            [{'product_id': test_product.id, 'quantity': 5}], owner_user.id,
        )
        assert transfer.status == 'pending'
        with pytest.raises(ValueError, match='في الطريق'):
            StockTransferService.receive_transfer(transfer.id, owner_user.id)

        transfer.status = 'in_transit'
        db.session.commit()
        received = StockTransferService.receive_transfer(transfer.id, owner_user.id)
        assert received.status == 'received'
        assert received.received_by_id == owner_user.id
        assert received.received_at is not None
        assert db.session.get(Product, test_product.id).current_stock == stock_before
        adjustments = StockMovement.query.filter_by(
            movement_type='adjustment', product_id=test_product.id).all()
        assert {m.quantity for m in adjustments} == {Decimal('-5'), Decimal('5')}
        assert {m.warehouse_id for m in adjustments} == {warehouse.id, dest.id}


class TestStockTakeService:
    def test_snapshot_and_complete_computes_variance(self, db, owner_user, test_product, warehouse):
        st = StockTakeService.create_stocktake(warehouse.id, owner_user.id)
        assert st.stocktake_number.startswith('STK-')
        assert st.status == 'in_progress'
        assert len(st.items) == 1
        assert st.items[0].system_quantity == Decimal('100')

        st.items[0].counted_quantity = Decimal('97')
        completed = StockTakeService.complete_stocktake(st.id)
        assert completed.status == 'completed'
        assert completed.completed_at is not None
        assert completed.items[0].variance == Decimal('-3')

    def test_approve_requires_completed_then_applies_variance(self, db, owner_user, test_product, warehouse):
        st_pending = StockTakeService.create_stocktake(warehouse.id, owner_user.id)
        with pytest.raises(ValueError, match='إكمال الجرد'):
            StockTakeService.approve_stocktake(st_pending.id, owner_user.id)

        item = st_pending.items[0]
        item.counted_quantity = Decimal('90')
        StockTakeService.complete_stocktake(st_pending.id)
        approved = StockTakeService.approve_stocktake(st_pending.id, owner_user.id)
        assert approved.status == 'approved'
        assert approved.approved_by_id == owner_user.id
        assert db.session.get(Product, test_product.id).current_stock == Decimal('90')


class TestDunningService:
    def test_check_overdue_generates_leveled_letters(self, db, owner_user, test_customer, test_sale):
        test_sale.sale_date = datetime.now() - timedelta(days=20)
        sale2 = Sale(
            sale_number='S-DUN-0002',
            customer_id=test_customer.id, seller_id=owner_user.id,
            total_amount=Decimal('200'), amount_base=Decimal('200'),
            paid_amount=Decimal('0'), paid_amount_base=Decimal('0'),
            balance_due=Decimal('200'), currency='AED',
            exchange_rate=Decimal('1'), payment_status='unpaid',
            status='confirmed', is_active=True,
            sale_date=datetime.now() - timedelta(days=75),
        )
        db.session.add(sale2)
        db.session.commit()

        letters = DunningService.check_overdue_accounts()
        by_level = {ln.level: ln for ln in letters}
        assert set(by_level) == {1, 3}
        assert by_level[1].sale_id == test_sale.id
        assert by_level[1].days_overdue == 20
        assert by_level[1].amount_due == Decimal('100.000')
        assert by_level[3].days_overdue == 75
        assert all(ln.letter_number.startswith('DUN-') for ln in letters)

    def test_sent_letter_not_regenerated_same_level(self, db, owner_user, test_customer, test_sale):
        test_sale.sale_date = datetime.now() - timedelta(days=20)
        db.session.commit()
        first = DunningService.check_overdue_accounts()
        assert len(first) == 1
        first[0].status = 'sent'
        db.session.commit()
        second = DunningService.check_overdue_accounts()
        assert second == []

    def test_recent_debts_are_skipped(self, db, test_sale):
        letters = DunningService.check_overdue_accounts()
        assert letters == []
        summary = DunningService.get_overdue_summary()
        assert summary['count'] == 1
        assert summary['total_overdue'] == 100.0


class TestRecurringExpenseService:
    def test_process_due_expenses_advances_template_only_when_due(self, db, owner_user):
        cat = ExpenseCategory(name='إيجار شهري')
        db.session.add(cat)
        db.session.flush()
        due_tpl = RecurringExpense(name='إيجار المعرض', category_id=cat.id,
                                   amount=Decimal('500'), currency='AED',
                                   payment_method='bank_transfer', frequency='monthly',
                                   next_due_date=date.today() - timedelta(days=1), is_active=True)
        inactive_tpl = RecurringExpense(name='اشتراك موقوف', category_id=cat.id,
                                        amount=Decimal('99'), currency='AED',
                                        payment_method='cash', frequency='monthly',
                                        next_due_date=date.today(), is_active=False)
        future_tpl = RecurringExpense(name='رسوم سنوية', category_id=cat.id,
                                      amount=Decimal('1200'), currency='AED',
                                      payment_method='bank_transfer', frequency='annual',
                                      next_due_date=date.today() + timedelta(days=30), is_active=True)
        db.session.add_all([cat, due_tpl, inactive_tpl, future_tpl])
        db.session.commit()

        created = RecurringExpenseService.process_due_expenses()
        assert len(created) == 1
        exp = created[0]
        assert isinstance(exp, Expense)
        assert exp.description == '[دوري] إيجار المعرض'
        assert exp.amount == Decimal('500')
        db.session.expire_all()
        tpl = db.session.get(RecurringExpense, due_tpl.id)
        assert tpl.last_generated_date == date.today()
        expected_next = (date.today() - timedelta(days=1)) + timedelta(days=30)
        assert tpl.next_due_date == expected_next


class TestEInvoiceService:
    def test_create_einvoice_builds_payloads(self, db, test_sale):
        test_sale.subtotal = Decimal('100')
        test_sale.tax_amount = Decimal('0')
        db.session.commit()

        einv = EInvoiceService.create_einvoice(test_sale.id)
        assert isinstance(einv, EInvoice)
        assert einv.invoice_number == f"EI-{test_sale.sale_number}"
        assert test_sale.sale_number in einv.uuid
        assert einv.buyer_name == 'Test Customer'
        assert einv.total_with_tax == Decimal('100.000')
        payload = json.loads(einv.json_payload)
        assert payload['invoice_number'] == einv.invoice_number
        assert payload['total_amount'] == 100.0
        assert len(payload['lines']) == 1
        assert einv.xml_payload.startswith('<Invoice')


BALANCED_LINES = [
    {'account_code': '1110', 'debit': 300, 'credit': 0, 'description': 'تحصيل نقدي'},
    {'account_code': '4100', 'debit': 0, 'credit': 300, 'description': 'إيراد'},
]


@pytest.fixture
def posted_entry(db, gl, owner_user):
    entry = AdvancedJournalEntryManager.create_entry_with_validation(
        description='قيد مرحل', lines=BALANCED_LINES, created_by=owner_user.id)
    db.session.commit()
    return entry


@pytest.fixture
def draft_entry(db, gl, owner_user):
    entry = AdvancedJournalEntryManager.create_entry_with_validation(
        description='قيد مبدئي', lines=BALANCED_LINES, created_by=owner_user.id)
    entry.is_posted = False
    db.session.commit()
    return entry


class TestAdvancedJournalManagerCreation:
    def test_validated_entry_created_with_audit(self, db, gl, owner_user):
        entry = AdvancedJournalEntryManager.create_entry_with_validation(
            description='قيد تسوية يدوي', lines=BALANCED_LINES,
            notes='ملاحظة', created_by=owner_user.id)
        assert entry.entry_type == 'manual'
        assert entry.is_posted is True
        assert float(entry.total_debit) == 300.0
        assert float(entry.total_credit) == 300.0
        audits = JournalEntryAudit.query.filter_by(journal_entry_id=entry.id, action='create').all()
        assert len(audits) == 1
        assert audits[0].performed_by == owner_user.id
        d = entry.to_dict()
        assert d['entry_number'] == entry.entry_number
        assert {item['account_code'] for item in d['lines']} == {'1110', '4100'}

    def test_unbalanced_entry_rejected(self, db, gl, owner_user):
        with pytest.raises(ValueError, match='غير متوازن'):
            AdvancedJournalEntryManager.create_entry_with_validation(
                description='قيد خاطئ',
                lines=[{'account_code': '1110', 'debit': 100, 'credit': 0},
                       {'account_code': '4100', 'debit': 0, 'credit': 90}],
                created_by=owner_user.id)

    def test_header_account_rejected(self, db, gl, owner_user):
        with pytest.raises(ValueError, match='الرئيسي'):
            AdvancedJournalEntryManager.create_entry_with_validation(
                description='قيد على حساب رئيسي',
                lines=[{'account_code': '1000', 'debit': 10, 'credit': 0},
                       {'account_code': '1110', 'debit': 0, 'credit': 10}],
                created_by=owner_user.id)

    def test_unknown_account_rejected(self, db, gl, owner_user):
        with pytest.raises(ValueError, match='9999'):
            AdvancedJournalEntryManager.create_entry_with_validation(
                description='حساب غير موجود',
                lines=[{'account_code': '9999', 'debit': 10, 'credit': 0},
                       {'account_code': '1110', 'debit': 0, 'credit': 10}],
                created_by=owner_user.id)


class TestAdvancedJournalManagerUpdate:
    def test_update_draft_entry_logs_audit(self, db, draft_entry, owner_user):
        updated = AdvancedJournalEntryManager.update_entry(
            draft_entry.id, {'description': 'قيد معدّل'}, owner_user.id, reason='تصحيح وصف')
        assert updated.description == 'قيد معدّل'
        audit = JournalEntryAudit.query.filter_by(
            journal_entry_id=draft_entry.id, action='update').first()
        assert audit is not None
        assert 'قيد مبدئي' in audit.old_values
        assert audit.performed_by == owner_user.id

    def test_update_posted_entry_rejected(self, db, posted_entry, owner_user):
        with pytest.raises(ValueError, match='مرحل'):
            AdvancedJournalEntryManager.update_entry(
                posted_entry.id, {'description': 'x'}, owner_user.id)

    def test_update_reversed_entry_rejected(self, db, draft_entry, owner_user):
        draft_entry.is_reversed = True
        db.session.commit()
        with pytest.raises(ValueError, match='معكوس'):
            AdvancedJournalEntryManager.update_entry(
                draft_entry.id, {'description': 'x'}, owner_user.id)

    def test_update_with_unbalanced_lines_rejected(self, db, draft_entry, owner_user):
        with pytest.raises(ValueError, match='بعد التحديث'):
            AdvancedJournalEntryManager.update_entry(
                draft_entry.id,
                {'lines': [{'account_code': '1110', 'debit': 100},
                           {'account_code': '4100', 'credit': 40}]},
                owner_user.id)

    def test_update_with_balanced_lines_replaces_lines(self, db, draft_entry, owner_user):
        updated = AdvancedJournalEntryManager.update_entry(
            draft_entry.id,
            {'lines': [{'account_code': '1120', 'debit': 120, 'description': 'بنك'},
                       {'account_code': '4100', 'credit': 120}]},
            owner_user.id, reason='إعادة تصنيف')
        assert float(updated.total_debit) == 120.0
        assert {ln.account.code for ln in updated.lines} == {'1120', '4100'}
        bank_line = next(ln for ln in updated.lines if ln.account.code == '1120')
        assert float(bank_line.debit) == 120.0
        audit = JournalEntryAudit.query.filter_by(
            journal_entry_id=draft_entry.id, action='update').count()
        assert audit == 1

    def test_update_with_unknown_line_account_rejected(self, db, draft_entry, owner_user):
        with pytest.raises(ValueError, match='7777'):
            AdvancedJournalEntryManager.update_entry(
                draft_entry.id,
                {'lines': [{'account_code': '7777', 'debit': 50},
                           {'account_code': '1110', 'credit': 50}]},
                owner_user.id)


class TestAdvancedJournalManagerReverse:
    def test_reverse_swaps_sides_and_links_entries(self, db, posted_entry, owner_user):
        reversal = AdvancedJournalEntryManager.reverse_entry_advanced(
            posted_entry.id, owner_user.id, 'خطأ في التسجيل')

        assert reversal is not None
        assert reversal.entry_type == 'reversing'
        assert 'سبب العكس' in reversal.notes and 'خطأ في التسجيل' in reversal.notes
        assert posted_entry.entry_number in reversal.description
        for line in reversal.lines:
            original = next(ln for ln in posted_entry.lines if ln.account_id == line.account_id)
            assert line.debit == original.credit
            assert line.credit == original.debit

        db.session.expire_all()
        orig = db.session.get(GLJournalEntry, posted_entry.id)
        rev = db.session.get(GLJournalEntry, reversal.id)
        assert orig.is_reversed is True
        assert orig.reversed_entry_id == rev.id
        assert rev.reversed_entry_id == orig.id
        assert JournalEntryAudit.query.filter_by(
            journal_entry_id=orig.id, action='reverse').count() == 1
        assert JournalEntryAudit.query.filter_by(
            journal_entry_id=rev.id, action='create').count() == 1

    def test_reverse_unposted_entry_rejected(self, db, draft_entry, owner_user):
        with pytest.raises(ValueError, match='غير مرحل'):
            AdvancedJournalEntryManager.reverse_entry_advanced(
                draft_entry.id, owner_user.id, 'سبب')

    def test_double_reverse_rejected(self, db, posted_entry, owner_user):
        AdvancedJournalEntryManager.reverse_entry_advanced(
            posted_entry.id, owner_user.id, 'أول عكس')
        with pytest.raises(ValueError, match='مسبقاً'):
            AdvancedJournalEntryManager.reverse_entry_advanced(
                posted_entry.id, owner_user.id, 'عكس ثانٍ')


class TestAdvancedJournalManagerDelete:
    def test_delete_draft_entry(self, db, draft_entry, owner_user):
        entry_id = draft_entry.id
        assert AdvancedJournalEntryManager.delete_entry(entry_id, owner_user.id, 'قيد زائد') is True
        assert db.session.get(GLJournalEntry, entry_id) is None
        audit = JournalEntryAudit.query.filter_by(journal_entry_id=entry_id, action='delete').first()
        assert audit is not None

    def test_delete_posted_entry_rejected(self, db, posted_entry, owner_user):
        with pytest.raises(ValueError, match='مرحل'):
            AdvancedJournalEntryManager.delete_entry(posted_entry.id, owner_user.id, 'سبب')

    def test_delete_entry_linked_to_reversal_rejected(self, db, draft_entry, posted_entry, owner_user):
        draft_entry.reversed_entry_id = posted_entry.id
        db.session.commit()
        with pytest.raises(ValueError, match='قيود عكسية مرتبطة'):
            AdvancedJournalEntryManager.delete_entry(draft_entry.id, owner_user.id, 'سبب')


class TestAdvancedJournalManagerApprove:
    def test_approve_draft_posts_entry(self, db, draft_entry, owner_user):
        approved = AdvancedJournalEntryManager.approve_entry(
            draft_entry.id, owner_user.id, approval_notes='تمت المراجعة')
        assert approved.is_posted is True
        audit = JournalEntryAudit.query.filter_by(
            journal_entry_id=draft_entry.id, action='approve').first()
        assert audit is not None
        assert 'تمت المراجعة' in audit.reason

    def test_approve_posted_entry_rejected(self, db, posted_entry, owner_user):
        with pytest.raises(ValueError, match='مرحل مسبقاً'):
            AdvancedJournalEntryManager.approve_entry(posted_entry.id, owner_user.id)

    def test_approve_unbalanced_entry_rejected(self, db, draft_entry, owner_user):
        lines = draft_entry.lines.all()
        lines[0].debit = Decimal('150')
        db.session.commit()
        with pytest.raises(ValueError, match='غير متوازن'):
            AdvancedJournalEntryManager.approve_entry(draft_entry.id, owner_user.id)


class TestAdvancedJournalManagerHelpers:
    def test_history_returns_audits_for_entry(self, db, draft_entry, owner_user):
        AdvancedJournalEntryManager.update_entry(draft_entry.id, {'notes': 'تحديث'}, owner_user.id)
        history = AdvancedJournalEntryManager.get_entry_history(draft_entry.id)
        assert len(history) == 2
        assert history[0].performed_at >= history[-1].performed_at
        assert {h.action for h in history} == {'create', 'update'}

    def test_helper_flags_and_balance_status(self, db, draft_entry, posted_entry):
        assert posted_entry.can_be_modified() is False
        assert posted_entry.can_be_reversed() is True
        assert posted_entry.can_be_deleted() is False
        assert draft_entry.can_be_modified() is True
        assert draft_entry.can_be_reversed() is False
        assert draft_entry.can_be_deleted() is True
        assert draft_entry.get_balance_status() == 'balanced'

        posted_entry.total_credit = Decimal('295')
        assert posted_entry.get_balance_status() == 'minor_imbalance'
        draft_entry.total_credit = Decimal('280')
        assert draft_entry.get_balance_status() == 'major_imbalance'

    def test_customer_fixture_still_usable_for_ledger_flow(self, db, gl, owner_user, test_customer):
        assert db.session.get(Customer, test_customer.id) is not None
        entry = AdvancedJournalEntryManager.create_entry_with_validation(
            description='تسوية ذمم', lines=[
                {'account_code': '1130', 'debit': 250, 'credit': 0},
                {'account_code': '4100', 'debit': 0, 'credit': 250},
            ], created_by=owner_user.id, reference_type='customer',
            reference_id=test_customer.id)
        assert entry.reference_type == 'customer'
        assert entry.reference_id == test_customer.id
