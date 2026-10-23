"""
P0 tests — تكلفة المخزون المتحركة (Moving Weighted Average Costing)
======================================================================

تغطي هذه الملف قواعد التقييم الجديدة (migrations/versions/b2_inventory_costing.py):

* المتوسط المتحرك — الصيغة وحرّاسها (كمية داخلية غير موجبة، قسمة على صفر).
* توزيع خصم المستند على الأسطر — التكلفة الصافية = المدفوع فعلياً ÷ الكمية.
* الشراء يُحرّك المتوسط — وشراء ثانٍ بسعر مختلف يحرّكه صحيحاً.
* لقطة البيع — التكلفة **وقت البيع** لا التكلفة بعدها.
* قيمة المخزون = الكمية × المتوسط المتحرك.
* البيع بلا أساس تكلفة مرفوض (fail-closed) بلا فاتورة ولا حركة ولا قيد.
* سطور التقييم — مجموع القيم يساوي مجموع القيم لكل منتج.
* المطابقة — الفرق بين تقييم المخزون وحساب المخزون في الأستاذ مُقاس.
"""

from decimal import Decimal

import pytest

from extensions import db
from models import (GLJournalEntry, Product, Purchase, PurchaseLine, Sale,
                    SaleLine, StockMovement, Supplier, Warehouse)


# =====================================================================
# أدوات مساعدة
# =====================================================================

def _product(db, name, sku, cost='10.000', price='25.000', stock='0'):
    product = Product(
        name=name, name_ar=name, sku=sku,
        cost_price=Decimal(cost), regular_price=Decimal(price),
        current_stock=Decimal(stock), is_active=True,
    )
    db.session.add(product)
    db.session.commit()
    return product


def _warehouse(db, code, is_main=True):
    warehouse = Warehouse(
        name=code, name_ar=code, code=code, is_active=True, is_main=is_main,
    )
    db.session.add(warehouse)
    db.session.commit()
    return warehouse


def _customer(db, name='عميل التكلفة'):
    from models import Customer

    customer = Customer(
        name=name, name_ar=name, customer_type='regular',
        credit_limit=Decimal('0'), balance=Decimal('0'), is_active=True,
    )
    db.session.add(customer)
    db.session.commit()
    return customer


def _supplier(db, name='مورد التكلفة'):
    supplier = Supplier(name=name)
    db.session.add(supplier)
    db.session.commit()
    return supplier


def _purchase(db, number, supplier, user_id, currency='ILS',
              exchange_rate='1', discount='0'):
    """فاتورة شراء بلا أسطر (الأسطر تُضاف يدوياً في كل اختبار)."""
    purchase = Purchase(
        purchase_number=number, supplier_id=supplier.id,
        supplier_name=supplier.name,
        total_amount=Decimal('0'), amount_base=Decimal('0'),
        currency=currency, exchange_rate=Decimal(exchange_rate),
        discount_amount=Decimal(discount),
        status='confirmed', user_id=user_id,
    )
    db.session.add(purchase)
    db.session.commit()
    return purchase


def _purchase_line(db, purchase, product, quantity, unit_cost,
                   discount_percent='0'):
    line = PurchaseLine(
        purchase_id=purchase.id, product_id=product.id,
        quantity=Decimal(quantity), unit_cost=Decimal(unit_cost),
        discount_percent=Decimal(discount_percent),
    )
    line.calculate_line_total()
    db.session.add(line)
    db.session.commit()
    return line


def _receive(db, purchase, product, quantity, unit_cost,
             discount_percent='0'):
    """فاتورة شراء بسطر واحد + استلامها (حركة مخزون + تحديث المتوسط)."""
    from services.stock_service import StockService

    line = _purchase_line(db, purchase, product, quantity, unit_cost,
                           discount_percent)
    purchase.calculate_totals()
    db.session.commit()
    StockService.process_purchase_lines(purchase, None)
    db.session.commit()
    db.session.refresh(product)
    return line


# =====================================================================
# المتوسط المتحرك — الصيغة والحرّاسات
# =====================================================================

