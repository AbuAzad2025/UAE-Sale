"""Unified, tenant-isolated, direction-aware brand header on every print page."""

import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _base():
    return open(
        os.path.join(ROOT, "templates", "base_print.html"), encoding="utf-8"
    ).read()


def test_three_part_header_direction_aware():
    src = _base()
    # logical properties => RTL/LTR mirror automatically
    assert "inset-inline-start:" in src
    assert "inset-inline-end:" in src
    assert "padding-inline: 125px" in src
    # tenant identity appears in the header (center is existing template markup)
    assert "_mono" in src and "_logo_src" in src


def test_all_receipt_templates_share_toolbar():
    folder = os.path.join(ROOT, "templates", "receipts")
    for f in os.listdir(folder):
        if f.endswith(".html"):
            src = open(os.path.join(folder, f), encoding="utf-8").read()
            assert "base_print.html" in src, f
            assert "receipt-print" not in src, f


def test_uploaded_logo_reaches_document_header():
    src = open(
        os.path.join(ROOT, "utils", "invoice_header.py"), encoding="utf-8"
    ).read()
    assert "settings" in src and "logo_path" in src
    assert "settings" in src and "tenant_id" in src
    assert "tenant.logo_url" in src


def test_real_samarkand_logo_asset():
    folder = os.path.join(ROOT, "static", "uploads", "tenant_2", "uploads", "logos")
    files = [f for f in os.listdir(folder) if f.endswith(".png")]
    assert files, "no tenant logo asset present"
    # A genuine Samarkand logo exists (not the Azad platform logo).
    assert any("samarkand" in f.lower() for f in files)


def test_real_qr_in_header_not_fontawesome_placeholder():
    src = _base()
    assert "qr_data_url(document_payload(" in src
    assert "data:image/png;base64" not in src  # injected at runtime, not literal
    assert "background-image: url('{{ _qr_url }}')" in src
    # no tax-badge duplication: tax text is no longer in the header pseudo
    assert "settings.tax_number if settings" not in src
    # fake FontAwesome QR blocks removed from invoice templates
    inv = os.path.join(ROOT, "templates", "invoices")
    for f in os.listdir(inv):
        if f.endswith(".html"):
            s = open(os.path.join(inv, f), encoding="utf-8").read()
            assert "fa-qrcode" not in s, f


def test_whatsapp_qr_is_printed_and_single_instance():
    src = _base()
    assert "TENANT_WHATSAPP_QR" in src
    assert "injectWhatsAppQR" in src
    assert "https://wa.me/" in src
    assert "tenant-wa-qr" in src
    # the QR is generated from the WhatsApp URL, not a clickable button
    assert "qr_data_url(_wa_url)" in src
    assert "tenant-wa-btn" not in src
    # WhatsApp QR must be injected into the FOOTER, not the header
    assert "foots = document.querySelectorAll" in src
    assert "f.appendChild(box)" in src
    # company name stacked above logo, built in JS
    assert "injectTenantBrand" in src and "tenant-brand-name" in src


def test_single_unified_toolbar_per_print_template():
    import glob

    # only base_print may own the print toolbar
    base = _base()
    assert "print-header-bar" in base and 'onclick="window.print()"' in base
    for folder in ("receipts", "invoices"):
        for p in glob.glob(os.path.join(ROOT, "templates", folder, "*.html")):
            s = open(p, encoding="utf-8").read()
            assert "window.print()" not in s, p
            assert "print-btn-fixed" not in s, p
    for p in ("purchases/print.html", "expenses/print.html"):
        s = open(os.path.join(ROOT, "templates", p), encoding="utf-8").read()
        assert "window.print()" not in s, p


def test_no_email_in_printed_documents():
    import glob

    for folder in ("receipts", "invoices", "purchases", "expenses"):
        for p in glob.glob(os.path.join(ROOT, "templates", folder, "*.html")):
            s = open(p, encoding="utf-8").read()
            if "print" in os.path.basename(p) or folder in ("receipts", "invoices"):
                assert "settings.email" not in s, p
    # no duplicate WhatsApp links left in the document footers
    for folder in ("receipts", "invoices"):
        d = os.path.join(ROOT, "templates", folder)
        for f in os.listdir(d):
            if f.endswith(".html"):
                s = open(os.path.join(d, f), encoding="utf-8").read()
                assert "wa.me" not in s, (folder, f)


def test_qr_generator_tenant_only():
    import base64
    from utils.document_qr import document_payload, qr_data_url

    payload = document_payload(
        "receipt",
        13,
        type("S", (), {"company_name_ar": "سمرقند", "tax_number": "T1"})(),
    )
    assert "سمرقند" in payload and "receipt" in payload and "13" in payload
    assert "Azad" not in payload
    url = qr_data_url(payload)
    assert url.startswith("data:image/png;base64,")
    raw = base64.b64decode(url.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
