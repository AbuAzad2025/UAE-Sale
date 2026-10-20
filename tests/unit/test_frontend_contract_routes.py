"""Tests for the backend routes that back the previously-dead frontend calls.

static/js called ten endpoints that did not exist, so every one of those
features failed with a 404. These tests pin the contract each frontend caller
depends on, so the routes cannot silently disappear again.
"""
import io
import json

import pytest
from PIL import Image


@pytest.fixture
def owner_login(client, login_owner, owner_user):
    """المالك مسجّل الدخول - يملك كل الصلاحيات."""
    return owner_user


@pytest.fixture(autouse=True)
def cleanup_uploaded_images():
    """احذف الصور التي رفعتها الاختبارات.

    رفع صورة منتج يكتب ملفاً في static/products/، وهو مكان صور المنتجات
    التي جزء من بيانات الكتالوج وتُدفع إلى git. الاختبار لا يجوز أن يترك
    أثراً في المستودع.
    """
    import os
    from flask import current_app

    yield

    try:
        static_dir = current_app.static_folder
        products_dir = os.path.join(static_dir, 'products')
        if not os.path.isdir(products_dir):
            return
        for name in os.listdir(products_dir):
            if name.startswith(('p_', 'photo_')) and name.endswith('.jpg'):
                try:
                    os.remove(os.path.join(products_dir, name))
                except OSError:
                    pass
    except Exception:
        pass


# ── /api/search/<target> ────────────────────────────────────────────────────

class TestSearchTarget:
    def test_returns_html_fragment_and_rows(self, client, owner_login,
                                           test_customer):
        r = client.get('/api/search/customers?q=' + test_customer.name[:4])
        assert r.status_code == 200
        body = r.get_json()
        assert 'html' in body
        assert 'results' in body
        assert body['results'], 'the seeded customer should be found'
        assert body['html'], 'the dropdown fragment should not be empty'
        assert test_customer.name in body['html']

    def test_html_is_escaped(self, client, owner_login, db):
        """اسم عميل فيه HTML يجب أن يُهرَّب في الجزء المُعاد."""
        from models import Customer
        from decimal import Decimal
        db.session.add(Customer(
            name='<script>alert(1)</script>', name_ar='x',
            customer_type='regular', balance=Decimal('0'), is_active=True))
        db.session.commit()
        r = client.get('/api/search/customers?q=script')
        assert r.status_code == 200
        html = r.get_json()['html']
        assert '<script>' not in html
        assert '&lt;script&gt;' in html

    def test_unknown_target_is_400(self, client, owner_login):
        r = client.get('/api/search/not_a_thing?q=x')
        assert r.status_code == 400
        assert r.get_json()['success'] is False

    def test_requires_login(self, client):
        """المسار يتطلب جلسة - لا يستجيب لزائر."""
        r = client.get('/api/search/customers?q=x')
        assert r.status_code in (302, 303, 401, 403)

    def test_existing_query_form_still_works(self, client, owner_login,
                                              test_customer):
        """المسار القديم /api/search?type=... يجب أن يبقى كما هو."""
        r = client.get('/api/search?type=customers&q='
                       + test_customer.name[:4])
        assert r.status_code == 200
        body = r.get_json()
        assert body['results']
        # 'html' اختياري في المسار القديم حتى لا نكسر Consumه الحالي.
        assert 'has_more' in body


# ── /api/inline-edit/<type>/<id> ───────────────────────────────────────────

