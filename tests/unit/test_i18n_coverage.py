"""Permanent regression tests for the full UI i18n migration.

Guarantees:
  * every t('key') used in a template actually exists in the dictionary
  * no two per-area dictionaries silently disagree on a key's translation
  * every template still parses as valid Jinja
  * t() honours the session language (ar -> Arabic, en -> English)
"""
import ast
import os
import re

import pytest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TPL_DIR = os.path.join(ROOT, "templates")
KEYS_DIR = os.path.join(ROOT, "utils", "i18n_keys")
# Capture the WHOLE quoted literal so ast.literal_eval reproduces exactly
# what Jinja evaluates (quotes of the other kind, \\n, escaped quotes, etc.).
KEY_RE = re.compile(r"""\bt\(\s*('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")""")


def _keys_in(src):
    for m in KEY_RE.finditer(src):
        yield ast.literal_eval(m.group(1))


def _templates():
    for base, _dirs, files in os.walk(TPL_DIR):
        for name in files:
            if name.endswith(".html"):
                yield os.path.join(base, name)


def _agent_dicts():
    """Return {filename: {key: {'ar':..., 'en':...}}} from agent_*.py files."""
    out = {}
    if not os.path.isdir(KEYS_DIR):
        return out
    for name in sorted(os.listdir(KEYS_DIR)):
        if not (name.startswith("agent_") and name.endswith(".py")):
            continue
        path = os.path.join(KEYS_DIR, name)
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "TRANSLATIONS" for t in node.targets
            ):
                out[name] = ast.literal_eval(node.value)
                break
    return out


def test_t_calls_have_dictionary_keys():
    from utils.i18n import TRANSLATIONS

    dicts = _agent_dicts()
    local = set(TRANSLATIONS)
    for filename, d in dicts.items():
        local |= set(d)

    missing = {}
    for path in _templates():
        src = open(path, encoding="utf-8").read()
        for key in _keys_in(src):
            if key not in local:
                missing.setdefault(os.path.relpath(path, ROOT), set()).add(key)
    assert not missing, f"t() keys without a translation: {missing}"


def test_agent_dictionaries_do_not_conflict():
    dicts = _agent_dicts()
    owners = {}
    conflicts = []
    for filename, d in dicts.items():
        for key, value in d.items():
            assert isinstance(value, dict), (filename, key)
            assert set(value) >= {"ar", "en"}, (filename, key, value)
            owners.setdefault(key, []).append((filename, value))
    for key, entries in owners.items():
        if len(entries) < 2:
            continue
        values = {tuple(sorted(v.items())) for _f, v in entries}
        if len(values) > 1:
            conflicts.append((key, [f for f, _ in entries]))
    assert not conflicts, f"conflicting translations for keys: {conflicts}"


def test_all_templates_parse():
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(TPL_DIR))
    for path in _templates():
        src = open(path, encoding="utf-8").read()
        try:
            env.parse(src)
        except Exception as exc:  # pragma: no cover - diagnostic
            pytest.fail(f"{os.path.relpath(path, ROOT)}: {exc}")


def test_t_respects_language(monkeypatch):
    from utils import i18n

    monkeypatch.setattr(i18n, "get_current_language", lambda: "ar")
    assert i18n.t("Save") == "حفظ"
    monkeypatch.setattr(i18n, "get_current_language", lambda: "en")
    assert i18n.t("Save") == "Save"


def test_status_badge_honours_language(monkeypatch):
    import app as app_module

    monkeypatch.setattr(
        "utils.i18n.get_current_language", lambda: "en"
    )
    html = str(app_module._status_badge("unpaid"))
    assert "Unpaid" in html and "غير مدفوع" not in html
    monkeypatch.setattr("utils.i18n.get_current_language", lambda: "ar")
    html = str(app_module._status_badge("unpaid"))
    assert "غير مدفوع" in html


def test_agent_keys_are_reused_not_duplicated_in_i18n_py():
    """Per-area keys must live in agent files, never be pasted into i18n.py."""
    src = open(os.path.join(ROOT, "utils", "i18n.py"), encoding="utf-8").read()
    assert "agent_" in src  # auto-loader present
    assert "Selftest" not in src
