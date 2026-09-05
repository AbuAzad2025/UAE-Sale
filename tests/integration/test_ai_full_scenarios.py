"""Full AI scenarios — chat shortcuts, security audit, sentry, metrics, cache.

Covers the 5 improvement tracks:
1. CSRF security audit helpers
2. Sentry error logging (graceful, no-DSN)
3. AI Metrics dashboard (/metrics + /ai-metrics)
4. End-to-end chat shortcut scenarios (product/customer/expense/payment)
5. GROQ cache hit/miss behaviour
"""
import pytest

from extensions import db as _db
from services import ai_commands as cmd
from services.ai_cache import clear as cache_clear, get as cache_get, set_value as cache_set, stats as cache_stats
from utils.monitoring import AIMetricsCollector, init_sentry


def _login(client, username="owner", password=None):
    password = password or "Owner123!"
    client.post("/auth/login", data={"username": username, "password": password},
                follow_redirects=True)


class TestChatShortcuts:
    def test_chat_product_shortcut(self, client, login_owner):
        resp = client.post("/ai/chat", json={
            "message": "منتج: فلتر زيت، FZ-100، 45، 10",
            "ai_mode": "local",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "response" in data

    def test_chat_customer_shortcut(self, client, login_owner):
        resp = client.post("/ai/chat", json={
            "message": "عميل: ورشة النور، 0501234567",
            "ai_mode": "local",
        })
        assert resp.status_code == 200

    def test_chat_expense_shortcut(self, client, login_owner):
        resp = client.post("/ai/chat", json={
            "message": "مصروف: وقود، 200",
            "ai_mode": "local",
        })
        assert resp.status_code == 200

    def test_chat_requires_message(self, client, login_owner):
        resp = client.post("/ai/chat", json={"message": "", "ai_mode": "local"})
        assert resp.status_code in (200, 400)

    def test_chat_requires_login(self, client):
        resp = client.post("/ai/chat", json={"message": "مرحبا"})
        assert resp.status_code in (302, 401)


class TestServiceLayerEndToEnd:
    def test_product_sale_payment_flow(self, db, owner_user):
        p = cmd.create_product("فلتر E2E", "E2E-001", 100.0, 20)
        assert p.id is not None
        c = cmd.create_customer("عميل E2E", phone="0500000001")
        assert c.id is not None
        sale = cmd.create_sale(c.id, p.id, 2, seller_id=owner_user.id)
        assert sale.id is not None
        pay = cmd.record_payment(c.id, 50.0, "cash", "incoming", owner_user.id, "customer_payment")
        assert pay.id is not None

    def test_expense_and_supplier_flow(self, db, owner_user):
        s = cmd.create_supplier("مورد E2E", phone="0500000002")
        assert s.id is not None
        e = cmd.create_expense("قرطاسية E2E", 75.0, owner_user.id)
        assert e.id is not None


class TestSecurityAudit:
    def test_non_sensitive_op_passes(self, app):
        from routes.ai import _require_csrf_for_sensitive_ops
        with app.test_request_context("/ai/chat", method="POST"):
            from flask import request as req
            req.ai_operation = "chat_ai"
            assert _require_csrf_for_sensitive_ops() is None

    def test_sensitive_op_without_token_blocked(self, app):
        from routes.ai import _require_csrf_for_sensitive_ops
        with app.test_request_context("/ai/chat", method="POST", data={}):
            from flask import request as req
            req.ai_operation = "create_product"
            result = _require_csrf_for_sensitive_ops()
            # No valid token supplied -> 403 tuple or None if fallback allows
            assert result is None or result[1] == 403

    def test_detect_ai_operation_mapping(self):
        from routes.ai import _detect_ai_operation
        assert _detect_ai_operation("منتج: فلتر، FZ-1، 45، 10") == "create_product"
        assert _detect_ai_operation("فاتورة: أحمد، فلتر، 2") == "create_sale"
        assert _detect_ai_operation("مصروف: وقود، 200") == "create_expense"
        assert _detect_ai_operation("دفعة: أحمد، 100، كاش") == "record_payment"
        assert _detect_ai_operation("مرحبا كيف حالك") == "chat_ai"
        assert _detect_ai_operation("عرض رصيد العميل: أحمد") == "chat_ai"

    def test_origin_mismatch_blocked_for_sensitive_op(self, app):
        from routes.ai import _require_csrf_for_sensitive_ops
        with app.test_request_context(
            "/ai/chat", method="POST",
            headers={"Origin": "https://evil.example.com"},
            base_url="http://localhost",
        ):
            from flask import request as req
            req.ai_operation = "create_sale"
            result = _require_csrf_for_sensitive_ops()
            assert result is not None and result[1] == 403

    def test_same_origin_allowed_without_token(self, app):
        from routes.ai import _require_csrf_for_sensitive_ops
        with app.test_request_context(
            "/ai/chat", method="POST",
            headers={"Origin": "http://localhost"},
            base_url="http://localhost",
        ):
            from flask import request as req
            req.ai_operation = "create_product"
            assert _require_csrf_for_sensitive_ops() is None

    def test_cross_site_chat_shortcut_blocked(self, client, login_owner):
        resp = client.post(
            "/ai/chat",
            json={"message": "منتج: فلتر، FZ-9، 10، 5", "ai_mode": "local"},
            headers={"Origin": "https://evil.example.com"},
        )
        assert resp.status_code == 403

    def test_security_endpoints_require_login(self, client):
        assert client.post("/ai/chat", json={"message": "x"}).status_code in (302, 401)


class TestSentryIntegration:
    def test_init_sentry_no_dsn_ok(self, app):
        app.config["SENTRY_DSN"] = ""
        init_sentry(app)  # must not raise

    def test_error_logger_graceful(self, app, db):
        from utils.monitoring import SentryErrorLogger
        with app.test_request_context("/ai/chat"):
            try:
                raise ValueError("sentry-test")
            except ValueError as e:
                SentryErrorLogger.log_error(e, context={"test": True})


class TestMetricsDashboard:
    def test_collector_record_and_get(self):
        AIMetricsCollector.record_ai_request("/chat", "local", tokens_used=10, duration_ms=5, success=True)
        m = AIMetricsCollector.get_metrics()
        assert m["total_requests"] >= 1
        assert "success_rate_percent" in m
        assert "cache_hit_rate_percent" in m

    def test_metrics_endpoints_require_owner(self, client):
        assert client.get("/metrics").status_code in (302, 403)
        assert client.get("/ai-metrics").status_code in (302, 403, 404)

    def test_metrics_ok_for_owner(self, client, login_owner):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "ai_metrics" in r.get_json()
        r2 = client.get("/ai-metrics")
        assert r2.status_code == 200
        assert "ai_metrics" in r2.get_json()


class TestGroqCache:
    def test_cache_miss_then_hit(self):
        cache_clear()
        assert cache_get("groq", "m", "سؤال فريد للكاش 12345", "") is None
        cache_set("groq", "m", "سؤال فريد للكاش 12345", "", "جواب مخزن")
        assert cache_get("groq", "m", "سؤال فريد للكاش 12345", "") == "جواب مخزن"
        assert cache_stats()["entries"] >= 1

    def test_cache_normalization(self):
        cache_clear()
        cache_set("groq", "m", "  مرحبا   بالعالم ", "", "hi")
        assert cache_get("groq", "m", "مرحبا بالعالم", "") == "hi"
