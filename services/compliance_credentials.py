"""Compliance credentials vault — تشفير مُثبت بختم Fernet (نفس نمط Card Vault).

كل شركة (tenant) يمكنها أن تخزن اعتماداتها لدى كل سلطة ضريبية حكومية
(ZATCA/FTA/ETA/GIB/NBR/OTA/HMRC/BZSt/JoI) عبر لوحة المالك — مُشفّرة عند
الراحة، لا تظهر داخل أي واجهة ولا في أي سجل.

**لا يُقدّم هذا المسار تكاملًا مع أي سلطة**؛ يلتقط الشهادات/العُقد اللازمة
ويختمها، ويُشير إلى حالة كل شهادة (missing/configured/verified)، ويسجل كل
إجراء في audit_logs.
"""

import base64
import hashlib
import json
from datetime import datetime, timezone

from flask import current_app

from extensions import db
from models.compliance_credential import ComplianceCredential

AUTHORITY_REGISTRY = {
    "zatca": {
        "label": "ZATCA — فوترة إلكترونية (السعودية)",
        "authority_name": "الهيئة العامة للزكاة والدخل / ZATCA",
        "country": "SA",
        "fields": [
            ("csid", "CSID (من ZATCA)", True),
            ("private_key_pem", "مفتاح خاص PEM", True),
            ("certificate_pem", "الشهادة المعتمدة PEM", True),
            ("zatca_api_environment", "البيئة", False, ("integration", "production")),
            ("request_id", "Request / Transaction ID", False),
        ],
    },
    "fta_ae": {
        "label": "Federal Tax Authority (الإمارات)",
        "authority_name": "Federal Tax Authority (FTA)",
        "country": "AE",
        "fields": [
            ("trn", "رقم المنشأة الضريبية (TRN)", False),
            ("fta_account_id", "معرّف حساب FTA", True),
            ("fta_account_secret", "كلمة مرور حساب FTA", True),
            ("fta_environment", "البيئة", False, ("uat", "production")),
        ],
    },
    "eta_eg": {
        "label": "مصلحة الضرائب المصرية (ETA)",
        "authority_name": "مصلحة الضرائب المصرية / ETA",
        "country": "EG",
        "fields": [
            ("eta_client_id", "ETA Client ID", True),
            ("eta_client_secret", "ETA Client Secret", True),
            ("taxpayer_id", "Taxpayer ID", False),
            ("eta_environment", "البيئة", False, ("preprod", "production")),
        ],
    },
    "gib_tr": {
        "label": "Gelir İdaresi Başkanlığı (تركيا)",
        "authority_name": "Gelir İdaresi Başkanlığı / GİB",
        "country": "TR",
        "fields": [
            ("gib_vkn", "الرقم الضريبي (VKN)", False),
            ("gib_cert_serial", "الرقم التسلسلي للشهادة", True),
            ("gib_cert_password", "كلمة مرور الشهادة", True),
        ],
    },
    "nbr_bh": {
        "label": "NBR (البحرين)",
        "authority_name": "NBR — هيئة الضرائب الوطنية",
        "country": "BH",
        "fields": [
            ("nbr_seller_id", "Seller ID", False),
            ("nbr_api_key", "API Key", True),
        ],
    },
    "ota_om": {
        "label": "Oman Tax Authority (عُمان)",
        "authority_name": "Oman Tax Authority",
        "country": "OM",
        "fields": [
            ("ota_registration_number", "الرقم الضريبي", False),
            ("ota_api_token", "API Token", True),
        ],
    },
    "hmrc_uk": {
        "label": "HMRC — Making Tax Digital (بريطانيا)",
        "authority_name": "HM Revenue and Customs / HMRC",
        "country": "GB",
        "fields": [
            ("mtd_client_id", "MTD Client ID", True),
            ("mtd_client_secret", "MTD Client Secret", True),
        ],
    },
    "bzst_de": {
        "label": "BZSt — XRechnung (ألمانيا)",
        "authority_name": "Bundeszentralamt für Steuern / BZSt",
        "country": "DE",
        "fields": [
            ("xrechnung_participant_id", "Participant ID (BT-26)", False),
            (
                "zugferd_profile",
                "ZUGFeRD Profile",
                False,
                ("basic", "en16931", "extended"),
            ),
            ("bgn_certificate_ref", "BGN Certificate ref", True),
        ],
    },
    "ioi_jo": {
        "label": "دائرة ضريبة الدخل والمبيعات (الأردن)",
        "authority_name": "دائرة ضريبة الدخل والمبيعات",
        "country": "JO",
        "fields": [
            ("joi_trn", "TRN", False),
            ("joi_api_token", "API Token", True),
        ],
    },
}