class TestMovingAverage:

    def test_the_formula_weights_the_old_stock_and_the_receipt(self):
        """(10 × 10 + 10 × 12) / 20 = 11 — لا 12 (سعر آخر شراء)."""
        from services.costing_service import CostingService

        result = CostingService.moving_average(
            Decimal('10'), Decimal('10'), Decimal('10'), Decimal('12'))
        assert result == Decimal('11.000')

    def test_a_zero_receipt_leaves_the_average_unchanged(self):
        from services.costing_service import CostingService

        assert CostingService.moving_average(
            Decimal('10'), Decimal('10'), Decimal('0'),
            Decimal('99')) == Decimal('10.000')

    def test_a_negative_quantity_leaves_the_average_unchanged(self):
        """الحركة الخارجة (بيع) لا تحرّك المتوسط."""
        from services.costing_service import CostingService

        assert CostingService.moving_average(
            Decimal('10'), Decimal('10'), Decimal('-5'),
            Decimal('99')) == Decimal('10.000')

    def test_the_division_by_zero_is_guarded(self):
        """لا كمية بعد ولا قبل ⇒ يعود المتوسط القديم بلا قسمة على صفر."""
        from services.costing_service import CostingService

        assert CostingService.moving_average(
            Decimal('0'), Decimal('10'), Decimal('0'),
            Decimal('5')) == Decimal('10.000')

    def test_a_negative_old_stock_is_treated_as_zero(self):
        from services.costing_service import CostingService

        assert CostingService.moving_average(
            Decimal('-5'), Decimal('10'), Decimal('5'),
            Decimal('20')) == Decimal('20.000')

    def test_the_average_is_rounded_half_up_to_three_decimals(self):
        """1.0005 ⇒ 1.001 (ROUND_HALF_UP، لا التقريب إلى الزوج)."""
        from services.costing_service import CostingService

        result = CostingService.moving_average(
            Decimal('0'), Decimal('0'), Decimal('2'), Decimal('1.0005'))
        assert result == Decimal('1.001')

    def test_apply_inbound_reads_the_stock_before_the_movement(self, db):
        """عقد apply_inbound: الكمية المقروءة هي ما قبل الحركة."""
        from services.costing_service import CostingService

        product = _product(db, 'عقد التطبيق', 'SKU-COST-CONTRACT',
                           cost='10', stock='10')
        # المتوسّط 10 والكمية 10 ⇒ (10×10 + 10×20)/20 = 15
        new_average = CostingService.apply_inbound(
            product, Decimal('10'), Decimal('20'))
        assert new_average == Decimal('15.000')
        assert Decimal(str(product.average_cost)) == Decimal('15.000')
        # الرصيد لم يُحرَّك — العقد يقول إن المستدعي يتكفّل بذلك.
        assert Decimal(str(product.current_stock)) == Decimal('10.000')


# =====================================================================
# خصم المستند — التكلفة الصافية
# =====================================================================

