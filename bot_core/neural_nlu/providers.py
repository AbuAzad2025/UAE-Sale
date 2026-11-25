"""Explicitly selected guidance adapters stay outside the local tool runner."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OptionalExternalProvider:
    credential: Callable[[], str | None]
    transport: Callable[[str], str | None]

    def answer(self, message: str, *, selected: bool = False) -> str | None:
        if not selected:
            return None
        try:
            if self.credential():
                return self.transport(message)
        except Exception:
            # The optional adapter provides guidance only. Failures return to the caller's local path.
            return None
        return None
