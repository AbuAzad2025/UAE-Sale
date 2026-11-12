"""سجل تحققات النسخ الاحتياطية — توثيق قابل للمراجعة (نتائج آلةَ الفحص)."""

from datetime import datetime, timezone

from extensions import db


class BackupVerification(db.Model):
    __tablename__ = "backup_verifications"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(300), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    checksum = db.Column(db.String(64))

    status = db.Column(db.String(16), nullable=False, default="failed", index=True)
    dialect = db.Column(db.String(32))
    table_count = db.Column(db.Integer, nullable=False, default=0)
    data_markers = db.Column(db.Integer, nullable=False, default=0)

    checks_json = db.Column(db.Text)  # JSON array<string>
    error = db.Column(db.Text)

    verified_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self):
        return f"<BackupVerification {self.filename} {self.status}>"
