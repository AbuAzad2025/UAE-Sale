import json
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from werkzeug.utils import secure_filename
from flask import current_app, request
from extensions import db


def _parse_sequence(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def generate_number(prefix, model, field_name='sale_number', date_format='%Y', max_retries=5):
    """Generate a unique sequential number with distributed locking.

    Uses Redis-based distributed lock to prevent duplicate numbers
    in multi-worker deployments. Falls back to retry+UUID if Redis
    is unavailable.
    """
    import time
    import uuid
    year = datetime.now().strftime(date_format)
    lock_name = f'gen_number:{prefix}:{year}'

    try:
        from utils.distributed_lock import distributed_lock
        with distributed_lock(lock_name, timeout=10, blocking_timeout=5):
            # Inside the lock — safe to read max and increment
            latest = db.session.query(model).filter(
                getattr(model, field_name).like(f'{prefix}-{year}-%')
            ).order_by(
                getattr(model, field_name).desc()
            ).first()

            if latest:
                last_number = getattr(latest, field_name).split('-')[-1]
                seq = _parse_sequence(last_number)
                next_number = seq + 1 if seq is not None else 1
            else:
                next_number = 1

            candidate = f'{prefix}-{year}-{next_number:04d}'

            # Check for collision (belt-and-suspenders)
            existing = db.session.query(model).filter(
                getattr(model, field_name) == candidate
            ).first()

            if not existing:
                return candidate

            # Collision inside the lock — very unlikely; retry once
            next_number += 1
            candidate = f'{prefix}-{year}-{next_number:04d}'
            existing = db.session.query(model).filter(
                getattr(model, field_name) == candidate
            ).first()

            if not existing:
                return candidate
    except ImportError:
        pass  # distributed_lock not available — use fallback below
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'Distributed lock failed for {lock_name}: {e}')

    # Fallback: retry-only approach (no distributed lock)
    for attempt in range(max_retries):
        latest = db.session.query(model).filter(
            getattr(model, field_name).like(f'{prefix}-{year}-%')
        ).order_by(
            getattr(model, field_name).desc()
        ).first()

        if latest:
            last_number = getattr(latest, field_name).split('-')[-1]
            seq = _parse_sequence(last_number)
            next_number = seq + 1 if seq is not None else 1
        else:
            next_number = 1

        candidate = f'{prefix}-{year}-{next_number:04d}'

        existing = db.session.query(model).filter(
            getattr(model, field_name) == candidate
        ).first()

        if not existing:
            return candidate

        time.sleep(0.01 * (attempt + 1))

    # Final fallback: use UUID suffix
    return f'{prefix}-{year}-{uuid.uuid4().hex[:8].upper()}'


def get_next_number(prefix, model_class, number_field='number'):
    year = datetime.now().year
    pattern = f'{prefix}-{year}-%'

    last_record = db.session.query(model_class).filter(
        getattr(model_class, number_field).like(pattern)
    ).order_by(
        getattr(model_class, number_field).desc()
    ).first()

    if last_record:
        seq = _parse_sequence(getattr(last_record, number_field).split('-')[-1])
        if seq is not None:
            return f'{prefix}-{year}-{seq + 1:04d}'

    return f'{prefix}-{year}-0001'


def calculate_discount(amount, discount_percent):
    """Calculate discount amount from percentage"""
    amount = Decimal(str(amount))
    discount_percent = Decimal(str(discount_percent))
    return (amount * discount_percent / Decimal('100')).quantize(Decimal('0.01'))


def calculate_vat(amount, vat_rate):
    """Calculate VAT/Tax amount from rate"""
    amount = Decimal(str(amount))
    vat_rate = Decimal(str(vat_rate))
    return (amount * vat_rate / Decimal('100')).quantize(Decimal('0.01'))


def format_currency_display(amount, currency='AED', lang='ar'):
    if not amount:
        return '0.00'

    try:
        if isinstance(amount, (int, float)):
            amount = Decimal(str(amount))

        formatted = f'{amount:,.2f}'

        if lang == 'ar':
            symbols = {
                'AED': 'د.إ',
                'USD': '$',
                'EUR': '€',
                'GBP': '£',
                'SAR': 'ر.س',
            }
            return f'{formatted} {symbols.get(currency, currency)}'

        return f'{currency} {formatted}'

    except Exception:
        return str(amount)


def format_currency(amount, currency='AED', lang='ar'):
    """Alias for format_currency_display to maintain backward compatibility"""
    return format_currency_display(amount, currency, lang)


def timeago(date):
    """Calculate time ago string"""
    if not date:
        return ''

    try:
        now = datetime.now(timezone.utc)
        if date.tzinfo is None:
            # Assume naive datetime is UTC or handle accordingly
            # For simplicity, let's assume it's system local time, but comparing with UTC is tricky.
            # Let's try to make it aware or just use now() naive if date is naive.
            if date.year < 1970:  # Handle invalid dates
                return ''
            date = date.replace(tzinfo=timezone.utc)

        diff = now - date
        seconds = diff.total_seconds()

        if seconds < 60:
            return 'منذ لحظات'
        elif seconds < 3600:
            return f'منذ {int(seconds // 60)} دقيقة'
        elif seconds < 86400:
            return f'منذ {int(seconds // 3600)} ساعة'
        elif seconds < 604800:
            return f'منذ {int(seconds // 86400)} يوم'
        else:
            return date.strftime('%Y-%m-%d')

    except Exception:
        return str(date)


