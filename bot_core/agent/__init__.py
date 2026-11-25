"""Structured tool registration and bounded execution."""

from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from time import monotonic
from typing import Any

from pydantic import BaseModel

from bot_core.dialogue import Dialogue
from bot_core.security import Actor, Effect, Principal, authorize


@dataclass(frozen=True, slots=True)
class ToolResult:
    message: str
    outcome: str
    entities: Mapping[str, Any]
    data: Mapping[str, Any] | None = None
    dialogue: Dialogue | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    inputs: type[BaseModel]
    permissions: tuple[str, ...]
    effect: Effect
    handler: Callable[[BaseModel, Actor, str], ToolResult]
    timeout_ms: int = 1500
    related_permissions: tuple[str, ...] = ()

    def authorize(self, actor: Actor, principal: Principal) -> None:
        authorize(actor, principal, self.permissions)
        if self.related_permissions:
            authorize(actor, principal, self.related_permissions)


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()):
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools or not tool.permissions or tool.timeout_ms <= 0:
            raise ValueError(f"Invalid or duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "effect": tool.effect.value,
                "input_schema": tool.inputs.model_json_schema(),
            }
            for tool in self._tools.values()
        ]


class AgentRunner:
    def __init__(
        self, registry: ToolRegistry, *, max_steps: int = 3, budget_ms: int = 3000,
        deadline: Callable[[int], AbstractContextManager] | None = None,
    ):
        if max_steps <= 0 or budget_ms <= 0:
            raise ValueError("Execution bounds must be positive.")
        self.registry = registry
        self.max_steps = max_steps
        self.budget_ms = budget_ms
        self._deadline = deadline or (lambda milliseconds: nullcontext())
        self._timeouts: dict[str, tuple[int, float]] = {}

    def run(
        self,
        calls: Iterable[ToolCall],
        actor: Actor,
        principal: Principal,
        request_id: str,
        *,
        confirmed: bool = False,
        direct_mutation: bool = False,
    ) -> list[ToolResult]:
        deadline = monotonic() + self.budget_ms / 1000
        results = []
        for step, call in enumerate(calls):
            if step >= self.max_steps:
                raise ValueError("Agent step limit exceeded.")
            if monotonic() >= deadline:
                raise TimeoutError("Agent execution budget expired.")
            tool = self.registry.get(call.name)
            if tool.effect is Effect.CONFIRMED and not confirmed:
                raise PermissionError("This tool requires a separate confirmation request.")
            if tool.effect is Effect.MUTATION and not direct_mutation:
                raise PermissionError("This tool requires an explicit mutation command.")
            tool.authorize(actor, principal)
            arguments = tool.inputs.model_validate(call.arguments, strict=True, extra="forbid")
            started = monotonic()
            count, until = self._timeouts.get(tool.name, (0, 0.0))
            if until > started:
                raise TimeoutError(f"Tool temporarily unavailable: {tool.name}")
            if until:
                count = 0
            time_limit = min(tool.timeout_ms, int((deadline - started) * 1000))
            try:
                if time_limit <= 0:
                    raise TimeoutError("Agent execution budget expired.")
                with self._deadline(time_limit):
                    result = tool.handler(arguments, actor, request_id)
                if monotonic() >= started + time_limit / 1000:
                    raise TimeoutError(f"Tool deadline exceeded: {tool.name}")
            except TimeoutError:
                self._timeouts[tool.name] = (count + 1, monotonic() + 15 if count >= 2 else 0)
                raise
            self._timeouts.pop(tool.name, None)
            results.append(result)
        return results
