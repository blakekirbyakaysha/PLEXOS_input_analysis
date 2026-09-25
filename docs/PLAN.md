# PLAN: demand–weather materiality check

Approved design (rev 3). Spec sections (§1–§9) define the analysis. Phase task cards (bottom) define what each implementation session builds. Progress and handover notes live in [PROGRESS.md](PROGRESS.md).

---

## §1 Scope and principles

**Question.** Does daily regional consumption show a strong and stable enough relationship with HDD/CDD to justify a more robust weather-normalisation study? The eventual use is to give AEMO OPSO reference-year traces weather-dependent annual and seasonal energy, for a wider range of revenue and budget outcomes. AEMO currently grows every reference-year trace to the same annual energy target (2026 Demand Forecasting Methodology §6.1 and §6.3).

**Principles**
- Exploratory and correlational. OLS only. Not causal, and not an AEMO forecast.
- Plain scripts and notebooks. Raw extraction (Phase 1), preparation (Phase 2) and analysis (Phases 3–4) are kept separate.
- Fail loudly. Never impute, guess or fall back silently. The single explicit exception is the monthly degree-day scaling rule in §7.
- Out of scope:
  - modifying AEMO traces
  - estimating future coefficients
  - AEMO Pass 1 synthetic traces
  - climate change
  - appliance-stock models
  - multi-station weighting
  - causal claims
  - ML
  - GUIs and packages

---

## §2 Data sources and fixed inputs

All data comes from QueryTool via `helper_functions.qt_post_request(sql, required_columns=...)`. The facts below were verified during planning.

| Table | Fields used | Facts |
|---|---|---|
| `mms.demandoperationalactual` | INTERVAL_DATETIME, REGIONID, OPERATIONAL_DEMAND, OPERATIONAL_DEMAND_ADJUSTMENT, WDR_ESTIMATE, LASTCHANGED | 30-min, **interval-ending**, NEM time (AEST, no DST). Starts 2020-12-01 00:00. Regions NSW1, QLD1, SA1, TAS1, VIC1. |
| `mms.dispatchregionsum` | SETTLEMENTDATE, REGIONID, INTERVENTION, TOTALDEMAND | 5-min, interval-ending. History back to ≤2005. **Filter `INTERVENTION = 0`** (intervention periods have duplicate rows with INTERVENTION = 1). Region SNOWY1 existed until mid-2008, so use from **2010-01-01**. TOTALDEMAND is scheduled demand, which differs from operational demand. |
| `mms.rooftop_pv_actual` | INTERVAL_DATETIME, REGIONID, POWER, TYPE, QI | 30-min, interval-ending. TYPE ∈ {MEASUREMENT, SATELLITE} from 2018-03-08, plus legacy DAILY 2016–2019. **Use TYPE = 'MEASUREMENT'.** The table also contains sub-region IDs (QLDC, QLDN, QLDS, TASN, TASS); **keep only the 5 region IDs.** |
| `bom.metar` | MET_DATETIME, ID_NUM, T_DB | Sub-hourly air temperature (°C). `ID_NUM` is the **WMO ID**. Timestamps are **local standard time** (no DST gaps or duplicates on DST change days). Regular obs fall on :00 and :30, with irregular SPECI obs in between (e.g. 01:36). |
| `bom.daily_max_min_temperature` | Met_Date, ID_Num, Daily_Max_Temperature, Daily_Min_Temperature, Daily_Avg_Temperature | Calendar-day summary of METAR, keyed by WMO ID. Daily_Avg is the unweighted mean of all obs that day. Used only for the max/min sensitivity and cross-checks. |

- Large aggregate queries return **HTTP 524**. Chunk as specified in the Phase 1 card.
- Reference check value: Bankstown (94765) on 2024-01-03 has 48 METAR obs on :00/:30, max 29.6 and min 19.3. The daily table shows max 29.6, min 19.3, avg 24.64.

### Station mapping: `inputs/station_mapping.csv` (fixed; already written)

There is one station per region, from the IASR 2025 Table 13 sub-region containing the capital city. SA1 and VIC1 have station changeovers.

