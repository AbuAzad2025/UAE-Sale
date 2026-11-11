"""Maintenance financial cycle — HTTP level, in-memory SQLite only.

Covers the reception -> parts -> invoice -> receipt -> delivery cycle with
its general-ledger effects, the credit/cash delivery policy, warranty work
charged to the warranty expense account, returns, and tenant isolation.
"""
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.engine import make_url


_url = make_url(os.environ['DATABASE_URL'])
if _url.get_backend_name() != 'sqlite' or _url.database not in (None, '', ':memory:'):
    pytest.skip('Maintenance financial tests require in-memory SQLite', allow_module_level=True)

from flask import g  # noqa: E402
from flask_login import login_user  # noqa: E402
from sqlalchemy import text  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

from extensions import db  # noqa: E402
from models import Customer, Permission, Product, ProductCategory, Role, Tenant, User, Warehouse  # noqa: E402
from models.gl import GLAccount, GLJournalEntry, GLJournalLine  # noqa: E402
from models.maintenance import (  # noqa: E402
    MaintenanceCreditNote, MaintenanceInvoice, MaintenanceOrder, MaintenanceOrderStatusLog, MaintenanceReceipt,
)
from services.gl_service import GLService  # noqa: E402
from utils.errors import ValidationError  # noqa: E402

def _login(client, user):
    g.pop('_login_user', None)
    with client.session_transaction() as session:
        session.clear()
    response = client.post('/auth/login', data={
        'username': user.username, 'password': PASSWORD,
    })
    assert response.status_code == 302
    g.pop('_login_user', None)


PASSWORD = 'Test-password-123!'


D = Decimal


@pytest.fixture(scope='session')
def password_hash():
    return generate_password_hash('Test-password-123!', method='pbkdf2:sha256:1000')


@pytest.fixture
def env(db, password_hash):
    tenant = Tenant(name='Tenant A', name_ar='Tenant A', slug='fin-a', enable_maintenance=True)
    other = Tenant(name='Tenant B', name_ar='Tenant B', slug='fin-b', enable_maintenance=True)
    db.session.add_all([tenant, other])
    db.session.flush()

    codes = ['maintenance_view', 'maintenance_receive', 'maintenance_cashier',
             'maintenance_work', 'maintenance_close', 'maintenance_discount',
             'maintenance_settings', 'maintenance_purchase']
    perms = [Permission(code=code, name=code, category='maintenance') for code in codes]
    by_code = {p.code: p for p in perms}
    admin_role = Role(name='Maint admin', slug='maint-admin-fin', permissions=perms)
    engineer_role = Role(name='Maint engineer fin', slug='maint-engineer-fin',
                         permissions=[by_code['maintenance_view'], by_code['maintenance_work']])
    reception_role = Role(name='Maint reception fin', slug='maint-reception-fin',
                          permissions=[by_code['maintenance_view'], by_code['maintenance_receive']])
    cashier_role = Role(name='Maint cashier fin', slug='maint-cashier-fin',
                        permissions=[by_code['maintenance_view'], by_code['maintenance_cashier']])
    db.session.add_all(perms + [admin_role, engineer_role, reception_role, cashier_role])
    db.session.flush()

    def make_user(name, tenant_id, role):
        user = User(username=name, email=f'{name}@example.invalid', full_name=name,
                    tenant_id=tenant_id, role_id=role.id, is_active=True,
                    password_hash=password_hash)
        db.session.add(user)
        return user

    admin = make_user('fin-admin', tenant.id, admin_role)
    engineer = make_user('fin-engineer', tenant.id, engineer_role)
    reception = make_user('fin-reception', tenant.id, reception_role)
    cashier = make_user('fin-cashier', tenant.id, cashier_role)
    other_admin = make_user('fin-admin-b', other.id, admin_role)

    customer = Customer(name='Paying customer', tenant_id=tenant.id, is_active=True,
                         customer_type='regular', credit_limit=D('1000'), balance=D('0'))
    other_customer = Customer(name='Foreign customer', tenant_id=other.id, is_active=True)
    db.session.add_all([customer, other_customer])
    db.session.flush()

    category = ProductCategory(name='Parts', is_active=True)
    db.session.add(category)
    db.session.flush()

    product = Product(name='Brake pad', sku='FIN-BRAKE-1', category_id=category.id,
                      tenant_id=tenant.id, cost_price=D('30'), regular_price=D('100'),
                      current_stock=D('0'), is_active=True)
    db.session.add(product)
    db.session.flush()

    warehouse = Warehouse(name='Maint warehouse', tenant_id=tenant.id, is_active=True,
                          is_maintenance_warehouse=True, code='FIN-WH-1')
    db.session.add(warehouse)
    db.session.flush()

    GLService.ensure_core_accounts()
    db.session.commit()

    # Give the product a real cost basis and stock through an inbound movement.
    # The tenant context must be active, otherwise the movement is stamped
    # without a tenant and the tenant-scoped queries cannot see it.
    from models.tenant_scope import clear_current_tenant_id, set_current_tenant_id
    from services.stock_service import StockService
    set_current_tenant_id(tenant.id)
    try:
        StockService.create_movement(
            product_id=product.id, quantity=D('100'), movement_type='purchase',
            reference_type='setup', reference_id=0, notes='initial stock',
            warehouse_id=warehouse.id, unit_cost_base=D('30'),
        )
        db.session.commit()
    finally:
        clear_current_tenant_id()

    return {'tenant': tenant, 'other': other, 'admin': admin, 'engineer': engineer,
            'reception': reception, 'cashier': cashier,
            'other_admin': other_admin, 'customer': customer,
            'other_customer': other_customer, 'product': product, 'warehouse': warehouse}


