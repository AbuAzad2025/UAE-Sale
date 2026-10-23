"""E2E surface — تسوية فرق العملات الأجنبية (tests/e2e/test_fx_revaluation_surface.py).

السطح الجديد (routes/owner.py) مسار واحد بأمرين، وكلاهما يجب أن يُنفَّذ
بطلب حقيقي وإلا هبط تغطية المسارات عن 100%:

    GET  /owner/fx-revaluation/   معاينة (dry run) + زر الترحيل   (manage_ledger)
    POST /owner/fx-revaluation/   ترحيل قيد التسوية              (manage_ledger)

الاختبار لا يكتفي بحالة الاستجابة: يتحقق من القيد المرحَّل (مدين 1130 /
دائن 4400 — ربح غير محقق على ذمم مدينة)، ومن أن القيد مرتبط بفترة التسوية
عبر المرجع، ومن أن الترحيل الثاني في نفس الفترة لا يولّد قيداً ثانياً،
ومن أن دوراً بلا صلاحية الدفتر يُرفض بـ403.
"""
from datetime import date
from decimal import Decimal

import pytest

from tests.e2e.harness import assert_entry_accounts

CONFIRM_TOKEN = 'YES_POST_FX_REVALUATION'


@pytest.fixture
def fixed_rates(monkeypatch):
    """أسعار صرف ثابتة بلا شبكة حتى تكون النتيجة حتمية.

    الفاتورة تُسجَّل بسعر 3.6 والسعر الحالي 3.7، فالفرق 100 وحدة من
    عملة الأساس على ذمم مدينة.
    """
    from services.currency_service import CurrencyService

    def _rate(from_currency, to_currency=None, user_rate=None):
        if user_rate is not None:
            return Decimal(str(user_rate))
        return Decimal('3.7')

    def _all_rates(base=None):
        return {
            'ILS': Decimal('1'),
            'USD': Decimal('0.27'),
            'EUR': Decimal('0.25'),
        }

    monkeypatch.setattr(CurrencyService, 'get_exchange_rate', staticmethod(_rate))
    monkeypatch.setattr(CurrencyService, 'get_all_rates', staticmethod(_all_rates))
    return True


def _foreign_sale(client, customer, product, warehouse):
    """فاتورة بيع بعملة أجنبية (1000 USD بسعر 3.6) عبر المسار الحقيقي."""
    from tests.e2e.harness import sale_form

    data = sale_form(
        customer,
        [{'product_id': product.id, 'quantity': 1, 'unit_price': 1000}],
        warehouse=warehouse,
        currency='USD',
        exchange_rate='3.6',
    )
    response = client.post('/sales/create', data=data)
    assert response.status_code in (302, 303), response.get_data(as_text=True)[:300]
    return response


def test_fx_revaluation_surface_exercises_every_route(
        client, db, login_as, owner, customer, product, warehouse, fixed_rates):
    """يمرّ على المسار (معاينة ثم ترحيل) ويتحقق من الأثر المحاسبي."""
    from models.gl import GLJournalEntry

    login_as('owner')
    _foreign_sale(client, customer, product, warehouse)

    # 1) GET /owner/fx-revaluation/ — المعاينة الجافة (لا ترحيل)
    response = client.get('/owner/fx-revaluation/')
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    body = response.get_data(as_text=True)
    assert 'USD' in body
    assert 'معاينة' in body
    assert GLJournalEntry.query.filter_by(
        reference_type='fx_revaluation').count() == 0, 'المعاينة لا ترحّل'

    # 2) POST /owner/fx-revaluation/ — ترحيل القيد
    response = client.post('/owner/fx-revaluation/', data={
        'confirm': CONFIRM_TOKEN,
        'as_of': '',
    }, follow_redirects=True)
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert 'تم ترحيل' in response.get_data(as_text=True)

    entry = GLJournalEntry.query.filter_by(
        reference_type='fx_revaluation').first()
    assert entry is not None, 'لم يُرحَّل قيد تسوية'

    # القيد: مدين 1130 (ذمم مدينة) / دائن 4400 (أرباح فرق العملة)
    assert_entry_accounts(entry.id, {
        '1130': (Decimal('100'), Decimal('0')),
        '4400': (Decimal('0'), Decimal('100')),
    })

    # القيد مرتبط بفترة التسوية عبر المرجع (reference_type + reference_id)
    today = date.today()
    assert entry.reference_id == int(f'{today.year:04d}{today.month:02d}')

    # 3) POST مرة أخرى — لا قيد ثانٍ في نفس الفترة
    response = client.post('/owner/fx-revaluation/', data={
        'confirm': CONFIRM_TOKEN,
        'as_of': '',
    }, follow_redirects=True)
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert 'مرحَّلة مسبقاً' in response.get_data(as_text=True)
    assert GLJournalEntry.query.filter_by(
        reference_type='fx_revaluation').count() == 1, 'تكرار غير مرغوب'


def test_fx_revaluation_surface_denies_a_role_without_the_permission(
        client, db, login_as, owner, customer, product, warehouse, fixed_rates):
    """دور بلا صلاحية الدفتر لا يصل إلى سطح التسوية."""
    login_as('pos_cashier')

    response = client.get('/owner/fx-revaluation/')
    assert response.status_code == 403

    response = client.post('/owner/fx-revaluation/', data={
        'confirm': CONFIRM_TOKEN,
        'as_of': '',
    })
    assert response.status_code == 403

    from models.gl import GLJournalEntry

    assert GLJournalEntry.query.filter_by(
        reference_type='fx_revaluation').count() == 0