| region | subregion | station_name | bom_site | wmo_id | valid_from | valid_to | hdd | cdd |
|---|---|---|---|---|---|---|---|---|
| NSW1 | SNW | Bankstown Airport AWS | 066137 | 94765 | 2007-02-20 | | 17.0 | 21.5 |
| QLD1 | SQ | Archerfield Airport | 040211 | 94575 | 2007-02-20 | | 17.0 | 22.0 |
| SA1 | CSA | Adelaide (Kent Town) | 023090 | 94675 | 2000-01-01 | 2020-07-31 | 16.5 | 22.0 |
| SA1 | CSA | Adelaide (West Terrace) | 023000 | 94648 | 2020-08-01 | | 16.5 | 22.0 |
| VIC1 | MEL | Melbourne Regional Office | 086071 | 94868 | 2000-01-01 | 2015-01-05 | 16.5 | 21.0 |
| VIC1 | MEL | Melbourne (Olympic Park) | 086338 | 95936 | 2015-01-06 | | 16.5 | 21.0 |
| TAS1 | TAS | Hobart (Ellerslie Road) | 094029 | 94970 | 2000-01-01 | | 16.0 | 20.0 |

- Thresholds are from Methodology Table 6. The VIC HDD value is printed "165.5" in the PDF; the user confirmed it is **16.5**.
- An empty `valid_to` means open-ended.
- Read `bom_site` as a string (leading zeros).
- Regions with no station before `valid_from` (NSW1 and QLD1 before 2007-02-20) have no weather on those days. That is expected: the days are NaN, not an error.

### Public holidays: `inputs/holidays/`

- `Public holidays.xlsx` (sheet `Dates`, 2004–2023). Columns include `Date` and `Public holiday` (name), plus one column per city containing 1.0 or NaN. City → region: Sydney→NSW1, Brisbane→QLD1, Adelaide→SA1, Melbourne→VIC1, Hobart→TAS1. **Use for years ≤ 2018.**
- `australian_public_holidays_2019.csv` … `_2025.csv` and `Aus-Holidays-2026.csv`. Columns: `Date` (int YYYYMMDD), `Holiday Name`, `Jurisdiction` (lowercase: nsw, qld, sa, tas, vic, plus act/nt/wa to ignore). The 2019 file has an extra `Raw Date` column. Read with `encoding='latin1'`. Names may have trailing spaces. **Use for 2019–2026.**
- For 2019–2023 the xlsx and CSVs overlap. Write the date/region mismatches to `outputs/holiday_mismatch.csv`; they are informational, not fatal.
- Every listed holiday counts as `holiday = 1` for its region, including holidays that fall on weekends and part-day holidays (e.g. SA Christmas Eve).
- `inputs/holidays/unused/` is not used.

---

## §3 Day convention and daily energy

- Market day = `(timestamp − 1 minute).date()`, applied to interval-ending AEST timestamps. A day's intervals end 00:30 (or 00:05) … 24:00.
- Daily energy (GWh) = Σ(MW × interval_hours) / 1000 over the intervals **actually present**. interval_hours is 0.5 for 30-min data and 1/12 for 5-min data.
- Expected interval counts are 48 (30-min) and 288 (5-min). A day is quality-OK for a series only if it has exactly the expected count, no NaN values and no conflicting duplicates.
- Exact duplicate rows are dropped and counted. Duplicates on (region, interval) with differing values are a **hard error**.

---

## §4 Temperature and degree days

- `mean_temp(d)` = unweighted mean of METAR `T_DB` obs whose minute ∈ {0, 30} and whose timestamp lies in **(21:00 on d−1, 21:00 on d]** (local standard time). Use the station valid on day d, per the mapping.
  - At least **44 of 48** obs are required. Otherwise `mean_temp` is NaN and `ok_temp = False`.
  - This follows AEMO's convention (Methodology §A2.1): average 30-min temperature from 9 pm the previous day to 9 pm on the day.
- `mean_temp_maxmin(d)` = (Daily_Max + Daily_Min) / 2 from `bom.daily_max_min_temperature` for the valid station. It is used only for sensitivity run E.
- `HDD = max(0, hdd_threshold − mean_temp)`; `CDD = max(0, mean_temp − cdd_threshold)`. Do the same for the maxmin variants (`HDD_mm`, `CDD_mm`).
- `HDD_lag1`, `CDD_lag1` = the previous calendar day's values. `ok_temp_lag` = `ok_temp` of the previous day.

