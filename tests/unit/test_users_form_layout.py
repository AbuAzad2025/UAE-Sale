"""RTL-safe layout for the user create/edit forms."""
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_user_form_uses_logical_properties():
    src = _read('templates/users/create.html')
    assert 'inset-inline-start: -10px' in src
    assert 'inset-inline-end: 10px' in src
    assert 'border-inline-start: 3px solid #e74c3c' in src
    # required marker must not span the whole column into other rows
    assert 'height: 48px' in src
    assert 'top: 32px' in src
    assert 'bottom: 0;' not in src


def test_select2_matches_form_control_height():
    src = _read('static/css/select2-enhanced.css')
    assert '.select2-container--bootstrap4 .select2-selection--single' in src
    assert 'height: 48px !important' in src
