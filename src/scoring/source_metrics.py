"""Deterministische Quellenmetriken und Scores für Themencluster."""

from __future__ import annotations

from src.models.schemas import Article, Settings, TopicCluster, TopicScores


def _cluster_articles(cluster: TopicCluster, articles: list[Article]) -> list[Article]:
    article_map = {a.id: a for a in articles}
    return [article_map[aid] for aid in cluster.article_ids if aid in article_map]


def compute_source_metrics(
    cluster: TopicCluster,
    articles: list[Article],
    *,
    high_priority_threshold: int = 8,
) -> TopicCluster:
    """Berechnet aggregierte Quellenmetriken für einen Themencluster."""
    cluster_articles = _cluster_articles(cluster, articles)

    if not cluster_articles:
        return cluster

    source_names = sorted({a.source_name for a in cluster_articles})
    source_types = sorted({a.source_type for a in cluster_articles})
    focus_areas = sorted({f for a in cluster_articles for f in a.source_focus})

    priorities = [a.source_priority for a in cluster_articles]
    unique_priorities = {a.source_name: a.source_priority for a in cluster_articles}
    high_priority_count = sum(
        1 for p in unique_priorities.values() if p >= high_priority_threshold
    )

    cluster.article_count = len(cluster_articles)
    cluster.source_count = len(source_names)
    cluster.source_names = source_names
    cluster.source_types = source_types
    cluster.focus_areas = focus_areas
    cluster.avg_source_priority = sum(priorities) / len(priorities)
    cluster.max_source_priority = max(priorities)
    cluster.high_priority_source_count = high_priority_count
    cluster.source_type_diversity = len(source_types)

    return cluster


def compute_source_priority_score(
    cluster: TopicCluster,
    *,
    high_priority_bonus: float = 0.5,
    max_bonus: float = 2.0,
) -> float:
    """
    Quellenpriorität (1–10).

    Basis: Durchschnitt der Quellenprioritäten.
    Bonus: +0,5 pro hochpriorisierter Quelle (Prio >= 8), max. +2.
    """
    if cluster.source_count == 0:
        return 0.0

    bonus = min(max_bonus, cluster.high_priority_source_count * high_priority_bonus)
    return round(min(10.0, cluster.avg_source_priority + bonus), 2)


def compute_source_diversity_score(
    cluster: TopicCluster,
    *,
    points_per_type: float = 2.5,
) -> float:
    """
    Quellenvielfalt (1–10).

    2,5 Punkte pro beteiligtem Quellentyp (media, science, policy, ngo).
    """
    if cluster.source_type_diversity == 0:
        return 0.0

    return round(min(10.0, cluster.source_type_diversity * points_per_type), 2)


def compute_objective_media_attention(
    cluster: TopicCluster,
    articles: list[Article],
    *,
    article_weight: float = 1.5,
    media_source_weight: float = 2.0,
    media_ratio_weight: float = 3.0,
) -> float:
    """
    Objektive Medienaufmerksamkeit (1–10) – ohne LLM.

    Basiert auf Artikelanzahl, Anzahl Medienquellen und Anteil media-Artikel.
    """
    cluster_articles = _cluster_articles(cluster, articles)
    if not cluster_articles:
        return 0.0

    media_articles = [a for a in cluster_articles if a.source_type == "media"]
    unique_media_sources = len({a.source_name for a in media_articles})
    media_ratio = len(media_articles) / len(cluster_articles)

    score = (
        len(cluster_articles) * article_weight
        + unique_media_sources * media_source_weight
        + media_ratio * media_ratio_weight
    )
    return round(min(10.0, score), 2)


def compute_deterministic_scores(
    cluster: TopicCluster,
    articles: list[Article],
    settings: Settings,
) -> TopicScores:
    """Berechnet alle deterministischen Scores für einen Cluster."""
    scoring = settings.scoring
    high_priority_threshold = scoring.get("high_priority_threshold", 8)

    cluster = compute_source_metrics(
        cluster,
        articles,
        high_priority_threshold=high_priority_threshold,
    )

    priority_score = compute_source_priority_score(cluster)
    diversity_score = compute_source_diversity_score(cluster)
    media_objective = compute_objective_media_attention(cluster, articles)

    return TopicScores(
        source_priority_score=priority_score,
        source_diversity_score=diversity_score,
        media_attention=media_objective,
        breakdown={
            "source_priority": priority_score,
            "source_diversity": diversity_score,
            "media_attention_objective": media_objective,
        },
    )


def enrich_cluster(
    cluster: TopicCluster,
    articles: list[Article],
    settings: Settings,
) -> tuple[TopicCluster, TopicScores]:
    """Metriken berechnen und deterministische Scores zurückgeben."""
    scoring = settings.scoring
    high_priority_threshold = scoring.get("high_priority_threshold", 8)

    cluster = compute_source_metrics(
        cluster,
        articles,
        high_priority_threshold=high_priority_threshold,
    )
    scores = compute_deterministic_scores(cluster, articles, settings)
    return cluster, scores
