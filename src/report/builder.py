"""Berichtsdaten aus topics.json aufbereiten."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.models.schemas import Settings
from src.utils.config import load_organization
from src.utils.llm import LLMClient

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[2] / "config" / "prompts" / "executive_summary.md"


@dataclass
class DailyReport:
    report_date: str
    generated_at: str
    organization_name: str
    executive_summary: str
    top_topics: list[dict]
    rankings: dict
    topics: list[dict]
    warnings: list[str] = field(default_factory=list)


def load_topics_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fallback_summary(topics: list[dict], rankings: dict) -> str:
    top = rankings.get("top_by_overall", [])[:3]
    if not top:
        return "Keine priorisierten Themen für den heutigen Bericht."

    labels = [t["label"] for t in top]
    if len(labels) == 1:
        lead = f"Das dominierende Thema des Tages ist „{labels[0]}“"
    else:
        joined = ", ".join(f"„{l}“" for l in labels[:-1])
        lead = f"Die Schwerpunkte des Tages sind {joined} und „{labels[-1]}“"

    best = topics[0] if topics else {}
    press = best.get("press_opportunity", {})
    story = press.get("story", "")
    suffix = f" Besonders relevant für die Pressearbeit: {story}" if story else ""
    return f"{lead}.{suffix}"


def _build_summary_prompt(topics: list[dict], rankings: dict) -> str:
    org = load_organization()
    lines = [
        f"Organisation: {org.name}",
        "",
        "Top-Themen nach Gesamtwert:",
    ]
    for item in rankings.get("top_by_overall", [])[:5]:
        lines.append(f"- {item['label']} (Score {item['score']})")

    lines.extend(["", "Themen mit hoher WWF-Anschlussfähigkeit:"])
    for item in rankings.get("top_by_wwf_relevance", [])[:3]:
        lines.append(f"- {item['label']} (WWF-Score {item['score']})")

    lines.extend(["", "Themen mit hoher Medienaufmerksamkeit:"])
    for item in rankings.get("top_by_media_attention", [])[:3]:
        lines.append(f"- {item['label']} (Medien-Score {item['score']})")

    lines.extend(["", "Kurzinfo zu Top-Themen:"])
    for topic in topics[:5]:
        press = topic.get("press_opportunity", {})
        lines.append(
            f"- {topic['label']}: {topic.get('why_relevant', '')} "
            f"Pressechance: {press.get('story', '–')}"
        )

    return "\n".join(lines)


def generate_executive_summary(
    topics: list[dict],
    rankings: dict,
    settings: Settings,
    *,
    llm: LLMClient | None = None,
    use_llm: bool = True,
) -> str:
    if not use_llm:
        return _fallback_summary(topics, rankings)

    try:
        if llm is None:
            llm = LLMClient(settings)
        model = settings.llm.get("models", {}).get("executive_summary", "gpt-4o-mini")
        payload = llm.complete_json(
            model=model,
            system_prompt=PROMPT_PATH.read_text(encoding="utf-8").strip(),
            user_prompt=_build_summary_prompt(topics, rankings),
        )
        summary = str(payload.get("executive_summary", "")).strip()
        if summary:
            return summary
    except Exception as exc:
        logger.warning("Executive Summary per LLM fehlgeschlagen: %s", exc)

    return _fallback_summary(topics, rankings)


def build_daily_report(
    topics_payload: dict,
    settings: Settings,
    *,
    llm: LLMClient | None = None,
    use_llm_summary: bool = True,
) -> DailyReport:
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz=tz)
    topics = topics_payload.get("topics", [])
    rankings = topics_payload.get("rankings", {})
    top_n = int(settings.report.get("top_topics_count", 5))

    org = load_organization()
    summary = generate_executive_summary(
        topics, rankings, settings, llm=llm, use_llm=use_llm_summary
    )

    return DailyReport(
        report_date=now.strftime("%d.%m.%Y"),
        generated_at=now.isoformat(),
        organization_name=org.name,
        executive_summary=summary,
        top_topics=rankings.get("top_by_overall", [])[:top_n],
        rankings=rankings,
        topics=topics,
        warnings=topics_payload.get("warnings", []),
    )
