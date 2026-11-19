# Weather and AEMO demand traces: summary

## The question

AEMO scales every reference-year demand trace to the same annual energy target, whatever that year's weather was. We were concerned this was hiding a real weather effect, and that it was the main reason actual demand keeps landing outside the range of reference years. If so, we would need to give each reference year its own weather-driven annual or monthly energy.

## Short answer

Not for now, and not as a fix for the misses. Weather is not the main reason actual demand lands outside the range of the traces. SA is worth revisiting before 2030.

- **The annual effect is modest but not negligible.** For the period to 2030, weather is likely to change a year's total energy by about ±1–2% in NSW and VIC, ±1.5–2.5% in QLD, about ±2–4% in SA and about ±0.7–1.5% in TAS. This is the only part AEMO's approach removes.
- **The month-to-month effect is large, and the traces already carry it.** Within each reference year, AEMO's monthly energy rises and falls with that year's actual weather.
- **The miss we looked at in detail is not weather.** In VIC in July 2026, actual demand was above every reference year even though the weather was exactly average.

## What was done

1. **Built a daily dataset.** It covers demand and weather for each NEM region.
   - Demand is AEMO operational demand, plus rooftop PV added back.
   - Weather comes from one capital-city station per region, using AEMO's temperature conventions.
2. **Measured how much weather moves demand.** We estimated the extra energy used on each cold or hot day, controlling for weekdays, holidays, season and growth. We tested this several ways and checked it against 16 years of history.
3. **Replayed history against today's demand.** We applied today's weather sensitivity to every year of weather from 2001 to 2025 (from 2008 for NSW and QLD). This shows how much energy each year's weather adds or removes, by month and for the year.
4. **Compared the results with AEMO's traces.** We used the 2026 ESOO FY2027 traces (POE50, operational demand, Step Change), and checked VIC's July–August 2026 miss against actual weather.

## Findings

**1. Weather has a clear, reliable effect on daily demand.**
- In NSW, QLD, SA and VIC, demand rises on cold days and on hot days, and the relationship is statistically solid.
- The effect of hot weather is larger and more stable than the effect of cold. Tasmania responds to cold only.
- The effect has grown over time. VIC's response to cold and QLD's response to heat are each up about 50% since 2013, consistent with electrification and growth.

**2. At annual level, weather is a modest effect.**
- Using today's demand, annual energy varies across weather years by about ±1% in NSW, QLD and VIC, about ±2% in SA, and less than ±0.75% in TAS. Section 5 explains why the true figure to 2030 is probably higher.
- Hot summers and cold winters partly offset within a year, and mild spring and autumn months dilute the rest.
- AEMO's traces remove this difference by design. Annual energy is effectively identical across reference years: in NSW, for example, the spread is about 0.06%.

