# Themenradar

KI-gestützter Themenradar für die Pressearbeit einer Umweltorganisation.

Das System identifiziert täglich relevante Themen aus RSS-Feeds, clustert ähnliche Meldungen und bewertet ihre Anschlussfähigkeit für die eigene Pressearbeit.

## Ziel

> Worüber berichten Medien aktuell – und wo kann unsere Organisation glaubwürdig und kompetent Teil dieser Geschichte werden?

## Status

**HTML-Bericht und GitHub Actions + GitHub Pages eingerichtet**

Der Workflow `.github/workflows/daily-report.yml` führt die komplette Pipeline aus und veröffentlicht den Bericht auf GitHub Pages (aktuell nur manueller Start).

## Voraussetzungen

- Python 3.11+
- Abhängigkeiten: `pip install -r requirements.txt`

## Konfiguration

| Datei | Zweck |
|-------|-------|
| `config/sources.yaml` | RSS-Feeds mit Typ, Priorität, Fokus, Rolle |
| `config/organization.yaml` | WWF-Profil für Pressechancen |
| `config/evaluation_priorities.yaml` | Bewertungsfragen für Phase 2 |
| `config/focus_areas.yaml` | Fokus-Vokabular |
| `config/settings.yaml` | Lookback, Sprache, Scoring-Gewichte |

### Feeds validieren

```bash
python scripts/validate_feeds.py
python scripts/validate_feeds.py -o data/runs/feed-report.json
```

### Phase 1: Artikelanalyse (OpenAI)

```bash
# API-Key setzen (lokal)
set OPENAI_API_KEY=sk-...

# Fetch + Analyse (empfohlen: zuerst mit Limit testen)
python -m src.main analyze --limit 5

# Aus bestehendem Fetch-Lauf
python -m src.main analyze -i data/runs/test.json --limit 10 -o data/runs/analyzed.json
```

Der Cache liegt in `data/cache/articles.json` — bereits analysierte URLs werden übersprungen.

### Clustering

```bash
# Mit LLM (nach analyze)
python -m src.main cluster -i data/runs/analyzed.json

# Fallback ohne API-Key testen
python -m src.main cluster -i tests/fixtures/analyzed_sample.json --fallback-only
```

Ausgabe: `data/runs/clustered.json` mit Themen, Quellenmetriken und Scores.

### Phase 2: Themenbewertung

```bash
python -m src.main topics \
  --analyzed tests/fixtures/analyzed_sample.json \
  --clusters data/runs/clustered.json
```

Ausgabe: `data/runs/topics.json` mit Scores, Narrativen, Pressechancen und Rankings.

### HTML-Bericht

```bash
python -m src.main report --topics tests/fixtures/topics_sample.json --no-llm-summary
```

Öffne `output/index.html` im Browser. Archivkopie unter `output/archive/YYYY-MM-DD.html`.

### Vollständige Pipeline (ein Befehl)

```bash
python -m src.main run
```

Optional für Tests:

```bash
python -m src.main run --limit 5 --no-llm-summary
```

### GitHub Actions + GitHub Pages

1. Repository auf GitHub anlegen und Code pushen
2. Unter **Settings → Secrets and variables → Actions** das Secret `OPENAI_API_KEY` hinterlegen
3. Unter **Settings → Pages** als Quelle **GitHub Actions** wählen
4. Workflow manuell testen: **Actions → Täglicher Themenradar → Run workflow**

Der Workflow wird per **Run workflow** in GitHub Actions gestartet (`workflow_dispatch`). Der tägliche Cron ist deaktiviert (in der YAML auskommentiert). Der Artikel-Cache (`data/cache/`) wird über `actions/cache` zwischen Läufen beibehalten.

Veröffentlichte URL: `https://<benutzer>.github.io/<repository>/`

### Quellenmetriken (Schritt D/E)

```bash
python -m src.main metrics --demo-cluster
python -m src.main metrics -i data/runs/test.json --demo-cluster -o data/runs/metrics.json
```


## Nutzung

### RSS-Feeds laden (ohne API-Key)

```bash
python -m src.main --fetch-only
```

Alternativ:

```bash
python -m src.main fetch
```

Mit JSON-Ausgabe in Datei:

```bash
python -m src.main --fetch-only -o data/runs/test.json
```

Ausführliche Logs:

```bash
python -m src.main fetch -v
```

## Projektstruktur

```
config/          # YAML-Konfiguration
src/
  fetch/         # RSS-Datenbeschaffung
  analyze/       # KI-Analyse und Clustering
  report/        # HTML-Bericht
  scoring/       # Deterministische Quellenmetriken
  models/        # Datenmodelle
  utils/         # Hilfsfunktionen
tests/           # Unit-Tests
data/runs/       # Lauf-Ergebnisse (JSON)
output/          # HTML-Berichte (GitHub Pages)
templates/       # Jinja2-Templates
.github/         # GitHub Actions Workflows
```

## Einrichtung auf GitHub

1. Secret `OPENAI_API_KEY` anlegen
2. GitHub Pages auf **GitHub Actions** stellen
3. Ersten Lauf über **Actions → Täglicher Themenradar → Run workflow** starten