def _login(client, user):
    g.pop('_login_user', None)
    with client.session_transaction() as session:
        session.clear()
    response = client.post('/auth/login', data={
        'username': user.username, 'password': 'Test-password-123!'})
    assert response.status_code == 302
    g.pop('_login_user', None)


def _gl_lines(reference_type, reference_id):
    entry = GLJournalEntry.query.filter_by(reference_type=reference_type,
                                           reference_id=reference_id).first()
    if entry is None:
        return []
    return [(line.account.code, D(str(line.debit or 0)), D(str(line.credit or 0)))
            for line in GLJournalLine.query.filter_by(entry_id=entry.id).all()]


def _gl_total(reference_type, reference_id):
    lines = _gl_lines(reference_type, reference_id)
    debit = sum((row[1] for row in lines), D('0'))
    credit = sum((row[2] for row in lines), D('0'))
    return debit, credit, lines


def _inventory_balance():
    """Book value of the inventory account (debits minus credits)."""
    row = db.session.execute(text(
        "SELECT COALESCE(SUM(debit - credit), 0) FROM gl_journal_lines "
        "WHERE account_id = (SELECT id FROM gl_accounts WHERE code = '1140')"
    )).scalar_one()
    return D(str(row))


def _create_order(client, env, payment_mode='cash'):
    _login(client, env['admin'])
    response = client.post('/maintenance/create', data={
        'customer_id': env['customer'].id, 'device_serial': 'FIN-SERIAL-1',
        'payment_mode': payment_mode,
    })
    assert response.status_code == 302
    order = MaintenanceOrder.query.filter_by(device_serial='FIN-SERIAL-1').one()
    return order


def _add_part(client, env, order, quantity=2, price='100', tax_rate='5'):
    return client.post(f'/maintenance/{order.id}/item', data={
        'product_id': env['product'].id, 'quantity': quantity, 'unit_price': price,
        'tax_rate': tax_rate, 'warehouse_id': env['warehouse'].id,
    })


def _add_service(client, env, order, price='50', tax_rate='5', cost='10'):
    return client.post(f'/maintenance/{order.id}/service', data={
        'service_name': 'فحص عام', 'unit_price': price, 'tax_rate': tax_rate,
        'duration_minutes': 30, 'cost_price': cost,
    })


def _advance(client, env, order, status):
    return client.post(f'/maintenance/{order.id}/status', data={'status': status})


# ---------------------------------------------------------------------------
def test_issuing_a_part_moves_stock_and_posts_the_actual_cost(client, env):
    order = _create_order(client, env)
    stock_before = D(str(env['product'].current_stock))
    inventory_before = _inventory_balance()

    response = _add_part(client, env, order, quantity=2, price='100')
    assert response.status_code == 302
    db.session.expire_all()

    product = db.session.get(Product, env['product'].id)
    assert product.current_stock == stock_before - 2

    item = order.items[0]
    assert item.cost_price == D('30')  # actual cost, not the selling price
    assert item.line_total == D('210.000')  # 2 x 100 + 5% VAT
    assert order.total_amount == D('210.000')
    assert order.tax_amount == D('10.000')
    assert order.total_amount - order.tax_amount == D('200.000')

    debit, credit, lines = _gl_total('maintenance_item', item.id)
    assert debit == credit == D('60.000')
    assert ('5101', D('60.000'), D('0')) in lines   # maintenance cost
    assert ('1140', D('0'), D('60.000')) in lines   # inventory relieved
    assert _inventory_balance() == inventory_before - D('60.000')


