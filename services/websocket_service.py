from flask import Flask
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import current_user
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def _tenant_of(data):
    """Best-effort tenant id from a broadcast payload."""
    if isinstance(data, dict):
        return data.get("tenant_id")
    return None


socketio = None


def init_socketio(app: Flask):
    global socketio

    origins = app.config.get("CORS_ORIGINS") or []
    socketio = SocketIO(
        app,
        cors_allowed_origins=origins or "/",
        async_mode="threading",
        message_queue=app.config.get("SOCKETIO_MESSAGE_QUEUE"),
        logger=False,
        engineio_logger=False,
    )

    @socketio.on("connect")
    def handle_connect():
        if current_user.is_authenticated:
            join_room(f"user_{current_user.id}")
            tid = getattr(current_user, "tenant_id", None)
            if tid:
                join_room(f"tenant_{tid}")
            emit("connected", {"status": "connected"})
            logger.info(f"User {current_user.id} connected via WebSocket")

    @socketio.on("disconnect")
    def handle_disconnect():
        if current_user.is_authenticated:
            leave_room(f"user_{current_user.id}")
            logger.info(f"User {current_user.id} disconnected")

    @socketio.on("ping")
    def handle_ping(data=None):
        emit("pong", {"timestamp": datetime.now().isoformat()})

    logger.info("[OK] WebSocket initialized")
    return socketio


def broadcast_sale_created(sale_data):
    if socketio:
        tid = _tenant_of(sale_data)
        socketio.emit("sale_created", sale_data, room=f"tenant_{tid}" if tid else None)
    else:
        logger.warning("broadcast_sale_created dropped: socketio not initialized")


def broadcast_payment_received(payment_data):
    if socketio:
        tid = _tenant_of(payment_data)
        socketio.emit("payment_received", payment_data, room=f"tenant_{tid}" if tid else None)
    else:
        logger.warning("broadcast_payment_received dropped: socketio not initialized")


def notify_user(user_id, message, notification_type="info"):
    if socketio:
        payload = {
            "title": message,
            "message": message,
            "type": notification_type,
        }
        socketio.emit("notification", payload, room=f"user_{user_id}")
        socketio.emit("broadcast_notification", payload, room=f"user_{user_id}")
    else:
        logger.warning(
            "notify_user dropped for user %s: socketio not initialized", user_id
        )


def broadcast_stock_alert(product_data):
    if socketio:
        tid = _tenant_of(product_data)
        socketio.emit("stock_alert", product_data, room=f"tenant_{tid}" if tid else None)
    else:
        logger.warning("broadcast_stock_alert dropped: socketio not initialized")
