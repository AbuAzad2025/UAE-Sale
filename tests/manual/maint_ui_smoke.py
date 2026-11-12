"""End-to-end smoke test of the maintenance module over real HTTP.

Runs against a RUNNING server (the throwaway SQLite database seeded by
tests/manual/maint_ui_seed.py). It exercises the browser path: login with a
CSRF token, then reception -> parts -> services -> invoice -> receipt ->
delivery -> printing, and checks the resulting ledger in the database.

Usage:
    MAINT_UI_DB=<path> MAINT_UI_BASE=http://127.0.0.1:5055 \
        python tests/manual/maint_ui_smoke.py
"""

import os
import re
import sqlite3
import sys

import requests

BASE = os.environ.get("MAINT_UI_BASE", "http://127.0.0.1:5055").rstrip("/")
DB_PATH = os.environ.get("MAINT_UI_DB")
USERNAME = os.environ.get("MAINT_UI_USER", "smoke")
PASSWORD = os.environ.get("MAINT_UI_PASSWORD", "SmokeTest-Password-123!")

failures = []


def check(condition, message):
    if condition:
        print(f"  OK   {message}")
    else:
        failures.append(message)
        print(f"  FAIL {message}")


def csrf_of(session, path):
    response = session.get(f"{BASE}{path}")
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    return match.group(1) if match else None


def post(session, path, data, token=None):
    payload = dict(data)
    if token:
        payload["csrf_token"] = token
    return session.post(f"{BASE}{path}", data=payload, allow_redirects=True)


def flash_messages(response):
    return re.findall(
        r"alert-(?:success|danger|warning|info)[^>]*>(.*?)</div>", response.text, re.S
    )


