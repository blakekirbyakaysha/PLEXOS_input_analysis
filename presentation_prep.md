# Presentation prep: weather slides (deck slides 10–15)

**Slide map:** 10 divider · 11 method in plain English · 12 what scaling keeps and removes · 13 annual effect chart and range to 2030 · 14 the VIC miss (context) · 15 weather test and recommendation. The section headings below use the earlier numbering: "Slide 11" = slide 12, "Slide 12" = slide 13, "Slide 13" = slides 14–15.

Written for the presenter. Sources: [method_walkthrough.md](method_walkthrough.md), [findings.md](findings.md), [summary_for_manager.md](summary_for_manager.md), the CSVs in `outputs/`. Where a number is **not** reproducible from this repo, it is marked ⚠.

## 1. The argument in 30 seconds

1. AEMO grows every reference-year trace to the same annual GWh, but keeps each year's seasonal shape.
2. So the question is: what does that equalising remove? Only the **annual net** weather effect. The within-year (monthly, seasonal) weather effect is still in the traces.
3. We measured how much a hot or cold day moves demand (regression), then replayed 2001–2025 weather through today's demand. The annual net effect is about **±1–1.3% (NSW, QLD, VIC), ±2.4% (SA), ±0.7% (TAS)** on operational demand (the quantity AEMO scales), and probably ±1.1–2.6% (SA ±2.7–4.9%) by 2030.
4. That is too small to justify changing the traces now, and it does not explain the VIC July–August 2026 miss, because that month had average weather.

## 2. How the numbers were made (the chain you must be able to explain)

