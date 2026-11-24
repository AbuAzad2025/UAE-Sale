"""RTL-safe login page layout."""
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_login_remember_checkbox_is_rtl_safe():
    css = open(os.path.join(ROOT, 'static', 'css', 'auth.css'),
               encoding='utf-8').read()
    assert 'html[dir="rtl"] .icheck-primary' in css
    assert 'gap: 0.5rem' in css
    assert 'html[dir="rtl"] .icheck-primary > input[type="checkbox"]' in css

    html = open(os.path.join(ROOT, 'templates', 'auth', 'login.html'),
                encoding='utf-8').read()
    assert 'css/auth.css' in html
