from types import SimpleNamespace


from utils.invoice_header import with_tenant_header


def tenant(**overrides):
    values = dict(
        id=1,
        name="Tenant A",
        name_ar="شركة أ",
        name_en=None,
        address_ar=None,
        city=None,
        country=None,
        phone_1=None,
        mobile=None,
        logo_url=None,
        brand_color_primary=None,
        brand_color_secondary=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_header_never_inherits_platform_business_fields():
    platform = SimpleNamespace(
        company_name_ar="Platform",
        tax_number="PLATFORM-TAX",
        iban="PLATFORM-IBAN",
        logo_path="platform.png",
        address_ar="Platform address",
    )
    result = with_tenant_header(platform, tenant())
    assert result.company_name_ar == "شركة أ"
    assert result.tax_number is None
    assert result.iban is None
    assert not result.logo_path
    assert not result.address_ar


def test_header_uses_each_tenant_independently():
    a = with_tenant_header(None, tenant(tax_number="A-TAX", city="Dubai"))
    b = with_tenant_header(None, tenant(id=2, name_ar="شركة ب", tax_number="B-TAX"))
    assert (a.company_name_ar, a.tax_number, a.address_ar) == (
        "شركة أ",
        "A-TAX",
        "Dubai",
    )
    assert (b.company_name_ar, b.tax_number) == ("شركة ب", "B-TAX")


def test_header_platform_context_returns_platform_settings():
    """tenant=None تعني سياق المنصة الكاملة: تُعاد إعدادات المنصة كما هي."""
    platform = object()  # أي كائن إعدادات كان — يجب أن تُعاد كما هي
    assert with_tenant_header(platform, None) is platform
