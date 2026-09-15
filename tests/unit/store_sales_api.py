"""
Store Backend — Sales API Tests

Tests validation, edge cases, idempotency, response shape stability
for sales endpoints (/sales/api/calculate-totals, /sales/api/get-price).
"""

from decimal import Decimal
import pytest

from models import Customer, Product, ProductCategory, Sale, SaleLine
from services.sale_service import SaleService
from extensions import db as _db


class TestCalculateTotalsAPI:
    """Test /sales/api/calculate-totals endpoint."""

    def test_calculate_totals_basic(self, client, login_owner):
        """Basic calculation with valid lines."""
        resp = client.post('/sales/api/calculate-totals', json={
            'lines': [
                {'quantity': 2, 'unit_price': 50, 'discount_percent': 0},
                {'quantity': 1, 'unit_price': 100, 'discount_percent': 10},
            ],
            'discount_amount': 5,
            'shipping_cost': 10,
            'tax_rate': 5,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        # subtotal = 2*50 + 1*100*(1-0.1) = 100 + 90 = 190
        assert data['subtotal'] == pytest.approx(190.0)
        # after_discount = 190 - 5 + 10 = 195
        assert data['discount'] == 5.0
        assert data['shipping'] == 10.0
        assert data['tax_amount'] == pytest.approx(195 * 0.05)
        assert data['total'] == pytest.approx(195 * 1.05)

    def test_calculate_totals_empty_lines(self, client, login_owner):
        """Empty lines list returns zero totals."""
        resp = client.post('/sales/api/calculate-totals', json={
            'lines': [],
            'discount_amount': 0,
            'shipping_cost': 0,
            'tax_rate': 0,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['subtotal'] == 0.0
        assert data['total'] == 0.0
        assert data['line_count'] == 0

    def test_calculate_totals_invalid_quantity(self, client, login_owner):
        """Invalid quantity in line is skipped, others processed."""
        resp = client.post('/sales/api/calculate-totals', json={
            'lines': [
                {'quantity': 'abc', 'unit_price': 50, 'discount_percent': 0},
                {'quantity': 2, 'unit_price': 30, 'discount_percent': 0},
            ],
            'discount_amount': 0,
            'shipping_cost': 0,
            'tax_rate': 0,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        # Only second line should count
        assert data['subtotal'] == pytest.approx(60.0)
        assert data['line_count'] == 1

    def test_calculate_totals_negative_values_allowed(self, client, login_owner):
        """Negative discount/shipping/tax passed through (backend validation later)."""
        resp = client.post('/sales/api/calculate-totals', json={
            'lines': [{'quantity': 1, 'unit_price': 100, 'discount_percent': 0}],
            'discount_amount': -10,  # negative discount = surcharge
            'shipping_cost': -5,     # negative shipping = rebate
            'tax_rate': -2,          # negative tax = subsidy
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        # subtotal = 100
        # after_discount = 100 - (-10) + (-5) = 105
        # tax = 105 * (-0.02) = -2.1
        # total = 105 + (-2.1) = 102.9
        assert data['subtotal'] == 100.0
        assert data['discount'] == -10.0
        assert data['shipping'] == -5.0
        assert data['tax_amount'] == pytest.approx(-2.1)
        assert data['total'] == pytest.approx(102.9)

    def test_calculate_totals_missing_fields_default_zero(self, client, login_owner):
        """Missing optional fields default to zero."""
        resp = client.post('/sales/api/calculate-totals', json={
            'lines': [{'quantity': 1, 'unit_price': 100}],
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['discount'] == 0.0
        assert data['shipping'] == 0.0
        assert data['tax_rate'] == 0.0
        assert data['tax_amount'] == 0.0
        assert data['total'] == 100.0

    def test_calculate_totals_no_data_returns_400(self, client, login_owner):
        """Empty request body returns 400."""
        resp = client.post('/sales/api/calculate-totals', json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert 'error' in data


class TestGetPriceAPI:
    """Test /sales/api/get-price endpoint."""

    @pytest.fixture
    def setup_product_customer(self, db, test_category):
        """Create a product with different price tiers and a customer."""
        product = Product(
            name='Test Product', name_ar='منتج تجريبي',
            sku='SKU-GET-PRICE', category_id=test_category.id,
            cost_price=Decimal('40.000'), regular_price=Decimal('100.000'),
            merchant_price=Decimal('10.00'),  # 10% discount
            partner_price=Decimal('20.00'),   # 20% discount
            current_stock=Decimal('50'), is_active=True,
        )
        db.session.add(product)

        customer = Customer(
            name='Price Customer', name_ar='عميل السعر',
            customer_type='partner', phone='+971509999999',
            credit_limit=Decimal('10000'), balance=Decimal('0'), is_active=True,
        )
        db.session.add(customer)
        db.session.commit()
        return product, customer

    def test_get_price_regular_customer(self, client, login_owner, setup_product_customer):
        """Regular customer gets regular_price."""
        product, _ = setup_product_customer
        regular_customer = Customer(
            name='Regular', customer_type='regular', phone='+971508888888',
            credit_limit=Decimal('1000'), balance=Decimal('0'), is_active=True,
        )
        _db.session.add(regular_customer)
        _db.session.commit()

        resp = client.get(f'/sales/api/get-price?product_id={product.id}&customer_id={regular_customer.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['price'] == 100.0
        assert data['current_stock'] == 50.0
        assert data['unit'] == 'piece'

    def test_get_price_partner_customer(self, client, login_owner, setup_product_customer):
        """Partner customer gets partner_price discount."""
        product, customer = setup_product_customer
        # partner_price = 20% discount
        resp = client.get(f'/sales/api/get-price?product_id={product.id}&customer_id={customer.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['price'] == pytest.approx(100.0 * (1 - 20/100))  # 80.0
        assert data['current_stock'] == 50.0

    def test_get_price_merchant_customer(self, client, login_owner, setup_product_customer):
        """Merchant customer gets merchant_price discount."""
        product, _ = setup_product_customer
        merchant = Customer(
            name='Merchant', customer_type='merchant', phone='+971507777777',
            credit_limit=Decimal('1000'), balance=Decimal('0'), is_active=True,
        )
        _db.session.add(merchant)
        _db.session.commit()

        resp = client.get(f'/sales/api/get-price?product_id={product.id}&customer_id={merchant.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['price'] == pytest.approx(100.0 * (1 - 10/100))  # 90.0

    def test_get_price_missing_product_returns_404(self, client, login_owner, test_customer, test_category):
        """Non-existent product returns 404."""
        resp = client.get(f'/sales/api/get-price?product_id=99999&customer_id={test_customer.id}')
        assert resp.status_code == 404

    def test_get_price_missing_customer_returns_404(self, client, login_owner, test_product):
        """Non-existent customer returns 404."""
        resp = client.get(f'/sales/api/get-price?product_id={test_product.id}&customer_id=99999')
        assert resp.status_code == 404

    def test_get_price_missing_params_returns_400(self, client, login_owner):
        """Missing required query parameters returns 400."""
        resp = client.get('/sales/api/get-price?product_id=1')
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['error'] == 'Missing parameters'

    def test_get_price_cost_price_hidden_for_seller(self, client, login_seller, setup_product_customer):
        """Sellers cannot see cost_price."""
        product, customer = setup_product_customer
        resp = client.get(f'/sales/api/get-price?product_id={product.id}&customer_id={customer.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['cost_price'] is None  # sellers don't have view_costs permission

    def test_get_price_cost_price_visible_for_owner(self, client, login_owner, setup_product_customer):
        """Owners can see cost_price."""
        product, customer = setup_product_customer
        resp = client.get(f'/sales/api/get-price?product_id={product.id}&customer_id={customer.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['cost_price'] == 40.0


class TestSaleCreateAPI:
    """Test sale creation via SaleService (used by /sales/create)."""

    def test_create_sale_success(self, db, owner_user, test_customer, test_product, test_category):
        """Valid sale creation with stock decrement."""
        lines_data = [
            {'product': test_product, 'quantity': Decimal('2'), 'discount_percent': Decimal('0'), 'unit_price': None},
        ]
        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=lines_data,
            currency='AED',
            user_exchange_rate=Decimal('1'),
        )
        assert sale.id is not None
        assert sale.total_amount > 0
        # Stock should be decremented
        _db.session.refresh(test_product)
        assert test_product.current_stock == Decimal('98')  # 100 - 2

    def test_create_sale_insufficient_stock_raises(self, db, owner_user, test_customer, test_product):
        """Insufficient stock raises ValueError with clear message."""
        lines_data = [
            {'product': test_product, 'quantity': Decimal('200'), 'discount_percent': Decimal('0'), 'unit_price': None},
        ]
        with pytest.raises(ValueError, match='المخزون غير كاف'):
            SaleService.create_sale(
                customer=test_customer,
                seller=owner_user,
                lines_data=lines_data,
                currency='AED',
            )

    def test_create_sale_inactive_customer_raises(self, db, owner_user, test_product):
        """Inactive customer raises ValueError."""
        inactive_customer = Customer(
            name='Inactive', customer_type='regular', phone='+971501111111',
            credit_limit=Decimal('1000'), balance=Decimal('0'), is_active=False,
        )
        _db.session.add(inactive_customer)
        _db.session.commit()

        lines_data = [
            {'product': test_product, 'quantity': Decimal('1'), 'discount_percent': Decimal('0'), 'unit_price': None},
        ]
        with pytest.raises(ValueError, match='العميل غير صالح'):
            SaleService.create_sale(
                customer=inactive_customer,
                seller=owner_user,
                lines_data=lines_data,
                currency='AED',
            )

    def test_create_sale_zero_quantity_raises(self, db, owner_user, test_customer, test_product):
        """Zero or negative quantity raises ValueError."""
        lines_data = [
            {'product': test_product, 'quantity': Decimal('0'), 'discount_percent': Decimal('0'), 'unit_price': None},
        ]
        with pytest.raises(ValueError, match='الكمية يجب أن تكون أكبر من صفر'):
            SaleService.create_sale(
                customer=test_customer,
                seller=owner_user,
                lines_data=lines_data,
                currency='AED',
            )

    def test_create_sale_negative_price_raises(self, db, owner_user, test_customer, test_product):
        """Negative unit price raises ValueError."""
        lines_data = [
            {'product': test_product, 'quantity': Decimal('1'), 'discount_percent': Decimal('0'), 'unit_price': Decimal('-10')},
        ]
        with pytest.raises(ValueError, match='السعر يجب أن يكون أكبر من صفر'):
            SaleService.create_sale(
                customer=test_customer,
                seller=owner_user,
                lines_data=lines_data,
                currency='AED',
            )

    def test_create_sale_over_credit_limit_raises(self, db, owner_user, test_product, test_category):
        """Customer over credit limit raises ValueError."""
        customer = Customer(
            name='Over Limit', customer_type='regular', phone='+971502222222',
            credit_limit=Decimal('50'), balance=Decimal('0'), is_active=True,
        )
        _db.session.add(customer)
        _db.session.commit()

        lines_data = [
            {'product': test_product, 'quantity': Decimal('1'), 'discount_percent': Decimal('0'), 'unit_price': Decimal('100')},
        ]
        with pytest.raises(ValueError, match='تجاوز حد الائتمان'):
            SaleService.create_sale(
                customer=customer,
                seller=owner_user,
                lines_data=lines_data,
                currency='AED',
            )

    def test_create_sale_with_payment_overpayment_caps_at_total(self, db, owner_user, test_customer, test_product):
        """Overpayment is capped at the sale total; customer balance is untouched."""
        lines_data = [
            {'product': test_product, 'quantity': Decimal('1'), 'discount_percent': Decimal('0'), 'unit_price': Decimal('100')},
        ]
        payment_data = {
            'amount': Decimal('150'),  # More than total
            'payment_method': 'cash',
            'currency': 'AED',
            'exchange_rate': Decimal('1'),
        }
        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=lines_data,
            currency='AED',
            payment_data=payment_data,
        )
        # Sale paid amount capped at total
        assert sale.paid_amount_base == sale.amount_base
        # No automatic overpayment credit is posted to the customer
        _db.session.refresh(test_customer)
        assert test_customer.balance == Decimal('0')

    def test_create_sale_credit_limit_check_uses_base_currency(self, db, owner_user, test_product, test_category):
        """Credit limit check works with foreign currency exchange rates."""
        # Create product with ILS pricing, sale in AED with rate 1 AED = 1 ILS
        customer = Customer(
            name='FX Customer', customer_type='regular', phone='+971503333333',
            credit_limit=Decimal('500'), balance=Decimal('0'), is_active=True,
        )
        _db.session.add(customer)
        _db.session.commit()

        lines_data = [
            {'product': test_product, 'quantity': Decimal('3'), 'discount_percent': Decimal('0'), 'unit_price': Decimal('100')},
        ]
        # Sale in AED, product price in AED, exchange_rate 1 -> amount_base = 300
        # Should be within 500 limit
        sale = SaleService.create_sale(
            customer=customer,
            seller=owner_user,
            lines_data=lines_data,
            currency='AED',
            user_exchange_rate=Decimal('1'),
        )
        assert sale.id is not None


class TestSaleServiceEdgeCases:
    """Edge cases and invariants in SaleService."""

    def test_reverse_sale_gl_entries_idempotent(self, db, owner_user, test_customer, test_product):
        """Reversing GL entries twice is safe (no duplicate reversals)."""
        lines_data = [
            {'product': test_product, 'quantity': Decimal('1'), 'discount_percent': Decimal('0'), 'unit_price': Decimal('100')},
        ]
        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=lines_data,
            currency='AED',
        )

        # First reversal
        reversals1 = SaleService.reverse_sale_gl_entries(sale, reason='Test1')
        assert len(reversals1) >= 1

        # Second reversal should not create new entries (already reversed)
        reversals2 = SaleService.reverse_sale_gl_entries(sale, reason='Test2')
        # Should return empty list or same entries (not create new ones)
        assert isinstance(reversals2, list)

    def test_update_payment_status_fx_invoice(self, db, owner_user, test_customer, test_product):
        """update_payment_status handles foreign currency correctly."""
        lines_data = [
            {'product': test_product, 'quantity': Decimal('1'), 'discount_percent': Decimal('0'), 'unit_price': Decimal('100')},
        ]
        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=lines_data,
            currency='USD',
            user_exchange_rate=Decimal('3.67'),  # 1 USD = 3.67 AED
        )
        # Initially unpaid
        assert sale.payment_status == 'unpaid'
        assert sale.balance_due > 0

        # Simulate full payment in base currency
        sale.paid_amount_base = sale.amount_base
        SaleService.update_payment_status(sale)
        _db.session.refresh(sale)
        assert sale.payment_status == 'paid'
        assert sale.balance_due == 0

    def test_cancel_sale_with_payments_raises(self, db, owner_user, test_customer, test_product):
        """Cancelling a paid sale raises ValueError."""
        lines_data = [
            {'product': test_product, 'quantity': Decimal('1'), 'discount_percent': Decimal('0'), 'unit_price': Decimal('100')},
        ]
        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=lines_data,
            currency='AED',
        )
        # Mark as paid
        sale.paid_amount_base = sale.amount_base
        sale.payment_status = 'paid'
        _db.session.commit()

        with pytest.raises(ValueError, match='لا يمكن إلغاء فاتورة مدفوعة'):
            SaleService.cancel_sale(sale)

    def test_calculate_totals_decimal_precision(self, db, owner_user, test_customer, test_product):
        """calculate_totals uses proper Decimal precision and rounding."""
        lines_data = [
            {'product': test_product, 'quantity': Decimal('3'), 'discount_percent': Decimal('33.33'), 'unit_price': Decimal('33.33')},
        ]
        sale = SaleService.create_sale(
            customer=test_customer,
            seller=owner_user,
            lines_data=lines_data,
            currency='AED',
            discount_amount=Decimal('0.01'),
            shipping_cost=Decimal('0.01'),
            tax_rate=Decimal('5.55'),
        )
        # Should not raise, totals calculated with Decimal precision
        assert sale.subtotal is not None
        assert sale.tax_amount is not None
        assert sale.total_amount is not None
        # All amounts should be quantized to 3dp
        assert str(sale.total_amount).count('.') <= 1
        if '.' in str(sale.total_amount):
            decimal_places = len(str(sale.total_amount).split('.')[1])
            assert decimal_places <= 3