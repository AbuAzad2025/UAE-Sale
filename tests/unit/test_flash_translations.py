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
        if sorted(ph.findall(ar)) != sorted(ph.findall(en)):
            bad.append(ar[:50])
    assert not bad, f"placeholder mismatch: {bad[:10]}"


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
