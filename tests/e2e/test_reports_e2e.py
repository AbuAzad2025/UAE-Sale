"""
E2E tests for Reports module - comprehensive coverage of all routes.
Tests cover: report index, sales, purchases, receivables, inventory, valuation, 
AP aging, cash flow, VAT report, top-selling, exports.
"""

import pytest


class TestReportsIndex:
    def test_reports_index_renders(self, client, login_as):
        login_as('owner')
        r = client.get('/reports/')
        assert r.status_code == 200


class TestSalesReport:
    def test_sales_report_renders(self, client, login_as, sale):
        login_as('owner')
        r = client.get('/reports/sales')
        assert r.status_code == 200
        assert sale.receipt_number in r.get_data(as_text=True)

    def test_sales_report_with_filters(self, client, login_as, sale):
        login_as('owner')
        r = client.get('/reports/sales', query_string={
            'date_from': '2026-01-01',
            'date_to': '2026-12-31',
        })
        assert r.status_code == 200


class TestPurchasesReport:
    def test_purchases_report_renders(self, client, login_as, purchase):
        login_as('owner')
        r = client.get('/reports/purchases')
        assert r.status_code == 200
        assert purchase.payment_number in r.get_data(as_text=True)


class TestReceivablesReport:
    def test_receivables_report_renders(self, client, login_as, customer, sale):
        login_as('owner')
        r = client.get('/reports/receivables')
        assert r.status_code == 200
        assert customer.name in r.get_data(as_text=True)


class TestInventoryReport:
    def test_inventory_report_renders(self, client, login_as, product):
        login_as('owner')
        r = client.get('/reports/inventory')
        assert r.status_code == 200
        assert product.name in r.get_data(as_text=True)


class TestInventoryValuation:
    def test_inventory_valuation_renders(self, client, login_as, product):
        login_as('owner')
        r = client.get('/reports/inventory-valuation')
        assert r.status_code == 200
        assert 'valuation' in r.get_data(as_text=True).lower()


class TestApAging:
    def test_ap_aging_renders(self, client, login_as, supplier, purchase):
        login_as('owner')
        r = client.get('/reports/ap-aging')
        assert r.status_code == 200
        assert supplier.name in r.get_data(as_text=True)


class TestCashFlow:
    def test_cash_flow_renders(self, client, login_as, sale, purchase):
        login_as('owner')
        r = client.get('/reports/cash-flow')
        assert r.status_code == 200
        assert 'cash flow' in r.get_data(as_text=True).lower()


class TestVatReport:
    def test_vat_report_renders(self, client, login_as, sale, purchase):
        login_as('owner')
        r = client.get('/reports/vat-report')
        assert r.status_code == 200
        assert 'vat' in r.get_data(as_text=True).lower()


class TestTopSelling:
    def test_top_selling_renders(self, client, login_as, sale, product):
        login_as('owner')
        r = client.get('/reports/top-selling')
        assert r.status_code == 200
        assert product.name in r.get_data(as_text=True)


class TestPartnersReport:
    def test_partners_report_renders(self, client, login_as, customer, sale):
        login_as('owner')
        r = client.get('/reports/partners')
        assert r.status_code == 200
        assert customer.name in r.get_data(as_text=True)


class TestExports:
    def test_export_sales_excel(self, client, login_as, sale):
        login_as('owner')
        r = client.get('/reports/sales/export?format=excel')
        assert r.status_code == 200
        assert r.content_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

    def test_export_sales_csv(self, client, login_as, sale):
        login_as('owner')
        r = client.get('/reports/sales/export?format=csv')
        assert r.status_code == 200
        assert r.content_type == 'text/csv'

    def test_export_purchases_excel(self, client, login_as, purchase):
        login_as('owner')
        r = client.get('/reports/purchases/export?format=excel')
        assert r.status_code == 200

    def test_export_receivables_excel(self, client, login_as, customer, sale):
        login_as('owner')
        r = client.get('/reports/receivables/export?format=excel')
        assert r.status_code == 200

    def test_export_inventory_excel(self, client, login_as, product):
        login_as('owner')
        r = client.get('/reports/inventory/export?format=excel')
        assert r.status_code == 200

    def test_export_vat_pdf(self, client, login_as):
        login_as('owner')
        r = client.get('/reports/vat-report/export?format=pdf')
        assert r.status_code == 200
        assert r.content_type == 'application/pdf'