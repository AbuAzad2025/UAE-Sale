"""Unit tests for infra/ops helpers with zero external dependencies.

Covers combined-coverage gaps: utils/database_optimizer.py (0%),
services/elasticsearch_service.py (0%), services/websocket_service.py
(0%), cli_commands.py db-status (33%).
"""
import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from utils.database_optimizer import DatabaseOptimizer
from services.elasticsearch_service import ElasticsearchService


# ── DatabaseOptimizer (SQLite test env: postgres-only paths decline) ─────────

class TestDatabaseOptimizer:
    def test_vacuum_declines_non_postgres(self, db):
        res = DatabaseOptimizer.vacuum_postgres()
        assert res['success'] is False
        assert 'PostgreSQL' in res['message']

    def test_analyze_ok(self, db):
        assert DatabaseOptimizer.analyze_tables() == {'success': True}

    def test_table_sizes_declines_non_postgres(self, db):
        res = DatabaseOptimizer.get_table_sizes()
        assert res['success'] is False

    def test_optimize_all_aggregates(self, db):
        res = DatabaseOptimizer.optimize_all()
        assert set(res) == {'vacuum', 'analyze', 'sizes'}
        assert res['analyze']['success'] is True


# ── ElasticsearchService ──────────────────────────────────────────────────────

def _make_sale(number='S-ES-1', notes='note-es'):
    from models import Sale
    from extensions import db as _db
    s = Sale(sale_number=number, total_amount=Decimal('10'),
             amount_base=Decimal('10'), paid_amount=Decimal('0'),
             paid_amount_base=Decimal('0'), balance_due=Decimal('10'),
             currency='AED', exchange_rate=Decimal('1'),
             payment_status='unpaid', status='confirmed',
             is_active=True, notes=notes)
    _db.session.add(s)
    _db.session.commit()
    return s


class TestElasticsearchService:
    def test_disabled_without_env(self, monkeypatch):
        monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
        assert ElasticsearchService.is_enabled() is False

    def test_enabled_with_env(self, monkeypatch):
        monkeypatch.setenv('ELASTICSEARCH_URL', 'http://localhost:9200')
        assert ElasticsearchService.is_enabled() is True

    def test_index_sale_disabled(self, monkeypatch):
        monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
        res = ElasticsearchService.index_sale({'id': 1})
        assert res['success'] is False

    def test_search_falls_back_when_disabled(self, monkeypatch, db):
        monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
        _make_sale()
        res = ElasticsearchService.search_sales('S-ES-1')
        assert res['success'] is True
        assert res['fallback'] is True
        assert res['total'] == 1

    def test_fallback_empty_query_returns_all(self, monkeypatch, db):
        monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
        _make_sale('S-ES-A')
        _make_sale('S-ES-B')
        res = ElasticsearchService.search_sales('')
        assert res['total'] == 2

    def test_fallback_filters_and_limit(self, monkeypatch, db):
        monkeypatch.delenv('ELASTICSEARCH_URL', raising=False)
        _make_sale('S-ES-C', notes='special-note-xyz')
        res = ElasticsearchService.search_sales(
            'special-note-xyz', filters={'status': 'confirmed'}, limit=5)
        assert res['total'] == 1
        assert res['results'][0]['sale_number'] == 'S-ES-C'


# ── WebSocket service (no server started) ─────────────────────────────────────

class TestWebsocketService:
    def test_broadcasts_noop_without_init(self):
        import services.websocket_service as ws
        old, ws.socketio = ws.socketio, None
        try:
            assert ws.broadcast_sale_created({}) is None
            assert ws.broadcast_payment_received({}) is None
            assert ws.notify_user(1, 'hi') is None
            assert ws.broadcast_stock_alert({}) is None
        finally:
            ws.socketio = old

    def test_broadcasts_delegate_to_socketio(self):
        import services.websocket_service as ws
        fake = MagicMock()
        old, ws.socketio = ws.socketio, fake
        try:
            ws.broadcast_sale_created({'id': 1})
            fake.emit.assert_called_with('sale_created', {'id': 1})
            ws.broadcast_payment_received({'id': 2})
            fake.emit.assert_called_with('payment_received', {'id': 2})
            ws.notify_user(7, 'hello', 'warning')
            fake.emit.assert_called_with(
                'notification', {'message': 'hello', 'type': 'warning'},
                room='user_7')
            ws.broadcast_stock_alert({'sku': 'X'})
            fake.emit.assert_called_with('stock_alert', {'sku': 'X'})
        finally:
            ws.socketio = old

    def test_init_socketio_returns_instance(self, app):
        import services.websocket_service as ws
        old = ws.socketio
        try:
            from flask_socketio import SocketIO
            sio = ws.init_socketio(app)
            assert isinstance(sio, SocketIO)
            assert ws.socketio is sio
        finally:
            ws.socketio = old


# ── CLI: flask db-status ──────────────────────────────────────────────────────

class TestCliDbStatus:
    def test_db_status_reports_not_migrated(self, app):
        # Test DB is created via create_all(): no alembic_version table.
        runner = app.test_cli_runner()
        result = runner.invoke(args=['db-status'])
        assert result.exit_code == 0
        assert 'Heads:' in result.output
        assert '13_add_gl_line_tenant' in result.output
        assert 'NOT MIGRATED' in result.output

    def test_register_cli_commands_wires_db(self, app):
        from cli_commands import register_cli_commands
        register_cli_commands(app)  # idempotent re-registration
        runner = app.test_cli_runner()
        assert runner.invoke(args=['db-status']).exit_code == 0