def test_invoice_separates_revenue_and_vat_and_posts_the_receivable(client, env):
    order = _create_order(client, env)
    _add_part(client, env, order)
    _add_service(client, env, order, price='50', tax_rate='5', cost='10')
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')

    response = client.post(f'/maintenance/{order.id}/invoice')
    assert response.status_code == 302
    db.session.expire_all()

    invoice = MaintenanceInvoice.query.filter_by(maintenance_order_id=order.id).one()
    assert invoice.gl_posted is True
    assert invoice.total_amount == D('262.500')   # 210.000 + 52.500
    assert invoice.tax_amount == D('12.500')      # 10.000 + 2.500

    debit, credit, lines = _gl_total('maintenance_invoice', invoice.id)
    assert debit == credit == D('262.500')
    assert ('1131', D('262.500'), D('0')) in lines   # maintenance receivable
    assert ('4210', D('0'), D('250.000')) in lines   # revenue net of VAT
    assert ('2131', D('0'), D('12.500')) in lines    # VAT output


def test_receipt_collects_cash_and_reduces_the_receivable(client, env):
    order = _create_order(client, env)
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    client.post(f'/maintenance/{order.id}/invoice')

    response = client.post(f'/maintenance/{order.id}/receive',
                           data={'amount': '100', 'payment_method': 'cash'})
    assert response.status_code == 302
    db.session.expire_all()

    receipt = MaintenanceReceipt.query.filter_by(maintenance_order_id=order.id).one()
    assert receipt.amount == D('100.000')
    assert receipt.posted is True
    debit, credit, lines = _gl_total('maintenance_receipt', receipt.id)
    assert debit == credit == D('100.000')
    assert ('1110', D('100.000'), D('0')) in lines   # cash
    assert ('1131', D('0'), D('100.000')) in lines   # receivable

    order = db.session.get(MaintenanceOrder, order.id)
    assert order.paid_amount == D('100.000')
    assert order.balance_due == order.total_amount - D('100.000')


def test_cash_order_cannot_be_delivered_before_it_is_paid(client, env):
    order = _create_order(client, env, payment_mode='cash')
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    client.post(f'/maintenance/{order.id}/invoice')

    response = _advance(client, env, order, 'closed')
    assert response.status_code == 302
    db.session.expire_all()
    assert db.session.get(MaintenanceOrder, order.id).status == 'ready'

    client.post(f'/maintenance/{order.id}/receive', data={'amount': '210', 'payment_method': 'cash'})
    db.session.expire_all()
    assert _advance(client, env, order, 'closed').status_code == 302
    db.session.expire_all()
    closed = db.session.get(MaintenanceOrder, order.id)
    assert closed.status == 'closed'
    assert closed.paid_amount == closed.total_amount
    assert closed.balance_due == 0


def test_credit_order_can_be_delivered_after_the_invoice_and_the_limit_check(client, env):
    order = _create_order(client, env, payment_mode='account')
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    client.post(f'/maintenance/{order.id}/invoice')

    # The limit is 1000 and the invoice is 210, so delivery on account is fine.
    assert _advance(client, env, order, 'closed').status_code == 302
    db.session.expire_all()
    assert db.session.get(MaintenanceOrder, order.id).status == 'closed'


def test_credit_delivery_is_refused_over_the_credit_limit(client, env):
    env['customer'].credit_limit = D('50')
    db.session.commit()
    order = _create_order(client, env, payment_mode='account')
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    client.post(f'/maintenance/{order.id}/invoice')

    _advance(client, env, order, 'closed')
    db.session.expire_all()
    assert db.session.get(MaintenanceOrder, order.id).status == 'ready'


def test_delivery_without_an_invoice_is_refused(client, env):
    order = _create_order(client, env)
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    _advance(client, env, order, 'closed')
    db.session.expire_all()
    assert db.session.get(MaintenanceOrder, order.id).status == 'ready'


