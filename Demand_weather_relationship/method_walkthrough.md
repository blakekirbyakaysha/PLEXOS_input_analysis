# Method walkthrough: how the weather materiality numbers were derived

Step by step, from raw data to conclusions. Code for each step is in this repo: `01_extract_data.py`, `02_prepare_daily.py`, `03_regressions.ipynb` and `04_weather_years.ipynb`.

---

## Step 1: Compile the data

Everything was pulled from QueryTool (NEOpoint).

| Data | Source | Resolution | Period |
|---|---|---|---|
| Operational demand | `mms.demandoperationalactual` | 30-min | Dec 2020 → Aug 2026 |
| Rooftop PV actual | `mms.rooftop_pv_actual` (TYPE = MEASUREMENT) | 30-min | Mar 2018 → Aug 2026 |
| Scheduled demand (TOTALDEMAND), long history | `mms.dispatchregionsum` | 5-min | 2010 → Aug 2026 |
| Temperature | `bom.metar` (BoM METAR obs) | 30-min | 2001 → Aug 2026 |
| Public holidays | supplied xlsx/csv files | daily | 2004 → 2026 |

**One weather station per region.** Each region uses the IASR 2025 station for the capital-city sub-region:
- NSW: Bankstown
- QLD: Archerfield
- SA: Kent Town, then West Terrace from Aug 2020
- VIC: Melbourne Regional Office, then Olympic Park from Jan 2015
- TAS: Hobart Ellerslie Rd

## Step 2: Build a daily dataset

For each region and day:

- **Energy (GWh).** Half-hourly MW summed into market days (interval-ending, AEST).
  - **Underlying demand = operational demand + rooftop PV.** This is the main dependent variable. Adding PV back stops PV growth being mistaken for a weather or trend effect.
  - Operational demand on its own is kept as a comparison.
- **Temperature.** Mean of the 48 half-hourly readings from 9 pm the previous day to 9 pm on the day. This is AEMO's convention. A day needs at least 44 of the 48 readings to count.
- **Degree days.** These use AEMO's thresholds (Methodology Table 6):
  - HDD = max(0, heating threshold − mean temp)
  - CDD = max(0, mean temp − cooling threshold)

  | Region | Heating threshold | Cooling threshold |
  |---|---|---|
  | NSW | 17.0 °C | 21.5 °C |
  | QLD | 17.0 °C | 22.0 °C |
  | SA | 16.5 °C | 22.0 °C |
  | VIC | 16.5 °C | 21.0 °C |
  | TAS | 16.0 °C | 20.0 °C |

- **Calendar fields:** day of week, month, public holiday flag, Christmas period flag (24 Dec – 2 Jan).
- **Quality flags.** Days with missing intervals or too few temperature readings are flagged and excluded. Nothing is filled in or estimated.

## Step 3: Run the regression

For each region, OLS on daily data. This is the main specification (M2):

```
Daily energy = β_HDD × HDD + β_CDD × CDD
             + day-of-week + month + holiday + Christmas period + linear trend + constant
```

- **Window:** 2022-09-01 → 2026-08-31, about 1,430 days per region.
- **Standard errors:** Newey-West (HAC, 7 lags), because daily demand errors are autocorrelated.
- **What the month dummies do:** β is identified from cold and hot spells *within* a month, compared with a normal day in that month. That is the variation that matters for "was this year colder or hotter than normal".

**Robustness checks:**
- **Other specifications:**
  - no calendar controls (M1)
  - a smooth seasonal curve instead of month dummies (M3)
  - adding yesterday's weather (M4)
- **Other samples and inputs:**
  - a longer window (2021–26)
  - max/min temperature instead of the 9 pm–9 pm mean
  - operational demand instead of underlying
- **Change over time:** rolling 4-year windows from 2010 on TOTALDEMAND, to see whether β drift.

## Step 4: Parameters obtained

M2, underlying demand, 2022–26:

| Region | β_HDD (GWh per HDD) | β_CDD (GWh per CDD) | R² | n (days) | Average annual energy |
|---|---|---|---|---|---|
| NSW | 4.09 | 8.15 | 0.90 | 1,434 | 75,100 GWh |
| QLD | 1.62 | 6.38 | 0.92 | 1,428 | 62,600 GWh |
| SA | 0.65 | 1.79 | 0.87 | 1,427 | 14,600 GWh |
| VIC | 2.42 | 5.96 | 0.88 | 1,437 | 49,500 GWh |
| TAS | 0.32 | 0.20 | 0.76 | 1,428 | 10,400 GWh |

- All mainland β are positive with p < 0.001.
- **Reading the parameters:** in VIC, a day 1 °C further below 16.5 °C adds about 2.4 GWh, and a day 1 °C further above 21 °C adds about 6.0 GWh.
- **Cooling β is stable** across specifications, varying by 11% or less.
- **Heating β varies by 25–48%** depending on the seasonal control. M2 is the lowest, so it is the conservative choice.

