"""Dashboard UI: tenant colours, translated labels, dual footer, fluid width."""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_unified_tenant_palette():
    src = open(os.path.join(ROOT, "templates", "dashboard.html"), encoding="utf-8").read()
    assert "--tenant-primary" in src or "var(--tenant-primary" in src
    # no random per-card gradients / button colours left
    assert "linear-gradient(135deg, #" not in src
    assert "btn-sm btn-warning" not in src
    assert "dash-action" in src
    assert ".stat-label { color: #222 !important" in src


def test_dual_footer_identities_and_fluid_width():
    src = open(os.path.join(ROOT, "templates", "base.html"), encoding="utf-8").read()
    assert "footer-tenant" in src  # tenant block
    assert "footer-platform" in src  # platform block
    assert "config.COMPANY_PHONE" in src  # platform contact from owner config
    assert "config.COMPANY_WHATSAPP" in src
    assert "img/azad_logo.png" in src  # platform logo
    # unified two-column footer, pinned to bottom of content-wrapper
    assert '<footer class="main-footer main-footer-azad">' in src
    assert "syncFooterWidth" not in src
    css = open(os.path.join(ROOT, "static", "css", "enhancements.css"), encoding="utf-8").read()
    assert ".main-footer .footer-col" in css
    assert "margin-top: auto !important" in css
    assert "padding-bottom: 0 !important" in css
    # no neon-green footer from the old theme
    other = open(os.path.join(ROOT, "static", "css", "modern-arabic-style.css"), encoding="utf-8").read()
    assert "#7CFC00" not in other


def test_theme_toggle_in_navbar():
    js = open(os.path.join(ROOT, "static", "js", "dark-mode.js"), encoding="utf-8").read()
    assert "navbarWidgets.insertBefore" in js
    assert "navbar-widgets" in js
    assert "navbarWidgets.appendChild(toggleButton)" not in js


def test_navbar_clean_and_no_duplicate_logo():
    src = open(os.path.join(ROOT, "templates", "base.html"), encoding="utf-8").read()
    nav = src[src.index('<nav class="main-header'):src.index('</nav>')]
    assert '<img' not in nav  # no extra logo in navbar (sidebar/footer only)
    assert nav.count('data-widget="pushmenu"') == 1
    assert "toggleSidebarDirection()" in nav  # one position toggle
    assert "nav-icon" in nav and "navbar-separator" in nav
    js = open(os.path.join(ROOT, "static", "js", "dark-mode.js"), encoding="utf-8").read()
    assert "fa-moon" in js and "fa-sun" in js  # icon toggle, not text


def test_no_floating_help_button_and_safe_modal():
    js = open(os.path.join(ROOT, "static", "js", "keyboard-shortcuts.js"), encoding="utf-8").read()
    assert "shortcuts-help-btn" not in js
    assert "shortcuts-nav-btn" in js
    assert "typeof $ === 'undefined'" in js  # modal guarded
    assert "typeof notify !== 'undefined'" in js  # first-load tip guarded


def test_tenant_logo_in_shell_but_platform_logo_in_footer():
    src = open(os.path.join(ROOT, "templates", "base.html"), encoding="utf-8").read()
    assert "_tenant_logo" in src
    assert "current_tenant.logo_url" in src
