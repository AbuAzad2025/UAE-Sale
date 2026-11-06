"""GuideLoader tests — نطاق آمن: Owner فقط، بدون تسريب"""
from ai_knowledge.guide_loader import GuideLoader


def _loader(tmp_path):
    # Use project root guides (read-only)
    return GuideLoader(base_dir=__import__("pathlib").Path(__file__).parents[2])


def test_public_sections_loaded():
    loader = GuideLoader(base_dir=__import__("pathlib").Path(__file__).parents[2])
    # Force fresh load
    loader._cache.clear()
    pub = loader.public_sections()
    assert len(pub) > 20
    titles = [s.title for s in pub]
    assert any("المبيعات" in t or "البدء" in t or "نظرة" in t or "Sales" in t for t in titles)


def test_owner_sections_loaded():
    loader = GuideLoader(base_dir=__import__("pathlib").Path(__file__).parents[2])
    loader._cache.clear()
    own = loader.owner_sections()
    assert len(own) > 5
    titles = [s.title for s in own]
    assert any("Dashboard" in t or "لوحة" in t or "Tenants" in t or "التينانت" in t for t in titles)


def test_scoping_no_leak():
    loader = GuideLoader(base_dir=__import__("pathlib").Path(__file__).parents[2])
    loader._cache.clear()
    non_owner = loader.visible_sections(is_owner=False)
    owner = loader.visible_sections(is_owner=True)
    assert len(owner) > len(non_owner)
    # Non-owner must not contain owner guide titles
    owner_titles = {s.title for s in loader.owner_sections()}
    non_owner_titles = {s.title for s in non_owner}
    assert not (owner_titles & non_owner_titles) or len(non_owner_titles & owner_titles) == 0


def test_search_respects_owner():
    loader = GuideLoader(base_dir=__import__("pathlib").Path(__file__).parents[2])
    loader._cache.clear()
    hits_public = loader.search("المبيعات", is_owner=False, top_k=3)
    hits_owner = loader.search("Tenants", is_owner=False, top_k=3)
    # Public search should return something (may be empty if no token match, but must not expose owner)
    for h in hits_public:
        assert h["title"] not in [s.title for s in loader.owner_sections()] if loader.owner_sections() else True
    # Search for owner-only term with is_owner=False should not return owner section
    owner_titles = {s.title for s in loader.owner_sections()}
    for h in hits_owner:
        assert h["title"] not in owner_titles


def test_get_context_max_chars():
    loader = GuideLoader(base_dir=__import__("pathlib").Path(__file__).parents[2])
    loader._cache.clear()
    ctx = loader.get_context("كيف أنشئ مبيعة", is_owner=False, max_chars=1000)
    assert len(ctx) <= 1100  # small tolerance for section headers
    assert "مبيعات" in ctx.lower() or "sales" in ctx.lower() or len(ctx) > 0


def test_list_titles_is_owner_only():
    loader = GuideLoader(base_dir=__import__("pathlib").Path(__file__).parents[2])
    loader._cache.clear()
    titles_non_owner = loader.list_titles(is_owner=False)
    titles_owner = loader.list_titles(is_owner=True)
    assert len(titles_owner) > len(titles_non_owner)
    scopes = {t["scope"] for t in titles_non_owner}
    assert scopes == {"public"}
    scopes_owner = {t["scope"] for t in titles_owner}
    assert "public" in scopes_owner and "owner" in scopes_owner
