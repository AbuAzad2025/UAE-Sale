from unittest.mock import MagicMock, patch


def test_websocket_blueprint_exists():
    from routes.websocket import websocket_bp
    assert websocket_bp is not None
    assert websocket_bp.name == 'websocket'


class _FakeSocketIO:
    def __init__(self):
        self.handlers = {}
        self.emitted = []

    def on(self, event):
        def deco(fn):
            self.handlers[event] = fn
            return fn
        return deco

    def emit(self, *args, **kwargs):
        self.emitted.append((args, kwargs))


def test_subscribe_joins_user_room():
    from routes import websocket as ws_mod
    from routes.websocket import register_websocket_events
    fake = _FakeSocketIO()
    user = MagicMock()
    user.is_authenticated = True
    user.id = 7
    with patch.object(ws_mod, 'init_socketio', return_value=fake), \
            patch('flask_login.current_user', user), \
            patch('flask_socketio.join_room') as join_room:
        sio = register_websocket_events(MagicMock())
        assert sio is fake
        handler = fake.handlers['subscribe_notifications']
        handler({'foo': 'bar'})
    join_room.assert_called_once_with('user_7')
    assert fake.emitted == [(('subscribed', {'room': 'user_7'}), {'room': 'user_7'})]


def test_subscribe_ignores_anonymous():
    from routes import websocket as ws_mod
    from routes.websocket import register_websocket_events
    fake = _FakeSocketIO()
    user = MagicMock()
    user.is_authenticated = False
    with patch.object(ws_mod, 'init_socketio', return_value=fake), \
            patch('flask_login.current_user', user), \
            patch('flask_socketio.join_room') as join_room:
        register_websocket_events(MagicMock())
        fake.handlers['subscribe_notifications']({'foo': 'bar'})
    join_room.assert_not_called()
    assert fake.emitted == []