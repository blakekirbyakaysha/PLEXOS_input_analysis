# PROGRESS

Read this file at the start of every session. It is the only state carried between sessions. The spec is in [PLAN.md](PLAN.md); workflow and rules are in [../CLAUDE.md](../CLAUDE.md).

## Status

| Phase | Deliverable | Owner | Status | Commit |
|---|---|---|---|---|
| 0 | Repo layout, docs, station mapping | Opus | Reviewed | b09c785 |
| 1 | `01_extract_data.py` | Sonnet → Opus review | Reviewed | |
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
| 2026-09-25 | METAR extracted per calendar month (all mapped stations in one query, each clipped to its range), not per (station, year); every chunk from every source checked for truncation before caching. Year queries stalled ~130 s and returned HTTP 200 with a truncated stream (e.g. 29 rows ending mid-timestamp). `bom.metar` PK is (MET_DATETIME, ID_NUM, ID_NAME), so cost scales with date range, not station count | User approved monthly + guard; all-station grouping by Opus for the same reason |

## Handover notes

### Phase 0: repo setup (Opus)
- Moved PDFs to `docs/reference/` (methodology renamed without " (1)"), the example notebook to `docs/examples/`, and holidays to `inputs/holidays/` (FY 2014-15 to 2017-18 files to `unused/`).
- Wrote `CLAUDE.md`, `docs/PLAN.md`, `docs/PROGRESS.md`, `inputs/station_mapping.csv` and `.gitignore`. Ran `git init` and made a baseline commit.
- `docs/examples/monthly_update.ipynb` will not run from its new location (imports and fonts). It is reference only.
- Planning query facts are recorded in PLAN §2. Useful check value: Bankstown 94765 on 2024-01-03 has max 29.6, min 19.3, and a calendar-day mean of 24.64.

### Phase 1: extract
**Status: Reviewed** (2026-09-25). The Sonnet agent wrote the script; it was interrupted after about 10 min on slow METAR queries. Opus diagnosed the problem, fixed the chunking and guard, ran the extract and reviewed it.

**Files created**
- `01_extract_data.py`
- `data/raw/<source>/<chunk>.parquet` and `data/raw/<source>.parquet` for `demand_oper`, `totaldemand_daily`, `rooftop_pv`, `metar`, `daily_maxmin`
- `data/raw/pv_satellite_annual.parquet`
- `outputs/extract_summary.md`

**Commands**
- `C:/anaconda3/python.exe -W ignore 01_extract_data.py`. It was re-launched from the shell after a transient HTTP 502; a rerun resumes from the cache.
- The second run reports `Queries issued this run: 0`.

**Key numbers** (see `outputs/extract_summary.md`)
- demand_oper: 503,995 rows, 2020-12-01 00:30 → 2026-09-01 00:00; 5 regions; rows per region-day min 47 / median 48 / max 48.
- totaldemand_daily: 30,435 region-days, 2010-01-01 → 2026-08-31; N_INTERVALS == 288 on 99.98% (min 286); N_NULL total 0.
- rooftop_pv: 743,585 rows, MEASUREMENT only, 5 regions; rows per region-day median 48 (min 19 on the partial first day, 2018-03-08).
- metar: 2,142,018 rows, 7 WMO IDs. The median of :00/:30 obs per station-day is 48 for every station within its valid range.
  - Days with obs / days in range: 94765 7121/7133; 94575 7126/7133; 94648 2222/2222; 95936 4256/4256.
  - 94675, 94868 and 94970 are short by about 367 days each. Their valid_from is 2000-01-01, but extraction starts on 2000-12-31, so 2000 is not extracted. That is expected.
- daily_maxmin: 42,364 rows, 7 IDs.
- Reference check: Bankstown 94765 on 2024-01-03 has 48 :00/:30 obs, max 29.6, min 19.3, all-obs mean 24.64. The daily table's avg is 24.64. ✔

**Deviations**
- METAR is queried per **calendar month for all mapped stations at once** (each station clipped to its own range), not per (WMO ID, year). PLAN has been updated; see the Decisions log.
- Every chunk is guarded by a server-side `SELECT count(*) FROM (<same query>)`. A chunk is cached only if the row counts match exactly.
  - Earlier chunks for demand_oper and rooftop_pv were count-verified once by hand; all matched.
  - totaldemand_daily was verified as 5 regions × days in month for all 200 months.

**QueryTool behaviour (important for any later pulls)**
- Responses are streamed CSV behind Cloudflare. A query that runs past the proxy limit (~100 s) can return **HTTP 200 with a truncated body**; the observed case was 29 rows ending mid-timestamp. `qt_post_request` cannot detect this.
- `bom.metar` primary key = (MET_DATETIME, ID_NUM, ID_NAME), with no index leading on ID_NUM. Each query scans every station (~115) for its date range: about 3.3 M rows for a recent month.
  - Timing is about 1–2 s when the pages are warm and about 16 s when cold. A year of cold pages takes about 130–180 s, which causes the truncation.
  - This is not rate limiting: there are no 429s or rate-limit headers, and tiny queries stay at 0.1 s during slow windows.
- An index on (ID_NUM, MET_DATETIME) on the NEOpoint side would make single-station pulls fast.
- A real source gap exists in METAR from 2001-12-29 ~12:30 to 2002-01-01 ~12:00, across **all** stations. Phase 2 will flag those days via the 44-of-48 rule.

**Review notes**
- The code reads cleanly. It does only column selection plus the SQL aggregation the card specifies. It fails loudly, via `NemPointQueryError` or `RuntimeError`, and caches nothing on failure.
- Raw dtypes: ID_NUM and ID_Num are int64. Timestamps are stored as strings, exactly as returned; Phase 2 parses them.
- demand_oper 2026 has 5 fewer rows than a full 5 × 48 grid (58,315 vs 58,320); rooftop_pv 2019, 2023 and 2024 are also a few rows short. These are genuine source gaps and are left for Phase 2's quality flags.

**Open issues**
- None blocking.

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
