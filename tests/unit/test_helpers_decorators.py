"""Unit tests for utils/helpers.py and utils/decorators.py."""

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from flask import get_flashed_messages
from flask_login import login_user
from werkzeug.exceptions import Forbidden, NotFound

import utils.decorators as decorators
from utils.helpers import (
    allowed_file,
    calculate_discount,
    calculate_vat,
    convert_currency,
    create_audit_log,
    format_currency,
    format_currency_display,
    generate_barcode,
    generate_number,
    generate_sku,
    get_next_number,
    save_uploaded_file,
    timeago,
)

YEAR = datetime.now().year


class FakeUpload:
    def __init__(self, filename, content=b'data', size=None):
        self.filename = filename
        self.content = content
        self.size = len(content) if size is None else size
        self.saved_to = None

    def seek(self, offset, whence=0):
        self.pos = offset

    def tell(self):
        return self.size

    def read(self, n=-1):
        return self.content if n < 0 else self.content[:n]

    def save(self, dst):
        self.saved_to = dst
        with open(dst, 'wb') as fh:
            fh.write(self.content)


def make_sale(db, number):
    from models import Sale

    sale = Sale(
        sale_number=number,
        total_amount=Decimal('10.000'),
        amount_base=Decimal('10.000'),
        paid_amount=Decimal('0'),
        paid_amount_base=Decimal('0'),
        balance_due=Decimal('10.000'),
        currency='AED',
        exchange_rate=Decimal('1'),
        payment_status='unpaid',
        status='confirmed',
        is_active=True,
    )
    db.session.add(sale)
    db.session.commit()
    return sale


class _Role:
    def __init__(self, slug):
        self.slug = slug


class FakeUser:
    def __init__(self, slug=None, is_owner=False, perms=()):
        self.is_authenticated = True
        self.is_owner = is_owner
        self.role = _Role(slug) if slug else None
        self._perms = frozenset(perms)

    def has_permission(self, code):
        return code in self._perms

    def is_super_admin(self):
        return bool(self.role and self.role.slug == 'super_admin')

    def is_manager(self):
        return bool(self.role and self.role.slug == 'manager')

    def is_seller(self):
        return bool(self.role and self.role.slug == 'seller')


ANON = SimpleNamespace(is_authenticated=False)


class TestGenerateNumber:
    def test_first_number_sequential_format(self, app, db):
        from models import Sale

        number = generate_number('S', Sale, 'sale_number')
        assert re.fullmatch(rf'S-{YEAR}-\d{{4}}', number)
        assert number == f'S-{YEAR}-0001'

    def test_increments_from_existing_committed_rows(self, app, db):
        from models import Sale

        make_sale(db, f'S-{YEAR}-0001')
        make_sale(db, f'S-{YEAR}-0002')
        assert generate_number('S', Sale, 'sale_number') == f'S-{YEAR}-0003'

    def test_collision_retry_inside_lock_skips_taken_candidate(self, app, db):
        from models import Sale

        make_sale(db, f'CL-{YEAR}-0009')
        make_sale(db, f'CL-{YEAR}-8')
        assert generate_number('CL', Sale, 'sale_number') == f'CL-{YEAR}-0010'

    def test_persistent_collision_exhausts_retries_and_uses_uuid(self, app, db, monkeypatch):
        from models import Sale

        monkeypatch.setitem(sys.modules, 'utils.distributed_lock', None)
        make_sale(db, f'PC-{YEAR}-0006')
        make_sale(db, f'PC-{YEAR}-5')
        number = generate_number('PC', Sale, 'sale_number')
        assert re.fullmatch(rf'PC-{YEAR}-[0-9A-F]{{8}}', number)

    def test_fallback_without_distributed_lock_still_increments(self, app, db, monkeypatch):
        from models import Sale

        monkeypatch.setitem(sys.modules, 'utils.distributed_lock', None)
        make_sale(db, f'FB-{YEAR}-0003')
        assert generate_number('FB', Sale, 'sale_number') == f'FB-{YEAR}-0004'

    def test_fallback_empty_table_starts_at_one(self, app, db, monkeypatch):
        from models import Sale

        monkeypatch.setitem(sys.modules, 'utils.distributed_lock', None)
        assert generate_number('FE', Sale, 'sale_number') == f'FE-{YEAR}-0001'

    def test_recovers_when_uuid_suffixed_row_is_max(self, app, db):
        from models import Sale

        make_sale(db, f'UP-{YEAR}-0001')
        make_sale(db, f'UP-{YEAR}-AABBCCDD')
        assert generate_number('UP', Sale, 'sale_number') == f'UP-{YEAR}-0002'

    def test_custom_date_format_is_honored(self, app, db):
        from models import Sale

        month_stamp = datetime.now().strftime('%Y%m')
        assert generate_number('QT', Sale, 'sale_number', date_format='%Y%m') == f'QT-{month_stamp}-0001'

    def test_generated_numbers_are_unique_across_calls(self, app, db):
        from models import Sale

        seen = set()
        for _ in range(5):
            number = generate_number('UQ', Sale, 'sale_number')
            assert number not in seen
            seen.add(number)
            make_sale(db, number)
        assert len(seen) == 5


