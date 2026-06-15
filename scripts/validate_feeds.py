#!/usr/bin/env python3
"""RSS-Feed-Validierung: Erreichbarkeit, Fehler und Artikelanzahl prüfen."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import feedparser  # noqa: E402
import yaml  # noqa: E402

from src.fetch.rss import fetch_articles  # noqa: E402
from src.utils.config import load_settings, parse_source  # noqa: E402

CONFIG_DIR = ROOT / "config"
SOURCES_PATH = CONFIG_DIR / "sources.yaml"


@dataclass
class FeedCheckResult:
    name: str
    type: str
    feed_url: str
    priority: int | None = None
    focus: list[str] = field(default_factory=list)
    status: str = "unknown"
    http_status: int | None = None
    reachable: bool = False
    parse_ok: bool = False
    total_entries: int = 0
    articles_in_lookback: int = 0
    error: str | None = None
    feed_title: str | None = None


def _load_sources_raw() -> tuple[list[dict] | None, str | None]:
    try:
        with SOURCES_PATH.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        return None, f"YAML-Syntaxfehler in sources.yaml: {exc}"
    except OSError as exc:
        return None, str(exc)

    if not data or "sources" not in data:
        return None, "sources.yaml enthält keine 'sources'-Liste."

    return data["sources"], None


def _check_single_feed(entry: dict, lookback_hours: int) -> FeedCheckResult:
    name = entry.get("name", "Unbekannt")
    result = FeedCheckResult(
        name=name,
        type=entry.get("type", "?"),
        feed_url=entry.get("feed_url", ""),
        priority=entry.get("priority"),
        focus=entry.get("focus") or [],
    )

    if not result.feed_url or result.feed_url == "RSS_URL_PRUEFEN":
        result.status = "invalid_url"
        result.error = "Keine gültige Feed-URL konfiguriert."
        return result

    try:
        feed = feedparser.parse(
            result.feed_url,
            agent="Themenradar-FeedValidator/0.1",
        )
    except Exception as exc:
        result.status = "fetch_error"
        result.error = str(exc)
        return result

    result.http_status = getattr(feed, "status", None)
    result.reachable = result.http_status in (200, 301, 302) or bool(feed.entries)
    result.total_entries = len(feed.entries)
    result.feed_title = getattr(getattr(feed, "feed", None), "title", None)

    if getattr(feed, "bozo", False):
        exc = getattr(feed, "bozo_exception", None)
        if exc and not feed.entries:
            result.status = "parse_error"
            result.error = str(exc)
            return result
        if exc:
            result.error = f"Parse-Warnung: {exc}"

    if not feed.entries:
        result.status = "empty"
        result.error = result.error or "Feed erreichbar, aber keine Einträge."
        return result

    result.parse_ok = True

    try:
        source = parse_source(entry)
        settings = load_settings()
        articles, _ = fetch_articles([source], settings)
        result.articles_in_lookback = len(articles)
        result.status = "ok"
    except ValueError as exc:
        result.status = "config_error"
        result.error = str(exc)
    except Exception as exc:
        result.status = "filter_error"
        result.error = f"Artikel konnten nicht gefiltert werden: {exc}"

    return result


def validate_all() -> dict:
    settings = load_settings()
    sources_raw, config_error = _load_sources_raw()

    report: dict = {
        "generated_at": datetime.now().isoformat(),
        "lookback_hours": settings.lookback_hours,
        "config_error": config_error,
        "summary": {
            "total": 0,
            "ok": 0,
            "failed": 0,
            "articles_in_lookback_total": 0,
        },
        "feeds": [],
    }

    if config_error or not sources_raw:
        return report

    results = [_check_single_feed(entry, settings.lookback_hours) for entry in sources_raw]
    report["feeds"] = [asdict(r) for r in results]
    report["summary"]["total"] = len(results)
    report["summary"]["ok"] = sum(1 for r in results if r.status == "ok")
    report["summary"]["failed"] = sum(1 for r in results if r.status != "ok")
    report["summary"]["articles_in_lookback_total"] = sum(
        r.articles_in_lookback for r in results
    )
    return report


def _print_text_report(report: dict) -> None:
    print("=" * 60)
    print("RSS-FEED VALIDIERUNG – WWF Themenradar")
    print("=" * 60)
    print(f"Lookback: {report['lookback_hours']} h")
    print()

    if report["config_error"]:
        print(f"FEHLER: {report['config_error']}")
        print()
        print("Bitte sources.yaml auf YAML-Syntax prüfen (Listen mit '-' statt '*').")
        return

    summary = report["summary"]
    print(
        f"Quellen gesamt: {summary['total']}  |  "
        f"OK: {summary['ok']}  |  "
        f"Fehler: {summary['failed']}  |  "
        f"Artikel (24h): {summary['articles_in_lookback_total']}"
    )
    print("-" * 60)

    for feed in report["feeds"]:
        status_icon = "OK" if feed["status"] == "ok" else "FEHLER"
        print(f"[{status_icon}] {feed['name']} ({feed['type']}, Prio {feed['priority']})")
        print(f"       URL: {feed['feed_url']}")
        if feed["feed_title"]:
            print(f"       Feed-Titel: {feed['feed_title']}")
        if feed["http_status"]:
            print(f"       HTTP: {feed['http_status']}")
        print(f"       Einträge gesamt: {feed['total_entries']}")
        print(f"       Artikel im Lookback: {feed['articles_in_lookback']}")
        if feed["focus"]:
            print(f"       Fokus: {', '.join(feed['focus'])}")
        if feed["error"]:
            print(f"       Fehler: {feed['error']}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="RSS-Feeds validieren")
    parser.add_argument(
        "-o", "--output",
        help="JSON-Bericht speichern (optional)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Nur JSON auf stdout ausgeben",
    )
    args = parser.parse_args()

    report = validate_all()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_text_report(report)

    if args.output:
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    has_config_error = bool(report["config_error"])
    has_feed_errors = report["summary"]["failed"] > 0
    return 1 if has_config_error or has_feed_errors else 0


if __name__ == "__main__":
    sys.exit(main())