**3. Month to month, weather is a much bigger effect, and AEMO's traces already capture it.**
- AEMO's scaling keeps each reference year's own seasonal pattern and adjusts only the annual total. A reference year with a hot summer still has a high summer, balanced by lower energy in other months.
- The monthly heatmaps show this clearly. Summer months differ strongly between reference years; spring, autumn and TAS hardly differ. That is the same pattern our weather model predicts.
- The months that stand out in AEMO's traces are the months our model says were unusually hot or mild. Of 16 standout months we checked, 13 match in direction. Examples:

  | Reference-year month | AEMO trace | Our weather estimate |
  |---|---|---|
  | SA, March 2008 (Adelaide's record heatwave) | highest March | +18.5% |
  | SA, January 2004 / February 2006 | lowest of their months | −11% / −10% |
  | NSW, January 2019 (heatwave) | highest January | +7% |
  | NSW, February 2008 | lowest February | −5% |
  | VIC, March 2013 / January 2004 | high / low | +8% / −7% |
  | QLD, March 2019 / January 2011 | high / low | +4% / −3% |

- The three months that did not match (for example SA January 2022 and QLD May 2022) may reflect cloud and rooftop solar output rather than temperature. AEMO's traces include solar variation; our model does not.
- If anything, AEMO's month-to-month swings are larger than ours. That is probably because AEMO uses more weather stations and a more detailed model.

**4. VIC's July–August 2026 miss is not weather.**
- **The weather was ordinary.** July 2026 was exactly an average July in Melbourne, and August was milder than average.
- **Demand still came in above every reference year.** Our model, trained on data up to June 2026, under-predicts July and August by about 7–9%. The gap has been building since around March 2026.
- **It is spread across the day.** Compared with July 2025, which had identical weather, demand was about 400 MW higher across the whole day, with more at midday.
- **The likely causes are demand level, not weather.** Candidates are growth running ahead of AEMO's forecast (electrification, data centres, industrial load) and rooftop PV behaving differently from AEMO's assumptions.
- **Better weather adjustment would not close this gap.** Even if our model understates weather effects by half, no weather adjustment fixes a miss in a month with average weather.

**5. How confident we are, and the outlook to 2030.**
- **What we are confident in:**
  - The annual effect is a few percent, not 5–10%.
  - It is much smaller than the month-to-month effect.
  - SA has the largest effect and TAS the smallest.
- **The exact figures are more likely too low than too high.** Our model uses one weather station per region and a simple straight-line response to temperature, and both tend to understate weather effects. AEMO's standout months are about 1.5–2 times larger than ours; for example, SA March 2008 is about +30% in AEMO's traces against our +18.5%.
- **Changing demand drivers do not distort the history.** The method takes only the weather from past years. The demand side comes entirely from 2022–26 data, so older demand patterns (less air-conditioning, no data centres) do not enter the calculation.
- **Changing drivers do matter for the years ahead,** because demand is becoming more weather-sensitive. Electrification and more air-conditioning push the effect up. Data centres and flat industrial load dilute it, because they add energy that barely responds to weather.

**How the 2030 range was built**

*Step 1: today's figure.* Run every weather year from 2001 to 2025 through today's (2022–26) demand and take the largest swing in any year. VIC is about ±1.0%.

*Step 2: has that figure been growing?* Repeat Step 1 using how demand responded to weather in earlier periods. Take every 4-year period from 2010–13 to 2022–25 and divide by that period's average demand. This shows how weather-sensitive demand was, as a share of total demand, at each point in time. Between the 2010–13 and 2022–25 periods it grew:

| Region | Growth, 2010–13 to 2022–25 | Per year |
|---|---|---|
| VIC | +76% | about 5% |
| NSW | +41% | about 3% |
| QLD | +37% | about 2.5% |
| SA | +21% | about 1.5% |
| TAS | about 0% (slightly down) | about 0% |

*Step 3: extend the trend to 2030 (low end of the range).* Continue each region's line to the 2027–30 period. That makes the effect in 2030 larger than today by about +20% in VIC, +7–16% in NSW, +10–18% in QLD, +10–14% in SA, and about 0–6% in TAS. The low end of the range is today's figure multiplied by this. VIC: ±1.0% × 1.2 ≈ ±1.2%.

*Step 4: allow for our model understating (high end of the range).* AEMO's own traces show monthly weather effects up to about twice ours. The high end is therefore twice today's figure. VIC: ±1.0% × 2 ≈ ±2%. We did not multiply by the trend as well, because AEMO's FY2027 traces already build in their forward view of demand.

| Region | Today (Step 1) | Low end: today × trend (Step 3) | High end: today × 2 (Step 4) | Range to 2030 |
|---|---|---|---|---|
| NSW | ±1.0% | ±1.1% | ±2.0% | **±1.1–2%** |
| QLD | ±1.3% | ±1.4–1.5% | ±2.5% | **±1.4–2.5%** |
| VIC | ±1.0% | ±1.2% | ±2.0% | **±1.2–2%** |
| SA | ±1.9% | ±2.1% | ±3.8% | **±2.1–4%** |
| TAS | ±0.7% | ±0.7–0.8% | ±1.5% | **±0.7–1.5%** |

**Why the result is a range.** The true figure is most likely somewhere between the two ends. The low end assumes our model is right and the past trend simply continues. The high end assumes the true weather sensitivity is closer to what AEMO's traces imply. Faster electrification than in the past (for example, VIC homes moving off gas) would push toward the top. Rapid data-centre growth would pull NSW, VIC and QLD toward the bottom.

## Recommendation

- **Do not add weather-driven annual or monthly energy to AEMO's traces at this stage.**
  - Monthly and seasonal weather variation is already in the traces.
  - The annual difference that AEMO removes is modest: about ±1–2.5% a year on the mainland to 2030.
  - It would not address the misses we are seeing.
- **Revisit SA before 2030.** SA is the one region where the annual effect could reach ±3–4%. That is large enough to consider giving its reference years different annual energy.
- **Focus next on the non-weather drivers of misses.** These are demand level and growth against AEMO's forecast, starting with VIC, and rooftop PV against AEMO's assumptions (being checked separately).
- **To firm up the annual numbers:**
  - test the revenue impact of a ±2% (±4% for SA) annual energy change directly in the budget model. If revenue barely moves at the top of the range, the question is closed.
  - improve the weather measure (several stations per region) and how extreme heat is modelled. This would narrow the ranges above.
  - if AEMO's first-pass traces (before scaling to the annual target) can be obtained, they would show AEMO's own annual weather spread directly.

## Caveats

- **Heatmap comparison is by eye.** It was read from the charts; a numeric comparison is possible from the trace data.
- **Only VIC's recent miss was checked.** The explanation above does not cover other regions or summer months.
- **Model limits.** Weather effects are estimated from four years of demand and one weather station per region. They show correlation, not proven cause.
- **The 2030 outlook is a trend extrapolation, not a forecast.** It extends the 2010–2025 growth in weather sensitivity, measured on AEMO's longer demand history (TOTALDEMAND), which excludes rooftop PV. The factor of 2 in Step 4 comes from reading AEMO's heatmaps by eye and is the least certain input. It does not use AEMO's electrification or data-centre forecasts.
- **Demand measure.** The demand measure excludes batteries and some smaller embedded generation.
