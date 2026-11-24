"""Sales invoice print templates: RTL-safe logical CSS and language-aware words."""
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_templates_use_logical_properties():
    for name in ('modern', 'classic', 'gulf', 'minimal', 'simple'):
        src = _read(f'templates/invoices/{name}.html')
        assert 'border-left:' not in src, name
        assert 'border-right:' not in src, name
        assert 'margin-left:' not in src, name
        assert 'margin-right:' not in src, name
        assert 'text-align: left' not in src, name
        assert 'text-align: right' not in src, name
        # CSS uses logical border-inline-start where a coloured accent border exists
        assert 'border-inline-start' in src or 'border-inline-end' in src or src.count('border:') > 0


def test_amount_words_follow_language():
    for name in ('modern', 'classic', 'gulf', 'minimal', 'simple'):
        src = _read(f'templates/invoices/{name}.html')
        assert "amount_words_ar if current_language == 'ar' else amount_words_en" in src, name


def test_templates_have_inner_padding():
    for name in ('modern', 'classic', 'gulf', 'minimal', 'simple'):
        src = _read(f'templates/invoices/{name}.html')
        assert 'padding:' in src, name


def test_tax_label_localised():
    src = _read('templates/invoices/_tax_label.html')
    for key in ('Zero-rated (0%)', 'Tax Exempt', 'Tax Included in Total', 'Additional Tax'):
        assert f't("{key}")' in src
