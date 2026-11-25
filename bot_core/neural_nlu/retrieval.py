"""Local sparse character embeddings for scoped record and guide suggestions."""

from collections import Counter
from collections.abc import Iterable
from math import sqrt
from typing import TypeVar

from bot_core.gateway import normalize

T = TypeVar("T")


def _embedding(text: str) -> Counter[str]:
    words = normalize(text).split()
    padded = [f"^{word}$" for word in words]
    return Counter(
        word[index:index + width]
        for word in padded
        for width in (2, 3)
        for index in range(len(word) - width + 1)
    )


def _norm(vector: Counter[str]) -> float:
    return sqrt(sum(count * count for count in vector.values()))


def rank(query: str, candidates: Iterable[tuple[T, str]], *, threshold: float = 0.30, limit: int = 5) -> list[T]:
    source = _embedding(query)
    source_norm = _norm(source)
    if not source_norm:
        return []
    ranked: list[tuple[float, T]] = []
    for candidate, text in candidates:
        vector = _embedding(text)
        norm = _norm(vector)
        if not norm:
            continue
        score = sum(count * vector[key] for key, count in source.items()) / (source_norm * norm)
        if score >= threshold:
            ranked.append((score, candidate))
    return [candidate for _, candidate in sorted(ranked, key=lambda entry: entry[0], reverse=True)[:limit]]


def guide(query: str, *, is_owner: bool) -> str | None:
    from ai_knowledge.guide_loader import get_guide_loader

    sections = get_guide_loader().visible_sections(is_owner)
    hits = rank(
        query,
        ((section, f"{section.title} {section.title} {section.content[:350]}") for section in sections),
        threshold=0.16, limit=1,
    )
    if not hits:
        return None
    section = hits[0]
    return f"{section.title}\n{section.content[:900]}"