def authority_country(authority_key):
    meta = AUTHORITY_REGISTRY.get(authority_key)
    return meta["country"] if meta else None


def authorities_for_country(country_code):
    code = (country_code or "").upper()
    return [
        (key, meta)
        for key, meta in AUTHORITY_REGISTRY.items()
        if meta["country"] == code
    ]


def _get_cipher():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover - env issue
        raise RuntimeError("cryptography module missing") from exc
    key = current_app.config.get("COMPLIANCE_ENCRYPTION_KEY") or current_app.config.get(
        "CARD_ENCRYPTION_KEY"
    )
    if not key:
        raise ValueError(
            "COMPLIANCE_ENCRYPTION_KEY (or CARD_ENCRYPTION_KEY) not configured"
        )
    key_bytes = key.encode() if isinstance(key, str) else key
    key_bytes = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
    return Fernet(key_bytes)


def encrypt_payload(values):
    cipher = _get_cipher()
    clean = {
        str(k).strip(): str(v).strip()
        for k, v in (values or {}).items()
        if str(v).strip()
    }
    return cipher.encrypt(json.dumps(clean, ensure_ascii=False).encode("utf-8")).decode(
        "ascii"
    )


def decrypt_payload(blob):
    if not blob:
        return {}
    cipher = _get_cipher()
    return json.loads(cipher.decrypt(blob.encode("ascii")).decode("utf-8"))


def credential_for(tenant_id, authority_key):
    return ComplianceCredential.query.filter_by(
        tenant_id=tenant_id, authority_key=authority_key
    ).first()


def save_credential(tenant_id, authority_key, values, notes=None, user_id=None):
    """يحفظ/يُدوّر اعتماد الشركة لدى السلطة (upsert) — audit في الخارج."""
    row = credential_for(tenant_id, authority_key)
    if row is None:
        row = ComplianceCredential(tenant_id=tenant_id, authority_key=authority_key)
    blob = encrypt_payload(values)
    row.payload_encrypted = blob if blob else None
    row.notes = (notes or "").strip() or None
    row.status = "configured" if blob else "missing"
    row.last_rotated_at = datetime.now(timezone.utc)
    db.session.add(row)
    return row


def mark_verified(tenant_id, authority_key):
    row = credential_for(tenant_id, authority_key)
    if row is None:
        return None
    row.status = "verified"
    row.verified_at = datetime.now(timezone.utc)
    db.session.add(row)
    return row


def clear_credential(tenant_id, authority_key):
    row = credential_for(tenant_id, authority_key)
    if row is None:
        return None
    row.payload_encrypted = None
    row.status = "missing"
    row.verified_at = None
    db.session.add(row)
    return row


def credential_summary(tenant_id, authority_key):
    """نسخة خفيفة للعرض فقط — بدون أي حقول سرية."""
    row = credential_for(tenant_id, authority_key)
    if row is None:
        return {
            "status": "missing",
            "last_rotated_at": None,
            "verified_at": None,
            "notes": None,
            "id": None,
        }
    return {
        "status": row.status,
        "last_rotated_at": row.last_rotated_at,
        "verified_at": row.verified_at,
        "notes": row.notes,
        "id": row.id,
    }


def credential_values(tenant_id, authority_key):
    """للقراءة الداخلية فقط (مثلاً في تكامل مستقبلي) — بلا واجهة."""
    row = credential_for(tenant_id, authority_key)
    if row is None or not row.payload_encrypted:
        return {}
    return decrypt_payload(row.payload_encrypted)
