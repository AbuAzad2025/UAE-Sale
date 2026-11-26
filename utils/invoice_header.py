"""Document branding from the document's owning tenant only.

الحساب/السياق:
- مستند له شركة مالكة (tenant_id): تُستخدم هويتها فقط — لا أزاد ولا إعدادات
  المنصة العامة. أي استخدام آخر ممنوع ومُبلَّغ.
- مستند بلا شركة (بيئة تنصيب/المالك يقرأ سياق المنصة الكاملة): تُعيد دالة
  `with_tenant_header` الإعدادات العامة للمنصة كما هي. لا يمكن لهذا المسار
  أن يؤدي إلى انتحال هوية شركة أخرى — كل شركة تملك مستنداتها عبر `tenant_id`
  الخاص بالسجل نفسه، وكل الوصول للآخر يجتاز فحص `get_owned_or_404` أولًا.
"""

from types import SimpleNamespace


def with_tenant_header(settings, tenant):
    """Use only neutral presentation settings; never inherit business identity."""
    if tenant is None:
        return settings
    design_fields = (
        "text_color",
        "logo_position",
        "logo_size",
        "paper_size",
        "orientation",
        "default_language",
        "show_barcode",
        "enable_qr_code",
        "whatsapp_number",
        "show_page_numbers",
        "show_due_date",
        "qr_position",
    )
    data = {field: getattr(settings, field, None) for field in design_fields}
    fields = (
        "name_en",
        "address_en",
        "phone_1",
        "phone_2",
        "email",
        "website",
        "tax_number",
        "commercial_register",
        "license_number",
        "bank_name",
        "bank_account_number",
        "iban",
        "swift_code",
        "payment_terms_ar",
        "footer_text_ar",
        "default_invoice_note_ar",
        "active_template",
    )
    data.update({field: getattr(tenant, field, None) for field in fields})
    data["company_name_ar"] = tenant.name_ar or tenant.name
    data["company_name_en"] = tenant.name_en or tenant.name
    # Use the Arabic address when present; only fall back to city/country so
    # an English country name is not appended next to an Arabic address.
    data["address_ar"] = tenant.address_ar or "، ".join(
        filter(None, (tenant.city, tenant.country))
    )
    data["phone_1"] = tenant.phone_1 or tenant.mobile
    # The owner invoice-settings form stores an uploaded logo in
    # InvoiceSettings.logo_path (tenant-scoped), while the tenant form stores a
    # URL in Tenant.logo_url. Honour both so an uploaded logo actually prints.
    # Settings are only honoured when they explicitly belong to THIS tenant —
    # a platform-level settings object can never supply a business logo.
    settings_logo = None
    if getattr(settings, "tenant_id", None) == tenant.id:
        settings_logo = getattr(settings, "logo_url", None) or getattr(
            settings, "logo_path", None
        )
    _logo = tenant.logo_url or settings_logo
    data["logo_url"] = _logo
    data["logo_path"] = _logo
    data["show_logo"] = bool(_logo)
    data["header_color"] = tenant.brand_color_primary or "#667eea"
    data["accent_color"] = tenant.brand_color_secondary or "#764ba2"
    data["tenant_id"] = tenant.id
    return SimpleNamespace(**data)


def document_tenant(document):
    """Resolve the owning tenant of a document strictly from the document."""
    from models.tenant import Tenant
    from extensions import db

    tenant_id = getattr(document, "tenant_id", None)
    if tenant_id is None:
        return None
    tenant = db.session.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError("Document owning tenant does not exist")
    return tenant
