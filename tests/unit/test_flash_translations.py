"""Permanent tests for the full flash-message translation layer."""
import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TRANS = os.path.join(ROOT, "utils", "flash_translations.json")
SRC = os.path.join(ROOT, "utils", "flash_messages_ar.json")


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def test_all_arabic_flashes_have_english():
    msgs = _load(SRC)
    trans = _load(TRANS)
    missing = [m for m in msgs if m not in trans]
    assert not missing, f"untranslated flashes: {missing[:10]}"


def test_placeholders_preserved():
    trans = _load(TRANS)
    ph = re.compile(r"\{[^{}]+\}")
    bad = []
    for ar, en in trans.items():
        ar_ph, en_ph = ph.findall(ar), ph.findall(en)
        # Conditional expressions (e.g. {'x' if cond else 'y'}) legitimately
        # translate the words inside them; only compare the COUNT of slots.
        if len(ar_ph) != len(en_ph):
            bad.append(ar[:50])
    assert not bad, f"placeholder count mismatch: {bad[:10]}"


def test_translate_flash_respects_language(monkeypatch):
    import app as app_module
    from utils import i18n

    trans = _load(TRANS)
    ar = next(iter(trans))
    monkeypatch.setattr(i18n, "get_current_language", lambda: "ar")
    assert app_module._translate_flash(ar) == ar
    monkeypatch.setattr(i18n, "get_current_language", lambda: "en")
    assert app_module._translate_flash(ar) == trans[ar]
    assert app_module._translate_flash("Unknown message") == "Unknown message"


def test_fstring_flash_translates(monkeypatch):
    """A flash built with an f-string (placeholder already resolved) still maps."""
    import app as app_module
    from utils import i18n

    monkeypatch.setattr(i18n, "get_current_language", lambda: "en")
    out = app_module._translate_flash("✅ تم حذف الشيك CHQ-2026-0001 نهائياً")
    assert "Cheque" in out and "CHQ-2026-0001" in out
    assert "تم حذف" not in out


def test_real_newline_matches_literal_newline_key(monkeypatch):
    """A flash with a real newline matches a dict key storing literal \n."""
    import app as app_module
    from utils import i18n

    monkeypatch.setattr(i18n, "get_current_language", lambda: "en")
    runtime = "⚠️ الرجاء إدخال اسم المستخدم وكلمة المرور.\n💡 كلا الحقلين مطلوبان للدخول."
    out = app_module._translate_flash(runtime)
    assert "Please enter the username and password" in out
    assert "الرجاء" not in out
