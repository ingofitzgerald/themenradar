"""Einstiegspunkt für den Themenradar."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.analyze.article import analysis_to_dict, analyze_articles
from src.analyze.cluster import cluster_articles, cluster_to_dict
from src.analyze.topic import analyze_topics, topic_analysis_to_dict
from src.fetch.rss import fetch_articles
from src.models.schemas import TopicCluster
from src.scoring.source_metrics import enrich_cluster
from src.report.builder import build_daily_report, load_topics_payload
from src.report.html import write_report
from src.scoring.summary import summarize_by_source
from src.utils.config import load_settings, load_sources_lenient
from src.utils.serialize import (
    analysis_from_dict,
    load_analyzed_run,
    load_articles_from_run,
    load_clustered_run,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "runs"
OUTPUT_DIR = ROOT / "output"


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )


def _fetch_articles_for_run(args, settings):
    """Artikel aus JSON-Datei oder per RSS-Fetch laden."""
    if getattr(args, "input", None):
        articles, _ = load_articles_from_run(Path(args.input))
        logging.info("Geladen: %d Artikel aus %s", len(articles), args.input)
        return articles, []
    sources, source_warnings = load_sources_lenient()
    articles, fetch_warnings = fetch_articles(sources, settings)
    return articles, source_warnings + fetch_warnings


def _analysis_run_to_json(
    articles: list,
    analyses: dict,
    warnings: list[str],
    settings,
    *,
    stats: dict | None = None,
) -> dict:
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz=tz)
    source_summary = [s.to_dict() for s in summarize_by_source(articles)]

    article_payload = []
    for article in articles:
        entry = article.to_dict()
        analysis = analyses.get(article.id)
        if analysis:
            entry["analysis"] = analysis_to_dict(analysis)
        article_payload.append(entry)

    payload = {
        "generated_at": now.isoformat(),
        "lookback_hours": settings.lookback_hours,
        "timezone": settings.timezone,
        "article_count": len(articles),
        "analyzed_count": len(analyses),
        "source_count": len(source_summary),
        "warnings": warnings,
        "source_summary": source_summary,
        "articles": article_payload,
    }
    if stats:
        payload["analysis_stats"] = stats
    return payload


def cmd_fetch_only(args: argparse.Namespace) -> int:
    settings = load_settings()
    sources, source_warnings = load_sources_lenient()

    logging.info(
        "Lade RSS-Feeds (%d Quellen, Lookback: %d h) …",
        len(sources),
        settings.lookback_hours,
    )

    articles, fetch_warnings = fetch_articles(sources, settings)
    all_warnings = source_warnings + fetch_warnings

    for warning in all_warnings:
        logging.warning(warning)

    payload = _analysis_run_to_json(articles, {}, all_warnings, settings)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logging.info("Ergebnis gespeichert: %s", output_path)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    logging.info("Fertig: %d Artikel im Lookback-Fenster.", len(articles))
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    settings = load_settings()
    articles, warnings = _fetch_articles_for_run(args, settings)

    for warning in warnings:
        logging.warning(warning)

    if not articles:
        logging.error("Keine Artikel zum Analysieren.")
        return 1

    try:
        result = analyze_articles(
            articles,
            settings,
            use_cache=not args.no_cache,
            limit=args.limit,
        )
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 1

    for error in result.errors:
        logging.warning(error)

    stats = {
        "cached": result.cached_count,
        "newly_analyzed": result.analyzed_count,
        "failed": result.failed_count,
    }

    payload = _analysis_run_to_json(
        articles,
        result.analyses,
        warnings + result.errors,
        settings,
        stats=stats,
    )

    output_path = Path(args.output) if args.output else DATA_DIR / "analyzed.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logging.info("Ergebnis gespeichert: %s", output_path)
    logging.info(
        "Analysiert: %d gesamt (%d neu, %d Cache, %d Fehler)",
        len(result.analyses),
        result.analyzed_count,
        result.cached_count,
        result.failed_count,
    )

    if args.print_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 1 if result.failed_count and not result.analyses else 0


def cmd_cluster(args: argparse.Namespace) -> int:
    settings = load_settings()
    warnings: list[str] = []
    analyses: dict = {}

    if args.input:
        input_path = Path(args.input)
        if _run_has_analyses(input_path):
            articles, analyses, _ = load_analyzed_run(input_path)
            logging.info(
                "Geladen: %d Artikel, %d Analysen aus %s",
                len(articles),
                len(analyses),
                args.input,
            )
        else:
            articles, payload = load_articles_from_run(input_path)
            for entry in payload.get("articles", []):
                if "analysis" in entry:
                    a = analysis_from_dict(entry["analysis"])
                    a.article_id = entry["id"]
                    analyses[entry["id"]] = a
            logging.info("Geladen: %d Artikel aus %s", len(articles), args.input)
    else:
        articles, warnings = _fetch_articles_for_run(args, settings)

    for warning in warnings:
        logging.warning(warning)

    if not analyses and not args.fallback_only:
        logging.info("Keine Analysen vorhanden — starte Phase 1 …")
        try:
            analysis_result = analyze_articles(
                articles,
                settings,
                use_cache=not args.no_cache,
                limit=args.limit,
            )
        except RuntimeError as exc:
            logging.error("%s", exc)
            return 1
        analyses = analysis_result.analyses
        warnings.extend(analysis_result.errors)

    if args.limit and analyses:
        limited_ids = {a.id for a in articles[: args.limit]}
        articles = [a for a in articles if a.id in limited_ids]
        analyses = {k: v for k, v in analyses.items() if k in limited_ids}

    if not analyses:
        logging.error(
            "Keine Artikelanalysen verfuegbar. "
            "Bitte zuerst 'analyze' ausfuehren oder --fallback-only nutzen."
        )
        return 1

    try:
        cluster_result = cluster_articles(
            articles,
            analyses,
            settings,
            use_fallback=args.fallback_only,
        )
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 1

    for error in cluster_result.errors:
        logging.warning(error)

    tz = ZoneInfo(settings.timezone)
    payload = {
        "generated_at": datetime.now(tz=tz).isoformat(),
        "topic_count": len(cluster_result.clusters),
        "article_count": len(analyses),
        "used_fallback": cluster_result.used_fallback,
        "warnings": warnings + cluster_result.errors,
        "topics": [
            cluster_to_dict(c, cluster_result.scores.get(c.id))
            for c in sorted(
                cluster_result.clusters,
                key=lambda c: (-c.article_count, c.label),
            )
        ],
    }

    output_path = Path(args.output) if args.output else DATA_DIR / "clustered.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logging.info("Ergebnis gespeichert: %s", output_path)
    logging.info("Themen: %d", len(cluster_result.clusters))

    if args.print_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 0


def _run_has_analyses(path: Path) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return any("analysis" in a for a in payload.get("articles", []))


def _rank_topics(topics_payload: list[dict], score_key: str, limit: int = 5) -> list[dict]:
    def _score(topic: dict) -> float:
        if score_key == "overall_score":
            return float(topic.get("overall_score", 0))
        return float(topic.get("scores", {}).get(score_key, 0))

    ranked = sorted(topics_payload, key=_score, reverse=True)
    return [
        {
            "id": t["id"],
            "label": t["label"],
            "score": _score(t),
        }
        for t in ranked[:limit]
    ]


def cmd_topics(args: argparse.Namespace) -> int:
    settings = load_settings()

    if not args.analyzed:
        logging.error("--analyzed ist erforderlich (Pfad zu analyzed.json).")
        return 1

    articles, analyses, _ = load_analyzed_run(Path(args.analyzed))
    logging.info(
        "Geladen: %d Artikel, %d Analysen aus %s",
        len(articles),
        len(analyses),
        args.analyzed,
    )

    clusters_path = Path(args.clusters) if args.clusters else DATA_DIR / "clustered.json"
    if not clusters_path.exists():
        logging.error("Cluster-Datei nicht gefunden: %s", clusters_path)
        return 1

    clusters, _ = load_clustered_run(clusters_path)
    logging.info("Geladen: %d Themen aus %s", len(clusters), clusters_path)

    try:
        result = analyze_topics(
            clusters,
            articles,
            analyses,
            settings,
            limit=args.limit,
        )
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 1

    for error in result.errors:
        logging.warning(error)

    cluster_map = {c.id: c for c in result.clusters}
    topics_payload = []
    for topic in result.topics:
        cluster = cluster_map.get(topic.topic_id)
        if cluster:
            topics_payload.append(
                topic_analysis_to_dict(cluster, topic, articles, analyses)
            )

    topics_payload.sort(key=lambda t: t.get("overall_score", 0), reverse=True)

    output_path = Path(args.output) if args.output else DATA_DIR / "topics.json"
    payload = _save_topics_payload(topics_payload, result.errors, settings, output_path)
    logging.info("Ergebnis gespeichert: %s", output_path)
    logging.info(
        "Themen bewertet: %d (%d Fehler)",
        result.analyzed_count,
        result.failed_count,
    )

    if args.print_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 1 if result.failed_count and not result.topics else 0


def _save_topics_payload(
    topics_payload: list[dict],
    result_errors: list[str],
    settings,
    output_path: Path,
) -> dict:
    top_n = int(settings.report.get("top_topics_count", 5))
    tz = ZoneInfo(settings.timezone)

    payload = {
        "generated_at": datetime.now(tz=tz).isoformat(),
        "topic_count": len(topics_payload),
        "warnings": result_errors,
        "rankings": {
            "top_by_overall": _rank_topics(topics_payload, "overall_score", top_n),
            "top_by_media_attention": _rank_topics(
                topics_payload, "media_attention", top_n
            ),
            "top_by_wwf_relevance": _rank_topics(
                topics_payload, "wwf_relevance", top_n
            ),
        },
        "topics": topics_payload,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def cmd_run(args: argparse.Namespace) -> int:
    """Vollständige Tages-Pipeline: Fetch → Analyse → Cluster → Topics → Report."""
    settings = load_settings()
    run_dir = DATA_DIR
    run_dir.mkdir(parents=True, exist_ok=True)

    sources, source_warnings = load_sources_lenient()
    logging.info("=== Schritt 1/5: RSS-Fetch (%d Quellen) ===", len(sources))

    articles, fetch_warnings = fetch_articles(sources, settings)
    all_warnings = source_warnings + fetch_warnings
    for warning in all_warnings:
        logging.warning(warning)

    if not articles:
        logging.error("Keine Artikel gefunden — Bericht abgebrochen.")
        return 1

    fetch_path = run_dir / "fetch.json"
    fetch_path.write_text(
        json.dumps(
            _analysis_run_to_json(articles, {}, all_warnings, settings),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logging.info("%d Artikel geladen.", len(articles))

    logging.info("=== Schritt 2/5: Phase 1 – Artikelanalyse ===")
    try:
        analysis_result = analyze_articles(
            articles,
            settings,
            use_cache=not args.no_cache,
            limit=args.limit,
        )
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 1

    all_warnings.extend(analysis_result.errors)
    if not analysis_result.analyses:
        logging.error("Keine Analysen — Bericht abgebrochen.")
        return 1

    analyzed_path = run_dir / "analyzed.json"
    analyzed_path.write_text(
        json.dumps(
            _analysis_run_to_json(
                articles,
                analysis_result.analyses,
                all_warnings,
                settings,
                stats={
                    "cached": analysis_result.cached_count,
                    "newly_analyzed": analysis_result.analyzed_count,
                    "failed": analysis_result.failed_count,
                },
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    logging.info("=== Schritt 3/5: Clustering ===")
    try:
        cluster_result = cluster_articles(
            articles,
            analysis_result.analyses,
            settings,
            use_fallback=args.fallback_only,
        )
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 1

    all_warnings.extend(cluster_result.errors)
    clustered_path = run_dir / "clustered.json"
    tz = ZoneInfo(settings.timezone)
    clustered_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(tz=tz).isoformat(),
                "topic_count": len(cluster_result.clusters),
                "article_count": len(analysis_result.analyses),
                "used_fallback": cluster_result.used_fallback,
                "warnings": all_warnings,
                "topics": [
                    cluster_to_dict(c, cluster_result.scores.get(c.id))
                    for c in sorted(
                        cluster_result.clusters,
                        key=lambda c: (-c.article_count, c.label),
                    )
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    logging.info("=== Schritt 4/5: Phase 2 – Themenbewertung ===")
    try:
        topic_result = analyze_topics(
            cluster_result.clusters,
            articles,
            analysis_result.analyses,
            settings,
            limit=args.limit,
        )
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 1

    all_warnings.extend(topic_result.errors)
    cluster_map = {c.id: c for c in topic_result.clusters}
    topics_payload = []
    for topic in topic_result.topics:
        cluster = cluster_map.get(topic.topic_id)
        if cluster:
            topics_payload.append(
                topic_analysis_to_dict(cluster, topic, articles, analysis_result.analyses)
            )
    topics_payload.sort(key=lambda t: t.get("overall_score", 0), reverse=True)

    topics_path = run_dir / "topics.json"
    topics_data = _save_topics_payload(
        topics_payload, all_warnings, settings, topics_path
    )

    logging.info("=== Schritt 5/5: HTML-Bericht ===")
    report = build_daily_report(
        topics_data,
        settings,
        use_llm_summary=not args.no_llm_summary,
    )
    index_path, archive_path = write_report(report, output_dir=OUTPUT_DIR)

    logging.info("Pipeline abgeschlossen.")
    logging.info("  Artikel:   %d", len(articles))
    logging.info("  Themen:    %d", len(topics_payload))
    logging.info("  Bericht:   %s", index_path)
    logging.info("  Archiv:    %s", archive_path)

    has_errors = analysis_result.failed_count or topic_result.failed_count
    return 1 if has_errors and not topics_payload else 0


def cmd_report(args: argparse.Namespace) -> int:
    settings = load_settings()
    topics_path = Path(args.topics) if args.topics else DATA_DIR / "topics.json"

    if not topics_path.exists():
        logging.error("Topics-Datei nicht gefunden: %s", topics_path)
        return 1

    payload = load_topics_payload(topics_path)
    logging.info("Geladen: %d Themen aus %s", len(payload.get("topics", [])), topics_path)

    report = build_daily_report(
        payload,
        settings,
        use_llm_summary=not args.no_llm_summary,
    )

    output_dir = Path(args.output) if args.output else OUTPUT_DIR
    index_path, archive_path = write_report(report, output_dir=output_dir)

    logging.info("Bericht erstellt: %s", index_path)
    logging.info("Archiv: %s", archive_path)
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    settings = load_settings()

    if args.input:
        articles, _ = load_articles_from_run(Path(args.input))
        logging.info("Geladen: %d Artikel aus %s", len(articles), args.input)
    else:
        sources, source_warnings = load_sources_lenient()
        articles, fetch_warnings = fetch_articles(sources, settings)
        for warning in source_warnings + fetch_warnings:
            logging.warning(warning)

    summary = summarize_by_source(articles)

    print("=" * 60)
    print("QUELLENÜBERSICHT")
    print("=" * 60)
    for s in summary:
        focus = ", ".join(s.focus) if s.focus else "–"
        print(
            f"  {s.source_name:35} {s.source_type:8} Prio {s.priority}  "
            f"{s.article_count:3} Artikel  [{focus}]"
        )
    print(f"\nGesamt: {len(articles)} Artikel aus {len(summary)} Quellen")

    if args.demo_cluster:
        cluster = TopicCluster(
            id="demo-all",
            label="Alle Artikel (Demo-Cluster)",
            article_ids=[a.id for a in articles],
        )
        enriched, scores = enrich_cluster(cluster, articles, settings)

        print("\n" + "=" * 60)
        print("DEMO-CLUSTER: Deterministische Metriken")
        print("=" * 60)
        print(f"  Artikel:              {enriched.article_count}")
        print(f"  Quellen:              {enriched.source_count}")
        print(f"  Quellentypen:         {', '.join(enriched.source_types)}")
        print(f"  Fokusbereiche:        {', '.join(enriched.focus_areas)}")
        print(f"  Ø Quellenprioritaet:   {enriched.avg_source_priority:.1f}")
        print(f"  Hochpriorisiert (>=8): {enriched.high_priority_source_count}")
        print(f"  Quellenpriorität:     {scores.source_priority_score}/10")
        print(f"  Quellenvielfalt:      {scores.source_diversity_score}/10")
        print(f"  Medienaufmerksamkeit: {scores.media_attention}/10 (objektiv)")

    if args.output:
        output = {
            "source_summary": [s.to_dict() for s in summary],
            "article_count": len(articles),
        }
        if args.demo_cluster:
            cluster = TopicCluster(
                id="demo-all",
                label="Alle Artikel (Demo-Cluster)",
                article_ids=[a.id for a in articles],
            )
            enriched, scores = enrich_cluster(cluster, articles, settings)
            output["demo_cluster"] = {
                "metrics": {
                    "article_count": enriched.article_count,
                    "source_count": enriched.source_count,
                    "source_types": enriched.source_types,
                    "focus_areas": enriched.focus_areas,
                    "avg_source_priority": enriched.avg_source_priority,
                    "high_priority_source_count": enriched.high_priority_source_count,
                },
                "scores": scores.breakdown,
            }

        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        logging.info("Metriken gespeichert: %s", out_path)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Ausführliche Log-Ausgabe",
    )

    parser = argparse.ArgumentParser(
        description="KI-gestützter Themenradar für Pressearbeit",
        parents=[parent],
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="RSS-Feeds laden (24h-Lookback), ohne KI-Analyse",
    )
    parser.add_argument(
        "-o", "--output",
        help="JSON-Ausgabedatei (optional, nur mit --fetch-only)",
    )

    subparsers = parser.add_subparsers(dest="command")

    fetch_parser = subparsers.add_parser(
        "fetch",
        help="RSS-Feeds laden (24h-Lookback)",
        parents=[parent],
    )
    fetch_parser.add_argument(
        "-o", "--output",
        help="JSON-Ausgabedatei (optional)",
    )
    fetch_parser.set_defaults(func=cmd_fetch_only)

    metrics_parser = subparsers.add_parser(
        "metrics",
        help="Quellenübersicht und deterministische Metriken",
        parents=[parent],
    )
    metrics_parser.add_argument(
        "-i", "--input",
        help="Bestehenden JSON-Lauf laden (statt RSS-Fetch)",
    )
    metrics_parser.add_argument(
        "-o", "--output",
        help="Metriken als JSON speichern",
    )
    metrics_parser.add_argument(
        "--demo-cluster",
        action="store_true",
        help="Demo-Cluster über alle Artikel berechnen",
    )
    metrics_parser.set_defaults(func=cmd_metrics)

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Phase 1: Artikel per LLM analysieren",
        parents=[parent],
    )
    analyze_parser.add_argument(
        "-i", "--input",
        help="Bestehenden Fetch-Lauf laden (statt RSS-Fetch)",
    )
    analyze_parser.add_argument(
        "-o", "--output",
        help="JSON-Ausgabedatei (Standard: data/runs/analyzed.json)",
    )
    analyze_parser.add_argument(
        "--limit",
        type=int,
        help="Maximale Anzahl zu analysierender Artikel",
    )
    analyze_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Cache ignorieren, alle Artikel neu analysieren",
    )
    analyze_parser.add_argument(
        "--print-json",
        action="store_true",
        help="JSON zusaetzlich auf stdout ausgeben",
    )
    analyze_parser.set_defaults(func=cmd_analyze)

    cluster_parser = subparsers.add_parser(
        "cluster",
        help="Artikel zu Themenclustern gruppieren",
        parents=[parent],
    )
    cluster_parser.add_argument(
        "-i", "--input",
        help="analyzed.json oder Fetch-Lauf als Eingabe",
    )
    cluster_parser.add_argument(
        "-o", "--output",
        help="JSON-Ausgabedatei (Standard: data/runs/clustered.json)",
    )
    cluster_parser.add_argument(
        "--limit",
        type=int,
        help="Maximale Anzahl Artikel",
    )
    cluster_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Analyse-Cache ignorieren (wenn Phase 1 noetig)",
    )
    cluster_parser.add_argument(
        "--fallback-only",
        action="store_true",
        help="Regelbasiertes Clustering ohne LLM (Test)",
    )
    cluster_parser.add_argument(
        "--print-json",
        action="store_true",
        help="JSON zusaetzlich auf stdout ausgeben",
    )
    cluster_parser.set_defaults(func=cmd_cluster)

    topics_parser = subparsers.add_parser(
        "topics",
        help="Phase 2: Themen bewerten und Pressechancen",
        parents=[parent],
    )
    topics_parser.add_argument(
        "--analyzed",
        required=True,
        help="Pfad zu analyzed.json (Phase 1)",
    )
    topics_parser.add_argument(
        "--clusters",
        help="Pfad zu clustered.json (Standard: data/runs/clustered.json)",
    )
    topics_parser.add_argument(
        "-o", "--output",
        help="JSON-Ausgabedatei (Standard: data/runs/topics.json)",
    )
    topics_parser.add_argument(
        "--limit",
        type=int,
        help="Maximale Anzahl zu bewertender Themen",
    )
    topics_parser.add_argument(
        "--print-json",
        action="store_true",
        help="JSON zusaetzlich auf stdout ausgeben",
    )
    topics_parser.set_defaults(func=cmd_topics)

    report_parser = subparsers.add_parser(
        "report",
        help="HTML-Tagesbericht generieren",
        parents=[parent],
    )
    report_parser.add_argument(
        "--topics",
        help="Pfad zu topics.json (Standard: data/runs/topics.json)",
    )
    report_parser.add_argument(
        "-o", "--output",
        help="Ausgabeordner (Standard: output/)",
    )
    report_parser.add_argument(
        "--no-llm-summary",
        action="store_true",
        help="Executive Summary ohne LLM (Fallback-Text)",
    )
    report_parser.set_defaults(func=cmd_report)

    run_parser = subparsers.add_parser(
        "run",
        help="Vollstaendige Tages-Pipeline (Fetch bis HTML)",
        parents=[parent],
    )
    run_parser.add_argument(
        "--limit",
        type=int,
        help="Maximale Anzahl Artikel/Themen (Test)",
    )
    run_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Analyse-Cache ignorieren",
    )
    run_parser.add_argument(
        "--fallback-only",
        action="store_true",
        help="Clustering ohne LLM (Fallback)",
    )
    run_parser.add_argument(
        "--no-llm-summary",
        action="store_true",
        help="Executive Summary ohne LLM",
    )
    run_parser.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))

    if args.fetch_only:
        return cmd_fetch_only(args)

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