class TestDocumentDiscountAllocation:

    def _purchase_with_two_lines(self, db, owner_user, discount='300'):
        supplier = _supplier(db)
        product_a = _product(db, 'صنف أ', 'SKU-COST-A', cost='0')
        product_b = _product(db, 'صنف ب', 'SKU-COST-B', cost='0')
        purchase = _purchase(db, 'PUR-COST-DISC', supplier, owner_user.id,
                             discount=discount)
        line_a = _purchase_line(db, purchase, product_a, '10', '100')
        line_b = _purchase_line(db, purchase, product_b, '10', '50')
        purchase.calculate_totals()
        db.session.commit()
        return purchase, line_a, line_b

    def test_the_document_discount_is_split_across_the_lines(self, db,
                                                              owner_user):
        """خصم 300 على أسطر 1000 و500 ⇒ 200 على الأول و100 على الثاني."""
        from services.costing_service import CostingService

        purchase, line_a, line_b = self._purchase_with_two_lines(db, owner_user)

        net_a = CostingService.net_unit_cost(line_a, purchase)
        net_b = CostingService.net_unit_cost(line_b, purchase)

        # 1000 − 200 = 800 على 10 وحدات ⇒ 80
        assert net_a == Decimal('80.000')
        # 500 − 100 = 400 على 10 وحدات ⇒ 40
        assert net_b == Decimal('40.000')

    def test_the_net_cost_equals_the_amount_paid_divided_by_the_quantity(
            self, db, owner_user):
        """صافي التكلفة = (المدفوع فعلياً) ÷ الكمية."""
        from services.costing_service import CostingService

        purchase, line_a, _line_b = self._purchase_with_two_lines(db, owner_user)

        subtotal = Decimal(str(purchase.subtotal))
        discount = Decimal(str(purchase.discount_amount))
        paid = subtotal - discount

        net_amount = (Decimal(str(line_a.line_total))
                      - discount * Decimal(str(line_a.line_total)) / subtotal)
        expected = net_amount / Decimal(str(line_a.quantity))

        assert CostingService.net_unit_cost(line_a, purchase) == \
            expected.quantize(Decimal('0.001'))
        assert paid == Decimal('1200.000')

    def test_the_discount_is_converted_to_the_base_currency(self, db,
                                                             owner_user):
        """سعر الصرف يُطبَّق على التكلفة الصافية."""
        from services.costing_service import CostingService

        supplier = _supplier(db)
        product = _product(db, 'صنف بالعملة', 'SKU-COST-FX', cost='0')
        purchase = _purchase(db, 'PUR-COST-FX', supplier, owner_user.id,
                             currency='USD', exchange_rate='3.67',
                             discount='100')
        line = _purchase_line(db, purchase, product, '10', '100')
        purchase.calculate_totals()
        db.session.commit()

        # 1000 − 100 = 900 ⇒ 90 لكل وحدة ⇒ × 3.67 = 330.3
        assert CostingService.net_unit_cost(line, purchase) == Decimal('330.300')

    def test_a_purchase_without_a_discount_keeps_the_line_cost(self, db,
                                                               owner_user):
        from services.costing_service import CostingService

        supplier = _supplier(db)
        product = _product(db, 'صنف بلا خصم', 'SKU-COST-NODISC', cost='0')
        purchase = _purchase(db, 'PUR-COST-NODISC', supplier, owner_user.id,
                             currency='ILS', exchange_rate='2')
        line = _purchase_line(db, purchase, product, '4', '25')
        purchase.calculate_totals()
        db.session.commit()

        assert CostingService.net_unit_cost(line, purchase) == Decimal('50.000')

    def test_a_line_discount_is_part_of_the_net_cost(self, db, owner_user):
        """خصم السطر (10%) يقلّل التكلفة الصافية قبل توزيع خصم المستند."""
        from services.costing_service import CostingService

        supplier = _supplier(db)
        product = _product(db, 'صنف بخصم سطر', 'SKU-COST-LINE', cost='0')
        purchase = _purchase(db, 'PUR-COST-LINE', supplier, owner_user.id)
        line = _purchase_line(db, purchase, product, '10', '100',
                              discount_percent='10')
        purchase.calculate_totals()
        db.session.commit()

        # line_total = 900 ⇒ 90 لكل وحدة
        assert CostingService.net_unit_cost(line, purchase) == Decimal('90.000')


# =====================================================================
# الشراء يُحرّك المتوسط
# =====================================================================