---

## §5 Demand definitions

| Column | Definition | Available | Role |
|---|---|---|---|
| `oper_gwh` | OPERATIONAL_DEMAND daily energy | 2020-12-01 → | Primary definition; used in final adjustments |
| `pv_gwh` | Rooftop PV (MEASUREMENT) daily energy | 2018-03-08 → | Component |
| `underlying_gwh` | `oper_gwh + pv_gwh` | 2020-12-01 → | **Primary dependent variable** for coefficients (rooftop PV growth has a seasonal shape a linear trend can't absorb) |
| `total_gwh` | TOTALDEMAND daily energy (INTERVENTION = 0) | 2010-01-01 → | Long-history and stability analysis only |
| `total_pv_gwh` | `total_gwh + pv_gwh` | 2018-03-08 → | Stability analysis only |

TOTALDEMAND is not used for final adjustments. Reclassification of generators between non-scheduled and semi-scheduled over time creates level shifts in it.

The underlying proxy is **not** complete underlying consumption. It omits batteries, PVNSG, ONSG, VPP operation, exempt generation and industrial load changes.

---

## §6 Regression models

OLS via `statsmodels.formula.api.ols`, with HAC (Newey-West) standard errors: `.fit(cov_type='HAC', cov_kwds={'maxlags': 7})`. Estimate each region independently.

Features:
- `dow` (0–6), `month` (1–12)
- `holiday` (0/1)
- `xmas_period` (1 if the date is 24 Dec – 2 Jan)
- `trend` = (date − window start).days / 365.25
- `sin_doy`, `cos_doy` = sin/cos of 2π·doy/365.25

| Model | Formula |
|---|---|
| M1 | `y ~ HDD + CDD` |
| M2 | `y ~ HDD + CDD + C(dow) + C(month) + holiday + xmas_period + trend` |
| M3 | `y ~ HDD + CDD + C(dow) + holiday + xmas_period + trend + sin_doy + cos_doy` |
| M4 | `y ~ HDD + CDD + HDD_lag1 + CDD_lag1 + C(dow) + C(month) + holiday + xmas_period + trend` |

- **M4 long-run:** β_HDD_LR = β_HDD + β_HDD_lag1, with SE, p and CI from `res.t_test('HDD + HDD_lag1 = 0')`. The same applies to CDD.
- **Common sample:** within each (region, dep var, window), M1–M4 use the same days. Those are days where the dep-var quality flag, `ok_temp` and `ok_temp_lag` are all True. HAC treats rows as consecutive even when excluded days leave gaps; this is accepted and noted.
- **Interpretation note:** month dummies identify β from within-month weather anomalies, which is the variation relevant to weather-year deviations. They may attenuate β relative to M1 and M3.

### Run matrix

| ID | Models | Dep vars | Window(s) |
|---|---|---|---|
| A | M1–M4 | underlying_gwh, oper_gwh | **Primary: 2022-09-01 → 2026-08-31** |
| B | M1–M4 | underlying_gwh, oper_gwh | 2021-01-01 → 2026-08-31 |
| C | M2 | total_gwh | 2010-01-01 → 2026-08-31 |
| D | M2 | total_gwh | Rolling 4-year windows ending 31 Dec 2013, 2014, …, 2025, plus the window 2022-09-01 → 2026-08-31 |
| D | M2 | total_pv_gwh | The same rolling windows, only those starting ≥ 2019-01-01 |
| E | M2 | underlying_gwh | Primary window, using `HDD_mm`/`CDD_mm` (max/min temperature) |
| F | — | total vs oper | 2021-01-01 → 2026-08-31: daily correlation, mean ratio and ratio std of total_gwh/oper_gwh, plus the M2 β for each on that window |

Rolling windows start on 1 Jan, four years before the end year + 1. For example, the window ending 31 Dec 2013 starts 1 Jan 2010.

Not in scope: quadratic terms, splines, humidity, apparent temperature, interactions, population, connections, EVs, industrial controls, structural-break algorithms and model-selection frameworks.

---

## §7 Weather-year adjustments

- **Weather years (complete calendar years):** NSW1 and QLD1 2008–2025; SA1, VIC1 and TAS1 2001–2025.
- **Monthly degree-day sums.** A region-month is *valid* if ≥ 90% of its days have `ok_temp`. For valid months, sum = mean(daily HDD over valid days) × days_in_month; CDD is treated the same way.
  - This scaling is the only permitted imputation-like step. Record `valid_day_share` in the output.
  - Invalid months are NaN. A year with any invalid month is excluded from annual totals and from standards.
- **Standard weather:** `std_HDD_m` = mean of month-m sums over valid weather years; CDD is treated the same way. Annual standard = Σ_m std_m.
  - Also report the median of annual totals over valid years and the offset (mean − median). AEMO's standard is POE50, i.e. the median; the offset shifts every year equally.
- **Adjustment:** `heat_adj_m = β_HDD × (HDD_m − std_HDD_m)`, `cool_adj_m = β_CDD × (CDD_m − std_CDD_m)`, `net_adj_m = heat + cool` (GWh).
- **Coefficient sets** (from `outputs/regression_results.csv`, run A):
  - `M2` β for dep var `underlying_gwh` and for `oper_gwh`
  - `M4_LR` long-run β for the same two dep vars
- **Percentages:**
  - `net_pct_m` = net_adj_m ÷ mean energy of calendar month m over the primary window (same dep var). Use a month's mean daily energy × days in month.
  - Annual `net_pct` = Σ_m net_adj ÷ mean annual energy over the primary window. Use mean daily energy × 365.25.
- **Roll-ups:** calendar year and financial year (FY labelled by ending year, e.g. FY2025 = Jul 2024 – Jun 2025). Only complete years in which all 12 months are valid.
- Coefficients are held at primary-window (2022–2026) levels and applied to historical weather anomalies. No electrification or climate trend.

---

## §8 Decision criteria

- **Proceed:** all of the following hold.
  - In the mainland regions (NSW1, QLD1, SA1, VIC1), β_HDD and β_CDD from run A (underlying, M2) are positive with p < 0.05.
  - M2, M3 and M4-LR estimates are within ±25% of each other.
  - Either the annual net adjustment range across weather years exceeds ±1.5% of annual energy (max ≥ +1.5% or min ≤ −1.5%), or monthly adjustments regularly exceed ±5% (in ≥ 20% of region-months).
- **Stop:** β are weak or wrong-signed, or both materiality measures fall below half those levels (±0.75% annual; monthly ±2.5% in < 20% of months).
- **Refine:** anything in between, or β materially sensitive to demand definition, window or rolling path.
- TAS1 CDD insignificance is expected (AEMO uses no CDD term for TAS) and does not count towards Stop.
- If the result is Refine or Proceed, list next improvements in priority order, drawing on §9 Deferred.

---

## §9 Assumptions, limitations, deferred

**Assumptions**
- One capital sub-region station represents the whole region. This is weakest for QLD1 (much load is in CQ/NQ) and NSW1.
- Current (2022–2026) sensitivity × historical weather anomalies gives weather-year variation. No electrification, appliance or climate trend.
- `demandoperationalactual` is as-generated, whereas OPSO traces are sent-out. The difference (auxiliaries) is immaterial for percentages.
- The underlying proxy excludes batteries, PVNSG, ONSG, VPP and industrial changes.
- The 9 pm cut-off uses each station's local standard time as METAR provides it. For Adelaide, ACST vs AEST is unverified; the 30-minute difference is immaterial.
- The response is linear beyond AEMO thresholds. The thresholds were fitted by AEMO to residential per-connection data, not regional totals.

**Limitations**
- Only about 4 years of operational demand in the primary window.
- Large industrial loads and outages (smelters in TAS, VIC, QLD, NSW, SA) remain in the dependent variable and dilute percentages.
- Station changeovers (Melbourne Jan 2015, Adelaide Jul 2020) introduce inhomogeneity into the weather history.
- NSW/QLD weather history starts in 2008, while AEMO reference years start in 2001.
- TOTALDEMAND has definitional level shifts.
- No PV series before 2018 in the chosen TYPE.
- Results are correlational.

**Deferred to later versions**
- AEMO-style multi-station regional weighting
- residential per-connection vs business (BMM) split
- explicit large-industrial-load controls
- battery, PVNSG and ONSG reconstruction
- nonlinear response (quadratic, splines, HDD² for TAS)
- humidity, apparent temperature and consecutive-hot-day effects
- COVID and structural-break handling
- climate-adjusted historical weather
- applying adjustments to AEMO future reference-year traces, by month or season

---

# Phase task cards

Each card is self-contained with the Spec sections it references.

**Every card ends with this instruction:** update your section of `docs/PROGRESS.md` with files created, commands run, key numbers, deviations and open issues; set the status to `Done – awaiting review`; **do not start the next phase.**

## Phase 1: `01_extract_data.py` (Sonnet)

**References:** §2, §3 (conventions only), §5.

Write a plain script that pulls the raw data from QueryTool into `data/raw/`. It must not transform anything beyond column selection.

- Import `qt_post_request` from `helper_functions` and always pass `required_columns`. Read WMO IDs and date ranges from `inputs/station_mapping.csv`.
- **Truncation guard:** QueryTool can return HTTP 200 with a truncated CSV stream. Before caching, every chunk must have strictly parseable timestamps and a last timestamp that reaches the chunk's end; otherwise raise and do not cache.
- **Caching:** each chunk is written as `data/raw/<source>/<chunk>.parquet`, and the script skips chunks whose file already exists. At the end, concatenate each source into `data/raw/<source>.parquet`. To refresh, delete the files.
- **Queries**
  1. `demand_oper`: `mms.demandoperationalactual`, one query per calendar year covering 2020-12-01 → 2026-09-01 00:00 inclusive (half-open `> start` / `<= end` bounds on interval-ending timestamps are fine if used consistently). Filter `REGIONID in ('NSW1','QLD1','SA1','TAS1','VIC1')`.
  2. `totaldemand_daily`: `mms.dispatchregionsum`, one query per calendar month, 2010-01 → 2026-08, with `INTERVENTION = 0` and the 5 regions. Aggregate in SQL by region and market day, where the day key is the date of `SETTLEMENTDATE − 1 minute`. Use `DATE_SUB(SETTLEMENTDATE, INTERVAL 1 MINUTE)`; the SQL dialect appears to be MySQL, so test on one month first. Return:
     - `REGIONID`, `MARKET_DATE`
     - `sum(TOTALDEMAND) as SUM_MW`
     - `count(*) as N_ROWS`, `count(distinct SETTLEMENTDATE) as N_INTERVALS`
     - `sum(case when TOTALDEMAND is null then 1 else 0 end) as N_NULL`

     Month bounds on SETTLEMENTDATE are `> first-of-month 00:00` and `<= first-of-next-month 00:00`.
  3. `rooftop_pv`: `mms.rooftop_pv_actual`, `TYPE = 'MEASUREMENT'`, the 5 regions, one query per year, 2018-03-08 → 2026-09-01. Also run one small query for **SATELLITE** annual totals per region and year (SQL aggregate per year; `sum(POWER)*0.5/1000` as GWh). Save it as `data/raw/pv_satellite_annual.parquet`.
  4. `metar`: `bom.metar`, columns `MET_DATETIME, ID_NUM, T_DB`. Station range: max(2000-12-31, valid_from − 1 day) to min(valid_to + 1 day, 2026-09-01). One query per **calendar month** covering all mapped stations, each clipped to its own range; chunk file `data/raw/metar/YYYY-MM.parquet`. (Changed from per (WMO ID, year) on 2026-09-25: the table's primary key leads with MET_DATETIME, so every query scans all stations for its date range; year queries stall past the proxy limit and return truncated streams.)
  5. `daily_maxmin`: `bom.daily_max_min_temperature`, for the mapped IDs over the same ranges, one query per ID.
- Print and write `outputs/extract_summary.md`. For each source, give row count, min/max timestamp and distinct IDs/regions. Also give rows per region-day (demand, PV) or obs per station-day (METAR) as min/median/max.
- **Acceptance**
  - `demand_oper`: about 48 rows per region-day from 2020-12-01 to 2026-08-31, with the 5 regions only.
  - `totaldemand_daily`: `N_INTERVALS` is 288 on nearly all days.
  - `metar`: median of 48 or more obs per station-day within each station's valid range.
  - `rooftop_pv`: 5 regions only and MEASUREMENT only.
  - A second run of the script makes no queries (all chunks cached).
- **Reviewer checks:** Bankstown (94765) on 2024-01-03 has 48 :00/:30 obs, max 29.6 and min 19.3. The summary numbers are consistent with §2 coverage.

## Phase 2: `02_prepare_daily.py` (Sonnet)

**References:** §2, §3, §4, §5 (and the holiday rules in §2).

Plain script: read `data/raw/*.parquet` and the inputs, then build the daily modelling dataset. It must make no API calls.

1. **Inspection report** `outputs/input_inspection.md`. For each raw source give:
   - columns and dtypes
   - date coverage
   - regions or stations present
   - interval resolution (mode of timestamp diffs per region or station)
   - missing-value counts
   - the units asserted: MW for demand and PV, °C for temperature
2. **Hard failures** (raise with a clear message):
   - missing required columns
   - unparseable timestamps
   - unexpected REGIONIDs
   - WMO IDs not in the mapping
   - a mapping gap or overlap on any date from 2001-01-01 to 2026-08-31 for SA1, VIC1 or TAS1, or from 2007-02-20 for NSW1 and QLD1
   - conflicting duplicates
   - any `T_DB` outside [−15, 50]
   - operational demand ≤ 0 or > 20,000 MW
   - negative PV
3. **Demand and PV daily energy:** apply §3 to `demand_oper` and `rooftop_pv`. For `totaldemand_daily`, energy = SUM_MW / 12 / 1000; OK iff N_INTERVALS = N_ROWS = 288 and N_NULL = 0.
4. **Temperature:** apply §4. Use the station per the mapping on each day, reading the previous day's evening obs from the same station. At a changeover day, use the new station's obs for the whole window.
5. **Holidays:** apply the §2 rules. Write `outputs/holiday_mismatch.csv`.
6. **Output** `data/processed/daily_model_dataset.parquet`: one row per (region, date) for 2001-01-01 → 2026-08-31, unique on that key. Columns:
   - `region, date, year, fy, month, doy, dow, weekend, holiday, xmas_period`
   - `station_wmo, n_obs_temp, mean_temp, mean_temp_maxmin, HDD, CDD, HDD_lag1, CDD_lag1, HDD_mm, CDD_mm, HDD_mm_lag1, CDD_mm_lag1`
   - `oper_gwh, pv_gwh, underlying_gwh, total_gwh, total_pv_gwh`
   - `n_int_oper, n_int_pv, n_int_total`
   - `ok_oper, ok_pv, ok_underlying (= ok_oper & ok_pv), ok_total, ok_total_pv, ok_temp, ok_temp_lag, ok_temp_mm`

   Energy is NaN outside each series' availability. `trend` is **not** stored; it is window-specific and computed in Phase 3.
7. **`outputs/data_quality.csv`:** one row per (region, date, series, reason) for every day inside a series' availability range that is not OK. Reasons: missing intervals, extra intervals, duplicate, NaN value, insufficient temperature obs. Also print a summary count per region × series × reason.
- **Acceptance**
  - (region, date) is unique.
  - A hand recomputation of one day's `oper_gwh` (NSW1 2024-01-03) from raw matches.
  - Bankstown 2024-01-03 `mean_temp` equals a manual (21:00 on 2 Jan, 21:00 on 3 Jan] mean.
  - Exclusion counts are in the handover.
- **Reviewer checks**
  - Correlation of `mean_temp` vs Daily_Avg per station is high.
  - Station switch dates are respected (SA1 2020-08-01, VIC1 2015-01-06).
  - Daily correlation of `oper_gwh` vs `total_gwh` is > 0.95 per region.

## Phase 3: `03_regressions.ipynb` (Sonnet)

**References:** §5, §6 (and §3 and §4 for column meaning).

The notebook loads `data/processed/daily_model_dataset.parquet` only.

- Put a small `fit(df, formula, window, dep_var)` helper in the notebook. It computes `trend`, applies the common-sample rule and returns a tidy row.
- Run matrix A–F from §6.
- **Outputs**
  - `outputs/regression_results.csv`: one row per (run_id, region, model, dep_var, window_start, window_end). Columns:
    - `n`
    - `b_HDD, se_HDD, p_HDD, ci_lo_HDD, ci_hi_HDD`, and the same for CDD, HDD_lag1, CDD_lag1, HDD_LR and CDD_LR (NaN where not applicable)
    - `r2, adj_r2`
  - `outputs/coefficient_flags.csv`: per region × dep var for run A:
    - `hdd_sign_ok, cdd_sign_ok, hdd_sig, cdd_sig`
    - `hdd_spread_m2_m3_m4lr, cdd_spread_m2_m3_m4lr` (max/min − 1)
    - `hdd_m1_to_m2_pct, cdd_m1_to_m2_pct`
    - `cdd_underlying_vs_oper_ratio`
    - `hdd_rolling_range, cdd_rolling_range` (from run D, total_gwh)
  - `outputs/overlap_check.csv` (run F).
  - **Figures** in `outputs/figures/`:
    - `diag_{region}.png`, 2×2 for M2 / underlying / primary window:
      - daily energy vs mean_temp, with vertical lines at the HDD and CDD thresholds
      - actual vs fitted over time
      - residuals over time
      - residuals vs fitted
    - `coef_comparison.png`: β_HDD and β_CDD ± 95% CI across M1–M4(LR) × dep var × window (A, B, E), faceted by region.
    - `rolling_betas.png`: run D β paths with CIs, by region.
- End the notebook with a short markdown cell listing the flag table. **Do not** write conclusions or recommendations; that is Phase 5.
- **Acceptance**
  - All run-matrix cells are present in the results.
  - n equals the common-sample count per (region, dep var, window).
  - The notebook runs top to bottom from a fresh kernel (`jupyter nbconvert --to notebook --execute --inplace`).
- **Reviewer checks**
  - Signs and magnitudes are plausible. For example, NSW1 β_CDD is of order 1–5 GWh per degree-day; this is a sanity range, not enforced.
  - M4 long-run SE comes from `t_test`.
  - Figures are legible.

## Phase 4: `04_weather_years.ipynb` (Sonnet)

**References:** §5, §7, §8.

The notebook loads the processed parquet and `outputs/regression_results.csv` (run A rows only).

- Implement §7 exactly.
- **Outputs**
  - `outputs/weather_year_monthly.csv`: `region, dep_var, coef_set, weather_year, month, valid_day_share, HDD, CDD, std_HDD, std_CDD, heat_adj_gwh, cool_adj_gwh, net_adj_gwh, net_pct`.
  - `outputs/weather_year_annual.csv`: `region, dep_var, coef_set, year_type (CY/FY), year, HDD, CDD, std_HDD, std_CDD, median_HDD, median_CDD, heat_adj_gwh, cool_adj_gwh, net_adj_gwh, net_pct`.
  - `outputs/materiality_summary.csv`: per region × dep var × coef_set:
    - annual net_pct min, max and range (CY and FY)
    - share of valid region-months with |net_pct| > 5% and > 2.5%
    - mean − median offsets
  - **Figures:**
    - `annual_adjustment.png`: CY net % by weather year, faceted by region, with M2 vs M4_LR for underlying.
    - `monthly_heatmap.png`: month × weather-year net %, faceted by region, using a diverging palette.
- End with a markdown cell showing the materiality summary table. No recommendation; that is Phase 5.
- **Acceptance**
  - Monthly adjustments sum to annual values.
  - Standards use valid years only.
  - Year coverage matches §7.
  - The notebook runs top to bottom from a fresh kernel.
- **Reviewer checks:** hand-check one region-year (e.g. VIC1 2019 CY) end to end.

## Phase 5: `findings.md` (Opus, orchestrating session; not delegated)

Written for the budgeting and revenue-forecasting audience. Contents:
- per-region commentary: signs, significance, stability across M1–M4, windows and rolling paths
- the effect of calendar and trend controls
- underlying vs operational (does adding PV back change the cooling response?)
- the materiality metrics
- an explicit **Stop / Refine / Proceed** against §8
- prioritised next steps
- caveats from §9
