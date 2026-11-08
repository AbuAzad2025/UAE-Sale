import pytest

from models.tenant import Tenant


@pytest.mark.parametrize('template', ['modern', 'classic', 'gulf', 'minimal', 'simple'])
def test_invoice_uses_document_tenant_and_not_platform(
        client, db, owner_user, login_owner, test_sale, template):
    a = Tenant(name='Unique Supplier A', name_ar='شركة ألف الفريدة',
               slug='invoice-test-a', tax_number='TRN-A-123',
               city='Dubai', country='UAE', iban='IBAN-A-UNIQUE')
    b = Tenant(name='Unique Supplier B', name_ar='شركة باء الفريدة',
               slug='invoice-test-b', tax_number='TRN-B-987',
               country='Jordan', iban='IBAN-B-UNIQUE')
    db.session.add_all([a, b])
    db.session.commit()
    test_sale.tenant_id = a.id
    db.session.commit()

    response = client.get(f'/sales/{test_sale.id}/print?template={template}')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'شركة ألف الفريدة' in html
    assert 'TRN-A-123' in html
    assert 'شركة باء الفريدة' not in html
    assert 'TRN-B-987' not in html
    assert 'IBAN-B-UNIQUE' not in html


def test_print_shows_mixed_line_treatment_badges(client, db, owner_user,
                                                login_owner, test_sale):
    tenant = Tenant(name='Badge tenant', name_ar='شركة الشارة',
                    slug='badge-tenant-2')
    db.session.add(tenant)
    db.session.commit()
    test_sale.tenant_id = tenant.id
    for line in test_sale.lines:
        line.tax_treatment = 'exempt'
    db.session.commit()
    response = client.get(f'/sales/{test_sale.id}/print?template=modern')
    assert response.status_code == 200
    assert 'معفى' in response.get_data(as_text=True)


def test_platform_context_document_prints_with_platform_settings(client, db, owner_user, login_owner, test_sale):
    """مستند بلا شركة في سياق المنصة يطبع بهوية المنصة — بلا فبركة هوية شركة."""
    test_sale.tenant_id = None
    db.session.commit()
    response = client.get(f'/sales/{test_sale.id}/print')
    assert response.status_code == 200


def test_tenant_document_cannot_print_after_its_tenant_is_deleted(client, db, owner_user, login_owner, test_sale):
    """شركة المستند حُذفت — الطباعة تُرفض بدل هوية وهمية."""
    tenant = Tenant(name='Ghost tenant', name_ar='شركة طيّارة', slug='ghost-tenant')
    db.session.add(tenant)
    db.session.commit()
    test_sale.tenant_id = tenant.id
    db.session.commit()
    db.session.delete(tenant)
    db.session.commit()
    response = client.get(f'/sales/{test_sale.id}/print')
    assert response.status_code == 409


def test_print_tax_label_distinguishes_inclusive_zero_and_exempt(
        client, db, owner_user, login_owner, test_sale):
    from decimal import Decimal
    tenant = Tenant(name='Tax label tenant', name_ar='شركة اختبار', slug='tax-label')
    db.session.add(tenant)
    db.session.flush()
    test_sale.tenant_id = tenant.id
    cases = [
        ('standard', True, '5', 'الضريبة المشمولة في الإجمالي'),
        ('standard', False, '5', 'الضريبة الإضافية'),
        ('zero', False, '0', 'خاضعة بنسبة صفرية'),
        ('exempt', False, '0', 'معفاة من الضريبة'),
    ]
    for treatment, inclusive, amount, expected in cases:
        test_sale.tax_treatment = treatment
        test_sale.tax_inclusive = inclusive
        test_sale.tax_rate = Decimal('5') if treatment == 'standard' else Decimal('0')
        test_sale.tax_amount = Decimal(amount)
        db.session.commit()
        response = client.get(f'/sales/{test_sale.id}/print?template=modern')
        assert response.status_code == 200
        assert expected in response.get_data(as_text=True)
