from uuid import uuid4

from sqlalchemy import func, select

from models import AssistantAction, AuditLog, Customer


def test_customer_creation_waits_for_confirmation_and_replays_result(client, login_owner, db):
    command = {"message": "أضف عميل: زبون للتأكيد نعم، 0590000000"}
    key = str(uuid4())
    headers = {"Idempotency-Key": key}
    name = "زبون للتأكيد نعم"
    proposal = client.post("/ai/chat", json=command, headers=headers)

    assert proposal.status_code == 200
    draft = proposal.get_json()
    assert draft["action_status"] == "pending"
    assert not Customer.query.filter_by(name=name).count()
    assert client.post("/ai/chat", json=command, headers=headers).get_json() == draft
    assert client.post(
        "/ai/chat", json={"message": "أضف عميل: مختلف"}, headers=headers
    ).status_code == 409

    # Simulate loading the proposal in a fresh SQLAlchemy session.
    db.session.remove()
    assert client.get("/ai/chat/actions/pending").get_json()["actions"] == [draft]
    confirmed = client.post(draft["confirm_url"])
    assert confirmed.status_code == 200
    outcome = confirmed.get_json()
    assert outcome["action_status"] == "confirmed"
    assert client.post(draft["confirm_url"]).get_json() == outcome
    assert Customer.query.filter_by(name=name).count() == 1
    assert client.get("/ai/chat/actions/pending").get_json()["actions"] == []

    audits = db.session.scalars(
        select(AuditLog).where(AuditLog.action == "assistant_action").order_by(AuditLog.id)
    ).all()
    assert [audit.changes["outcome"] for audit in audits] == ["proposed", "confirmed"]
    assert audits[0].changes["message"] == command["message"]
    assert audits[0].changes["intent"] == "create_customer"
    assert audits[1].changes["matched_entities"]["customer_id"] == (
        Customer.query.filter_by(name=name).one().id
    )


def test_expired_confirmation_cannot_create_an_entity(client, login_owner, db):
    from datetime import datetime, timedelta

    key = str(uuid4())
    proposal = client.post(
        "/ai/chat",
        json={"message": "أضف عميل: مسودة منتهية"},
        headers={"Idempotency-Key": key},
    )
    action = db.session.get(AssistantAction, key)
    action.expires_at = datetime.now() - timedelta(days=1)
    db.session.commit()

    expired = client.post(proposal.get_json()["confirm_url"])
    assert expired.get_json()["action_status"] == "expired"
    assert not Customer.query.filter_by(name="مسودة منتهية").count()


def test_ambiguous_balance_lists_ids_without_exposing_either_balance(client, login_owner, db):
    name = "شركة النور"
    first = Customer(name=name, balance=123.45)
    second = Customer(name=name, balance=543.21)
    db.session.add_all([first, second])
    db.session.commit()

    response = client.post("/ai/chat", json={"message": f"رصيد {name}"}).get_json()["response"]
    assert f"رصيد #{first.id}" in response and f"رصيد #{second.id}" in response
    assert "123.45" not in response and "543.21" not in response


def test_legacy_write_only_offers_the_form(client, login_owner, db):
    from models import Sale

    before = db.session.scalar(select(func.count(Sale.id)))
    result = client.post("/ai/chat", json={"message": "أنشئ فاتورة: نور، منتج، 2، نعم"})
    assert result.status_code == 200
    assert "formal_url" in result.get_json()
    assert db.session.scalar(select(func.count(Sale.id))) == before



def test_stock_by_sku_and_invoice_status_are_scoped_reads(client, login_owner, test_sale, test_product):
    test_product.sku = "PART-250"
    test_product.current_stock = 8
    from extensions import db

    db.session.commit()
    stock = client.post("/ai/chat", json={"message": "مخزون الصنف PART-250"})
    assert stock.status_code == 200
    assert "8" in stock.get_json()["response"]
    invoice = client.post("/ai/chat", json={"message": f"حالة فاتورة {test_sale.sale_number}"})
    assert invoice.status_code == 200
    assert "مؤكدة" in invoice.get_json()["response"]



def test_confirmation_is_bound_to_the_proposing_user(client, login_owner, seller_user, app):
    draft = client.post(
        "/ai/chat", json={"message": "أضف عميل: ملكية المسودة"},
        headers={"Idempotency-Key": str(uuid4())},
    ).get_json()
    with app.app_context():
        other = app.test_client()
        other.post(
            "/auth/login",
            data={"username": "testseller", "password": "SellerPass123!"},
        )
        with other.session_transaction() as session:
            assert session["_user_id"] == str(seller_user.id)
        assert other.post(draft["confirm_url"]).status_code == 404
    assert not Customer.query.filter_by(name="ملكية المسودة").count()


