"""Konfiguration aus YAML-Dateien laden."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.models.schemas import (
    EvaluationPriorities,
    Organization,
    Settings,
    Source,
)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(config_dir: Path | None = None) -> Settings:
    data = _load_yaml((config_dir or CONFIG_DIR) / "settings.yaml")
    return Settings(
        lookback_hours=data.get("lookback_hours", 24),
        timezone=data.get("timezone", "Europe/Berlin"),
        language=data.get("language", "de"),
        report=data.get("report", {}),
        llm=data.get("llm", {}),
        dedup=data.get("dedup", {}),
        scoring=data.get("scoring", {}),
    )


def parse_source(entry: dict) -> Source:
    return Source(
        name=entry["name"],
        type=entry["type"],
        feed_url=entry["feed_url"],
        priority=entry.get("priority", 5),
        focus=entry.get("focus") or [],
        source_role=entry.get("source_role", "agenda"),
    )


def _parse_source(entry: dict) -> Source:
    """Alias für Abwärtskompatibilität."""
    return parse_source(entry)


def load_sources(config_dir: Path | None = None) -> list[Source]:
    data = _load_yaml((config_dir or CONFIG_DIR) / "sources.yaml")
    sources = [parse_source(entry) for entry in data.get("sources", [])]
    invalid = [s for s in sources if s.feed_url in ("", "RSS_URL_PRUEFEN")]
    if invalid:
        names = ", ".join(s.name for s in invalid)
        raise ValueError(
            f"Ungültige feed_url bei: {names}. "
            "Bitte URL ergänzen oder Quelle auskommentieren."
        )
    return sources


def load_sources_lenient(config_dir: Path | None = None) -> tuple[list[Source], list[str]]:
    """Lädt Quellen und überspringt Einträge mit ungültiger URL."""
    data = _load_yaml((config_dir or CONFIG_DIR) / "sources.yaml")
    sources: list[Source] = []
    warnings: list[str] = []

    for entry in data.get("sources", []):
        feed_url = entry.get("feed_url", "")
        if not feed_url or feed_url == "RSS_URL_PRUEFEN":
            warnings.append(
                f"Quelle '{entry.get('name', '?')}' übersprungen: keine gültige feed_url"
            )
            continue
        try:
            sources.append(parse_source(entry))
        except ValueError as exc:
            warnings.append(str(exc))

    return sources, warnings


def load_organization(config_dir: Path | None = None) -> Organization:
    data = _load_yaml((config_dir or CONFIG_DIR) / "organization.yaml")
    mission = data.get("mission", "")
    if isinstance(mission, str):
        mission = mission.strip()
    return Organization(
        name=data.get("name", ""),
        mission=mission,
        expertise=data.get("expertise", []),
        regions=data.get("regions", []),
        avoid=data.get("avoid", []),
        tone=data.get("tone", "").strip() if isinstance(data.get("tone"), str) else "",
        project_types=data.get("project_types", []),
        media_goals=data.get("media_goals", []),
        high_relevance_signals=data.get("high_relevance_signals", []),
        potential_story_angles=data.get("potential_story_angles", []),
        spokespersons=data.get("spokespersons", []),
    )


def load_evaluation_priorities(config_dir: Path | None = None) -> EvaluationPriorities:
    data = _load_yaml((config_dir or CONFIG_DIR) / "evaluation_priorities.yaml")
    return EvaluationPriorities(questions=data.get("evaluation_priorities", []))


def load_focus_areas(config_dir: Path | None = None) -> dict[str, dict]:
    data = _load_yaml((config_dir or CONFIG_DIR) / "focus_areas.yaml")
    return data.get("focus_areas", {})
