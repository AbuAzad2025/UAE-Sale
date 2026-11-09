"""
Guide Loader — مصدر واحد للحقيقة لدليل المستخدم
=================================================

يريد المساعد أن يشرح النظام بدقة، بدون дублирование من قواعد المعرفة
القديمة (user_guide.py / system_knowledge.py المتناقضة).

هذا الموديول يقرأ ملفي Markdown من جذر المشروع:
- FULL_USER_GUIDE.md  → دليل عام آمن للجميع
- OWNER_USER_GUIDE.md → دليل المالك — للمالك فقط

الأمان:
- لا وصول لقاعدة البيانات من هنا
- لا أسرار ولا مفاتيح
- نطاق صارم: المستخدِم العادي لا يرى أقسام المالك أبداً

الكاش:
- يُقرأ عند الحاجة ويُخزَّن في الذاكرة
- يُحقق من mtime في كل استدعاء — أي تحديث للإصدار يلتقط فوراً
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GuideSection:
    title: str
    level: int  # 1 = # , 2 = ## , 3 = ###
    content: str


def _parse_markdown_sections(text: str) -> list[GuideSection]:
    sections: list[GuideSection] = []
    title = "مقدمة"
    level = 1
    buf: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^(#{1,3})\s+(.+)", line)
        if m:
            if buf:
                sections.append(GuideSection(title=title, level=level, content="\n".join(buf).strip()))
            title = m.group(2).strip()
            level = len(m.group(1))
            buf = []
        else:
            buf.append(line)
    if buf:
        sections.append(GuideSection(title=title, level=level, content="\n".join(buf).strip()))
    return sections


class GuideLoader:
    """تحميل وبحث في أدلة Markdown بآمان."""

    _instance: "GuideLoader | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self, base_dir: str | Path | None = None):
        if getattr(self, "_loaded", False):
            return
        self._base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parents[1]
        self._public_path = self._base_dir / "FULL_USER_GUIDE.md"
        self._owner_path = self._base_dir / "OWNER_USER_GUIDE.md"
        self._cache: dict[str, tuple[float, list[GuideSection]]] = {}
        self._loaded = True

    # ---------- loading ----------
    def _load_sections(self, path: Path) -> list[GuideSection]:
        try:
            mtime = path.stat().st_mtime if path.exists() else 0
        except Exception:
            mtime = 0
        cached = self._cache.get(str(path))
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            if not path.exists():
                logger.warning("Guide file not found: %s", path)
                sections: list[GuideSection] = []
            else:
                text = path.read_text(encoding="utf-8", errors="ignore")
                sections = _parse_markdown_sections(text)
            self._cache[str(path)] = (mtime, sections)
            return sections
        except Exception as exc:
            logger.warning("Guide load failed %s: %s", path, exc)
            return cached[1] if cached else []

    def public_sections(self) -> list[GuideSection]:
        return self._load_sections(self._public_path)

    def owner_sections(self) -> list[GuideSection]:
        return self._load_sections(self._owner_path)

    def visible_sections(self, is_owner: bool) -> list[GuideSection]:
        sections = list(self.public_sections())
        if bool(is_owner):
            sections = sections + self.owner_sections()
        return sections

    # ---------- search ----------
    @staticmethod
    def _score(section: GuideSection, query: str) -> int:
        q = (query or "").strip().lower()
        if not q:
            return 0
        score = 0
        title = section.title.lower()
        body = section.content.lower()
        if q in title:
            score += 3
        if q in body:
            score += 2
        for token in re.split(r"\s+", q):
            if len(token) < 2:
                continue
            if token in title:
                score += 2
            if token in body:
                score += 1
        return score

    def search(self, query: str, is_owner: bool, top_k: int = 3) -> list[dict]:
        sections = self.visible_sections(is_owner)
        if not query or not query.strip():
            return [{"title": s.title, "content": s.content[:600], "level": s.level} for s in sections[:top_k]]
        ranked = sorted(sections, key=lambda s: self._score(s, query), reverse=True)
        hits = [s for s in ranked if self._score(s, query) > 0][: int(top_k or 3)]
        if hits:
            return [{"title": s.title, "content": s.content[:1200], "level": s.level} for s in hits]
        return [{"title": s.title, "content": s.content[:600], "level": s.level} for s in sections[:top_k]]

    def get_context(self, query: str, is_owner: bool, max_chars: int = 6000) -> str:
        """سياق مختصر للـ LLM — مقسّم حسب النطاق، بدون بيانات حساسة."""
        hits = self.search(query, is_owner, top_k=3)
        if not hits:
            return ""
        parts = []
        total = 0
        for h in hits:
            block = f"## {h['title']}\n{h['content']}"
            if total + len(block) > max_chars:
                block = block[: max(0, max_chars - total)]
                parts.append(block)
                break
            parts.append(block)
            total += len(block) + 2
        return "\n\n".join(parts)

    def list_titles(self, is_owner: bool) -> list[dict]:
        return [
            {"title": s.title, "level": s.level, "scope": "owner" if s in self.owner_sections() else "public"}
            for s in self.visible_sections(is_owner)
        ]


def get_guide_loader() -> GuideLoader:
    with GuideLoader._lock:
        return GuideLoader()


# Singleton instance
guide_loader = get_guide_loader()


__all__ = ["GuideLoader", "get_guide_loader", "guide_loader"]
