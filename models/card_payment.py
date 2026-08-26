"""
Card Payment Model
نموذج حفظ معلومات البطاقات بشكل آمن ومشفر

SECURITY CONTRACT (remediation):
- Payloads are sealed with real Fernet (AES128-CBC + HMAC) using
  CARD_ENCRYPTION_KEY — the legacy plain base64 "encryption" is rejected.
- CVV is NEVER persisted. encrypt_card_data() accepts-and-discards it and
  stores only a masked PAN (last 4) plus an irreversible token hash.
- Reading legacy base64 rows raises ValueError('legacy insecure payload
  rejected') so insecure data can never silently round-trip again.
"""

from datetime import datetime, timezone
from extensions import db
from flask import current_app
import json
import base64
import hashlib

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    Fernet = None

LEGACY_PAYLOAD_MESSAGE = 'legacy insecure payload rejected'


def _get_card_payment_cipher():
    """Own Fernet cipher mirroring CardVault._get_cipher (CARD_ENCRYPTION_KEY)."""
    if not HAS_CRYPTO:
        raise RuntimeError('cryptography module not installed')

    key = current_app.config.get('CARD_ENCRYPTION_KEY')
    if not key:
        raise ValueError('CARD_ENCRYPTION_KEY not configured')

    key_bytes = key.encode() if isinstance(key, str) else key
    key_bytes = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())

    return Fernet(key_bytes)


