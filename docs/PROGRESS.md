# PROGRESS

Read this file at the start of every session. It is the only state carried between sessions. The spec is in [PLAN.md](PLAN.md); workflow and rules are in [../CLAUDE.md](../CLAUDE.md).

## Status

| Phase | Deliverable | Owner | Status | Commit |
|---|---|---|---|---|
| 0 | Repo layout, docs, station mapping | Opus | Reviewed | b09c785 |
| 1 | `01_extract_data.py` | Sonnet → Opus review | Reviewed | dd2ba88 |
| 2 | `02_prepare_daily.py` | Sonnet → Opus review | Reviewed | a3f46a4 |
| 3 | `03_regressions.ipynb` | Sonnet → Opus review | Reviewed | 4b16c5e |
| 4 | `04_weather_years.ipynb` | Sonnet → Opus review | Reviewed | 19e6221 |
| 5 | `findings.md` | Opus | Reviewed | 17c2587 |

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
**Status: Reviewed** (2026-09-25). The Sonnet agent built and ran the notebook. Opus reviewed it, made two small edits (see Review notes) and re-executed it from a fresh kernel.

**Files created**
- `03_regressions.ipynb`
- `outputs/regression_results.csv` (190 rows)
- `outputs/coefficient_flags.csv` (10 rows: 5 regions x 2 dep vars)
- `outputs/overlap_check.csv` (5 rows, one per region)
- `outputs/figures/diag_{NSW1,QLD1,SA1,TAS1,VIC1}.png`, `outputs/figures/coef_comparison.png`, `outputs/figures/rolling_betas.png`

**Commands**
- `C:/anaconda3/python.exe -m jupyter nbconvert --to notebook --execute --inplace 03_regressions.ipynb` (run from repo root; ~1-2 min)

**Key numbers**
- Run A, M2, common-sample n by region matches the Phase 2 handover numbers exactly: NSW1 1434/1438 (underlying/oper), QLD1 1428/1432, SA1 1427/1432, TAS1 1428/1431, VIC1 1437/1441.
- Run A, M2, underlying_gwh: beta_HDD / beta_CDD (GWh per degree-day), both p < 0.001 in every region:
  - NSW1: 4.09 / 8.15 (r2 0.899)
  - QLD1: 1.62 / 6.38 (r2 0.922)
  - SA1: 0.65 / 1.79 (r2 0.870)
  - TAS1: 0.32 / 0.20 (r2 0.760, CDD p = 0.0039 -- weakest CDD signal, as expected for a cold climate)
  - VIC1: 2.42 / 5.96 (r2 0.880)
  - All ten (region x dep_var) rows have `hdd_sign_ok`, `cdd_sign_ok`, `hdd_sig`, `cdd_sig` all True in `coefficient_flags.csv`.
- The acceptance cell independently recomputed `n` for all 190 run-matrix rows via a fresh `select_sample()` call and matched the stored `n` exactly; it also confirmed every expected (run_id, region, model, dep_var, window) combination is present.
- `hdd_rolling_range`/`cdd_rolling_range` (max/min - 1 of run D `total_gwh` beta over the 13 calendar-year rolling windows, 2013-2025): all finite (mins were positive in every region), e.g. NSW1 0.41/0.39 (HDD/CDD), QLD1 0.96/0.47, SA1 0.29/0.11, VIC1 0.61/0.48, TAS1 0.20/132.9. TAS1's CDD beta is small and swings from about 0.001 to 0.14 GWh/DD across the rolling windows (min in the 2022-2025 window) -- the guard for min beta <= 0 was not triggered, but the ratio is nonetheless dominated by TAS1's very weak, unstable cooling response and should be read with that caveat rather than as a stability problem comparable to the other regions.
- `cdd_underlying_vs_oper_ratio` (run A M2 underlying/oper) is close to 1 everywhere (0.78-1.18), i.e. rooftop PV growth does not change the CDD response much over the primary window.
- `overlap_check.csv`: corr(total_gwh, oper_gwh) on the common 2021-01-01->2026-08-31 sample: NSW1 0.9985, QLD1 0.9990, SA1 0.9827, TAS1 0.9547, VIC1 0.9907 (consistent with the Phase 2 handover figures computed on a slightly different sample). mean_ratio (total/oper) ranges 0.960 (VIC1) to 0.995 (QLD1).
- All figures were opened and visually checked. `coef_comparison.png` and `rolling_betas.png` use a 5-colour region palette (PINE/AMBER/AZURE/AMARANTH/SPRING) chosen for mutual distinctness rather than the more natural but too-similar MOSS/JADE pairing; the diag-plot "fitted" line uses a neutral grey rather than an Akaysha colour so it never collides with a region's own colour (this mattered for QLD1, which is now amber).

