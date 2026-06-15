"""Gesamtwert-Berechnung aus LLM- und Quellen-Scores."""

from __future__ import annotations

from src.models.schemas import Settings, TopicScores


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(10.0, value)), 2)


def _score_weight(settings: Settings, key: str, default: float) -> float:
    return float(settings.scoring.get("weights", {}).get(key, default))


def compute_hybrid_media_attention(
    llm_score: float,
    objective_score: float,
    settings: Settings,
) -> float:
    cfg = settings.scoring.get("media_attention", {})
    obj_weight = float(cfg.get("objective_weight", 0.5))
    llm_weight = float(cfg.get("llm_weight", 0.5))
    total = obj_weight + llm_weight
    if total == 0:
        return _clamp_score(llm_score)
    hybrid = (obj_weight * objective_score + llm_weight * llm_score) / total
    return _clamp_score(hybrid)


def compute_overall_score(
    llm_scores: TopicScores,
    source_scores: TopicScores,
    settings: Settings,
) -> TopicScores:
    """
    Kombiniert LLM-Bewertungen mit deterministischen Quellenmetriken.

    Gewichte (settings.yaml):
      30% WWF-Relevanz
      25% Medienaufmerksamkeit (hybrid)
      20% politische Relevanz
      15% Quellenpriorität
      10% Quellenvielfalt
    """
    w_wwf = _score_weight(settings, "wwf_relevance", 0.30)
    w_media = _score_weight(settings, "media_attention", 0.25)
    w_political = _score_weight(settings, "political_relevance", 0.20)
    w_priority = _score_weight(settings, "source_priority", 0.15)
    w_diversity = _score_weight(settings, "source_diversity", 0.10)

    media_objective = source_scores.breakdown.get(
        "media_attention_objective",
        source_scores.media_attention,
    )
    media_hybrid = compute_hybrid_media_attention(
        llm_scores.media_attention,
        media_objective,
        settings,
    )

    components = {
        "wwf_relevance": _clamp_score(llm_scores.wwf_relevance),
        "media_attention": media_hybrid,
        "political_relevance": _clamp_score(llm_scores.political_relevance),
        "source_priority": _clamp_score(source_scores.source_priority_score),
        "source_diversity": _clamp_score(source_scores.source_diversity_score),
    }

    weighted = {
        key: round(components[key] * weight, 3)
        for key, weight in [
            ("wwf_relevance", w_wwf),
            ("media_attention", w_media),
            ("political_relevance", w_political),
            ("source_priority", w_priority),
            ("source_diversity", w_diversity),
        ]
    }

    overall = round(sum(weighted.values()), 2)

    breakdown = {
        **components,
        "media_attention_llm": _clamp_score(llm_scores.media_attention),
        "media_attention_objective": _clamp_score(media_objective),
        "weighted": weighted,
        "overall_score": overall,
    }

    return TopicScores(
        wwf_relevance=components["wwf_relevance"],
        media_attention=media_hybrid,
        political_relevance=components["political_relevance"],
        source_priority_score=components["source_priority"],
        source_diversity_score=components["source_diversity"],
        overall_score=overall,
        breakdown=breakdown,
    )
