"""قالب فاتورة واحد — بيانات التينانت (اسم/رقم ضريبي/عنوان/شعار/ألوان).

يجعل قوالب `templates/invoices|receipts/*.html` تقرأ من الشركة المالكة
للمستند وليس من أزاد، مع بقاء التصميم العام.
"""
import types


def with_tenant_header(settings, tenant):
    """دمج `tenant` فوق `settings` (نسخة جديدة، الفواصل تبقى للتصميم)."""
    if settings is None or tenant is None:
        return settings
    ns = dict(getattr(settings, '__dict__', {}) or {})
    ns.pop('_sa_instance_state', None)
    _display_name = (getattr(tenant, 'name_ar', None) or getattr(tenant, 'name', None))
    _ns['company_name_ar'] = _display_name or _ns.get('company_name_ar')
    _ns['company_name_en'] = getattr(tenant, 'name_en', None) or getattr(tenant, 'name', None) or _ns.get('company_name_en')
    _ns['address_ar'] = getattr(tenant, 'address_ar', None) or _ns.get('address_ar')
    _city_country = f"{getattr(tenant, 'city', None) or ''}، {getattr(tenant, 'country', None) or ''}".strip('، ')
    if _city_country:
        _ns['address_ar'] = (_ns.get('address_ar') or '') + (f" — {_city_country}" if _city_country else '')
    _ns['phone_1'] = getattr(tenant, 'phone_1', None) or getattr(tenant, 'mobile', None) or _ns.get('phone_1')
    _ns['phone_2'] = getattr(tenant, 'phone_2', None) or _ns.get('phone_2')
    _ns['email'] = getattr(tenant, 'email', None) or _ns.get('email')
    _ns['website'] = getattr(tenant, 'website', None) or _ns.get('website')
    _ns['tax_number'] = getattr(tenant, 'tax_number', None) or _ns.get('tax_number')
    _ns['commercial_register'] = getattr(tenant, 'commercial_register', None) or _ns.get('commercial_register')
    _ns['logo_url'] = getattr(tenant, 'logo_url', None) or _ns.get('logo_url')
    _ns['logo_dark_url'] = getattr(tenant, 'logo_dark_url', None) or _ns.get('logo_dark_url')
    _ns['logo_path'] = getattr(tenant, 'logo_url', None) or _ns.get('logo_path')
    _ns['header_color'] = getattr(tenant, 'brand_color_primary', None) or _ns.get('header_color')
    _ns['accent_color'] = getattr(tenant, 'brand_color_secondary', None) or _ns.get('accent_color')
    _ns['tenant_id'] = getattr(tenant, 'id', None)
    return types.SimpleNamespace(**_ns)