def test_warranty_work_is_expensed_and_never_billed_to_the_customer(client, env):
    order = _create_order(client, env)
    order.warranty_status = 'under_warranty'
    db.session.commit()
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')

    # No customer invoice for warranty work.
    response = client.post(f'/maintenance/{order.id}/invoice')
    assert response.status_code == 302
    db.session.expire_all()
    assert MaintenanceInvoice.query.filter_by(maintenance_order_id=order.id).count() == 0

    assert _advance(client, env, order, 'closed').status_code == 302
    db.session.expire_all()
    assert db.session.get(MaintenanceOrder, order.id).status == 'closed'

    debit, credit, lines = _gl_total('maintenance_order', order.id)
    assert debit == credit == D('60.000')
    assert ('6401', D('60.000'), D('0')) in lines    # warranty expense
    assert ('5101', D('0'), D('60.000')) in lines    # reclassified out of cost
    # No receivable and no revenue for warranty work.
    assert not any(code in ('1131', '4210') for code, _, _ in lines)


def test_a_second_posting_of_the_same_document_is_refused(client, env):
    order = _create_order(client, env)
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    client.post(f'/maintenance/{order.id}/invoice')
    db.session.expire_all()
    invoice = MaintenanceInvoice.query.filter_by(maintenance_order_id=order.id).one()
    entries_before = GLJournalEntry.query.filter_by(
        reference_type='maintenance_invoice', reference_id=invoice.id).count()

    from services import maintenance_accounting as accounting
    with pytest.raises(ValidationError):
        accounting.post_maintenance_invoice(order, invoice)
    db.session.rollback()
    entries_after = GLJournalEntry.query.filter_by(
        reference_type='maintenance_invoice', reference_id=invoice.id).count()
    assert entries_before == entries_after == 1


def test_returning_a_part_puts_the_stock_back_and_reverses_its_cost(client, env):
    order = _create_order(client, env)
    _add_part(client, env, order, quantity=2)
    db.session.expire_all()
    stock_after_issue = D(str(db.session.get(Product, env['product'].id).current_stock))

    item_id = order.items[0].id
    response = client.post(f'/maintenance/{order.id}/return', data={
        'order_item_id': item_id, 'quantity': '1', 'reason': 'قطعة غير مطابقة',
    })
    assert response.status_code == 302
    db.session.expire_all()

    assert D(str(db.session.get(Product, env['product'].id).current_stock)) == stock_after_issue + 1
    order = db.session.get(MaintenanceOrder, order.id)
    assert order.items[0].returned_quantity == D('1.000')
    assert order.total_amount == D('105.000')  # one remaining part at 100 + 5%

    debit, credit, lines = _gl_total('maintenance_return', order.returns[0].id)
    assert debit == credit == D('30.000')
    assert ('1140', D('30.000'), D('0')) in lines   # back into inventory
    assert ('5101', D('0'), D('30.000')) in lines   # cost reversed


def test_a_return_after_the_invoice_is_refused(client, env):
    order = _create_order(client, env)
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    client.post(f'/maintenance/{order.id}/invoice')
    db.session.expire_all()
    item_id = order.items[0].id
    response = client.post(f'/maintenance/{order.id}/return', data={
        'order_item_id': item_id, 'quantity': '1', 'reason': 'late return',
    })
    assert response.status_code == 302
    db.session.expire_all()
    assert order.returns == [] or len(order.returns) == 0


def test_deposit_creates_receipt_and_gl_posting(client, env):
    """A deposit at reception creates a receipt and posts GL."""
    _login(client, env['admin'])
    response = client.post('/maintenance/create', data={
        'customer_id': env['customer'].id,
        'device_serial': 'DEP-SMOKE-1',
        'deposit': '200',
        'deposit_payment_method': 'cash',
    })
    assert response.status_code == 302
    db.session.expire_all()
    order = MaintenanceOrder.query.filter_by(device_serial='DEP-SMOKE-1').one()
    assert order.deposit == D('200.000')
    assert order.paid_amount == D('200.000')
    assert order.balance_due == D('-200.000')
    receipt = MaintenanceReceipt.query.filter_by(maintenance_order_id=order.id).one()
    assert receipt.amount == D('200.000')
    assert receipt.posted is True
    debit, credit, lines = _gl_total('maintenance_deposit', receipt.id)
    assert debit == credit == D('200.000')
    assert ('1110', D('200.000'), D('0')) in lines   # cash
    assert ('1131', D('0'), D('200.000')) in lines   # maintenance receivable