class TestGetNextNumber:
    def test_empty_table_returns_first_sequence(self, app, db):
        from models import Sale

        assert get_next_number('NV', Sale, 'sale_number') == f'NV-{YEAR}-0001'

    def test_increments_past_existing_max(self, app, db):
        from models import Sale

        make_sale(db, f'NX-{YEAR}-0041')
        assert get_next_number('NX', Sale, 'sale_number') == f'NX-{YEAR}-0042'


class TestMoneyMath:
    def test_calculate_discount_decimal_inputs(self):
        assert calculate_discount('250.00', '10') == Decimal('25.00')

    def test_calculate_discount_float_input_quantized(self):
        assert calculate_discount(199.99, 15) == Decimal('30.00')

    def test_calculate_vat_basic(self):
        assert calculate_vat(100, 5) == Decimal('5.00')

    def test_calculate_vat_rounding(self):
        assert calculate_vat('33.33', 5) == Decimal('1.67')

    def test_format_currency_display_zero_variants(self):
        assert format_currency_display(None) == '0.00'
        assert format_currency_display(Decimal('0')) == '0.00'

    def test_format_currency_display_arabic_aed(self):
        assert format_currency_display(Decimal('1234.5')) == '1,234.50 د.إ'

    def test_format_currency_display_english_usd(self):
        assert format_currency_display(99.99, 'USD', 'en') == 'USD 99.99'

    def test_format_currency_display_unknown_currency_falls_back_to_code(self):
        assert format_currency_display(Decimal('12'), 'XYZ') == '12.00 XYZ'

    def test_format_currency_display_string_amount_returns_raw_string(self):
        assert format_currency_display('N/A') == 'N/A'

    def test_format_currency_alias_matches_display(self):
        assert format_currency(100, 'AED', 'en') == format_currency_display(100, 'AED', 'en')


class TestTimeAgo:
    NOW = datetime.now(timezone.utc)

    def test_none_returns_empty(self):
        assert timeago(None) == ''

    def test_under_a_minute(self):
        assert timeago(datetime.now(timezone.utc) - timedelta(seconds=20)) == 'منذ لحظات'

    def test_minutes_branch(self):
        assert timeago(datetime.now(timezone.utc) - timedelta(minutes=5)) == 'منذ 5 دقيقة'

    def test_hours_branch(self):
        assert timeago(datetime.now(timezone.utc) - timedelta(hours=2)) == 'منذ 2 ساعة'

    def test_days_branch(self):
        assert timeago(datetime.now(timezone.utc) - timedelta(days=2)) == 'منذ 2 يوم'

    def test_beyond_week_shows_absolute_date(self):
        naive = (datetime.now(timezone.utc) - timedelta(days=10)).replace(tzinfo=None)
        assert timeago(naive) == naive.strftime('%Y-%m-%d')

    def test_naive_date_before_1970_is_rejected(self):
        assert timeago(datetime(1900, 1, 1)) == ''

    def test_garbage_input_returns_str_representation(self):
        assert timeago('not-a-date') == 'not-a-date'


class TestCreateAuditLog:
    def test_anonymous_request_logs_null_user_with_ip_and_agent(self, app, db):
        from models import AuditLog

        with app.test_request_context(
            '/', environ_base={'REMOTE_ADDR': '10.1.2.3'},
            headers={'User-Agent': 'TestAgent/1.0'},
        ):
            create_audit_log('create', table_name='sales', record_id=7,
                             changes={'total': ['0', '100']})
            log = AuditLog.query.one()

        assert log.user_id is None
        assert log.action == 'create'
        assert log.table_name == 'sales'
        assert log.record_id == 7
        assert log.changes == {'total': ['0', '100']}
        assert log.ip_address == '10.1.2.3'
        assert log.user_agent == 'TestAgent/1.0'

    def test_authenticated_user_is_recorded(self, app, db, owner_user):
        from models import AuditLog

        with app.test_request_context('/', environ_base={'REMOTE_ADDR': '127.0.0.1'}):
            login_user(owner_user)
            create_audit_log('login')
            log = AuditLog.query.one()

        assert log.user_id == owner_user.id

    def test_commit_failure_is_swallowed_without_raising(self, app, db):
        from models import AuditLog

        with app.test_request_context('/'):
            create_audit_log('delete', changes=object())
        db.session.rollback()
        assert AuditLog.query.count() == 0


