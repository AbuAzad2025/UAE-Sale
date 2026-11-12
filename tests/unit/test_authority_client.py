"""Authority client seam — يضمن أن كل دولة لها عميل مهيأ (والآن: ManualAuthorityClient فقط)."""

from services.authority_client import (
    ManualAuthorityClient,
    authority_client,
    _authority_key_for_country,
)


def test_all_countries_have_a_client():
    for code in ("SA", "AE", "EG", "TR", "BH", "OM", "GB", "DE", "JO"):
        assert isinstance(
            authority_client(_authority_key_for_country(code)), ManualAuthorityClient
        )


def test_manual_client_records_intent_and_contacts_nothing():
    class Doc:
        id = 42

    client = ManualAuthorityClient()
    result = client.submit_invoice(Doc(), tenant_id=7)
    assert result["status"] == "manual"
    assert result["reference"] is None
    assert result["tenant_id"] == 7
    assert client.health()["status"] == "manual"


def test_unknown_country_falls_back_to_manual():
    assert isinstance(authority_client("manual"), ManualAuthorityClient)
    assert _authority_key_for_country("ZZ") == "manual"
    assert _authority_key_for_country(None) == "manual"


def test_invoice_status_is_manual_and_no_external_call():
    out = ManualAuthorityClient().invoice_status("REF-1", tenant_id=3)
    assert out["status"] == "manual"
    assert out["reference"] == "REF-1"
    assert out["tenant_id"] == 3
