"""
اختبارات P0 للخدمات (F1..F9) — tests/unit/test_services_p0.py
==============================================================

تغطي هذا الملف الإصلاحات التالية:

* F1 — لا فاتورة بلا تكلفة (منتج cost_price = 0 يُرفض)، وفحص التوفر
        واعي بالمستودع (لا بيع مخزون يجلس في مستودع آخر).
* F2 — مسار المساعد الذكي (services/ai_commands) يمرّ عبر SaleService:
        حركة مخزون + قيد إيراد + قيد تكلفة + لقطة تكلفة على سطر البيع.
* F3 — المرتجع يترك تسوية الفاتورة صحيحة عبر إعادة الاحتساب الواحدة
        (بلا تحرير يدوي لـ balance_due).
* F5 — ارتداد الشيك يحدّث رصيد العميل عبر الكاتب الوحيد
        (models/customer.recompute_customer_balance) ويتّفق معه.
* F6 — المخزون السالب يُرفض (لا يُقصّ إلى صفر) — على الإدراج وعلى
        التحديث.
* F7 — القيد غير المتوازن يُرفض بالمستمع (على مجموع سطوره لا إجماليات
        رأسه).
* F8 — PaymentService.create_refund + adjust_customer_balance.
* F4 — قائمة التدفقات النقدية تحلّ حساباتها عبر AccountResolver.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from extensions import db
from models import (AuditLog, Customer, GLAccount, GLJournalEntry, GLJournalLine,
                    Payment, Product, Sale, SaleLine, StockMovement, Warehouse)
from services.sale_service import SaleService
from utils.errors import ValidationError


# =====================================================================
# أدوات مساعدة
# =====================================================================

def _warehouse(db, code, name=None, is_main=False):
    wh = Warehouse(
        name=name or code, name_ar=name or code, code=code,
        is_active=True, is_main=is_main,
    )
    db.session.add(wh)
    db.session.commit()
    return wh


def _product(db, name, sku, cost='10.000', price='25.000', stock='0'):
    product = Product(
        name=name, name_ar=name, sku=sku,
        cost_price=Decimal(cost), regular_price=Decimal(price),
        current_stock=Decimal(stock), is_active=True,
    )
    db.session.add(product)
    db.session.commit()
    return product


def _customer(db, name='عميل P0'):
    customer = Customer(
        name=name, name_ar=name, customer_type='regular',
        credit_limit=Decimal('0'), balance=Decimal('0'), is_active=True,
    )
    db.session.add(customer)
    db.session.commit()
    return customer


def _lines(product, quantity='2', price=None):
    line = {'product': product, 'quantity': Decimal(quantity)}
    if price is not None:
        line['unit_price'] = Decimal(price)
    return [line]


# =====================================================================
# F1 — لا فاتورة بلا تكلفة
# =====================================================================

class TestZeroCostSaleIsRefused:

    def test_sale_of_a_zero_cost_product_is_refused(self, db, owner_user):
        """منتج بلا تكلفة ⇒ لا فاتورة إيراد بلا قيد تكلفة."""
        customer = _customer(db, 'عميل بلا تكلفة')
        product = _product(db, 'صنف بلا تكلفة', 'SKU-P0-ZERO',
                           cost='0', price='50', stock='10')
        warehouse = _warehouse(db, 'WH-P0-ZERO', is_main=True)

        with pytest.raises(ValidationError) as exc:
            SaleService.create_sale(
                customer=customer, seller=owner_user,
                lines_data=_lines(product, '2'),
                warehouse_id=warehouse.id,
            )

        assert 'صنف بلا تكلفة' in str(exc.value)
        assert 'SKU-P0-ZERO' in str(exc.value)

        # لا فاتورة، لا حركة مخزون، لا قيد — لا شيء على الإطلاق.
        db.session.rollback()
        assert Sale.query.count() == 0
        assert SaleLine.query.count() == 0
        assert StockMovement.query.count() == 0
        assert GLJournalEntry.query.count() == 0

    def test_a_costed_product_is_still_sold_with_a_cogs_entry(self, db, owner_user):
        """الضمان المضاد: المنتج costing الغير مباح يمرّ وينتج قيد COGS."""
        customer = _customer(db, 'عميل بتكلفة')
        product = _product(db, 'صنف بتكلفة', 'SKU-P0-COST',
                           cost='10', price='50', stock='10')
        warehouse = _warehouse(db, 'WH-P0-COST', is_main=True)

        sale = SaleService.create_sale(
            customer=customer, seller=owner_user,
            lines_data=_lines(product, '2'),
            warehouse_id=warehouse.id,
        )

        entries = GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id).all()
        cogs = [e for e in entries if e.description.startswith('COGS')]
        assert cogs, 'no COGS entry for a costed sale'
        cogs_debit = sum(Decimal(str(l.debit or 0)) for l in cogs[0].lines)
        assert cogs_debit == Decimal('20.000')  # 2 × 10 (تكلفة بالأساس)


# =====================================================================
# F1 — فحص التوفر واعي بالمستودع
# =====================================================================

class TestWarehouseAwareAvailability:

    def _stocked_product(self, db, main):
        from services.stock_service import StockService

        product = _product(db, 'صنف مستودع', 'SKU-P0-WH',
                           cost='10', price='25', stock='0')
        StockService.add_stock(product.id, Decimal('10'), warehouse_id=main.id)
        db.session.commit()
        return product

    def test_sale_cannot_draw_stock_sitting_in_another_warehouse(self, db, owner_user):
        from services.stock_service import StockService

        customer = _customer(db, 'عميل مستودع')
        main = _warehouse(db, 'WH-P0-MAIN', is_main=True)
        other = _warehouse(db, 'WH-P0-OTHER')
        product = self._stocked_product(db, main)

        with pytest.raises(ValidationError):
            SaleService.create_sale(
                customer=customer, seller=owner_user,
                lines_data=_lines(product, '2'),
                warehouse_id=other.id,
            )

        db.session.rollback()
        assert Sale.query.count() == 0
        # المخزون لم يتحرك إطلاقاً.
        assert StockService.get_warehouse_quantity(product.id, main.id) == Decimal('10')
        assert StockService.get_warehouse_quantity(product.id, other.id) == Decimal('0')

    def test_sale_from_the_owning_warehouse_is_allowed(self, db, owner_user):
        from services.stock_service import StockService

        customer = _customer(db, 'عميل مستودع صحيح')
        main = _warehouse(db, 'WH-P0-MAIN2', is_main=True)
        other = _warehouse(db, 'WH-P0-OTHER2')
        product = self._stocked_product(db, main)

        sale = SaleService.create_sale(
            customer=customer, seller=owner_user,
            lines_data=_lines(product, '2'),
            warehouse_id=main.id,
        )

        assert sale.id is not None
        assert sale.warehouse_id == main.id
        assert StockService.get_warehouse_quantity(product.id, main.id) == Decimal('8')
        assert StockService.get_warehouse_quantity(product.id, other.id) == Decimal('0')


# =====================================================================
# F2 — مسار المساعد الذكي
# =====================================================================

class TestAiCommandSalePath:

    def test_ai_sale_writes_movement_revenue_cogs_and_cost_snapshot(self, db, owner_user):
        from services import ai_commands as cmd

        customer = _customer(db, 'عميل AI')
        product = _product(db, 'صنف AI', 'SKU-P0-AI',
                           cost='10', price='25', stock='10')
        _warehouse(db, 'WH-P0-AI', is_main=True)

        sale = cmd.create_sale(customer.id, product.id, Decimal('2'), owner_user.id)

        # 1) حركة مخزون (لم تعد كتابة مباشرة على current_stock)
        moves = StockMovement.query.filter_by(product_id=product.id).all()
        assert len(moves) == 1
        assert Decimal(str(moves[0].quantity)) == Decimal('-2.000')
        db.session.refresh(product)
        assert Decimal(str(product.current_stock)) == Decimal('8.000')

        # 2) لقطة التكلفة على سطر البيع
        line = SaleLine.query.filter_by(sale_id=sale.id).one()
        assert Decimal(str(line.cost_price)) == Decimal('10.000')

        # 3) قيد إيراد + قيد تكلفة بضاعة مباعة
        entries = GLJournalEntry.query.filter_by(
            reference_type='Sale', reference_id=sale.id).all()
        revenue = [e for e in entries if e.description.startswith('Sale ')]
        cogs = [e for e in entries if e.description.startswith('COGS')]
        assert revenue, 'no revenue entry for the AI sale'
        assert cogs, 'no COGS entry for the AI sale'
        cogs_debit = sum(Decimal(str(l.debit or 0)) for l in cogs[0].lines)
        assert cogs_debit == Decimal('20.000')

    def test_ai_sale_of_a_zero_cost_product_is_refused(self, db, owner_user):
        from services import ai_commands as cmd

        customer = _customer(db, 'عميل AI بلا تكلفة')
        product = _product(db, 'صنف AI بلا تكلفة', 'SKU-P0-AI-ZERO',
                           cost='0', price='25', stock='10')

        with pytest.raises(ValidationError) as exc:
            cmd.create_sale(customer.id, product.id, Decimal('2'), owner_user.id)

        assert 'صنف AI بلا تكلفة' in str(exc.value)
        db.session.rollback()
        assert Sale.query.count() == 0
        assert StockMovement.query.count() == 0


# =====================================================================
# F3 — المرتجع وتسوية الفاتورة
# =====================================================================

class TestReturnSettlement:

    def test_return_settles_the_invoice_without_a_manual_balance_edit(self, db, owner_user):
        from models.sale import recompute_sale_settlement
        from services.return_service import ReturnService

        customer = _customer(db, 'عميل مرتجع')
        product = _product(db, 'صنف مرتجع', 'SKU-P0-RET',
                           cost='10', price='50', stock='10')
        warehouse = _warehouse(db, 'WH-P0-RET', is_main=True)

        sale = SaleService.create_sale(
            customer=customer, seller=owner_user,
            lines_data=_lines(product, '2'),
            warehouse_id=warehouse.id,
        )
        assert Decimal(str(sale.balance_due)) == Decimal('100.000')

        line = SaleLine.query.filter_by(sale_id=sale.id).one()
        ret = ReturnService.create_return(
            sale.id, [{'sale_line_id': line.id, 'quantity': Decimal('2')}],
            user_id=owner_user.id,
        )
        assert ret.refund_amount == Decimal('100.000')

        db.session.refresh(sale)
        # التسوية Fixture: الفاتورة أصبحت مسددة بالكامل.
        assert Decimal(str(sale.balance_due)) == Decimal('0.000')
        assert sale.payment_status == 'paid'

        # إعادة الاحتساب (المصدر الوحيد) لا تغيّر شيئاً ⇒ لا تحرير يدوي.
        # NOTE: يُمرَّر الاتصال صراحةً — models/sale.py يستورد `db` محلياً
        # بعد السطر 114 (UnboundLocalError عند connection=None)؛ الملف
        # خارج نطاق التعديل هنا.
        recompute_sale_settlement(sale.id, connection=db.session.connection())
        db.session.refresh(sale)
        assert Decimal(str(sale.balance_due)) == Decimal('0.000')
        assert sale.payment_status == 'paid'

        # رصيد العميل يتبع نفس الاشتقاق.
        db.session.refresh(customer)
        assert Decimal(str(customer.balance)) == Decimal('0.000')

    def test_return_of_a_partly_returned_invoice_keeps_the_remainder(self, db, owner_user):
        from services.return_service import ReturnService

        customer = _customer(db, 'عميل مرتجع جزئي')
        product = _product(db, 'صنف مرتجع جزئي', 'SKU-P0-RET2',
                           cost='10', price='50', stock='10')
        warehouse = _warehouse(db, 'WH-P0-RET2', is_main=True)

        sale = SaleService.create_sale(
            customer=customer, seller=owner_user,
            lines_data=_lines(product, '2'),
            warehouse_id=warehouse.id,
        )
        assert Decimal(str(sale.balance_due)) == Decimal('100.000')

        line = SaleLine.query.filter_by(sale_id=sale.id).one()
        ReturnService.create_return(
            sale.id, [{'sale_line_id': line.id, 'quantity': Decimal('1')}],
            user_id=owner_user.id,
        )

        db.session.refresh(sale)
        # نصف الفاتورة مُرتجَع ⇒ المتبقي 50 (لا تحرير يدوي).
        assert Decimal(str(sale.paid_amount_base)) == Decimal('0.000')
        assert Decimal(str(sale.balance_due)) == Decimal('50.000')
        assert sale.payment_status == 'unpaid'


# =====================================================================
# F5 — ارتداد الشيك
# =====================================================================

class TestChequeBounceUsesTheSingleWriter:

    def _standalone_cheque(self, db, customer, number='CHQ-P0-1', amount='100.000'):
        from models import Cheque

        cheque = Cheque(
            cheque_number=number, cheque_bank_number=number,
            cheque_type='incoming', bank_name='بنك P0',
            amount=Decimal(amount), currency='ILS', exchange_rate=Decimal('1'),
            amount_base=Decimal(amount),
            issue_date=date.today(), due_date=date.today() + timedelta(days=30),
            status='pending', customer_id=customer.id, is_active=True,
        )
        db.session.add(cheque)
        db.session.commit()
        return cheque

    def test_bounce_updates_the_balance_through_the_single_writer(self, db, owner_user):
        from models.customer import derive_customer_balance, recompute_customer_balance

        customer = _customer(db, 'عميل شيك')
        cheque = self._standalone_cheque(db, customer)

        cheque.bounce_cheque('مرتد من البنك')
        db.session.commit()

        db.session.refresh(customer)
        # الرصيد بعد الارتداد = 100 (الشيك المرتد يُعيد الدين).
        assert Decimal(str(customer.balance)) == Decimal('100.000')

        # الكاتبان يتّفقان: المخزَّن = المشتق.
        stored = Decimal(str(customer.balance))
        derived = derive_customer_balance(customer.id)
        assert stored == derived

        # إعادة الاحتساب لا تغيّر شيئاً (لا زيادة يدوية فوق المشتق).
        recompute_customer_balance(customer.id)
        db.session.refresh(customer)
        assert Decimal(str(customer.balance)) == derived

    def test_bounce_posts_the_reversal_entry(self, db, owner_user):
        customer = _customer(db, 'عميل شيك قيد')
        cheque = self._standalone_cheque(db, customer, number='CHQ-P0-2')

        cheque.bounce_cheque('مرتد من البنك')
        db.session.commit()

        entries = GLJournalEntry.query.filter_by(
            reference_type='cheque_bounce', reference_id=cheque.id).all()
        assert entries, 'no journal entry for the bounced cheque'
        entry = entries[0]
        assert Decimal(str(entry.total_debit)) == Decimal(str(entry.total_credit))


# =====================================================================
# F6 — المخزون السالب يُرفض
# =====================================================================

class TestNegativeStockIsRefused:

    def test_negative_stock_on_update_is_refused_not_truncated(self, db, owner_user):
        product = _product(db, 'صنف سالب', 'SKU-P0-NEG',
                           cost='10', price='25', stock='3')

        with pytest.raises(ValidationError) as exc:
            product.current_stock = Decimal('-7')
            db.session.commit()

        assert 'صنف سالب' in str(exc.value)
        db.session.rollback()
        db.session.refresh(product)
        # لم يُقصّ إلى صفر: الرصيد كما كان.
        assert Decimal(str(product.current_stock)) == Decimal('3.000')

    def test_negative_stock_on_insert_is_refused(self, db, owner_user):
        product = Product(
            name='صنف سالب إدراج', name_ar='صنف سالب إدراج', sku='SKU-P0-NEG2',
            cost_price=Decimal('10'), regular_price=Decimal('25'),
            current_stock=Decimal('-1'), is_active=True,
        )
        db.session.add(product)

        with pytest.raises(ValidationError) as exc:
            db.session.commit()

        assert 'صنف سالب إدراج' in str(exc.value)
        db.session.rollback()
        assert Product.query.filter_by(sku='SKU-P0-NEG2').count() == 0


# =====================================================================
# F7 — القيد غير المتوازن يُرفض
# =====================================================================

class TestUnbalancedJournalEntryIsRefused:

    def test_unbalanced_header_totals_are_refused(self, db, owner_user):
        entry = GLJournalEntry(
            entry_number='JE-P0-UNBAL', total_debit=Decimal('100.000'),
            total_credit=Decimal('90.000'),
        )
        db.session.add(entry)

        with pytest.raises(ValidationError) as exc:
            db.session.commit()

        assert 'غير متوازن' in str(exc.value)
        db.session.rollback()
        assert GLJournalEntry.query.filter_by(
            entry_number='JE-P0-UNBAL').count() == 0

    def test_balanced_header_with_unbalanced_lines_is_refused(self, db, owner_user):
        """الأهم: الرأس يدّعي التوازن والسطور لا تتوازن ⇒ يُرفض."""
        from services.gl_service import GLService

        GLService.ensure_core_accounts()
        cash = GLAccount.query.filter_by(code='1110').first()
        revenue = GLAccount.query.filter_by(code='4100').first()

        entry = GLJournalEntry(
            entry_number='JE-P0-LIES', total_debit=Decimal('100.000'),
            total_credit=Decimal('100.000'),
        )
        db.session.add(entry)
        db.session.add(GLJournalLine(
            entry=entry, account=cash, debit=Decimal('100.000'),
            credit=Decimal('0'), amount_base=Decimal('100.000'),
        ))
        db.session.add(GLJournalLine(
            entry=entry, account=revenue, debit=Decimal('0'),
            credit=Decimal('90.000'), amount_base=Decimal('90.000'),
        ))

        with pytest.raises(ValidationError) as exc:
            db.session.commit()

        assert 'غير متوازن' in str(exc.value)
        db.session.rollback()
        assert GLJournalEntry.query.filter_by(
            entry_number='JE-P0-LIES').count() == 0

    def test_a_balanced_entry_is_accepted(self, db, owner_user):
        from services.gl_service import GLService

        GLService.ensure_core_accounts()
        cash = GLAccount.query.filter_by(code='1110').first()
        revenue = GLAccount.query.filter_by(code='4100').first()

        entry = GLJournalEntry(
            entry_number='JE-P0-OK', total_debit=Decimal('100.000'),
            total_credit=Decimal('100.000'),
        )
        db.session.add(entry)
        db.session.add(GLJournalLine(
            entry=entry, account=cash, debit=Decimal('100.000'),
            credit=Decimal('0'), amount_base=Decimal('100.000'),
        ))
        db.session.add(GLJournalLine(
            entry=entry, account=revenue, debit=Decimal('0'),
            credit=Decimal('100.000'), amount_base=Decimal('100.000'),
        ))
        db.session.commit()

        assert GLJournalEntry.query.filter_by(
            entry_number='JE-P0-OK').count() == 1


# =====================================================================
# F8 — استرداد نقدي + ضبط يدوي للرصيد
# =====================================================================

class TestPaymentServiceRefundAndAdjustment:

    def test_create_refund_creates_a_real_refund_with_a_gl_entry(self, db, owner_user):
        from services.payment_service import PaymentService

        customer = _customer(db, 'عميل استرداد')
        product = _product(db, 'صنف استرداد', 'SKU-P0-REF',
                           cost='10', price='50', stock='10')
        warehouse = _warehouse(db, 'WH-P0-REF', is_main=True)

        sale = SaleService.create_sale(
            customer=customer, seller=owner_user,
            lines_data=_lines(product, '2'),
            warehouse_id=warehouse.id,
        )
        db.session.refresh(customer)
        assert Decimal(str(customer.balance)) == Decimal('100.000')

        payment = PaymentService.create_refund(
            customer=customer, amount=Decimal('30'),
            reason='استرداد نقدي', payment_method='cash',
            user_id=owner_user.id,
        )

        # سند صرف حقيقي
        assert payment.id is not None
        assert payment.direction == 'outgoing'
        assert payment.payment_type == 'refund'
        assert payment.customer_id == customer.id
        assert Decimal(str(payment.amount_base)) == Decimal('30.000')

        # قيد محاسبي (مدين ذمم مدينة / دائن صندوق)
        entry = GLJournalEntry.query.filter_by(
            reference_type='Payment', reference_id=payment.id).first()
        assert entry is not None, 'the refund has no journal entry'
        assert Decimal(str(entry.total_debit)) == Decimal('30.000')
        assert Decimal(str(entry.total_credit)) == Decimal('30.000')

        # أثر الرصيد: 100 − 30 = 70 (عبر الاشتقاق لا بالكتابة اليدوية)
        db.session.refresh(customer)
        assert Decimal(str(customer.balance)) == Decimal('70.000')

        # صف تدقيق
        audit = AuditLog.query.filter_by(
            table_name='payments', record_id=payment.id).first()
        assert audit is not None, 'the refund has no audit row'
        assert 'استرداد نقدي' in str(audit.changes)

    def test_create_refund_rejects_a_non_positive_amount(self, db, owner_user):
        from services.payment_service import PaymentService

        customer = _customer(db, 'عميل استرداد صفري')
        with pytest.raises(ValidationError):
            PaymentService.create_refund(
                customer=customer, amount=Decimal('0'), reason='بلا سبب')
        db.session.rollback()
        assert Payment.query.count() == 0

    def test_adjust_customer_balance_records_an_audited_adjustment(self, db, owner_user):
        from models.customer import derive_customer_balance
        from services.payment_service import PaymentService

        customer = _customer(db, 'عميل ضبط')
        product = _product(db, 'صنف ضبط', 'SKU-P0-ADJ',
                           cost='10', price='50', stock='10')
        warehouse = _warehouse(db, 'WH-P0-ADJ', is_main=True)

        sale = SaleService.create_sale(
            customer=customer, seller=owner_user,
            lines_data=_lines(product, '2'),
            warehouse_id=warehouse.id,
        )
        db.session.refresh(customer)
        assert Decimal(str(customer.balance)) == Decimal('100.000')

        PaymentService.adjust_customer_balance(
            customer=customer, new_balance=Decimal('40'),
            reason='تسوية يدوية بعد مراجعة', user_id=owner_user.id,
        )

        db.session.refresh(customer)
        assert Decimal(str(customer.balance)) == Decimal('40.000')

        # التعديل مسجَّل بالسبب في سجل التدقيق
        audit = AuditLog.query.filter_by(
            table_name='customers', record_id=customer.id).first()
        assert audit is not None, 'the adjustment has no audit row'
        assert 'تسوية يدوية بعد مراجعة' in str(audit.changes)

        # التعديل يبقى بعد أي إعادة اشتقاق لاحقة (لا يُمحى بصمت)
        from models.customer import recompute_customer_balance
        recompute_customer_balance(customer.id)
        db.session.refresh(customer)
        assert Decimal(str(customer.balance)) == Decimal('40.000')
        assert Decimal(str(derive_customer_balance(customer.id))) == Decimal('40.000')

    def test_adjust_customer_balance_requires_a_reason(self, db, owner_user):
        from services.payment_service import PaymentService

        customer = _customer(db, 'عميل ضبط بلا سبب')
        with pytest.raises(ValidationError):
            PaymentService.adjust_customer_balance(
                customer=customer, new_balance=Decimal('10'), reason='  ')
        db.session.rollback()
        assert AuditLog.query.filter_by(
            table_name='customers', record_id=customer.id).count() == 0


# =====================================================================
# F4 — قائمة التدفقات النقدية عبر AccountResolver
# =====================================================================

class TestCashFlowResolvesAccountsThroughTheResolver:

    def test_cash_account_codes_come_from_the_resolver(self, db, owner_user):
        from services.account_resolution import AccountResolver, AccountRole
        from services.cash_flow_service import CashFlowService

        codes = CashFlowService.cash_account_codes()
        assert codes == (
            AccountResolver.code_for(AccountRole.CASH),
            AccountResolver.code_for(AccountRole.BANK),
        )

    def test_a_remapped_cash_account_is_followed(self, db, owner_user):
        """مستأجر remap حساب الصندوق ⇒ القائمة تستعمل الكود الجديد."""
        from models.system_settings import SystemSettings
        from services.cash_flow_service import CashFlowService

        settings = SystemSettings(system_name='P0', is_active=True)
        settings.set_custom_setting('gl_role_map', {'CASH': '1121'})
        db.session.add(settings)
        db.session.commit()

        assert CashFlowService.cash_account_codes()[0] == '1121'

    def test_the_statement_uses_the_resolved_cash_account(self, db, owner_user):
        """قيد على الصندوق المُعاد ترميزه ينعكس على رصيد النقدية."""
        from datetime import datetime, timezone

        from models.system_settings import SystemSettings
        from services.cash_flow_service import CashFlowService
        from services.gl_service import GLService

        settings = SystemSettings(system_name='P0', is_active=True)
        settings.set_custom_setting('gl_role_map', {'CASH': '1121'})
        db.session.add(settings)
        db.session.commit()

        GLService.ensure_core_accounts()

        # قيد على الصندوق المُعاد ترميزه (1121) بتاريخ قبل بداية الفترة
        GLService.post_entry(
            lines=[
                {'account': '1121', 'debit': Decimal('500'), 'credit': Decimal('0')},
                {'account': '4100', 'debit': Decimal('0'), 'credit': Decimal('500')},
            ],
            description='P0 cash flow', reference_type='manual',
            entry_date=datetime.now(timezone.utc) - timedelta(days=3),
        )
        db.session.commit()

        report = CashFlowService.generate_gl_cash_flow(
            date.today() - timedelta(days=2), date.today() + timedelta(days=2))
        # رصيد النقدية الافتتاحي يشمل الحساب المُعاد ترميزه (1121) — لو
        # كان الكود ثابتاً ('1110','1120') لما ظهر الـ 500 إطلاقاً.
        assert Decimal(str(report['cash_beginning'])) == Decimal('500.000')
        assert Decimal(str(report['cash_ending'])) == Decimal('500.000')
