"""User guide: bilingual, accurate routes, no sensitive/internal info."""
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(name):
    with open(os.path.join(ROOT, 'templates', 'public', name),
              encoding='utf-8') as f:
        return f.read()


def test_guide_has_no_sensitive_internal_details():
    en = _read('user_guide_en.html')
    ar = _read('user_guide.html')
    for secret in ('Master Key', 'Owner Panel', 'id="owner"', 'backups', 'tenants management'):
        assert secret not in en, secret
    for secret in ('Master Key', 'Owner Panel', 'قاعدة البيانات', 'النسخ الاحتياطي'):
        assert secret not in ar, secret
    # no real credentials or tenant phone numbers leaked into public docs
    for leak in ('Test-', 'samarkand_manager', '0562150193'):
        assert leak not in en and leak not in ar


def test_both_guides_have_matching_sections():
    en = _read('user_guide_en.html')
    ar = _read('user_guide.html')
    for section in ('notifications', 'vault', 'support'):
        assert f'id="{section}"' in en
        assert f'id="{section}"' in ar


def test_arabic_guide_uses_real_routes():
    ar = _read('user_guide.html')
    assert '/hr/leave' in ar
    assert '/hr/leave-types' in ar
    assert '/ai/assistant' in ar
    assert '/hr/leaves' not in ar
    assert '/hr/attendance' not in ar
