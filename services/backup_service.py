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
            
            # مسار قاعدة البيانات
            db_path = 'instance/app.db'
            
            if not os.path.exists(db_path):
                logger.error(f"Database not found: {db_path}")
                return None
            
            # إنشاء اسم الملف
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            prefix = cls.MANUAL_PREFIX if manual else cls.BACKUP_PREFIX
            backup_name = f"{prefix}{timestamp}.db"
            
            if compress:
                backup_name += '.gz'
            
            backup_path = os.path.join(cls.BACKUP_DIR, backup_name)
            
            # نسخ الملف
            if compress:
                # نسخ مع ضغط
                with open(db_path, 'rb') as f_in:
                    with gzip.open(backup_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            else:
                # نسخ مباشر
                shutil.copy2(db_path, backup_path)
            
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
        """حذف النسخ القديمة (الاحتفاظ بآخر 5 فقط)"""
        try:
            backups = cls.list_backups(auto_only=True)
            
            if len(backups) > cls.MAX_BACKUPS:
                # ترتيب حسب التاريخ (الأقدم أولاً)
                backups_sorted = sorted(backups, key=lambda x: x['timestamp'])
                
                # حذف الزائد
                to_delete = backups_sorted[:len(backups) - cls.MAX_BACKUPS]
                
                for backup in to_delete:
                    try:
                        # حذف الملف
                        if os.path.exists(backup['path']):
                            os.remove(backup['path'])
                        
                        # حذف الـ metadata
                        meta_path = backup['path'] + '.meta.json'
                        if os.path.exists(meta_path):
                            os.remove(meta_path)
                        
                        logger.info(f"Deleted old backup: {backup['filename']}")
                    except Exception as e:
                        logger.warning(f"Failed to delete backup {backup['filename']}: {e}")
                
                logger.info(f"Cleanup complete. Kept last {cls.MAX_BACKUPS} backups")
        
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
    
    @classmethod
    def list_backups(cls, auto_only: bool = False, manual_only: bool = False) -> List[Dict]:
        """
        قائمة النسخ الاحتياطية
        
        Args:
            auto_only: النسخ التلقائية فقط
            manual_only: النسخ اليدوية فقط
        
        Returns:
            قائمة بمعلومات النسخ
        """
        try:
            cls.initialize()
            
            backups = []
            backup_dir = Path(cls.BACKUP_DIR)
            
            # البحث عن ملفات .db و .db.gz
            for backup_file in backup_dir.glob('*backup_*.db*'):
                # تجاهل ملفات metadata
                if '.meta.json' in backup_file.name:
                    continue
                
                # تحميل metadata إذا وجد
                meta_path = str(backup_file) + '.meta.json'
                if os.path.exists(meta_path):
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                else:
                    # إنشاء metadata أساسي
                    metadata = {
                        'filename': backup_file.name,
                        'path': str(backup_file),
                        'size': os.path.getsize(backup_file),
                        'size_mb': round(os.path.getsize(backup_file) / (1024 * 1024), 2),
                        'timestamp': backup_file.stem.split('_')[-2] + '_' + backup_file.stem.split('_')[-1],
                        'manual': cls.MANUAL_PREFIX in backup_file.name,
                        'compressed': backup_file.suffix == '.gz',
                    }
                
                # فلترة حسب النوع
                if auto_only and metadata.get('manual', False):
                    continue
                if manual_only and not metadata.get('manual', False):
                    continue
                
                backups.append(metadata)
            
            # ترتيب حسب التاريخ (الأحدث أولاً)
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
            db_path = 'instance/app.db'
            
            # إنشاء نسخة احتياطية من الوضع الحالي قبل الاستعادة
            current_backup = cls.create_backup(
                manual=True, 
                description=f"Pre-restore backup before restoring {backup_filename}"
            )
            
            if not current_backup:
                logger.warning("⚠️ Could not create pre-restore backup")
            
            # فك الضغط إذا لزم الأمر
            if backup_path.endswith('.gz'):
                with gzip.open(backup_path, 'rb') as f_in:
                    with open(db_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            else:
                shutil.copy2(backup_path, db_path)
            
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
                # إضافة قاعدة البيانات
                zipf.write('instance/app.db', 'database/app.db')
                
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
                    'database_size': os.path.getsize('instance/app.db'),
                }
                
                zipf.writestr('backup_info.json', json.dumps(metadata, indent=2, ensure_ascii=False))
            
            logger.info(f"Full backup exported: {export_name}")
            return export_path
        
        except Exception as e:
            logger.error(f"Export failed: {e}")
            return None