class TestInlineEdit:
    def test_updates_an_allowed_field(self, client, owner_login, test_customer):
        r = client.patch(
            f'/api/inline-edit/customer/{test_customer.id}',
            json={'field': 'phone', 'value': '+971500000123'})
        assert r.status_code == 200
        body = r.get_json()
        assert body['success'] is True
        assert body['field'] == 'phone'

        from models import Customer
        from extensions import db
        db.session.expire_all()
        assert Customer.query.get(test_customer.id).phone == '+971500000123'

    def test_rejects_a_field_outside_the_allowlist(self, client, owner_login,
                                                   test_customer):
        """قاعدة الأمان: لا يُسمح بتعديل أي عمود - فقط المسموح."""
        r = client.patch(
            f'/api/inline-edit/customer/{test_customer.id}',
            json={'field': 'balance', 'value': 999999})
        assert r.status_code == 400
        assert r.get_json()['code'] == 'FIELD_NOT_EDITABLE'

    def test_cannot_edit_tenant_id(self, client, owner_login, test_customer):
        r = client.patch(
            f'/api/inline-edit/customer/{test_customer.id}',
            json={'field': 'tenant_id', 'value': 999})
        assert r.status_code == 400

    def test_unknown_entity_type_is_400(self, client, owner_login):
        r = client.patch('/api/inline-edit/nonsense/1',
                          json={'field': 'name', 'value': 'x'})
        assert r.status_code == 400
        assert r.get_json()['success'] is False

    def test_decimal_field_is_coerced(self, client, owner_login, test_product):
        r = client.patch(
            f'/api/inline-edit/product/{test_product.id}',
            json={'field': 'regular_price', 'value': '42.50'})
        assert r.status_code == 200
        from decimal import Decimal
        from models import Product
        from extensions import db
        db.session.expire_all()
        assert Product.query.get(test_product.id).regular_price == Decimal(
            '42.50')

    def test_invalid_decimal_is_rejected(self, client, owner_login,
                                         test_product):
        r = client.patch(
            f'/api/inline-edit/product/{test_product.id}',
            json={'field': 'regular_price', 'value': 'not-a-number'})
        assert r.status_code == 400
        assert r.get_json()['code'] == 'INVALID_VALUE'

    def test_missing_row_is_404(self, client, owner_login):
        r = client.patch('/api/inline-edit/customer/99999999',
                         json={'field': 'name', 'value': 'x'})
        assert r.status_code == 404

    def test_requires_permission(self, client, db, owner_user, test_customer):
        """مستخدم بلا صلاحية manage_customers لا يعدّل عميلاً."""
        from models import Role, User
        role = Role(name='NoCust', name_ar='بلا', slug='nocust', permissions=[])
        db.session.add(role)
        db.session.flush()
        weak = User(username='weakuser', email='weak@test.com',
                    password_hash=owner_user.password_hash, role_id=role.id,
                    tenant_id=owner_user.tenant_id, is_active=True)
        db.session.add(weak)
        db.session.commit()
        client.post('/auth/login', data={
            'username': 'weakuser', 'password': 'OwnerPass123!'},
            follow_redirects=True)

        r = client.patch(
            f'/api/inline-edit/customer/{test_customer.id}',
            json={'field': 'phone', 'value': '+971000000000'})
        assert r.status_code == 403
        assert r.get_json()['code'] == 'PERMISSION_DENIED'


# ── /api/products/<id>/info ────────────────────────────────────────────────

class TestProductInfo:
    def test_returns_product_with_stock(self, client, owner_login,
                                        test_product):
        r = client.get(f'/api/products/{test_product.id}/info')
        assert r.status_code == 200
        body = r.get_json()
        assert body['success'] is True
        assert body['id'] == test_product.id
        assert body['sku'] == test_product.sku
        assert 'current_stock' in body
        assert 'default_price' in body

    def test_unknown_product_is_404(self, client, owner_login):
        assert client.get('/api/products/99999999/info').status_code == 404

    def test_cost_hidden_without_permission(self, client, login_seller,
                                            seller_user, test_product):
        body = client.get(f'/api/products/{test_product.id}/info').get_json()
        assert body['cost_price'] is None


# ── /payments/search-entities ───────────────────────────────────────────────

