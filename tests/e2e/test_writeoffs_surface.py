"""E2E surface — المديونيات المشطوبة (tests/e2e/test_writeoffs_surface.py).

السطح الجديد (routes/writeoffs.py) خمس مسارات، وكل واحد منها يجب أن يُنفَّذ
بطلب حقيقي وإلا هبط تغطية المسارات عن 100%:

    GET  /writeoffs/                 قائمة المشطوبات          (view_ledger)
    GET  /writeoffs/new              نموذج المشطوبة           (manage_ledger)
    POST /writeoffs/                 تنفيذ المشطوبة          (manage_ledger)
    GET  /writeoffs/<id>             تفاصيل المشطوبة          (view_ledger)
    POST /writeoffs/<id>/void        إلغاء المشطوبة          (manage_ledger)

الاختبار لا يكتفي بحالة الاستجابة: يتحقق من القيد المرحّل (مدين 6960 /
دائن 1130)، ومن رصيد العميل بعد المشطوبة وبعد إلغائها، ومن أن دوراً بلا
صلاحية يُرفض بـ403.
"""
from decimal import Decimal

from tests.e2e.harness import assert_entry_accounts


def _write_off_id_from_redirect(response):
    """معرّف المشطوبة من عنوان إعادة التوجيه."""
    location = response.headers.get('Location', '')
    return int(location.rstrip('/').split('/')[-1])


def test_writeoff_surface_exercises_every_route(client, db, login_as, sale, customer):
    """يمرّ على المسارات الخمسة ويتحقق من الأثر المحاسبي والمالي."""
    from models.gl import GLJournalEntry
    from models.write_off import WriteOff

    login_as('senior_accountant')

    # 1) GET /writeoffs/ — القائمة
    response = client.get('/writeoffs/')
    assert response.status_code == 200, response.get_data(as_text=True)[:300]

    # 2) GET /writeoffs/new — النموذج
    response = client.get('/writeoffs/new')
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    body = response.get_data(as_text=True)
    assert 'name="amount"' in body
    assert 'name="reason"' in body
    assert 'name="customer_id"' in body

    # 3) POST /writeoffs/ — تنفيذ المشطوبة
    response = client.post('/writeoffs/', data={
        'customer_id': str(customer.id),
        'amount': '50.000',
        'currency': 'ILS',
        'reason': 'العميل لم يعد قابلاً للوصول',
        'notes': 'مسطوبة اختبار',
    })
    assert response.status_code in (302, 303), response.get_data(as_text=True)[:300]
    write_off_id = _write_off_id_from_redirect(response)

    write_off = db.session.get(WriteOff, write_off_id)
    assert write_off is not None, 'المشطوبة لم تُنشأ'
    assert write_off.status == 'posted'
    assert write_off.gl_entry_id is not None
    assert Decimal(str(write_off.amount)) == Decimal('50.000')

    # القيد: مدين 6960 (مديونية مشطوبة) / دائن 1130 (ذمم مدينة)
    assert_entry_accounts(write_off.gl_entry_id, {
        '6960': (Decimal('50'), Decimal('0')),
        '1130': (Decimal('0'), Decimal('50')),
    })

    # رصيد العميل نقص بالمبلغ المشطوب
    from models.customer import derive_customer_balance
    assert derive_customer_balance(customer.id) == Decimal('150.000')

    # 4) GET /writeoffs/<id> — التفاصيل
    response = client.get(f'/writeoffs/{write_off_id}')
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert 'العميل' in response.get_data(as_text=True)

    # 5) POST /writeoffs/<id>/void — الإلغاء
    response = client.post(f'/writeoffs/{write_off_id}/void', data={
        'reason': 'تصحيح خطأ في المشطوبة',
    })
    assert response.status_code in (302, 303), response.get_data(as_text=True)[:300]

    write_off = db.session.get(WriteOff, write_off_id)
    assert write_off.status == 'void'
    assert write_off.voided_at is not None

    # القيد الأصلي صار معكوساً والقيد العكسي معاكس
    original = db.session.get(GLJournalEntry, write_off.gl_entry_id)
    assert original.is_reversed is True
    reversal = db.session.get(GLJournalEntry, original.reversed_entry_id)
    assert reversal is not None
    assert reversal.entry_type == 'reversing'

    # والرصيد عاد كما كان
    assert derive_customer_balance(customer.id) == Decimal('200.000')


def test_writeoff_surface_denies_a_role_without_the_permission(
        client, db, login_as, sale, customer):
    """دور بلا صلاحية الدفتر لا يصل إلى سطح المشطوبات."""
    login_as('pos_cashier')

    response = client.get('/writeoffs/')
    assert response.status_code == 403

    response = client.get('/writeoffs/new')
    assert response.status_code == 403

    response = client.post('/writeoffs/', data={
        'customer_id': str(customer.id),
        'amount': '10.000',
        'currency': 'ILS',
        'reason': 'محاولة مرفوضة',
    })
    assert response.status_code == 403

    from models.write_off import WriteOff
    assert WriteOff.query.count() == 0
