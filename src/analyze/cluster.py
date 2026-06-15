"""Themenclustering per LLM (Batch)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from src.models.schemas import Article, ArticleAnalysis, Settings, TopicCluster, TopicScores
from src.scoring.source_metrics import enrich_cluster
from src.utils.llm import LLMClient

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[2] / "config" / "prompts" / "clustering.md"


@dataclass
class ClusterRunResult:
    clusters: list[TopicCluster]
    scores: dict[str, TopicScores] = field(default_factory=dict)
    unassigned_article_ids: list[str] = field(default_factory=list)
    used_fallback: bool = False
    errors: list[str] = field(default_factory=list)


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def _make_topic_id(label: str, index: int) -> str:
    digest = sha256(f"{label}-{index}".encode()).hexdigest()[:8]
    return f"topic-{digest}"


def _normalize_topic(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _build_user_prompt(
    articles: list[Article],
    analyses: dict[str, ArticleAnalysis],
) -> str:
    lines = ["Artikel des Tages:\n"]
    for article in articles:
        analysis = analyses.get(article.id)
        if not analysis:
            continue
        topics = ", ".join(analysis.main_topics) or "–"
        env = ", ".join(analysis.environmental_links) or "keine"
        lines.append(
            f"- id: {article.id}\n"
            f"  titel: {article.title}\n"
            f"  quelle: {article.source_name} ({article.source_type})\n"
            f"  summary: {analysis.summary}\n"
            f"  hauptthemen: {topics}\n"
            f"  umweltbezuege: {env}"
        )
    return "\n".join(lines)


def _validate_cluster_payload(
    data: dict,
    valid_ids: set[str],
) -> list[tuple[str, list[str]]]:
    if "topics" not in data or not isinstance(data["topics"], list):
        raise ValueError("LLM-Antwort muss 'topics'-Liste enthalten")

    clusters: list[tuple[str, list[str]]] = []
    seen_ids: set[str] = set()

    for entry in data["topics"]:
        if not isinstance(entry, dict):
            raise ValueError("Jedes Topic muss ein Objekt sein")
        label = str(entry.get("label", "")).strip()
        article_ids = entry.get("article_ids", [])
        if not label:
            raise ValueError("Cluster-Label fehlt")
        if not isinstance(article_ids, list):
            raise ValueError(f"article_ids muss Liste sein bei '{label}'")

        ids = []
        for raw_id in article_ids:
            aid = str(raw_id).strip()
            if aid not in valid_ids:
                logger.warning("Unbekannte article_id ignoriert: %s", aid)
                continue
            if aid in seen_ids:
                logger.warning("Doppelte Zuordnung ignoriert: %s", aid)
                continue
            seen_ids.add(aid)
            ids.append(aid)

        if ids:
            clusters.append((label, ids))

    if not clusters:
        raise ValueError("Keine gültigen Cluster in LLM-Antwort")

    return clusters


def cluster_by_topic_fallback(
    articles: list[Article],
    analyses: dict[str, ArticleAnalysis],
) -> list[tuple[str, list[str]]]:
    """Regelbasiertes Fallback: Gruppierung nach erstem Hauptthema."""
    buckets: dict[str, list[str]] = {}

    for article in articles:
        analysis = analyses.get(article.id)
        if not analysis:
            continue
        key = _normalize_topic(analysis.main_topics[0]) if analysis.main_topics else "sonstige meldungen"
        buckets.setdefault(key, []).append(article.id)

    clusters = []
    for key, ids in sorted(buckets.items(), key=lambda x: -len(x[1])):
        label = key.title() if key != "sonstige meldungen" else "Sonstige Meldungen"
        clusters.append((label, ids))
    return clusters


def _build_clusters(
    grouped: list[tuple[str, list[str]]],
    all_ids: set[str],
) -> list[TopicCluster]:
    assigned: set[str] = set()
    clusters: list[TopicCluster] = []

    for index, (label, article_ids) in enumerate(grouped, start=1):
        assigned.update(article_ids)
        clusters.append(
            TopicCluster(
                id=_make_topic_id(label, index),
                label=label,
                article_ids=article_ids,
            )
        )

    missing = sorted(all_ids - assigned)
    if missing:
        clusters.append(
            TopicCluster(
                id=_make_topic_id("Nicht zugeordnete Meldungen", len(clusters) + 1),
                label="Nicht zugeordnete Meldungen",
                article_ids=missing,
            )
        )

    return clusters


def cluster_articles_llm(
    articles: list[Article],
    analyses: dict[str, ArticleAnalysis],
    settings: Settings,
    llm: LLMClient,
) -> list[tuple[str, list[str]]]:
    model = settings.llm.get("models", {}).get("clustering", "gpt-4o-mini")
    max_topics = int(settings.report.get("max_topics", 15))

    eligible = [a for a in articles if a.id in analyses]
    valid_ids = {a.id for a in eligible}

    user_prompt = (
        f"Maximale Cluster-Anzahl: {max_topics}\n"
        f"Anzahl Artikel: {len(eligible)}\n\n"
        f"{_build_user_prompt(eligible, analyses)}"
    )

    payload = llm.complete_json(
        model=model,
        system_prompt=_load_system_prompt(),
        user_prompt=user_prompt,
    )
    return _validate_cluster_payload(payload, valid_ids)


def cluster_articles(
    articles: list[Article],
    analyses: dict[str, ArticleAnalysis],
    settings: Settings,
    *,
    llm: LLMClient | None = None,
    use_fallback: bool = False,
) -> ClusterRunResult:
    """Clustert analysierte Artikel und berechnet Quellenmetriken."""
    result = ClusterRunResult(clusters=[])

    eligible = [a for a in articles if a.id in analyses]
    if not eligible:
        result.errors.append("Keine analysierten Artikel zum Clustern vorhanden.")
        return result

    valid_ids = {a.id for a in eligible}
    grouped: list[tuple[str, list[str]]] = []

    if use_fallback:
        grouped = cluster_by_topic_fallback(eligible, analyses)
        result.used_fallback = True
    else:
        if llm is None:
            llm = LLMClient(settings)
        try:
            grouped = cluster_articles_llm(eligible, analyses, settings, llm)
        except Exception as exc:
            msg = f"LLM-Clustering fehlgeschlagen, Fallback aktiv: {exc}"
            logger.warning(msg)
            result.errors.append(msg)
            grouped = cluster_by_topic_fallback(eligible, analyses)
            result.used_fallback = True

    clusters = _build_clusters(grouped, valid_ids)
    result.unassigned_article_ids = []

    for cluster in clusters:
        enriched, scores = enrich_cluster(cluster, eligible, settings)
        result.clusters.append(enriched)
        result.scores[enriched.id] = scores

    logger.info(
        "Clustering abgeschlossen: %d Themen aus %d Artikeln%s",
        len(result.clusters),
        len(eligible),
        " (Fallback)" if result.used_fallback else "",
    )
    return result


def cluster_to_dict(cluster: TopicCluster, scores: TopicScores | None = None) -> dict:
    data = {
        "id": cluster.id,
        "label": cluster.label,
        "article_ids": cluster.article_ids,
        "article_count": cluster.article_count,
        "source_count": cluster.source_count,
        "source_names": cluster.source_names,
        "source_types": cluster.source_types,
        "focus_areas": cluster.focus_areas,
        "avg_source_priority": round(cluster.avg_source_priority, 2),
        "high_priority_source_count": cluster.high_priority_source_count,
        "source_type_diversity": cluster.source_type_diversity,
    }
    if scores:
        data["scores"] = scores.breakdown
    return data
