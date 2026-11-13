"""
Backup Service - Professional Automated Backup System
خدمة النسخ الاحتياطي الاحترافي مع التشفير والأمان العالي
"""

import os
import shutil
import gzip
import json
import hashlib
import tempfile
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


def _validated_backup_path(backup_dir: str, filename) -> Optional[str]:
    """Resolve *filename* inside *backup_dir* or return None when unsafe.

    Fail-closed wrapper around utils.db_safety.validate_backup_filename so
    direct service callers (not just the owner routes) are protected against
    path traversal.
    """
    try:
        from utils.db_safety import validate_backup_filename
    except ImportError:
        return None
    try:
        return validate_backup_filename(filename, backup_dir)
    except (ValueError, TypeError):
        logger.warning("Rejected unsafe backup filename: %r", filename)
        return None


class BackupService:
    """خدمة النسخ الاحتياطي الاحترافية"""

    _BASEDIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    BACKUP_DIR = os.path.join(_BASEDIR, "instance", "backups")
    MAX_BACKUPS = 5  # آخر 5 نسخ فقط
    BACKUP_PREFIX = "auto_backup_"
    MANUAL_PREFIX = "manual_backup_"

    FREQUENCY_INTERVAL_HOURS = {
        "hourly": 1,
        "daily": 24,
        "weekly": 24 * 7,
        "monthly": 24 * 30,
    }

    @classmethod
    def _schedule_settings_path(cls) -> str:
        return os.path.join(cls._BASEDIR, "instance", "backup_settings.json")

    @classmethod
    def _schedule_state_path(cls) -> str:
        return os.path.join(cls._BASEDIR, "instance", "backup_state.json")

    @classmethod
    def _load_json_file(cls, file_path: str) -> Optional[Dict]:
        try:
            if not os.path.exists(file_path):
                return None
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    @classmethod
    def _write_json_file(cls, file_path: str, data: Dict) -> bool:
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    @classmethod
    def get_schedule_settings(cls) -> Dict:
        settings = cls._load_json_file(cls._schedule_settings_path()) or {}
        return {
            "enabled": bool(settings.get("enabled", True)),
            "frequency": str(settings.get("frequency", "daily")),
            "backup_time": str(settings.get("backup_time", "02:00")),
            "keep_count": int(settings.get("keep_count", cls.MAX_BACKUPS)),
        }

    @classmethod
    def save_schedule_settings(cls, settings: Dict) -> bool:
        normalized = {
            "enabled": bool(settings.get("enabled", True)),
            "frequency": str(settings.get("frequency", "daily")),
            "backup_time": str(settings.get("backup_time", "02:00")),
            "keep_count": int(settings.get("keep_count", cls.MAX_BACKUPS)),
        }
        return cls._write_json_file(cls._schedule_settings_path(), normalized)

    @classmethod
    def _parse_state_datetime(cls, raw_value) -> Optional[datetime]:
        """Parse an ISO timestamp from schedule state; naive local on success, None otherwise."""
        if not raw_value or not isinstance(raw_value, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw_value.strip())
        except (ValueError, TypeError):
            return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed

    @classmethod
    def _resolve_interval_hours(cls, settings: Dict, state: Dict) -> int:
        """Interval between auto backups: explicit state override, else per frequency."""
        try:
            override = int(state.get("interval_hours", 0))
            if override > 0:
                return override
        except (TypeError, ValueError):
            pass
        frequency = str(settings.get("frequency", "daily")).strip().lower()
        return cls.FREQUENCY_INTERVAL_HOURS.get(frequency, 24)

    @classmethod
    def auto_backup_daily(cls) -> Optional[Dict]:
        """تشغيل النسخ الاحتياطي التلقائي عند استحقاقه.

        Reads the saved schedule settings (get_schedule_settings), runs
        create_backup when due (last run older than the configured interval),
        then records last_run in backup_state.json. Returns the backup
        metadata dict, or None when disabled / not due / failed. Never raises.
        """
        try:
            settings = cls.get_schedule_settings()
            if not settings.get("enabled", True):
                logger.info("Automatic backup disabled by schedule settings")
                return None

            state = cls._load_json_file(cls._schedule_state_path()) or {}
            interval_hours = cls._resolve_interval_hours(settings, state)
            now = datetime.now()
            last_run = cls._parse_state_datetime(state.get("last_auto_backup"))

            if last_run is not None:
                elapsed_hours = (now - last_run).total_seconds() / 3600.0
                if elapsed_hours < interval_hours:
                    logger.debug(
                        "Auto-backup not due (elapsed %.2fh < interval %dh)",
                        elapsed_hours,
                        interval_hours,
                    )
                    return None

            backup = cls.create_backup(
                manual=False, description="Scheduled automatic backup"
            )

            if not backup:
                logger.error("Automatic backup failed — last_run not advanced")
                return None

            updated_state = dict(state)
            updated_state["last_auto_backup"] = now.isoformat()
            updated_state["last_backup_filename"] = backup.get("filename")
            cls._write_json_file(cls._schedule_state_path(), updated_state)

            logger.info(
                "Automatic backup completed: %s (interval %dh)",
                backup.get("filename"),
                interval_hours,
            )
            return backup

        except Exception as e:
            logger.error(f"auto_backup_daily failed: {e}")
            return None

    @classmethod
    def get_backup_stats(cls) -> Dict:
        try:
            backups = cls.list_backups()
            total_size_bytes = sum(int(b.get("size", 0) or 0) for b in backups)
            manual_count = sum(1 for b in backups if bool(b.get("manual")))
            auto_count = max(0, len(backups) - manual_count)
            latest = backups[0] if backups else None
            return {
                "total_count": len(backups),
                "manual_count": manual_count,
                "auto_count": auto_count,
                "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
                "latest_backup": latest,
            }
        except Exception:
            return {
                "total_count": 0,
                "manual_count": 0,
                "auto_count": 0,
                "total_size_mb": 0,
                "latest_backup": None,
            }

    @classmethod
    def _parse_postgres_params(cls) -> Optional[Dict[str, str]]:
        """استخراج بيانات الاتصال من إعدادات SQLAlchemy"""
        try:
            from extensions import db

            url = db.engine.url

            if "postgresql" not in url.drivername and "postgres" not in url.drivername:
                return None

            host = url.host
            port = url.port or 5432
            username = url.username
            password = url.password
            dbname = (url.database or "").lstrip("/")

            if not host or not username or not dbname:
                return None

            normalized_host = str(host)
            if normalized_host.lower() in ("localhost", "::1"):
                normalized_host = "127.0.0.1"

            return {
                "host": normalized_host,
                "port": str(port),
                "username": str(username),
                "password": str(password) if password else "",
                "dbname": str(dbname),
            }
        except Exception as e:
            logger.error(f"Error parsing DB params: {e}")
            return None

    @classmethod
    def initialize(cls):
        """تهيئة مجلد النسخ الاحتياطي"""
        try:
            os.makedirs(cls.BACKUP_DIR, exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"Failed to initialize backup directory: {e}")
            return False

    @classmethod
    def create_backup(
        cls,
        manual: bool = False,
        compress: bool = True,  # noqa: C901
        encrypt: bool = False,
        description: str = "",
    ) -> Optional[Dict]:
        """
        إنشاء نسخة احتياطية
        """
        try:
            cls.initialize()

            params = cls._parse_postgres_params()
            if not params:
                logger.error(
                    "Only PostgreSQL backups are supported or failed to parse DB URL"
                )
                return None

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = cls.MANUAL_PREFIX if manual else cls.BACKUP_PREFIX

            # Let's use SQL format compressed with gzip as it's universally readable and less prone to version mismatch issues than custom binary formats sometimes.  # noqa: E501

            backup_name = f"{prefix}{timestamp}.sql.gz"
            backup_path = os.path.join(cls.BACKUP_DIR, backup_name)

            pg_dump_env = os.environ.get("PG_DUMP_PATH", "").strip()
            pg_dump = (
                pg_dump_env if pg_dump_env else shutil.which("pg_dump") or "pg_dump"
            )
            cmd = [
                pg_dump,
                "--host",
                params["host"],
                "--port",
                params["port"],
                "--username",
                params["username"],
                "--no-owner",
                "--no-privileges",
                "--clean",
                "--if-exists",
                params["dbname"],
            ]
            os.environ["PGPASSWORD"] = params["password"]
            os.environ["PGHOST"] = params["host"]
            os.environ["PGPORT"] = str(params["port"])
            os.environ["PGUSER"] = params["username"]
            os.environ["PGDATABASE"] = params["dbname"]

            temp_dir = tempfile.gettempdir()
            temp_sql_path = os.path.join(
                temp_dir, f"backup_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.sql"
            )
            try:
                process = subprocess.run(
                    cmd + ["-f", temp_sql_path],
                    capture_output=True,
                    text=True,
                )
                if process.returncode != 0:
                    err_text = (process.stderr or "").strip()
                    logger.error(f"pg_dump failed: {err_text}")
                    try:
                        if os.path.exists(temp_sql_path):
                            os.remove(temp_sql_path)
                    except Exception:
                        pass
                    return None
                with (
                    open(temp_sql_path, "rb") as f_in,
                    gzip.open(backup_path, "wb") as f_out,
                ):
                    shutil.copyfileobj(f_in, f_out)
            except FileNotFoundError:
                logger.warning(
                    "pg_dump not found. Set PG_DUMP_PATH to pg_dump.exe path."
                )
                return None
            except Exception as e:
                logger.error(f"Error executing pg_dump: {e}")
                try:
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
                except Exception:
                    pass
                return None
            finally:
                try:
                    if os.path.exists(temp_sql_path):
                        os.remove(temp_sql_path)
                except Exception:
                    pass

            if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
                logger.error("Backup file is empty or not created")
                return None

            file_size = os.path.getsize(backup_path)
            checksum = cls._calculate_checksum(backup_path)

            metadata = {
                "filename": backup_name,
                "path": backup_path,
                "timestamp": timestamp,
                "datetime": datetime.now().isoformat(),
                "size": file_size,
                "size_mb": round(file_size / (1024 * 1024), 2),
                "compressed": True,
                "encrypted": False,
                "manual": manual,
                "description": description,
                "checksum": checksum,
                "type": "postgresql_sql_gz",
            }

            metadata_path = backup_path + ".meta.json"
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            logger.info(f"Backup created successfully: {backup_name}")

            if not manual:
                cls._cleanup_old_backups()

            return metadata

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return None

    @classmethod
    def _calculate_checksum(cls, file_path: str) -> str:
        """حساب الـ checksum للملف"""
        try:
            sha256_hash = hashlib.sha256()
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception:
            return ""

    @classmethod
    def _cleanup_old_backups(cls):
        try:
            keep_count = cls.MAX_BACKUPS
            try:
                settings = cls.get_schedule_settings()
                keep_count = int(settings.get("keep_count", keep_count))
            except Exception:
                pass

            backups = cls.list_backups(auto_only=True)

            if len(backups) > keep_count:
                backups_sorted = sorted(backups, key=lambda x: x["timestamp"])
                to_delete = backups_sorted[: len(backups) - keep_count]

                for backup in to_delete:
                    cls.delete_backup(backup["filename"])

                logger.info(f"Cleanup complete. Kept last {keep_count} backups")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")

    @classmethod
    def list_backups(
        cls, auto_only: bool = False, manual_only: bool = False
    ) -> List[Dict]:  # noqa: C901
        try:
            cls.initialize()

            backups = []
            backup_dir = Path(cls.BACKUP_DIR)

            candidates = []
            candidates.extend(list(backup_dir.glob("*.sql.gz")))
            candidates.extend(list(backup_dir.glob("*.dump")))

            processed_names = set()

            for backup_file in sorted(candidates, key=os.path.getmtime, reverse=True):
                if backup_file.name in processed_names:
                    continue

                processed_names.add(backup_file.name)

                meta_path = str(backup_file) + ".meta.json"
                metadata = {}

                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            metadata = json.load(f)
                    except Exception:
                        pass

                if not metadata:
                    name = backup_file.name
                    is_manual = cls.MANUAL_PREFIX in name

                    ts_str = (
                        name.replace(cls.MANUAL_PREFIX, "")
                        .replace(cls.BACKUP_PREFIX, "")
                        .split(".")[0]
                    )

                    metadata = {
                        "filename": backup_file.name,
                        "path": str(backup_file),
                        "size": os.path.getsize(backup_file),
                        "size_mb": round(
                            os.path.getsize(backup_file) / (1024 * 1024), 2
                        ),
                        "timestamp": ts_str,
                        "datetime": datetime.fromtimestamp(
                            os.path.getmtime(backup_file)
                        ).isoformat(),
                        "manual": is_manual,
                        "compressed": name.endswith(".gz"),
                    }

                if auto_only and metadata.get("manual", False):
                    continue
                if manual_only and not metadata.get("manual", False):
                    continue

                backups.append(metadata)

            return backups

        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
            return []

    @classmethod
    def verify_backup(cls, filename: str) -> bool:  # noqa: C901
        """التحقق من سلامة نسخة احتياطية"""
        try:
            backup_path = _validated_backup_path(cls.BACKUP_DIR, filename)
            if not backup_path:
                return False
            if not os.path.exists(backup_path):
                return False

            if os.path.getsize(backup_path) == 0:
                return False

            if filename.endswith(".gz"):
                try:
                    with gzip.open(backup_path, "rb") as f:
                        for _chunk in iter(lambda: f.read(65536), b""):
                            pass
                except Exception:
                    return False

            meta_path = backup_path + ".meta.json"
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    return False
                stored_checksum = (
                    meta.get("checksum") if isinstance(meta, dict) else None
                )
                if stored_checksum:
                    current_checksum = cls._calculate_checksum(backup_path)
                    if not current_checksum or current_checksum != stored_checksum:
                        return False

            return True
        except Exception:
            return False

    @classmethod
    def restore_backup(cls, backup_filename: str) -> bool:  # noqa: C901
        """
        استعادة نسخة احتياطية
        """
        try:
            cls.initialize()
            backup_path = _validated_backup_path(cls.BACKUP_DIR, backup_filename)
            if not backup_path:
                logger.error(f"Rejected unsafe backup filename: {backup_filename!r}")
                return False

            if not os.path.exists(backup_path):
                logger.error(f"Backup file not found: {backup_filename}")
                return False

            params = cls._parse_postgres_params()
            if not params:
                return False

            cls.create_backup(
                manual=True, description=f"Pre-restore before {backup_filename}"
            )

            psql = os.environ.get("PSQL_PATH", "psql")
            pg_restore = os.environ.get("PG_RESTORE_PATH", "pg_restore")

            env = os.environ.copy()
            dsn = f"postgresql://{params['username']}:{params['password']}@{params['host']}:{params['port']}/{params['dbname']}"

            if backup_filename.endswith(".dump"):
                temp_dir = tempfile.gettempdir()
                temp_path = os.path.join(
                    temp_dir, f"restore_{datetime.now().strftime('%f')}.dump"
                )
                shutil.copy2(backup_path, temp_path)

                try:
                    cmd = [
                        pg_restore,
                        "--host",
                        params["host"],
                        "--port",
                        params["port"],
                        "--username",
                        params["username"],
                        "--dbname",
                        params["dbname"],
                        "--clean",
                        "--if-exists",
                        "--no-owner",
                        "--no-privileges",
                        temp_path,
                    ]

                    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
                    if proc.returncode != 0:
                        logger.error(f"pg_restore failed: {proc.stderr}")
                        return False

                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)

            else:
                cmd = [psql, "--dbname", dsn, "--set", "ON_ERROR_STOP=on"]

                if backup_filename.endswith(".gz"):
                    f_in = gzip.open(backup_path, "rb")
                else:
                    f_in = open(backup_path, "rb")

                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdin=f_in,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=env,
                    )
                    _, stderr = proc.communicate()

                    if proc.returncode != 0:
                        logger.error(
                            f"psql restore failed: {stderr.decode('utf-8', errors='replace')}"
                        )
                        return False

                finally:
                    f_in.close()

            logger.info(f"Database restored successfully from {backup_filename}")
            return True

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    @classmethod
    def delete_backup(cls, backup_filename: str) -> bool:
        try:
            backup_path = _validated_backup_path(cls.BACKUP_DIR, backup_filename)
            if not backup_path:
                logger.error(f"Rejected unsafe backup filename: {backup_filename!r}")
                return False
            meta_path = backup_path + ".meta.json"

            logger.info(f"Attempting to delete backup: {backup_path}")

            if not os.path.exists(backup_path):
                logger.warning(f"Backup file not found (noop): {backup_path}")
                if os.path.exists(meta_path):
                    try:
                        os.remove(meta_path)
                    except Exception:
                        pass
                return True

            os.remove(backup_path)
            logger.info(f"Deleted backup file: {backup_path}")

            if os.path.exists(meta_path):
                os.remove(meta_path)
                logger.info(f"Deleted metadata file: {meta_path}")

            return True
        except Exception as e:
            logger.error(f"Failed to delete backup {backup_filename}: {e}")
            return False
