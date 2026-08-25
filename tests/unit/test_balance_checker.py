"""
Balance Checker Tests — Detect and repair drifted balances.

Tests the utility created to fix denormalized balance drift.
"""

from decimal import Decimal


class TestBalanceChecker:
    """Test balance consistency checker."""

    def test_no_drift_when_balances_match(self, client, db, owner_user, test_customer, test_product):
        """No drift detected when stored balance matches calculated."""
        from models import Sale, SaleLine
        from utils.helpers import generate_number
        from utils.balance_checker import check_customer_balance

        # Create sale with known amounts
        sale = Sale(
            sale_number=generate_number('S', Sale, 'sale_number'),
            customer_id=test_customer.id,
            seller_id=owner_user.id,
            total_amount=Decimal('100.000'),
            amount_base=Decimal('100.000'),
            paid_amount=Decimal('30.000'),
            paid_amount_base=Decimal('30.000'),
            balance_due=Decimal('70.000'),
            currency='AED',
            exchange_rate=Decimal('1'),
            payment_status='partial',
            status='confirmed',
            is_active=True,
        )
        db.session.add(sale)
        db.session.flush()

        line = SaleLine(
            sale_id=sale.id,
            product_id=test_product.id,
            quantity=Decimal('2'),
            unit_price=Decimal('50.000'),
            discount_percent=Decimal('0'),
            line_total=Decimal('100.000'),
            cost_price=Decimal('25.000'),
        )
        db.session.add(line)

        # Set customer balance to match calculated (100 - 30 = 70)
        test_customer.balance = Decimal('70.000')
        db.session.commit()

        drifts = check_customer_balance(test_customer.id)
        assert len(drifts) == 0

    def test_drift_detected(self, client, db, owner_user, test_customer, test_product):
        """Drift detected when stored balance differs from calculated."""
        from models import Sale, SaleLine
        from utils.helpers import generate_number
        from utils.balance_checker import check_customer_balance

        sale = Sale(
            sale_number=generate_number('S', Sale, 'sale_number'),
            customer_id=test_customer.id,
            seller_id=owner_user.id,
            total_amount=Decimal('100.000'),
            amount_base=Decimal('100.000'),
            paid_amount=Decimal('0'),
            paid_amount_base=Decimal('0'),
            balance_due=Decimal('100.000'),
            currency='AED',
            exchange_rate=Decimal('1'),
            payment_status='unpaid',
            status='confirmed',
            is_active=True,
        )
        db.session.add(sale)
        db.session.flush()

        line = SaleLine(
            sale_id=sale.id,
            product_id=test_product.id,
            quantity=Decimal('2'),
            unit_price=Decimal('50.000'),
            discount_percent=Decimal('0'),
            line_total=Decimal('100.000'),
            cost_price=Decimal('25.000'),
        )
        db.session.add(line)

        # Set customer balance to WRONG value (drift!)
        test_customer.balance = Decimal('50.000')  # Should be 100
        db.session.commit()

        drifts = check_customer_balance(test_customer.id)
        assert len(drifts) == 1
        assert drifts[0]['customer_id'] == test_customer.id
        assert drifts[0]['stored'] == 50.0
        assert drifts[0]['calculated'] == 100.0

    def test_repair_fixes_drift(self, client, db, owner_user, test_customer, test_product):
        """Repair function fixes drifted balance."""
        from models import Sale, SaleLine
        from utils.helpers import generate_number
        from utils.balance_checker import check_customer_balance, repair_customer_balance

        sale = Sale(
            sale_number=generate_number('S', Sale, 'sale_number'),
            customer_id=test_customer.id,
            seller_id=owner_user.id,
            total_amount=Decimal('200.000'),
            amount_base=Decimal('200.000'),
            paid_amount=Decimal('50.000'),
            paid_amount_base=Decimal('50.000'),
            balance_due=Decimal('150.000'),
            currency='AED',
            exchange_rate=Decimal('1'),
            payment_status='partial',
            status='confirmed',
            is_active=True,
        )
        db.session.add(sale)
        db.session.flush()

        line = SaleLine(
            sale_id=sale.id,
            product_id=test_product.id,
            quantity=Decimal('4'),
            unit_price=Decimal('50.000'),
            discount_percent=Decimal('0'),
            line_total=Decimal('200.000'),
            cost_price=Decimal('25.000'),
        )
        db.session.add(line)

        # Wrong balance
        test_customer.balance = Decimal('0')
        db.session.commit()

        # Detect drift
        drifts = check_customer_balance(test_customer.id)
        assert len(drifts) == 1

        # Repair
        repaired = repair_customer_balance(test_customer.id)
        assert repaired == 1

        # Verify
        from extensions import db as _db
        _db.session.refresh(test_customer)
        assert test_customer.balance == Decimal('150.000')
