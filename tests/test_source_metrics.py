"""Tests für Quellenmetriken."""

from datetime import datetime, timezone

from src.models.schemas import Article, Settings, TopicCluster
from src.scoring.source_metrics import (
    compute_deterministic_scores,
    compute_objective_media_attention,
    compute_source_diversity_score,
    compute_source_metrics,
    compute_source_priority_score,
    enrich_cluster,
)
from src.scoring.summary import summarize_by_source

TZ = timezone.utc


def _article(
    id_: str,
    source_name: str,
    source_type: str,
    priority: int = 5,
    focus: list[str] | None = None,
) -> Article:
    return Article(
        id=id_,
        title=f"Artikel {id_}",
        source_name=source_name,
        source_type=source_type,
        published_at=datetime(2026, 6, 15, 12, 0, tzinfo=TZ),
        description="Test",
        url=f"https://example.com/{id_}",
        source_priority=priority,
        source_focus=focus or ["climate"],
        source_role="agenda",
    )


def _settings() -> Settings:
    return Settings(
        lookback_hours=24,
        timezone="Europe/Berlin",
        language="de",
        scoring={"high_priority_threshold": 8},
    )


def test_summarize_by_source():
    articles = [
        _article("1", "Tagesschau", "media", 8),
        _article("2", "Tagesschau", "media", 8),
        _article("3", "BfN", "science", 10, ["biodiversity"]),
    ]
    summary = summarize_by_source(articles)

    assert len(summary) == 2
    assert summary[0].source_name == "Tagesschau"
    assert summary[0].article_count == 2
    assert summary[1].source_name == "BfN"


def test_compute_source_metrics():
    articles = [
        _article("1", "Tagesschau", "media", 8),
        _article("2", "BfN", "science", 10, ["biodiversity"]),
        _article("3", "BUND", "ngo", 7, ["climate", "policy"]),
    ]
    cluster = TopicCluster(
        id="t1",
        label="Test",
        article_ids=["1", "2", "3"],
    )

    result = compute_source_metrics(cluster, articles)

    assert result.article_count == 3
    assert result.source_count == 3
    assert result.source_types == ["media", "ngo", "science"]
    assert result.source_type_diversity == 3
    assert result.high_priority_source_count == 2
    assert "biodiversity" in result.focus_areas
    assert "climate" in result.focus_areas


def test_priority_score_with_high_priority_bonus():
    cluster = TopicCluster(
        id="t1",
        label="Test",
        article_ids=[],
        avg_source_priority=8.0,
        high_priority_source_count=2,
        source_count=2,
    )
    score = compute_source_priority_score(cluster)
    assert score == 9.0


def test_diversity_score_four_types():
    cluster = TopicCluster(
        id="t1",
        label="Test",
        article_ids=[],
        source_type_diversity=4,
    )
    assert compute_source_diversity_score(cluster) == 10.0


def test_objective_media_attention():
    articles = [
        _article("1", "Tagesschau", "media", 8),
        _article("2", "ZEIT", "media", 8),
        _article("3", "BfN", "science", 10),
    ]
    cluster = TopicCluster(id="t1", label="Test", article_ids=["1", "2", "3"])
    cluster = compute_source_metrics(cluster, articles)

    score = compute_objective_media_attention(cluster, articles)
    assert score > 0


def test_enrich_cluster_returns_scores():
    articles = [
        _article("1", "Tagesschau", "media", 9),
        _article("2", "EU-Kommission", "policy", 9, ["eu_policy"]),
    ]
    cluster = TopicCluster(id="t1", label="EU-Klima", article_ids=["1", "2"])

    enriched, scores = enrich_cluster(cluster, articles, _settings())

    assert enriched.article_count == 2
    assert scores.source_priority_score > 0
    assert scores.source_diversity_score == 5.0
    assert scores.media_attention > 0
    assert "source_priority" in scores.breakdown


def test_compute_deterministic_scores():
    articles = [_article("1", "BUND", "ngo", 7)]
    cluster = TopicCluster(id="t1", label="Einzel", article_ids=["1"])
    cluster = compute_source_metrics(cluster, articles)

    scores = compute_deterministic_scores(cluster, articles, _settings())
    assert scores.source_priority_score == 7.0
    assert scores.source_diversity_score == 2.5
