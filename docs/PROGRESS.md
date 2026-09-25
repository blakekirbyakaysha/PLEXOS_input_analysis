# PROGRESS

Read this file at the start of every session. It is the only state carried between sessions. The spec is in [PLAN.md](PLAN.md); workflow and rules are in [../CLAUDE.md](../CLAUDE.md).

## Status

| Phase | Deliverable | Owner | Status | Commit |
|---|---|---|---|---|
| 0 | Repo layout, docs, station mapping | Opus | Reviewed | (baseline) |
| 1 | `01_extract_data.py` | Sonnet → Opus review | Not started | |
| 2 | `02_prepare_daily.py` | Sonnet → Opus review | Not started | |
| 3 | `03_regressions.ipynb` | Sonnet → Opus review | Not started | |
| 4 | `04_weather_years.ipynb` | Sonnet → Opus review | Not started | |
| 5 | `findings.md` | Opus | Not started | |

Status values: `Not started` / `In progress` / `Done – awaiting review` / `Reviewed` / `Needs fixes`.

## Decisions log

| Date | Decision | Source |
|---|---|---|
| 2026-09-25 | One weather station per region: the IASR 2025 Table 13 station for the sub-region containing the capital (SNW Bankstown, SQ Archerfield, CSA Kent Town→West Terrace, MEL Melbourne RO→Olympic Park, TAS Hobart Ellerslie Rd) | User |
| 2026-09-25 | VIC HDD threshold = 16.5 °C (PDF typo "165.5") | User |
| 2026-09-25 | Temperature = AEMO-style 9 pm–9 pm mean of 30-min METAR obs (`bom.metar`); max/min average only as a sensitivity | Planning (METAR found in QueryTool) |
| 2026-09-25 | Rooftop PV TYPE = MEASUREMENT; SATELLITE annual totals compared once | Planning default, not objected to |
| 2026-09-25 | Primary dependent variable = operational + rooftop PV; operational kept as comparison and used in final adjustments | Planning |
| 2026-09-25 | TOTALDEMAND (DISPATCHREGIONSUM, INTERVENTION = 0) used for the long history 2010→ and rolling stability only | User suggestion; role limited in planning |
| 2026-09-25 | Primary window 2022-09-01 → 2026-08-31; robustness 2021-01-01 → 2026-08-31 | Planning (2026 holidays now supplied) |
| 2026-09-25 | Holidays: xlsx for ≤ 2018, CSVs for 2019–2026 | User supplied files |
| 2026-09-25 | Materiality thresholds per PLAN §8 | User accepted recommendation |
| 2026-09-25 | Added one control: `xmas_period` (24 Dec – 2 Jan) | Planning |

## Handover notes

### Phase 0: repo setup (Opus)
- Moved PDFs to `docs/reference/` (methodology renamed without " (1)"), the example notebook to `docs/examples/`, and holidays to `inputs/holidays/` (FY 2014-15 to 2017-18 files to `unused/`).
- Wrote `CLAUDE.md`, `docs/PLAN.md`, `docs/PROGRESS.md`, `inputs/station_mapping.csv` and `.gitignore`. Ran `git init` and made a baseline commit.
- `docs/examples/monthly_update.ipynb` will not run from its new location (imports and fonts). It is reference only.
- Planning query facts are recorded in PLAN §2. Useful check value: Bankstown 94765 on 2024-01-03 has max 29.6, min 19.3, and a calendar-day mean of 24.64.

### Phase 1: extract
_Not started._

### Phase 2: prepare
_Not started._

### Phase 3: regressions
_Not started._

### Phase 4: weather years
_Not started._

### Phase 5: findings
_Not started._

## Open issues
- None.