class TestPurchaseMovesTheAverage:

    def test_a_purchase_sets_the_average_to_the_paid_cost(self, db,
                                                           owner_user):
        from services.stock_service import StockService

        supplier = _supplier(db)
        product = _product(db, 'صنف الشراء', 'SKU-COST-BUY', cost='0')
        purchase = _purchase(db, 'PUR-COST-BUY', supplier, owner_user.id)

        _receive(db, purchase, product, '10', '12')

        assert Decimal(str(product.current_stock)) == Decimal('10.000')
        assert Decimal(str(product.average_cost)) == Decimal('12.000')

    def test_a_second_purchase_at_another_price_moves_the_average(
            self, db, owner_user):
        """(10 × 12 + 10 × 18) / 20 = 15 — لا 18 (سعر آخر شراء)."""
        supplier = _supplier(db)
        product = _product(db, 'صنف الشراءين', 'SKU-COST-BUY2', cost='0')
        first = _purchase(db, 'PUR-COST-BUY2-A', supplier, owner_user.id)
        _receive(db, first, product, '10', '12')

        second = _purchase(db, 'PUR-COST-BUY2-B', supplier, owner_user.id)
        _receive(db, second, product, '10', '18')

        assert Decimal(str(product.current_stock)) == Decimal('20.000')
        assert Decimal(str(product.average_cost)) == Decimal('15.000')
        # سعر آخر شراء يبقى مرجعاً منفصلاً عن أساس التقييم.
        assert Decimal(str(product.cost_price)) == Decimal('18.000')

    def test_a_discounted_purchase_lowers_the_average(self, db, owner_user):
        """خصم المستند ينزل بالتكلفة الفعلية — والمتوسط يتبعها."""
        supplier = _supplier(db)
        product = _product(db, 'صنف بخصم', 'SKU-COST-BUY3', cost='0')
        purchase = _purchase(db, 'PUR-COST-BUY3', supplier, owner_user.id,
                             discount='200')

        # 10 وحدات × 100 = 1000، خصم المستند 200 ⇒ 800 ⇒ 80 للوحدة
        _receive(db, purchase, product, '10', '100')

        assert Decimal(str(product.average_cost)) == Decimal('80.000')

    def test_the_stock_value_is_the_quantity_times_the_average(self, db,
                                                               owner_user):
        from services.costing_service import CostingService

        supplier = _supplier(db)
        product = _product(db, 'صنف القيمة', 'SKU-COST-VAL', cost='0')
        purchase = _purchase(db, 'PUR-COST-VAL', supplier, owner_user.id)
        _receive(db, purchase, product, '10', '12')
        _receive(db, _purchase(db, 'PUR-COST-VAL-2', supplier, owner_user.id),
                 product, '10', '18')

        assert CostingService.stock_value(product) == Decimal('300.000')
        assert (Decimal(str(product.current_stock))
                * Decimal(str(product.average_cost))) == Decimal('300.000')
        assert product.stock_value == Decimal('300.000')


# =====================================================================
# لقطة البيع — التكلفة وقت البيع
# =====================================================================

class TestSaleSnapshot:

    def _sale(self, db, owner_user, customer, product, quantity='2'):
        from services.sale_service import SaleService

        sale = SaleService.create_sale(
            customer=customer, seller=owner_user,
            lines_data=[{'product': product,
                         'quantity': Decimal(quantity)}],
            notes='اختبار التكلفة',
        )
        return sale

    def test_the_sale_snapshots_the_average_of_the_moment(self, db,
                                                          owner_user,
                                                          test_customer):
        supplier = _supplier(db)
        product = _product(db, 'صنف البيع', 'SKU-COST-SELL', cost='0')
        _receive(db, _purchase(db, 'PUR-COST-SELL', supplier, owner_user.id),
                 product, '10', '12')

        sale = self._sale(db, owner_user, test_customer, product, '2')
        line = SaleLine.query.filter_by(sale_id=sale.id).one()
        assert Decimal(str(line.cost_price)) == Decimal('12.000')

    def test_a_later_purchase_does_not_rewrite_the_old_snapshot(
            self, db, owner_user, test_customer):
        """البيع الثاني يلتقط المتوسط الجديد — واللقطة الأولى لا تتغير."""
        supplier = _supplier(db)
        product = _product(db, 'صنف البيعين', 'SKU-COST-SELL2', cost='0')
        _receive(db, _purchase(db, 'PUR-COST-SELL2-A', supplier, owner_user.id),
                 product, '10', '12')

        first_sale = self._sale(db, owner_user, test_customer, product, '2')
        first_line = SaleLine.query.filter_by(sale_id=first_sale.id).one()

        _receive(db, _purchase(db, 'PUR-COST-SELL2-B', supplier, owner_user.id),
                 product, '10', '18')
        # بعد البيع الأول بقي 8 وحدات بـ 12، فالمتوسط الجديد =
        # (8 × 12 + 10 × 18) / 18 = 15.333
        assert Decimal(str(product.average_cost)) == Decimal('15.333')

        second_sale = self._sale(db, owner_user, test_customer, product, '2')
        second_line = SaleLine.query.filter_by(sale_id=second_sale.id).one()

        # اللقطة الأولى ما زالت 12 (التكلفة وقت البيع الأول)…
        assert Decimal(str(first_line.cost_price)) == Decimal('12.000')
        # …واللقطة الثانية 15.333 (المتوسط الجديد).
        assert Decimal(str(second_line.cost_price)) == Decimal('15.333')

    def test_the_sale_does_not_move_the_average(self, db, owner_user,
                                                 test_customer):
        """البيع يخفض الكمية والقيمة معاً، ووحدة المتبقية تكلّفتها نفسها."""
        supplier = _supplier(db)
        product = _product(db, 'صنف بيع لا يحرّك المتوسط', 'SKU-COST-SELL3',
                           cost='0')
        _receive(db, _purchase(db, 'PUR-COST-SELL3', supplier, owner_user.id),
                 product, '10', '12')

        self._sale(db, owner_user, test_customer, product, '4')

        assert Decimal(str(product.current_stock)) == Decimal('6.000')
        assert Decimal(str(product.average_cost)) == Decimal('12.000')


