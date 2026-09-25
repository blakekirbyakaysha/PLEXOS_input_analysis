# Findings: does weather move annual NEM demand enough to matter?

First-pass, exploratory check (Phase 5 of [docs/PLAN.md](docs/PLAN.md)). It is correlational, not a forecast.

## Summary

**Verdict against §8: Refine.** Do not adopt weather-dependent annual energy for the reference-year traces yet. Weather does have a real, measurable effect, and a better-specified study is justified for the mainland regions, starting with SA1.

- **The relationship is real and well determined on the mainland.** In NSW1, QLD1, SA1 and VIC1, daily demand rises on cold and hot days. Both effects are positive and significant (p < 0.001) under every model and in both windows.
- **The cooling (hot-day) response is stable. The heating (cold-day) response is not pinned down.** The estimated heating sensitivity changes by 25–48% depending on how the seasonal calendar is controlled (NSW1, QLD1, SA1). That fails the §8 stability test.
- **At annual level, the effect is moderate.** Holding today's sensitivity fixed and replaying 2001–2025 weather, the weather-driven swing in annual energy is about ±1% of annual energy in NSW1, QLD1 and VIC1, and about ±1.9% in SA1. TAS1 stays within ±0.75%.
  - SA1 is the only region that passes the ±1.5% "Proceed" threshold, and it does so in 2 of 22 years (2019 and 2023).
- **Seasonally, the effect is large.** Summer (Dec–Feb) energy moves by ±3–5% on the mainland from weather alone. AEMO's scaling keeps each reference year's seasonal shape and resets only its annual total (Methodology §6.1). Most of this seasonal signal is therefore already in the traces; the part AEMO removes is mainly the annual net figure above.
- **Sensitivities are rising over time.** Since 2013, VIC1's heating response is up about 50% and QLD1's cooling response is up about 47%, consistent with electrification and growth. Numbers based on today's sensitivity may understate the effect in future years.

## What was done

- **Daily demand, 2022-09 to 2026-08, per region.**
  - "Underlying" demand = operational demand + rooftop PV. This is the main measure.
  - Operational demand alone is used as a comparison.
- **Weather.** One capital-city weather station per region. The day runs 9 pm to 9 pm, as in AEMO's methodology. The station's temperature is converted to:
  - **heating degree days (HDD):** degrees below AEMO's heating threshold, roughly 16–17 °C
  - **cooling degree days (CDD):** degrees above AEMO's cooling threshold, roughly 20–22 °C
- **Regressions.** Linear regressions give **β**, the extra GWh of daily demand per degree day. They control for day of week, holidays, the Christmas period, trend and season.
  - M1: no calendar controls.
  - M2: month dummies.
  - M3: smooth seasonal curve.
  - M4: adds the previous day's weather.
- **Weather-year replay.** Today's β were applied to each historical year's monthly degree days relative to the long-run average. The result is that year's weather-driven energy difference, as a % of average annual energy.

All inputs, code and checks are in the phase scripts and notebooks. Review notes are in [docs/PROGRESS.md](docs/PROGRESS.md).

## 1. How strongly does demand respond to weather?

Primary window 2022-09-01 → 2026-08-31, underlying demand, model M2. Units are GWh per degree day.

| Region | β heating (HDD) | β cooling (CDD) | R² | Typical daily demand |
|---|---|---|---|---|
| NSW1 | 4.09 | 8.15 | 0.90 | ~206 GWh |
| QLD1 | 1.62 | 6.38 | 0.92 | ~171 GWh |
| SA1 | 0.65 | 1.79 | 0.87 | ~40 GWh |
| TAS1 | 0.32 | 0.20 (p = 0.004) | 0.76 | ~29 GWh |
| VIC1 | 2.42 | 5.96 | 0.88 | ~135 GWh |

- **All mainland β are positive with p < 0.001.** The fits are good: weather plus calendar explains 87–92% of the day-to-day variation. The diagnostic plots ([outputs/figures/diag_NSW1.png](outputs/figures/diag_NSW1.png) and the other regions) show the expected U-shape, a flat band between the thresholds, and no obvious drift in the residuals.
- **Cooling dominates the mainland.** A hot day costs NSW1 about twice as much energy per degree as a cold day.
- **TAS1 is heating-driven.** Its cooling term is small and unstable: it is insignificant in the longer window and in most rolling windows since 2020. This matches AEMO, which uses no cooling term for Tasmania, and §8 does not count it against the result.

