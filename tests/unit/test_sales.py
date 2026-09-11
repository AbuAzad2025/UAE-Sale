"""
Sales Tests — CRUD operations, IDOR protection, permissions.

Tests the sale workflow and security fixes.
"""

from decimal import Decimal


class TestSaleView:
    """Test sale viewing with permission checks."""

    def test_view_sale_as_owner(self, client, login_owner, test_sale):
        """Owner can view any sale."""
        response = client.get(f'/sales/{test_sale.id}')
        assert response.status_code == 200

    def test_view_sale_requires_auth(self, client, test_sale):
        """Unauthenticated user redirects to login."""
        response = client.get(f'/sales/{test_sale.id}', follow_redirects=False)
        assert response.status_code == 302

    def test_seller_can_view_own_sale(self, client, db, login_seller, seller_user, test_customer, test_product):
        """Seller can view their own sale."""
        from models import Sale, SaleLine
        from utils.helpers import generate_number

        sale = Sale(
            sale_number=generate_number('S', Sale, 'sale_number'),
            customer_id=test_customer.id,
            seller_id=seller_user.id,
            total_amount=Decimal('50.000'),
            amount_base=Decimal('50.000'),
            paid_amount=Decimal('0'),
            paid_amount_base=Decimal('0'),
            balance_due=Decimal('50.000'),
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
            quantity=Decimal('1'),
            unit_price=Decimal('50.000'),
            discount_percent=Decimal('0'),
            line_total=Decimal('50.000'),
            cost_price=Decimal('25.000'),
        )
        db.session.add(line)
        db.session.commit()

        response = client.get(f'/sales/{sale.id}')
        # Seller owns this sale + holds manage_sales -> renders (200).
        assert response.status_code == 200
        assert sale.sale_number.encode() in response.data
        # DB-state: row untouched by a read.
        from models import Sale as _Sale
        assert db.session.get(_Sale, sale.id) is not None

    def test_seller_cannot_view_other_sale(self, client, db, login_seller, seller_user, owner_user, test_customer, test_product):
        """Seller cannot view another seller's sale (IDOR protection)."""
        from models import Sale
        from utils.helpers import generate_number

        # Create sale owned by owner
        sale = Sale(
            sale_number=generate_number('S', Sale, 'sale_number'),
            customer_id=test_customer.id,
            seller_id=owner_user.id,  # Owner's sale
            total_amount=Decimal('50.000'),
            amount_base=Decimal('50.000'),
            paid_amount=Decimal('0'),
            paid_amount_base=Decimal('0'),
            balance_due=Decimal('50.000'),
            currency='AED',
            exchange_rate=Decimal('1'),
            payment_status='unpaid',
            status='confirmed',
            is_active=True,
        )
        db.session.add(sale)
        db.session.commit()

        # Try to view owner's sale — should be redirected
        response = client.get(f'/sales/{sale.id}', follow_redirects=False)
        # IDOR guard flashes + redirects to sales.index (never renders).
        assert response.status_code == 302
        assert '/sales' in response.headers.get('Location', '')
        # DB-state: foreign sale untouched.
        db.session.expire_all()
        assert db.session.get(Sale, sale.id) is not None
        assert db.session.get(Sale, sale.id).seller_id == owner_user.id
        # Flash + list isolation: following the redirect surfaces the
        # denial and the seller list still hides the foreign invoice.
        denied = client.get(f'/sales/{sale.id}', follow_redirects=True)
        assert denied.status_code == 200
        assert sale.sale_number not in client.get('/sales/').get_data(as_text=True)


