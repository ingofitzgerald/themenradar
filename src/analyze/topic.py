"""Phase 2: Themenbewertung und Pressechancen."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.models.schemas import (
    Article,
    ArticleAnalysis,
    EvaluationPriorities,
    Organization,
    Settings,
    TopicAnalysis,
    TopicCluster,
    TopicScores,
)
from src.scoring.overall import compute_overall_score
from src.scoring.source_metrics import enrich_cluster
from src.utils.config import load_evaluation_priorities, load_organization
from src.utils.llm import LLMClient

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[2] / "config" / "prompts" / "topic_analysis.md"


@dataclass
class TopicRunResult:
    topics: list[TopicAnalysis] = field(default_factory=list)
    clusters: list[TopicCluster] = field(default_factory=list)
    analyzed_count: int = 0
    failed_count: int = 0
    errors: list[str] = field(default_factory=list)


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def _as_str_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"Feld '{field_name}' muss eine Liste sein")
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_score(value: object, field_name: str) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Ungültiger Score für '{field_name}'") from exc
    return max(1.0, min(10.0, score))


def _validate_topic_payload(data: dict, questions: list[str]) -> dict:
    required_top = (
        "scores",
        "why_relevant",
        "narratives",
        "conflict_lines",
        "target_media",
        "press_opportunity",
        "risks",
        "evaluation_answers",
    )
    missing = [k for k in required_top if k not in data]
    if missing:
        raise ValueError(f"LLM-Antwort unvollständig: {', '.join(missing)}")

    scores_raw = data["scores"]
    if not isinstance(scores_raw, dict):
        raise ValueError("scores muss ein Objekt sein")

    for key in ("wwf_relevance", "media_attention", "political_relevance"):
        if key not in scores_raw:
            raise ValueError(f"Score '{key}' fehlt")

    press = data["press_opportunity"]
    if not isinstance(press, dict):
        raise ValueError("press_opportunity muss ein Objekt sein")
    for key in ("story", "perspective", "experts", "regional_hooks"):
        if not str(press.get(key, "")).strip():
            raise ValueError(f"press_opportunity.{key} fehlt")

    eval_answers = data.get("evaluation_answers", {})
    if not isinstance(eval_answers, dict):
        raise ValueError("evaluation_answers muss ein Objekt sein")

    normalized_answers = {}
    for q in questions:
        normalized_answers[q] = str(eval_answers.get(q, "Keine Einschätzung")).strip()

    return {
        "scores": {
            "wwf_relevance": _parse_score(scores_raw["wwf_relevance"], "wwf_relevance"),
            "media_attention": _parse_score(scores_raw["media_attention"], "media_attention"),
            "political_relevance": _parse_score(
                scores_raw["political_relevance"], "political_relevance"
            ),
        },
        "why_relevant": str(data["why_relevant"]).strip(),
        "narratives": _as_str_list(data["narratives"], "narratives"),
        "conflict_lines": _as_str_list(data["conflict_lines"], "conflict_lines"),
        "target_media": _as_str_list(data["target_media"], "target_media"),
        "press_opportunity": {k: str(press[k]).strip() for k in press},
        "risks": _as_str_list(data["risks"], "risks"),
        "evaluation_answers": normalized_answers,
    }


def _format_org_context(org: Organization) -> str:
    lines = [
        f"Organisation: {org.name}",
        f"Mission: {org.mission}",
        f"Expertise: {', '.join(org.expertise[:12])}",
        f"Regionen: {', '.join(org.regions[:6])}",
        f"Projekttypen: {', '.join(org.project_types[:8])}",
        f"Medienziele: {', '.join(org.media_goals[:5])}",
        f"Relevanzsignale: {', '.join(org.high_relevance_signals[:10])}",
        f"Vermeiden: {', '.join(org.avoid)}",
        f"Tonalität: {org.tone}",
    ]
    return "\n".join(lines)


def _build_topic_user_prompt(
    cluster: TopicCluster,
    articles: list[Article],
    analyses: dict[str, ArticleAnalysis],
    org: Organization,
    priorities: EvaluationPriorities,
    source_scores: TopicScores,
) -> str:
    article_map = {a.id: a for a in articles}
    lines = [
        _format_org_context(org),
        "",
        "Bewertungsfragen:",
    ]
    for q in priorities.questions:
        lines.append(f"- {q}")

    lines.extend(
        [
            "",
            f"Thema: {cluster.label}",
            f"Artikel im Cluster: {cluster.article_count}",
            f"Quellen: {', '.join(cluster.source_names)}",
            f"Quellentypen: {', '.join(cluster.source_types)}",
            f"Fokusbereiche: {', '.join(cluster.focus_areas)}",
            f"Quellenprioritaet-Score: {source_scores.source_priority_score}/10",
            f"Quellenvielfalt-Score: {source_scores.source_diversity_score}/10",
            f"Medienaufmerksamkeit (objektiv): {source_scores.breakdown.get('media_attention_objective', 0)}/10",
            "",
            "Artikel in diesem Thema:",
        ]
    )

    for aid in cluster.article_ids:
        article = article_map.get(aid)
        analysis = analyses.get(aid)
        if not article or not analysis:
            continue
        lines.append(
            f"- {article.title} ({article.source_name}, {article.source_type})\n"
            f"  {analysis.summary}\n"
            f"  Themen: {', '.join(analysis.main_topics)}\n"
            f"  Umweltbezug: {', '.join(analysis.environmental_links) or 'keiner'}"
        )

    return "\n".join(lines)


def analyze_topic(
    cluster: TopicCluster,
    articles: list[Article],
    analyses: dict[str, ArticleAnalysis],
    settings: Settings,
    llm: LLMClient,
    *,
    org: Organization | None = None,
    priorities: EvaluationPriorities | None = None,
) -> TopicAnalysis:
    org = org or load_organization()
    priorities = priorities or load_evaluation_priorities()

    enriched, source_scores = enrich_cluster(cluster, articles, settings)
    model = settings.llm.get("models", {}).get("topic_analysis", "gpt-4o-mini")

    payload = llm.complete_json(
        model=model,
        system_prompt=_load_system_prompt(),
        user_prompt=_build_topic_user_prompt(
            enriched, articles, analyses, org, priorities, source_scores
        ),
    )
    parsed = _validate_topic_payload(payload, priorities.questions)

    llm_scores = TopicScores(
        wwf_relevance=parsed["scores"]["wwf_relevance"],
        media_attention=parsed["scores"]["media_attention"],
        political_relevance=parsed["scores"]["political_relevance"],
    )
    final_scores = compute_overall_score(llm_scores, source_scores, settings)

    return TopicAnalysis(
        topic_id=enriched.id,
        why_relevant=parsed["why_relevant"],
        narratives=parsed["narratives"],
        conflict_lines=parsed["conflict_lines"],
        target_media=parsed["target_media"],
        press_opportunity=parsed["press_opportunity"],
        risks=parsed["risks"],
        evaluation_answers=parsed["evaluation_answers"],
        scores=final_scores,
    )


def analyze_topics(
    clusters: list[TopicCluster],
    articles: list[Article],
    analyses: dict[str, ArticleAnalysis],
    settings: Settings,
    *,
    llm: LLMClient | None = None,
    limit: int | None = None,
) -> TopicRunResult:
    """Bewertet alle Themencluster. Fehler pro Thema werden protokolliert."""
    if llm is None:
        llm = LLMClient(settings)

    result = TopicRunResult()
    targets = clusters[:limit] if limit else clusters

    logger.info("Phase 2: %d Themen zu bewerten …", len(targets))

    for i, cluster in enumerate(targets, start=1):
        try:
            topic = analyze_topic(cluster, articles, analyses, settings, llm)
            enriched, _ = enrich_cluster(cluster, articles, settings)
            result.topics.append(topic)
            result.clusters.append(enriched)
            result.analyzed_count += 1
            logger.info(
                "[%d/%d] Thema bewertet: %s (Gesamtwert %.1f)",
                i,
                len(targets),
                cluster.label[:60],
                topic.scores.overall_score,
            )
        except Exception as exc:
            msg = f"Themenanalyse fehlgeschlagen fuer '{cluster.label}': {exc}"
            logger.warning(msg)
            result.errors.append(msg)
            result.failed_count += 1

    return result


def topic_analysis_to_dict(
    cluster: TopicCluster,
    analysis: TopicAnalysis,
    articles: list[Article],
    analyses: dict[str, ArticleAnalysis],
) -> dict:
    article_map = {a.id: a for a in articles}
    sources = []
    for aid in cluster.article_ids:
        article = article_map.get(aid)
        if article:
            sources.append(
                {
                    "title": article.title,
                    "source_name": article.source_name,
                    "source_type": article.source_type,
                    "url": article.url,
                    "published_at": article.published_at.isoformat(),
                }
            )

    return {
        "id": cluster.id,
        "label": cluster.label,
        "article_count": cluster.article_count,
        "source_count": cluster.source_count,
        "source_names": cluster.source_names,
        "source_types": cluster.source_types,
        "focus_areas": cluster.focus_areas,
        "scores": analysis.scores.breakdown,
        "overall_score": analysis.scores.overall_score,
        "why_relevant": analysis.why_relevant,
        "narratives": analysis.narratives,
        "conflict_lines": analysis.conflict_lines,
        "target_media": analysis.target_media,
        "press_opportunity": analysis.press_opportunity,
        "risks": analysis.risks,
        "evaluation_answers": analysis.evaluation_answers,
        "articles": sources,
    }
