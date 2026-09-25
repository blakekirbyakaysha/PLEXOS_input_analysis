# Elevator pitch: weather and AEMO reference-year traces

**Question.** AEMO grows every reference-year OPSO trace to the same annual energy target. Is that hiding a weather effect we should add back, and is it the reason actual demand keeps landing outside the reference-year range?

**What we did.**
- **Data.** Daily regional operational demand plus rooftop PV, regressed on HDD/CDD with calendar controls and trend. Weather is from one capital-city station per region, on AEMO's 9 pm–9 pm convention with AEMO's Table 6 thresholds.
- **Models.** OLS with HAC standard errors, over 2022–26. We tested four specifications, a longer window, and rolling windows back to 2010.
- **Weather-year effect.** For each year 2001–2025, we took the difference between its HDD/CDD and the average year's, month by month. We multiplied that difference by the 2022–26 β. The result is the extra (or reduced) energy that year's weather would cause at today's demand. Summed over the year, this is the part AEMO's annual scaling removes.
  - Example, VIC 2023: 62 fewer CDD × 5.96 GWh/CDD + 41 fewer HDD × 2.42 GWh/HDD ≈ −465 GWh, or −0.9% of annual energy.
- **Comparison.** Results were checked against the 2026 ESOO FY2027 traces, and against VIC's July–August 2026 miss.

**What we found.**
- **The relationship is solid.** Weather sensitivity is positive and significant in every mainland region (R² 0.87–0.92).
  - Cooling β is stable across specifications.
  - Heating β moves 25–48% depending on how seasonality is controlled.
  - The weather effect as a share of demand has grown 20–75% on the mainland since 2010–13, with VIC the fastest. TAS is flat.
- **The annual effect, which is the part AEMO removes, is modest.** About ±1% today in NSW, QLD and VIC, and ±1.9% in SA. Allowing for trend growth and likely model understatement, it is about **±1–2.5% on the mainland to 2030, and ±2–4% in SA**.
- **The monthly effect is large, and AEMO already keeps it.** Scaling preserves each reference year's seasonal shape. In the FY2027 heatmaps, 13 of 16 standout months match our weather estimates in direction (e.g. SA March 2008, NSW January 2019). AEMO's monthly swings are, if anything, larger than ours.
- **The misses are demand level, not weather.** VIC July 2026 was an exactly average weather month, yet actual demand sat above every reference year. The model under-predicts by 7–9% and the gap is spread across all hours. This points to growth or new load, and possibly PV, not a missing weather adjustment.

**Conclusion.** Don't add weather-driven annual or monthly energy to AEMO's traces now. The seasonal weather signal is already in them. The annual component they remove is ±1–2.5% (±2–4% in SA), and it doesn't explain the misses.

**Next steps.**
- Focus on why demand level differs from AEMO's forecast, starting with VIC, and on PV versus AEMO's assumptions.
- Revisit SA before 2030.
- If we want to close the annual question properly, test a ±2% (SA ±4%) annual energy shift in the budget model.

**Main caveats.**
- One weather station per region and a linear response. Both probably understate the effect.
- The heatmap comparison is by eye.
- The 2030 view is a trend extrapolation, not a forecast.
