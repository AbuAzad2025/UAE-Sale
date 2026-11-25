"""Opt-in mixed workload against a disposable PostgreSQL test database."""

from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from os import environ
from time import monotonic, sleep
from uuid import uuid4

import pytest
from openpyxl import Workbook
from sqlalchemy import select, text, update

from bot_core.agent import AgentRunner
from bot_core.agent.deadline import sql_deadline
from bot_core.agent.erp import build_registry
from bot_core.dialogue import StateManager
from bot_core.gateway import MessageEvent
from bot_core.gateway.store import submit
from bot_core.observability import utcnow
from bot_core.observability.queue_metrics import summarize
from bot_core.security import Actor
from bot_core.worker import work_one
from models import Currency, Customer, GLJournalEntry, StockMovement, Tenant, User, Warehouse
from models.bot_event import BotEvent, BotEventAudit
from models.journal_entry_audit import JournalEntryAudit
from services.fiscal_period_guard import ensure_current_period


@pytest.mark.skipif(environ.get("BOT_QUEUE_LOAD_TEST") != "1", reason="Opt-in PostgreSQL mixed workload")
def test_reports_and_large_excel_workbooks_share_agent_queue(app, db, owner_user, tmp_path, monkeypatch):
    import ai_knowledge

    monkeypatch.setattr(ai_knowledge, "AI_KNOWLEDGE_DIR", str(tmp_path))
    assert db.engine.dialect.name == "postgresql"
    company = Tenant(name="Queue load test", name_ar="شركة اختبار الحمل", slug="queue-load", default_currency="AED")
    db.session.add(company)
    db.session.flush()
    company_id = company.id
    currency = db.session.scalar(select(Currency).where(Currency.code == "AED"))
    if currency is None:
        db.session.add(Currency(code="AED", name="Dirham", is_active=True))
    else:
        currency.is_active = True
    ensure_current_period(tenant_id=company_id)
    warehouse = Warehouse(name="Load warehouse", code="LOAD", tenant_id=company_id)
    customer = Customer(name="Load customer", tenant_id=company_id)
    people = [User(username=f"bench-{n}", email=f"bench-{n}@example.invalid", password_hash="disabled",
                   role_id=owner_user.role_id, tenant_id=company_id, is_owner=False) for n in range(9)]
    db.session.add_all([warehouse, customer, *people])
    db.session.flush()
    warehouse_id = warehouse.id
    actor = Actor(owner_user.id, company_id)
    readers = [Actor(person.id, company_id) for person in people]
    db.session.execute(text("SET LOCAL statement_timeout = '120s'"))
    db.session.execute(text("""
        INSERT INTO sales (tenant_id, sale_number, customer_id, seller_id, sale_date, total_amount, currency,
                           amount_base, payment_status, status, is_active, created_at)
        SELECT :tenant, 'BENCH-' || n, :customer, :seller,
               CURRENT_DATE - (n % 45) * INTERVAL '1 day', 12, 'AED', 12, 'unpaid', 'confirmed', true, CURRENT_TIMESTAMP
        FROM generate_series(1, 200000) AS n
    """), {"tenant": company_id, "customer": customer.id, "seller": actor.user_id})
    db.session.commit()
    db.session.execute(text("ANALYZE sales"))
    db.session.commit()

    def send(principal, message, command=None):
        key = str(uuid4())
        submit(MessageEvent.receive(key, message, principal, command=command))
        return key

    def workbook(rows):
        book = Workbook(write_only=True)
        sheet = book.create_sheet()
        sheet.append(["اسم المنتج", "رقم القطعة", "السعر", "التكلفة", "الكمية"])
        for index in range(rows):
            sheet.append([f"Bench product {rows}-{index}", f"BENCH-{rows}-{index}", 20, 10, 1])
        file = BytesIO()
        book.save(file)
        return b64encode(file.getvalue()).decode("ascii")

    def upload(rows):
        return send(actor, f"workbook-{rows}", {"tool": "prepare_stock_import", "arguments": {
            "content": workbook(rows), "warehouse_id": warehouse_id,
        }})

    def load(ids, *, reserve):
        db.session.execute(update(BotEvent).where(BotEvent.id.in_(ids)).values(available_at=utcnow()))
        db.session.commit()

        def drain(interactive_only):
            runner = AgentRunner(build_registry(), deadline=sql_deadline, budget_ms=90000)
            cutoff = monotonic() + 150
            while monotonic() < cutoff:
                if work_one(app, runner, StateManager(), interactive_only=interactive_only):
                    continue
                with app.app_context():
                    waiting = db.session.scalar(select(BotEvent.id).where(
                        BotEvent.id.in_(ids), BotEvent.status.in_(("queued", "processing")),
                    ).limit(1))
                if waiting is None:
                    return
                sleep(0.02)
            pytest.fail("The mixed queue did not drain within 150 seconds")

        with ThreadPoolExecutor(max_workers=2 if reserve else 1) as workers:
            jobs = [workers.submit(drain, False)]
            if reserve:
                jobs.append(workers.submit(drain, True))
            for job in jobs:
                job.result()
        db.session.expire_all()
        results = {key: db.session.get(BotEvent, key).result for key in ids}
        details = db.session.scalars(select(BotEventAudit.details).where(
            BotEventAudit.event_id.in_(ids), BotEventAudit.outcome.in_(("completed", "failed")),
        )).all()
        measurements = summarize(details)
        print(f"{'reserved worker' if reserve else 'single worker'}: {measurements}", flush=True)
        return results, measurements

    def reports():
        return [send(reader, "قارن مبيعات هذا الشهر والشهر الماضي") for reader in readers[:8]]

    max_upload = upload(1000)
    oversized = upload(1001)
    report_ids = reports()
    results, _ = load([max_upload, oversized, *report_ids], reserve=False)
    assert results[max_upload]["outcome"] == "proposed"
    assert results[oversized]["outcome"] == "invalid"
    assert "1000" in results[oversized]["message"]
    assert all(results[key]["outcome"] == "read" for key in report_ids)

    confirmation = send(actor, "confirm workload workbook", {"tool": "confirm_action", "arguments": {
        "action_id": results[max_upload]["data"]["action_id"],
    }})
    report_ids = reports()
    fast_check = send(readers[-1], "حالة فاتورة BENCH-1")
    results, measurements = load([confirmation, *report_ids, fast_check], reserve=True)
    assert results[confirmation]["outcome"] == "confirmed"
    assert all(results[key]["outcome"] == "read" for key in [*report_ids, fast_check])
    assert StockMovement.query.filter_by(tenant_id=company_id).count() == 1000
    assert GLJournalEntry.query.filter_by(tenant_id=company_id, is_posted=True).count() == 1000
    assert JournalEntryAudit.query.filter_by(tenant_id=company_id, performed_by=actor.user_id).count() == 1000
    assert measurements["sales_report"]["timeouts"] == 0
    assert measurements["sales_report"]["queue_ms"]["max"] < 5000
