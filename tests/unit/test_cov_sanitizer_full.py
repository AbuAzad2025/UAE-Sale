"""Full unit coverage for utils/sanitizer.py — real inputs, real outputs."""
from utils.sanitizer import InputSanitizer, sanitize_form_data


class TestSanitizeHtml:
    def test_empty_returns_empty(self):
        assert InputSanitizer.sanitize_html('') == ''
        assert InputSanitizer.sanitize_html(None) == ''

    def test_plain_text_escaped(self):
        out = InputSanitizer.sanitize_html('<script>alert(1)</script>')
        assert '<script>' not in out
        assert 'alert(1)' in out

    def test_allow_tags_keeps_safe_strips_script(self):
        out = InputSanitizer.sanitize_html('<p>hi <b>x</b></p><script>bad()</script>', allow_tags=True)
        assert '<p>' in out and '<b>' in out
        assert '<script>' not in out
        assert 'bad()' in out

    def test_allow_tags_strips_disallowed_attrs(self):
        out = InputSanitizer.sanitize_html('<p onclick="evil()">t</p>', allow_tags=True)
        assert 'onclick' not in out


class TestSanitizeText:
    def test_empty(self):
        assert InputSanitizer.sanitize_text('') == ''
        assert InputSanitizer.sanitize_text(None) == ''

    def test_strips_tags_and_escapes(self):
        out = InputSanitizer.sanitize_text('  <b>hello</b> & bye  ')
        assert '<b>' not in out
        assert 'hello' in out

    def test_max_length_truncates(self):
        assert InputSanitizer.sanitize_text('abcdef', max_length=3) == 'abc'

    def test_no_truncation_when_short(self):
        assert InputSanitizer.sanitize_text('ab', max_length=10) == 'ab'

    def test_non_string_input(self):
        assert InputSanitizer.sanitize_text(12345) == '12345'


class TestSanitizeEmail:
    def test_empty_returns_none(self):
        assert InputSanitizer.sanitize_email('') is None
        assert InputSanitizer.sanitize_email(None) is None

    def test_normalizes_case_and_spaces(self):
        assert InputSanitizer.sanitize_email('  User@Example.COM ') == 'user@example.com'

    def test_invalid_returns_none(self):
        assert InputSanitizer.sanitize_email('not-an-email') is None
        assert InputSanitizer.sanitize_email('a@b') is None


class TestSanitizePhone:
    def test_empty_returns_none(self):
        assert InputSanitizer.sanitize_phone('') is None
        assert InputSanitizer.sanitize_phone(None) is None

    def test_strips_letters_keeps_format(self):
        assert InputSanitizer.sanitize_phone('call +1 (555) 123-4567 ext.9') == '+1 (555) 123-4567 9'


class TestSanitizeNumber:
    def test_empty_returns_none(self):
        assert InputSanitizer.sanitize_number(None) is None
        assert InputSanitizer.sanitize_number('') is None

    def test_float_and_int_paths(self):
        assert InputSanitizer.sanitize_number('12.5') == 12.5
        assert InputSanitizer.sanitize_number('12', allow_decimal=False) == 12
        assert InputSanitizer.sanitize_number('12.5', allow_decimal=False) is None
        assert InputSanitizer.sanitize_number(7) == 7.0

    def test_negative_blocked(self):
        assert InputSanitizer.sanitize_number('-3', allow_negative=False) is None
        assert InputSanitizer.sanitize_number('-3') == -3.0

    def test_garbage_returns_none(self):
        assert InputSanitizer.sanitize_number('abc') is None
        assert InputSanitizer.sanitize_number(object()) is None


class TestSanitizeSqlInput:
    def test_empty(self):
        assert InputSanitizer.sanitize_sql_input('') == ''
        assert InputSanitizer.sanitize_sql_input(None) == ''

    def test_strips_dangerous_tokens(self):
        out = InputSanitizer.sanitize_sql_input("a'; DROP TABLE x; -- /* xp_ exec")
        assert ';' not in out
        assert '--' not in out
        assert '/*' not in out
        assert 'xp_' not in out
        assert 'exec' not in out
        assert 'DROP TABLE' in out

    def test_clean_text_untouched(self):
        assert InputSanitizer.sanitize_sql_input('customer name 42') == 'customer name 42'


class TestSanitizeFormData:
    def test_all_rule_types(self):
        data = {
            'email': ' A@B.com ',
            'phone': 'abc+123',
            'qty': '4',
            'bio': '<script>x</script><p>ok</p>',
            'name': '  <i>Ali</i>  ',
        }
        rules = {
            'email': {'type': 'email'},
            'phone': {'type': 'phone'},
            'qty': {'type': 'number'},
            'bio': {'type': 'html'},
            'name': {'max_length': 3},
        }
        out = sanitize_form_data(data, rules)
        assert out['email'] == 'a@b.com'
        assert out['phone'] == '+123'
        assert out['qty'] == 4.0
        assert '<script>' not in out['bio'] and '<p>' in out['bio']
        assert out['name'] == 'Ali'

    def test_defaults_and_empty_rules(self):
        out = sanitize_form_data({'a': '<b>1</b>'})
        assert out == {'a': '1'}
        assert sanitize_form_data({}) == {}
