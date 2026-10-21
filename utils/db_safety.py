"""
Database & Path Safety Utilities
CRITICAL: Validates table names and file paths to prevent SQL injection and path traversal.
"""

import os
from sqlalchemy import inspect as sa_inspect


#: جداول ممنوع مسحها أو إتلافها من أي مسار في التطبيق.
#:
#: القائمة تضم (١) جداول الهوية والصلاحيات، (٢) كل أثر التدقيق
#: (audit trail)، (٣) دفتر الأستاذ العام، (٤) المستندات المالية.
#: مسح أيٍّ منها يعني محو الدليل أو المحاسبة نفسها، لذلك يُرفض المسح
#: من أي مسار — لا من مسار لوحة المالك وحده.
PROTECTED_TABLES = frozenset({
    # identity & access
    'users', 'roles', 'permissions', 'tenants', 'role_permissions',
    # audit trail
    'audit_logs', 'journal_entry_audits', 'error_logs', 'login_history',
    'security_alerts',
    # general ledger
    'gl_journal_entries', 'gl_journal_lines', 'gl_accounts',
    # financial documents
    'sales', 'sale_lines', 'payments', 'receipts', 'purchases',
    'purchase_lines', 'product_returns', 'product_return_lines',
    'expenses',
    # stock & master data
    'products', 'warehouses', 'stock_movements', 'customers', 'suppliers',
})


def is_protected_table(table_name):
    """هل الجدول ممنوع المسح؟ (قائمة الحظر المركزية)"""
    if not table_name or not isinstance(table_name, str):
        return False
    return table_name.strip().lower() in PROTECTED_TABLES


def assert_table_not_protected(table_name):
    """ترفض مسح جدول محمي.

    Raises:
        ValueError: إذا كان الجدول ضمن قائمة الحظر.
    """
    if is_protected_table(table_name):
        raise ValueError(
            f'Table is protected and cannot be truncated: {table_name}')
    return table_name


def get_allowed_table_names():
    """Get a set of all valid table names from the database schema.

    Returns a cached set to avoid repeated introspection.
    """
    from extensions import db
    try:
        inspector = sa_inspect(db.engine)
        return set(inspector.get_table_names())
    except Exception:
        return set()


def validate_table_name(table_name, allowed=None):
    """Validate that a table name is a real database table.

    Prevents SQL injection via f-string table names.

    Args:
        table_name: The table name to validate (from user input)
        allowed: Optional pre-fetched set of allowed names

    Returns:
        The validated table name if valid

    Raises:
        ValueError: If the table name is invalid or not in the database
    """
    if not table_name or not isinstance(table_name, str):
        raise ValueError('Invalid table name')

    # Strict regex: only alphanumeric and underscores
    import re
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
        raise ValueError(f'Invalid table name format: {table_name}')

    # Reject SQL keywords that could be abused
    dangerous = {
        'pg_', 'information_schema', 'pg_catalog', 'pg_class',
        'pg_tables', 'pg_proc', 'pg_attribute', 'pg_type',
        'pg_namespace', 'pg_roles', 'pg_shdepend', 'pg_authid',
    }
    for prefix in dangerous:
        if table_name.lower().startswith(prefix):
            raise ValueError(f'Table name not allowed: {table_name}')

    if allowed is None:
        allowed = get_allowed_table_names()

    if table_name not in allowed:
        raise ValueError(f'Table does not exist: {table_name}')

    return table_name


def validate_backup_filename(filename, backup_dir):
    """Validate that a backup filename is safe and within the backup directory.

    Prevents path traversal attacks (e.g., '../../etc/passwd').

    Args:
        filename: The filename from user input
        backup_dir: The expected backup directory path

    Returns:
        The validated absolute path if valid

    Raises:
        ValueError: If the filename is unsafe
    """
    if not filename or not isinstance(filename, str):
        raise ValueError('Invalid filename')

    # Reject null bytes
    if '\x00' in filename:
        raise ValueError('Invalid filename: contains null bytes')

    # Use werkzeug's secure_filename to strip dangerous characters
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(filename)

    if not safe_name or safe_name != filename:
        raise ValueError(f'Invalid filename: {filename}')

    # Build the full path and resolve it
    full_path = os.path.normpath(os.path.join(backup_dir, filename))
    abs_backup_dir = os.path.realpath(backup_dir)
    abs_full_path = os.path.realpath(full_path)

    # Ensure the resolved path is within the backup directory
    if not abs_full_path.startswith(abs_backup_dir + os.sep) and abs_full_path != abs_backup_dir:
        raise ValueError(f'Path traversal detected: {filename}')

    return abs_full_path
