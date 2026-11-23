"""Dashboard UI: tenant colours, translated labels, dual footer, fluid width."""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_unified_tenant_palette():
    src = open(os.path.join(ROOT, "templates", "dashboard.html"), encoding="utf-8").read()
    assert "--tenant-brand: #007A3D" in src
    # no random per-card gradients / button colours left
    assert "linear-gradient(135deg, #" not in src
    assert "btn-sm btn-warning" not in src
    assert "dash-action" in src
    assert ".stat-label { color: #222 !important" in src


def test_dual_footer_identities_and_fluid_width():
    src = open(os.path.join(ROOT, "templates", "base.html"), encoding="utf-8").read()
    assert "footer-tenant" in src  # tenant block
    assert "img/azad_logo.png" in src  # platform block
    assert "--footer-side-offset" in src
    assert "MutationObserver" in src
    css = open(os.path.join(ROOT, "static", "css", "enhancements.css"), encoding="utf-8").read()
    assert ".main-footer-azad { margin-right: 0 !important; }" in css
    assert "margin-inline-start: var(--footer-side-offset" in css


def test_tenant_logo_in_shell_but_platform_logo_in_footer():
    src = open(os.path.join(ROOT, "templates", "base.html"), encoding="utf-8").read()
    assert "_tenant_logo" in src
    assert "img/tenants/samarkand_logo.png" in src