def main():
    session = requests.Session()

    token = csrf_of(session, "/auth/login")
    check(token is not None, "login page carries a CSRF token")
    response = post(
        session, "/auth/login", {"username": USERNAME, "password": PASSWORD}, token
    )
    check("/auth/login" not in response.url, "login succeeded")

    # --- reception -------------------------------------------------------
    token = csrf_of(session, "/maintenance/create")
    check(token is not None, "reception form carries a CSRF token")
    create_page = session.get(f"{BASE}/maintenance/create").text
    customer_match = re.search(
        r'name="customer_id".*?<option value="(\d+)"', create_page, re.S
    )
    check(customer_match is not None, "the customer list is rendered")
    response = post(
        session,
        "/maintenance/create",
        {
            "customer_id": customer_match.group(1) if customer_match else "",
            "device_brand": "Toyota",
            "device_model": "Camry",
            "device_serial": "UI-SMOKE-1",
            "device_problem": "Brake noise",
            "payment_mode": "cash",
            "priority": "normal",
        },
        token,
    )
    check(
        re.search(r"/maintenance/\d+", response.url) is not None,
        "the order was created and redirected to it",
    )
    order_id = int(re.search(r"/maintenance/(\d+)", response.url).group(1))
    check("UI-SMOKE-1" in response.text, "the order page shows the device serial")

    # --- a part is issued -------------------------------------------------
    token = csrf_of(session, f"/maintenance/{order_id}")
    product_match = re.search(
        r'<option value="(\d+)">([^<]*\(SMOKE-1\))', response.text
    )
    warehouse_match = re.search(
        r'name="warehouse_id".*?<option value="(\d+)"', response.text, re.S
    )
    check(
        product_match is not None and warehouse_match is not None,
        "the part and the warehouse are offered in the form",
    )
    response = post(
        session,
        f"/maintenance/{order_id}/item",
        {
            "product_id": product_match.group(1),
            "warehouse_id": warehouse_match.group(1),
            "quantity": "2",
            "unit_price": "100",
            "tax_rate": "5",
            "discount_percent": "0",
        },
        token,
    )
    check(
        "210" in response.text.replace(",", ""), "the order shows the new total (210)"
    )

    # --- a service --------------------------------------------------------
    token = csrf_of(session, f"/maintenance/{order_id}")
    response = post(
        session,
        f"/maintenance/{order_id}/service",
        {
            "service_name": "Diagnostics",
            "service_name_ar": "فحص",
            "service_code": "DIAG-1",
            "unit_price": "50",
            "tax_rate": "5",
            "duration_minutes": "30",
            "cost_price": "10",
        },
        token,
    )
    check("Diagnostics" in response.text, "the service line is listed")
    check(
        "262.500" in response.text.replace(",", ""),
        "the total includes the service (262.500)",
    )

    # --- status transitions ----------------------------------------------
    for status in ("diagnosis", "in_progress", "ready"):
        token = csrf_of(session, f"/maintenance/{order_id}")
        response = post(
            session, f"/maintenance/{order_id}/status", {"status": status}, token
        )
        check(
            status in response.text or "سجل حالات الأمر" in response.text,
            f"status moved to {status}",
        )

    # --- invoice ----------------------------------------------------------
    token = csrf_of(session, f"/maintenance/{order_id}")
    response = post(session, f"/maintenance/{order_id}/invoice", {}, token)
    check("MI-" in response.text, "the invoice number is shown on the order")
    check("مُرحَّلة" in response.text, "the invoice is marked as posted")

    # --- a cash order cannot be delivered unpaid ---------------------------
    token = csrf_of(session, f"/maintenance/{order_id}")
    response = post(
        session, f"/maintenance/{order_id}/status", {"status": "closed"}, token
    )
    check(
        "لا يمكن التسليم قبل سداد" in response.text,
        "delivery is refused while the balance is open",
    )

    # --- receipt ----------------------------------------------------------
    token = csrf_of(session, f"/maintenance/{order_id}")
    response = post(
        session,
        f"/maintenance/{order_id}/receive",
        {"amount": "100", "payment_method": "cash"},
        token,
    )
    check("PT-MN-" in response.text, "the receipt number is shown")

    token = csrf_of(session, f"/maintenance/{order_id}")
    response = post(
        session,
        f"/maintenance/{order_id}/receive",
        {"amount": "162.5", "payment_method": "cash"},
        token,
    )
    check(
        "262.500" in response.text.replace(",", ""), "the order total is still 262.500"
    )

    token = csrf_of(session, f"/maintenance/{order_id}")
    response = post(
        session, f"/maintenance/{order_id}/status", {"status": "closed"}, token
    )
    check(
        "closed" in response.text or "مغلق" in response.text,
        "the order is closed after it is paid in full",
    )

    # --- printing ---------------------------------------------------------
    response = session.get(f"{BASE}/maintenance/{order_id}")
    receipt_match = re.search(r"/print-receipt\?receipt_id=(\d+)", response.text)
    check(receipt_match is not None, "the order links to its receipt print-out")
    response = session.get(f"{BASE}/maintenance/{order_id}/print-intake")
    check(response.status_code == 200, f"print-intake renders ({response.status_code})")
    response = session.get(f"{BASE}/maintenance/{order_id}/print-receipt")
    check(
        response.status_code == 404,
        "printing a receipt without choosing one is refused (404)",
    )
    response = session.get(
        f"{BASE}/maintenance/{order_id}/print-receipt?receipt_id={receipt_match.group(1)}"
    )
    check(response.status_code == 200, "the chosen receipt prints")
    response = session.get(f"{BASE}/maintenance/{order_id}/print-invoice")
    check(response.status_code == 200, "the invoice prints")
    response = session.get(f"{BASE}/maintenance/cost-report")
    check(
        response.status_code == 200 and "الإيرادات الإجمالية" in response.text,
        "the cost report renders",
    )
    response = session.get(f"{BASE}/maintenance/purchases")
    check(response.status_code == 200, "the purchases page renders")

    # --- the ledger behind it --------------------------------------------
    connection = sqlite3.connect(DB_PATH)
    entries = connection.execute(
        "SELECT reference_type, description, total_debit, total_credit, is_posted "
        "FROM gl_journal_entries ORDER BY id"
    ).fetchall()
    print("\n  journal entries:")
    for entry in entries:
        print("   ", entry)
    check(
        all(row[2] == row[3] and row[2] > 0 for row in entries),
        "every journal entry is balanced and posted",
    )
    types = [row[0] for row in entries]
    check(types.count("maintenance_item") == 1, "one cost entry for the issued part")
    check(types.count("maintenance_invoice") == 1, "one revenue entry for the invoice")
    check(types.count("maintenance_receipt") == 2, "two collection entries")
    lines = connection.execute(
        "SELECT a.code, SUM(l.debit), SUM(l.credit) FROM gl_journal_lines l "
        "JOIN gl_accounts a ON a.id = l.account_id GROUP BY a.code "
        "ORDER BY a.code"
    ).fetchall()
    print("\n  account movement:")
    for line in lines:
        print("   ", line)
    balances = {code: (debit or 0) - (credit or 0) for code, debit, credit in lines}
    check(
        abs(balances.get("1140", 0) + 60) < D("0.001"),
        "inventory is relieved by the cost (60)",
    )
    check(
        abs(balances.get("4210", 0) + 250) < D("0.001"),
        "maintenance revenue is 250 net",
    )
    check(abs(balances.get("2131", 0) + 12.5) < D("0.001"), "VAT output is 12.500")
    check(
        abs(balances.get("1131", 0)) < D("0.001"),
        "the receivable is settled (balance zero)",
    )
    check(abs(balances.get("5101", 0) - 60) < D("0.001"), "maintenance cost is 60")
    check(
        abs(balances.get("1110", 0) - 262.5) < D("0.001"), "cash collected is 262.500"
    )
    connection.close()

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for failure in failures:
            print("  -", failure)
        return 1
    print("ALL BROWSER-PATH CHECKS PASSED")
    return 0


if __name__ == "__main__":
    from decimal import Decimal as D

    sys.exit(main())
