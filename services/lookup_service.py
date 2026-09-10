"""LookupService — merged system constants (code base + owner overrides).

Base lists live in ``utils.constants`` and are registered in
``LOOKUP_GROUPS`` with capability flags.  Owner customizations are stored
in ``SystemSettings.custom_settings`` under the ``lookup_overrides`` key::

    {group: {'custom': [[code, ar, en], ...],
             'labels': {code: {'ar': ..., 'en': ...}},
             'disabled': [code, ...]}}

No schema changes are required.  Locked groups (codes drive application
logic) accept label edits only — add/disable are refused server-side.
"""
from utils import constants as _constants


OVERRIDES_KEY = 'lookup_overrides'


def _registry():
    return _constants.LOOKUP_GROUPS


def groups():
    """Registered lookup groups with capability flags."""
    return _registry()


def _base_list(group):
    reg = _registry()
    if group not in reg:
        raise ValueError(f'مجموعة ثوابت غير معروفة: {group}')
    source = reg[group]['source']
    return list(getattr(_constants, source))


def _load_overrides():
    from models import SystemSettings
    settings = SystemSettings.get_current()
    data = settings.get_custom_setting(OVERRIDES_KEY, {}) or {}
    return settings, (data if isinstance(data, dict) else {})


def _group_override(data, group):
    ov = data.get(group) or {}
    if not isinstance(ov, dict):
        ov = {}
    custom = ov.get('custom') or []
    labels = ov.get('labels') or {}
    disabled = ov.get('disabled') or []
    if not isinstance(custom, list):
        custom = []
    if not isinstance(labels, dict):
        labels = {}
    if not isinstance(disabled, list):
        disabled = []
    return custom, labels, set(disabled)


def get_lookup(group):
    """Merged [(code, {'ar', 'en', ...}), ...] for *group*."""
    base = _base_list(group)
    _, data = _load_overrides()
    custom, labels, disabled = _group_override(data, group)
    return _merge(base, custom, labels, disabled)


def get_all():
    """Merged lookups for every group with a SINGLE settings read."""
    _, data = _load_overrides()
    out = {}
    for group in _registry():
        base = _base_list(group)
        custom, labels, disabled = _group_override(data, group)
        out[group] = _merge(base, custom, labels, disabled)
    return out


def _merge(base, custom, labels, disabled):
    merged = []
    for code, meta in base:
        if code in disabled:
            continue
        meta = dict(meta)
        if code in labels and isinstance(labels[code], dict):
            if labels[code].get('ar'):
                meta['ar'] = labels[code]['ar']
            if labels[code].get('en'):
                meta['en'] = labels[code]['en']
        merged.append((code, meta))
    for item in custom:
        try:
            code, ar, en = item
        except (TypeError, ValueError):
            continue
        if code in disabled:
            continue
        merged.append((code, {'ar': ar, 'en': en or code}))
    return merged


def get_codes(group):
    return [code for code, _ in get_lookup(group)]


def group_detail(group):
    """Rows for the owner UI, INCLUDING disabled codes.

    Each row: {'code', 'ar', 'en', 'custom', 'disabled', 'locked'}.
    """
    if group not in _registry():
        raise ValueError(f'مجموعة ثوابت غير معروفة: {group}')
    reg = _registry()[group]
    base = _base_list(group)
    _, data = _load_overrides()
    custom, labels, disabled = _group_override(data, group)
    rows = []
    for code, meta in base:
        meta = dict(meta)
        if code in labels and isinstance(labels[code], dict):
            if labels[code].get('ar'):
                meta['ar'] = labels[code]['ar']
            if labels[code].get('en'):
                meta['en'] = labels[code]['en']
        rows.append({'code': code, 'ar': meta.get('ar') or code,
                     'en': meta.get('en') or code,
                     'custom': False, 'disabled': code in disabled,
                     'locked': bool(reg.get('locked_codes'))})
    for item in custom:
        try:
            code, ar, en = item
        except (TypeError, ValueError):
            continue
        rows.append({'code': code, 'ar': ar, 'en': en or code,
                     'custom': True, 'disabled': code in disabled,
                     'locked': False})
    return rows


def get_label(group, code, lang='ar'):
    for c, meta in get_lookup(group):
        if c == code:
            return meta.get(lang) or meta.get('ar') or code
    return code


