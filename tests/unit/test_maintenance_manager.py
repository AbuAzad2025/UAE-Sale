"""Maintenance has two operational roles; the manager can perform all of them."""
import os
os.environ.setdefault('PYTHONIOENCODING','utf-8')


def test_maintenance_roles_are_only_reception_and_engineer():
    src = open('utils/system_init.py', encoding='utf-8').read()
    block = src[src.index('"maintenance_reception": ('):]
    # no extra maintenance role definitions remain
    for extra in ('"maintenance_cashier": (', '"maintenance_closer": (',
                  '"maintenance_discount": (', '"maintenance_settings": ('):
        assert extra not in block, extra


def test_both_maintenance_roles_and_manager_have_full_purpose():
    src = open('utils/system_init.py', encoding='utf-8').read()
    required = {
        'maintenance_view', 'maintenance_receive', 'maintenance_work',
        'maintenance_cashier', 'maintenance_close', 'maintenance_discount',
        'maintenance_settings', 'maintenance_purchase',
    }
    # reception block and engineer block each carry the full set
    for start, end in [('"maintenance_reception": (','"maintenance_engineer": ('),
                       ('"maintenance_engineer": (','}')]:
        block = src[src.index(start):src.index(end, src.index(start))]
        for code in required:
            assert f'"{code}"' in block, (start, code)
    # manager still holds every maintenance permission
    i = src.index('"manager": (')
    manager = src[i:src.index('"seller": (', i)]
    for code in required:
        assert f'"{code}"' in manager, code
