# ESOO gas analysis: summary of work and findings

Status as of 2026-10-01. Final outputs are in `rry_gas_adjusted_traces/`. Final script: `apply_rry_gas_levels (2).py`.

## At a glance (for team discussion)

- **What we did:** re-based AEMO's 2025 single-reference-year (RY) gas limit traces onto the ISP 2026 representative reference year (RRY) supply level, keeping each RY's weather variability. POE10 only.
- **Result:** 143 daily traces (11 zones × RY2011–2023) running to 2050-12-31, with no negative values and no gaps.
- **How each zone was treated:**
  - Use the RRY directly: Colongra, Gippsland, Kurri Kurri, Newcastle, Port Campbell.
  - Single-RY plus a hand-set level and seasonal shape: Moomba, Northern, NQGP.
  - Single-RY plus a smoothed offset to the RRY: Gladstone, Melbourne, Southern.
- **Fit:** Moomba and NQGP track the RRY closely (mean absolute error 5.9 and 2.5 TJ/d). Northern is looser (16.3 TJ/d).
- **To decide or resolve:** see sections 7 and 8. The main items are a Moomba level-date error in `levels.csv`, whether to adjust POE50, and median-offset accuracy for Melbourne and Southern.

---

## 1. Purpose

AEMO's 2025 gas fuel limitation traces are daily RHS limits (TJ/d) for each gas zone's "Gas Zone Daily Offtake Limit" constraint. There is one trace per zone and per **single reference year (single-RY)** from 2011 to 2023, at POE10 and POE50. They come from the 2025 ESOO and run to about 2045.

The ISP 2026 provides a **representative reference year (RRY)** trace per zone. It is a single 25-year trace (FY2027 to FY2051) that already reflects updated gas supply and infrastructure.

The work builds **adjusted single-RY traces**. These keep the weather and demand variability of each single reference year, but sit on the supply/infrastructure level of the ISP 2026 RRY. They are continuous daily series to 2050-12-31.

### Why it was needed

- The PLEXOS runs use single-reference-year weather. The AEMO GPG limit traces in that format do not reflect the ISP 2026 gas supply outlook. They include only existing, committed and anticipated supply, so later in the horizon they understate the gas available for generation. Gippsland, for example, falls to zero after about 2033.
- The RRY traces include future supply, but each financial year uses a different weather year. Used directly, the gas limits would follow different weather from the electricity demand, wind and solar in the run. That understates the cold, still winter conditions when gas constraints bind.
- So the need was single-RY traces that carry the RRY's supply position and keep each reference year's own weather.

### Why it was hard

- The difference between the RRY and a single-RY trace mixes supply changes with differences in demand assumptions and in how strongly each responds to weather.
- There are data gaps. There are no single-RY traces for RY2024 and RY2025 (the RRY uses these in FY2040 and FY2041, so the matched comparison has no data for those years). Port Campbell has no RY2012 file. The single-RY traces stop in 2045.
- Several zones have zero baselines (flat at zero for long periods), which gives the single-RY traces no weather signal to build on.
- Automatic fits overfit to weather. The final approach therefore uses manually set supply levels, which you review against plots.

### Accuracy expectation

The result is meant to be good enough to show where gas constraints could bind, not an exact reproduction of the RRY. Where the RRY responds to weather more strongly than the single-RY traces do, the cold-day lows are likely to be conservative (the limit is higher than the RRY would give).

## 2. Data and scripts

### Inputs
| Item | Contents |
|---|---|
| `2025 gas fuel limitations data/` | Original single-RY traces (11 zones × RY2011–2023 × POE10/POE50) |
| `ISP 2026 RRY gas fuel limitations/` | RRY traces (file code `5000`, POE10), 1 Jul 2026 to 30 Jun 2051 |
| `rry_gas_manual_inputs/zone_settings.csv`, `levels.csv`, `seasonal.csv` | Hand-set treatment per zone, held levels, and seasonal shapes |
| `PLEXOS_gas_constraints.csv`, `Offtake.csv`, `Generation.csv`, `Fuel_memberships.csv`, `Objects_list.csv`, `load.csv`, `RE_gen.csv`, `Available Capacity.csv` | PLEXOS model data for the earlier gas-consumption and residual-demand work |

