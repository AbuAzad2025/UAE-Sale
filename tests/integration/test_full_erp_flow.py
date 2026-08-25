"""
Integration Test: Full ERP Flow
Tests the complete business flow: Credit Limit, Fiscal Period, Quotation, PO, Stock Transfer, Stock Take, E-Invoice, Dunning, Lot, Bin

Uses shared fixtures from tests/conftest.py (app/db/client).
The `db` fixture keeps one app context (and therefore one session) open
for the duration of each test - do NOT push extra app contexts here.
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal


@pytest.fixture
def seed(db):
    """Seed fresh data for each test"""
    from models import (User, Role, Tenant, Product, ProductCategory,
                        Customer, Supplier, Warehouse, GLAccount)
    from werkzeug.security import generate_password_hash

    tenant = Tenant(name='Test', name_ar='تجريبي', slug='test-tenant')
    owner_role = Role(name='Owner', name_ar='المالك', slug='owner')
    manager_role = Role(name='Manager', name_ar='مدير', slug='manager')
    db.session.add_all([tenant, owner_role, manager_role])
    db.session.flush()

    owner = User(username='owner', email='o@t.com', full_name='Owner',
                 password_hash=generate_password_hash('x'), role_id=owner_role.id, is_owner=True)
    manager = User(username='mgr', email='m@t.com', full_name='Manager',
                   password_hash=generate_password_hash('x'), role_id=manager_role.id)
    db.session.add_all([owner, manager])
    db.session.flush()

    for code, name, name_ar, typ in [
        ('1110', 'Cash', 'صندوق', 'asset'), ('1120', 'Bank', 'بنك', 'asset'),
        ('1130', 'AR', 'ذمم مدينة', 'asset'), ('1140', 'Inventory', 'مخزون', 'asset'),
        ('2110', 'AP', 'ذمم دائنة', 'liability'), ('2130', 'Tax', 'ضرائب', 'liability'),
        ('4100', 'Revenue', 'إيرادات', 'revenue'), ('5000', 'COGS', 'تكلفة', 'expense'),
    ]:
        db.session.add(GLAccount(code=code, name=name, name_ar=name_ar, type=typ, currency='AED'))
    db.session.flush()

    cat = ProductCategory(name='Parts', name_ar='قطع')
    db.session.add(cat)
    db.session.flush()

    product = Product(name='Brake Pad', name_ar='صدة', sku='BP-001', barcode='123',
                      category_id=cat.id, cost_price=Decimal('50'),
                      regular_price=Decimal('100'), current_stock=Decimal('50'))
    customer = Customer(name='Cust', name_ar='عميل', customer_type='regular',
                        phone='050', credit_limit=Decimal('10000'))
    supplier = Supplier(name='Supp', name_ar='مورد', phone='051')
    warehouse = Warehouse(name='Main', name_ar='رئيسي', code='WH-01',
                          location='Dubai', is_main=True, is_active=True)
    db.session.add_all([product, customer, supplier, warehouse])
    db.session.flush()

    from models.erp_modules import FiscalPeriod
    fp = FiscalPeriod(name=f'FY {date.today().year}', year=date.today().year,
                      period_type='annual', start_date=date(date.today().year, 1, 1),
                      end_date=date(date.today().year, 12, 31), is_closed=False)
    db.session.add(fp)
    db.session.commit()

    return {'owner': owner, 'manager': manager, 'product': product,
            'customer': customer, 'supplier': supplier, 'warehouse': warehouse}


# ===== CREDIT LIMIT =====

def test_sale_within_limit(seed):
    from services.sale_service import SaleService
    sale = SaleService.create_sale(
        customer=seed['customer'], seller=seed['manager'],
        lines_data=[{'product': seed['product'], 'quantity': 5, 'unit_price': Decimal('100')}],
        currency='AED')
    assert sale.total_amount == Decimal('500.000')


def test_sale_exceeding_limit_fails(seed):
    from services.sale_service import SaleService
    from extensions import db
    with pytest.raises(ValueError, match='تجاوز حد الائتمان'):
        SaleService.create_sale(
            customer=seed['customer'], seller=seed['manager'],
            lines_data=[{'product': seed['product'], 'quantity': 120, 'unit_price': Decimal('100')}],
            currency='AED')
    db.session.rollback()


def test_zero_credit_limit_allows_all(seed):
    from services.sale_service import SaleService
    from extensions import db
    seed['customer'].credit_limit = Decimal('0')
    db.session.commit()
    sale = SaleService.create_sale(
        customer=seed['customer'], seller=seed['manager'],
        lines_data=[{'product': seed['product'], 'quantity': 45, 'unit_price': Decimal('100')}],
        currency='AED')
    assert sale.total_amount == Decimal('4500.000')


# ===== FISCAL PERIOD =====

def test_sale_in_closed_period_fails(seed):
    from services.sale_service import SaleService
    from models.erp_modules import FiscalPeriod
    from extensions import db
    fp = FiscalPeriod.query.first()
    fp.close(seed['owner'].id)
    db.session.commit()
    with pytest.raises(ValueError, match='الفترة المالية الحالية مغلقة'):
        SaleService.create_sale(
            customer=seed['customer'], seller=seed['manager'],
            lines_data=[{'product': seed['product'], 'quantity': 1, 'unit_price': Decimal('100')}],
            currency='AED')
    db.session.rollback()


def test_fiscal_period_close_reopen(seed):
    from models.erp_modules import FiscalPeriod
    from extensions import db
    fp = FiscalPeriod.query.first()
    assert not fp.is_closed
    fp.close(seed['owner'].id)
    db.session.commit()
    assert fp.is_closed
    fp.reopen()
    db.session.commit()
    assert not fp.is_closed


# ===== QUOTATIONS =====

def test_create_quotation(seed):
    from services.erp_modules_service import QuotationService
    q = QuotationService.create_quotation(
        customer_id=seed['customer'].id, seller_id=seed['manager'].id,
        lines_data=[{'product_id': seed['product'].id, 'quantity': 10, 'unit_price': 100}],
        currency='AED', tax_rate=5)
    assert q.quotation_number.startswith('QT-')
    assert q.total_amount > Decimal('0')


def test_convert_quotation_to_sale(seed):
    from services.erp_modules_service import QuotationService
    from extensions import db
    q = QuotationService.create_quotation(
        customer_id=seed['customer'].id, seller_id=seed['manager'].id,
        lines_data=[{'product_id': seed['product'].id, 'quantity': 5, 'unit_price': 100}],
        currency='AED')
    q.status = 'accepted'
    db.session.commit()
    sale = QuotationService.convert_to_sale(q.id, seed['owner'].id)
    assert sale is not None
    assert q.status == 'converted'


# ===== PURCHASE ORDERS =====

def test_create_and_receive_po(seed):
    from services.erp_modules_service import PurchaseOrderService
    from extensions import db
    po = PurchaseOrderService.create_po(
        supplier_id=seed['supplier'].id, warehouse_id=seed['warehouse'].id,
        lines_data=[{'product_id': seed['product'].id, 'quantity': 20, 'unit_cost': 50}],
        user_id=seed['manager'].id)
    assert po.po_number.startswith('PO-')
    po.status = 'submitted'
    db.session.commit()
    PurchaseOrderService.approve_po(po.id, seed['owner'].id)
    purchase = PurchaseOrderService.receive_po(po.id, seed['manager'].id)
    assert purchase is not None
    assert po.status == 'received'


# ===== STOCK TRANSFERS =====

def test_stock_transfer(seed):
    from services.erp_modules_service import StockTransferService
    from models import Warehouse
    from extensions import db
    wh2 = Warehouse(name='Branch', name_ar='فرع', code='WH-02',
                    location='Abu Dhabi', is_active=True)
    db.session.add(wh2)
    db.session.commit()
    t = StockTransferService.create_transfer(
        from_warehouse_id=seed['warehouse'].id, to_warehouse_id=wh2.id,
        lines_data=[{'product_id': seed['product'].id, 'quantity': 10}],
        user_id=seed['manager'].id)
    assert t.transfer_number.startswith('TRF-')
    t.status = 'in_transit'
    db.session.commit()
    StockTransferService.receive_transfer(t.id, seed['manager'].id)
    assert t.status == 'received'


# ===== STOCK TAKE =====

def test_stock_take(seed):
    from services.erp_modules_service import StockTakeService
    st = StockTakeService.create_stocktake(
        warehouse_id=seed['warehouse'].id, user_id=seed['manager'].id)
    assert st.stocktake_number.startswith('STK-')
    assert len(st.items) > 0
    for item in st.items:
        item.counted_quantity = item.system_quantity + Decimal('5')
        item.calculate_variance()
    StockTakeService.complete_stocktake(st.id)
    assert st.status == 'completed'
    StockTakeService.approve_stocktake(st.id, seed['owner'].id)
    assert st.status == 'approved'


# ===== E-INVOICE =====

def test_einvoice(seed):
    from services.erp_modules_service import EInvoiceService
    from services.sale_service import SaleService
    sale = SaleService.create_sale(
        customer=seed['customer'], seller=seed['manager'],
        lines_data=[{'product': seed['product'], 'quantity': 3, 'unit_price': Decimal('100')}],
        currency='AED', tax_rate=5)
    einv = EInvoiceService.create_einvoice(sale.id)
    assert einv.invoice_number.startswith('EI-')
    assert einv.total_amount == Decimal('300.000')
    assert einv.tax_amount == Decimal('15.000')
    assert einv.json_payload is not None
    assert einv.xml_payload is not None


# ===== DUNNING =====

def test_dunning(seed):
    from services.erp_modules_service import DunningService
    from models import Sale
    from extensions import db
    sale = Sale(sale_number='S-OLD-001', customer_id=seed['customer'].id,
                seller_id=seed['manager'].id, warehouse_id=seed['warehouse'].id,
                sale_date=date.today() - timedelta(days=45),
                total_amount=Decimal('1000'), amount_base=Decimal('1000'),
                paid_amount=Decimal('0'), balance_due=Decimal('1000'),
                payment_status='unpaid', status='confirmed', currency='AED')
    db.session.add(sale)
    db.session.commit()
    letters = DunningService.check_overdue_accounts()
    assert len(letters) >= 1
    assert letters[0].days_overdue >= 45


# ===== LOT TRACKING =====

def test_lot_tracking(seed):
    from models.erp_modules import ProductLot
    from extensions import db
    lot = ProductLot(product_id=seed['product'].id, lot_number='LOT-001',
                     warehouse_id=seed['warehouse'].id, quantity=Decimal('100'),
                     cost_price=Decimal('50'),
                     manufacture_date=date.today() - timedelta(days=30),
                     expiry_date=date.today() + timedelta(days=365))
    db.session.add(lot)
    db.session.commit()
    assert lot.id is not None
    assert not lot.is_expired


# ===== BIN TRACKING =====

def test_bin_tracking(seed):
    from models.erp_modules import WarehouseBin, ProductBin
    from extensions import db
    b = WarehouseBin(warehouse_id=seed['warehouse'].id, code='A-01',
                     name='Bay 1', aisle='A', shelf='01', position='front', capacity=500)
    db.session.add(b)
    db.session.flush()
    pb = ProductBin(bin_id=b.id, product_id=seed['product'].id, stock_quantity=Decimal('25'))
    db.session.add(pb)
    db.session.commit()
    assert b.current_stock == 25
    assert b.full_code is not None