### Stability across models (the heating problem)

The table shows the spread between M2, M3 and M4-long-run, as max/min − 1. §8 requires this to be ≤ 25%.

| Region | Heating spread | Cooling spread |
|---|---|---|
| NSW1 | **36%** (4.09 → 5.57) | 9% |
| QLD1 | **25.2%** (1.62 → 2.03) | 5% |
| SA1 | **48%** (0.65 → 0.96) | 9% |
| TAS1 | 7% | 46% (weak term) |
| VIC1 | 24% (2.42 → 3.00) | 11% |

- The cooling β barely moves between specifications. The heating β does.
  - M2 (month dummies) gives the lowest heating β.
  - M3 (smooth seasonal curve) gives the highest.
- **Why:** cold weather coincides with other winter effects, such as longer lighting hours, darker evenings and winter behaviour. How much of the winter lift gets attributed to "cold" depends on how the calendar is modelled.
  - M2 uses only within-month cold snaps. That is the variation most relevant to "was this winter colder than normal", so M2 is the conservative choice used for the adjustments.
  - The question is not settled, though, and resolving it is the first modelling task below.
- **Heating matters less than cooling for the annual swing on the mainland.** The heating adjustment's year-to-year variability is smaller than cooling's everywhere: NSW1 247 vs 458 GWh (s.d.), QLD1 73 vs 553, SA1 43 vs 133, VIC1 194 vs 258. Rescaling the heating adjustment to the M3 β (the highest) barely changes the annual ranges: NSW1 −1.02/+0.94%, QLD1 −1.20/+1.24%, VIC1 −1.08/+0.86%, SA1 −2.08/+1.92%. No new region crosses ±1.5%. This check was done for this write-up; it is not part of the Phase 4 outputs.

### Stability across windows and over time

- **Longer window (2021-01 → 2026-08):** β are close to the primary window. The exception is QLD1 heating, which is 14% lower (1.39 vs 1.62).
- **Rolling 4-year windows back to 2010 ([rolling_betas.png](outputs/figures/rolling_betas.png)).** These use AEMO's scheduled-demand series (TOTALDEMAND), which has a longer history.
  - β have risen steadily in NSW1, QLD1 and VIC1:
    - VIC1 heating: 1.7 → 2.6
    - VIC1 cooling: 4.1 → 5.9
    - QLD1 cooling: 3.7 → 5.4
    - NSW1 cooling: 5.6 → 6.9
  - SA1 is flat. TAS1 heating is flat.
  - This is the expected direction as air-conditioning and electric heating spread and load grows. It means the relationship is not fixed.
- **Max/min temperature instead of the 9 pm–9 pm mean:** cooling β is 11–18% lower in NSW1, QLD1 and VIC1, and heating β is about the same. This is partly a scale effect, because the two temperature measures produce different degree-day totals. It still shows that the temperature definition matters for hot days.

## 2. Effect of calendar and trend controls

Adding day-of-week, holiday, month and trend controls (M1 → M2):

| | Underlying | Operational |
|---|---|---|
| Heating β, NSW1/SA1/VIC1 | −28% to −37% | −45% to −63% |
| Heating β, QLD1 | +12% | −53% |
| Cooling β, mainland | −16% to 0% | −12% to +12% |

- Without calendar controls, the heating β absorbs seasonal effects that are not weather.
- Cooling β is largely unaffected, which is further evidence that the hot-day response is robust.

## 3. Does adding rooftop PV back change the answer?

- **The cooling response is higher when PV is added back in NSW1 and QLD1**, by about 17–18% (NSW1 8.15 vs 6.96; QLD1 6.38 vs 5.39).
  - Hot days are mostly sunny. Rooftop PV output rises with them and hides part of the extra consumption from the grid.
  - SA1 (0.99×) and VIC1 (1.01×) show no difference.
- **QLD1 heating is also higher on underlying demand** (1.62 vs 1.00). Cold Brisbane winter days tend to be clear, so PV again masks consumption.
- **As a % of annual energy, the two definitions give similar materiality.** Operational demand has both a smaller β and a smaller base.
  - The exception is SA1. Its β are the same on both definitions, but its operational energy is 22% smaller, so the % swing is larger on operational (annual −2.4% / +2.4%).
  - For a trace-level adjustment (OPSO is operational demand), the SA1 operational figure is the relevant one.