class TestSearchEntities:
    def test_returns_an_array(self, client, owner_login, test_customer):
        r = client.get('/payments/search-entities?type=customers&q='
                        + test_customer.name[:3])
        assert r.status_code == 200
        body = r.get_json()
        assert isinstance(body, list)
        assert body, 'the seeded customer should be suggested'
        first = body[0]
        # static/js/payments.js يقرأ result.id و result.display
        assert 'id' in first
        assert 'display' in first

    def test_empty_query_returns_empty_list(self, client, owner_login):
        r = client.get('/payments/search-entities?type=customers&q=')
        assert r.status_code == 200
        assert r.get_json() == []

    def test_suppliers_type(self, client, owner_login, db):
        from models import Supplier
        db.session.add(Supplier(name='Unique Supplier Co', name_ar='م',
                                 is_active=True))
        db.session.commit()
        r = client.get('/payments/search-entities?type=suppliers&q=Unique')
        assert r.status_code == 200
        body = r.get_json()
        assert any(row['display'] == 'Unique Supplier Co' for row in body)


# ── /payments/archive/<id> ──────────────────────────────────────────────────

class TestPaymentArchive:
    def test_archives_a_payment(self, client, owner_login, db):
        from models import Payment
        from decimal import Decimal
        pay = Payment(payment_number='ARC-JSON-1', amount=Decimal('10'),
                      amount_base=Decimal('10'), currency='AED',
                      exchange_rate=Decimal('1'), direction='outgoing',
                      payment_type='payment', payment_method='cash')
        db.session.add(pay)
        db.session.commit()

        r = client.post(f'/payments/archive/{pay.id}',
                         data={'reason': 'اختبار JSON'})
        assert r.status_code == 200
        body = r.get_json()
        assert body['status'] == 'success'
        assert body['ok'] is True

        from models import ArchivedRecord
        assert ArchivedRecord.query.filter_by(
            table_name='payments', record_id=pay.id).first() is not None

    def test_missing_record_is_404(self, client, owner_login):
        r = client.post('/payments/archive/99999999', data={'reason': 'x'})
        assert r.status_code == 404

    def test_requires_permission(self, client, login_seller, seller_user):
        r = client.post('/payments/archive/1', data={'reason': 'x'})
        assert r.status_code == 403


# ── /reports/api/model_fields ───────────────────────────────────────────────

class TestModelFields:
    def test_returns_the_three_lists(self, client, owner_login):
        r = client.get('/reports/api/model_fields?model=sales')
        assert r.status_code == 200
        body = r.get_json()
        for key in ('columns', 'date_fields', 'all_fields'):
            assert key in body
        assert body['columns'], 'sales must expose some columns'
        assert 'sale_number' in body['columns']
        assert 'sale_date' in body['date_fields']
        assert set(body['date_fields']).issubset(set(body['all_fields']))

    def test_unknown_model_is_400(self, client, owner_login):
        r = client.get('/reports/api/model_fields?model=nope')
        assert r.status_code == 400
        body = r.get_json()
        assert body['columns'] == []

    def test_requires_permission(self, client, login_seller, seller_user):
        r = client.get('/reports/api/model_fields?model=sales')
        assert r.status_code == 403


# ── /warehouse/api/upload_product_image ─────────────────────────────────────

def _png_bytes(size=(40, 30)):
    buf = io.BytesIO()
    Image.new('RGB', size, (200, 30, 30)).save(buf, 'PNG')
    buf.seek(0)
    return buf