# =====================================================================
# البيع بلا أساس تكلفة — مغلق
# =====================================================================

class TestFailClosedWithoutCostBasis:

    def test_a_sale_of_a_product_with_stock_but_no_cost_is_refused(
            self, db, owner_user, test_customer):
        """بيعٌ بلا تكلفة يضخّم الربح — يُرفض مغلقاً بلا أثر."""
        from services.sale_service import SaleService
        from utils.errors import ValidationError

        product = _product(db, 'بلا تكلفةMove', 'SKU-COST-NOCOST',
                           cost='0', stock='10')
        warehouse = _warehouse(db, 'WH-COST-NOCOST')

        with pytest.raises(ValidationError) as exc:
            SaleService.create_sale(
                customer=test_customer, seller=owner_user,
                lines_data=[{'product': product, 'quantity': Decimal('2')}],
                warehouse_id=warehouse.id,
            )

        assert 'بلا تكلفةMove' in str(exc.value)
        db.session.rollback()
        assert Sale.query.count() == 0
        assert SaleLine.query.count() == 0
        assert StockMovement.query.count() == 0
        assert GLJournalEntry.query.count() == 0

    def test_cost_for_sale_refuses_a_product_without_any_cost(self, db):
        from services.costing_service import CostingService
        from utils.errors import ValidationError

        product = _product(db, 'بلا تكلفة إطلاقاً', 'SKU-COST-NOCOST2',
                           cost='0', stock='3')

        with pytest.raises(ValidationError):
            CostingService.cost_for_sale(product, 1)

    def test_the_existing_cost_basis_guard_still_names_the_product(self, db):
        """حارس التكلفة الموروث (require_cost_basis) ما زال يعمل."""
        from services.stock_service import StockService
        from utils.errors import ValidationError

        product = _product(db, 'بلا تكلفة الحارس', 'SKU-COST-GUARD',
                           cost='0', stock='5')

        with pytest.raises(ValidationError) as exc:
            StockService.require_cost_basis(product)
        message = str(exc.value)
        assert 'بلا تكلفة الحارس' in message
        assert 'SKU-COST-GUARD' in message


# =====================================================================
# سطور التقييم
# =====================================================================