def _json_safe_changes(value):
    """تحويل حمولة التدقيق إلى قيم قابلة للتخزين في عمود JSON.

    الأرقام العشرية (Decimal) والتواريخ لا يمرّرها مُسلسل JSON كما هي، ولو
    فشلت عملية الكتابة لأُهملت السجلات الصامتة. التحويل هنا يمنع أن يسقط
    سجل التدقيق بسبب قيمة رقمية في الحمولة.
    """
    if isinstance(value, dict):
        return {str(k): _json_safe_changes(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_changes(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def create_audit_log(action, table_name=None, record_id=None, changes=None, commit=None):
    """تسجيل عملية في سجل التدقيق ضمن معاملة المستدعي (لا تلتزم بشكل مستقل).

    كان في الدالة عيبان:

    * ``except Exception: logger.error(...)`` — كان الفشل يُبلع فتسير العملية
      التجارية بلا سجل تدقيق (fail-open). الآن يُسجَّل الخطأ على مستوى ERROR
      ويُعاد رفعه فتُلغى العملية.
    * ``db.session.commit()`` — كان السجل يلتزم ما عدا في الجلسة، فيُثبّت
      عملاً تجارياً لم يُقصد تثبيته ويكسر ذرّية المعاملة.

    Args:
        commit: ``None`` (الافتراضي) = ارتباط تلقائي: إن كانت الجلسة تحمل
            عملاً معلّقاً آخر فالسجل جزء من معاملة المستدعي (الالتزام الخاص
            به)، وإلا فالسجل مستقل فيُلتزم فوراً حتى لا يضيع. ``True`` =
            التزام فوري صريح. ``False`` = لا يلتزم أبداً؛ المستدعي هو من
            يلتزم.
    """
    from models import AuditLog
    from flask_login import current_user

    session = db.session
    # هل تحمل الجلسة عملاً معلّقاً آخر؟ إن كان نعم فسجّل صف التدقيق ضمن
    # معاملة المستدعي (commit الخاصة به)، وإلا فالصف مستقل.
    pending_before = bool(session.new) or bool(session.dirty)

    try:
        log = AuditLog(
            user_id=current_user.id if (getattr(current_user, 'is_authenticated', False)) else None,
            action=action,
            table_name=table_name,
            record_id=record_id,
            changes=_json_safe_changes(changes),
            ip_address=request.remote_addr if request else None,
            user_agent=request.headers.get('User-Agent') if request else None,
        )
        session.add(log)
        session.flush()
        if commit is True:
            session.commit()
        elif commit is None and not pending_before:
            # استدعاء مستقل (لا معاملة تجارية مفتوحة): نلتزم حتى لا يضيع
            # السجل مع نهاية الطلب.
            session.commit()
        return log
    except Exception as e:
        current_app.logger.error(f'Failed to create audit log: {e}')
        # fail-closed: السجل جزء من العملية، فشلُه يُلغي العملية.
        raise


def instance_audit_dir():
    """مسار مجلد التدقيق الدائم داخل ``instance/``.

    سجل التدقيق داخل قاعدة البيانات لا ينجو من استعادة نسخة احتياطية
    (الاستعادة تعيد كتابة جدول ``audit_logs``)، لذلك تُكتب العمليات
    الحسّاسة (الاستعادة/الحذف/المسح) في ملف دائم داخل ``instance/``.
    """
    try:
        path = current_app.instance_path
        if path:
            return os.path.join(path, 'audit')
    except Exception:
        pass
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, 'instance', 'audit')


def append_audit_record(payload, directory=None, filename='audit_trail.jsonl'):
    """كتابة سجل تدقيق دائم في ملف JSONL داخل ``instance/audit``.

    Used for the acts that must survive a database restore: the restore
    itself rewrites ``audit_logs`` with the backup's contents, so the only
    durable proof that it happened is a file on disk.

    Returns the absolute path of the file that was written.
    """
    target_dir = directory or instance_audit_dir()
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, filename)

    record = {
        'recorded_at': datetime.now(timezone.utc).isoformat(),
    }
    if isinstance(payload, dict):
        record.update(payload)
    else:
        record['payload'] = payload

    try:
        user_id = None
        username = None
        try:
            from flask_login import current_user
            if getattr(current_user, 'is_authenticated', False):
                user_id = current_user.id
                username = getattr(current_user, 'username', None)
        except Exception:
            pass
        record.setdefault('user_id', user_id)
        record.setdefault('username', username)
        if request:
            record.setdefault('ip_address', request.remote_addr)
            record.setdefault('user_agent', request.headers.get('User-Agent'))
    except Exception:
        pass

    with open(path, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
    return path


def allowed_file(filename, allowed_extensions=None):
    if not filename:
        return False

    if allowed_extensions is None:
        config_extensions = current_app.config.get('ALLOWED_UPLOAD_EXTENSIONS', {})
        if 'all' in config_extensions:
            allowed_extensions = config_extensions['all']
        else:
            allowed_extensions = set()
            for ext_set in config_extensions.values():
                if isinstance(ext_set, set):
                    allowed_extensions.update(ext_set)

    if _is_double_extension_attack(filename):
        return False

    return '.' in filename and \
           '.' + filename.rsplit('.', 1)[1].lower() in allowed_extensions


#: App-level upload cap (see save_uploaded_file): the effective limit is the
#: stricter of this and Flask's MAX_CONTENT_LENGTH, so neither bound can be
#: silently exceeded by the other.
_APP_LEVEL_MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: Intermediate extensions that must never appear before the final extension
#: ('invoice.php.jpg' bypasses naive last-extension checks).
_DANGEROUS_INTERMEDIATE_EXTS = frozenset({
    '.php', '.phtml', '.phar', '.exe', '.dll', '.so', '.elf', '.sh',
    '.bash', '.bat', '.cmd', '.com', '.msi', '.ps1', '.vbs', '.vbe',
    '.js', '.jsp', '.asp', '.aspx', '.py', '.rb', '.pl', '.cgi',
    '.htm', '.html', '.xhtml', '.svg', '.swf', '.jar', '.war',
})

#: Byte markers (lowercased) signalling an executable/script polyglot hiding
#: behind an innocent extension. Checked against the file header alongside
#: the MZ/ELF magic-number guard.
_POLYGLOT_MARKERS = (b'<?php', b'<?=', b'<%', b'<script')


def _is_double_extension_attack(filename):
    """True when a dangerous extension hides before the final extension."""
    parts = str(filename or '').lower().split('.')
    if len(parts) < 3:
        return False
    return any('.' + part in _DANGEROUS_INTERMEDIATE_EXTS for part in parts[1:-1])


def _is_polyglot_header(file_header):
    """True when the header mixes executable/script content into the file."""
    if not file_header:
        return False
    if file_header.startswith(b'MZ') or file_header.startswith(b'\x7fELF'):
        return True
    lowered = bytes(file_header).lower()
    if lowered.lstrip().startswith(b'#!'):
        return True
    return any(marker in lowered for marker in _POLYGLOT_MARKERS)


def save_uploaded_file(file, upload_folder='uploads', allowed_extensions=None):
    """حفظ ملف مرفوع مع فحوصات أمان"""
    if not file or not file.filename:
        return None

    if not allowed_file(file.filename, allowed_extensions):
        raise ValueError('File type not allowed')

    if _is_double_extension_attack(file.filename):
        raise ValueError('File type not allowed (double extension)')

    # Effective cap is the stricter of Flask's MAX_CONTENT_LENGTH (request
    # layer, default 16MB) and the 5MB app-level upload policy, so lowering
    # either bound is always honored and neither can silently exceed the other.
    # NOTE: must stay usable without an app context (plain unit tests), hence
    # the broad fallback to the app-level default.
    try:
        configured_max = int(current_app.config.get('MAX_CONTENT_LENGTH'))
    except Exception:
        configured_max = _APP_LEVEL_MAX_UPLOAD_BYTES
    max_file_size = min(configured_max, _APP_LEVEL_MAX_UPLOAD_BYTES)
    file.seek(0, os.SEEK_END)
    file_length = file.tell()
    file.seek(0)

    if file_length > max_file_size:
        raise ValueError(f'File size exceeds limit ({max_file_size // (1024 * 1024)}MB)')

    file_header = file.read(512)
    file.seek(0)

    if _is_polyglot_header(file_header):
        raise ValueError('Executable files are not allowed')

    filename = secure_filename(file.filename)
    name, ext = os.path.splitext(filename)
    unique_filename = f'{name}_{uuid.uuid4().hex[:8]}{ext}'

    full_upload_folder = os.path.join(current_app.static_folder, upload_folder)
    os.makedirs(full_upload_folder, exist_ok=True)

    filepath = os.path.join(full_upload_folder, unique_filename)
    file.save(filepath)

    current_app.logger.info(f'File uploaded: {unique_filename} ({file_length} bytes)')

    return os.path.join(upload_folder, unique_filename).replace('\\', '/')


def convert_currency(amount, from_currency, to_currency='AED'):
    from services.currency_service import CurrencyService

    if from_currency == to_currency:
        return amount

    rate = CurrencyService.get_exchange_rate(from_currency, to_currency)
    return amount * Decimal(str(rate))


def generate_sku():
    return f'SKU-{uuid.uuid4().hex[:8].upper()}'


def generate_barcode():
    return f'{datetime.now().strftime("%Y%m%d")}{uuid.uuid4().hex[:6].upper()}'