class TestSaleEdit:
    """Test sale editing with IDOR protection."""

    def test_edit_sale_requires_auth(self, client, test_sale):
        """Unauthenticated user cannot edit."""
        response = client.get(f'/sales/{test_sale.id}/edit', follow_redirects=False)
        assert response.status_code == 302

    def test_edit_sale_as_owner(self, client, login_owner, test_sale):
        """Owner can edit any sale."""
        response = client.get(f'/sales/{test_sale.id}/edit')
        assert response.status_code == 200

    def test_seller_cannot_edit_other_sale(self, client, db, login_seller, seller_user, owner_user, test_customer, test_product):
        """Seller cannot edit another seller's sale (IDOR protection)."""
        from models import Sale
        from utils.helpers import generate_number

        sale = Sale(
            sale_number=generate_number('S', Sale, 'sale_number'),
            customer_id=test_customer.id,
            seller_id=owner_user.id,
            total_amount=Decimal('50.000'),
            amount_base=Decimal('50.000'),
            paid_amount=Decimal('0'),
            paid_amount_base=Decimal('0'),
            balance_due=Decimal('50.000'),
            currency='AED',
            exchange_rate=Decimal('1'),
            payment_status='unpaid',
            status='confirmed',
            is_active=True,
        )
        db.session.add(sale)
        db.session.commit()

        response = client.get(f'/sales/{sale.id}/edit', follow_redirects=False)
        # IDOR guard flashes 'ليس لديك صلاحية لتعديل' + redirects to sales.index.
        assert response.status_code == 302
        assert '/sales' in response.headers.get('Location', '')
        assert '/edit' not in response.headers.get('Location', '')
        # DB-state: foreign sale untouched.
        db.session.expire_all()
        assert db.session.get(Sale, sale.id).total_amount == Decimal('50.000')

    def test_cannot_edit_paid_sale(self, client, login_owner, test_sale, db):
        """Paid sales cannot be edited."""
        test_sale.payment_status = 'paid'
        db.session.commit()

        response = client.get(f'/sales/{test_sale.id}/edit', follow_redirects=False)
        # Paid-sale guard flashes 'مدفوعة' + redirects to sales.view (not edit).
        assert response.status_code == 302
        assert f'/sales/{test_sale.id}' in response.headers.get('Location', '')
        assert '/edit' not in response.headers.get('Location', '')
        # DB-state: guard is read-only.
        db.session.expire_all()
        assert db.session.get(type(test_sale), test_sale.id).payment_status == 'paid'
        blocked_page = client.get(f'/sales/{test_sale.id}/edit', follow_redirects=True)
        assert 'مدفوعة' in blocked_page.get_data(as_text=True)


class TestSaleDelete:
    """Test sale deletion with IDOR protection."""

    def test_delete_sale_requires_auth(self, client, test_sale):
        """Unauthenticated user cannot delete."""
        response = client.post(f'/sales/{test_sale.id}/delete', follow_redirects=False)
        assert response.status_code == 302

    def test_seller_cannot_delete_other_sale(self, client, db, login_seller, seller_user, owner_user, test_customer, test_product):
        """Seller cannot delete another seller's sale (IDOR protection)."""
        from models import Sale
        from utils.helpers import generate_number

        sale = Sale(
            sale_number=generate_number('S', Sale, 'sale_number'),
            customer_id=test_customer.id,
            seller_id=owner_user.id,
            total_amount=Decimal('50.000'),
            amount_base=Decimal('50.000'),
            paid_amount=Decimal('0'),
            paid_amount_base=Decimal('0'),
            balance_due=Decimal('50.000'),
            currency='AED',
            exchange_rate=Decimal('1'),
            payment_status='unpaid',
            status='confirmed',
            is_active=True,
        )
        db.session.add(sale)
        db.session.commit()

        sale_id = sale.id
        sale_number = sale.sale_number
        response = client.post(f'/sales/{sale.id}/delete', follow_redirects=False)
        # IDOR guard flashes 'ليس لديك صلاحية لحذف' + redirects to sales.index.
        assert response.status_code == 302
        assert '/sales' in response.headers.get('Location', '')
        # DB-state: foreign sale NOT deleted/archived.
        from models import Sale as _Sale2
        assert db.session.get(_Sale2, sale_id) is not None
        denied_page = client.post(f'/sales/{sale_id}/delete', follow_redirects=True)
        assert denied_page.status_code == 200
        assert db.session.get(_Sale2, sale_id) is not None
        assert sale_number not in client.get('/sales/').get_data(as_text=True)