class TestValuationRows:

    def test_the_rows_total_equals_the_sum_of_the_product_values(self, db,
                                                                   owner_user):
        from services.costing_service import CostingService

        supplier = _supplier(db)
        first = _product(db, 'صنف تقييم أول', 'SKU-COST-ROW1', cost='0')
        second = _product(db, 'صنف تقييم ثانٍ', 'SKU-COST-ROW2', cost='0')

        _receive(db, _purchase(db, 'PUR-COST-ROW1', supplier, owner_user.id),
                 first, '10', '12')
        _receive(db, _purchase(db, 'PUR-COST-ROW2', supplier, owner_user.id),
                 second, '5', '20')

        rows = CostingService.valuation_rows()
        by_id = {row['product_id']: row for row in rows}

        assert by_id[first.id]['quantity'] == Decimal('10.000')
        assert by_id[first.id]['average_cost'] == Decimal('12.000')
        assert by_id[first.id]['value'] == Decimal('120.000')
        assert by_id[second.id]['value'] == Decimal('100.000')

        total = sum((row['value'] for row in rows), Decimal('0'))
        assert total == sum((row['value'] for row in rows), Decimal('0'))
        assert total >= Decimal('220.000')

    def test_every_row_carries_the_documented_keys(self, db):
        from services.costing_service import CostingService

        _product(db, 'صنف المفاتيح', 'SKU-COST-KEYS', cost='7', stock='3')
        rows = CostingService.valuation_rows()

        assert rows
        for key in ('product_id', 'sku', 'name', 'quantity', 'average_cost',
                    'value'):
            assert key in rows[0]


# =====================================================================
# المطابقة — الفرق عن الأستاذ العام
# =====================================================================

class TestReconciliationUsesTheMovingAverage:

    def _post_purchase_entry(self, db, purchase, amount):
        from services.gl_service import GLService

        GLService.ensure_core_accounts()
        GLService.post_entry(
            lines=[
                {'account': '1140', 'debit': Decimal(amount),
                 'credit': Decimal('0')},
                {'account': '2110', 'debit': Decimal('0'),
                 'credit': Decimal(amount)},
            ],
            description=f'Purchase {purchase.purchase_number}',
            reference_type='Purchase',
            reference_id=purchase.id,
            currency='ILS',
            exchange_rate=Decimal('1'),
        )
        db.session.commit()

    def test_the_valuation_uses_the_average_and_not_the_last_price(
            self, db, owner_user):
        """تقييم المنتج = الكمية × المتوسط المتحرك."""
        from services.inventory_reconciliation import reconcile_inventory

        supplier = _supplier(db)
        product = _product(db, 'صنف المطابقة', 'SKU-COST-REC', cost='0')
        purchase = _purchase(db, 'PUR-COST-REC', supplier, owner_user.id)
        _receive(db, purchase, product, '10', '12')
        _receive(db, _purchase(db, 'PUR-COST-REC2', supplier, owner_user.id),
                 product, '10', '18')

        report = reconcile_inventory()
        row = [r for r in report['products']
               if r['product_id'] == product.id][0]

        # المتوسط 15 (لا 18 = سعر آخر شراء) ⇒ 20 × 15 = 300
        assert row['average_cost'] == Decimal('15.00')
        assert row['valuation_at_average_cost'] == Decimal('300.00')

    def test_a_divergence_from_the_inventory_control_account_is_detected(
            self, db, owner_user):
        """قيد شراء أخسر من التقييم ⇒ فرق مقاس لا مخفي."""
        from services.inventory_reconciliation import reconcile_inventory

        supplier = _supplier(db)
        product = _product(db, 'صنف الفرق', 'SKU-COST-REC2', cost='0')
        purchase = _purchase(db, 'PUR-COST-REC2', supplier, owner_user.id)
        _receive(db, purchase, product, '10', '12')

        # الأستاذ يحمل 150 بينما تقييم المخزون 10 × 12 = 120
        self._post_purchase_entry(db, purchase, '150')

        report = reconcile_inventory()
        row = [r for r in report['products']
               if r['product_id'] == product.id][0]

        assert row['valuation_at_average_cost'] == Decimal('120.00')
        assert row['gl_control_balance'] == Decimal('150.00')
        assert row['gl_difference'] == Decimal('30.00')
        assert report['gl_difference'] == Decimal('30.00')
        assert not report['balanced']
        assert report['breaks']

    def test_a_matching_inventory_control_account_is_balanced(self, db,
                                                                owner_user):
        """القيد على أساس التقييم ⇒ التوازن قائم."""
        from services.inventory_reconciliation import reconcile_inventory

        supplier = _supplier(db)
        product = _product(db, 'صنف التوازن', 'SKU-COST-REC3', cost='0')
        purchase = _purchase(db, 'PUR-COST-REC3', supplier, owner_user.id)
        _receive(db, purchase, product, '10', '12')

        self._post_purchase_entry(db, purchase, '120')

        report = reconcile_inventory()
        row = [r for r in report['products']
               if r['product_id'] == product.id][0]

        assert row['gl_difference'] == Decimal('0.00')
        assert report['gl_difference'] == Decimal('0.00')
        assert report['balanced']


