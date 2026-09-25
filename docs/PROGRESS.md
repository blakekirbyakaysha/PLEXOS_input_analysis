# PROGRESS

Read this file at the start of every session. It is the only state carried between sessions. The spec is in [PLAN.md](PLAN.md); workflow and rules are in [../CLAUDE.md](../CLAUDE.md).

## Status

| Phase | Deliverable | Owner | Status | Commit |
|---|---|---|---|---|
| 0 | Repo layout, docs, station mapping | Opus | Reviewed | b09c785 |
| 1 | `01_extract_data.py` | Sonnet → Opus review | Reviewed | dd2ba88 |
| 2 | `02_prepare_daily.py` | Sonnet → Opus review | Reviewed | a3f46a4 |
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
| 2026-09-25 | SA1 operational demand ≤ 0 is real (PV export) and kept; the ≤ 0 hard failure applies to other regions only. METAR `T_DB = -9999` is treated as a missing obs | Opus Phase 2 review |
| 2026-09-25 | Holiday inputs edited: VIC AFL GF Friday added for 2022-09-23 (row missing) and 2025-09-26 (row had no date); 2022-09-22 National Day of Mourning added for all 5 regions | User |

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
**Status: Reviewed** (2026-09-25). The Sonnet agent wrote and ran the script. In review, Opus changed how SA1 negative operational demand is handled (see Deviations) and re-ran the script.

**Files created**
- `02_prepare_daily.py`
- `data/processed/daily_model_dataset.parquet`: 46,870 rows (5 regions × 9,374 days), 2001-01-01 → 2026-08-31, unique on (region, date)
- `outputs/input_inspection.md`
- `outputs/data_quality.csv`: 635 rows, one per (region, date, series, reason)
- `outputs/holiday_mismatch.csv`: 59 rows, xlsx vs CSV for 2019–2023 (informational)

**Commands**
- `C:/anaconda3/python.exe -W ignore 02_prepare_daily.py` (takes a few minutes; prints the acceptance and reviewer checks at the end)

**Key numbers**
- Acceptance: (region, date) is unique ✔.
  - NSW1 2024-01-03 `oper_gwh`: hand 178.950 = script 178.950 (48 intervals) ✔.
  - Bankstown 2024-01-03 `mean_temp`: hand (21:00 2 Jan, 21:00 3 Jan] mean 24.66875 (n = 48) = script ✔. (The 24.64 in §2 is the calendar-day mean, so the two are expected to differ.)
- Reviewer checks:
  - corr(mean_temp, Daily_Avg) per station is 0.994–0.997 ✔.
  - Station switches: SA1 94675 → 94648 on 2020-08-01; VIC1 94868 → 95936 on 2015-01-06 ✔.
  - corr(oper_gwh, total_gwh), n = 2,100 per region: NSW1 0.9985, QLD1 0.9990, SA1 0.9818, TAS1 0.9551, VIC1 0.9907 ✔.
- Drops before aggregation:
  - METAR: 17 exact duplicate rows; 479 rows at `T_DB = -9999`; 117,772 SPECI (non-:00/:30) obs.
  - Demand, PV, total and maxmin: 0 exact duplicates. PV has 209 native null `POWER` values.
- SA1: 147 intervals with `OPERATIONAL_DEMAND` ≤ 0 (min −263 MW, 2023-12 → 2026-03). They are **kept** as real values.
- Exclusions in `data_quality.csv`. The counts are identical for every region, except temp:
  - oper, missing intervals: 1
  - pv, missing intervals: 5
  - pv, NaN value: 10 (SA1: 11)
  - total, missing intervals: 1
  - temp, insufficient obs: NSW1 101, QLD1 61, SA1 91, TAS1 233, VIC1 63. These counts cover only days on or after each region's first `valid_from`. They are concentrated in 2001–2004 (216 of 549) and in the Dec 2001–Jan 2002 outage. Several recent dates fail across all stations at once (e.g. 2024-06-07, 2025-01-17/18, 2026-02-15/16), which points to source gaps.
- Common-sample sizes (ok_underlying & ok_temp & ok_temp_lag):
  - Primary window (1,461 days): NSW1 1434, QLD1 1428, SA1 1427*, TAS1 1428, VIC1 1437.
  - 2021 → window (2,069 days): 2,031–2,042.
  - \*SA1 was 1,395 before the review fix.

**Deviations from Spec**
- **SA1 negative operational demand is kept, not treated as a hard failure.** §2 / the card list "operational demand ≤ 0" as a hard failure. That rule is wrong for SA1, where rooftop-PV export exceeds load at midday on mild sunny days.
  - The agent originally set these intervals to NaN and flagged 32 SA1 days as not OK. That would have selectively removed mild spring days, i.e. exactly the low-HDD/CDD days.
  - Opus changed this: SA1 values ≤ 0 are kept and counted. Any other region ≤ 0, or any value > 20,000 MW, still fails hard. This is recorded in the Decisions log.
- METAR `T_DB = -9999` is BoM's missing-value code, so those rows are dropped as missing obs, not treated as a hard failure. Any other value outside [−15, 50] still fails (none occurred). This only reduces `n_obs_temp`, and the 44-of-48 rule handles the rest.
- `station_wmo` is float64 because it is NaN before a region's first `valid_from`.

**Review notes**
- Code reviewed:
  - Timestamps are parsed strictly with an explicit format.
  - The 21:00 bucketing puts 21:00 in day d and 21:30 in day d+1 ✔.
  - Lags are shifted on a gap-free daily station table per region, so at a changeover the lag comes from the old station, which §4 allows.
  - Conflicting duplicates raise. Energy is computed over the intervals present, and the ok flag carries the quality.
- The agent's handover claimed that the temp exclusions include NSW1/QLD1 days before 2007-02-20. That was wrong: they start at 2007-02-20 (corrected above).
- `holiday` = 0 for 2001–2003 because no source covers those years. Phase 3 windows start in 2010 and Phase 4 does not use `holiday`, so this has no effect.
- Holiday mismatches are Easter Saturday/Sunday, SA Christmas Eve and NYE part-days, regional show days (xlsx) and bank holidays (CSV). All are expected and informational.

**Open issues**
- ~~VIC1 AFL Grand Final Friday missing on 2022-09-23 and 2025-09-26.~~ **Resolved (user-approved).** Added the 2022-09-23 row to `australian_public_holidays_2022.csv` and filled `20250926` into the undated 2025 row. The script was re-run: both days now have `holiday = 1`, `holiday_mismatch.csv` had 54 rows at that point, and all checks are unchanged.
- ~~2022-09-22 National Day of Mourning missing from both holiday sources.~~ **Resolved (user-approved).** Added rows for nsw, qld, sa, tas and vic to `australian_public_holidays_2022.csv`. After the re-run, all 5 regions have `holiday = 1` that day. `holiday_mismatch.csv` now has 59 rows: the extra 5 are CSV-only because the xlsx lacks this date too. All checks are unchanged.

### Phase 3: regressions
_Not started._

### Phase 4: weather years
_Not started._

### Phase 5: findings
_Not started._

## Open issues
- None.