class TestAllowedFile:
    def test_explicit_extensions_case_insensitive_and_missing_dot(self):
        exts = {'.pdf', '.png'}
        assert allowed_file('report.PDF', exts)
        assert allowed_file('scan.pNg', exts)
        assert not allowed_file('virus.txt', exts)
        assert not allowed_file('README', exts)
        assert not allowed_file('', exts)

    def test_config_all_key_short_circuits_merge(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'ALLOWED_UPLOAD_EXTENSIONS', {'all': {'.csv'}})
        assert allowed_file('a.CSV')
        assert not allowed_file('a.exe')

    def test_config_merges_extension_sets(self, app, monkeypatch):
        monkeypatch.setitem(
            app.config, 'ALLOWED_UPLOAD_EXTENSIONS',
            {'images': {'.jpg'}, 'documents': {'.pdf'}},
        )
        assert allowed_file('doc.pdf')
        assert allowed_file('pic.jpg')
        assert not allowed_file('arc.zip')


class TestSaveUploadedFile:
    def test_missing_file_or_filename_returns_none(self, app):
        assert save_uploaded_file(None) is None
        assert save_uploaded_file(FakeUpload('')) is None

    def test_disallowed_extension_raises(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(app, 'static_folder', str(tmp_path))
        with pytest.raises(ValueError, match='not allowed'):
            save_uploaded_file(FakeUpload('evil.exe'), 'up', {'.png'})

    def test_executable_header_rejected(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(app, 'static_folder', str(tmp_path))
        with pytest.raises(ValueError, match='Executable'):
            save_uploaded_file(FakeUpload('fake.png', content=b'MZ\x90\x00'), 'up', {'.png'})

    def test_elf_header_rejected(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(app, 'static_folder', str(tmp_path))
        with pytest.raises(ValueError, match='Executable'):
            save_uploaded_file(FakeUpload('fake.png', content=b'\x7fELF\x02'), 'up', {'.png'})

    def test_oversized_file_raises(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(app, 'static_folder', str(tmp_path))
        big = FakeUpload('big.png', size=6 * 1024 * 1024)
        with pytest.raises(ValueError, match='size'):
            save_uploaded_file(big, 'up', {'.png'})

    def test_successful_upload_saves_unique_file(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(app, 'static_folder', str(tmp_path))
        payload = b'\x89PNG\r\n\x1a\n' + b'x' * 64
        upload = FakeUpload('invoice copy.png', content=payload)
        result = save_uploaded_file(upload, 'uploads_test', {'.png'})

        base = os.path.basename(result)
        name, ext = os.path.splitext(base)
        assert result.startswith('uploads_test/')
        assert result == result.replace('\\', '/')
        assert ext == '.png'
        assert name.startswith('invoice_copy')
        assert re.search(r'_[0-9a-f]{8}$', name)
        assert upload.saved_to == os.path.join(str(tmp_path), 'uploads_test', base)
        with open(upload.saved_to, 'rb') as fh:
            assert fh.read() == payload


class TestConvertCurrency:
    def test_same_currency_passthrough(self):
        assert convert_currency(Decimal('25.50'), 'AED') == Decimal('25.50')

    def test_cross_currency_applies_rate(self, monkeypatch):
        from services.currency_service import CurrencyService

        monkeypatch.setattr(CurrencyService, 'get_exchange_rate', lambda f, t: '3.6725')
        assert convert_currency(Decimal('100'), 'USD', 'AED') == Decimal('367.25')


class TestIdGenerators:
    def test_generate_sku_format_and_uniqueness(self):
        first, second = generate_sku(), generate_sku()
        assert re.fullmatch(r'SKU-[0-9A-F]{8}', first)
        assert first != second

    def test_generate_barcode_matches_today_prefix(self):
        barcode = generate_barcode()
        assert barcode.startswith(datetime.now().strftime('%Y%m%d'))
        assert re.fullmatch(r'\d{8}[0-9A-F]{6}', barcode)


class TestPermissionRequired:
    def _view(self):
        @decorators.permission_required('manage_sales')
        def endpoint():
            return 'OK'
        return endpoint

    def test_anonymous_redirects_to_login_with_warning_flash(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', ANON)
        with app.test_request_context('/'):
            response = self._view()()
            flashes = get_flashed_messages(with_categories=True)
        assert response.status_code == 302
        assert response.location.endswith('/auth/login')
        assert flashes == [('warning', 'الرجاء تسجيل الدخول أولاً')]

    def test_user_without_permission_gets_403(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', FakeUser(slug='seller', perms=('manage_products',)))
        with app.test_request_context('/'):
            with pytest.raises(Forbidden):
                self._view()()
            assert ('danger', 'ليس لديك صلاحية للوصول لهذه الصفحة') in get_flashed_messages(with_categories=True)

    def test_user_with_permission_gets_return_value(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', FakeUser(perms=('manage_sales',)))
        view = self._view()
        with app.test_request_context('/'):
            assert view() == 'OK'
        assert view.__name__ == 'endpoint'


class TestAdminRequired:
    def _view(self):
        @decorators.admin_required
        def endpoint():
            return 'ADMIN-OK'
        return endpoint

    def test_owner_passes(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', FakeUser(is_owner=True))
        with app.test_request_context('/'):
            assert self._view()() == 'ADMIN-OK'

    def test_plain_role_gets_403(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', FakeUser(slug='accountant'))
        with app.test_request_context('/'):
            with pytest.raises(Forbidden):
                self._view()()


class TestSellerOrAbove:
    def _view(self):
        @decorators.seller_or_above
        def endpoint():
            return 'SHOP-OK'
        return endpoint

    def test_manager_passes(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', FakeUser(slug='manager'))
        with app.test_request_context('/'):
            assert self._view()() == 'SHOP-OK'

    def test_seller_passes(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', FakeUser(slug='seller'))
        with app.test_request_context('/'):
            assert self._view()() == 'SHOP-OK'

    def test_owner_short_circuits_role_checks(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', FakeUser(slug=None, is_owner=True))
        with app.test_request_context('/'):
            assert self._view()() == 'SHOP-OK'

    def test_other_role_gets_403(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', FakeUser(slug='viewer'))
        with app.test_request_context('/'):
            with pytest.raises(Forbidden):
                self._view()()


class TestSuperAdminRequired:
    def _view(self):
        @decorators.super_admin_required
        def endpoint():
            return 'ROOT-OK'
        return endpoint

    def test_super_admin_passes(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', FakeUser(slug='super_admin'))
        with app.test_request_context('/'):
            assert self._view()() == 'ROOT-OK'

    def test_regular_user_gets_403(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', FakeUser(slug='seller'))
        with app.test_request_context('/'):
            with pytest.raises(Forbidden):
                self._view()()


class TestOwnerRequired:
    def _view(self):
        @decorators.owner_required
        def endpoint():
            return 'OWNER-OK'
        return endpoint

    def test_anonymous_gets_404(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', ANON)
        with app.test_request_context('/'):
            with pytest.raises(NotFound):
                self._view()()

    def test_developer_role_passes(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', FakeUser(slug='developer'))
        with app.test_request_context('/'):
            assert self._view()() == 'OWNER-OK'

    def test_non_privileged_user_gets_404(self, app, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', FakeUser(slug='seller'))
        with app.test_request_context('/'):
            with pytest.raises(NotFound):
                self._view()()

    def test_real_owner_fixture_passes_with_real_permissions(self, app, db, owner_user, monkeypatch):
        monkeypatch.setattr(decorators, 'current_user', owner_user)

        @decorators.permission_required('manage_payments')
        def endpoint():
            return 'REAL-USER-OK'

        with app.test_request_context('/'):
            assert endpoint() == 'REAL-USER-OK'


@pytest.mark.parametrize('decorator_factory', [
    lambda: decorators.admin_required,
    lambda: decorators.seller_or_above,
    lambda: decorators.super_admin_required,
], ids=['admin', 'seller_or_above', 'super_admin'])
def test_remaining_decorators_redirect_anonymous_to_login(app, monkeypatch, decorator_factory):
    monkeypatch.setattr(decorators, 'current_user', ANON)

    @decorator_factory()
    def endpoint():
        return 'SHOULD-NOT-RUN'

    with app.test_request_context('/'):
        response = endpoint()
        flashes = get_flashed_messages(with_categories=True)
    assert response.status_code == 302
    assert response.location.endswith('/auth/login')
    assert flashes == [('warning', 'الرجاء تسجيل الدخول أولاً')]