**Deviations from Spec**
- The run-D "12 calendar-year rolling windows" wording in the orchestrator's clarification #3 does not match the run-matrix table, which lists 13 end years (2013...2025 inclusive). Implemented with all 13, matching the explicit table; flagged here rather than guessed silently.
- `total_pv_gwh` rolling windows in run D use only the literal "rolling 4-year windows... starting >= 2019-01-01" (4 windows, end years 2022-2025); the extra one-off 2022-09->2026-08 window was not duplicated for `total_pv_gwh`, since the run-matrix table only lists the extra window on the `total_gwh` row.
- `fit()` and `select_sample()` take an additional optional `extra_ok_cols` keyword beyond the four positional arguments in the task card, to support run E's `ok_temp_mm` requirement and run F's cross-checks against the other dependent variable's quality flag (per the orchestrator's clarifications #2 and #5). The four-argument call signature works unchanged for runs A, B, C and D.
- `rolling_betas.png` plots `total_gwh` as the main line with CI band and overlays `total_pv_gwh` as unshaded "x" markers (only 4 points, 2022-2025); this was a judgement call to keep the figure legible rather than doubling the shaded bands.

**Open issues**
- None blocking. See the TAS1 CDD note above -- worth carrying into Phase 5's discussion of where a weather-year adjustment is and is not material.

