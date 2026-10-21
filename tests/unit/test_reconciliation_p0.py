"""
Reconciliation P0 — مطابقة الذمم والتقارير مع مصدر الحقيقة الواحد
=====================================================================

يغطّي هذا الملف الإصلاحات P0:

  F1: services/subledger_reconciliation.py صار يستعمل
      models.customer.derive_customer_balance و
      models.supplier.derive_supplier_totals — نفس مصدر التطبيق — بدل
      صيغته الخاصة التي كانت تُنتج فرقاً دائماً.
  F2: services/aging_analysis_service.py صار ي mirroring سياسة
      routes/ledger.py::_receivables_aging (نفس الفلاتر والشرائح).
  F3: التقارير (كشف حساب العميل + تقرير المشتريات) تستبعد المستندات
      المؤرشفة (ArchivedRecord).
  F4: كل تصدير تقرير يكتب صفاً في سجل التدقيق (action='export').

كل المبالغ Decimal — لا حسابات بمؤشرات عائمة أبداً.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from extensions import db
from models import (ArchivedRecord, AuditLog, Cheque, Customer, Payment,
                    ProductReturn, Purchase, Receipt, Sale, Supplier)
from services.aging_analysis_service import AgingAnalysisService
from services.gl_service import GLService
from services.subledger_reconciliation import SubLedgerReconciliation


# ─────────────────────────── helpers ───────────────────────────

def _post(dr_code, cr_code, amount, description='reconciliation-p0'):
    """Post one balanced GL pair (flush only; caller commits)."""
    GLService.ensure_core_accounts()
    amount = Decimal(str(amount))
    GLService.post_entry(
        [
            {'account': dr_code, 'debit': amount},
            {'account': cr_code, 'credit': amount},
        ],
        description=description,
        currency='ILS',
        exchange_rate=1,
    )


def _make_sale(customer_id, seller_id, number, amount, paid_base='0',
               status='confirmed', is_active=True, days_ago=0):
    amount_d = Decimal(str(amount))
    paid_d = Decimal(str(paid_base))
    return Sale(
        sale_number=number,
        customer_id=customer_id,
        seller_id=seller_id,
        total_amount=amount_d,
        amount_base=amount_d,
        paid_amount=paid_d,
        paid_amount_base=paid_d,
        balance_due=amount_d - paid_d,
        currency='ILS',
        exchange_rate=Decimal('1'),
        payment_status='partial' if paid_d > 0 else 'unpaid',
        status=status,
        is_active=is_active,
        sale_date=datetime.now() - timedelta(days=days_ago),
    )


def _make_receipt(customer_id, sale_id, number, amount, confirmed=True):
    amount_d = Decimal(str(amount))
    return Receipt(
        receipt_number=number,
        source_type='sale',
        source_id=sale_id,
        sale_id=sale_id,
        direction='incoming',
        customer_id=customer_id,
        amount=amount_d,
        currency='ILS',
        exchange_rate=Decimal('1'),
        amount_base=amount_d,
        payment_method='cash',
        payment_confirmed=confirmed,
    )


def _item(report, code):
    """بند التسوية بالرمز من تقرير المطابقة."""
    for entry in report.get('reconciling_items', []):
        if entry['code'] == code:
            return entry
    return None


# ═════════════════════════ AR — المصدر الواحد ═════════════════════════

class TestARReconciliationUsesSingleSource:

    def test_ar_matches_derive_customer_balance_with_opening_return_and_receipt(
            self, db, owner_user, test_customer):
        """عميل برصيد افتتاحي ومرتجع معتمد وقبض جزئي:
        رصيد المطابقة = derive_customer_balance بالضبط."""
        from models.customer import derive_customer_balance, recompute_customer_balance

        # رصيد افتتاحي مُرحَّل (100 × 1)
        test_customer.opening_balance = Decimal('100')
        test_customer.opening_balance_currency = 'ILS'
        test_customer.opening_balance_rate = Decimal('1')
        test_customer.opening_balance_date = date(2024, 1, 1)
        db.session.commit()

        sale = _make_sale(test_customer.id, owner_user.id, 'S-P0-AR-001', 500)
        db.session.add(sale)
        db.session.commit()

        # قبض جزئي (200) موزَّع على الفاتورة
        receipt = _make_receipt(test_customer.id, sale.id, 'RCV-P0-AR-001', 200)
        db.session.add(receipt)
        db.session.flush()
        from services.payment_service import PaymentService
        PaymentService.apply_allocation_to_sale(
            sale=sale, receipt=receipt,
            allocated_amount=Decimal('200'), allocated_base=Decimal('200'))
        db.session.commit()

        # مرتجع معتمد (30)
        product_return = ProductReturn(
            return_number='RET-P0-AR-001',
            sale_id=sale.id,
            customer_id=test_customer.id,
            total_amount=Decimal('30'),
            refund_amount=Decimal('30'),
            currency='ILS',
            exchange_rate=Decimal('1'),
            amount_base=Decimal('30'),
            status='approved',
        )
        db.session.add(product_return)
        db.session.commit()

        # مزامنة عمود الرصيد (كما يفعل التطبيق بعد كل كتابة)
        recompute_customer_balance(test_customer.id)
        db.session.commit()

        expected = derive_customer_balance(test_customer.id)
        # 100 (افتتاحي) + (500 − 200) − 30 (مرتجع معتمد) = 370
        assert expected == Decimal('370.000')

        report = SubLedgerReconciliation.reconcile_receivables()

        assert report['section'] == 'AR'
        assert report['subledger_sum'] == Decimal('370.00')
        assert report['column_sum'] == Decimal('370.00')
        assert report['breaks'] == []

        # مطابقة الكيان نفسه مع المصدر الوحيد
        expected_by_entity = {
            b['entity_id']: b['expected'] for b in report['breaks']
        }
        assert expected_by_entity.get(test_customer.id) is None

    def test_ar_reconciling_item_covers_opening_balance(self, db, owner_user, test_customer):
        """الرصيد الافتتاحي ليس قيداً في الأستاذ ⇒ بند تسوية لا كسر."""
        test_customer.opening_balance = Decimal('100')
        test_customer.opening_balance_rate = Decimal('1')
        db.session.commit()

        sale = _make_sale(test_customer.id, owner_user.id, 'S-P0-AR-002', 200)
        db.session.add(sale)
        db.session.commit()

        # قيد الفاتورة فقط (200) — لا قيد للافتتاحي
        _post('1130', '4100', 200)
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        opening = _item(report, 'opening_balances')
        assert opening is not None
        assert opening['amount'] == Decimal('100.00')
        assert opening['sign'] == 1

        # الفرق كله مفهوم (الرصيد الافتتاحي) ⇒ لا كسر
        assert report['control_difference'] == Decimal('-100.00')
        assert report['adjusted_control_difference'] == Decimal('0.00')
        assert report['breaks'] == []
        assert report['balanced'] is True


# ═════════════════════════ AP — المصدر الواحد ═════════════════════════

class TestAPReconciliationUsesSingleSource:

    def test_ap_matches_derive_supplier_totals(self, db, owner_user):
        """مورد برصيد افتتاحي + دفعة على مستوى المورد:
        رصيد المطابقة = derive_supplier_totals + الرصيد الافتتاحي."""
        from models.supplier import derive_supplier_totals

        supplier = Supplier(
            name='P0 Supplier',
            is_active=True,
            opening_balance=Decimal('50'),
            opening_balance_currency='ILS',
            opening_balance_rate=Decimal('1'),
        )
        db.session.add(supplier)
        db.session.flush()

        purchase = Purchase(
            purchase_number='P-P0-AP-001',
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            total_amount=Decimal('400'),
            amount_base=Decimal('400'),
            paid_amount=Decimal('150'),
            payment_status='partial',
            status='confirmed',
            currency='ILS',
            exchange_rate=Decimal('1'),
            user_id=owner_user.id,
        )
        db.session.add(purchase)
        db.session.commit()

        # دفعة على مستوى المورد (بلا purchase_id) — تُحتسب ضمن المسدّد
        payment = Payment(
            payment_number='PAY-P0-AP-001',
            payment_type='payment',
            direction='outgoing',
            supplier_id=supplier.id,
            amount=Decimal('30'),
            currency='ILS',
            exchange_rate=Decimal('1'),
            amount_base=Decimal('30'),
            payment_method='cash',
            payment_confirmed=True,
        )
        db.session.add(payment)
        db.session.commit()

        total_purchases, total_paid = derive_supplier_totals(supplier.id)
        assert total_purchases == Decimal('400.000')
        assert total_paid == Decimal('180.000')

        report = SubLedgerReconciliation.reconcile_payables()

        assert report['section'] == 'AP'
        # 400 − 180 + 50 (افتتاحي) = 270
        assert report['subledger_sum'] == Decimal('270.00')
        assert report['column_sum'] == Decimal('270.00')
        assert report['breaks'] == []

    def test_ap_reconciling_item_covers_opening_balance(self, db, owner_user):
        """الرصيد الافتتاحي للمورد بند تسوية لا كسر."""
        supplier = Supplier(
            name='P0 Supplier B',
            is_active=True,
            opening_balance=Decimal('75'),
            opening_balance_rate=Decimal('1'),
        )
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            purchase_number='P-P0-AP-002',
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            total_amount=Decimal('300'),
            amount_base=Decimal('300'),
            paid_amount=Decimal('0'),
            payment_status='unpaid',
            status='confirmed',
            currency='ILS',
            exchange_rate=Decimal('1'),
            user_id=owner_user.id,
        )
        db.session.add(purchase)
        db.session.commit()

        _post('1140', '2110', 300)
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_payables()

        opening = _item(report, 'opening_balances')
        assert opening is not None
        assert opening['amount'] == Decimal('75.00')
        assert report['breaks'] == []
        assert report['balanced'] is True


# ═════════════════ شيك وارد معلّق — بند تسوية لا كسر ═════════════════

class TestPendingChequeIsReconcilingItem:

    def test_pending_incoming_cheque_is_reconciling_item_not_break(
            self, db, owner_user, test_customer):
        """الشيك المعلّق: الأستاذ يقيّد الدائن والفاتورة تبقى مفتوحة ⇒
        الفرق بند تسوية معروف وليس كسراً."""
        sale = _make_sale(test_customer.id, owner_user.id, 'S-P0-CHQ-001', 100)
        db.session.add(sale)
        db.session.commit()

        # قيد الفاتورة
        _post('1130', '4100', 100)
        db.session.commit()

        # شيك وارد معلّق: قيد الاستلام (مدين 1150 / دائن 1130) والفاتورة
        # تبقى مفتوحة لأن السند غير مؤكَّد.
        cheque = Cheque(
            cheque_number='CHQ-P0-001',
            cheque_bank_number='BANK-P0-001',
            cheque_type='incoming',
            bank_name='Test Bank',
            amount=Decimal('100'),
            currency='ILS',
            exchange_rate=Decimal('1'),
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            status='pending',
            customer_id=test_customer.id,
            user_id=owner_user.id,
        )
        cheque.calculate_amount_base()
        db.session.add(cheque)
        db.session.flush()
        cheque.receive_cheque()   # posts the under-collection transfer
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        pending = _item(report, 'pending_incoming_cheques')
        assert pending is not None
        assert pending['amount'] == Decimal('100.00')
        assert pending['sign'] == 1

        # لا كسر على مستوى الكيان (العمود مطابق للمصدر الواحد)
        assert report['breaks'] == []
        # الفرق كله مفهوم ⇒ متوازن
        assert report['control_difference'] == Decimal('-100.00')
        assert report['adjusted_control_difference'] == Decimal('0.00')
        assert report['balanced'] is True

    def test_confirmed_cheque_is_not_a_reconciling_item(self, db, owner_user, test_customer):
        """شيك مصروف/مؤكَّد ليس بند تسوية."""
        cheque = Cheque(
            cheque_number='CHQ-P0-002',
            cheque_bank_number='BANK-P0-002',
            cheque_type='incoming',
            bank_name='Test Bank',
            amount=Decimal('50'),
            currency='ILS',
            exchange_rate=Decimal('1'),
            issue_date=date.today(),
            due_date=date.today(),
            status='cleared',
            customer_id=test_customer.id,
            user_id=owner_user.id,
        )
        cheque.calculate_amount_base()
        db.session.add(cheque)
        db.session.flush()
        cheque.receive_cheque()
        db.session.commit()

        report = SubLedgerReconciliation.reconcile_receivables()

        pending = _item(report, 'pending_incoming_cheques')
        assert pending is not None
        assert pending['amount'] == Decimal('0.00')


# ═════════════════════ المستندات المؤرشفة (F3) ═════════════════════

class TestArchivedDocumentsExcluded:

    def test_archived_receipt_does_not_reduce_statement_balance(
            self, client, db, login_owner, owner_user, test_customer):
        """سند قبض مؤرشف لا يخفض رصيد كشف حساب العميل."""
        sale = _make_sale(test_customer.id, owner_user.id, 'S-P0-ARC-001', 100)
        db.session.add(sale)
        db.session.commit()

        receipt = _make_receipt(test_customer.id, sale.id, 'RCV-P0-ARC-001', 40)
        db.session.add(receipt)
        db.session.commit()

        response = client.get(f'/reports/entity_report_fragment/customer/{test_customer.id}')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        # الرصيد قبل الأرشفة: 100 − 40 = 60
        assert 'الرصيد: 60.00' in body

        # أرشفة السند (الخدمة تكتب صف ArchivedRecord ولا تقلب is_active)
        db.session.add(ArchivedRecord(
            table_name='receipts',
            record_id=receipt.id,
            data={'receipt_number': receipt.receipt_number},
            reason='test archive',
        ))
        db.session.commit()

        response = client.get(f'/reports/entity_report_fragment/customer/{test_customer.id}')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        # بعد الأرشفة: السند لا يُحتسب ⇒ الرصيد 100
        assert 'الرصيد: 100.00' in body
        assert 'الرصيد: 60.00' not in body

    def test_archived_purchase_excluded_from_purchases_report(
            self, client, db, login_owner, owner_user):
        """فاتورة شراء مؤرشفة لا تُحتسب في تقرير المشتريات."""
        supplier = Supplier(name='P0 Archived Supplier', is_active=True)
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            purchase_number='P-P0-ARCH-001',
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            total_amount=Decimal('500'),
            amount_base=Decimal('500'),
            paid_amount=Decimal('0'),
            payment_status='unpaid',
            status='confirmed',
            currency='ILS',
            exchange_rate=Decimal('1'),
            user_id=owner_user.id,
        )
        db.session.add(purchase)
        db.session.commit()

        response = client.get('/reports/purchases')
        assert response.status_code == 200
        assert 'P-P0-ARCH-001' in response.get_data(as_text=True)

        db.session.add(ArchivedRecord(
            table_name='purchases',
            record_id=purchase.id,
            data={'purchase_number': purchase.purchase_number},
            reason='test archive',
        ))
        db.session.commit()

        response = client.get('/reports/purchases')
        assert response.status_code == 200
        assert 'P-P0-ARCH-001' not in response.get_data(as_text=True)


# ═════════════════════ سياسة الأعمار (F2) ═════════════════════

class TestAgingMirrorsLedger:

    def test_aging_service_and_ledger_agree_on_buckets(self, db, owner_user, test_customer):
        """الخدمة ودفتر الأستاذ: نفس الشرائح ونفس الأرقام لنفس البيانات."""
        from routes.ledger import _receivables_aging

        db.session.add_all([
            _make_sale(test_customer.id, owner_user.id, 'S-P0-AGE-001', 100, days_ago=10),
            _make_sale(test_customer.id, owner_user.id, 'S-P0-AGE-002', 200, days_ago=45),
            _make_sale(test_customer.id, owner_user.id, 'S-P0-AGE-003', 300, days_ago=100),
            _make_sale(test_customer.id, owner_user.id, 'S-P0-AGE-004', 150, days_ago=200),
        ])
        db.session.commit()

        service = AgingAnalysisService.get_receivables_aging()
        ledger = _receivables_aging()

        for bucket in ('0-30', '31-60', '61-90', '91-120', 'over_120'):
            assert Decimal(str(service['totals'][bucket])) == ledger['buckets'][bucket], bucket

        assert Decimal(str(service['totals']['total'])) == ledger['total']

    def test_aging_service_and_ledger_agree_on_scope(self, db, owner_user, test_customer):
        """نفس النطاق: مؤكد + نشط + غير مؤرشف + الطرف نشط."""
        from routes.ledger import _receivables_aging

        db.session.add_all([
            # مسودة (غير مؤكَّدة) — تُستبعد من الطرفين
            _make_sale(test_customer.id, owner_user.id, 'S-P0-AGE-010', 400,
                       status='pending'),
            # غير نشط — يُستبعد من الطرفين
            _make_sale(test_customer.id, owner_user.id, 'S-P0-AGE-011', 500,
                       is_active=False),
        ])
        db.session.commit()

        # مؤرشف — يجب استبعاده صراحةً (الأرشفة لا تقلب is_active)
        archived_sale = _make_sale(test_customer.id, owner_user.id, 'S-P0-AGE-012', 600)
        db.session.add(archived_sale)
        db.session.commit()
        db.session.add(ArchivedRecord(
            table_name='sales',
            record_id=archived_sale.id,
            data={'sale_number': archived_sale.sale_number},
            reason='test archive',
        ))
        db.session.commit()

        service = AgingAnalysisService.get_receivables_aging()
        ledger = _receivables_aging()

        assert service['totals']['total'] == 0.0
        assert ledger['total'] == Decimal('0')
        assert service['customer_count'] == 0
        assert ledger['customer_count'] == 0

    def test_aging_service_ignores_payment_status(self, db, owner_user, test_customer):
        """الخدمة لا تعتمد على payment_status (source of truth = المبالغ)."""
        sale = _make_sale(test_customer.id, owner_user.id, 'S-P0-AGE-020', 250)
        sale.payment_status = 'paid'      # حالة قديمة لا تطابق الأرقام
        db.session.add(sale)
        db.session.commit()

        service = AgingAnalysisService.get_receivables_aging()
        assert service['totals']['total'] == 250.0


# ═════════════════════ تدقيق التصدير (F4) ═════════════════════

class TestExportAudit:

    def test_export_writes_audit_row(self, client, db, login_owner):
        """كل تصدير يكتب صفاً في سجل التدقيق باسم التقرير والصيغة."""
        before = AuditLog.query.filter_by(action='export').count()

        response = client.get('/reports/cash-flow/export?format=csv')
        assert response.status_code == 200

        after = AuditLog.query.filter_by(action='export').count()
        assert after == before + 1

        log = (AuditLog.query.filter_by(action='export')
               .order_by(AuditLog.id.desc()).first())
        assert log is not None
        assert log.table_name == 'reports'
        assert log.changes['report'] == 'cash_flow'
        assert log.changes['format'] == 'csv'
        assert log.changes['result'] == 'granted'
        assert 'date_from' in log.changes['filters']

    def test_denied_export_is_audited(self, client, db, owner_user):
        """رفض التصدير (gate التكلفة) يُدقَّق أيضاً."""
        from models import Permission, Role, User

        # بائع بصلاحية view_reports فقط (بلا view_costs)
        view_reports = Permission.query.filter_by(code='view_reports').first()
        role = Role(name='ReportsOnly', name_ar='تقارير فقط', slug='reports-only',
                    permissions=[view_reports] if view_reports else [])
        db.session.add(role)
        db.session.flush()
        user = User(username='reportsonly', email='reports@test.com',
                    full_name='Reports Only', is_owner=False, is_active=True,
                    role_id=role.id)
        user.set_password('OwnerPass123!')
        db.session.add(user)
        db.session.commit()

        client.post('/auth/login', data={
            'username': 'reportsonly', 'password': 'OwnerPass123!',
        }, follow_redirects=True)

        response = client.get('/reports/inventory-valuation/export?format=csv')
        assert response.status_code == 403

        log = (AuditLog.query.filter_by(action='export')
               .order_by(AuditLog.id.desc()).first())
        assert log is not None
        assert log.changes['report'] == 'inventory_valuation'
        assert log.changes['result'] == 'denied'


# ═════════════════════ قياس فرق التقييم عن الأستاذ (F7) ═════════════════════

class TestInventoryValuationReconciliation:

    def test_reconciliation_measurement_is_exposed(self, client, db, login_owner):
        """F7: فرق تقييم المخزون عن الأستاذ مقيس ومعروض (لا مخفي)."""
        response = client.get('/reports/inventory-valuation/reconciliation')
        assert response.status_code == 200
        payload = response.get_data(as_text=True)
        assert 'valuation_basis' in payload
        assert 'gl_difference' in payload
        assert 'control_balance' in payload

    def test_inventory_valuation_page_still_renders(self, client, db, login_owner):
        """F7: صفحة التقييم ما زالت تعمل بعد إضافة القياس."""
        response = client.get('/reports/inventory-valuation')
        assert response.status_code == 200


# ═════════════════════ قوالب الرصيد الافتتاحي وسعر الصرف (F5/F6) ═════════════════════

class TestOpeningBalanceAndRateTemplates:

    def test_customer_create_has_opening_balance_fields(self, client, db, login_owner):
        """نموذج إضافة عميل يحمل حقول الرصيد الافتتاحي بأسمائها المعتمدة."""
        response = client.get('/customers/create')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'name="opening_balance"' in body
        assert 'name="opening_balance_currency"' in body
        assert 'name="opening_balance_rate"' in body
        assert 'name="opening_balance_date"' in body

    def test_customer_edit_has_opening_balance_fields(self, client, db, login_owner, test_customer):
        response = client.get(f'/customers/{test_customer.id}/edit')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'name="opening_balance"' in body
        assert 'name="opening_balance_rate"' in body
        assert 'name="opening_balance_date"' in body

    def test_supplier_forms_have_opening_balance_and_no_initial_balance(
            self, client, db, login_owner, owner_user):
        """نموذج المورد: حقول الرصيد الافتتاحي، ولا حقل initial_balance القديم."""
        response = client.get('/suppliers/create')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'name="opening_balance"' in body
        assert 'name="opening_balance_currency"' in body
        assert 'name="opening_balance_rate"' in body
        assert 'name="opening_balance_date"' in body
        assert 'name="initial_balance"' not in body

        supplier = Supplier(name='P0 Template Supplier', is_active=True)
        db.session.add(supplier)
        db.session.commit()

        response = client.get(f'/suppliers/{supplier.id}/edit')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'name="opening_balance"' in body
        assert 'name="opening_balance_rate"' in body

    def test_supplier_view_shows_opening_balance_separately(
            self, client, db, login_owner, owner_user):
        """صفحة المورد: الرصيد الافتتاحي منفصل عن إجمالي المشتريات."""
        supplier = Supplier(
            name='P0 View Supplier', is_active=True,
            opening_balance=Decimal('120'), opening_balance_rate=Decimal('1'),
        )
        db.session.add(supplier)
        db.session.commit()

        response = client.get(f'/suppliers/{supplier.id}')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'الرصيد الافتتاحي' in body
        assert 'إجمالي المشتريات' in body

    def test_customer_view_renders_opening_balance(self, client, db, login_owner, test_customer):
        """صفحة العميل: الرصيد الافتتاحي ظاهر منفصلاً عن الرصيد."""
        test_customer.opening_balance = Decimal('90')
        test_customer.opening_balance_rate = Decimal('1')
        db.session.commit()

        response = client.get(f'/customers/{test_customer.id}')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'الرصيد الافتتاحي' in body
        assert '90.00' in body

    def test_receipt_form_exchange_rate_is_editable(
            self, client, db, login_owner, owner_user, test_customer):
        """سعر الصرف في سند القبض قابل للتعديل (لم يعد readonly)."""
        sale = _make_sale(test_customer.id, owner_user.id, 'S-P0-TPL-001', 100)
        db.session.add(sale)
        db.session.commit()

        response = client.get(f'/payments/create_from_sale/{sale.id}')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'id="exchange_rate"' in body
        # الحقل نفسه بلا readonly
        exchange_input = body.split('id="exchange_rate"')[1].split('>')[0]
        assert 'readonly' not in exchange_input
        # وتوجد دالة التحديث عند تغيير العملة
        assert 'refreshExchangeRate' in body
