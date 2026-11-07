"""Document branding from the document's owning tenant only."""
from types import SimpleNamespace


def with_tenant_header(settings, tenant):
    """Use only neutral presentation settings; never inherit business identity."""
    if tenant is None:
        raise ValueError('Document has no owning tenant')
    design_fields = ('text_color', 'logo_position', 'logo_size', 'paper_size',
                     'orientation', 'default_language', 'show_barcode',
                     'show_page_numbers', 'show_due_date', 'qr_position')
    data = {field: getattr(settings, field, None) for field in design_fields}
    fields = ('name_en', 'address_en', 'phone_1', 'phone_2', 'email', 'website',
              'tax_number', 'commercial_register', 'license_number', 'bank_name',
              'bank_account_number', 'iban', 'swift_code', 'payment_terms_ar',
              'footer_text_ar', 'default_invoice_note_ar', 'active_template')
    data.update({field: getattr(tenant, field, None) for field in fields})
    data['company_name_ar'] = tenant.name_ar or tenant.name
    data['company_name_en'] = tenant.name_en or tenant.name
    data['address_ar'] = '، '.join(filter(None, (tenant.address_ar, tenant.city, tenant.country)))
    data['phone_1'] = tenant.phone_1 or tenant.mobile
    data['logo_url'] = tenant.logo_url
    data['logo_path'] = tenant.logo_url
    data['show_logo'] = bool(tenant.logo_url)
    data['header_color'] = tenant.brand_color_primary or '#667eea'
    data['accent_color'] = tenant.brand_color_secondary or '#764ba2'
    data['tenant_id'] = tenant.id
    return SimpleNamespace(**data)


def document_tenant(document):
    """Resolve strictly from the document, never from a related party or actor."""
    from models.tenant import Tenant
    tenant_id = getattr(document, 'tenant_id', None)
    if tenant_id is None:
        raise ValueError('Document has no owning tenant')
    tenant = Tenant.query.get(tenant_id)
    if tenant is None:
        raise ValueError('Document owning tenant does not exist')
    return tenant
