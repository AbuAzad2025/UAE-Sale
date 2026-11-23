"""Regression tests for the expenses audit fixes."""
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_expense_category_requires_valid_gl_account():
    src = _read('routes/expenses.py')
    assert 'GLAccount.query.filter_by(code=gl_code).first()' in src
    assert 'غير صالح أو حساب رئيسي' in src
    # empty code is allowed (expense_gl falls back to 6990)
    assert 'if gl_code:' in src


def test_expense_create_reports_real_value_error():
    src = _read('routes/expenses.py')
    # a ValueError from GL posting must surface, not become a generic message
    assert 'except ValueError as e:' in src
    assert 'flash(f"❌ {e}", "danger")' in src


def test_archived_expense_reads_category_key_and_translates():
    src = _read('routes/expenses.py')
    assert 'data.get("category_name") or data.get("category")' in src
    assert 'get_current_language()' in src
    assert 'cat.name_ar' in src


def test_expense_print_single_language_amount_words():
    src = _read('templates/expenses/print.html')
    assert "amount_words_ar if current_language == 'ar' else amount_words_en" in src
    # both words must not be printed together
    assert '{% if amount_words_en %}' not in src
    assert 'class="invoice-header"' in src
    assert 'class="azad_invoice_footer"' in src


def test_expense_create_has_arabic_description_field():
    src = _read('templates/expenses/create.html')
    assert 'name="description_ar"' in src
    assert 'Arabic Description' in src


def test_expense_archive_restore_report_failures():
    src = _read('routes/expenses.py')
    assert 'current_app.logger.exception("expense archive failed")' in src
    assert 'current_app.logger.exception("expense restore failed")' in src
    assert '❌ تعذرت أرشفة المصروف' in src
    assert '❌ تعذرت استعادة المصروف' in src


def test_expense_views_prefer_arabic_category_name():
    for name in ('index.html', 'view.html', 'print.html'):
        src = _read(f'templates/expenses/{name}')
        assert 'category.name_ar' in src, name