**Review notes (Opus)**
- Code reviewed:
  - The common sample is dep-var flag & ok_temp & ok_temp_lag (+ ok_temp_mm for E, and the other series' flag for F).
  - `trend` is measured from each fit's own window start; windows are inclusive.
  - Rolling windows are 4 calendar years (end_year − 3 → end_year).
  - HAC maxlags = 7.
  - The M4 LR terms come from `res.t_test` ✔.
- Independent refit of NSW1 / A / M4 / underlying outside the notebook: n 1434; b_HDD 3.090 + b_HDD_lag1 1.471 = LR 4.561, SE 0.202, CI [4.165, 4.957]. All match the CSV exactly ✔.
- Fresh-kernel `nbconvert --execute`:
  - The first attempt hit a transient `OSError 22` saving `diag_VIC1.png` (file lock, probably the editor preview).
  - The immediate rerun passed, including the acceptance cell (190 rows, all n matched).
- Run matrix: A 40, B 40, C 5, D 70 total + 20 total_pv, E 5, F 10 ✔. My clarification #3 wrongly said "12" rolling windows; the agent correctly used 13.
- Edits made in review:
  - Appended a final **markdown** cell with the flag table (the card asks for markdown; the notebook had ended on a code cell). The values are copied from `coefficient_flags.csv`.
  - Corrected the NSW1 rolling-range numbers above; the handover had quoted the M2/M3/M4-LR spreads.
- Figures are legible. In the diag plots the grey fitted line partly hides the actual line; this is cosmetic and was not changed.
- Magnitudes are plausible. NSW1 β_CDD ≈ 8 GWh/DD is above the card's indicative 1–5 range, but NSW1 underlying demand is ~200 GWh/day and the scatter shows a ~+50 GWh rise from 22 °C to 30 °C, so 8 is consistent (the range was never enforced).
- Observations for Phase 5 (no conclusions drawn here):
  - The HDD spread across M2/M3/M4-LR exceeds 25% for NSW1 (0.36) and SA1 (0.48) underlying, and for QLD1 oper (0.93). M2 (month dummies) gives the lowest HDD; M3 and M4-LR are higher.
  - CDD spreads are ≤ 0.14 on the mainland.
  - M1 → M2 attenuates HDD by 28–39% on the mainland for underlying (QLD1 underlying is the exception, +12%), and by 45–63% for oper.
  - Run D shows βs trending up over time for NSW1/VIC1 HDD and for NSW1/QLD1/VIC1 CDD (e.g. VIC1 β_HDD 1.7 → 2.6), consistent with electrification and growth.
  - TAS1 CDD is weak: B/M2 underlying p = 0.065; F total_gwh p = 0.67.

### Phase 4: weather years
**Status: Reviewed** (2026-09-25). The Sonnet agent built and ran `04_weather_years.ipynb`. Opus reviewed it, fixed two figure issues and corrected the handover (see Review notes).

**Files created**
- `04_weather_years.ipynb`
- `outputs/weather_year_monthly.csv` (5,328 rows: 5 regions x 2 dep_vars x 2 coef_sets x region-year-range x 12 months)
- `outputs/weather_year_annual.csv` (740 rows: CY + FY, valid years only)
- `outputs/materiality_summary.csv` (20 rows: 5 regions x 2 dep_vars x 2 coef_sets)
- `outputs/figures/annual_adjustment.png`, `outputs/figures/monthly_heatmap.png`

**Commands**
- `C:/anaconda3/python.exe -m jupyter nbconvert --to notebook --execute --inplace 04_weather_years.ipynb` (run from repo root; a few seconds). Re-run twice more after cosmetic figure/markdown edits; all three runs passed from a fresh kernel with no errors.

**Key numbers**
- Coefficients (run A, primary window 2022-09-01→2026-08-31): one row per (region, model, dep_var) confirmed unique for M2 and M4.
- Valid CY weather years (of the region's full S7 range) / excluded years (invalid months):
  - NSW1: 13 of 18 (2008–2025). Excluded: 2008 (Sep,Oct), 2010 (Apr,May), 2016 (Feb,Aug), 2017 (Sep), 2024 (Aug).
  - QLD1: 17 of 18. Excluded: 2016 (Aug).
  - SA1: 22 of 25 (2001–2025). Excluded: 2001 (Jul,Oct,Dec), 2002 (Aug), 2003 (Sep).
  - TAS1: 20 of 25. Excluded: 2001 (8 months, Dec2001–Jan2002 METAR outage plus others), 2002 (5 months), 2003 (4 months), 2004 (Jan,Feb), 2014 (Jun).
  - VIC1: 23 of 25. Excluded: 2001 (Jul), 2010 (Mar).
  - These match the Phase 2 temp-exclusion pattern (2001–2004 concentration, Dec2001–Jan2002 outage, scattered later single-region-months).
- Valid FY years (labelled by ending year): NSW1 FY2011–FY2024 minus the 2016/2017 exclusions overlapping FY boundaries → 11 valid FYs; QLD1 16 (FY2009–FY2025 minus FY2017 overlap); SA1 21 (FY2005–FY2025 range, minus early-2000s exclusions); TAS1 20 (FY2005–FY2025 range); VIC1 22 (FY2003–FY2025 range). Exact lists are reproducible from `dd_df`/`valid_fy` in the notebook.
- Denominators (annual, mean daily x 365.25, GWh): underlying / oper: NSW1 75,114 / 66,388; QLD1 62,600 / 54,103; SA1 14,581 / 11,436; TAS1 10,428 / 10,044; VIC1 49,460 / 43,956.
- Annual CY `net_pct` (underlying_gwh, M2) min/max/range: NSW1 −1.01/+0.85/1.85; QLD1 −1.24/+1.27/2.52; SA1 −1.89/+1.84/3.74; TAS1 −0.53/+0.74/1.27; VIC1 −0.99/+0.76/1.75. M4_LR ranges are 3–10% wider than M2 in every region (e.g. SA1 M4_LR range 4.08). FY ranges are similar magnitude to CY (e.g. NSW1 FY range 2.15).
- `oper_gwh` ranges are close to `underlying_gwh` on the mainland but noticeably wider for SA1 (M2 CY range 4.81 vs 3.74 for underlying) . *(Opus correction: the SA1 β are nearly equal for underlying and oper (M2 HDD 0.65 vs 0.64, CDD 1.79 vs 1.81). The wider oper % range comes from the smaller denominator (11,436 vs 14,581 GWh), not from PV damping the weather response.)*
- Monthly exceedance shares (underlying, M2): `>5%` — NSW1 2.9%, QLD1 1.4%, SA1 7.1%, TAS1 0.0%, VIC1 1.7% of valid region-months; all well under the 20% threshold in every region/dep_var/coef_set combination in `materiality_summary.csv`. `>2.5%` shares are higher (10–36%) but that measure has no explicit decision-criteria threshold.
- Mean-vs-median (POE50) offsets (`cy_offset_net_pct`): small in every region, |offset| ≤ 0.21% for CY, ≤ 0.28% for FY across all combos — the mean/median choice barely matters here.
- Acceptance cell: (a) monthly sums equal annual values within 1e-9 for every (region, dep_var, coef_set, CY/FY year) — passed; (b) standards recomputed from valid years only match `std` dict exactly, no invalid year contributes — passed; (c) year/month coverage matches S7 exactly per region (no 2026, no pre-2008 NSW1/QLD1) — passed; (d) CY mean of annual HDD/CDD over valid years equals Σ_m std_m — passed by construction and asserted.
- VIC1 2019 CY hand-check (underlying, M2), recomputed independently from raw parquet rows: HDD 868.98, CDD 163.83, heat_adj/cool_adj/net_adj and net_pct 0.486% all matched the CSV row to 1e-9. Independent standard re-derivation (valid-year list, monthly standards) also matched exactly.

**Deviations from Spec**
- None identified. The orchestrator's clarifications (#1–#10) were followed as written; no ambiguity required an "Open issues" entry.
- Cosmetic-only: `annual_adjustment.png` x-axis uses an integer year locator (`MaxNLocator(integer=True)`) since matplotlib's default produced float-looking tick labels (e.g. "2007.5") on some facets with wide year ranges; this does not change any data or the figure's substance.

**Open issues**
- None blocking. Note for Phase 5: decision-criteria materiality (§8) is mixed across regions on the annual-range test (±1.5%) — SA1, QLD1 and NSW1 CY ranges straddle or approach ±1.5% while TAS1 and VIC1 stay under it — but the monthly ±5%-in-≥20%-of-months test is not met anywhere (max share 7.1%, SA1). This is exactly the kind of split result §8 calls "Refine," but the actual Proceed/Stop/Refine call, and any β sign/significance/spread checks against run A/M2/M3/M4-LR from Phase 3, belong to Phase 5.

**Review notes (Opus)**
- Code reviewed against §7 and clarifications #1–#10:
  - The valid-month rule uses `ok_temp` only, with the day-share scaling.
  - Standards come from valid CY years only and are shared by the CY and FY roll-ups.
  - The monthly denominator uses the days in that weather-year month; the annual denominator is ×365.25.
  - FYs require all 12 months valid and inside the CY range.
  - Invalid years are omitted from the annual CSV. β come from run A M2 and M4 (LR) with a uniqueness assert.
- Independent vectorised recompute (my own code, not the notebook's) of underlying/M2 for all 5 regions reproduced n_CY, CY min/max and the >5% / >2.5% monthly shares exactly ✔.
- The notebook runs from a fresh kernel. Acceptance checks (a)–(d) and the VIC1 2019 hand-check pass ✔.
- **Handover correction on §8:** the annual test (max ≥ +1.5% or min ≤ −1.5%) is met only by **SA1** (underlying M2 −1.89/+1.84). With M4_LR it is SA1 only; with oper it is also SA1 only. QLD1 (−1.24/+1.27), NSW1, VIC1 and TAS1 do not meet it. The Stop half-levels (±0.75%) are exceeded in every region (TAS1 barely: −0.53/+0.74 CY underlying M2). The monthly ≥ 20%-of-months test is met nowhere (max share 17.3%, SA1 oper M4_LR).
- Edits made in review (the notebook was re-executed after them):
  - `annual_adjustment.png`: lines were drawn straight across excluded years (e.g. NSW1 2015→2018). The series is now reindexed to every weather year, so gaps show; the title notes this.
  - `monthly_heatmap.png`: the colour scale was set by one SA1 extreme (13.9%), which left most cells near-white. It is now capped at ±10% with an extended colourbar, and the label is wrapped.
  - The `date` parse now uses an explicit `%Y-%m-%d` format.
- Observations for Phase 5:
  - NSW1 loses 5 of 18 CY years to a single invalid month each, so its annual range rests on 13 years. The 90% rule is strict for that region.
  - The heatmap shows SA1 summer months (Nov–Mar) hitting ±10% in several years. The annual effect is diluted by mild shoulder months.

### Phase 5: findings
**Status: Reviewed** (2026-09-25). Written by Opus (orchestrating session) per the card.

**Files created**
- `findings.md` (repo root)

**Inputs used:** `outputs/regression_results.csv`, `coefficient_flags.csv`, `overlap_check.csv`, `materiality_summary.csv`, `weather_year_annual.csv`, `weather_year_monthly.csv`, the figures, and Methodology §6.1–6.3 (checked with `pdftotext`: traces are scaled to annual energy and max/min targets "such that seasonality ... [is] preserved").

**Verdict: Refine.**
- Mainland β are positive with p < 0.001 everywhere.
- The M2/M3/M4-LR heating spread fails ±25% in NSW1 (36%), QLD1 (25.2%) and SA1 (48%); cooling ≤ 11%.
- The annual ±1.5% test is met only by SA1 (CY −1.89/+1.84%). The monthly 20% test is met nowhere.
- No mainland region is at Stop level. TAS1 is at Stop level on materiality (M2 max +0.74%) and is recommended for dropping.

**Extra calculations made in the write-up** (not new outputs; derived from Phase 4 CSVs):
- Seasonal DJF/JJA net %, for seasons with all 3 months valid. Mainland summer ranges are about ±3–5%.
- Annual range with the heating adjustment rescaled to the M3 β. No new region crosses ±1.5%.

**Interpretation choices**
- §8 materiality was applied per region, on underlying/M2. The overall reading gives the same verdict.
- The QLD1 heating spread of 25.2% is counted as a fail (strict threshold).

**Open issues:** none.

## Open issues
- None.
