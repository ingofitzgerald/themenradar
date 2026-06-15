"""Tests für Themenclustering."""

from datetime import datetime, timezone

import pytest

from src.analyze.cluster import (
    _validate_cluster_payload,
    cluster_articles,
    cluster_by_topic_fallback,
)
from src.models.schemas import Article, ArticleAnalysis, Settings

TZ = timezone.utc


def _settings() -> Settings:
    return Settings(
        lookback_hours=24,
        timezone="Europe/Berlin",
        language="de",
        report={"max_topics": 15},
        scoring={"high_priority_threshold": 8},
    )


def _article(aid: str, title: str) -> Article:
    return Article(
        id=aid,
        title=title,
        source_name="Tagesschau",
        source_type="media",
        published_at=datetime(2026, 6, 15, 8, 0, tzinfo=TZ),
        description="Beschreibung",
        url=f"https://example.com/{aid}",
        source_priority=8,
        source_focus=["climate"],
        source_role="agenda",
    )


def _analysis(aid: str, topics: list[str]) -> ArticleAnalysis:
    return ArticleAnalysis(
        article_id=aid,
        summary=f"Zusammenfassung {aid}",
        main_topics=topics,
        keywords=["test"],
        environmental_links=["Klimaschutz"],
    )


class FakeLLM:
    def complete_json(self, **kwargs) -> dict:
        return {
            "topics": [
                {
                    "label": "EU-Klimapolitik",
                    "article_ids": ["a1", "a2"],
                },
                {
                    "label": "Artenschutz",
                    "article_ids": ["a3"],
                },
            ]
        }


def test_validate_cluster_payload():
    grouped = _validate_cluster_payload(
        {
            "topics": [
                {"label": "Klima", "article_ids": ["a1", "a2"]},
            ]
        },
        {"a1", "a2", "a3"},
    )
    assert grouped[0][0] == "Klima"
    assert grouped[0][1] == ["a1", "a2"]


def test_validate_cluster_payload_rejects_invalid():
    with pytest.raises(ValueError):
        _validate_cluster_payload({"topics": []}, {"a1"})


def test_fallback_clustering_groups_by_main_topic():
    articles = [
        _article("a1", "EU Klima"),
        _article("a2", "EU Beschluss"),
        _article("a3", "Wolf gesichtet"),
    ]
    analyses = {
        "a1": _analysis("a1", ["EU-Klimapolitik"]),
        "a2": _analysis("a2", ["EU-Klimapolitik"]),
        "a3": _analysis("a3", ["Artenschutz"]),
    }

    grouped = cluster_by_topic_fallback(articles, analyses)
    assert len(grouped) == 2
    assert sum(len(ids) for _, ids in grouped) == 3


def test_cluster_articles_with_fake_llm():
    articles = [
        _article("a1", "EU Klima 1"),
        _article("a2", "EU Klima 2"),
        _article("a3", "Artenschutz"),
    ]
    analyses = {
        "a1": _analysis("a1", ["EU-Klimapolitik"]),
        "a2": _analysis("a2", ["EU-Klimapolitik"]),
        "a3": _analysis("a3", ["Artenschutz"]),
    }

    result = cluster_articles(
        articles,
        analyses,
        _settings(),
        llm=FakeLLM(),  # type: ignore[arg-type]
    )

    assert len(result.clusters) == 2
    assert result.clusters[0].article_count >= 1
    assert result.scores


def test_cluster_articles_fallback_only():
    articles = [_article("a1", "Test")]
    analyses = {"a1": _analysis("a1", ["Klimapolitik"])}

    result = cluster_articles(
        articles,
        analyses,
        _settings(),
        use_fallback=True,
    )

    assert result.used_fallback is True
    assert len(result.clusters) == 1