### Scripts (in the order the work went)
| Script | What it does |
|---|---|
| `build_constraint_membership_audit.py` | Lists the generators on the left-hand side of each gas-zone constraint and checks they appear in `Offtake.csv`. Output: `analysis_outputs/constraint_lhs_audit.csv` |
| `gas_consumption_analysis_daily_cf_with_profiles.py` | Compares daily zone offtake and capacity factors with the constraint ceiling (RY2011, POE50). Writes `analysis_outputs/` |
| `esoo_residual_demand_*.py` (3 scripts) | Residual demand (load minus renewables) by region, 4-hour extremes, and P10/P90 by FY. Writes `residual_demand_outputs/` |
| `analyse_gas_rhs_reference_years (1).py` | Compares RHS traces across reference years (POE50, FY2028–31). Writes `rhs_reference_year_analysis/` |
| `plot_rry_gas_daily_by_fy.py` | One chart per zone and FY, with every RY plus the RRY overlay. Writes `rry_gas_daily_by_fy_plots/` |
| **`apply_rry_gas_levels.py`** | **Builds the adjusted traces. Two versions exist, and the `(2)` version is the later one.** |

The scripts `check.py` and `check.ipynb` only check datetime parsing in `load.csv`.

## 3. Method (apply_rry_gas_levels)

**Reference-year mapping.** The 25-year RRY is treated as a sequence of financial years, each of which uses one reference year's weather. FY2026 maps to RY2015. FY2027 onward cycles through 2011–2025 and then 2015, repeating every 16 years (`REFERENCE_SEQUENCE`). Each single-RY trace is compared with the RRY on the days the RRY uses that reference year.

**Treatment per zone** (set in `zone_settings.csv`). Every zone has a treatment, and the chosen mode applies per zone and per FY:

| Treatment | Zones | What happens |
|---|---|---|
| `adopt_rry` | Colongra, Gippsland, Kurri Kurri, Newcastle, Port Campbell | Every single-RY trace is replaced with the RRY daily values. |
| `adjust` | Moomba, Northern, NQGP | Output is the single-RY value plus a manual adjustment: a held level (`levels.csv`, step-hold) plus a monthly seasonal shape (`seasonal.csv`). |
| `median_offset` | Gladstone, Melbourne, Southern | Adjustment = a 31-day centred rolling mean of [RRY minus the median of all single-RY traces on that day]. The same adjustment is added to every RY. It needs no manual inputs, and it can cover gaps in the single-RY data. |

For `adjust` and `median_offset`, the derived value is `max(single + adjustment, min(0, single))`. This stops an adjustment from pushing a value below zero when the original was not negative.

**Transplant (NQGP only in practice).** The `adjust` zones use a "censored" test. In a month where most single-RY days are about zero (≤1 TJ), the single-RY trace carries no weather signal. In those months the script copies the RRY's daily weather shape instead (`rry_transplant`). It rebuilds the value as `max(level_target + RRY(source day) − level_source, 0)`, using a smoothed RRY level. In the current run only NQGP triggers this: 108 months, 2042-01 to 2050-12, about 42,700 days per RY file.

**Continuity.**
- Dates before the RRY starts (before 2026-07-01) are left unchanged (`pre_rry_unchanged`).
- Single-RY traces end around 2045. They are extended to 2050-12-31 by repeating the same month and day from the last available year (2045). Feb 29 uses Feb 28. This affects 143 files, 1,826 days each (2046-01-01 to 2050-12-31).
- Internal gaps up to 3 days are forward-filled. Longer gaps raise an error.

## 4. Settings applied

**Constant-limit detection.** An FY is "constant limit" if 3 values cover at least 90% of its days. This applies to Colongra, Kurri Kurri and Newcastle, which are flat in every FY. Their `adopt_rry` result is the same as `auto` would give.

**Held levels (`levels.csv`).** These were hand-picked to track the RRY as it changes over time:
- Gippsland: 23.7 → 274.6 TJ/d (13 steps)
- Gladstone: 15 → 70 (0 to −3 in the mid-2030s)
- Melbourne: 91.5 → about 1,240 (2035) → 1,065.7
- Moomba: 157.8 → about 400 (2033–36) → 325.3
- Northern: −50 → 1,000 (2033–34) → 710
- NQGP: 6.5 → 295.8 → 280
- Port Campbell: −20.6 → 556 (2044) → about 484
- Southern: −34.6 → 1,646 (2035) → 1,511.5

