"""Tests für Gesamtwert-Berechnung."""

from src.models.schemas import Settings, TopicScores
from src.scoring.overall import compute_hybrid_media_attention, compute_overall_score


def _settings() -> Settings:
    return Settings(
        lookback_hours=24,
        timezone="Europe/Berlin",
        language="de",
        scoring={
            "weights": {
                "wwf_relevance": 0.30,
                "media_attention": 0.25,
                "political_relevance": 0.20,
                "source_priority": 0.15,
                "source_diversity": 0.10,
            },
            "media_attention": {
                "objective_weight": 0.5,
                "llm_weight": 0.5,
            },
        },
    )


def test_hybrid_media_attention():
    score = compute_hybrid_media_attention(8.0, 6.0, _settings())
    assert score == 7.0


def test_overall_score_weighted_sum():
    llm = TopicScores(wwf_relevance=10, media_attention=10, political_relevance=10)
    source = TopicScores(
        source_priority_score=10,
        source_diversity_score=10,
        media_attention=10,
        breakdown={"media_attention_objective": 10},
    )

    result = compute_overall_score(llm, source, _settings())
    assert result.overall_score == 10.0
    assert "weighted" in result.breakdown
    assert result.breakdown["wwf_relevance"] == 10.0
