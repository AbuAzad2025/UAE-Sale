"""
P0 tests — سلامة المخزون وأثر التدقيق (Inventory Integrity & Audit Trail)
=========================================================================

تغطي هذه الملف الإصلاحات P0:

* F1 — مجموع كميات حركات المخزون == product.current_stock بعد تعديل طرح،
       وأن مسار التسوية يجب أن يفشل مغلقاً (fail-closed) عند فشل القيد.
* F2 — منتج بلا تكلفة لا يمكن أن ينتج فاتورة إيراد بلا تكلفة.
* F3 — رصيد المستودع = المجموع البسيط للحركات، والـ API يردّ على
       'current_stock' و 'available' بالقيمة نفسها.
* F4 — مسار AI يمرّ عبر StockService/PaymentService (حركة + قيد + تدقيق).
* F6 — المرتجع يردّ المبلغ صافي خصم السطر ويعكس الضريبة على الأساس نفسه.
* F9 — مسار مسح الجداول يرفض الجداول المالية والتدقيقية ويسجّل سطر تدقيق
       قبل العملية المدمّرة (ويبقى السطر حتى لو فشلت العملية).
* F10 — استعادة قاعدة البيانات تكتب سجلها في ملف داخل instance/ قبل الاستعادة.
* F11 — /ai/analyze-margins يرفض 403 لدور بلا صلاحية عرض التكاليف.
* F12 — create_audit_log يلتزم ضمن معاملة المستدعي ويفشل مغلقاً.
* F7 — reconcile_inventory() يقيس الفرق بدل إخفائه.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from extensions import db
from models import (AuditLog, Product, Sale, SaleLine, StockMovement,
                    Warehouse)


# =====================================================================
# أدوات مساعدة
# =====================================================================

@pytest.fixture(scope='function')
def open_fiscal_period(db):
    """فترة مالية مفتوحة تغطي اليوم.

    حارس الفترة المالية (services/fiscal_period_guard.py) يرفض ترحيل أي
    مستند إلى تاريخ لا تغطيه فترة معرَّفة، فكل اختبار يُرحّل قيداً يحتاج
    هذه الفترة.
    """
    from models.erp_modules import FiscalPeriod

    today = date.today()
    period = FiscalPeriod(
        name=f'P0 {today.year}', year=today.year, period_type='annual',
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=1),
        is_closed=False,
    )
    db.session.add(period)
    db.session.commit()
    return period


@pytest.fixture(scope='function')
def two_warehouses(db):
    """مستودعان: الرئيسي ومستودع ثانوي (لاختبار رصيد مستودع بعينه)."""
    main = Warehouse(name='Main WH', name_ar='المستودع الرئيسي',
                      is_active=True, is_main=True)
    other = Warehouse(name='Second WH', name_ar='المستودع الثاني',
                      is_active=True, is_main=False)
    db.session.add_all([main, other])
    db.session.commit()
    return main, other


@pytest.fixture(scope='function')
def fresh_product(db, test_category):
    """منتج بمخزون صفر وحركات متسقة (Σ movements == current_stock)."""
    product = Product(
        name='P0 Widget', name_ar='قطعة P0', sku='SKU-P0-001',
        category_id=test_category.id,
        cost_price=Decimal('10.000'), regular_price=Decimal('25.000'),
        current_stock=Decimal('0'), min_stock_alert=Decimal('1'),
        is_active=True,
    )
    db.session.add(product)
    db.session.commit()
    return product


def _movement_sum(product_id):
    total = db.session.query(
        db.func.coalesce(db.func.sum(StockMovement.quantity), 0)
    ).filter(StockMovement.product_id == product_id).scalar()
    return Decimal(str(total or 0))


def _login(client, user, password):
    client.post('/auth/login', data={
        'username': user.username, 'password': password,
    }, follow_redirects=True)


# =====================================================================
# F1 — مجموع الحركات == الرصيد
# =====================================================================

class TestStockMovementSign:
    def test_sum_of_movements_equals_current_stock_after_subtract(
            self, client, db, owner_user, fresh_product, two_warehouses,
            open_fiscal_period):
        """طرح 30 من 100: الرصيد 70 ومجموع الحركات 70 — لا 130."""
        from services.stock_service import StockService

        main, _other = two_warehouses
        StockService.add_stock(fresh_product.id, Decimal('100'),
                                reference_type='Purchase',
                                warehouse_id=main.id)
        db.session.commit()
        assert fresh_product.current_stock == Decimal('100')
        assert _movement_sum(fresh_product.id) == Decimal('100')

        _login(client, owner_user, 'OwnerPass123!')
        resp = client.post(f'/products/{fresh_product.id}/adjust-stock', data={
            'adjustment_type': 'subtract', 'quantity': '30',
        })
        assert resp.get_json()['success'] is True, resp.get_json()

        db.session.refresh(fresh_product)
        assert fresh_product.current_stock == Decimal('70')
        # THE INVARIANT: the movements carry the SIGN of the adjustment.
        assert _movement_sum(fresh_product.id) == Decimal('70')
        assert _movement_sum(fresh_product.id) == fresh_product.current_stock

        moves = StockMovement.query.filter_by(
            product_id=fresh_product.id, movement_type='adjustment').all()
        assert len(moves) == 1
        assert Decimal(str(moves[0].quantity)) == Decimal('-30')

    def test_adjustment_posts_a_gl_entry(self, client, db, owner_user,
                                         fresh_product, two_warehouses,
                                         open_fiscal_period):
        """التسوية اليدوية تُرحَّل في الأستاذ العام (Dr 1140 / Cr 5150)."""
        from models import GLAccount, GLJournalEntry, GLJournalLine
        from services.stock_service import StockService

        main, _other = two_warehouses
        StockService.add_stock(fresh_product.id, Decimal('100'),
                                warehouse_id=main.id)
        db.session.commit()

        before = GLJournalEntry.query.count()
        _login(client, owner_user, 'OwnerPass123!')
        resp = client.post(f'/products/{fresh_product.id}/adjust-stock', data={
            'adjustment_type': 'add', 'quantity': '15',
        })
        assert resp.get_json()['success'] is True, resp.get_json()

        assert GLJournalEntry.query.count() > before
        inv = GLAccount.query.filter_by(code='1140').first()
        lines = GLJournalLine.query.filter_by(account_id=inv.id).all()
        assert lines, 'the inventory account carries no line for the adjustment'
        assert sum(Decimal(str(l.amount_base)) for l in lines) == Decimal('150')

    def test_gl_failure_rolls_the_stock_back(self, db, monkeypatch,
                                             fresh_product, two_warehouses):
        """fail-closed: إذا تعذّر الترحيل فلا يبقى المخزون متحركاً."""
        from services import gl_service
        from services.stock_service import StockService

        main, _other = two_warehouses

        def _boom(*args, **kwargs):
            raise RuntimeError('GL down')

        monkeypatch.setattr(gl_service.GLService, 'post_entry', staticmethod(_boom))

        with pytest.raises(Exception):
            StockService.adjust_stock(fresh_product.id, Decimal('-5'),
                                      notes='test', warehouse_id=main.id)
        db.session.rollback()
        db.session.refresh(fresh_product)
        assert fresh_product.current_stock == Decimal('0')
        assert _movement_sum(fresh_product.id) == Decimal('0')


# =====================================================================
# F2 — لا فاتورة بلا تكلفة
# =====================================================================

class TestZeroCostGuard:
    def test_require_cost_basis_names_the_product(self, db):
        from services.stock_service import StockService
        from utils.errors import ValidationError

        product = Product(name='بلا تكلفة', sku='SKU-NOCOST-1',
                          regular_price=Decimal('100'),
                          cost_price=Decimal('0'), current_stock=Decimal('5'),
                          is_active=True)
        db.session.add(product)
        db.session.commit()

        with pytest.raises(ValidationError) as exc:
            StockService.require_cost_basis(product)
        message = str(exc.value)
        assert 'بلا تكلفة' in message
        assert 'SKU-NOCOST-1' in message

    def test_ai_sale_refuses_a_zero_cost_product(self, db, owner_user,
                                                  test_customer):
        """مسار AI: منتج بلا تكلفة ⇒ لا فاتورة إيراد بلا تكلفة."""
        from routes.ai import _ai_create_sale
        from utils.errors import ValidationError

        product = Product(name='صنف بلا تكلفة', sku='SKU-ZERO-2',
                          regular_price=Decimal('50'),
                          cost_price=Decimal('0'), current_stock=Decimal('10'),
                          is_active=True)
        db.session.add(product)
        db.session.commit()

        with pytest.raises(ValidationError) as exc:
            _ai_create_sale(user=owner_user, customer=test_customer,
                            product=product, quantity=Decimal('2'))
        assert 'صنف بلا تكلفة' in str(exc.value)
        assert Sale.query.filter_by(customer_id=test_customer.id).count() == 0
        assert _movement_sum(product.id) == Decimal('0')

    def test_ai_sale_snapshots_the_cost_and_moves_the_stock(
            self, db, owner_user, test_customer, two_warehouses,
            open_fiscal_period):
        """فاتورة AI: حركة مخزون + لقطة تكلفة على سطر البيع."""
        from routes.ai import _ai_create_sale
        from services.stock_service import StockService

        main, _other = two_warehouses
        product = Product(name='صنف بسعر', sku='SKU-COST-3',
                          regular_price=Decimal('50'),
                          cost_price=Decimal('20'), current_stock=Decimal('0'),
                          is_active=True)
        db.session.add(product)
        db.session.commit()
        StockService.add_stock(product.id, Decimal('10'),
                                warehouse_id=main.id)
        db.session.commit()

        sale = _ai_create_sale(user=owner_user, customer=test_customer,
                               product=product, quantity=Decimal('2'))

        line = SaleLine.query.filter_by(sale_id=sale.id).one()
        assert Decimal(str(line.cost_price)) == Decimal('20')
        assert _movement_sum(product.id) == Decimal('8')
        db.session.refresh(product)
        assert product.current_stock == Decimal('8')


# =====================================================================
# F3 — رصيد المستودع
# =====================================================================

class TestWarehouseStockApi:
    def test_foreign_warehouse_stock_is_the_plain_sum_of_its_movements(
            self, client, db, owner_user, fresh_product, two_warehouses):
        """مستودع فيه شراء 40 وبيع 10 ⇒ 30 (لا 50 ولا 130)."""
        from services.stock_service import StockService

        main, other = two_warehouses
        StockService.add_stock(fresh_product.id, Decimal('40'),
                                warehouse_id=other.id)
        StockService.remove_stock(fresh_product.id, Decimal('10'),
                                   warehouse_id=other.id)
        db.session.commit()

        assert StockService.get_warehouse_quantity(
            fresh_product.id, other.id) == Decimal('30')

        _login(client, owner_user, 'OwnerPass123!')
        resp = client.get(
            f'/api/products/{fresh_product.id}/info?warehouse_id={other.id}')
        assert resp.status_code == 200
        body = resp.get_json()
        # The sale movement is NEGATIVE, so "received - issued" used to
        # report 50 here.
        assert body['current_stock'] == 30
        assert body['available'] == 30

    def test_info_endpoint_exposes_available_and_current_stock(
            self, client, db, owner_user, fresh_product, two_warehouses):
        _login(client, owner_user, 'OwnerPass123!')
        resp = client.get(f'/api/products/{fresh_product.id}/info')
        body = resp.get_json()
        assert 'available' in body
        assert body['available'] == body['current_stock']


# =====================================================================
# F6 — المرتجع يردّ الصافي ويعكس الضريبة على الأساس نفسه
# =====================================================================

class TestReturnDiscount:
    def _discounted_sale(self, db, owner_user, test_customer, fresh_product):
        sale = Sale(
            sale_number='S-P0-DISC', customer_id=test_customer.id,
            seller_id=owner_user.id, total_amount=Decimal('450.000'),
            amount_base=Decimal('450.000'), paid_amount=Decimal('0'),
            paid_amount_base=Decimal('0'), balance_due=Decimal('450.000'),
            currency='AED', exchange_rate=Decimal('1'), tax_rate=Decimal('5'),
            payment_status='unpaid', status='confirmed', is_active=True,
        )
        db.session.add(sale)
        db.session.flush()
        line = SaleLine(
            sale_id=sale.id, product_id=fresh_product.id,
            quantity=Decimal('5'), unit_price=Decimal('100'),
            discount_percent=Decimal('10'), line_total=Decimal('450.000'),
            cost_price=Decimal('20'),
        )
        db.session.add(line)
        db.session.commit()
        return sale, line

    def test_return_refunds_the_discounted_amount_and_reverses_tax_on_it(
            self, db, owner_user, test_customer, fresh_product,
            open_fiscal_period):
        """5 × 100 بخصم 10% ⇒ الإيراد 450 والاسترداد 450 (لا 500)."""
        from services.return_service import ReturnService

        sale, line = self._discounted_sale(db, owner_user, test_customer,
                                           fresh_product)
        ret = ReturnService.create_return(
            sale_id=sale.id,
            return_lines_data=[{'sale_line_id': line.id, 'quantity': 5}],
            user_id=owner_user.id,
        )
        db.session.refresh(ret)
        assert ret.total_amount == Decimal('450.000')
        # الضريبة تُعكس على الأساس المخصم (450) لا على 500 ⇒ 22.5
        assert ret.refund_amount == Decimal('472.500')

    def test_pending_return_does_not_consume_the_returnable_quantity(
            self, db, owner_user, test_sale, test_product,
            open_fiscal_period):
        """المرتجع المعلّق (غير المعتمد) لا يستهلك الكمية القابلة للإرجاع."""
        from models import ProductReturn, ProductReturnLine
        from services.return_service import ReturnService

        line = SaleLine.query.filter_by(sale_id=test_sale.id).first()

        pending = ProductReturn(
            return_number='R-P0-PENDING', sale_id=test_sale.id,
            customer_id=test_sale.customer_id, currency='AED',
            exchange_rate=Decimal('1'), total_amount=Decimal('50'),
            refund_amount=Decimal('50'), amount_base=Decimal('50'),
            status='pending',
        )
        db.session.add(pending)
        db.session.flush()
        db.session.add(ProductReturnLine(
            return_id=pending.id, sale_line_id=line.id,
            product_id=test_product.id, quantity=Decimal('1'),
            unit_price=Decimal('50'), line_total=Decimal('50'),
        ))
        db.session.commit()

        # The pending return must NOT block the approved one.
        ret = ReturnService.create_return(
            sale_id=test_sale.id,
            return_lines_data=[{'sale_line_id': line.id, 'quantity': 1}],
            user_id=owner_user.id,
        )
        assert ret.id is not None


# =====================================================================
# F9 — مسح الجداول
# =====================================================================

class TestTruncateTableProtection:
    @pytest.mark.parametrize('table_name', [
        'audit_logs', 'gl_journal_entries', 'sales', 'payments',
        'purchases', 'receipts', 'journal_entry_audits', 'error_logs',
    ])
    def test_financial_and_audit_tables_cannot_be_truncated(
            self, client, db, owner_user, table_name):
        _login(client, owner_user, 'OwnerPass123!')
        before = db.session.execute(
            db.text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()

        resp = client.post('/owner/truncate-table', data={
            'table_name': table_name, 'confirm': 'YES_DELETE_ALL',
        }, follow_redirects=False)
        assert resp.status_code in (302, 303)

        after = db.session.execute(
            db.text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
        assert after == before, f'{table_name} was emptied'

    def test_truncate_writes_an_audit_row(self, client, db, owner_user):
        from models import ProductCategory

        db.session.add(ProductCategory(name='P0 Category', is_active=True))
        db.session.commit()

        _login(client, owner_user, 'OwnerPass123!')
        resp = client.post('/owner/truncate-table', data={
            'table_name': 'product_categories', 'confirm': 'YES_DELETE_ALL',
        }, follow_redirects=False)
        assert resp.status_code in (302, 303)

        log = AuditLog.query.filter_by(action='truncate_table').order_by(
            AuditLog.id.desc()).first()
        assert log is not None, 'the truncate was not audited'
        assert log.table_name == 'database'
        assert log.changes['table'] == 'product_categories'

    def test_audit_row_survives_a_failing_delete(self, client, db, owner_user,
                                                  monkeypatch):
        """السجل يُكتب قبل العملية المدمّرة، فيبقى حتى لو فشلت."""
        import routes.owner as owner_module
        from models import ProductCategory

        db.session.add(ProductCategory(name='P0 Category 2', is_active=True))
        db.session.commit()

        def _explode(*args, **kwargs):
            raise RuntimeError('simulated DELETE failure')

        monkeypatch.setattr(owner_module, 'text', _explode)

        _login(client, owner_user, 'OwnerPass123!')
        resp = client.post('/owner/truncate-table', data={
            'table_name': 'product_categories', 'confirm': 'YES_DELETE_ALL',
        }, follow_redirects=False)
        assert resp.status_code in (302, 303)

        log = AuditLog.query.filter_by(action='truncate_table').order_by(
            AuditLog.id.desc()).first()
        assert log is not None, (
            'the audit row was lost when the destructive statement failed')
        assert log.changes['table'] == 'product_categories'


# =====================================================================
# F10 — تدقيق الاستعادة
# =====================================================================

class TestRestoreAudit:
    def test_restore_writes_its_record_to_instance_before_restoring(
            self, client, db, owner_user, tmp_path, monkeypatch):
        import json

        import utils.helpers as helpers_module
        from services.backup_service import BackupService

        monkeypatch.setattr(helpers_module, 'instance_audit_dir',
                            lambda: str(tmp_path))
        monkeypatch.setattr(BackupService, 'verify_backup',
                            staticmethod(lambda filename: True))

        calls = {'restored': False}

        def _fake_restore(filename):
            calls['restored'] = True
            # The audit file must ALREADY exist when the restore starts.
            audit_file = tmp_path / 'audit_trail.jsonl'
            assert audit_file.exists(), (
                'the restore started without a durable audit record')
            return True

        monkeypatch.setattr(BackupService, 'restore_backup',
                            staticmethod(_fake_restore))

        _login(client, owner_user, 'OwnerPass123!')
        resp = client.post('/owner/backups/restore/p0-test.dump', data={
            'confirm_password': 'OwnerPass123!',
        }, follow_redirects=False)
        assert resp.status_code in (302, 303)
        assert calls['restored'] is True

        audit_file = tmp_path / 'audit_trail.jsonl'
        assert audit_file.exists()
        records = [json.loads(line) for line in
                   audit_file.read_text(encoding='utf-8').splitlines() if line]
        actions = [r.get('action') for r in records]
        assert 'restore_backup' in actions
        record = [r for r in records if r.get('action') == 'restore_backup'][0]
        assert record.get('backup_filename') == 'p0-test.dump'

    def test_delete_backup_is_audited_too(self, client, db, owner_user,
                                           tmp_path, monkeypatch):
        import json

        import utils.helpers as helpers_module
        from services.backup_service import BackupService

        monkeypatch.setattr(helpers_module, 'instance_audit_dir',
                            lambda: str(tmp_path))
        monkeypatch.setattr(BackupService, 'list_backups', staticmethod(
            lambda: [{'filename': 'p0-test.dump'}]))
        monkeypatch.setattr(BackupService, 'delete_backup',
                            staticmethod(lambda filename: True))

        _login(client, owner_user, 'OwnerPass123!')
        resp = client.post('/owner/backups/delete', data={
            'filename': 'p0-test.dump',
        }, follow_redirects=False)
        assert resp.status_code in (302, 303)

        audit_file = tmp_path / 'audit_trail.jsonl'
        assert audit_file.exists()
        records = [json.loads(line) for line in
                   audit_file.read_text(encoding='utf-8').splitlines() if line]
        assert any(r.get('action') == 'delete_backup' for r in records)


# =====================================================================
# F11 — تسريب التكاليف عبر AI
# =====================================================================

class TestAiCostVisibility:
    def test_analyze_margins_is_403_without_cost_permission(
            self, client, db, owner_user, seller_user):
        _login(client, seller_user, 'SellerPass123!')
        resp = client.get('/ai/analyze-margins')
        assert resp.status_code == 403

    def test_analyze_margins_is_200_for_the_owner(self, client, db, owner_user):
        _login(client, owner_user, 'OwnerPass123!')
        resp = client.get('/ai/analyze-margins')
        assert resp.status_code == 200

    def test_optimize_inventory_is_403_without_cost_permission(
            self, client, db, owner_user, seller_user):
        _login(client, seller_user, 'SellerPass123!')
        resp = client.get('/ai/optimize-inventory')
        assert resp.status_code == 403


# =====================================================================
# F12 — سجل التدقيق يفشل مغلقاً
# =====================================================================

class TestAuditLogContract:
    def test_audit_failure_raises_and_persists_nothing(self, app, db):
        """حمولة غير قابلة للتسلسل ⇒ خطأ (لا ابتلاع) ولا صف محفوظ."""
        from utils.helpers import create_audit_log

        with app.test_request_context('/'):
            with pytest.raises(Exception):
                create_audit_log('delete', changes=object())
        db.session.rollback()
        assert AuditLog.query.count() == 0

    def test_audit_row_is_persisted_by_the_caller_commit(self, app, db):
        """السجل جزء من معاملة المستدعي: يُثبَّت ب.commit المستدعي فقط."""
        from utils.helpers import create_audit_log

        with app.test_request_context('/'):
            create_audit_log('create', table_name='products', record_id=1,
                             changes={'x': '1'}, commit=False)
            # A rollback of the caller's transaction must take the audit row
            # with it — proof that the row is NOT committed on its own.
            db.session.rollback()
            assert AuditLog.query.count() == 0, (
                'the audit row must not survive the rollback of the caller')

            create_audit_log('create', table_name='products', record_id=1,
                             changes={'x': '1'}, commit=False)
            db.session.commit()
            assert AuditLog.query.count() == 1


# =====================================================================
# F7 — قياس الفرق
# =====================================================================

class TestInventoryReconciliation:
    def test_reconcile_inventory_measures_the_divergence(self, db,
                                                         fresh_product):
        """الفرق بين الحركات والرصيد والأستاذ يُقاس ولا يُخفى."""
        from services.inventory_reconciliation import reconcile_inventory

        product = fresh_product
        product.current_stock = Decimal('100')   # لا حركة تقابلها
        db.session.commit()

        report = reconcile_inventory()
        row = [r for r in report['products']
               if r['product_id'] == product.id][0]

        assert row['quantity_from_movements'] == Decimal('0.000')
        assert row['current_stock'] == Decimal('100.000')
        assert row['difference'] == Decimal('100.000')
        assert row['valuation_at_cost_price'] == Decimal('0.00')
        # The GL carries nothing for this product, so the divergence is 0
        # against the (empty) valuation but is REPORTED, not hidden.
        assert 'gl_control_balance' in row
        assert 'gl_difference' in row
        assert not report['balanced']
        assert report['breaks']

    def test_reconcile_inventory_reports_a_matching_product(self, db,
                                                            fresh_product,
                                                            two_warehouses):
        from services.inventory_reconciliation import reconcile_inventory
        from services.stock_service import StockService

        main, _other = two_warehouses
        StockService.add_stock(fresh_product.id, Decimal('40'),
                                warehouse_id=main.id)
        db.session.commit()

        report = reconcile_inventory()
        row = [r for r in report['products']
               if r['product_id'] == fresh_product.id][0]
        assert row['quantity_from_movements'] == Decimal('40.000')
        assert row['current_stock'] == Decimal('40.000')
        assert row['difference'] == Decimal('0.000')
        assert row['valuation_at_cost_price'] == Decimal('400.00')
