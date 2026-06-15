"""Datenmodelle für den Themenradar."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Any


@dataclass
class Source:
    name: str
    type: str
    feed_url: str
    priority: int = 5
    focus: list[str] = field(default_factory=list)
    source_role: str = "agenda"

    VALID_TYPES = frozenset({"media", "science", "policy", "ngo"})
    VALID_ROLES = frozenset({"agenda", "early_warning", "stakeholder"})

    def __post_init__(self) -> None:
        if self.type not in self.VALID_TYPES:
            raise ValueError(
                f"Ungültiger Quellentyp '{self.type}' für '{self.name}'. "
                f"Erlaubt: {', '.join(sorted(self.VALID_TYPES))}"
            )
        if self.source_role not in self.VALID_ROLES:
            raise ValueError(
                f"Ungültige source_role '{self.source_role}' für '{self.name}'. "
                f"Erlaubt: {', '.join(sorted(self.VALID_ROLES))}"
            )
        if not 1 <= self.priority <= 10:
            raise ValueError(
                f"priority muss zwischen 1 und 10 liegen, "
                f"ist {self.priority} bei '{self.name}'"
            )


@dataclass
class Article:
    id: str
    title: str
    source_name: str
    source_type: str
    published_at: datetime
    description: str
    url: str
    source_priority: int = 5
    source_focus: list[str] = field(default_factory=list)
    source_role: str = "agenda"

    @staticmethod
    def make_id(url: str) -> str:
        return sha256(url.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["published_at"] = self.published_at.isoformat()
        return data


@dataclass
class ArticleAnalysis:
    article_id: str
    summary: str
    main_topics: list[str]
    keywords: list[str]
    environmental_links: list[str]
    analyzed_at: datetime | None = None


@dataclass
class TopicCluster:
    id: str
    label: str
    article_ids: list[str]
    article_count: int = 0
    source_count: int = 0
    source_names: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list)
    focus_areas: list[str] = field(default_factory=list)
    avg_source_priority: float = 0.0
    max_source_priority: int = 0
    high_priority_source_count: int = 0
    source_type_diversity: int = 0


@dataclass
class TopicScores:
    wwf_relevance: float = 0.0
    media_attention: float = 0.0
    political_relevance: float = 0.0
    source_priority_score: float = 0.0
    source_diversity_score: float = 0.0
    overall_score: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class TopicAnalysis:
    topic_id: str
    why_relevant: str = ""
    narratives: list[str] = field(default_factory=list)
    conflict_lines: list[str] = field(default_factory=list)
    target_media: list[str] = field(default_factory=list)
    press_opportunity: dict[str, str] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    evaluation_answers: dict[str, str] = field(default_factory=dict)
    scores: TopicScores = field(default_factory=TopicScores)


@dataclass
class Settings:
    lookback_hours: int
    timezone: str
    language: str
    report: dict[str, Any] = field(default_factory=dict)
    llm: dict[str, Any] = field(default_factory=dict)
    dedup: dict[str, Any] = field(default_factory=dict)
    scoring: dict[str, Any] = field(default_factory=dict)


@dataclass
class Organization:
    name: str
    mission: str
    expertise: list[str]
    regions: list[str]
    avoid: list[str]
    tone: str
    project_types: list[str] = field(default_factory=list)
    media_goals: list[str] = field(default_factory=list)
    high_relevance_signals: list[str] = field(default_factory=list)
    potential_story_angles: list[str] = field(default_factory=list)
    spokespersons: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EvaluationPriorities:
    questions: list[str]