def test_credit_note_reverses_invoice_and_allows_return(client, db, env):
    """A credit note reverses revenue/VAT and unblocks returns after invoicing."""
    from models.maintenance import MaintenanceCreditNote

    order = _create_order(client, env)
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    client.post(f'/maintenance/{order.id}/invoice')
    db.session.expire_all()
    order = db.session.get(MaintenanceOrder, order.id)
    invoice = order.invoice
    assert invoice.gl_posted is True

    # Credit note reverses revenue and VAT.
    response = client.post(f'/maintenance/{order.id}/credit-note', data={
        'reason': 'خطأ في الفاتورة',
    })
    assert response.status_code == 302
    db.session.expire_all()
    cn = MaintenanceCreditNote.query.filter_by(maintenance_order_id=order.id).one()
    assert cn.posted is True
    assert cn.gl_posted is True

    debit, credit, lines = _gl_total('maintenance_credit_note', cn.id)
    assert debit == credit == invoice.total_amount
    assert ('4210', D(str(invoice.total_amount - invoice.tax_amount)), D('0')) in lines
    assert ('2131', D(str(invoice.tax_amount)), D('0')) in lines
    assert ('1131', D('0'), D(str(invoice.total_amount))) in lines

    # After the credit note, returns are allowed again.
    item_id = order.items[0].id
    response = client.post(f'/maintenance/{order.id}/return', data={
        'order_item_id': item_id, 'quantity': '1', 'reason': 'بعد الإشعار',
    })
    assert response.status_code == 302
    db.session.expire_all()
    assert len(db.session.get(MaintenanceOrder, order.id).returns) == 1


def test_credit_note_reverses_invoice_and_allows_return(client, db, env):
    """سند الائتمان يعكس الإيراد والضريبة، ويتيح المرتجع بعد الفاتورة."""
    from models.maintenance import MaintenanceCreditNote

    order = _create_order(client, env)
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    client.post(f'/maintenance/{order.id}/invoice')
    db.session.expire_all()
    order = db.session.get(MaintenanceOrder, order.id)
    invoice = order.invoice
    assert invoice.gl_posted is True

    # سند الائتمان يعكس الإيراد والضريبة.
    response = client.post(f'/maintenance/{order.id}/credit-note', data={
        'reason': 'خطأ في الفاتورة',
    })
    assert response.status_code == 302
    db.session.expire_all()
    cn = MaintenanceCreditNote.query.filter_by(maintenance_order_id=order.id).one()
    assert cn.posted is True
    assert cn.gl_posted is True

    debit, credit, lines = _gl_total('maintenance_credit_note', cn.id)
    assert debit == credit == invoice.total_amount
    assert ('4210', D(str(invoice.total_amount - invoice.tax_amount)), D('0')) in lines
    assert ('2131', D(str(invoice.tax_amount)), D('0')) in lines
    assert ('1131', D('0'), D(str(invoice.total_amount))) in lines

    # بعد السند الائتماني، المرتجع متاح مرة أخرى.
    item_id = order.items[0].id
    response = client.post(f'/maintenance/{order.id}/return', data={
        'order_item_id': item_id, 'quantity': '1', 'reason': 'بعد السند',
    })
    assert response.status_code == 302
    db.session.expire_all()
    assert len(db.session.get(MaintenanceOrder, order.id).returns) == 1


def test_every_posting_of_the_order_is_balanced(client, env):
    order = _create_order(client, env)
    _add_part(client, env, order)
    db.session.expire_all()
    before = order.total_amount

    response = client.post(f'/maintenance/{order.id}/discount',
                           data={'discount_percent': '50', 'discount_value': '0'})
    assert response.status_code == 302
    db.session.expire_all()
    order = db.session.get(MaintenanceOrder, order.id)
    assert order.discount_total_percent == D('0')  # refused, the cap is 15%
    assert order.total_amount == before

    response = client.post(f'/maintenance/{order.id}/discount',
                           data={'discount_percent': '10', 'discount_value': '0'})
    assert response.status_code == 302
    db.session.expire_all()
    order = db.session.get(MaintenanceOrder, order.id)
    assert order.discount_total_percent == D('10')
    # The discount is applied to the net (pre-VAT) basis of 200, so the VAT
    # falls with it: 200 - 20 = 180 net, + 5% VAT = 189.
    assert order.discount_total_value == D('20.000')
    assert order.total_amount == D('189.000')
    assert order.tax_amount == D('9.000')


