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


def test_platform_logo_replaced_with_new_azad_erp_graphic():
    from PIL import Image
    old = Image.open(os.path.join(ROOT, 'static', 'img', 'azad_logo.png'))
    new = Image.open(os.path.join(ROOT, 'logos', 'Azad ERP Gradient Logo.png'))
    assert old.size == new.size, (old.size, new.size)
    assert old.size == (1199, 1312)


def test_login_shows_both_platform_logos():
    html = open(os.path.join(ROOT, 'templates', 'auth', 'login.html'),
                encoding='utf-8').read()
    css = open(os.path.join(ROOT, 'static', 'css', 'auth.css'),
               encoding='utf-8').read()
    assert 'platform-logo-top' in html
    assert 'platform-logo-bottom' in html
    assert 'img/azad_logo.png' in html
    assert 'img/azad_login_graphic.png' in html
    assert '.login-logo img.platform-logo-top' in css
    assert '.login-card-footer-platform img.platform-logo-bottom' in css
    # the full graphic (including the bottom credit lines) must never be cropped
    assert 'object-fit: contain' in css
    assert 'object-fit: cover' not in css
    graphic = os.path.join(ROOT, 'static', 'img', 'azad_login_graphic.png')
    assert os.path.exists(graphic)
    # keep the footer graphic lightweight for the login page
    assert os.path.getsize(graphic) < 800 * 1024
    # tenant logo must remain untouched
    tenant = os.path.join(ROOT, 'static', 'img', 'tenants', 'samarkand_logo.png')
    assert os.path.getsize(tenant) > 0

