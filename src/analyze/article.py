"""Phase 1: Einzelanalyse von Artikeln per LLM."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.analyze.cache import (
    DEFAULT_CACHE_PATH,
    get_cached_analysis,
    load_cache,
    save_cache,
    store_analysis,
)
from src.models.schemas import Article, ArticleAnalysis, Settings
from src.utils.llm import LLMClient

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[2] / "config" / "prompts" / "article_analysis.md"


@dataclass
class AnalysisRunResult:
    analyses: dict[str, ArticleAnalysis]
    cached_count: int = 0
    analyzed_count: int = 0
    failed_count: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def _validate_analysis_payload(data: dict) -> ArticleAnalysis:
    required = ("summary", "main_topics", "keywords", "environmental_links")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"LLM-Antwort unvollständig, fehlend: {', '.join(missing)}")

    def _as_str_list(value: object, field: str) -> list[str]:
        if not isinstance(value, list):
            raise ValueError(f"Feld '{field}' muss eine Liste sein")
        return [str(item).strip() for item in value if str(item).strip()]

    summary = str(data["summary"]).strip()
    if not summary:
        raise ValueError("summary darf nicht leer sein")

    return ArticleAnalysis(
        article_id="",
        summary=summary,
        main_topics=_as_str_list(data["main_topics"], "main_topics"),
        keywords=_as_str_list(data["keywords"], "keywords"),
        environmental_links=_as_str_list(data["environmental_links"], "environmental_links"),
    )


def _build_user_prompt(article: Article) -> str:
    focus = ", ".join(article.source_focus) if article.source_focus else "–"
    description = article.description or "(keine Beschreibung)"

    return (
        f"Titel: {article.title}\n"
        f"Quelle: {article.source_name} ({article.source_type})\n"
        f"Quellenfokus: {focus}\n"
        f"Veröffentlicht: {article.published_at.isoformat()}\n"
        f"Beschreibung: {description}\n"
        f"URL: {article.url}"
    )


def analyze_article(
    article: Article,
    llm: LLMClient,
    settings: Settings,
) -> ArticleAnalysis:
    """Einzelnen Artikel per LLM analysieren."""
    model = settings.llm.get("models", {}).get("article_analysis", "gpt-4o-mini")
    payload = llm.complete_json(
        model=model,
        system_prompt=_load_system_prompt(),
        user_prompt=_build_user_prompt(article),
    )
    analysis = _validate_analysis_payload(payload)
    analysis.article_id = article.id
    analysis.analyzed_at = datetime.now(ZoneInfo(settings.timezone))
    return analysis


def analyze_articles(
    articles: list[Article],
    settings: Settings,
    *,
    llm: LLMClient | None = None,
    cache_path: Path = DEFAULT_CACHE_PATH,
    use_cache: bool = True,
    limit: int | None = None,
) -> AnalysisRunResult:
    """Analysiert Artikel mit Cache. Fehler pro Artikel werden protokolliert."""
    if llm is None:
        llm = LLMClient(settings)

    cache = load_cache(cache_path) if use_cache else {"version": 1, "entries": {}}
    result = AnalysisRunResult(analyses={})

    targets = articles[:limit] if limit else articles
    logger.info("Phase 1: %d Artikel zu analysieren …", len(targets))

    for i, article in enumerate(targets, start=1):
        if use_cache:
            cached = get_cached_analysis(cache, article.url)
            if cached:
                cached.article_id = article.id
                result.analyses[article.id] = cached
                result.cached_count += 1
                logger.debug("Cache-Treffer: %s", article.title[:60])
                continue

        try:
            analysis = analyze_article(article, llm, settings)
            result.analyses[article.id] = analysis
            result.analyzed_count += 1

            if use_cache:
                store_analysis(cache, article.url, analysis)
                save_cache(cache, cache_path)

            logger.info(
                "[%d/%d] Analysiert: %s",
                i,
                len(targets),
                article.title[:70],
            )
        except Exception as exc:
            msg = f"Analyse fehlgeschlagen fuer '{article.title}': {exc}"
            logger.warning(msg)
            result.errors.append(msg)
            result.failed_count += 1

    logger.info(
        "Phase 1 abgeschlossen: %d neu, %d aus Cache, %d Fehler",
        result.analyzed_count,
        result.cached_count,
        result.failed_count,
    )
    return result


def analysis_to_dict(analysis: ArticleAnalysis) -> dict:
    return {
        "article_id": analysis.article_id,
        "summary": analysis.summary,
        "main_topics": analysis.main_topics,
        "keywords": analysis.keywords,
        "environmental_links": analysis.environmental_links,
        "analyzed_at": analysis.analyzed_at.isoformat() if analysis.analyzed_at else None,
    }