| Step | What | Key fact |
|---|---|---|
| Data | Daily regional demand, 2022-09 → 2026-08, about 1,430 days per region | Underlying = operational + rooftop PV (so PV growth isn't mistaken for weather) is the main series for the regressions. **The slide 12 chart and 2030 ranges use operational demand**, because that is what AEMO scales to a common GWh |
| Weather | One capital-city station per region; mean temp over 9 pm–9 pm (AEMO convention); at least 44 of 48 half-hours present | HDD = max(0, heating threshold − T); CDD = max(0, T − cooling threshold); AEMO Table 6 thresholds, e.g. VIC 16.5 / 21 °C |
| Regression | Daily GWh on HDD, CDD, day-of-week, month dummies, holiday, Christmas, trend. OLS with Newey-West (7 lags) errors | β = extra GWh per degree day. Month dummies mean β comes from hot or cold spells *within* a month |
| Replay | For each weather year and month: β × (that month's degree days − the average for that month) | Sum 12 months, divide by average annual energy |
| Compare | AEMO FY2027 traces (POE50, OPSO_MODELLING, Step Change) | Annual energy equal across reference years; monthly heatmaps compared by eye |

**Worked example to have ready (VIC 2023, mild).** It uses the underlying β; the operational version is slightly different (VIC operational range is −1.06 / +0.80%), so call it illustrative:
CDD 82 vs average 144 → −62 × 5.96 = −366 GWh. HDD 778 vs 819 → −41 × 2.42 = −100 GWh. Total −465 GWh = **−0.94%** of 49,460 GWh.

**Coefficients (M2, underlying, GWh per degree day):**

| Region | HDD β | CDD β | R² |
|---|---|---|---|
| NSW | 4.09 | 8.15 | 0.90 |
| QLD | 1.62 | 6.38 | 0.92 |
| VIC | 2.42 | 5.96 | 0.88 |
| SA | 0.65 | 1.79 | 0.87 |
| TAS | 0.32 | 0.20 | 0.76 |

Plain-English reading: in VIC a day 1 °C below 16.5 °C adds about 2.4 GWh, and a day 1 °C above 21 °C adds about 6 GWh. Cooling costs more per degree than heating on the mainland.

## 3. Slide by slide

### New slide 11: "What we did, in plain English"
Four steps: measure the link (last four years of daily demand), replay 2001–2025 weather, separate what AEMO's scaling removes from what it keeps, test the VIC miss. Tiles: 4 years of data, the VIC 2023 example (−0.9%, underlying basis), 5 regions with one station each. Use it to define a degree day before any numbers appear.

### New slide 14: "The miss: VIC demand ran above the reference years in winter 2026"
Reuses slide 6's chart. The 2.5% (July) and 1.1% (August) are the median reference year against actual sent-out operational demand. This is the benchmark the audience has already seen. The next slide then asks whether weather explains it, using our own model (7–9%), so keep the two benchmarks separate.


### Slide 11: "Equal-GWh scaling removes only the annual part of weather"

**Message:** the large weather effect is seasonal, and AEMO's method keeps it. Only the annual net is removed.

- **Why is the annual smaller than the seasonal?** A hot summer is partly offset by a mild winter, and mild shoulder months add little. Mainland summer (Dec–Feb) moves ±3–5% but the annual is ±1–2%.
- **Summer ranges** (from `weather_year_monthly.csv`, derived in findings.md §4): NSW −3.8/+5.3, QLD −3.8/+3.7, SA −4.0/+3.8, VIC −2.6/+2.9, TAS −0.6/+0.5 (%).
- **"p < 0.001"** means both HDD and CDD β are positive and clearly non-zero in NSW, QLD, SA and VIC under every specification and both windows. TAS is excluded because its cooling term is weak (p = 0.004 in M2, insignificant in the longer window and in most rolling windows). That matches AEMO using no cooling term for Tasmania.
- **"87–92% R²"** is the share of day-to-day variation in demand explained by weather plus calendar. It is a fit statistic. It does not mean weather explains 87% of demand.
- **"13 of 16"** ⚠: this is a by-eye match between AEMO monthly heatmap cells and our monthly estimates, in direction only. Nine of the sixteen are listed in method_walkthrough.md Addendum A1 (SA 2008-03 +18.5%, SA 2004-01 −11.1%, SA 2006-02 −10.1%, VIC 2013-03 +8.3%, VIC 2004-01 −6.7%, NSW 2019-01 +7.2%, NSW 2008-02 −4.7%, QLD 2019-03 +4.2%, QLD 2011-01 −2.8%). The three misses are SA 2022-01, QLD 2022-05 (possibly cloud and PV, which a temperature-only model lacks) and VIC 2006-02. The remaining cells are not written down in the repo. If asked for all 16, say you read them from the charts and the trace file could not be loaded (pyarrow version mismatch).
- **"Only the annual net is removed"** relies on Methodology §6.1: traces are scaled to annual energy and max/min targets "such that seasonality … [is] preserved". The optimiser's half-hourly scale factors are not strictly uniform, so this is an approximation.

**Likely questions**
- *Isn't the seasonal weather signal also distorted by the scaling?* Somewhat. Scaling a hot year down to the annual target scales all its months down, so its summer peak is damped a little and its winter is lifted. This study did not quantify that. It is the same ±1–2% order of magnitude as the annual effect.
- *Why one weather station?* It follows the IASR 2025 Table 13 capital-city station per region. It probably understates the effect, most of all in QLD and NSW (see limits).

### Slide 12: "The annual weather effect is about ±1–2%, largest in SA"

**Message:** at today's demand sensitivity, the most extreme weather years move annual energy by 1–2%. SA is largest, TAS smallest.

**Chart values** (operational demand, M2, calendar years; `materiality_summary.csv`, `dep_var = oper_gwh`). The underlying figures are in brackets.

| Region | Min | Max | Valid years |
|---|---|---|---|
| NSW | −0.98 (−1.01) | +0.83 (+0.85) | 13 (from 2008) |
| QLD | −1.25 (−1.24) | +1.28 (+1.27) | 17 (from 2008) |
| VIC | −1.06 (−0.99) | +0.80 (+0.76) | 23 |
| SA | −2.43 (−1.89) | +2.37 (+1.84) | 22 |
| TAS | −0.52 (−0.53) | +0.72 (+0.74) | 20 |

**Why operational, not underlying.** AEMO scales operational demand (net of rooftop PV) to the same annual target. Underlying = operational + that reference year's PV, so underlying annual energy is *not* equal across reference years (sunny years carry more PV). What the scaling removes is therefore the weather effect on operational energy. The two bases give nearly the same answer except SA, where operational demand is about 22% smaller, so the same β is a bigger percentage (SA ±2.4% vs ±1.9%).

- **Typical year, not the extreme:** the s.d. of annual net % is NSW 0.58, QLD 0.79, SA 0.96, TAS 0.30, VIC 0.55. A typical year sits within about ±0.5–1%.
- **GWh terms:** NSW annual swing (max − min) is about 1,390 GWh on a base of 75,100. SA is about 545 GWh on 14,600.
- **Which years are dropped:** any year with a month under 90% valid temperature data. NSW loses 5 of 18 years, each for one bad month. TAS 2001–2003 are mostly dropped (Dec 2001–Jan 2002 METAR outage).
- **Mean vs median standard:** AEMO's standard is POE50. We use the mean year. The difference is ≤ 0.21% in every region.
- **Model choice:** the heating-β spread across M2, M3, M4-LR is 36% (NSW), 25% (QLD), 48% (SA). Re-running the annual ranges with the highest heating β (M3) changes them by < 0.2 percentage points, because cooling dominates the annual swing. Heating adjustment s.d.: NSW 247 vs cooling 458 GWh; QLD 73 vs 553; SA 43 vs 133; VIC 194 vs 258.

**Important nuance (the OPSO question).** The slide was first drafted on underlying demand and then switched to operational, which is the basis AEMO's traces use. If someone asks for underlying, the answer is the bracketed figures above. With M4-LR, SA operational is −2.76 / +2.69%.

**Related point: PV masks hot-day demand.** On sunny hot days PV hides some extra consumption from the grid, so the operational cooling β is lower than underlying in NSW and QLD (underlying is about 17–18% higher). As rooftop PV grows toward 2030, the operational weather response should shrink further. A 2022–26 operational β could therefore overstate the future effect, which pulls against the upward trend in the 2030 range.

**"Range to 2030" card ⚠ (the least solid part of the deck)**
- Low end = today's operational figure × growth in weather sensitivity as a share of demand. Growth comes from rolling 4-year windows, 2010–13 to 2022–25: VIC +76%, NSW +41%, QLD +37%, SA +21%, TAS about 0. It is extrapolated linearly to 2030 using the 2018–25 and 2013–25 fits, giving ×1.07–1.24 depending on region.
- High end = today's operational figure × 2. The 2 comes from reading AEMO's heatmaps by eye: their standout months look 1.5–2× ours (e.g. SA March 2008 ≈ +30% vs our +18.5%). It is not multiplied by the growth trend as well, because AEMO's FY2027 traces already include their forward view.
- **Recomputed on operational demand.** Only the "today" figure changed: NSW 0.98, QLD 1.28, VIC 1.06, SA 2.43, TAS 0.72. The growth factors are unchanged because they come from TOTALDEMAND rolling windows (NSW ×1.07–1.16, QLD ×1.10–1.18, VIC ×1.18–1.24, SA ×1.10–1.14, TAS ×1.00–1.06). Low ends are today × the lower factor (NSW 1.05, QLD 1.41, VIC 1.25, SA 2.68, TAS 0.72); high ends are today × 2 (1.95, 2.57, 2.12, 4.87, 1.44). The growth factors come from the earlier analysis (method_walkthrough.md Addendum A3) and were not re-derived here.
- **Decision (user): TOTALDEMAND is kept for the growth factors, labelled as a proxy on slide 12.** Operational demand on the server only starts 2020-12-01, so no operational history exists for a 2010-on trend. Expect the challenge "TOTALDEMAND isn't operational demand": the answer is that only growth rates are used, not levels, but TOTALDEMAND has definitional level shifts (generators moving between scheduled, semi-scheduled and non-scheduled), which could bias the trend either way. A cross-check on operational demand alone would only cover about 4 years.
- The long history uses TOTALDEMAND (scheduled demand, excludes rooftop PV), so only the growth rates are used, not the levels.
- It is a trend extrapolation, not a forecast. It ignores AEMO's electrification and data-centre forecasts. Faster VIC gas-to-electric would push VIC up. Data-centre load dilutes the percentage in NSW, VIC and QLD.

**Stat tiles**
- **"±2.4%"** is SA's largest annual swing on operational demand (extreme years are 2023 at −2.43% and 2019 at +2.37%, the same as on underlying).
- **"+76%"** is VIC's weather effect as a share of demand, 2010–13 window to 2022–25 window (s.d. of annual net %: 0.38 → 0.67). About 5% a year. It reflects electrification and growth in weather-sensitive load.
- **"0.06%"** ⚠ is the NSW spread of annual energy across AEMO's reference years, read from AEMO's chart (`REGION_NSW_2_spread_by_fy.png`). It is not in this repo's outputs.

**Likely questions**
- *Why do the bars look different from the tiles?* ±2.4% is SA only. NSW, QLD, VIC are about ±1–1.3%.
- *Does a ±1–2% energy difference matter?* Unknown. We didn't test revenue impact. That is the recommended next step.
- *Is ±1.5% a standard threshold?* It is our own materiality criterion from the plan (PLAN §8): Proceed if annual ≥ ±1.5% or monthly ±5% in ≥ 20% of months. Only SA meets the annual test. The monthly test is met nowhere (max 7.1% of months in SA, underlying M2). Verdict: **Refine**, not Proceed or Stop.
- *Why did SA go from ±1.9% to ±2.4%?* We switched from underlying to operational demand, which is the series AEMO scales. SA's β barely change, but its operational base is smaller, so the same GWh is a larger percentage.
- *Why isn't TAS in the "adjust" list?* Annual swing is ±0.5–0.75%, below the Stop level, and it has no real cooling response. We recommend dropping it.

### Slide 13: "VIC's July–August 2026 miss is not a weather miss"

**Message:** even a perfect weather adjustment would not close the gap, because the weather in those months was ordinary.

- **Weather:** July 2026 mean 10.83 °C vs 10.86 °C long-run; HDD/day 5.67 vs 5.64. August 12.03 °C vs 11.66 °C (milder).
- **The model:** the M2 regression fitted only to 2022-09-01 → 2026-06-30, then used to predict July and August. Residuals (actual minus model):

  | Month | Operational | Underlying | Rooftop PV |
  |---|---|---|---|
  | July 2026 | +11.3 GWh/day (+7.7%) | +9.3 | −2.0 |
  | August 2026 | +12.2 GWh/day (+9.1%) | +9.7 | −2.4 |

  Residuals rise from about +2 GWh/day in March 2026. That is where "7–9%" comes from (operational).
- **400 MW:** July 2026 vs July 2025 (same HDD): about +390 MW overnight, +490 MW at 10–16 h, +417 MW averaged over the day. August: +220 MW overnight, +640 MW midday.
- **Interpretation:** demand level (growth, electrification, data centres, industrial load) plus a midday component (PV below trend or midday load). It is a hypothesis, not a proven cause.

**Likely questions**
- *This contradicts slide 6?* Slide 6 compares actual sent-out operational demand with the OPSO_MODELLING reference years: forecast is 1–2.5% low. Slide 13 compares actuals with our own regression model on as-generated operational demand. Different benchmark, different basis. Both say demand is above expectations, and neither is weather. Keep the two numbers separate.
- *Maybe the model just misses cold-snap behaviour?* Both months had average or mild weather, so there is no weather anomaly to mis-fit. Even if our model understated weather effects by half, no weather adjustment fixes a miss in an average-weather month.
- *Why does the gap start in March?* Not established. It is a rise in the residual from about +2 GWh/day. That timing is worth investigating with demand growth and PV data.
- *Does this cover other regions or summer?* No. Only VIC July–August was checked.

**Recommendation card**
- Don't add weather-driven annual or monthly energy now. The annual component is ±1–2.5%, and the seasonal part is already there.
- Revisit SA before 2030, where the annual effect could reach about ±5%.
- Test ±2.5% (SA ±5%) annual energy shifts in the budget model. If revenue barely moves at the top of the range, close the question. This is next step 1 in findings.md.

## 4. Where the analysis is weakest (say these before someone else does)

1. **Four years of data** (2022-09 → 2026-08) fix β. Confidence intervals are about ±10%, but the real risk is systematic bias, which mostly points down.
2. **One station per region.** Errors in the temperature measure bias β toward zero and understate weather spread. Worst in QLD (load in CQ/NQ) and NSW.
3. **Linear response beyond the thresholds.** Heatwave non-linearity is untested, and summer is where the material effects sit.
4. **Heating β is not pinned down:** M2 4.09 vs M3/M4-LR up to 5.57 in NSW. We use M2, the lowest, and show it barely changes annual ranges. It matters more if the question moves to winter months.
5. **Fixed sensitivity.** Historical weather is replayed through today's demand. It ignores the trend toward more weather-sensitive load, which is why the 2030 range is wider.
6. **Underlying demand is only operational + rooftop PV.** It excludes batteries, PVNSG, VPPs, exempt generation and industrial changes. Large industrial loads dilute percentages, notably in TAS.
7. **The ×2 and the 13 of 16 are by-eye** from AEMO charts. The comparison to AEMO could be made numeric if the trace data can be loaded.
8. **Correlation, not causation.**

## 5. Numbers to know cold

| | |
|---|---|
| Annual effect today (operational M2) | NSW ±1.0, QLD ±1.3, VIC ±1.1, SA ±2.4, TAS ±0.7 (%) (underlying SA is ±1.9) |
| Range to 2030 (operational) | NSW 1.1–2, QLD 1.4–2.6, VIC 1.3–2.1, SA 2.7–4.9, TAS 0.7–1.4 (%) |
| Summer (Dec–Feb) swing, mainland | ±3–5% |
| Monthly months beyond ±5% | NSW 2.9%, QLD 1.4%, SA 7.1%, TAS 0%, VIC 1.7% of valid months |
| β heating spread across models | NSW 36%, QLD 25%, SA 48%, VIC 24%, TAS 7% |
| Growth in sensitivity, 2010–13 → 2022–25 | VIC +76%, NSW +41%, QLD +37%, SA +21%, TAS ≈ 0 |
| VIC 2023 example | −465 GWh, −0.94% |
| VIC Jul–Aug 2026 | weather average; model under-predicts by 7–9%; +400 MW vs July 2025 |
| Verdict | Refine. Don't adjust now; revisit SA before 2030; test revenue impact |

## 6. Questions I'd expect, with short answers

- **"What is a degree day?"** The number of degrees the day's mean temperature is below the heating threshold (HDD) or above the cooling threshold (CDD). A 12 °C day in VIC (threshold 16.5) is 4.5 HDD.
- **"Why 9 pm–9 pm?"** AEMO's own convention, so the weather day matches how AEMO builds its models.
- **"Why month dummies?"** They stop cold-weather coefficients from absorbing winter effects such as longer lighting hours. They identify β from within-month spells, which is what "this winter was colder than normal" means.
- **"Why underlying for the regressions but operational on the slides?"** The regressions use underlying so rooftop PV growth isn't mistaken for a trend or weather effect. The slides report operational because AEMO scales operational demand, so that is what its method removes. The two give similar percentages except in SA.
- **"Is the heating β really that uncertain?"** Yes across specifications, but it makes little difference to the annual number, because cooling dominates the annual swing.
- **"What would change your mind?"** If the revenue test shows ±2.5% (SA ±5%) annual energy moves revenue materially; if multi-station weather raises β substantially; or if the first-pass (pre-scaling) AEMO traces show a larger annual weather spread than ours.
- **"What does AEMO do differently?"** More stations, a more detailed model (their Table 6 thresholds come from residential per-connection data), and scaling to a target; their monthly weather swings look about 1.5–2× ours.
- **"Why not just use all 25 weather years?"** Each reference-year trace is a single weather year. The annual figure is the spread across those years, which is what the chart shows.

## 7. Final state and pre-presentation checklist

**Deck:** `Gas_Traces_Summary_with_weather.pptx`. Slides 1–9 are unchanged. Slide 10 is the divider; slides 11–13 are the weather content, each with speaker notes.

**Labelled as indicative on slide 12:** the "Range to 2030" card and the +76% VIC tile. Reason: the growth factors come from TOTALDEMAND (operational demand starts 2020-12; the archive has no earlier file), and SA's series has a break around 2022.

**Before you present**
1. Decide whether you are comfortable with the ⚠ numbers: the 0.06% NSW spread, the 13-of-16 heatmap matches and the ×2 allowance were read by eye from AEMO charts.
2. Have the slide 6 vs slide 13 answer ready (OPSO traces 1–2.5% low vs our model 7–9% low; different benchmark).
3. Know why slide 12 is operational and the regressions are underlying (section 6).
4. Know the one-line answer to "TOTALDEMAND isn't operational demand" (growth rates only; stable ratio in NSW, QLD, VIC over 2021–26; SA break).
5. Open item, not blocking: if AEMO supplies restated operational history back to 2016, the trend factors can be re-measured on the right series.