def test_failed_write_rolls_back_the_claim_and_customer(client, login_owner, db, monkeypatch):
    from services import ai_commands

    create_customer = ai_commands.create_customer

    def fail_after_insert(**kwargs):
        create_customer(**kwargs)
        raise RuntimeError("test failure after flush")

    key = str(uuid4())
    proposal = client.post(
        "/ai/chat", json={"message": "أضف عميل: ذرية التنفيذ"},
        headers={"Idempotency-Key": key},
    ).get_json()

    with monkeypatch.context() as temporary:
        temporary.setattr(ai_commands, "create_customer", fail_after_insert)
        assert client.post(proposal["confirm_url"]).status_code == 500

    assert db.session.get(AssistantAction, key).status == "pending"
    assert not Customer.query.filter_by(name="ذرية التنفيذ").count()
    assert client.post(proposal["confirm_url"]).get_json()["action_status"] == "confirmed"
    assert Customer.query.filter_by(name="ذرية التنفيذ").count() == 1


def test_nlu_timeout_leaves_local_guidance_available(client, login_owner, app, monkeypatch):
    from services import assistant_nlu
    from services.ai_service import AIService

    monkeypatch.setitem(app.config, "AI_NLU_URL", "http://127.0.0.1:8011/interpret")

    def time_out(*args, **kwargs):
        assert kwargs["timeout"] == (0.2, 0.35)
        raise assistant_nlu.requests.Timeout

    def guidance(message, context):
        assert context["guidance_only"] and context["force_local"]
        return "شرح محلي"

    monkeypatch.setattr(assistant_nlu.requests, "post", time_out)
    monkeypatch.setattr(AIService, "chat_response", guidance)
    answer = client.post("/ai/chat", json={"message": "كيف أتنقل بين الصفحات؟"})
    assert answer.get_json()["response"] == "شرح محلي"


def test_nlu_worker_classifies_intent_and_extracts_reference():
    from services.assistant_nlu_worker import create_app

    with create_app().test_client() as worker:
        result = worker.post(
            "/interpret",
            json={"message": "اريد معرفة حالة الفاتورة S-123"},
        ).get_json()
    assert result["intent"] == "get_invoice_status"
    assert result["confidence"] > 0.65
    assert result["entities"]["references"] == ["S-123"]

    with create_app().test_client() as worker:
        purchase = worker.post(
            "/interpret",
            json={"message": "أريد إنشاء أمر شراء، اسم العميل: شركة النور، كمية ٣، SKU-20، 2027-01-10"},
        ).get_json()
    assert purchase["intent"] == "create_purchase_order"
    assert purchase["entities"] == {
        "references": ["SKU-20"],
        "dates": ["2027-01-10"],
        "quantities": ["٣"],
        "names": ["شركة النور"],
    }



def test_quote_preview_and_replayed_confirmation_create_one_draft(
    client, login_owner, db, test_customer, test_product,
):
    from models import Currency, Warehouse
    from models.erp_modules import Quotation
    from services.currency_service import CurrencyService

    currency_code = CurrencyService.get_base_currency()
    currency = Currency.query.filter_by(code=currency_code).first()
    if currency is None:
        db.session.add(Currency(code=currency_code, name="Base currency", is_active=True))
    else:
        currency.is_active = True
    warehouse = Warehouse(name="مستودع العرض", code="WH-Q1", is_active=True)
    db.session.add(warehouse)
    test_product.sku = "SKU-Q1"
    test_product.regular_price = 50
    db.session.commit()

    command = {
        "message": f"عرض سعر: #{test_customer.id} | SKU-Q1 | 2 | WH-Q1 | {currency_code}"
    }
    headers = {"Idempotency-Key": str(uuid4())}
    proposal = client.post("/ai/chat", json=command, headers=headers)
    assert proposal.status_code == 200
    draft = proposal.get_json()
    assert draft["action_status"] == "pending", draft
    assert "100.000" in draft["response"]
    assert Quotation.query.count() == 0

    try_again = client.post("/ai/chat", json=command, headers=headers)
    assert try_again.get_json() == draft
    confirmed = client.post(draft["confirm_url"])
    assert confirmed.status_code == 200, confirmed.get_json()
    assert confirmed.get_json()["action_status"] == "confirmed"
    assert client.post(draft["confirm_url"]).get_json() == confirmed.get_json()
    quote = Quotation.query.one()
    assert quote.status == "draft"
    assert quote.warehouse_id == warehouse.id
    assert quote.total_amount == 100
    assert quote.lines[0].quantity == 2
    assert quote.converted_sale_id is None


