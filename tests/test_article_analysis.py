"""Tests für Phase-1-Artikelanalyse."""

from datetime import datetime, timezone

import pytest

from src.analyze.article import (
    AnalysisRunResult,
    _build_user_prompt,
    _validate_analysis_payload,
    analyze_articles,
)
from src.analyze.cache import get_cached_analysis, load_cache, save_cache, store_analysis
from src.models.schemas import Article, ArticleAnalysis, Settings

TZ = timezone.utc


def _article(article_id: str = "a1") -> Article:
    return Article(
        id=article_id,
        title="EU verschärft Klimaziele",
        source_name="Tagesschau",
        source_type="media",
        published_at=datetime(2026, 6, 15, 8, 0, tzinfo=TZ),
        description="Die EU einigt sich auf neue Emissionsziele.",
        url="https://example.com/eu-klima",
        source_priority=8,
        source_focus=["climate", "eu_policy"],
        source_role="agenda",
    )


def _settings() -> Settings:
    return Settings(
        lookback_hours=24,
        timezone="Europe/Berlin",
        language="de",
        llm={"models": {"article_analysis": "gpt-4o-mini"}},
    )


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, **kwargs) -> dict:
        self.calls += 1
        return {
            "summary": "Die EU beschließt verschärfte Klimaziele.",
            "main_topics": ["EU-Klimapolitik", "Emissionsziele"],
            "keywords": ["EU", "Klima", "Emissionen"],
            "environmental_links": ["Klimaschutz", "EU-Politik"],
        }


def test_validate_analysis_payload():
    analysis = _validate_analysis_payload(
        {
            "summary": "Kurzfassung.",
            "main_topics": ["Klima"],
            "keywords": ["EU"],
            "environmental_links": [],
        }
    )
    assert analysis.summary == "Kurzfassung."
    assert analysis.main_topics == ["Klima"]


def test_validate_analysis_payload_missing_field():
    with pytest.raises(ValueError, match="unvollständig"):
        _validate_analysis_payload({"summary": "x"})


def test_build_user_prompt_contains_metadata():
    prompt = _build_user_prompt(_article())
    assert "EU verschärft Klimaziele" in prompt
    assert "Tagesschau" in prompt
    assert "climate" in prompt


def test_cache_roundtrip(tmp_path):
    cache = {"version": 1, "entries": {}}
    analysis = ArticleAnalysis(
        article_id="a1",
        summary="Test",
        main_topics=["Klima"],
        keywords=["EU"],
        environmental_links=["Klimaschutz"],
        analyzed_at=datetime(2026, 6, 15, 12, 0, tzinfo=TZ),
    )
    store_analysis(cache, "https://example.com/eu-klima", analysis)

    cache_path = tmp_path / "articles.json"
    save_cache(cache, cache_path)
    loaded = load_cache(cache_path)
    cached = get_cached_analysis(loaded, "https://example.com/eu-klima")

    assert cached is not None
    assert cached.summary == "Test"
    assert cached.main_topics == ["Klima"]


def test_analyze_articles_with_fake_llm(tmp_path):
    cache_path = tmp_path / "articles.json"
    articles = [_article()]

    result = analyze_articles(
        articles,
        _settings(),
        llm=FakeLLM(),  # type: ignore[arg-type]
        cache_path=cache_path,
    )

    assert isinstance(result, AnalysisRunResult)
    assert result.analyzed_count == 1
    assert "a1" in result.analyses
    assert result.analyses["a1"].environmental_links == ["Klimaschutz", "EU-Politik"]

    # Zweiter Lauf nutzt Cache
    result2 = analyze_articles(
        articles,
        _settings(),
        llm=FakeLLM(),  # type: ignore[arg-type]
        cache_path=cache_path,
    )
    assert result2.cached_count == 1
    assert result2.analyzed_count == 0