class TestProductImageUpload:
    def test_uploads_and_returns_urls(self, client, owner_login, tmp_path,
                                       app):
        data = {
            'file': (io.BytesIO(_png_bytes().getvalue()), 'photo.png'),
            'subdir': 'products',
            'max_side': '1200',
            'quality': '82',
        }
        r = client.post('/warehouse/api/upload_product_image',
                        data=data, content_type='multipart/form-data')
        assert r.status_code == 200, r.get_data(as_text=True)[:300]
        body = r.get_json()
        assert body['ok'] is True
        assert body['url']
        assert body['thumb_url']
        assert body['url'] != body['thumb_url']

        import os
        from flask import current_app
        assert os.path.exists(
            os.path.join(current_app.static_folder, body['url']))
        assert os.path.exists(
            os.path.join(current_app.static_folder, body['thumb_url']))

    def test_rejects_a_non_image(self, client, owner_login):
        """ملف بامتداد صورة لكنه ليس صورة - يجب أن يُرفض."""
        data = {
            'file': (io.BytesIO(b'not an image at all'), 'evil.png'),
        }
        r = client.post('/warehouse/api/upload_product_image',
                        data=data, content_type='multipart/form-data')
        assert r.status_code == 400
        assert r.get_json()['ok'] is False

    def test_missing_file_is_400(self, client, owner_login):
        r = client.post('/warehouse/api/upload_product_image',
                        data={}, content_type='multipart/form-data')
        assert r.status_code == 400

    def test_requires_permission(self, client, db, owner_user):
        """مستخدم بلا صلاحية manage_products لا يرفع صورة."""
        from models import Role, User
        role = Role(name='NoProd', name_ar='بلا', slug='noprod', permissions=[])
        db.session.add(role)
        db.session.flush()
        weak = User(username='weakprod', email='weakp@test.com',
                    password_hash=owner_user.password_hash, role_id=role.id,
                    tenant_id=owner_user.tenant_id, is_active=True)
        db.session.add(weak)
        db.session.commit()
        client.post('/auth/login', data={
            'username': 'weakprod', 'password': 'OwnerPass123!'},
            follow_redirects=True)

        data = {'file': (io.BytesIO(_png_bytes().getvalue()), 'p.png')}
        r = client.post('/warehouse/api/upload_product_image',
                        data=data, content_type='multipart/form-data')
        assert r.status_code == 403

    def test_subdir_cannot_escape_the_static_folder(self, client,
                                                     owner_login):
        """المجلد الفرعي من الطلب - قائمة بيضاء فقط."""
        data = {
            'file': (io.BytesIO(_png_bytes().getvalue()), 'p.png'),
            'subdir': '../../etc',
        }
        r = client.post('/warehouse/api/upload_product_image',
                        data=data, content_type='multipart/form-data')
        assert r.status_code == 400
        assert r.get_json()['ok'] is False

    def test_allowed_subdir_is_used(self, client, owner_login):
        data = {
            'file': (io.BytesIO(_png_bytes().getvalue()), 'p.png'),
            'subdir': 'products',
        }
        r = client.post('/warehouse/api/upload_product_image',
                        data=data, content_type='multipart/form-data')
        assert r.status_code == 200
        assert r.get_json()['url'].startswith('products/')


# ── /payment-vault/lock|unlock/<id> ─────────────────────────────────────────

class TestVaultJsonRoutes:
    def test_lock_requires_owner(self, client, login_seller, seller_user):
        r = client.post('/payment-vault/lock/1')
        assert r.status_code == 403
        assert r.get_json()['success'] is False

    def test_lock_with_wrong_id_is_404(self, client, owner_login, db):
        from models import PaymentVault
        vault = PaymentVault.query.first()
        if vault is None:
            pytest.skip('no vault in this fixture set')
        r = client.post(f'/payment-vault/lock/{vault.id + 9999}')
        assert r.status_code == 404

    def test_unlock_requires_a_password(self, client, owner_login, db):
        from models import PaymentVault
        vault = PaymentVault.query.first()
        if vault is None:
            pytest.skip('no vault in this fixture set')
        r = client.post(f'/payment-vault/unlock/{vault.id}', data={})
        assert r.status_code == 400
        assert r.get_json()['success'] is False

    def test_unlock_with_wrong_password_is_401(self, client, owner_login, db):
        from models import PaymentVault
        vault = PaymentVault.query.first()
        if vault is None:
            pytest.skip('no vault in this fixture set')
        r = client.post(f'/payment-vault/unlock/{vault.id}',
                         json={'password': 'definitely-wrong'})
        assert r.status_code == 401
        assert r.get_json()['success'] is False