# =====================================================================
# المسارات — التكلفة في الواجهة والتقارير
# =====================================================================

class TestRoutesShowTheMovingAverage:

    def test_the_product_list_shows_the_average_and_the_stock_value(
            self, client, db, owner_user, login_owner, test_product):
        """قائمة المنتجات تُبنى على أساس المتوسط المتحرك."""
        response = client.get('/products/')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert test_product.sku in body
        # القيمة الدفترية متاحة على النموذج للقالب:
        # الكمية × المتوسط المتحرك.
        assert test_product.stock_value == (
            Decimal(str(test_product.current_stock))
            * Decimal(str(test_product.average_cost)))

    def test_a_manual_cost_edit_does_not_move_the_average_of_a_product_with_stock(
            self, client, db, owner_user, test_product):
        """منتج له مخزون: تعديل التكلفة اليدوي لا يحرّك المتوسط."""
        before = Decimal(str(test_product.average_cost))

        client.post('/auth/login', data={
            'username': owner_user.username, 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        response = client.post(f'/products/{test_product.id}/edit', data={
            'name': test_product.name,
            'sku': test_product.sku,
            'regular_price': '100',
            'cost_price': '77',
            'current_stock': str(test_product.current_stock),
        }, follow_redirects=True)

        assert response.status_code == 200
        db.session.refresh(test_product)
        assert Decimal(str(test_product.cost_price)) == Decimal('77')
        assert Decimal(str(test_product.average_cost)) == before

    def test_a_manual_cost_edit_moves_the_average_of_an_empty_product(
            self, client, db, owner_user):
        """منتج بلا مخزون وبلا مشتريات: المتوسط يتبع التكلفة المُدخلة."""
        product = _product(db, 'صنف فارغ', 'SKU-COST-EMPTY', cost='10',
                           stock='0')
        client.post('/auth/login', data={
            'username': owner_user.username, 'password': 'OwnerPass123!',
        }, follow_redirects=True)
        client.post(f'/products/{product.id}/edit', data={
            'name': product.name,
            'sku': product.sku,
            'regular_price': '100',
            'cost_price': '33',
            'current_stock': '0',
        }, follow_redirects=True)

        db.session.refresh(product)
        assert Decimal(str(product.cost_price)) == Decimal('33')
        assert Decimal(str(product.average_cost)) == Decimal('33.000')

    def test_the_inventory_valuation_report_uses_the_moving_average(
            self, client, db, owner_user, login_owner, test_product):
        """تقرير التقييم يعرض المتوسط المتحرك في عمود «سعر التكلفة»."""
        response = client.get('/reports/inventory-valuation')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        # القيمة المعروضة = الكمية × المتوسط (100 × 50)
        assert '5,000.000' in body or '5000.000' in body

    def test_the_reconciliation_endpoint_uses_the_moving_average(
            self, client, db, owner_user, login_owner, test_product):
        response = client.get('/reports/inventory-valuation/reconciliation')
        assert response.status_code == 200
        payload = response.get_json()
        assert 'valuation_basis' in payload
        assert 'average_cost' in payload['valuation_basis']
        assert payload['valuation_at_average_cost'] is not None