**Seasonal shapes (`seasonal.csv`).** One shape per zone from 2026-07-01. Southern has three further shapes, from 2031-07, 2034-07 and 2043-07.

The `levels.csv` and `seasonal.csv` rows for Gippsland, Gladstone, Melbourne, Port Campbell and Southern are not used in the final run. Those zones are set to `adopt_rry` or `median_offset`, so their rows are ignored.

## 5. Final outputs (`rry_gas_adjusted_traces/`)

| File | Contents |
|---|---|
| `adjusted_single_ry_traces/` | **The deliverable.** 143 CSVs (`Year, Month, Day, Value`) in the original naming (`GPG_Limit_STEP_CHANGE_<Zone>_GPG_Limit_TJ_<RY>_POE10.csv`). Each file is daily from 2025-01-01 to 2050-12-31 (9,496 days). |
| `zone_fy_modes.csv` | Mode applied per zone and FY, with the constant-limit flag |
| `days_by_mode.csv` | Days per file in each mode: `adopt_rry`, `adjust`, `median_offset`, `rry_transplant`, `pre_rry_unchanged` |
| `level_schedule.csv` | Held-level schedule for the `adjust` zones (with the row numbers in `levels.csv`) |
| `median_offset_daily.csv` | Daily RRY, single-RY median, raw difference and applied smoothed adjustment (Gladstone, Melbourne, Southern) |
| `monthly_review.csv` | Monthly diagnostics per zone: observed difference, applied adjustment, leftover, transplant and gap flags |
| `fill_and_extension_report.csv` | Every filled or extended series |
| `review_plots/` | 20 PNGs: level and seasonal review for `adjust` zones, median-offset review, and all-trace charts for every zone |
| `daily_fy_plots/<zone>/` | 275 PNGs, one per zone and financial year (FY2027–FY2051). Top panel: adjusted daily traces, one line per reference year, with the RRY in black. Bottom panel: the original single-RY traces on the same axis. Controlled by `MAKE_DAILY_PLOTS`, `DAILY_ZONES` and `DAILY_FY_START/END` in the script |

`rry_gas_daily_by_fy_plots/` holds the per-FY daily charts, with all RYs overlaid on the RRY.

## 6. Findings and observations

Figures below were re-checked against the rerun outputs on 2026-10-01. The treatment and level choices come from your input files. Whether the levels are right is yours to judge.

1. **Adjusted traces are complete.** There are 143 files (11 zones × 13 reference years) with 9,496 consecutive days each, no negative values, and no unfilled gaps. The only RRY fills are 29 Feb 2048 (1 day each).
2. **Port Campbell RY2012 is now filled.** The source folder has no RY2012 file for Port Campbell. The script now builds it as the daily median of the other 12 reference years and records it as `filled_median_of_other_RYs` in `fill_and_extension_report.csv`. Port Campbell uses `adopt_rry`, so the fill only affects the 546 days before 2026-07-01. The other 142 traces are identical to the previous run.
3. **Mode coverage.** Per file, 7,098 days (2025-01-01 to 2026-06-30) are `pre_rry_unchanged`. The other 116,350 days use the zone's treatment.
4. **Fit quality for `adjust` zones.** The leftover is the monthly RRY-minus-single-RY difference minus the applied adjustment. It should hover around 0 if the level is right. These figures exclude the extended months (2046–2050).

   | Zone | Mean leftover (TJ/d) | Mean absolute leftover (TJ/d) |
   |---|---|---|
   | Moomba | −0.3 | 5.9 |
   | Northern | 0.9 | 16.3 |
   | NQGP | 1.4 | 2.5 |

   Moomba and NQGP fit tightly. Northern is looser, which is consistent with it having many level steps and a larger scale. The gap-proxy residual (months with no matched single-RY data) is −6.2 for Moomba, 17.0 for Northern and −0.2 for NQGP.
