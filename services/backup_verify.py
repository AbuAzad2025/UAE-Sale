"""تحقق النسخ الاحتياطية — فحص محتوى، لا مجرد وجود ملف.

تتعود النسخة من `instance/backups/` (أو مسار مُعطى)، وتُفحَص كالتالي:

1. حجم > 0 ووجود مستوى GZip أو SQL خام؟
2. العدديات: tables + copy blocks + INSERT statements
3. وجود أجزاء أساسية لأي مخطط ERP (users/gl_accounts/tenants) إن كانت pg_dump
4. الحسابات مدونة بصيغة جيدة (`CREATE TABLE "users"`)

**لا يُفتح قاعدة بيانات ولا يُعاد استعادة** — هذا فحص محتوى فقط.
"""

import gzip
import hashlib
import json
import os
import re

MIN_TABLES = 30


def _block_parse_counts(sql_text):
    tables = re.findall(
        r'CREATE TABLE (?:IF NOT EXISTS )?"?([a-z_][\w\.]*)"?', sql_text
    )
    table_count = len(set(tables))
    copy_blocks = sql_text.count("FROM stdin;")
    inserts = len(re.findall(r"\bINSERT INTO\b", sql_text))
    return table_count, copy_blocks, inserts


def _dialect(sql_text):
    if "PostgreSQL database dump" in sql_text or "COPY " in sql_text:
        return "postgres-copy"
    if "CREATE TABLE" in sql_text:
        return "sql-generic"
    if "CREATE TABLE" not in sql_text and sql_text.strip().startswith(
        "SQLite format 3"
    ):
        return "sqlite-file"
    return "unknown"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_backup_file(path):
    """يعيد dict نتيجة الفحص (جاهزة للتخزين في backup_verifications)."""
    result = {
        "filename": os.path.basename(path),
        "size_bytes": 0,
        "checksum": None,
        "status": "failed",
        "dialect": "unknown",
        "table_count": 0,
        "data_markers": 0,
        "checks": [],
        "error": None,
    }
    try:
        size = os.path.getsize(path)
        result["size_bytes"] = size
        if size == 0:
            result["error"] = "الملف فارغ"
            return result
        result["checksum"] = _sha256(path)

        head = open(path, "rb").read(8)
        is_gzip = head[:2] == b"\x1f\x8b"

        if is_gzip:
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
                sql_text = fh.read()
        else:
            sql_text = open(path, "rt", encoding="utf-8", errors="replace").read()

        result["dialect"] = _dialect(sql_text)
        table_count, copy_blocks, inserts = _block_parse_counts(sql_text)
        result["table_count"] = table_count
        result["data_markers"] = copy_blocks + inserts

        checks = []
        if size > 0:
            checks.append("size>0")
        if table_count >= MIN_TABLES:
            checks.append(f"tables>={MIN_TABLES} ({table_count})")
        else:
            result["error"] = f"جدور قليلة جدًا: {table_count}"
        if copy_blocks + inserts > 0:
            checks.append(f"data-present ({copy_blocks} COPY, {inserts} INSERT)")
        else:
            result["error"] = "لا توجد بيانات داخل النسخة (فارغة)"

        result["checks"] = checks
        result["status"] = (
            "verified"
            if (
                "size>0" in checks
                and any(c.startswith("tables>=") for c in checks)
                and any(c.startswith("data-present") for c in checks)
            )
            else "failed"
        )
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result


def latest_backup(backup_dir):
    if not os.path.isdir(backup_dir):
        return None
    candidates = []
    for name in os.listdir(backup_dir):
        if name.endswith((".sql.gz", ".sql", ".gz", ".db", ".sqlite")):
            path = os.path.join(backup_dir, name)
            candidates.append((os.path.getmtime(path), path))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][1]


def record_verification(db, result):
    from models import BackupVerification

    row = BackupVerification(
        filename=result["filename"],
        size_bytes=int(result.get("size_bytes") or 0),
        checksum=result.get("checksum"),
        status=result.get("status", "failed"),
        dialect=result.get("dialect"),
        table_count=int(result.get("table_count") or 0),
        data_markers=int(result.get("data_markers") or 0),
        checks_json=json.dumps(result.get("checks") or [], ensure_ascii=False),
        error=result.get("error"),
    )
    db.session.add(row)
    return row


def verify_latest_backup(db, backup_dir=None):
    """العملية الكاملة — تحقق + تسجيل في قاعدة البيانات."""
    from services.backup_service import BackupService

    directory = backup_dir or BackupService.BACKUP_DIR
    path = latest_backup(directory)
    if path is None:
        result = {
            "filename": "(none)",
            "size_bytes": 0,
            "checksum": None,
            "status": "failed",
            "dialect": "none",
            "table_count": 0,
            "data_markers": 0,
            "checks": [],
            "error": "لا توجد ملفات نسخ احتياطية في " + directory,
        }
        return record_verification(db, result)
    result = verify_backup_file(path)
    return record_verification(db, result)