class CardPayment(db.Model):
    """
    معلومات الدفع بالبطاقات - محفوظة بشكل آمن ومشفر
    """
    __tablename__ = 'card_payments'

    id = db.Column(db.Integer, primary_key=True)

    # معلومات العميل
    customer_name = db.Column(db.String(200), nullable=False)
    customer_email = db.Column(db.String(200))
    customer_phone = db.Column(db.String(50))

    # معلومات المشترية/التبرع
    transaction_type = db.Column(db.String(20), nullable=False)  # purchase, donation
    package = db.Column(db.String(50))  # للمشتريات
    amount = db.Column(db.Numeric(15, 2), nullable=False)

    # معلومات البطاقة (مشفرة)
    card_last_4 = db.Column(db.String(4))  # آخر 4 أرقام فقط (غير مشفرة)
    card_type = db.Column(db.String(20))  # Visa, Mastercard, Amex
    card_bin = db.Column(db.String(6))  # أول 6 أرقام (BIN)

    # بيانات مشفرة (لا تُحفظ إلا إذا ضروري جداً)
    encrypted_data = db.Column(db.Text)  # بيانات مشفرة إضافية

    # معلومات المعاملة
    transaction_id = db.Column(db.String(200), unique=True, index=True)
    payment_gateway = db.Column(db.String(50))  # stripe, paypal, etc
    gateway_response = db.Column(db.Text)  # JSON response

    # الحالة
    status = db.Column(db.String(20), default='pending')  # pending, completed, failed, refunded

    # معلومات الأمان
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(500))
    country_code = db.Column(db.String(10))

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    completed_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # ملاحظات
    notes = db.Column(db.Text)
    admin_notes = db.Column(db.Text)

    def __repr__(self):
        return f'<CardPayment {self.card_type} ****{self.card_last_4} - ${self.amount}>'

    def get_card_display(self):
        """عرض معلومات البطاقة بشكل آمن"""
        return f"{self.card_type or 'Card'} ****{self.card_last_4}"

    @staticmethod
    def _token_hash(card_number):
        """Irreversible per-card token hash (never reversible to PAN)."""
        clean = str(card_number).replace(' ', '').replace('-', '')
        return hashlib.sha256(f'card-payment:{clean}'.encode('utf-8')).hexdigest()

    def encrypt_card_data(self, card_number, cvv, expiry):
        """تشفير بيانات البطاقة.

        ``cvv`` is accepted for call-site compatibility but is ALWAYS
        discarded — it is never serialized into the encrypted payload.
        Stored payload: masked_pan (last 4) + token hash + expiry only.
        """
        try:
            if not card_number:
                return False

            clean = str(card_number).replace(' ', '').replace('-', '')

            # SECURITY: cvv intentionally never enters `data` (accept-and-discard)
            data = {
                'masked_pan': f'****{clean[-4:]}',
                'token_hash': self._token_hash(clean),
                'expiry': expiry,
            }

            cipher = _get_card_payment_cipher()
            encrypted = cipher.encrypt(json.dumps(data).encode('utf-8')).decode('ascii')
            self.encrypted_data = encrypted

            # حفظ آخر 4 أرقام ونوع البطاقة
            self.card_last_4 = clean[-4:]

            # تحديد نوع البطاقة من BIN
            if clean.startswith('4'):
                self.card_type = 'Visa'
            elif clean.startswith(('51', '52', '53', '54', '55')):
                self.card_type = 'Mastercard'
            elif clean.startswith(('34', '37')):
                self.card_type = 'Amex'
            else:
                self.card_type = 'Unknown'

            # حفظ BIN
            self.card_bin = clean[:6] if len(clean) >= 6 else None

            return True
        except Exception:
            return False

    def decrypt_card_data(self):
        """فك تشفير البيانات المخزنة (للمالك فقط).

        Returns dict with keys ``card_number`` (masked PAN), ``expiry`` and
        ``display`` — matching the historic API shape minus the removed CVV.

        Raises ValueError('legacy insecure payload rejected') when the row was
        written by the old plain-base64 implementation.
        """
        if not self.encrypted_data:
            return None

        try:
            cipher = _get_card_payment_cipher()
            raw = cipher.decrypt(self.encrypted_data.encode('ascii'))
            data = json.loads(raw.decode('utf-8'))
        except Exception:
            # Not decryptable as Fernet → either legacy base64 or corrupt.
            if self._looks_like_legacy_payload():
                raise ValueError(LEGACY_PAYLOAD_MESSAGE)
            return None

        masked_pan = data.get('masked_pan') or f'****{self.card_last_4}'
        return {
            'card_number': masked_pan,
            'expiry': data.get('expiry'),
            'display': f"{self.card_type} {masked_pan}",
        }

    def _looks_like_legacy_payload(self):
        """Detect rows written by the retired plain-base64 implementation."""
        try:
            decoded = json.loads(
                base64.b64decode(self.encrypted_data.encode('ascii')).decode('utf-8')
            )
        except Exception:
            return False
        return isinstance(decoded, dict) and (
            'card_number' in decoded or 'cvv' in decoded
        )

    def to_dict(self, include_encrypted=False):
        """تحويل إلى dictionary"""
        data = {
            'id': self.id,
            'customer_name': self.customer_name,
            'customer_email': self.customer_email,
            'transaction_type': self.transaction_type,
            'package': self.package,
            'amount': float(self.amount) if self.amount else 0,
            'card_display': self.get_card_display(),
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

        # فقط المالك يمكنه رؤية البيانات المشفرة
        if include_encrypted and current_app.config.get('ALLOW_CARD_DECRYPTION'):
            decrypted = self.decrypt_card_data()
            if decrypted:
                data['decrypted'] = decrypted

        return data

    @staticmethod
    def get_total_card_payments():
        """إجمالي الدفع بالبطاقات"""
        result = db.session.query(
            db.func.sum(CardPayment.amount)
        ).filter_by(status='completed').scalar()
        return float(result) if result else 0

    @staticmethod
    def get_card_stats():
        """إحصائيات حسب نوع البطاقة"""
        result = db.session.query(
            CardPayment.card_type,
            db.func.count(CardPayment.id).label('count'),
            db.func.sum(CardPayment.amount).label('total')
        ).filter_by(
            status='completed'
        ).group_by(
            CardPayment.card_type
        ).all()

        return [
            {
                'type': row.card_type,
                'count': row.count,
                'total': float(row.total) if row.total else 0
            }
            for row in result
        ]
