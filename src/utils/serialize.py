"""Hilfsfunktionen zum Laden gespeicherter Läufe."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.models.schemas import Article, ArticleAnalysis, TopicCluster


def article_from_dict(data: dict) -> Article:
    published = data["published_at"]
    if isinstance(published, str):
        published = datetime.fromisoformat(published)

    return Article(
        id=data["id"],
        title=data["title"],
        source_name=data["source_name"],
        source_type=data["source_type"],
        published_at=published,
        description=data.get("description", ""),
        url=data["url"],
        source_priority=data.get("source_priority", 5),
        source_focus=data.get("source_focus", []),
        source_role=data.get("source_role", "agenda"),
    )


def analysis_from_dict(data: dict) -> ArticleAnalysis:
    analyzed_at = data.get("analyzed_at")
    if isinstance(analyzed_at, str):
        analyzed_at = datetime.fromisoformat(analyzed_at)

    return ArticleAnalysis(
        article_id=data.get("article_id", ""),
        summary=data.get("summary", ""),
        main_topics=data.get("main_topics", []),
        keywords=data.get("keywords", []),
        environmental_links=data.get("environmental_links", []),
        analyzed_at=analyzed_at,
    )


def load_articles_from_run(path: Path) -> tuple[list[Article], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    articles = [article_from_dict(a) for a in payload.get("articles", [])]
    return articles, payload


def load_clustered_run(path: Path) -> tuple[list[TopicCluster], dict]:
    """Lädt Themencluster aus clustered.json."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    clusters = []
    for entry in payload.get("topics", []):
        clusters.append(
            TopicCluster(
                id=entry["id"],
                label=entry["label"],
                article_ids=entry.get("article_ids", []),
                article_count=entry.get("article_count", 0),
                source_count=entry.get("source_count", 0),
                source_names=entry.get("source_names", []),
                source_types=entry.get("source_types", []),
                focus_areas=entry.get("focus_areas", []),
                avg_source_priority=entry.get("avg_source_priority", 0.0),
                max_source_priority=entry.get("max_source_priority", 0),
                high_priority_source_count=entry.get("high_priority_source_count", 0),
                source_type_diversity=entry.get("source_type_diversity", 0),
            )
        )
    return clusters, payload


def load_analyzed_run(
    path: Path,
) -> tuple[list[Article], dict[str, ArticleAnalysis], dict]:
    """Lädt Artikel und Phase-1-Analysen aus einem analyzed.json-Lauf."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    articles: list[Article] = []
    analyses: dict[str, ArticleAnalysis] = {}

    for entry in payload.get("articles", []):
        article = article_from_dict(entry)
        articles.append(article)
        if "analysis" in entry:
            analysis = analysis_from_dict(entry["analysis"])
            analysis.article_id = article.id
            analyses[article.id] = analysis

    return articles, analyses, payload