## 4. How big is the weather-year effect?

Today's (2022–26) sensitivity applied to each historical weather year, relative to the average weather year. Underlying demand, M2, calendar years; FY in brackets. Full table: [outputs/materiality_summary.csv](outputs/materiality_summary.csv); chart: [annual_adjustment.png](outputs/figures/annual_adjustment.png).

| Region | Valid years | Annual min | Annual max | Annual swing, GWh (max − min) | Months beyond ±5% | Months beyond ±2.5% |
|---|---|---|---|---|---|---|
| NSW1 | 13 | −1.01% (−1.10%) | +0.85% (+1.05%) | 1,390 | 2.9% | 13.0% |
| QLD1 | 17 | −1.24% (−1.15%) | +1.27% (+0.90%) | 1,580 | 1.4% | 14.0% |
| SA1 | 22 | **−1.89%** (−1.24%) | **+1.84%** (+1.33%) | 545 | 7.1% | 24.1% |
| TAS1 | 20 | −0.53% (−0.55%) | +0.74% (+0.48%) | 130 | 0.0% | 0.4% |
| VIC1 | 23 | −0.99% (−0.57%) | +0.76% (+1.00%) | 870 | 1.7% | 10.1% |

- **A typical year sits within about ±0.5–1%** (standard deviation of annual net %: NSW1 0.58, QLD1 0.79, SA1 0.96, TAS1 0.30, VIC1 0.55).
- **Only SA1 has years beyond ±1.5%:** 2019 (+1.84%, hot) and 2023 (−1.89%, mild). On a financial-year basis SA1 stays within ±1.5% on underlying demand, but reaches −1.60% / +1.72% on operational demand.
- **The model choice barely matters here.** Using the M4 long-run β widens every range by only 3–10%.
- **Mean vs median standard:** AEMO's standard is the POE50 median; this analysis uses the mean. The difference is ≤ 0.21% in every region, so the choice is immaterial.
- **Monthly effects are concentrated in summer** ([monthly_heatmap.png](outputs/figures/monthly_heatmap.png)). Every month beyond ±5% is in November–March. April–October never exceeds ±5% in any region.
- **Seasonal view:** these figures were computed for this write-up from [weather_year_monthly.csv](outputs/weather_year_monthly.csv). They are Σ net adjustment ÷ Σ average monthly energy, for seasons with all three months valid.

  | Region | Summer Dec–Feb, min / max | Winter Jun–Aug, min / max |
  |---|---|---|
  | NSW1 | −3.8% / +5.3% | −1.1% / +1.4% |
  | QLD1 | −3.8% / +3.7% | −0.7% / +0.7% |
  | SA1 | −4.0% / +3.8% | −1.2% / +1.2% |
  | VIC1 | −2.6% / +2.9% | −1.0% / +1.2% |
  | TAS1 | −0.6% / +0.5% | −1.2% / +1.1% |

- **Why the annual number is smaller than the summer number:** a hot summer is partly offset by a mild winter (or the reverse), and the mild shoulder months dilute the rest.
- **What this means for AEMO's method.** AEMO scales each reference year to the same annual energy while preserving its seasonal shape (Methodology §6.1).
  - The weather signal within a year is therefore largely kept, as the relative size of summer vs winter.
  - What is lost is the annual net effect in the table above.
  - The optimiser's half-hourly scale factors are not strictly uniform, so this is an approximation.

## 5. Decision against §8

| Test | NSW1 | QLD1 | SA1 | VIC1 | TAS1 |
|---|---|---|---|---|---|
| β positive, p < 0.05 (run A, M2) | ✔ | ✔ | ✔ | ✔ | ✔ heating (cooling ✔ but weak; exempt) |
| M2, M3 and M4-LR within ±25% | ✘ heating 36% | ✘ heating 25.2% | ✘ heating 48% | ✔ | ✔ heating (cooling exempt) |
| Annual ≥ ±1.5% **or** monthly ±5% in ≥ 20% of months | ✘ (±1.0%; 3%) | ✘ (±1.3%; 1%) | ✔ annual (±1.9%) | ✘ (±1.0%; 2%) | ✘ |
| Stop level: annual < ±0.75% **and** monthly ±2.5% in < 20% of months | not met | not met | not met | not met | **met** on M2 (max +0.74%); marginal on M4-LR (+0.79%) |
| β sensitive to definition, window or path? | cooling rising over time | heating by definition/window; cooling rising | stable | heating and cooling rising | cooling unstable |

