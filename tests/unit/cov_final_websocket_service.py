"""Backend test coverage for services/websocket_service.py (real API).

There are no /ws HTTP routes in this codebase (routes/websocket.py only
registers Socket.IO events); the service exposes broadcast helpers that
safely no-op when Socket.IO is not initialized.
"""
import services.websocket_service as ws


class TestWebSocketService:
    """Test WebSocket service helpers."""

    def test_broadcast_sale_created_no_raise(self):
        assert ws.broadcast_sale_created({'id': 1, 'total': 100.0}) is None

    def test_broadcast_payment_received_no_raise(self):
        assert ws.broadcast_payment_received({'id': 2, 'amount': 50.0}) is None

    def test_broadcast_stock_alert_no_raise(self):
        assert ws.broadcast_stock_alert({'sku': 'SKU-1', 'stock': 0}) is None

    def test_notify_user_no_raise(self):
        assert ws.notify_user(1, 'hello', 'info') is None
        assert ws.notify_user(1, 'hello') is None

    def test_service_entry_points_exist(self):
        for name in ('init_socketio', 'broadcast_sale_created',
                     'broadcast_payment_received', 'broadcast_stock_alert',
                     'notify_user'):
            assert callable(getattr(ws, name)), name

    def test_register_websocket_events_callable(self):
        from routes.websocket import register_websocket_events
        assert callable(register_websocket_events)
