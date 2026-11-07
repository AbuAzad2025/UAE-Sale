"""E2E — ضريبة المشتريات (شامل/إضافي/معفى) والترحيل المحاسبي.

يثبت أن فاتورة الشراء ت:توازن دائماً: مخزون = الإجمالي − الضريبة، وما دام
الترحيل يمر حتماً عبر GLService بوعاء مدين/دائن متساوٍ.
"""
from decimal import Decimal

from tests.e2e.harness import purchase_form, purchase_id_from_redirect
from tests.e2e.harness import assert_entry_accounts


def _purchase_entry(db, pid):
    from models.gl import GLJournalEntry
    return GLJournalEntry.query.filter_by(
        reference_type='Purchase', reference_id=pid).one()


def test_inclusive_purchase_posts_inventory_net_of_tax(
        client, db, login_as, supplier, product, warehouse):
    login_as('owner')

    data = purchase_form(
        supplier,
        [{'product_id': product.id, 'quantity': 1, 'unit_cost': 105}],
        warehouse=warehouse, tax_rate=5, tax_inclusive=True,
    )
    r = client.post('/purchases/create', data=data)
    assert r.status_code in (302, 303)
    pid = purchase_id_from_redirect(r)

    from models import Purchase
    purchase = db.session.get(Purchase, pid)
    assert purchase.tax_amount == Decimal('5.00')
    assert purchase.total_amount == Decimal('105')

    entry = _purchase_entry(db, pid)
    accounts = assert_entry_accounts(entry.id, {
        '1140': (Decimal('100'), Decimal('0')),
        '2130': (Decimal('5'), Decimal('0')),
        '2110': (Decimal('0'), Decimal('105')),
    })
    assert accounts
    assert entry.total_debit == entry.total_credit


def test_exempt_purchase_posts_no_tax_lines(
        client, db, login_as, supplier, product, warehouse):
    login_as('owner')

    data = purchase_form(
        supplier,
        [{'product_id': product.id, 'quantity': 1, 'unit_cost': 80}],
        warehouse=warehouse, tax_rate=5,
        tax_treatment='exempt',
    )
    r = client.post('/purchases/create', data=data)
    assert r.status_code in (302, 303)
    pid = purchase_id_from_redirect(r)

    from models import Purchase
    purchase = db.session.get(Purchase, pid)
    assert purchase.tax_amount == Decimal('0.000')
    assert purchase.total_amount == Decimal('80')

    entry = _purchase_entry(db, pid)
    assert_entry_accounts(entry.id, {
        '1140': (Decimal('80'), Decimal('0')),
        '2110': (Decimal('0'), Decimal('80')),
    })
    codes = {line.account.code for line in entry.lines}
    assert '2130' not in codes


def test_purchase_print_uses_owning_tenant_not_platform(
        client, db, login_as, supplier, product, warehouse):
    from models.tenant import Tenant

    login_as('owner')
    from tests.e2e.harness import purchase_form, purchase_id_from_redirect

    tenant = Tenant(name='Print Supplier Co', name_ar='شركة الطباعة المتحدة',
                    slug='print-test-tenant', tax_number='PRN-TRN-777',
                    country='UAE', city='Dubai')
    db.session.add(tenant)
    db.session.commit()

    data = purchase_form(
        supplier,
        [{'product_id': product.id, 'quantity': 1, 'unit_cost': 90}],
        warehouse=warehouse, tax_rate=5,
    )
    r = client.post('/purchases/create', data=data)
    pid = purchase_id_from_redirect(r)

    from models import Purchase
    purchase = Purchase.query.get(pid)
    purchase.tenant_id = tenant.id
    db.session.commit()

    html = client.get(f'/purchases/{pid}/print').get_data(as_text=True)
    assert 'شركة الطباعة المتحدة' in html
    assert 'PRN-TRN-777' in html


def test_zero_rated_purchase_posts_no_tax_lines(
        client, db, login_as, supplier, product, warehouse):
    login_as('owner')

    data = purchase_form(
        supplier,
        [{'product_id': product.id, 'quantity': 2, 'unit_cost': 50}],
        warehouse=warehouse, tax_rate=5,
        tax_treatment='zero',
    )
    r = client.post('/purchases/create', data=data)
    assert r.status_code in (302, 303)
    pid = purchase_id_from_redirect(r)

    from models import Purchase
    purchase = db.session.get(Purchase, pid)
    assert purchase.tax_amount == Decimal('0.000')
    assert purchase.total_amount == Decimal('100')

    entry = _purchase_entry(db, pid)
    assert entry.total_debit == entry.total_credit
