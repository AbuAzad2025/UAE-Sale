"""Database-backed, actor-scoped dialogue state."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import update

from bot_core.observability import utcnow
from bot_core.security import Actor
from extensions import db
from models import AssistantAction
from models.bot_event import BotConversation


@dataclass(frozen=True, slots=True)
class Dialogue:
    topic: str
    slots: dict[str, Any]


class StateManager:
    def __init__(self, ttl: timedelta = timedelta(minutes=15)):
        if ttl <= timedelta(0):
            raise ValueError("The dialogue TTL must be positive.")
        self.ttl = ttl

    @staticmethod
    def _key(actor: Actor) -> str:
        return f"{actor.user_id}:{actor.tenant_id}"

    def load(self, actor: Actor) -> Dialogue | None:
        row = db.session.get(BotConversation, self._key(actor))
        if row is None or row.expires_at <= utcnow():
            return None
        return Dialogue(row.topic, dict(row.slots))

    def save(self, actor: Actor, dialogue: Dialogue) -> None:
        db.session.merge(BotConversation(
            scope_key=self._key(actor), topic=dialogue.topic,
            slots=dict(dialogue.slots), expires_at=utcnow() + self.ttl,
        ))

    def reset(self, actor: Actor) -> None:
        row = db.session.get(BotConversation, self._key(actor))
        if row is not None:
            db.session.delete(row)

    def cancel(self, actor: Actor, dialogue: Dialogue | None) -> bool:
        self.reset(actor)
        if dialogue is None or dialogue.topic != "confirmation":
            return False
        result = db.session.execute(
            update(AssistantAction)
            .where(
                AssistantAction.id == dialogue.slots["action_id"],
                AssistantAction.user_id == actor.user_id,
                AssistantAction.tenant_id == actor.tenant_id,
                AssistantAction.status == "pending",
                AssistantAction.expires_at > utcnow(),
            )
            .values(status="cancelled", response="أُلغيت المسودة.")
        )
        return result.rowcount == 1