def _validate_new_code(group, code):
    reg = _registry()[group]
    if reg.get('locked_codes'):
        raise ValueError('هذه المجموعة مقفلة منطقياً — لا يمكن إضافة أكواد جديدة.')
    if not reg.get('allow_add'):
        raise ValueError('الإضافة غير مسموحة لهذه المجموعة.')
    code = (code or '').strip()
    if not (1 <= len(code) <= 60):
        raise ValueError('الكود مطلوب (1-60 حرفاً).')
    for bad in '<>"\'\\':
        if bad in code:
            raise ValueError('الكود يحتوي محارف غير مسموحة.')
    existing = {c for c, _ in _base_list(group)}
    _, data = _load_overrides()
    custom, _, _ = _group_override(data, group)
    existing |= {item[0] for item in custom
                 if isinstance(item, (list, tuple)) and len(item) >= 1}
    if code in existing:
        raise ValueError(f'الكود "{code}" موجود بالفعل.')
    return code


def add_custom(group, code, ar, en=None):
    """Append an owner-defined value to an unlocked group."""
    if group not in _registry():
        raise ValueError(f'مجموعة ثوابت غير معروفة: {group}')
    code = _validate_new_code(group, code)
    ar = (ar or '').strip()
    en = (en or '').strip() or code
    if not ar:
        raise ValueError('التسمية العربية مطلوبة.')
    if len(ar) > 200 or len(en) > 200:
        raise ValueError('التسمية طويلة (الحد 200 حرف).')
    settings, data = _load_overrides()
    ov = data.get(group) or {}
    if not isinstance(ov, dict):
        ov = {}
    custom = ov.get('custom') or []
    if not isinstance(custom, list):
        custom = []
    custom.append([code, ar, en])
    ov['custom'] = custom
    data[group] = ov
    settings.set_custom_setting(OVERRIDES_KEY, data)
    from extensions import db
    db.session.commit()
    return code


def set_label(group, code, ar, en=None):
    """Override display labels (allowed for every group, incl. locked)."""
    if group not in _registry():
        raise ValueError(f'مجموعة ثوابت غير معروفة: {group}')
    ar = (ar or '').strip()
    en = (en or '').strip()
    if not ar:
        raise ValueError('التسمية العربية مطلوبة.')
    if len(ar) > 200 or len(en) > 200:
        raise ValueError('التسمية طويلة (الحد 200 حرف).')
    known = {c for c, _ in _base_list(group)}
    settings, data = _load_overrides()
    custom, _, _ = _group_override(data, group)
    known |= {item[0] for item in custom
              if isinstance(item, (list, tuple)) and len(item) >= 1}
    if code not in known:
        raise ValueError(f'الكود "{code}" غير موجود في هذه المجموعة.')
    ov = data.get(group) or {}
    if not isinstance(ov, dict):
        ov = {}
    labels = ov.get('labels') or {}
    if not isinstance(labels, dict):
        labels = {}
    labels[code] = {'ar': ar, 'en': en or ar}
    ov['labels'] = labels
    data[group] = ov
    settings.set_custom_setting(OVERRIDES_KEY, data)
    from extensions import db
    db.session.commit()


def set_disabled(group, code, disabled):
    """Hide/restore a code in dropdowns (unlocked groups only)."""
    if group not in _registry():
        raise ValueError(f'مجموعة ثوابت غير معروفة: {group}')
    reg = _registry()[group]
    if reg.get('locked_codes'):
        raise ValueError('هذه المجموعة مقفلة منطقياً — لا يمكن إخفاء أكوادها.')
    if not reg.get('allow_disable'):
        raise ValueError('الإخفاء غير مسموح لهذه المجموعة.')
    base_codes = {c for c, _ in _base_list(group)}
    if code not in base_codes:
        raise ValueError('الإخفاء متاح لأكواد النظام فقط (وليس المضافة).')
    settings, data = _load_overrides()
    ov = data.get(group) or {}
    if not isinstance(ov, dict):
        ov = {}
    disabled_list = ov.get('disabled') or []
    if not isinstance(disabled_list, list):
        disabled_list = []
    if disabled and code not in disabled_list:
        disabled_list.append(code)
    if not disabled and code in disabled_list:
        disabled_list.remove(code)
    ov['disabled'] = disabled_list
    data[group] = ov
    settings.set_custom_setting(OVERRIDES_KEY, data)
    from extensions import db
    db.session.commit()