**Result: Refine.**
- No region meets all three Proceed tests. Even SA1, which is closest (large enough and stable over time), fails the heating-spread test.
- No mainland region is at Stop level: every one has years beyond ±0.75%.
- β also change materially with demand definition (QLD1) and over time (NSW1, QLD1, VIC1). That alone is a Refine trigger under §8.
- **TAS1 alone is at Stop level.** Weather-year differences in its annual energy are too small to matter (±0.5–0.75%). It should be dropped from further work, unless a later multi-station or industrial-load-adjusted version changes that.

How §8 was applied: the materiality test was read region by region, on underlying demand with M2. §8 does not say whether "either … or" must hold per region or overall. Reading it overall, the conclusion is the same.

## 6. What this means for budgeting and revenue

- Holding today's sensitivity fixed, choosing one weather year over another moves annual regional energy by roughly **±1% (NSW1, QLD1, VIC1)** and **±2% (SA1)**.
  - For NSW1 that is about −650 to +550 GWh a year of operational energy against ~66,400 GWh.
  - In SA1 it is about ±270 GWh of operational energy (±2.4%) against ~11,400 GWh.
- The current AEMO method removes this spread by design. Our scenario range across reference years is therefore slightly too narrow on energy volume, most of all in SA1 and in hot or mild summers.
- The larger weather effect is seasonal and on peak days, and the traces already carry most of that. Whether a ±1–2% change in annual volume matters for revenue depends on how revenue responds to energy volume versus price shape and extremes. This study did not test that, and it is the most useful next question (step 1 below).

## 7. Next steps, in priority order

1. **Test the revenue impact directly.** Take a few reference years at the extremes (e.g. SA1 2019 and 2023, QLD1 2008 and 2019), rescale their OPSO traces by the annual (or monthly) net adjustment, and run them through the budget model. If revenue moves by less than other known uncertainties, stop here. This is the §9 deferred item "apply adjustments to AEMO reference-year traces".
2. **Resolve the heating-β specification question** (M2 vs M3). Add explicit controls for day length / lighting and school holidays, and compare the models on held-out years. This is the only Proceed test the mainland fails apart from size.
3. **Multi-station, population-weighted regional weather** (AEMO-style), particularly QLD1 (load in CQ/NQ) and NSW1. A single capital station understates regional weather variation. This will probably raise both β and materiality.
4. **Nonlinear and heatwave effects**: quadratic or spline response, and consecutive hot days. The linear-beyond-threshold assumption is untested, and summer is where the material effects sit.
5. **Account for the rising trend in sensitivity.** Decide whether forward years should use today's β or a projected β that includes electrification, since some β have risen by up to ~50% in a decade.
6. **Climate-adjusted historical weather.** 2001–2010 weather may be cooler than today's climate, which biases the "standard" year.
7. **Large-industrial-load controls and a residential/business split** (smelters dilute percentages, especially in TAS1), then battery/PVNSG/ONSG reconstruction for a truer underlying series.
8. **COVID and structural-break handling** in the longer history.

## 8. Caveats

- **Correlational, not causal.** OLS on about four years of operational demand (2022-09 → 2026-08).
- **One weather station per region**, the capital-city sub-region station. This is weakest for QLD1 and NSW1. Station changeovers (Melbourne Jan 2015, Adelaide Aug 2020) make the historical weather less consistent.
- **Weather history for NSW1 and QLD1 starts in 2008,** whereas AEMO's reference years start in 2001.
  - NSW1 annual results rest on 13 of 18 years. Five years were excluded, each for a single month with too many missing observations.
- **Fixed sensitivity.** Today's β are applied to historical weather: no electrification, appliance or climate trend. The response is assumed linear beyond AEMO's thresholds, which AEMO fitted to residential per-connection data, not regional totals.
- **"Underlying" is an approximation.** It is operational demand + rooftop PV only. It excludes batteries, PVNSG, ONSG, VPPs, exempt generation and industrial changes.
- **Definition mismatch.** Operational demand here is as-generated; OPSO traces are sent-out. The difference is immaterial for percentages.
- **TOTALDEMAND** (used only for the rolling history) has definitional level shifts. Rooftop PV (MEASUREMENT) is only available from 2018.
- **Industrial loads dilute percentages.** Large industrial loads and outages remain in the demand series.
