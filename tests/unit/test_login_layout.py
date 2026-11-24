"""Professional ERP login page — structure, branding and RTL/LTR safety."""
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_login_structure_preserved():
    html = _read('templates/auth/login.html')
    # authentication contract untouched
    assert 'method="POST"' in html
    assert "url_for('auth.login')" in html
    for name in ('csrf_token', 'username', 'password', 'remember'):
        assert 'name="' + name + '"' in html
    assert 'id="togglePassword"' in html
    assert 'id="langDropdown"' in html
    assert "url_for('language.set_language', lang='ar')" in html
    assert "url_for('language.set_language', lang='en')" in html
    assert 'get_flashed_messages' in html


def test_clean_transparent_erp_logo():
    p = os.path.join(ROOT, 'static', 'img', 'azad_erp_logo.png')
    im = Image.open(p)
    assert im.mode == 'RGBA'
    a = im.getchannel('A')
    assert a.getextrema()[0] == 0            # genuinely transparent background
    assert im.size == (446, 376)             # original aspect ratio, not squashed
    # no large white container around it in the header
    assert 'object-fit: contain' in _read('static/css/auth.css')


def test_compact_header_and_real_html_footer():
    html = _read('templates/auth/login.html')
    css = _read('static/css/auth.css')
    assert 'login-logo-img' in html
    assert 'login-product' in html and 'login-tagline' in html
    assert 'login-location' in html
    assert 'login-footer' in html
    # footer is real HTML text, not a promotional raster banner
    assert 'azad_login_graphic' not in html
    assert 'login-footer-company' in html
    assert 'login-footer-dev' in html
    assert 'login-footer-wa' in html
    assert 'COMPANY_WHATSAPP' in html
    # compact targets
    assert 'height: 88px' in css
    assert 'padding: 16px 20px 14px' in css
    assert 'padding: 10px 16px 12px' in css


def test_whatsapp_number_format():
    html = _read('templates/auth/login.html')
    assert '+{{ config.COMPANY_WHATSAPP }}' in html
    assert 'https://wa.me/{{ config.COMPANY_WHATSAPP }}' in html


def test_language_aware_fonts():
    css = _read('static/css/auth.css')
    assert '--font-ar' in css and '--font-en' in css
    assert "html[lang='ar']" in css
    assert "'Tajawal'" in css
    assert "'Segoe UI'" in css
    assert 'tabular-nums' in css


def test_checkbox_gap_and_rtl_ltr_safe():
    css = _read('static/css/auth.css')
    assert '.icheck-primary' in css
    assert 'gap: .5rem' in css
    assert "position: static !important" in css
    assert 'label::before,\n.icheck-primary label::after { display: none' in css
    # language direction comes from <html dir>, never hard-coded globally
    assert 'direction: rtl' not in css


def test_responsive_no_fixed_card_height():
    css = _read('static/css/auth.css')
    assert 'box-sizing: border-box' in css
    assert 'min-height: 100dvh' in css
    assert 'max-width: 440px' in css
    assert "@media (max-width: 480px)" in css
    assert "@media (max-height: 720px)" in css
