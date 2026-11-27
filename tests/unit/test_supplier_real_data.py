"""The supplier edit form shows the stored delivery-note identity."""

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from models import Supplier


def test_supplier_identity_in_edit_form(client, login_owner, db):
    fields = {
        "name": "مورد اختبار الطباعة",
        "name_en": "Delivery Note Fixture",
        "phone": "0590001234",
        "tax_number": "TAX-FIXTURE-123",
        "address": "عنوان اختباري",
    }
    supplier = Supplier(**fields)
    db.session.add(supplier)
    db.session.commit()
    path = f"/suppliers/{supplier.id}/edit"
    response = client.get(path)
    assert response.status_code == 200

    with sync_playwright() as playwright:
        channel = os.environ.get("PLAYWRIGHT_BROWSER_CHANNEL") or (
            "chromium"
            if Path(playwright.chromium.executable_path).is_file()
            else "chrome"
        )
        browser = playwright.chromium.launch(headless=True, channel=channel)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.route("**/*", lambda route: route.abort())
            page.route(
                "http://supplier.test" + path,
                lambda route: route.fulfill(
                    status=200, content_type="text/html", body=response.data
                ),
            )
            page.goto("http://supplier.test" + path)
            for name, expected in fields.items():
                assert page.locator(f'[name="{name}"]').first.input_value() == expected
        finally:
            browser.close()
