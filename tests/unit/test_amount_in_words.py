"""Amount-in-words — invoice footer legal wording."""

from decimal import Decimal

from utils.amount_in_words import (
    amount_in_words,
    number_words_ar,
    number_words_en,
)


class TestArabicWords:
    def test_zero(self):
        assert number_words_ar(0) == "صفر"

    def test_units_and_tens(self):
        assert number_words_ar(7) == "سبعة"
        assert number_words_ar(22) == "اثنان وعشرون"

    def test_hundreds(self):
        assert number_words_ar(100) == "مائة"
        assert number_words_ar(200) == "مائتان"
        assert number_words_ar(350) == "ثلاثمائة وخمسون"

    def test_thousands_and_millions(self):
        assert number_words_ar(1000) == "ألف"
        assert number_words_ar(2000) == "ألفين"
        assert number_words_ar(3000) == "ثلاثة آلاف"
        assert number_words_ar(1500) == "ألف وخمسمائة"
        assert number_words_ar(1_000_000) == "مليون"
        assert number_words_ar(2_000_000) == "مليونين"

    def test_full_amount_sentence(self):
        s = amount_in_words(1500, "AED", "ar")
        assert "ألف وخمسمائة" in s
        assert "درهم إماراتي" in s
        assert s.endswith("فقط")

    def test_fraction_is_included_in_words(self):
        s = amount_in_words(Decimal("3250.50"), "SAR", "ar")
        assert "هللة" in s
        assert "ثلاثة آلاف" in s

    def test_zero_fraction_omitted(self):
        s = amount_in_words(Decimal("100.00"), "SAR", "ar")
        assert "هللة" not in s


class TestEnglishWords:
    def test_zero(self):
        assert number_words_en(0) == "Zero"

    def test_composite(self):
        assert number_words_en(21) == "Twenty One"
        assert number_words_en(100) == "One Hundred"
        assert number_words_en(1500) == "One Thousand Five Hundred"

    def test_full_amount_sentence(self):
        s = amount_in_words(1500, "AED", "en")
        assert "One Thousand Five Hundred" in s
        assert "UAE Dirham" in s
        assert s.endswith("only")

    def test_fraction_is_included(self):
        s = amount_in_words(Decimal("1500.50"), "AED", "en")
        assert "Fifty" in s
        assert "Fils" in s
