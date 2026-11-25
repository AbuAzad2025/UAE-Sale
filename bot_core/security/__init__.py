"""Authorization contracts for the ERP agent."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Effect(StrEnum):
    READ = "read"
    PREVIEW = "preview"
    MUTATION = "mutation"
    CONFIRMED = "confirmed"


class Principal(Protocol):
    id: int
    is_authenticated: bool

    def has_permission(self, code: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: int
    tenant_id: int | None

    @classmethod
    def authenticated(cls, principal: Principal, tenant_id: int | None) -> "Actor":
        if not principal.is_authenticated or type(principal.id) is not int or principal.id <= 0:
            raise PermissionError("An authenticated ERP user is required.")
        return cls(principal.id, tenant_id)


def authorize(actor: Actor, principal: Principal, permissions: tuple[str, ...]) -> None:
    if (
        not principal.is_authenticated
        or principal.id != actor.user_id
        or not any(principal.has_permission(code) for code in permissions)
    ):
        raise PermissionError("The current ERP user lacks permission for this tool.")
