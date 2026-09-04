from decimal import Decimal
import pytest

from services import ai_commands as cmd
from extensions import db as _db


@pytest.fixture(scope='function')
def owner(db):
    from models import Role, User
    role = Role(name='Owner', name_ar='مالك', slug='owner')
    _db.session.add(role)
    _db.session.flush()
    user = User(username='ai_cmd_owner', email='ai_cmd_owner@test.com',
                full_name='Owner', is_owner=True, is_active=True,
                role_id=role.id)
    user.set_password('Pass123!')
    _db.session.add(user)
    _db.session.commit()
    return user


class TestCustomerService:
    def test_create(self, db):
        c = cmd.create_customer('أحمد', phone='0501', address='دبي')
        assert c.id and c.name == 'أحمد' and c.balance == 0


class TestProductService:
    def test_create(self, db):
        p = cmd.create_product('فلتر', part_number='P-1', regular_price=Decimal('50'), current_stock=Decimal('10'))
        assert p.id and p.regular_price == Decimal('50')


class TestSaleService:
    def test_create_moves_stock(self, db, owner):
        p = cmd.create_product('قطع', regular_price=Decimal('20'), current_stock=Decimal('10'))
        c = cmd.create_customer('عميل')
        s = cmd.create_sale(c.id, p.id, Decimal('2'), owner.id)
        assert s.id and s.total_amount == Decimal('40')
        from models import Product
        assert Product.query.get(p.id).current_stock == Decimal('8')


class TestPaymentService:
    def test_record_incoming(self, db, owner):
        c = cmd.create_customer('عميل دفع')
        pmt = cmd.record_payment(c.id, Decimal('100'), 'cash', 'incoming', owner.id, 'customer_payment')
        assert pmt.id and pmt.amount_base == Decimal('100')


class TestExpenseService:
    def test_create(self, db, owner):
        e = cmd.create_expense('مصروف', Decimal('30'), owner.id)
        assert e.id and e.amount_base == Decimal('30')


class TestSupplierService:
    def test_create(self, db):
        s = cmd.create_supplier('مورد', phone='050', email='s@t.com')
        assert s.id and s.name == 'مورد'


class TestPurchaseService:
    def test_create_stocks_up(self, db, owner):
        s = cmd.create_supplier('مورد مشتريات')
        p = cmd.create_product('قطعة شراء', regular_price=Decimal('5'), current_stock=Decimal('0'))
        pu = cmd.create_purchase(s.id, p.id, Decimal('3'), Decimal('4'), owner.id)
        assert pu.id and pu.total_amount == Decimal('12')
        from models import Product
        assert Product.query.get(p.id).current_stock == Decimal('3')


class TestChequeService:
    def test_create_incoming(self, db, owner):
        from datetime import date
        ch = cmd.create_cheque('CH-1', Decimal('500'), date(2026, 12, 31), 'incoming', owner.id)
        assert ch.id and ch.cheque_type == 'incoming'


class TestUserService:
    def test_create(self, db):
        from models import Role
        _db.session.add(Role(name='بائع', name_ar='بائع', slug='seller'))
        _db.session.commit()
        u = cmd.create_user('cmd_user', 'Pass123!x', 'seller', email='u@t.com')
        assert u.id and u.check_password('Pass123!x')
        assert u.role.slug == 'seller'
