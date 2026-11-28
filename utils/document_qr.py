"""Real QR codes for printed tenant documents.

The QR carries a compact, self-contained verification payload so a scanned
receipt/invoice can be checked offline: tenant identity, document type/id and
tax registration. No platform identity is ever embedded.
"""
import base64
import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def qr_data_url(payload: str) -> str:
    """Return a base64 PNG data URL for the given payload."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=5,
        border=4,
    )
    qr.add_data(str(payload or ""))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def document_payload(doc_type: str, doc_id, settings=None) -> str:
    """Build the tenant-isolated verification payload."""
    tenant_name = ""
    tax = ""
    if settings:
        tenant_name = (
            getattr(settings, "company_name_en", None)
            or getattr(settings, "company_name_ar", None)
            or ""
        )
        tax = getattr(settings, "tax_number", None) or ""
    return "|".join(
        str(x)
        for x in (
            "AZD-DOC-V1",
            tenant_name,
            doc_type or "document",
            doc_id or "",
            tax,
        )
    )