5. **Median-offset zones (31-day smoothing).** The smoothed adjustment averages about 33 TJ/d for Gladstone, 804 for Melbourne and 1,119 for Southern. The ranges are −11 to 79 (Gladstone), −174 to 1,388 (Melbourne) and −275 to 1,848 (Southern). The monthly median of the derived traces is within 1.4 TJ/d (Gladstone), 14.9 (Melbourne) and 17.9 (Southern) of the RRY on average (mean absolute), with mean errors of −0.2, 2.4 and 2.2. The window was shortened from 91 to 31 days on 2026-10-01. At 91 days the errors were 2.7, 44.5 and 55.3. The adjustment changes by about 4 TJ/d from day to day at 31 days. The traces for these three zones were regenerated; the other eight zones are unchanged. One day was floored at zero by the new adjustment.
6. **2046–2050: no change needed.** I compared the RRY with itself and with the adjusted traces:
   - The RRY's daily values for 2046–2050 are an exact repeat of its 2045 values in all 11 zones (zero difference). By contrast, 2045 differs from 2044 by up to about 300 TJ/d in some zones.
   - The gap between the RRY and the adjusted traces in 2046–2050 is no worse than in 2036–2045 for any zone (for example, mean absolute gap for Southern is 53.6 vs 53.7, Northern 7.5 vs 13.9, Moomba 3.9 vs 6.0).
   - So repeating 2045 for the single-RY traces matches how the RRY itself behaves. The "use RRY weather where the pattern changes" switch would never trigger, and I did not add it. Note that the RRY after 2045 carries no independent information, because it only repeats 2045.
7. **Data issues in the inputs:**
   - **`levels.csv` Moomba row error (this does change values).** Row 75 has the date `15//08/2034` (double slash). It parses as 15 Aug 2034, the same date as row 74. The script keeps the last row for a duplicate date, so row 74 (390 TJ/d) is dropped and 400 TJ/d applies from 2034-08-15 to 2036-10-14. If row 75 was meant to be a later date, Moomba is 10 TJ/d too high for that period. My earlier note that this had no effect was wrong.
   - **Redundant levels:** Moomba 357 (2030-01 and 2030-03), Melbourne 1,239.8 (2034-12 and 2035-02), Gladstone 15 (2035-09 and 2035-12) and 40 (2043-09 to 2044-12). These are harmless.
   - **The RRY runs to 2051-06-30**, but outputs stop at 2050-12-31. This is accepted.
   - **The `adjust` zones use `Transplant_Censored = TRUE`.** Only NQGP triggers it.
8. **Script versions.** `apply_rry_gas_levels (2).py` is final. The older `apply_rry_gas_levels.py` has no `median_offset` treatment and can be dropped. An earlier Copilot summary mentioned a `quantile_map` treatment for the weather-sensitive zones. Neither script in this folder contains it, so it was not used.
9. **Gaps from the missing RY2024 and RY2025.** The RRY uses RY2024 in FY2040 and RY2025 in FY2041. There are no single-RY files for those years, so no matched comparison exists for them. The `adjust` zones rely on the level and seasonal inputs there, and the `median_offset` zones rely on the median of the other reference years.

### Differences from the earlier Copilot summary

An earlier Copilot summary of this work has been folded into sections 1 and 6. Some of its statements do not match the work in this folder:

- **Gippsland.** Copilot says zero-baseline zones such as Gippsland get the RRY's shape with each reference year's own weather. In the final run Gippsland uses `adopt_rry`, so every reference year gets identical RRY values. If Gippsland should carry each reference year's weather, it needs a different treatment, such as `median_offset`. The team should decide this.
- **Pipeline-limit zones.** Copilot says Newcastle, Colongra and Kurri Kurri use the RRY directly. This matches (they are flat limits, in `adopt_rry`). Port Campbell also uses `adopt_rry`, which Copilot did not mention.
- **`plot_rry_vs_single_scatter.py`.** Copilot mentions this script. It is not in the folder.
- **"Tested on stand-in data only."** The outputs here come from runs on the real single-RY and RRY files.
- **Plots.** Copilot lists review plots, a QA summary and a fill/extension report. All three exist (`review_plots/`, the console summary and `monthly_review.csv`, and `fill_and_extension_report.csv`). The daily charts per zone and financial year are in `daily_fy_plots/`.

## 7. Decisions made

