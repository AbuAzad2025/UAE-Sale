"""Append interaction evidence within the transaction that changed state."""

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from extensions import db
from models.bot_event import BotEventAudit


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def append(event_id: str, actor, outcome: str, details: Mapping[str, Any]) -> None:
    db.session.add(
        BotEventAudit(
            event_id=event_id,
            user_id=actor.user_id,
            tenant_id=actor.tenant_id,
            outcome=outcome,
            details=dict(details),
            recorded_at=utcnow(),
        )
    )
