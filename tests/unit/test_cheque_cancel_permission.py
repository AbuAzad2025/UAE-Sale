"""Manager may cancel a cheque, and the action must be fully audited."""
import os
os.environ.setdefault('PYTHONIOENCODING','utf-8')

from app import create_app


def test_cancel_uses_manage_payments_permission():
    src = open('routes/cheques.py', encoding='utf-8').read()
    block = src[src.index('def cancel(id):') - 250:src.index('def cancel(id):') + 60]
    assert '@permission_required("manage_payments")' in block
    assert '@admin_required' not in block


def test_cancel_audit_records_reason_and_cheque():
    src = open('routes/cheques.py', encoding='utf-8').read()
    block = src[src.index('def cancel(id):'):src.index('def delete(id):')]
    assert 'create_audit_log(' in block
    assert 'cheque_bank_number' in block
    assert 'reason' in block