def test_another_tenant_cannot_reach_the_order_or_its_documents(client, env):
    order = _create_order(client, env)
    _add_part(client, env, order)
    db.session.expire_all()

    _login(client, env['other_admin'])
    assert client.get(f'/maintenance/{order.id}').status_code == 404
    response = client.post(f'/maintenance/{order.id}/item', data={
        'product_id': env['product'].id, 'quantity': '1', 'unit_price': '10',
        'warehouse_id': env['warehouse'].id,
    })
    assert response.status_code in (302, 404)
    db.session.expire_all()
    assert len(db.session.get(MaintenanceOrder, order.id).items) == 1
    assert db.session.get(MaintenanceOrder, order.id).items[0].quantity == D('2.000')
    assert D(str(db.session.get(Product, env['product'].id).current_stock)) == D('98.000')


def test_engineer_cannot_collect_money_or_invoice(client, env):
    order = _create_order(client, env)
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    db.session.expire_all()

    _login(client, env['engineer'])
    assert client.post(f'/maintenance/{order.id}/receive',
                       data={'amount': '10', 'payment_method': 'cash'}).status_code == 403
    assert client.post(f'/maintenance/{order.id}/invoice').status_code == 403
    db.session.expire_all()
    assert MaintenanceInvoice.query.count() == 0
    assert MaintenanceReceipt.query.count() == 0


def test_a_part_without_a_cost_basis_is_refused(client, env):
    """No cost basis means no reliable cost: the issue is refused."""
    from models import Product as ProductModel
    cheap = ProductModel(name='No cost part', sku='FIN-NOCOST-1',
                         tenant_id=env['tenant'].id, regular_price=D('50'),
                         current_stock=D('5'), is_active=True)
    db.session.add(cheap)
    db.session.commit()
    order = _create_order(client, env)
    response = client.post(f'/maintenance/{order.id}/item', data={
        'product_id': cheap.id, 'quantity': '1', 'unit_price': '50',
        'warehouse_id': env['warehouse'].id,
    })
    assert response.status_code == 302
    db.session.expire_all()
    assert len(db.session.get(MaintenanceOrder, order.id).items) == 0


def test_issuing_more_than_the_stock_is_refused(client, env):
    order = _create_order(client, env)
    response = _add_part(client, env, order, quantity=5000)
    assert response.status_code == 302
    db.session.expire_all()
    assert len(db.session.get(MaintenanceOrder, order.id).items) == 0
    assert D(str(db.session.get(Product, env['product'].id).current_stock)) == D('100.000')


def test_tax_inclusive_pricing_splits_the_vat_out_of_the_entered_price(client, env):
    order = _create_order(client, env)
    order.tax_inclusive = True
    db.session.commit()
    response = client.post(f'/maintenance/{order.id}/item', data={
        'product_id': env['product'].id, 'quantity': '1', 'unit_price': '105',
        'tax_rate': '5', 'warehouse_id': env['warehouse'].id,
    })
    assert response.status_code == 302
    db.session.expire_all()
    order = db.session.get(MaintenanceOrder, order.id)
    assert order.total_amount == D('105.000')
    assert order.tax_amount == D('5.000')
    assert order.total_amount - order.tax_amount == D('100.000')


def test_a_fixed_discount_amount_reduces_the_revenue(client, env):
    order = _create_order(client, env)
    _add_part(client, env, order)
    db.session.expire_all()
    response = client.post(f'/maintenance/{order.id}/discount',
                           data={'discount_percent': '0', 'discount_value': '50'})
    assert response.status_code == 302
    db.session.expire_all()
    order = db.session.get(MaintenanceOrder, order.id)
    assert order.discount_total_value == D('50.000')
    assert order.total_amount == D('157.500')   # 150 net + 5% VAT on 150
    assert order.tax_amount == D('7.500')


def test_warranty_reclassification_uses_the_parts_still_issued(client, env):
    order = _create_order(client, env)
    order.warranty_status = 'under_warranty'
    db.session.commit()
    _add_part(client, env, order, quantity=2)
    db.session.expire_all()
    item_id = db.session.get(MaintenanceOrder, order.id).items[0].id
    client.post(f'/maintenance/{order.id}/return', data={
        'order_item_id': item_id, 'quantity': '1', 'reason': 'قطعة زائدة',
    })
    db.session.expire_all()
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    _advance(client, env, order, 'closed')
    db.session.expire_all()
    debit, credit, lines = _gl_total('maintenance_order', order.id)
    # Only the part that stayed on the order is expensed (30 AED each).
    assert debit == credit == D('30.000')
    assert ('6401', D('30.000'), D('0')) in lines


