"""RSS-Feeds laden und in Artikel umwandeln."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from html import unescape
from zoneinfo import ZoneInfo

import feedparser

from src.models.schemas import Article, Settings, Source

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    if not text:
        return ""
    cleaned = unescape(_HTML_TAG_RE.sub(" ", text))
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def _parse_entry_date(entry: feedparser.FeedParserDict) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return datetime(*parsed[:6], tzinfo=ZoneInfo("UTC"))
    return None


def _entry_url(entry: feedparser.FeedParserDict) -> str | None:
    link = getattr(entry, "link", None)
    if link:
        return link.strip()
    links = getattr(entry, "links", [])
    for item in links:
        if item.get("rel") == "alternate" and item.get("href"):
            return item["href"].strip()
    return None


def _entry_title(entry: feedparser.FeedParserDict) -> str:
    title = getattr(entry, "title", "") or ""
    return _strip_html(title)


def _entry_description(entry: feedparser.FeedParserDict) -> str:
    for attr in ("summary", "description", "content"):
        value = getattr(entry, attr, None)
        if not value:
            continue
        if isinstance(value, list) and value:
            value = value[0].get("value", "")
        text = _strip_html(str(value))
        if text:
            return text[:2000]
    return ""


def fetch_articles(
    sources: list[Source],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> tuple[list[Article], list[str]]:
    """Lädt Artikel aus allen Quellen und filtert nach Lookback-Fenster."""
    tz = ZoneInfo(settings.timezone)
    reference = (now or datetime.now(tz=tz)).astimezone(tz)
    cutoff = reference - timedelta(hours=settings.lookback_hours)

    articles: list[Article] = []
    warnings: list[str] = []

    for source in sources:
        try:
            feed = feedparser.parse(
                source.feed_url,
                agent="Themenradar/0.1 (+https://github.com/)",
            )
        except Exception as exc:
            msg = f"Feed '{source.name}' konnte nicht geladen werden: {exc}"
            warnings.append(msg)
            continue

        if getattr(feed, "bozo", False) and not feed.entries:
            msg = f"Feed '{source.name}' ist fehlerhaft oder leer."
            warnings.append(msg)
            continue

        for entry in feed.entries:
            title = _entry_title(entry)
            url = _entry_url(entry)
            published_at = _parse_entry_date(entry)

            if not title or not url:
                continue

            if published_at is None:
                warnings.append(
                    f"Artikel ohne Datum übersprungen: '{title}' ({source.name})"
                )
                continue

            published_local = published_at.astimezone(tz)
            if published_local < cutoff:
                continue

            articles.append(
                Article(
                    id=Article.make_id(url),
                    title=title,
                    source_name=source.name,
                    source_type=source.type,
                    published_at=published_local,
                    description=_entry_description(entry),
                    url=url,
                    source_priority=source.priority,
                    source_focus=list(source.focus),
                    source_role=source.source_role,
                )
            )

    articles.sort(key=lambda a: a.published_at, reverse=True)
    return articles, warnings
