"""External tax-authority client seam.

الوضع الافتراضي: ``ManualAuthorityClient`` — لا يتصل بأي سلطة، ولا يوقّع ولا
يرسل. يُسجّل فقط النية (ما فُرض على التعداد) حتى يعرف المختص ماذا كان سيحدث.

عندما يُبرم عقد مع مزود معتمد (ZATCA Phase 2 / ETA / غيره)، يُنفَّذ صنف
``AuthorityClient`` فعلي ضده ويُسجَّل في ``_AUTHORITY_CLIENTS`` — لا تُعاد
نمذجة الشهادات/الفواتير/الـ GL؛ فقط طبقة العميل تتغير.

هذا الملف **لا** يدّعي أن أي تكامل مع أي سلطة موجود الآن.
"""
from datetime import datetime, timezone

from services.compliance_credentials import AUTHORITY_REGISTRY
from models.tenant_scope import get_current_tenant_id


class AuthorityClient:
    """Interface كل مزود معتمد سيطبقها لاحقًا."""

    name = 'abstract'

    def submit_invoice(self, document, tenant_id=None, credentials=None):
        raise NotImplementedError

    def invoice_status(self, reference, tenant_id=None, credentials=None):
        raise NotImplementedError

    def health(self):
        return {'name': self.name, 'status': 'ok'}


class ManualAuthorityClient(AuthorityClient):
    """الوضع الافتراضي: تسجّل النية فقط، لا يفعل شيئًا."""

    name = 'manual'

    def submit_invoice(self, document, tenant_id=None, credentials=None):
        return {
            'status': 'manual',
            'reference': None,
            'document_id': getattr(document, 'id', None),
            'tenant_id': tenant_id or get_current_tenant_id(),
            'recorded_at': datetime.now(timezone.utc).isoformat(),
            'note': 'وضع يدوي: لا يُرسل أي شيء إلى أي سلطة. يُسجّل النية فقط.',
        }

    def invoice_status(self, reference, tenant_id=None, credentials=None):
        return {
            'status': 'manual',
            'reference': reference,
            'tenant_id': tenant_id or get_current_tenant_id(),
            'note': 'وضع يدوي — لا استعلام للسلطة.',
        }

    def health(self):
        return {'name': self.name, 'status': 'manual',
                'detail': 'لا تكامل فعلي مع أي سلطة — تخزين فقط.'}


# جدول أصناف العملاء. كل قيمة = صنف. لإضافة مزود لاحقًا:
#   1) نفّذ AuthorityClient ضده (توقيع/إرسال/استعلام/موافقة)
#   2) أضف: 'zatca': ZatcaAuthorityClient
#   3) عندها فقط يظهر الوضع في واجهة الاعتمادات /owner/compliance-credentials
_AUTHORITY_CLIENTS = {
    'manual': ManualAuthorityClient,
}


def authority_client(authority_key):
    """يُعيد العميل المهيأ لنقطة اتصال معينة."""
    authority_key = (authority_key or 'manual').strip().lower()
    if authority_key in _AUTHORITY_CLIENTS:
        return _AUTHORITY_CLIENTS[authority_key]()
    if authority_key in AUTHORITY_REGISTRY:
        return ManualAuthorityClient()   # على السلطة تغطيها عند جاهزيتها
    return ManualAuthorityClient()


def authority_client_for_tenant(tenant, authority_key=None):
    """العميل المناسب للدولة المهيأة في المستأجر — دائمًا ManualAuthorityClient."""
    key = authority_key or _authority_key_for_country(getattr(tenant, 'tax_country', None))
    return authority_client(key)


def _authority_key_for_country(country_code):
    code = (country_code or '').strip().upper()
    mapping = {
        'SA': 'zatca', 'AE': 'fta_ae', 'EG': 'eta_eg', 'TR': 'gib_tr',
        'BH': 'nbr_bh', 'OM': 'ota_om', 'GB': 'hmrc_uk', 'DE': 'bzst_de', 'JO': 'ioi_jo',
    }
    return mapping.get(code, 'manual')


__all__ = ['AuthorityClient', 'ManualAuthorityClient', 'authority_client',
           'authority_client_for_tenant', '_authority_key_for_country']
