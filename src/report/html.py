"""HTML-Bericht generieren."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.report.builder import DailyReport

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "output"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
ASSETS_DIR = OUTPUT_DIR / "assets"


def _score_width(score: float) -> int:
    return max(0, min(100, int(score * 10)))


def _format_time(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%H:%M Uhr")
    except ValueError:
        return ""


def render_report(report: DailyReport) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["score_width"] = _score_width

    template = env.get_template("report.html.j2")
    return template.render(
        report=report,
        generated_time=_format_time(report.generated_at),
    )


def write_report(
    report: DailyReport,
    *,
    output_dir: Path = OUTPUT_DIR,
) -> tuple[Path, Path]:
    """Schreibt index.html und Archivkopie."""
    html = render_report(report)

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = output_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    index_path = output_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    date_slug = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d")
    archive_path = archive_dir / f"{date_slug}.html"
    archive_path.write_text(html, encoding="utf-8")

    # GitHub Pages: Jekyll deaktivieren
    (output_dir / ".nojekyll").touch(exist_ok=True)

    return index_path, archive_path
