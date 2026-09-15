"""Wave-1 coverage tests for ai_knowledge/document_generator.py (DB-backed)."""
import csv
import io

from ai_knowledge.document_generator import DocumentGenerator, document_generator


def test_generate_receipt_success_and_unformatted_template(db, test_sale):
    content, message = DocumentGenerator.generate_receipt(test_sale.id)
    assert content is not None
    assert message == 'تم توليد سند القبض بنجاح'
    assert 'سند قبض' in content
    # BUG: template is a plain (non-f) string so placeholders are never
    # interpolated; the literal text is returned as-is.
    assert '{sale_id' in content


def test_generate_receipt_missing_sale(db):
    content, message = DocumentGenerator.generate_receipt(999999)
    assert content is None
    assert message == 'الفاتورة غير موجودة'


def test_generate_invoice_hits_wrong_relationship_name(db, test_sale):
    # BUG: Sale exposes `lines`, not `sale_lines` -> AttributeError caught
    # and reported instead of an invoice.
    content, message = DocumentGenerator.generate_invoice(test_sale.id)
    assert content is None
    assert message.startswith('خطأ في توليد الفاتورة')
    assert 'sale_lines' in message


def test_generate_invoice_missing_sale(db):
    content, message = DocumentGenerator.generate_invoice(999999)
    assert content is None
    assert message == 'الفاتورة غير موجودة'


def test_generate_sales_report_with_data(db, test_sale):
    content, message = DocumentGenerator.generate_sales_report()
    assert content is not None
    assert message == 'تم توليد تقرير المبيعات بنجاح'
    assert 'تقرير المبيعات' in content


def test_generate_sales_report_empty(db):
    content, message = DocumentGenerator.generate_sales_report()
    assert content is None
    assert message == 'لا توجد مبيعات في الفترة المحددة'


def test_generate_sales_report_date_filter_excludes(db, test_sale):
    from datetime import datetime, timedelta, timezone
    future = datetime.now(timezone.utc) + timedelta(days=30)
    content, message = DocumentGenerator.generate_sales_report(start_date=future)
    assert content is None
    assert message == 'لا توجد مبيعات في الفترة المحددة'


def test_export_sales_csv(db, test_sale, test_customer):
    payload, filename = DocumentGenerator.export_to_excel('sales')
    assert filename.startswith('sales_export_') and filename.endswith('.csv')
    text = payload.getvalue().decode('utf-8-sig')
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][0] == 'رقم الفاتورة'
    assert len(rows) == 2
    assert rows[1][1] == test_customer.name
    assert rows[1][6] == 'غير مدفوع'


def test_export_customers_csv(db, test_customer):
    payload, filename = DocumentGenerator.export_to_excel('customers')
    assert filename.startswith('customers_export_') and filename.endswith('.csv')
    text = payload.getvalue().decode('utf-8-sig')
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][1] == 'الاسم'
    assert rows[1][1] == test_customer.name


def test_export_products_hits_missing_unit_price(db, test_product):
    # BUG: Product has `regular_price`, not `unit_price` -> AttributeError
    # caught and reported instead of a CSV.
    payload, message = DocumentGenerator.export_to_excel('products')
    assert payload is None
    assert message.startswith('خطأ في تصدير البيانات')
    assert 'unit_price' in message


def test_export_invalid_type(db):
    payload, message = DocumentGenerator.export_to_excel('bogus')
    assert payload is None
    assert message == 'نوع البيانات غير صحيح'


def test_generate_customer_statement_success(db, test_customer, test_sale):
    content, message = DocumentGenerator.generate_customer_statement(test_customer.id)
    assert content is not None
    assert message == 'تم توليد كشف الحساب بنجاح'
    assert 'كشف حساب العميل' in content


def test_generate_customer_statement_missing_customer(db):
    content, message = DocumentGenerator.generate_customer_statement(999999)
    assert content is None
    assert message == 'العميل غير موجود'


def test_global_instance():
    assert isinstance(document_generator, DocumentGenerator)
