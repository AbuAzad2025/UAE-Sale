"""Maintenance print documents use the same unified print shell as sales."""
import os
import re
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_maintenance_print_templates_extend_unified_print_shell():
    for name in ('print_invoice.html', 'print_receipt.html', 'print_intake.html'):
        src = _read(f'templates/maintenance/{name}')
        assert src.startswith('{% extends \'base_print.html\' %}'), name
        # tenant brand header + WhatsApp QR come from the shared shell
        assert 'document_content' in src, name
        # no leftover inline app-shell print styles
        assert '{% extends \'base.html\' %}' not in src, name
        assert 'window.print();' not in src, name  # toolbar handles printing


def test_maintenance_print_routes_pass_tenant_branding_context():
    src = _read('routes/maintenance.py')
    assert '_print_context' in src
    assert 'with_tenant_header' in src
    assert 'document_tenant' in src
    for doc_type in ('maintenance_invoice', 'maintenance_receipt', 'maintenance_intake'):
        assert f'"{doc_type}"' in src, doc_type


def test_maintenance_print_templates_have_no_raw_english_labels():
    for name in ('print_invoice.html', 'print_receipt.html', 'print_intake.html'):
        src = _read(f'templates/maintenance/{name}')
        # labels must go through t(); no hard-coded English UI words in source
        for word in ('>Problem<', '>Warranty Status<', '>Order Status<',
                     '>Maintenance<', '>Collection Details<'):
            assert word not in src, (name, word)
