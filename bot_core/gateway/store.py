"""A PostgreSQL/SQLite message queue with expiring, fenced worker claims."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from bot_core.gateway import MessageEvent
from bot_core.observability import append, utcnow
from bot_core.security import Actor
from extensions import db
from models.bot_event import BotEvent

_LEASE = timedelta(seconds=15)
_OPERATION_LEASE = timedelta(seconds=120)
_EVENT_TTL = timedelta(minutes=5)
_DEBOUNCE = timedelta(milliseconds=250)
_MAX_ATTEMPTS = 3


class IdempotencyConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Claim:
    event: MessageEvent
    token: str
    queued_at: datetime | None = None


def _scoped(event_id: str, actor: Actor):
    return select(BotEvent).where(
        BotEvent.id == event_id,
        BotEvent.user_id == actor.user_id,
        BotEvent.tenant_id == actor.tenant_id,
    )


def read(event_id: str, actor: Actor) -> BotEvent | None:
    return db.session.scalar(_scoped(event_id, actor))


def active(actor: Actor) -> list[tuple[str, str]]:
    rows = db.session.execute(
        select(BotEvent.id, BotEvent.status)
        .where(
            BotEvent.user_id == actor.user_id,
            BotEvent.tenant_id == actor.tenant_id,
            BotEvent.status.in_(("queued", "processing")),
            BotEvent.expires_at > utcnow(),
        )
        .order_by(BotEvent.created_at, BotEvent.id)
    )
    return [(row.id, row.status) for row in rows]


def submit(event: MessageEvent) -> BotEvent:
    command_kind = event.command["tool"] if event.command else None
    existing = read(event.id, event.actor)
    if existing is not None:
        if existing.raw_input != event.raw_input or existing.command_kind != command_kind:
            raise IdempotencyConflict("This idempotency key is already in use.")
        return existing
    now = utcnow()
    row = BotEvent(
        id=event.id, user_id=event.actor.user_id, tenant_id=event.actor.tenant_id,
        raw_input=event.raw_input, normalized=event.normalized, status="queued",
        created_at=now, available_at=now + _DEBOUNCE, expires_at=now + _EVENT_TTL,
        command=event.command, command_kind=command_kind,
    )
    try:
        db.session.add(row)
        # Postpone recent queued messages in this conversation as a batch, while
        # preserving each key and its order. Older messages cannot be postponed indefinitely.
        db.session.execute(
            update(BotEvent)
            .where(
                BotEvent.user_id == event.actor.user_id,
                BotEvent.tenant_id == event.actor.tenant_id,
                BotEvent.status == "queued",
                BotEvent.created_at > now - _DEBOUNCE,
                BotEvent.created_at < now,
                BotEvent.available_at > now,
            )
            .values(available_at=now + _DEBOUNCE)
        )
        append(event.id, event.actor, "queued", {
            "raw_input": event.raw_input, "normalized": event.normalized,
        })
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = read(event.id, event.actor)
        if existing is None or existing.raw_input != event.raw_input or existing.command_kind != command_kind:
            raise IdempotencyConflict("This idempotency key is already in use.") from None
        return existing
    return row


def _recoverable(now):
    return or_(
        and_(BotEvent.status == "queued", BotEvent.available_at <= now),
        and_(BotEvent.status == "processing", BotEvent.lease_until <= now),
    )


def claim_next(*, interactive_only: bool = False) -> Claim | None:
    now = utcnow()
    older = aliased(BotEvent)
    prior_message = exists(
        select(older.id).where(
            older.user_id == BotEvent.user_id,
            older.tenant_id.is_not_distinct_from(BotEvent.tenant_id),
            older.status.in_(("queued", "processing")),
            or_(
                older.created_at < BotEvent.created_at,
                and_(older.created_at == BotEvent.created_at, older.id < BotEvent.id),
            ),
        ).correlate(BotEvent)
    )
    eligible = (_recoverable(now), ~prior_message)
    if interactive_only:
        eligible += (BotEvent.command_kind.is_(None),)
    candidate = db.session.execute(
        select(
            BotEvent.id, BotEvent.user_id, BotEvent.tenant_id, BotEvent.raw_input,
            BotEvent.normalized, BotEvent.created_at, BotEvent.expires_at, BotEvent.attempts, BotEvent.command,
        )
        .where(*eligible)
        .order_by(BotEvent.created_at, BotEvent.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).one_or_none()
    if candidate is None:
        db.session.rollback()
        return None

    actor = Actor(candidate.user_id, candidate.tenant_id)
    token = str(uuid4())
    expired = candidate.expires_at <= now or candidate.attempts >= _MAX_ATTEMPTS
    status = "failed" if expired else "processing"
    changes: dict[str, Any] = {"status": status, "attempts": candidate.attempts + 1}
    if expired:
        result = {"message": "انتهت مهلة الطلب. أرسل طلبًا جديدًا.", "outcome": "queue_expired"}
        if candidate.command and candidate.command["tool"] == "confirm_action":
            result["data"] = {"action_id": candidate.command["arguments"]["action_id"]}
        changes.update(
            result=result, lease_token=None, lease_until=None, command=None,
        )
    else:
        lease = _OPERATION_LEASE if candidate.command else _LEASE
        changes.update(lease_token=token, lease_until=now + lease)
    updated = db.session.execute(
        update(BotEvent)
        .where(BotEvent.id == candidate.id, BotEvent.attempts == candidate.attempts, _recoverable(now))
        .values(**changes)
    )
    if updated.rowcount != 1:
        db.session.rollback()
        return None
    append(candidate.id, actor, status, {
        "attempt": candidate.attempts + 1,
        "queue_wait_ms": max(0, round((now - candidate.created_at).total_seconds() * 1000)),
        **({"outcome": "queue_expired", "operation": candidate.command and candidate.command["tool"] or "message"} if expired else {}),
    })
    db.session.commit()
    if expired:
        return None
    return Claim(MessageEvent(candidate.id, actor, candidate.raw_input, candidate.normalized, candidate.command), token, candidate.created_at)


def finish(
    claim: Claim, *, outcome: str, result: Mapping[str, Any], trace: Mapping[str, Any],
) -> bool:
    """Commit results (and any transactional tool changes) only for the active claim."""
    if outcome not in ("completed", "failed"):
        raise ValueError("Invalid terminal outcome.")
    updated = db.session.execute(
        update(BotEvent)
        .where(
            BotEvent.id == claim.event.id,
            BotEvent.status == "processing",
            BotEvent.lease_token == claim.token,
            BotEvent.lease_until > utcnow(),
        )
        .values(status=outcome, result=dict(result), lease_token=None, lease_until=None, command=None)
    )
    if updated.rowcount != 1:
        db.session.rollback()
        return False
    append(claim.event.id, claim.event.actor, outcome, trace)
    db.session.commit()
    return True
