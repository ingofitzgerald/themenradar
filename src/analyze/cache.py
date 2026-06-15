"""Persistenter Cache für Artikelanalysen."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.models.schemas import ArticleAnalysis

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
DEFAULT_CACHE_PATH = CACHE_DIR / "articles.json"


def _empty_cache() -> dict:
    return {"version": 1, "entries": {}}


def load_cache(path: Path = DEFAULT_CACHE_PATH) -> dict:
    if not path.exists():
        return _empty_cache()
    data = json.loads(path.read_text(encoding="utf-8"))
    if "entries" not in data:
        return _empty_cache()
    return data


def save_cache(cache: dict, path: Path = DEFAULT_CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def get_cached_analysis(cache: dict, url: str) -> ArticleAnalysis | None:
    entry = cache.get("entries", {}).get(url)
    if not entry:
        return None
    analyzed_at = entry.get("analyzed_at")
    return ArticleAnalysis(
        article_id=entry.get("article_id", ""),
        summary=entry.get("summary", ""),
        main_topics=entry.get("main_topics", []),
        keywords=entry.get("keywords", []),
        environmental_links=entry.get("environmental_links", []),
        analyzed_at=datetime.fromisoformat(analyzed_at) if analyzed_at else None,
    )


def store_analysis(
    cache: dict,
    url: str,
    analysis: ArticleAnalysis,
) -> None:
    cache.setdefault("entries", {})[url] = {
        "article_id": analysis.article_id,
        "summary": analysis.summary,
        "main_topics": analysis.main_topics,
        "keywords": analysis.keywords,
        "environmental_links": analysis.environmental_links,
        "analyzed_at": (
            analysis.analyzed_at.isoformat()
            if analysis.analyzed_at
            else datetime.now().isoformat()
        ),
    }
