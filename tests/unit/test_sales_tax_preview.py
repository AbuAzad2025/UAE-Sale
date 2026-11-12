import pytest


@pytest.mark.parametrize(
    "treatment,inclusive,expected_tax,expected_total",
    [
        ("standard", False, 5.0, 105.0),
        ("standard", True, 4.76, 100.0),
        ("zero", False, 0.0, 100.0),
        ("exempt", True, 0.0, 100.0),
    ],
)
def test_preview_matches_invoice_tax_modes(
    client,
    db,
    owner_user,
    login_owner,
    treatment,
    inclusive,
    expected_tax,
    expected_total,
):
    response = client.post(
        "/sales/api/calculate-totals",
        json={
            "lines": [{"quantity": 1, "unit_price": 100, "discount_percent": 0}],
            "tax_rate": 5,
            "tax_treatment": treatment,
            "tax_inclusive": inclusive,
        },
    )
    assert response.status_code == 200
    assert response.json["tax_amount"] == expected_tax
    assert response.json["total"] == expected_total
