"""Unit tests for utils/password_validator.py — policy, scoring, labels, helper."""
import pytest

from utils.password_validator import (
    PasswordValidator,
    validate_password_with_helpful_message,
)

STRONG = 'K7#mQ9!vX2pL'  # 12 chars, upper+lower+digit+special, no sequences


class TestValidate:
    def test_empty_rejected(self):
        ok, errors = PasswordValidator.validate('')
        assert ok is False and errors

    def test_none_rejected(self):
        ok, _ = PasswordValidator.validate(None)
        assert ok is False

    def test_too_short(self):
        ok, errors = PasswordValidator.validate('Aa1!bc')
        assert ok is False
        assert any('10' in e for e in errors)

    @pytest.mark.parametrize('pwd,missing', [
        ('abcdefgh1!', 'كبير'),
        ('ABCDEFGH1!', 'صغير'),
        ('Abcdefgh!!', 'رقم'),
        ('Abcdefgh12', 'رمز'),
    ])
    def test_missing_character_class(self, pwd, missing):
        ok, errors = PasswordValidator.validate(pwd)
        assert ok is False
        assert any(missing in e for e in errors)

    def test_common_password_rejected(self):
        ok, errors = PasswordValidator.validate('Password123')
        assert ok is False
        assert any('شائعة' in e for e in errors)

    def test_sequence_rejected(self):
        ok, errors = PasswordValidator.validate('Xy9!abcQwK2#')
        assert ok is False
        assert any('تسلسلات' in e for e in errors)

    def test_strong_password_accepted(self):
        ok, errors = PasswordValidator.validate(STRONG)
        assert ok is True and errors == []


class TestStrengthScore:
    def test_empty_scores_zero(self):
        assert PasswordValidator.get_strength_score('') == 0

    def test_capped_at_100(self):
        long_unique = 'Aa1!Bb2@Cc3#Dd4$Ee5%Ff6^Gh7&Ij8*'
        assert PasswordValidator.get_strength_score(long_unique) == 100

    def test_repetition_penalty_applies(self):
        varied = 'Ab3!Xy9#Qw2$'
        repeated = 'Aa1!Aa1!Aa1!'
        assert (PasswordValidator.get_strength_score(varied)
                > PasswordValidator.get_strength_score(repeated))

    def test_weak_scores_low(self):
        assert PasswordValidator.get_strength_score('abc') < 30


class TestStrengthLabel:
    @pytest.mark.parametrize('score,expected', [
        (0, ('ضعيف جداً', 'danger')),
        (29, ('ضعيف جداً', 'danger')),
        (30, ('ضعيف', 'warning')),
        (49, ('ضعيف', 'warning')),
        (50, ('متوسط', 'info')),
        (69, ('متوسط', 'info')),
        (70, ('قوي', 'primary')),
        (89, ('قوي', 'primary')),
        (90, ('قوي جداً', 'success')),
        (100, ('قوي جداً', 'success')),
    ])
    def test_label_boundaries(self, score, expected):
        assert PasswordValidator.get_strength_label(score) == expected


class TestSuggestionAndHelper:
    def test_suggestion_passes_validation(self):
        for _ in range(3):
            assert PasswordValidator.validate(
                PasswordValidator.generate_suggestion())[0] is True

    def test_suggestion_ignores_username(self):
        pwd = PasswordValidator.generate_suggestion(username='owner')
        assert PasswordValidator.validate(pwd)[0] is True

    def test_helper_success_message(self):
        ok, msg = validate_password_with_helpful_message(STRONG)
        assert ok is True and '/100' in msg

    def test_helper_failure_message_with_suggestion(self):
        ok, msg = validate_password_with_helpful_message('abc')
        assert ok is False and 'اقتراح' in msg
