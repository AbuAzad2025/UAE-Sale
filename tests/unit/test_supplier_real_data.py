"""Supplier 'Al Nizal / Hi Cable' carries its real delivery-note identity."""
import os
os.environ.setdefault('PYTHONIOENCODING','utf-8')

from playwright.sync_api import sync_playwright


def test_supplier_real_identity_in_ui():
    """Regression: supplier 1 must display the real delivery-note details."""
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={'width':1280,'height':800})
        pg.goto('http://localhost:8001/auth/login')
        pg.wait_for_load_state('load')
        pg.fill('input[name="username"]', 'samarkand_manager')
        pg.fill('input[name="password"]', 'Test-samarqand-2026!')
        pg.locator('button[type="submit"]').first.click()
        pg.wait_for_load_state('load')
        pg.goto('http://localhost:8001/suppliers/1/edit')
        pg.wait_for_load_state('load')
        vals = {
            'name': "شركة النزال للكوابل للحلول الذكية",
            'name_en': "Hi Cable Company for Smart Solutions",
            'phone': "0592053262",
            'tax_number': "562335687",
            'address': "رام الله - فلسطين",
        }
        for name, expected in vals.items():
            actual = pg.locator(f'[name="{name}"]').first.input_value()
            assert actual == expected, (name, actual, expected)
        b.close()
