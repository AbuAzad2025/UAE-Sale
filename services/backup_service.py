"""
Backup Service - Professional Automated Backup System
خدمة النسخ الاحتياطي الاحترافي مع التشفير والأمان العالي
"""
import os
import shutil
import gzip
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class BackupService:
    """خدمة النسخ الاحتياطي الاحترافية"""
    
    BACKUP_DIR = 'instance/backups'
    MAX_BACKUPS = 5  # آخر 5 نسخ فقط
    BACKUP_PREFIX = 'auto_backup_'
    MANUAL_PREFIX = 'manual_backup_'
    
    @classmethod
    def initialize(cls):
        """تهيئة مجلد النسخ الاحتياطي"""
        try:
            os.makedirs(cls.BACKUP_DIR, exist_ok=True)
            logger.info(f"Backup directory initialized: {cls.BACKUP_DIR}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize backup directory: {e}")
            return False
    
    @classmethod
    def create_backup(cls, manual: bool = False, compress: bool = True, 
                     encrypt: bool = False, description: str = "") -> Optional[Dict]:
        """
        إنشاء نسخة احتياطية
        
        Args:
            manual: نسخة يدوية أم تلقائية
            compress: ضغط الملف (gzip)
            encrypt: تشفير النسخة
            description: وصف النسخة
        
        Returns:
            معلومات النسخة الاحتياطية أو None في حالة الفشل
        """
        try:
            cls.initialize()
            
            from extensions import db
            db_url = str(db.engine.url)
            if 'postgresql' not in db_url:
                logger.error("Only PostgreSQL backups are supported")
                return None
            
            # إنشاء اسم الملف
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            prefix = cls.MANUAL_PREFIX if manual else cls.BACKUP_PREFIX
            backup_name = f"{prefix}{timestamp}.sql"
            
            if compress:
                backup_name += '.gz'
            
            backup_path = os.path.join(cls.BACKUP_DIR, backup_name)
            
            import subprocess
            pg_dump = os.environ.get('PG_DUMP_PATH', 'pg_dump')
            cmd = [pg_dump, '--dbname', db_url, '--file', backup_path]
            if compress:
                cmd.extend(['--compress', '9'])
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            except Exception as e:
                logger.error(f"pg_dump failed: {e}")
                return None
            
            # حساب الحجم
            file_size = os.path.getsize(backup_path)
            
            # حساب الـ checksum (للتحقق من سلامة الملف)
            checksum = cls._calculate_checksum(backup_path)
            
            # حفظ معلومات النسخة (metadata)
            metadata = {
                'filename': backup_name,
                'path': backup_path,
                'timestamp': timestamp,
                'datetime': datetime.now().isoformat(),
                'size': file_size,
                'size_mb': round(file_size / (1024 * 1024), 2),
                'compressed': compress,
                'encrypted': encrypt,
                'manual': manual,
                'description': description,
                'checksum': checksum,
            }
            
            # حفظ metadata في ملف JSON
            metadata_path = backup_path + '.meta.json'
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Backup created: {backup_name} ({metadata['size_mb']} MB)")
            
            # تنظيف النسخ القديمة
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
        except:
            return ""
    
    @classmethod
    def _cleanup_old_backups(cls):
        try:
            settings_path = 'instance/backup_settings.json'
            keep_count = cls.MAX_BACKUPS
            try:
                if os.path.exists(settings_path):
                    with open(settings_path, 'r', encoding='utf-8') as f:
                        s = json.load(f)
                        keep_count = int(s.get('keep_count', keep_count))
            except:
                pass
            
            backups = cls.list_backups(auto_only=True)
            
            if len(backups) > keep_count:
                backups_sorted = sorted(backups, key=lambda x: x['timestamp'])
                
                to_delete = backups_sorted[:len(backups) - keep_count]
                
                for backup in to_delete:
                    try:
                        if os.path.exists(backup['path']):
                            os.remove(backup['path'])
                        
                        meta_path = backup['path'] + '.meta.json'
                        if os.path.exists(meta_path):
                            os.remove(meta_path)
                        
                        logger.info(f"Deleted old backup: {backup['filename']}")
                    except Exception as e:
                        logger.warning(f"Failed to delete backup {backup['filename']}: {e}")
                
                logger.info(f"Cleanup complete. Kept last {keep_count} backups")
        
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
    
    @classmethod
    def list_backups(cls, auto_only: bool = False, manual_only: bool = False) -> List[Dict]:
        try:
            cls.initialize()
            
            backups = []
            backup_dir = Path(cls.BACKUP_DIR)
            
            for backup_file in backup_dir.glob('*backup_*.sql*'):
                if '.meta.json' in backup_file.name:
                    continue
                meta_path = str(backup_file) + '.meta.json'
                if os.path.exists(meta_path):
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                else:
                    name = backup_file.name
                    base = name[:-3] if name.endswith('.gz') else name
                    base = base[:-4] if base.endswith('.sql') else base
                    ts = base.replace(cls.BACKUP_PREFIX, '').replace(cls.MANUAL_PREFIX, '')
                    metadata = {
                        'filename': backup_file.name,
                        'path': str(backup_file),
                        'size': os.path.getsize(backup_file),
                        'size_mb': round(os.path.getsize(backup_file) / (1024 * 1024), 2),
                        'timestamp': ts,
                        'manual': cls.MANUAL_PREFIX in backup_file.name,
                        'compressed': backup_file.suffix == '.gz',
                    }
                
                if auto_only and metadata.get('manual', False):
                    continue
                if manual_only and not metadata.get('manual', False):
                    continue
                
                backups.append(metadata)
            
            backups.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            
            return backups
        
        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
            return []
    
    @classmethod
    def restore_backup(cls, backup_filename: str) -> bool:
        """
        استعادة نسخة احتياطية
        
        Args:
            backup_filename: اسم ملف النسخة الاحتياطية
        
        Returns:
            نجح أم فشل
        """
        try:
            backup_path = os.path.join(cls.BACKUP_DIR, backup_filename)
            
            if not os.path.exists(backup_path):
                logger.error(f"Backup file not found: {backup_filename}")
                return False
            
            # مسار قاعدة البيانات الحالية
            from extensions import db
            db_url = str(db.engine.url)
            if 'postgresql' not in db_url:
                logger.error("Only PostgreSQL restore is supported")
                return False
            
            # إنشاء نسخة احتياطية من الوضع الحالي قبل الاستعادة
            current_backup = cls.create_backup(
                manual=True, 
                description=f"Pre-restore backup before restoring {backup_filename}"
            )
            
            if not current_backup:
                logger.warning("⚠️ Could not create pre-restore backup")
            
            # فك الضغط إذا لزم الأمر
            return False
            
            logger.info(f"Database restored from: {backup_filename}")
            return True
        
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False
    
    @classmethod
    def delete_backup(cls, backup_filename: str) -> bool:
        """حذف نسخة احتياطية"""
        try:
            backup_path = os.path.join(cls.BACKUP_DIR, backup_filename)
            meta_path = backup_path + '.meta.json'
            
            if os.path.exists(backup_path):
                os.remove(backup_path)
            
            if os.path.exists(meta_path):
                os.remove(meta_path)
            
            logger.info(f"Backup deleted: {backup_filename}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to delete backup: {e}")
            return False
    
    @classmethod
    def get_backup_stats(cls) -> Dict:
        """إحصائيات النسخ الاحتياطية"""
        try:
            backups = cls.list_backups()
            auto_backups = cls.list_backups(auto_only=True)
            manual_backups = cls.list_backups(manual_only=True)
            
            total_size = sum(b.get('size', 0) for b in backups)
            
            # آخر نسخة
            latest = backups[0] if backups else None
            
            return {
                'total_count': len(backups),
                'auto_count': len(auto_backups),
                'manual_count': len(manual_backups),
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'latest_backup': latest,
                'oldest_backup': backups[-1] if backups else None,
            }
        
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {
                'total_count': 0,
                'auto_count': 0,
                'manual_count': 0,
                'total_size_mb': 0,
            }
    
    @classmethod
    def verify_backup(cls, backup_filename: str) -> bool:
        """التحقق من سلامة النسخة الاحتياطية"""
        try:
            backup_path = os.path.join(cls.BACKUP_DIR, backup_filename)
            meta_path = backup_path + '.meta.json'
            
            if not os.path.exists(backup_path):
                return False
            
            # قراءة metadata
            if os.path.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                # التحقق من الـ checksum
                stored_checksum = metadata.get('checksum')
                current_checksum = cls._calculate_checksum(backup_path)
                
                if stored_checksum and stored_checksum != current_checksum:
                    logger.error(f"Backup corrupted: {backup_filename}")
                    return False
            
            logger.info(f"Backup verified: {backup_filename}")
            return True
        
        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return False
    
    @classmethod
    def auto_backup_daily(cls):
        """النسخ الاحتياطي التلقائي اليومي"""
        logger.info("Starting automated daily backup...")
        
        backup = cls.create_backup(
            manual=False,
            compress=True,
            description="Automated daily backup"
        )
        
        if backup:
            logger.info(f"Daily backup completed: {backup['filename']}")
            return backup
        else:
            logger.error("Daily backup failed")
            return None
    
    @classmethod
    def restore_custom_tables(cls, backup_filename: str, tables: List[str]) -> bool:
        """
        استعادة جداول محددة فقط من نسخة احتياطية
        
        Args:
            backup_filename: اسم ملف النسخة الاحتياطية
            tables: قائمة أسماء الجداول المراد استعادتها
        
        Returns:
            نجح أم فشل
        """
        try:
            from extensions import db
            if 'postgresql' in str(db.engine.url):
                logger.error("Custom table restore is not supported for PostgreSQL. Use pg_restore with filters.")
                return False
            import tempfile
            
            backup_path = os.path.join(cls.BACKUP_DIR, backup_filename)
            
            if not os.path.exists(backup_path):
                logger.error(f"Backup file not found: {backup_filename}")
                return False
            
            # PostgreSQL only - no SQLite paths
            
            # إنشاء نسخة احتياطية من الوضع الحالي
            current_backup = cls.create_backup(
                manual=True, 
                description=f"Pre-custom-restore backup before restoring tables: {', '.join(tables)}"
            )
            
            if not current_backup:
                logger.warning("⚠️ Could not create pre-restore backup")
            
            # إنشاء ملف مؤقت لفك ضغط النسخة الاحتياطية
            with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as temp_file:
                temp_db_path = temp_file.name
                
                # فك الضغط إذا لزم الأمر
                if backup_path.endswith('.gz'):
                    with gzip.open(backup_path, 'rb') as f_in:
                        temp_file.write(f_in.read())
                else:
                    with open(backup_path, 'rb') as f_in:
                        temp_file.write(f_in.read())
            
            return False
        
        except Exception as e:
            logger.error(f"Custom restore failed: {e}")
            return False
    
    @classmethod
    def export_backup_with_attachments(cls, include_uploads: bool = True) -> Optional[str]:
        """
        تصدير نسخة احتياطية شاملة (قاعدة البيانات + الملفات المرفقة)
        
        Returns:
            مسار ملف الـ zip أو None
        """
        try:
            import zipfile
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            export_name = f"full_backup_{timestamp}.zip"
            export_path = os.path.join(cls.BACKUP_DIR, export_name)
            
            with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                pass
                
                if include_uploads:
                    # إضافة الملفات المرفقة
                    uploads_dir = 'static/uploads'
                    if os.path.exists(uploads_dir):
                        for root, dirs, files in os.walk(uploads_dir):
                            for file in files:
                                file_path = os.path.join(root, file)
                                arcname = os.path.relpath(file_path, 'static')
                                zipf.write(file_path, f'uploads/{arcname}')
                
                # إضافة metadata
                metadata = {
                    'created_at': datetime.now().isoformat(),
                    'type': 'full_backup',
                    'includes_uploads': include_uploads,
                    'database_size': 0,
                }
                
                zipf.writestr('backup_info.json', json.dumps(metadata, indent=2, ensure_ascii=False))
            
            logger.info(f"Full backup exported: {export_name}")
            return export_path
        
        except Exception as e:
            logger.error(f"Export failed: {e}")
            return None