## Step 5: Build the weather history

- **Sum degree days by month.** For every region, monthly HDD and CDD were summed for each year from 2001 to 2025. NSW and QLD start in 2008, when their stations begin.
- **Invalid months.** A month is used only if at least 90% of its days have valid temperature data. Years with an invalid month are dropped from annual figures.
- **The "average year".** For each calendar month, the mean HDD and CDD across all valid years. For example, the VIC average year has 819 HDD and 144 CDD.

## Step 6: Estimate each weather year's effect on energy

For each region, year and month:

```
Weather effect (GWh) = β_HDD × (HDD in that month − average HDD for that month)
                     + β_CDD × (CDD in that month − average CDD for that month)
```

- **Monthly %:** divide by average energy for that month over 2022–26.
- **Annual %:** add up the 12 months and divide by average annual energy.

The result is the energy that year's weather would add to or remove from today's demand, compared with an average-weather year.

**Worked example: VIC 2023 (a mild year).**

| | 2023 | Average year | Difference | × β | Effect |
|---|---|---|---|---|---|
| CDD | 82 | 144 | −62 | × 5.96 | −366 GWh |
| HDD | 778 | 819 | −41 | × 2.42 | −100 GWh |
| **Total** | | | | | **−465 GWh = −0.94% of 49,460 GWh** |

## Step 7: Results

**Annual weather effect across all valid years (calendar years):**

| Region | Mildest year | Most extreme year | Years used |
|---|---|---|---|
| NSW | −1.0% | +0.8% | 13 |
| QLD | −1.2% | +1.3% | 17 |
| SA | −1.9% (2023) | +1.8% (2019) | 22 |
| VIC | −1.0% | +0.8% | 23 |
| TAS | −0.5% | +0.7% | 20 |

- **Monthly:** larger swings, concentrated in summer. The Dec–Feb summer season moves ±3–5% on the mainland. Individual SA months range from −8% to +14% on underlying demand, and from −11% to +18.5% on operational demand.
- **Why the annual effect is smaller than the monthly:** hot summers and cold winters partly offset within a year, and mild shoulder months dilute the total.

## Step 8: Compare with AEMO's traces

- **Annual energy is equalised.** AEMO scales each reference year to the same annual energy target while keeping its seasonal shape (Methodology §6.1). In the FY2027 traces, annual energy is effectively identical across reference years (NSW spread about 0.06%). What AEMO removes is therefore the Step 7 annual effect only.
- **Monthly variation matches weather.** In the FY2027 monthly heatmaps, the months that stand out match our Step 6 monthly estimates in direction for 13 of 16 standout months checked. Examples: SA March 2008 +18.5%, NSW January 2019 +7%. AEMO's swings are roughly 1.5–2× ours. The monthly weather effect is already in the traces.

## Step 9: Check a recent miss (VIC, July–August 2026)

- **Weather was normal.** July 2026 HDD was 5.67/day against a 2001–25 average of 5.64. August was milder than average.
- **The model under-predicts.** The M2 model fitted up to June 2026 under-predicts July and August by 7–9%.
- **The gap is spread across the day.** Against July 2025, which had identical HDD, demand was about +400 MW across all hours.
- **Conclusion:** this is demand level (growth, new load, PV), not weather.

## Step 10: Outlook to 2030

1. **Today's figure:** the largest annual swing from Step 7 (e.g. VIC ±1.0%).
2. **Growth:** the Step 6 calculation was repeated with β from each rolling 4-year window since 2010–13, divided by that window's average demand. The weather effect as a share of demand grew by:
   - VIC +76%
   - NSW +41%
   - QLD +37%
   - SA +21%
   - TAS about 0%
3. **Low end:** extend that trend to 2030, which gives a factor of ×1.1–1.25 (VIC ±1.2%).
4. **High end:** ×2 for likely model understatement, based on the AEMO comparison in Step 8 (VIC ±2%).

**Range to 2030:** NSW ±1.1–2%, QLD ±1.4–2.5%, VIC ±1.2–2%, SA ±2.1–4%, TAS ±0.7–1.5%.

## Conclusion

AEMO's traces already contain the large monthly and seasonal weather effect. The annual effect their scaling removes is modest: ±1–2.5% on the mainland to 2030, and ±2–4% in SA. It does not explain recent misses such as VIC in 2026.

**Recommendation:**
- Don't add weather-driven energy to the traces now.
- Look into demand level and PV instead.
- Revisit SA before 2030.

## Main limitations

- **One station per region.** This probably understates the weather effect, most of all in QLD and NSW.
- **Linear response above and below the thresholds.** Extreme heat may be understated.
- **Only four years of operational demand** are available to estimate β.
- **Heatmap comparison and the ×2 factor** were read by eye from charts.
- **The 2030 view is a trend extrapolation,** not a forecast. It does not use AEMO's electrification or data-centre assumptions.