| # | Topic | Decision | Status |
|---|---|---|---|
| 1 | Port Campbell RY2012 | Fill from the median of the other reference years, and flag it | Done |
| 2 | Final script | `apply_rry_gas_levels (2).py` | Done |
| 3 | POE | POE10 only, because the RRY exists only at POE10 | Whether to adjust POE50 is open (section 8) |
| 4 | End date | 2050-12-31 is fine | Done |
| 5 | 2046–2050 extension | Keep repeating 2045. The RRY itself repeats 2045 in those years, so no RRY-weather switch is needed | Done, subject to your agreement |
| 6 | `adopt_rry` for Gippsland and Port Campbell | Deliberate. Their unused level and seasonal rows can be deleted | Done |
| 7 | Audience | You, for a team discussion | Done |
| 8 | Pre-RRY period (before 2026-07-01) | Left unchanged, since it is in the past and won't be modelled | Done |

## 8. Open items for the team discussion

1. **Moomba level row 75.** Should the `15//08/2034` row (400 TJ/d) be a different date, or should the 390 TJ/d row stay? At the moment 400 applies from 2034-08-15.
2. **POE50 traces.** Proposed position: use the POE10 gas traces for POE50 runs. The RRY exists only at POE10, and the POE10 and POE50 single-RY levels match on average (section 9). The winter check in section 9 shows POE10 limits are slightly lower on the tightest winter days in Southern and Melbourne, so this is a small conservative choice there. The team should confirm.
3. **Northern fit.** The mean absolute leftover is 16.3 TJ/d, and the gap check shows the RRY about 17 TJ/d above the proxy in months with no matched single-RY data. The team may want to review its level steps.
4. **Median-offset window.** The 31-day window leaves Melbourne and Southern about 15–18 TJ/d off the RRY month by month. Shorter windows fit more closely but pass more of the RRY's own daily weather onto every reference year. The team may want to confirm 31 days is the right balance (see the comparison in the table below). The daily charts show a side effect: where the RRY makes a sudden step (for example Melbourne on 1 Jan 2035), the 31-day smoothing turns the step into a ramp lasting about a month, so the derived traces lag the RRY there.
5. **Large median-offset adjustments.** Southern and Melbourne are adjusted upward by an average of about 1,120 and 805 TJ/d. Confirm that this is the intended direction of the ISP 2026 RRY relative to the 2025 traces.
6. **Information after 2045.** The RRY repeats 2045 through 2051, so supply is flat from 2046 in all zones. The team may want to say so in any outputs that cover those years.

### Smoothing window comparison (median_offset zones, 2026-10-01)

| Window (days) | Gladstone monthly error | Melbourne monthly error | Southern monthly error | Melbourne daily error | Southern daily error |
|---|---|---|---|---|---|
| 91 | 2.7 | 44.5 | 55.3 | 66 | 78 |
| 61 | 2.1 | 31.9 | 38.2 | 57 | 66 |
| 45 | 1.6 | 22.8 | 27.2 | 51 | 60 |
| **31 (applied)** | 1.4 | 14.9 | 17.9 | 45 | 54 |
| 21 | 1.3 | 11.6 | 14.4 | 40 | 48 |
| 15 | 1.3 | 9.8 | 12.2 | 36 | 43 |
| 7 | 1.0 | 8.2 | 10.4 | 26 | 33 |

Errors are mean absolute differences in TJ/d. "Monthly" compares monthly medians with the RRY. "Daily" compares the day-by-day median across reference years with the RRY. A window of 1 day gives zero daily error but gives every reference year the RRY's weather.

## 9. POE10 vs POE50 single-reference-year traces

Script: `compare_poe50_poe10.py`. Outputs: `poe_comparison/` (summary CSVs, 11 zone overview charts, 142 zone-by-RY monthly charts, and optional daily charts per zone, RY and FY). Difference = POE10 − POE50, compared on days present in both files (2025-01-01 to 2045-12-31, all 13 RYs).

| Zone | Mean POE50 (TJ/d) | Mean difference | Mean absolute difference | 5th to 95th percentile of difference | Days identical |
|---|---|---|---|---|---|
| Colongra | 40.3 | 0.0 | 0.0 | 0 to 0 | 100% |
| Kurri Kurri | 60.0 | 0.0 | 0.0 | 0 to 0 | 100% |
| Gippsland | 134.4 | −0.04 | 1.9 | −6.7 to 6.2 | 60% |
| Newcastle | 275.1 | −0.1 | 8.2 | −31.5 to 30.8 | 75% |
| NQGP | 12.8 | 0.0 | 0.8 | −2.4 to 1.9 | 19% |
| Gladstone | 31.7 | −0.3 | 10.8 | −17.0 to 21.9 | 0% |
| Moomba | 433.3 | 0.0 | 6.7 | −13.7 to 16.7 | 0% |
| Northern | 2,834.2 | 0.0 | 12.7 | −22.8 to 25.7 | 0% |
| Port Campbell | 376.3 | −1.3 | 13.6 | −38.4 to 34.3 | 0% |
| Melbourne | 363.1 | 0.4 | 27.7 | −76.9 to 77.7 | 5% |
| Southern | 630.5 | −1.5 | 42.5 | −114.9 to 114.6 | 2% |