def test_reception_creates_orders_but_cannot_collect_money(client, env):
    """Separation of duties: reception takes the device in, the cashier takes
    the money."""
    order = _create_order(client, env)
    _login(client, env['reception'])
    # Reception has no collection permission.
    assert client.post(f'/maintenance/{order.id}/receive',
                       data={'amount': '10', 'payment_method': 'cash'}).status_code == 403
    db.session.expire_all()
    assert MaintenanceReceipt.query.count() == 0

    _login(client, env['reception'])
    response = client.post('/maintenance/create', data={
        'customer_id': env['customer'].id, 'device_serial': 'FIN-RECEPTION-1',
    })
    assert response.status_code == 302
    db.session.expire_all()
    assert MaintenanceOrder.query.filter_by(device_serial='FIN-RECEPTION-1').count() == 1


def test_cashier_collects_but_does_not_issue_parts(client, env):
    order = _create_order(client, env)
    _login(client, env['cashier'])
    response = _add_part(client, env, order)
    assert response.status_code == 403
    db.session.expire_all()
    assert len(db.session.get(MaintenanceOrder, order.id).items) == 0


def test_purchasing_parts_records_a_maintenance_payable(client, db, env):
    """A purchase order posts nothing; receiving the goods does."""
    from models import Supplier
    from models.erp_modules import PurchaseOrder

    supplier = Supplier(name='Parts supplier', tenant_id=env['tenant'].id, is_active=True)
    db.session.add(supplier)
    db.session.commit()

    _login(client, env['admin'])
    response = client.post('/maintenance/purchases', data={
        'supplier_id': supplier.id, 'warehouse_id': env['warehouse'].id,
        'product_id': env['product'].id, 'quantity': '10', 'unit_cost': '25',
        'tax_rate': '0',
    })
    assert response.status_code == 302
    db.session.expire_all()
    purchase = PurchaseOrder.query.filter_by(tenant_id=env['tenant'].id).one()
    assert purchase.total_amount == D('250.000')
    # Nothing is posted while the order is only a request.
    assert GLJournalEntry.query.filter_by(reference_type='maintenance_purchase').count() == 0

    stock_before = D(str(db.session.get(Product, env['product'].id).current_stock))
    response = client.post(f'/maintenance/purchases/{purchase.id}/receive')
    assert response.status_code == 302
    db.session.expire_all()

    assert D(str(db.session.get(Product, env['product'].id).current_stock)) == stock_before + 10
    debit, credit, lines = _gl_total('maintenance_purchase', purchase.id)
    assert debit == credit == D('250.000')
    assert ('1140', D('250.000'), D('0')) in lines   # inventory in
    assert ('2111', D('0'), D('250.000')) in lines   # maintenance payable

    # Paying the supplier settles the payable.
    response = client.post('/maintenance/purchases/pay', data={
        'supplier_id': supplier.id, 'amount': '100', 'payment_method': 'cash',
    })
    assert response.status_code == 302
    db.session.expire_all()
    entries = GLJournalEntry.query.filter_by(
        reference_type='maintenance_supplier_payment').all()
    assert len(entries) == 1
    payment_lines = [(line.account.code, D(str(line.debit or 0)), D(str(line.credit or 0)))
                     for entry in entries
                     for line in GLJournalLine.query.filter_by(entry_id=entry.id).all()]
    assert ('2111', D('100.000'), D('0')) in payment_lines
    assert ('1110', D('0'), D('100.000')) in payment_lines


def test_a_supplier_payment_cannot_exceed_the_payable(client, db, env):
    from models import Supplier
    supplier = Supplier(name='Small supplier', tenant_id=env['tenant'].id, is_active=True)
    db.session.add(supplier)
    db.session.commit()
    _login(client, env['admin'])
    response = client.post('/maintenance/purchases/pay', data={
        'supplier_id': supplier.id, 'amount': '50', 'payment_method': 'cash',
    })
    assert response.status_code == 302
    db.session.expire_all()
    assert GLJournalEntry.query.filter_by(
        reference_type='maintenance_supplier_payment').count() == 0


