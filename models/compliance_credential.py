"""Compliance credential vault — شركة × سلطة (ZATCA/FTA/ETA/...).

كل سجل يمثل اعتماد الشركة لدى سلطة ضريبية واحدة. الحمولة (شهادة/مفتاح/سر)
مُشفّرة كاملة عند الراحة بختم Fernet (نفس أسلوب Card Vault)؛ الحقول غير
السرية تظهر كما هي في النماذج. لا شيء من هنا يُرسَل إلى أي سلطة.
"""

from datetime import datetime, timezone

from extensions import db


class ComplianceCredential(db.Model):
    __tablename__ = "compliance_credentials"

    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id",
            "authority_key",
            name="uq_compliance_credential_tenant_authority",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    authority_key = db.Column(db.String(40), nullable=False, index=True)

    payload_encrypted = db.Column(db.Text)
    status = db.Column(
        db.String(20), nullable=False, default="configured"
    )  # configured | verified
    notes = db.Column(db.Text)

    last_rotated_at = db.Column(db.DateTime)
    verified_at = db.Column(db.DateTime)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return f"<ComplianceCredential tenant={self.tenant_id} {self.authority_key}>"
