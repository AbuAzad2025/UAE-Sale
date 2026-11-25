from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from bot_core.agent import AgentRunner
from bot_core.agent.deadline import sql_deadline
from bot_core.agent.erp import build_registry
from bot_core.dialogue import StateManager
from bot_core.dialogue.routing import decide, from_prediction
from bot_core.gateway import MessageEvent, normalize
from bot_core.gateway.store import claim_next, finish, read, submit
from bot_core.neural_nlu import Prediction
from bot_core.neural_nlu.providers import OptionalExternalProvider
from bot_core.observability import utcnow
from bot_core.security import Actor
from bot_core.worker import work_one
from models import Customer, Tenant
from models.bot_event import BotEvent, BotEventAudit


@pytest.fixture(autouse=True)
def enable_agent_queue(app, monkeypatch):
    monkeypatch.setitem(app.config, "BOT_QUEUE_ENABLED", True)


def test_disabled_agent_rejects_new_queue_items(app, client, login_owner, monkeypatch):
    monkeypatch.setitem(app.config, "BOT_QUEUE_ENABLED", False)
    response = client.post("/ai/chat/events", json={"message": "رصيد عميل"},
                           headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 503
    assert client.get("/ai/chat/events").status_code == 200


def test_normalization_preserves_codes_and_decimal_punctuation():
    assert normalize("  مَخزون   SKU-٧ | ۲.۵ ") == "مخزون sku-7 | 2.5"
    event = MessageEvent.receive(str(uuid4()), "look up payment for invoice INV-3024", Actor(1, 2))
    decision = decide(event, None)
    assert decision.call.name == "get_invoice_status"
    assert decision.call.arguments == {"reference": "INV-3024"}


def test_neural_invoice_routing_uses_a_unique_explicit_invoice_code():
    message = "Is INV-184 paid yet?"
    fallback = decide(MessageEvent.receive(str(uuid4()), message, Actor(1, 2)), None)
    prediction = Prediction("get_invoice_status", 0.98, {}, {"reference": ["paid", "inv-184"]})
    decision = from_prediction(prediction, 0.75, fallback, message=message)
    assert decision.call.arguments == {"reference": "inv-184"}
    assert from_prediction(prediction, 0.75, fallback, message="Were INV-184 and INV-185 paid?").call is None


def test_optional_provider_skips_transport_by_default_and_when_key_is_missing():
    calls = []
    adapter = OptionalExternalProvider(lambda: None, lambda payload: calls.append(payload))
    assert adapter.answer("question") is None
    assert adapter.answer("question", selected=True) is None
    assert not calls


def _enqueue(client, message, key=None, **extra):
    response = client.post(
        "/ai/chat/events", json={"message": message, **extra},
        headers={"Idempotency-Key": key or str(uuid4())},
    )
    assert response.status_code == 202
    return response.get_json()


def _due(session, event_id):
    session.execute(
        update(BotEvent).where(BotEvent.id == event_id).values(available_at=utcnow() - timedelta(seconds=1))
    )
    session.commit()


def _process(app, db, client, queued, runner=None):
    _due(db.session, queued["id"])
    assert work_one(app, runner or AgentRunner(build_registry(), deadline=sql_deadline), StateManager())
    return client.get(queued["status_url"]).get_json()["result"]


def _confirm(client, result, key=None):
    response = client.post(result["confirm_url"], headers={"Idempotency-Key": key or str(uuid4())})
    assert response.status_code == 202
    return response.get_json()


def test_queue_has_persistent_slots_and_can_create_one_confirmed_customer(
    app, db, client, login_owner, monkeypatch,
):
    # This worker path must never make a network request, even with provider keys configured.
    import requests

    def unexpected_network(*args, **kwargs):
        raise AssertionError("The local worker attempted an HTTP request.")

    monkeypatch.setattr(requests.Session, "request", unexpected_network)
    monkeypatch.setitem(app.config, "BOT_QUEUE_ENABLED", True)
    assert b'id="ai-mode-agent"' in client.get("/ai/assistant").data
    runner = AgentRunner(build_registry(), deadline=sql_deadline)
    key = str(uuid4())
    first = _enqueue(client, "أضف عميل", key, user_id=-1, tenant_id=-1)
    assert _enqueue(client, "أضف عميل", key)["id"] == first["id"]
    assert [event["id"] for event in client.get("/ai/chat/events").get_json()["events"]] == [first["id"]]
    assert client.post(
        "/ai/chat/events", json={"message": "different"}, headers={"Idempotency-Key": key}
    ).status_code == 409
    _due(db.session, first["id"])
    assert work_one(app, runner, StateManager())
    assert client.get(first["status_url"]).get_json()["result"]["outcome"] == "clarification"

    second = _enqueue(client, "عميل من الوكيل")
    _due(db.session, second["id"])
    db.session.remove()
    assert work_one(app, runner, StateManager())
    result = client.get(second["status_url"]).get_json()["result"]
    assert result["outcome"] == "proposed"
    assert Customer.query.filter_by(name="عميل من الوكيل").count() == 0
    confirmation_key = str(uuid4())
    confirmation = _confirm(client, result, confirmation_key)
    assert _confirm(client, result, confirmation_key)["id"] == confirmation["id"]
    assert Customer.query.filter_by(name="عميل من الوكيل").count() == 0
    assert _process(app, db, client, confirmation)["outcome"] == "confirmed"
    assert Customer.query.filter_by(name="عميل من الوكيل").count() == 1

    audits = db.session.scalars(
        select(BotEventAudit).where(BotEventAudit.event_id == second["id"]).order_by(BotEventAudit.id)
    ).all()
    assert [entry.outcome for entry in audits] == ["queued", "processing", "completed"]
    assert audits[0].details["raw_input"] == "عميل من الوكيل"
    assert audits[-1].details["tools"] == ["draft_customer"]


def test_expired_claim_is_recovered_and_stale_worker_cannot_publish(db):
    actor = Actor(812, 14)
    item = MessageEvent.receive(str(uuid4()), "inventory", actor)
    submit(item)
    _due(db.session, item.id)
    first = claim_next()
    assert first is not None
    assert claim_next() is None
    db.session.execute(
        update(BotEvent).where(BotEvent.id == item.id).values(lease_until=utcnow() - timedelta(seconds=1))
    )
    db.session.commit()
    second = claim_next()
    assert second is not None and second.token != first.token
    assert not finish(first, outcome="completed", result={"message": "stale"}, trace={})
    assert finish(second, outcome="completed", result={"message": "recovered"}, trace={})
    assert read(item.id, actor).result["message"] == "recovered"
    assert read(item.id, Actor(812, 15)) is None


def test_low_confidence_and_timed_out_inference_leave_the_worker_available(app, db, client, login_owner):
    class Uncertain:
        def predict(self, message):
            return Prediction("draft_customer", 0.22, {"draft_customer": 0.22}, {"customer": ["غير مؤكد"]})

    class TimedOut:
        def predict(self, message):
            raise TimeoutError()

    runner = AgentRunner(build_registry())
    states = StateManager()
    for interpreter in (Uncertain(), TimedOut()):
        job = _enqueue(client, "استفسار")
        _due(db.session, job["id"])
        assert work_one(app, runner, states, interpreter)
        assert client.get(job["status_url"]).get_json()["result"]["outcome"] == "clarification"
    assert Customer.query.filter_by(name="غير مؤكد").count() == 0
    assert db.session.scalar(select(BotEventAudit).where(
        BotEventAudit.event_id == job["id"], BotEventAudit.outcome == "completed",
    )).details["inference"] == "timeout"


def test_worker_rechecks_permissions_before_resolving_entities(app, db, client, login_seller, seller_user):
    company = Tenant(name="Queue test tenant", name_ar="شركة اختبار", slug="queue-test")
    db.session.add(company)
    db.session.flush()
    seller_user.tenant_id = company.id
    seller_user.role.permissions.clear()
    db.session.commit()
    event = _enqueue(client, "رصيد عميل لا يجب البحث عنه")
    _due(db.session, event["id"])
    assert work_one(app, AgentRunner(build_registry()), StateManager())
    result = client.get(event["status_url"]).get_json()["result"]
    assert result["outcome"] == "denied"
    audit = db.session.scalar(select(BotEventAudit).where(
        BotEventAudit.event_id == event["id"], BotEventAudit.outcome == "completed",
    ))
    assert audit.details["tools"] == []


def test_cancel_prevents_confirmation_of_the_active_preview(app, db, client, login_owner):
    runner = AgentRunner(build_registry())
    states = StateManager()
    draft = _enqueue(client, "أضف عميل: عميل ملغى")
    _due(db.session, draft["id"])
    assert work_one(app, runner, states)
    confirm_url = client.get(draft["status_url"]).get_json()["result"]["confirm_url"]
    cancellation = _enqueue(client, "إلغاء")
    _due(db.session, cancellation["id"])
    assert work_one(app, runner, StateManager())
    assert client.get(cancellation["status_url"]).get_json()["result"]["outcome"] == "reset"
    confirmation = _confirm(client, {"confirm_url": confirm_url})
    assert _process(app, db, client, confirmation)["outcome"] == "cancelled"
    assert Customer.query.filter_by(name="عميل ملغى").count() == 0


def _tenant_context(db, client):
    from models import Currency

    company = Tenant(name="Agent workflow tenant", name_ar="شركة الوكيل", slug="agent-workflow", default_currency="AED")
    db.session.add(company)
    currency = db.session.scalar(select(Currency).where(Currency.code == "AED"))
    if currency is not None:
        currency.is_active = True
    else:
        db.session.add(Currency(code="AED", name="Dirham", is_active=True))
    db.session.commit()
    with client.session_transaction() as session:
        session["impersonate_tenant_id"] = company.id
    return company


def test_quick_questions_use_tenant_reports_in_agent_mode(app, db, client, login_owner):
    for question in ("كم عدد العملاء؟", "كم عدد المبيعات اليوم؟"):
        outcome = _process(app, db, client, _enqueue(client, question))
        assert outcome["outcome"] == "clarification" and "اختر شركة" in outcome["message"]
    company = _tenant_context(db, client)
    db.session.add_all([Customer(name="Current", tenant_id=company.id), Customer(name="Platform only")])
    db.session.commit()
    questions = {
        "كم عدد العملاء؟": "العملاء النشطون في الشركة الحالية: 1.",
        "ما حالة المخزون؟": "المخزون في الشركة الحالية:",
        "كم عدد المصروفات هذا الشهر؟": "مصروفات هذا الشهر في الشركة الحالية:",
        "كم عدد الشيكات؟": "الشيكات المسجلة في الشركة الحالية:",
        "ما حالة الفترات المالية؟": "الفترات المالية في الشركة الحالية:",
    }
    for question, expected in questions.items():
        result = _process(app, db, client, _enqueue(client, question))
        assert result["outcome"] == "read" and expected in result["message"], (question, result)


def test_sales_question_and_relative_period_in_agent_mode(app, db, client, login_owner):
    _tenant_context(db, client)
    turns = (
        ("كيف كانت مبيعات الشهر الماضي؟", "الشهر الماضي", "read"),
        ("وما قبلها؟", "الشهر الذي قبل الماضي", "read"),
        ("كيف كانت مبيعات اليوم؟", "اليوم", "read"),
        ("وما قبلها؟", "أمس", "read"),
        ("قارن مبيعات اليوم وأمس", "المبيعات اليوم", "read"),
        ("وما قبلها؟", "أي فترة تقصد", "clarification"),
    )
    for question, expected, outcome in turns:
        result = _process(app, db, client, _enqueue(client, question))
        assert result["outcome"] == outcome and expected in result["message"], (question, result)


def test_customer_invoice_and_stock_follow_ups_use_scoped_live_records(app, db, client, login_owner, owner_user):
    from models import Product, Sale, SaleLine

    company = _tenant_context(db, client)
    other_company = Tenant(name="Outside context", name_ar="شركة أخرى", slug="agent-outside")
    db.session.add(other_company)
    db.session.flush()
    customer = Customer(name="عميل السياق", tenant_id=company.id, balance=37)
    product = Product(name="صنف السياق", sku="CXT-ONE", tenant_id=company.id, current_stock=8, regular_price=10)
    extra = Product(name="صنف إضافي", sku="CXT-TWO", tenant_id=company.id, current_stock=0, regular_price=10)
    foreign = Product(name="صنف محجوب", sku="CXT-FOREIGN", tenant_id=other_company.id, current_stock=99, regular_price=10)
    db.session.add_all([customer, product, extra, foreign])
    db.session.flush()
    sale = Sale(
        tenant_id=company.id, sale_number="CTX-INV", seller_id=owner_user.id, customer_id=customer.id,
        total_amount=50, amount_base=100, paid_amount_base=60, balance_due=40,
        currency="USD", exchange_rate=2, payment_status="partial", status="confirmed",
    )
    db.session.add(sale)
    db.session.flush()
    db.session.add_all([
        SaleLine(tenant_id=company.id, sale_id=sale.id, product_id=item.id, quantity=1, unit_price=10, line_total=10)
        for item in (product, foreign)
    ])
    db.session.commit()
    customer_id, sale_id, product_id, extra_id, foreign_id = customer.id, sale.id, product.id, extra.id, foreign.id

    def reply(message, expected, outcome="read"):
        result = _process(app, db, client, _enqueue(client, message))
        assert result["outcome"] == outcome and expected in result["message"], (message, result)
        return result["message"]

    reply(f"كم رصيد العميل #{customer_id}؟", "رصيد عميل السياق")
    reply("ما آخر فاتورة له؟", "CTX-INV")
    reply("قديش ضل عليها؟", "40.00 AED")
    reply("كم بقي عليها من الضريبة؟", "حدّد المطلوب", "clarification")
    reply("ما آخر فاتورة لأحمد؟", "حدّد المطلوب", "clarification")
    reply("كم رصيد عميلها؟", "رصيد عميل السياق")
    reply(f"حالة فاتورة #{sale_id}", "مدفوعة جزئيًا")
    reply("هل الصنف الموجود فيها متوفر؟", "صنف السياق متوفر")
    db.session.execute(update(Product).where(Product.id == product_id).values(current_stock=0))
    db.session.commit()
    reply("هل هو متوفر؟", "صنف السياق غير متوفر")
    reply(f"حالة فاتورة #{sale_id}", "CTX-INV")
    db.session.add(SaleLine(
        tenant_id=company.id, sale_id=sale_id, product_id=extra_id, quantity=1, unit_price=10, line_total=10,
    ))
    db.session.commit()
    options = reply("مخزون الأصناف اللي فيها؟", "صنف إضافي", "ambiguous")
    assert "صنف محجوب" not in options
    reply(f"#{foreign_id}", "أرسل رقم السجل من القائمة السابقة", "clarification")
    reply(str(extra_id), "صنف إضافي غير متوفر")
    with client.session_transaction() as session:
        session["impersonate_tenant_id"] = other_company.id
    reply("هل هو متوفر؟", "حدّد المطلوب", "clarification")
    with client.session_transaction() as session:
        session["impersonate_tenant_id"] = company.id
    reply("إلغاء", "ألغيت", "reset")
    reply("هل هو متوفر؟", "حدّد المطلوب", "clarification")


def test_related_customer_invoice_read_requires_both_permissions():
    class Principal:
        id = 1
        is_authenticated = True

        def has_permission(self, code):
            return code == "view_reports"

    tool = build_registry().get("get_latest_customer_invoice")
    with pytest.raises(PermissionError):
        tool.authorize(Actor(1, 2), Principal())


def test_sales_prediction_needs_a_sales_subject():
    message = "ما حالة الحساب؟"
    event = MessageEvent.receive(str(uuid4()), message, Actor(1, 2))
    fallback = decide(event, None)
    prediction = Prediction("sales_report", 0.99, {}, {})
    assert from_prediction(prediction, 0.85, fallback, message=message).call is None


def test_purchase_resumes_and_confirms_in_the_queue(app, db, client, login_owner):
    from models import Product, Supplier, Warehouse
    from models.erp_modules import PurchaseOrder

    company = _tenant_context(db, client)
    db.session.add_all([
        Supplier(name="مورد الاختبار", tenant_id=company.id),
        Warehouse(name="مستودع الاختبار", code="WH-AG", tenant_id=company.id),
        Product(name="صنف الاختبار", sku="SKU-AG", regular_price=25, tenant_id=company.id),
    ])
    db.session.commit()

    def reply(message):
        return _process(app, db, client, _enqueue(client, message))

    first = reply("أمر شراء")
    assert first["outcome"] == "clarification", [
        audit.details for audit in db.session.scalars(select(BotEventAudit).where(BotEventAudit.outcome == "completed"))
    ]
    assert "المستودع" in reply("مورد الاختبار")["message"]
    clarification = reply("ماذا تقصد؟")
    assert clarification["outcome"] == "clarification" and "المستودع" in clarification["message"]
    assert "المستودع" in reply("أمر شراء")["message"]
    assert reply("مخزون الصنف SKU-AG")["outcome"] == "read"
    db.session.remove()
    assert "كل صنف" in reply("WH-AG")["message"]
    assert "التسليم" in reply("SKU-AG | 2 | 15.5")["message"]
    proposal = reply("تخطي")
    assert proposal["outcome"] == "proposed"
    assert "AED" in proposal["message"]
    assert PurchaseOrder.query.count() == 0
    assert _process(app, db, client, _confirm(client, proposal))["outcome"] == "confirmed"
    assert _process(app, db, client, _confirm(client, proposal))["outcome"] == "confirmed"
    order = PurchaseOrder.query.one()
    assert order.tenant_id == company.id
    assert order.status == "draft" and order.currency == "AED"


def test_queued_workbook_and_confirmation_post_once_with_actor(app, db, client, login_owner, owner_user, monkeypatch):
    from io import BytesIO

    from openpyxl import Workbook

    from models import GLJournalEntry, Product, StockMovement, Warehouse
    from services.fiscal_period_guard import ensure_current_period
    from services.stock_service import StockService

    company = _tenant_context(db, client)
    warehouse = Warehouse(name="مستودع Excel للوكيل", tenant_id=company.id)
    db.session.add(warehouse)
    ensure_current_period(tenant_id=company.id)
    db.session.commit()
    book = Workbook()
    book.active.append(["اسم المنتج", "رقم القطعة", "السعر", "التكلفة", "الكمية"])
    book.active.append(["قطعة للوكيل", "AG-01", 32, 8, 2.5])
    file = BytesIO()
    book.save(file)
    file.seek(0)
    uploaded = client.post(
        "/ai/upload-excel",
        data={"file": (file, "agent.xlsx"), "warehouse_id": warehouse.id, "agent_queue": "1"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert uploaded.status_code == 202
    job = uploaded.get_json()
    assert Product.query.filter_by(part_number="AG-01").count() == 0
    preview = _process(app, db, client, job)
    assert preview["outcome"] == "proposed"
    assert "20.000" in preview["message"]
    assert db.session.get(BotEvent, job["id"]).command is None
    assert StockMovement.query.count() == 0
    post_journal = StockService.post_adjustment_gl

    def fail_after_posting(*args, **kwargs):
        post_journal(*args, **kwargs)
        raise RuntimeError("test failure after journal flush")

    with monkeypatch.context() as fault:
        fault.setattr(StockService, "post_adjustment_gl", fail_after_posting)
        assert _process(app, db, client, _confirm(client, preview))["outcome"] == "error"
    assert StockMovement.query.count() == 0
    assert GLJournalEntry.query.count() == 0
    assert Product.query.filter_by(part_number="AG-01").count() == 0
    confirmation = _confirm(client, preview)
    assert StockMovement.query.count() == 0
    assert _process(app, db, client, confirmation)["outcome"] == "confirmed"
    assert _process(app, db, client, _confirm(client, preview))["outcome"] == "confirmed"
    movement = StockMovement.query.one()
    assert movement.user_id == owner_user.id and movement.tenant_id == company.id
    journal = GLJournalEntry.query.filter_by(reference_type="stock_adjustment", reference_id=movement.id).one()
    assert journal.tenant_id == company.id and journal.created_by == owner_user.id
    assert sum(line.debit for line in journal.lines) == 20


def test_batch_workbook_rolls_back_and_records_each_stock_adjustment(app, db, client, login_owner, owner_user, monkeypatch):
    from io import BytesIO

    from openpyxl import Workbook

    from models import GLJournalEntry, Product, StockMovement, Warehouse
    from models.journal_entry_audit import JournalEntryAudit
    from services.fiscal_period_guard import ensure_current_period
    from services.gl_service import GLService

    company = _tenant_context(db, client)
    warehouse = Warehouse(name="Batch warehouse", tenant_id=company.id)
    existing = Product(name="Existing part", part_number="BATCH-1", current_stock=4, average_cost=5,
                       regular_price=15, tenant_id=company.id)
    db.session.add_all([warehouse, existing])
    ensure_current_period(tenant_id=company.id)
    db.session.commit()

    workbook = Workbook()
    workbook.active.append(["اسم المنتج", "رقم القطعة", "السعر", "التكلفة", "الكمية"])
    workbook.active.append(["Existing part", "BATCH-1", 15, 8, 2])
    workbook.active.append(["New part", "BATCH-2", 20, 10, 3])
    file = BytesIO()
    workbook.save(file)
    file.seek(0)
    route = client.post("/ai/upload-excel", data={
        "file": (file, "batch.xlsx"), "warehouse_id": warehouse.id, "agent_queue": "1",
    }, headers={"Idempotency-Key": str(uuid4())})
    assert route.status_code == 202
    preview = _process(app, db, client, route.get_json())
    assert preview["outcome"] == "proposed"

    real_post = GLService.post_import_adjustments

    def fail_after_post(*args, **kwargs):
        assert len(real_post(*args, **kwargs)) == 2
        raise TimeoutError("Test expiry after batch journal flush")

    with monkeypatch.context() as fault:
        fault.setattr(GLService, "post_import_adjustments", staticmethod(fail_after_post))
        expired = _process(app, db, client, _confirm(client, preview))
        assert expired["outcome"] == "timeout" and expired["confirm_url"] == preview["confirm_url"]
    db.session.refresh(existing)
    assert existing.current_stock == 4
    assert StockMovement.query.count() == GLJournalEntry.query.count() == JournalEntryAudit.query.count() == 0
    if db.engine.dialect.name == "postgresql":
        with db.engine.begin() as lock:
            lock.execute(select(Warehouse.id).where(Warehouse.id == warehouse.id).with_for_update())
            assert _process(app, db, client, _confirm(client, preview))["outcome"] == "timeout"
        assert StockMovement.query.count() == GLJournalEntry.query.count() == JournalEntryAudit.query.count() == 0
    assert _process(app, db, client, _confirm(client, preview))["outcome"] == "confirmed"
    db.session.refresh(existing)
    assert existing.current_stock == 6 and existing.average_cost == 6
    movements = StockMovement.query.order_by(StockMovement.id).all()
    journals = GLJournalEntry.query.order_by(GLJournalEntry.id).all()
    assert [journal.reference_id for journal in journals] == [move.id for move in movements]
    assert [journal.total_debit for journal in journals] == [16, 30]
    assert all(move.user_id == owner_user.id for move in movements)
    assert JournalEntryAudit.query.filter_by(tenant_id=company.id, performed_by=owner_user.id).count() == 2


def test_low_risk_note_mutation_is_scoped_and_replayed_once(app, db, client, login_owner):
    customer = Customer(name="عميل الملاحظات", notes="ملاحظة سابقة")
    db.session.add(customer)
    db.session.commit()
    key = str(uuid4())
    message = f"ملاحظة عميل #{customer.id}: اتصل يوم الأحد"
    first = _enqueue(client, message, key)
    assert _enqueue(client, message, key)["id"] == first["id"]
    assert _process(app, db, client, first)["outcome"] == "updated"
    assert _enqueue(client, message, key)["status"] == "completed"
    db.session.refresh(customer)
    assert customer.notes == "ملاحظة سابقة\nاتصل يوم الأحد"


def test_worker_uses_the_company_selected_by_platform_admin(app, db, client, login_owner, owner_user):
    company = _tenant_context(db, client)
    owner_user.is_owner = False
    owner_user.role.slug = "super_admin"
    customer = Customer(name="عميل الشركة المحددة", tenant_id=company.id)
    db.session.add(customer)
    db.session.commit()
    event = _enqueue(client, "رصيد العميل: عميل الشركة المحددة")
    result = _process(app, db, client, event)
    assert result["outcome"] == "read" and customer.name in result["message"]


def test_stock_transfer_waits_for_confirmation_and_preserves_inventory(app, db, client, login_owner):
    from models import Product, StockMovement, Warehouse
    from models.erp_modules import StockTransfer

    company = _tenant_context(db, client)
    source = Warehouse(name="مخزن مصدر", code="AG-FROM", tenant_id=company.id)
    target = Warehouse(name="مخزن وجهة", code="AG-TO", tenant_id=company.id)
    product = Product(name="صنف النقل", sku="AG-SKU", regular_price=25, tenant_id=company.id)
    db.session.add_all([source, target, product])
    db.session.flush()
    db.session.add(StockMovement(
        product_id=product.id, warehouse_id=source.id, tenant_id=company.id,
        movement_type="adjustment", quantity=5,
    ))
    db.session.commit()
    request = _enqueue(client, "نقل مخزون: AG-FROM | AG-TO | AG-SKU | ٣")
    preview = _process(app, db, client, request)
    assert preview["outcome"] == "proposed"
    assert StockTransfer.query.count() == 0
    assert _process(app, db, client, _confirm(client, preview))["outcome"] == "confirmed"
    transfer = StockTransfer.query.one()
    assert transfer.tenant_id == company.id and transfer.status == "pending"
    assert transfer.lines[0].quantity == 3
    assert StockMovement.query.count() == 1

    def reply(message):
        return _process(app, db, client, _enqueue(client, message))

    assert "الوجهة" in reply("نقل مخزون: AG-FROM")["message"]
    assert reply("لم أفهم")["outcome"] == "clarification"
    db.session.remove()
    assert "رمز الصنف" in reply("AG-TO")["message"]
    assert "الكمية" in reply("AG-SKU")["message"]
    assert reply("هل يمكنك التوضيح؟")["outcome"] == "clarification"
    resumed = reply("٣")
    assert resumed["outcome"] == "proposed"
    assert all(name in resumed["message"] for name in ("مخزن مصدر", "مخزن وجهة", "صنف النقل"))
