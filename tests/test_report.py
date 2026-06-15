"""Tests für HTML-Bericht."""

from pathlib import Path

from src.models.schemas import Settings
from src.report.builder import build_daily_report, load_topics_payload
from src.report.html import render_report, write_report

FIXTURE = Path(__file__).resolve().parents[0] / "fixtures" / "topics_sample.json"


def _settings() -> Settings:
    return Settings(
        lookback_hours=24,
        timezone="Europe/Berlin",
        language="de",
        report={"top_topics_count": 5},
    )


def test_build_daily_report_fallback_summary():
    payload = load_topics_payload(FIXTURE)
    report = build_daily_report(payload, _settings(), use_llm_summary=False)

    assert report.organization_name == "WWF Deutschland"
    assert len(report.top_topics) == 2
    assert "EU-Klimapolitik" in report.executive_summary


def test_render_report_contains_topics():
    payload = load_topics_payload(FIXTURE)
    report = build_daily_report(payload, _settings(), use_llm_summary=False)
    html = render_report(report)

    assert "EU-Klimapolitik" in html
    assert "Pressechance" in html
    assert "Executive Summary" in html


def test_write_report_creates_files(tmp_path):
    payload = load_topics_payload(FIXTURE)
    report = build_daily_report(payload, _settings(), use_llm_summary=False)

    index_path, archive_path = write_report(report, output_dir=tmp_path)

    assert index_path.exists()
    assert archive_path.exists()
    assert "Artenschutz" in index_path.read_text(encoding="utf-8")