1. **No systematic level difference.** The mean difference is within 1.5 TJ/d of zero in every zone. POE10 and POE50 follow the same supply path and differ only in the daily weather detail. The POE10 higher/lower split is close to 50/50 in the weather-driven zones.
2. **Flat-limit zones are identical.** Colongra and Kurri Kurri have the same values in both. Newcastle and Gippsland are identical on 75% and 60% of days.
3. **The day-to-day spread is largest in Southern and Melbourne.** Their 5th to 95th percentile ranges are about ±115 and ±77 TJ/d. This is the same pair of zones that need the largest adjustments to the RRY.
4. **Port Campbell RY2012 exists at POE50 but not at POE10.** It is the only unpaired reference year, and it could be used instead of the median fill, with the caveat that POE50 and POE10 differ day to day (mean absolute difference 13.6 TJ/d for Port Campbell). Port Campbell uses the RRY directly, so this only affects dates before 2026-07-01.
5. **For the POE50 question.** The levels match on average, so adjusting POE50 would not mix two supply paths. The simpler position is to use the POE10 adjusted traces for POE50 runs, because the RRY exists only at POE10. The winter check below says what that costs.

### Winter and tight-day check

The all-day averages above could hide a difference on the days when gas constraints bind. I checked three proxies, because the real binding days would need the model's offtake results. "Winter" is June to August. "Tight days" are the lowest 10% of limit days in each zone, reference year and FY (Colongra and Kurri Kurri are excluded because they are flat). Differences are POE10 minus POE50, in TJ/d, pooled over FY2025–FY2046.

| Zone | Mean difference, all days | Mean difference, winter days | Mean difference, tight days | Mean difference in each year's minimum limit |
|---|---|---|---|---|
| Southern | −1.5 | −14.8 | −30.0 | −44.6 |
| Melbourne | 0.4 | −5.1 | −17.4 | −34.6 |
| Port Campbell | −1.3 | −1.3 | −11.1 | −9.9 |
| Moomba | 0.0 | −3.1 | −1.3 | −6.6 |
| Newcastle | −0.1 | −2.9 | −4.6 | −3.8 |
| Northern | 0.0 | −10.4 | +10.8 | +8.4 |
| Gladstone | −0.3 | −7.6 | +14.4 | +7.7 |
| Gippsland | 0.0 | −0.6 | −0.1 | −1.3 |
| NQGP | 0.0 | −0.4 | −0.2 | −0.4 |

1. **There is a winter signal.** In most zones POE10 limits are lower than POE50 on winter days (Southern −14.8, Northern −10.4, Gladstone −7.6, Melbourne −5.1 TJ/d), even though the all-day averages are near zero.
2. **Southern and Melbourne are tighter at POE10 on the tightest days.** The lowest limit each year is lower at POE10 by about 45 TJ/d in Southern and 35 TJ/d in Melbourne, and POE10 has the lower 5th-percentile limit in 64% and 48% of reference-year/FY pairs. With about 250 reference-year/FY pairs per zone, the Southern and Melbourne differences are well beyond sampling noise.
3. **Northern and Gladstone go the other way on tight days** (POE10 higher by 8 to 14 TJ/d), although POE10 is lower in winter generally.
4. **What this means.** Using POE10 gas traces in POE50 runs is slightly conservative where it matters most (Southern and Melbourne winter lows), by tens of TJ/d. That is small against the 1,000+ TJ/d levels in those zones in the early years, but it is a larger share of the lows after 2033, when Southern falls to a few hundred TJ/d. It is not a reason to avoid using POE10 only, but it should be stated.
5. **Limits of the check.** The tight-day measure is a proxy built from the limit values alone. It does not know whether a day actually binds in the model. If the team wants a firmer answer, the binding days from a model run would be the right filter.