def test_quote_rejects_nonpositive_quantity_without_a_proposal(client, login_owner):
    result = client.post(
        "/ai/chat",
        json={"message": "عرض سعر: النور | SKU-1 | 0 | WH-1 | ILS"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert "أكبر من صفر" in result.get_json()["response"]
    assert AssistantAction.query.count() == 0



def excel_upload(rows):
    from io import BytesIO

    from openpyxl import Workbook

    book = Workbook()
    book.active.append(["اسم المنتج", "رقم القطعة", "السعر", "التكلفة", "الكمية"])
    for row in rows:
        book.active.append(row)
    content = BytesIO()
    book.save(content)
    content.seek(0)
    return content


def test_excel_confirmation_posts_stock_and_gl_once(client, login_owner, db, monkeypatch):
    from io import BytesIO

    from models import Currency, GLJournalEntry, Product, StockMovement, Tenant, Warehouse
    from services.fiscal_period_guard import ensure_current_period

    company = Tenant(
        name="Import company", name_ar="شركة الاستيراد", slug="stock-import-tenant", default_currency="ILS"
    )
    currency = Currency.query.filter_by(code="ILS").first()
    if currency is None:
        db.session.add(Currency(code="ILS", name="ILS", is_active=True))
    else:
        currency.is_active = True
    db.session.add(company)
    db.session.flush()
    warehouse = Warehouse(name="مستودع استيراد", tenant_id=company.id, is_active=True)
    db.session.add(warehouse)
    ensure_current_period(tenant_id=company.id)
    db.session.commit()
    with client.session_transaction() as session:
        session["impersonate_tenant_id"] = company.id

    content = excel_upload([["قطعة مستوردة", "IMP-101", 32, 8, 2.5]]).getvalue()
    key = str(uuid4())

    def upload(data):
        return client.post(
            "/ai/upload-excel",
            data={"file": (BytesIO(data), "stock.xlsx"), "warehouse_id": warehouse.id},
            headers={"Idempotency-Key": key},
        )

    initial = upload(content)
    assert initial.status_code == 200, initial.get_json()
    draft = initial.get_json()
    assert draft["action_status"] == "pending"
    assert "20.000" in draft["response"]
    assert upload(content).get_json() == draft
    different = excel_upload([["قطعة مستوردة", "IMP-101", 32, 8, 3]]).getvalue()
    assert upload(different).status_code == 409
    product_query = Product.query.filter_by(part_number="IMP-101")
    assert product_query.count() == 0

    from services.stock_service import StockService

    original_post = StockService.post_adjustment_gl

    def fail_after_journal(*args, **kwargs):
        original_post(*args, **kwargs)
        raise RuntimeError("test failure after stock and journal flushes")

    with monkeypatch.context() as temporary:
        temporary.setattr(StockService, "post_adjustment_gl", fail_after_journal)
        assert client.post(draft["confirm_url"]).status_code == 500
    assert product_query.count() == 0
    assert StockMovement.query.count() == 0
    assert GLJournalEntry.query.count() == 0
    assert db.session.get(AssistantAction, key).status == "pending"

    confirmed = client.post(draft["confirm_url"])
    assert confirmed.status_code == 200, confirmed.get_json()
    assert client.post(draft["confirm_url"]).get_json() == confirmed.get_json()
    product = product_query.one()
    movements = StockMovement.query.filter_by(product_id=product.id).all()
    assert product.current_stock == movements[0].quantity
    assert float(product.current_stock) == 2.5
    assert len(movements) == 1
    journal = GLJournalEntry.query.filter_by(
        reference_type="stock_adjustment", reference_id=movements[0].id
    ).one()
    assert sum(line.debit for line in journal.lines) == 20


def test_excel_rejects_invalid_stock_before_creating_a_draft(client, login_owner, db):
    from models import Warehouse

    warehouse = Warehouse(name="مستودع التحقق", is_active=True)
    db.session.add(warehouse)
    db.session.commit()
    response = client.post(
        "/ai/upload-excel",
        data={
            "file": (excel_upload([["فلتر", "X-001", 15, 4, -2]]), "stock.xlsx"),
            "warehouse_id": warehouse.id,
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 400
    assert "السطر 2" in response.get_json()["response"]
    assert AssistantAction.query.count() == 0



def test_purchase_dialog_recovers_steps_and_creates_one_draft(client, login_owner, db, test_product):
    from models import Currency, StockMovement, Supplier, Warehouse
    from models.erp_modules import PurchaseOrder
    from services.currency_service import CurrencyService

    currency = CurrencyService.get_base_currency()
    currency_row = Currency.query.filter_by(code=currency).first()
    if currency_row:
        currency_row.is_active = True
    else:
        db.session.add(Currency(code=currency, name=currency, is_active=True))
    warehouse = Warehouse(name="مستودع الشراء", code="WH-PO", is_active=True)
    suppliers = [Supplier(name="شركة القطع"), Supplier(name="شركة القطع")]
    test_product.sku = "SKU-PO"
    db.session.add_all([warehouse, *suppliers])
    db.session.commit()

    command = {"message": "أنشئ أمر شراء"}
    headers = {"Idempotency-Key": str(uuid4())}
    started = client.post("/ai/chat", json=command, headers=headers)
    assert started.status_code == 200, started.get_json()
    draft = started.get_json()
    assert draft["action_status"] == "po_supplier", draft
    ambiguous = client.post(draft["collect_url"], json={"message": "شركة القطع"})
    assert ambiguous.status_code == 400
    assert all(f"#{supplier.id}" in ambiguous.get_json()["response"] for supplier in suppliers)
    supplier_answer = {"message": f"#{suppliers[0].id}"}
    warehouse_step = client.post(draft["collect_url"], json=supplier_answer).get_json()
    assert warehouse_step["action_status"] == "po_warehouse"
    assert client.post(draft["collect_url"], json=supplier_answer).get_json() == warehouse_step

    db.session.remove()
    assert client.get("/ai/chat/actions/pending").get_json()["actions"] == [warehouse_step]
    items_step = client.post(warehouse_step["collect_url"], json={"message": "WH-PO"}).get_json()
    assert items_step["multiline"] is True
    bad_quantity = client.post(items_step["collect_url"], json={"message": "SKU-PO | -4 | 12"})
    assert bad_quantity.status_code == 400
    delivery_step = client.post(
        items_step["collect_url"], json={"message": "SKU-PO | 4 | 12.250"}
    ).get_json()
    assert delivery_step["action_status"] == "po_delivery"
    bad_date = client.post(delivery_step["collect_url"], json={"message": "2026-02-30"})
    assert bad_date.status_code == 400
    pending = client.post(delivery_step["collect_url"], json={"message": "تخطي"}).get_json()
    assert pending["action_status"] == "pending"
    assert "49.000" in pending["response"]
    assert PurchaseOrder.query.count() == 0

    posted = client.post(pending["confirm_url"])
    assert posted.status_code == 200, posted.get_json()
    assert client.post(pending["confirm_url"]).get_json() == posted.get_json()
    order = PurchaseOrder.query.one()
    assert order.status == "draft"
    assert order.total_amount == 49
    assert order.currency == currency
    assert order.purchase_id is None
    assert StockMovement.query.count() == 0



def test_concurrent_confirmation_claims_the_action_once(client, login_owner, app, db, tmp_path):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing
    from threading import Barrier

    from sqlalchemy import create_engine

    name = "تأكيد متزامن"
    started = client.post(
        "/ai/chat",
        json={"message": f"أضف عميل: {name}"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    url = started.get_json()["confirm_url"]
    cookie_name = app.config["SESSION_COOKIE_NAME"]
    cookie = client.get_cookie(cookie_name).value
    original_engine = db.engine
    if original_engine.dialect.name != "sqlite":
        import pytest

        pytest.skip("The test copies the isolated SQLite fixture into a two-connection database.")
    db.session.remove()
    disk = tmp_path / "concurrent-actions.db"
    with original_engine.connect() as source, closing(sqlite3.connect(disk)) as destination:
        source.connection.driver_connection.backup(destination)

    competing_engine = create_engine(f"sqlite:///{disk.as_posix()}")
    barrier = Barrier(2)

    def send():
        other = app.test_client()
        other.set_cookie(cookie_name, cookie)
        barrier.wait(timeout=5)
        result = other.post(url)
        return result.status_code, result.get_json()

    db.engines[None] = competing_engine
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(send)
            second = workers.submit(send)
            responses = first.result(timeout=15), second.result(timeout=15)
        assert responses[0] == responses[1]
        assert responses[0][0] == 200
        assert responses[0][1]["action_status"] == "confirmed"
        assert Customer.query.filter_by(name=name).count() == 1
    finally:
        db.session.remove()
        db.engines[None] = original_engine
        competing_engine.dispose()