def test_credit_note_reverses_invoice_and_allows_return(client, db, env):
    """A credit note reverses revenue/VAT and unblocks returns after invoicing."""
    from models.maintenance import MaintenanceCreditNote

    order = _create_order(client, env)
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    client.post(f'/maintenance/{order.id}/invoice')
    db.session.expire_all()
    order = db.session.get(MaintenanceOrder, order.id)
    invoice = order.invoice
    assert invoice.gl_posted is True

    # Credit note reverses revenue and VAT.
    response = client.post(f'/maintenance/{order.id}/credit-note', data={
        'reason': 'خطأ في الفاتورة',
    })
    assert response.status_code == 302
    db.session.expire_all()
    cn = MaintenanceCreditNote.query.filter_by(maintenance_order_id=order.id).one()
    assert cn.posted is True
    assert cn.gl_posted is True

    debit, credit, lines = _gl_total('maintenance_credit_note', cn.id)
    assert debit == credit == invoice.total_amount
    assert ('4210', D(str(invoice.total_amount - invoice.tax_amount)), D('0')) in lines
    assert ('2131', D(str(invoice.tax_amount)), D('0')) in lines
    assert ('1131', D('0'), D(str(invoice.total_amount))) in lines

    # After the credit note, returns are allowed again.
    item_id = order.items[0].id
    response = client.post(f'/maintenance/{order.id}/return', data={
        'order_item_id': item_id, 'quantity': '1', 'reason': 'بعد الإشعار',
    })
    assert response.status_code == 302
    db.session.expire_all()
    assert len(db.session.get(MaintenanceOrder, order.id).returns) == 1


def test_credit_note_reverses_invoice_and_allows_return(client, db, env):
    """A credit note reverses revenue/VAT and unblocks returns after invoicing."""
    from models.maintenance import MaintenanceCreditNote

    order = _create_order(client, env)
    _add_part(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    client.post(f'/maintenance/{order.id}/invoice')
    db.session.expire_all()
    order = db.session.get(MaintenanceOrder, order.id)
    invoice = order.invoice
    assert invoice.gl_posted is True

    # Credit note reverses revenue and VAT.
    response = client.post(f'/maintenance/{order.id}/credit-note', data={
        'reason': 'خطأ في الفاتورة',
    })
    assert response.status_code == 302
    db.session.expire_all()
    cn = MaintenanceCreditNote.query.filter_by(maintenance_order_id=order.id).one()
    assert cn.posted is True
    assert cn.gl_posted is True

    debit, credit, lines = _gl_total('maintenance_credit_note', cn.id)
    assert debit == credit == invoice.total_amount
    assert ('4210', D(str(invoice.total_amount - invoice.tax_amount)), D('0')) in lines
    assert ('2131', D(str(invoice.tax_amount)), D('0')) in lines
    assert ('1131', D('0'), D(str(invoice.total_amount))) in lines

    # After the credit note, returns are allowed again.
    item_id = order.items[0].id
    response = client.post(f'/maintenance/{order.id}/return', data={
        'order_item_id': item_id, 'quantity': '1', 'reason': 'بعد الإشعار',
    })
    assert response.status_code == 302
    db.session.expire_all()
    assert len(db.session.get(MaintenanceOrder, order.id).returns) == 1


def test_every_posting_of_the_order_is_balanced(client, env):
    order = _create_order(client, env, payment_mode='account')
    _add_part(client, env, order)
    _add_service(client, env, order)
    _advance(client, env, order, 'diagnosis')
    _advance(client, env, order, 'in_progress')
    _advance(client, env, order, 'ready')
    client.post(f'/maintenance/{order.id}/invoice')
    client.post(f'/maintenance/{order.id}/receive', data={'amount': '50', 'payment_method': 'card'})
    db.session.expire_all()

    entries = GLJournalEntry.query.filter(
        (GLJournalEntry.reference_type == 'maintenance_item')
        | (GLJournalEntry.reference_type == 'maintenance_invoice')
        | (GLJournalEntry.reference_type == 'maintenance_receipt')
    ).all()
    assert len(entries) == 3
    for entry in entries:
        assert entry.total_debit == entry.total_credit
        assert entry.total_debit > 0
        assert entry.is_posted is True
        for line in GLJournalLine.query.filter_by(entry_id=entry.id).all():
            assert not (line.debit and line.credit)
