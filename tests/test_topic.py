"""Tests für Phase-2-Themenanalyse."""

from datetime import datetime, timezone

import pytest

from src.analyze.topic import _validate_topic_payload, analyze_topics
from src.models.schemas import Article, ArticleAnalysis, Settings, TopicCluster

TZ = timezone.utc

QUESTIONS = [
    "Kann der WWF glaubwürdig Expertise beitragen?",
    "Gibt es politischen Handlungsbedarf?",
]


def _settings() -> Settings:
    return Settings(
        lookback_hours=24,
        timezone="Europe/Berlin",
        language="de",
        llm={"models": {"topic_analysis": "gpt-4o-mini"}},
        scoring={"high_priority_threshold": 8},
    )


def _article(aid: str) -> Article:
    return Article(
        id=aid,
        title="EU Klimapolitik",
        source_name="Tagesschau",
        source_type="media",
        published_at=datetime(2026, 6, 15, 8, 0, tzinfo=TZ),
        description="Test",
        url=f"https://example.com/{aid}",
        source_priority=8,
        source_focus=["climate"],
        source_role="agenda",
    )


def _analysis(aid: str) -> ArticleAnalysis:
    return ArticleAnalysis(
        article_id=aid,
        summary="EU beschließt Klimaziele.",
        main_topics=["EU-Klimapolitik"],
        keywords=["EU"],
        environmental_links=["Klimaschutz"],
    )


class FakeLLM:
    def complete_json(self, **kwargs) -> dict:
        return {
            "scores": {
                "wwf_relevance": 9,
                "media_attention": 8,
                "political_relevance": 9,
            },
            "why_relevant": "EU-Klimapolitik ist aktuell.",
            "narratives": ["Ambition vs. Umsetzung"],
            "conflict_lines": ["Industrie vs. Klimaschutz"],
            "target_media": ["Tagesschau", "FAZ"],
            "press_opportunity": {
                "story": "Umsetzungslücke in Deutschland",
                "perspective": "WWF als Umsetzungsexperte",
                "experts": "Klimapolitik-Referent/in",
                "regional_hooks": "Bundesländer mit verfehlten Zielen",
            },
            "risks": ["Zu technisch"],
            "evaluation_answers": {
                QUESTIONS[0]: "Ja, starke EU-Expertise.",
                QUESTIONS[1]: "Ja, Handlungsbedarf hoch.",
            },
        }


def test_validate_topic_payload():
    parsed = _validate_topic_payload(
        FakeLLM().complete_json(),
        QUESTIONS,
    )
    assert parsed["scores"]["wwf_relevance"] == 9
    assert "story" in parsed["press_opportunity"]


def test_validate_topic_payload_missing_score():
    with pytest.raises(ValueError):
        _validate_topic_payload({"scores": {}}, QUESTIONS)


def test_analyze_topics_with_fake_llm():
    clusters = [
        TopicCluster(id="t1", label="EU-Klima", article_ids=["a1", "a2"]),
    ]
    articles = [_article("a1"), _article("a2")]
    analyses = {"a1": _analysis("a1"), "a2": _analysis("a2")}

    result = analyze_topics(
        clusters,
        articles,
        analyses,
        _settings(),
        llm=FakeLLM(),  # type: ignore[arg-type]
    )

    assert result.analyzed_count == 1
    assert result.topics[0].scores.overall_score > 0
    assert result.topics[0].press_opportunity["story"]
