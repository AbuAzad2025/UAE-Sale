"""Root fix: RTL checkbox labels must not stick to the checkbox."""
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_rtl_checkbox_spacing_is_global():
    src = open(os.path.join(ROOT, 'static', 'css', 'enhancements.css'),
               encoding='utf-8').read()
    assert 'html[dir="rtl"] .form-check' in src
    assert 'padding-inline-start' in src
    assert 'margin-inline-start: -1.4rem' in src
    assert 'html[dir="rtl"] .form-check-label' in src
    assert 'padding-inline-start: 0.5rem' in src
    # loaded on every page through the shared base template
    base = open(os.path.join(ROOT, 'templates', 'base.html'),
                encoding='utf-8').read()
    assert "static', filename='css/enhancements.css'" in base
