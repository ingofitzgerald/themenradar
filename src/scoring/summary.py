"""Zusammenfassung von Artikeln nach Quelle."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.models.schemas import Article


@dataclass
class SourceSummary:
    source_name: str
    source_type: str
    source_role: str
    priority: int
    focus: list[str]
    article_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def summarize_by_source(articles: list[Article]) -> list[SourceSummary]:
    """Aggregiert Artikel nach Quelle (eindeutig pro source_name)."""
    buckets: dict[str, SourceSummary] = {}

    for article in articles:
        if article.source_name not in buckets:
            buckets[article.source_name] = SourceSummary(
                source_name=article.source_name,
                source_type=article.source_type,
                source_role=article.source_role,
                priority=article.source_priority,
                focus=list(article.source_focus),
            )
        buckets[article.source_name].article_count += 1

    return sorted(
        buckets.values(),
        key=lambda s: (-s.article_count, -s.priority, s.source_name),
    )
