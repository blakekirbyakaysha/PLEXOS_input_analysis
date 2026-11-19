# Demand representation review — findings for team discussion

## Motivation

Two things kicked this off:

1. Backcasting the PLEXOS model against AEMO `TOTALDEMAND` instead of AEMO's own demand forecasts showed a large demand gap. The model is built around AEMO's demand forecasts (`OPSO_MODELLING`) as an input, so using a different, non-equivalent series as the comparison point was always going to show a mismatch — the question was how much of the gap was real and how much was a bad comparison.
2. Separately, we want to know whether our demand representation can be improved to better forecast price outcomes, or at least capture a wider range of plausible price outcomes.

## Findings

### 1. AEMO's demand traces: energy is stable, shape is not

Across reference years, AEMO's `OPSO_MODELLING` traces don't vary much in annual energy, but the half-hourly shape (seasonal and diurnal) varies a lot between reference years. Any comparison or sensitivity work needs to account for shape, not just annual totals.

### 2. `TOTALDEMAND` is the wrong comparator; operational demand is correct

`TOTALDEMAND` (`DISPATCHREGIONSUM`) is NEMDE's dispatch-target figure, not a clean demand measurement. It excludes demand met by significant non-scheduled generation (wind/solar ≥30 MW and a few named units) — which the PLEXOS model represents as generator objects — and it's as-generated rather than sent-out, so it also carries auxiliary load. These two errors partly cancel in aggregate, which is why `TOTALDEMAND` can look deceptively close to operational demand, but they don't cancel consistently: for Jul–Aug 2026 the net difference between `TOTALDEMAND` and sent-out operational demand ranges from **−2.8% (TAS) to +5.9% (QLD)**, and it moves with wind/solar output within the day. Full breakdown in [`Note_TOTALDEMAND_vs_OPSO.md`](Note_TOTALDEMAND_vs_OPSO.md).

`MMS.DEMANDOPERATIONALACTUAL` operational demand is the correct actuals series to use instead.

### 3. Operational demand still needs an as-generated → sent-out conversion

Raw operational demand includes auxiliary load and interconnector losses that `OPSO_MODELLING` excludes. Converting (subtracting IASR-derived auxiliary load and allocated interconnector losses — see `compare_to_actuals.py`) closes a meaningful part of the remaining gap. For Jul–Aug 2026 this adjustment is **~3.6–5.6% of operational demand in NSW/QLD/VIC**, and under 1% in SA/TAS (interconnector losses add another ~0.4–0.6%).

With both corrections applied — using operational demand instead of `TOTALDEMAND`, and converting it to a sent-out basis — the delta between actuals and `OPSO_MODELLING` closes significantly. For NSW in Jul–Aug 2026, the operational-demand energy error against `OPSO_MODELLING` is **~5–8%** across reference years (see `Comparison_PV_Underlying/all_regions_error_decomposition.csv`), down from the much larger apparent gap when `TOTALDEMAND` was used as the comparator.

### 4. BtM VPP is double-counted in the backcast as currently configured

The PLEXOS model includes BtM VPP as a generator/storage object. But AEMO doesn't have real-world VPP visibility yet, so real-world VPP behaviour is already embedded in the adjusted operational demand actuals (it shows up as part of measured demand, not separately). Running the backcast with the VPP object active double-counts that behaviour.

To compare demand correctly we need to either:
- subtract real-world VPP behaviour from the actuals before comparing, or
- add equivalent VPP behaviour into the `OPSO_MODELLING`-basis trace.

Until one of those is done, **the VPP object should be turned off in the backcast** — this is the single highest-value model-input fix.

### 5. Underlying-demand (pre-PV) comparisons are not currently valid

AEMO's `PV_TOT` trace includes PVNSG (non-scheduled PV from 100 kW up to 30 MW) as well as rooftop PV. We only have real-world data for rooftop PV (`MMS.ROOFTOP_PV_ACTUAL`), not PVNSG, so there's no actual-side equivalent to net off against `PV_TOT`. This means the `ROOFTOP_PV` and `UNDERLYING` (operational + PV) comparisons currently overstate forecast error — most visibly in SA, which has the highest PVNSG penetration. The `OPERATIONAL` measure (point 3 above) is the only one of the three that's currently a clean test; PV error for NSW Jul–Aug 2026 ran **~9–17%**, which is overstated by the missing PVNSG actuals, not necessarily a real forecast error.

### 6. The remaining operational/underlying gap looks explainable by PVNSG + BtM storage — but AEMO's BtM BESS assumptions look questionable

After accounting for points 2–5, the residual delta between operational and underlying demand should be largely explained by PVNSG (point 5) and BtM storage behaviour — though there may be an additional effect where BtM storage's *actual* dispatch profile differs from what AEMO assumes.

One data point worth flagging: AEMO's NSW ISP Step Change BtM storage (ESS) trace implies roughly 1,400 MW of installed 2.5-hour BESS, but across reference years for Jul–Aug 2026 it peaks at only **~300–450 MW** of charge/discharge (see `Comparison_ESS_EV_JulAug2026/ESS/daily_statistics_by_reference_year.csv`). That's a low utilisation rate for winter peak months and is worth sanity-checking against AEMO's assumed dispatch logic — it may be a real behavioural constraint (e.g. tariff/export limits) or it may indicate AEMO's profile assumptions underutilise the fleet relative to its capacity.

### 7. EV load is a minor factor at this stage

BtM EV charging load was checked over the same NSW Jul–Aug 2026 window and is small relative to the BESS and PVNSG effects above. Not a priority for further work right now.

## Bottom line

Our original comparison point was wrong (`TOTALDEMAND` against `OPSO_MODELLING`-based model inputs is not a like-for-like comparison), and our backcast inputs are also wrong as currently configured (VPP object double-counts behaviour already in the actuals). Once those are fixed, the gap between modelled and actual demand closes substantially. What's left — mostly PVNSG and BtM BESS profile differences — is smaller, better understood, and needs targeted follow-up rather than a wholesale rethink of the demand representation.

## Recommended next steps

1. **Fix the backcast inputs**: turn off the BtM VPP object in the backcast (or supply a VPP-consistent demand trace), and switch the actuals comparator from `TOTALDEMAND` to sent-out operational demand. Re-run the backcast and confirm the price/dispatch gap narrows as expected.
2. **Validate AEMO's BtM BESS dispatch assumptions**: investigate why the ~1,400 MW installed NSW BtM BESS fleet only peaks at ~300–450 MW charge/discharge in AEMO's winter traces — check against AEMO's IDP/model instructions for the assumed dispatch logic, and consider whether our own BESS representation should deviate from AEMO's trace if it's understating winter peak contribution.
3. **Scope a PVNSG estimate**: look for any usable proxy for real-world PVNSG output (even approximate) so the underlying-demand comparison can be made valid rather than structurally overstating error, particularly for SA.
4. **Fold in the weather reference-year work**: bring in the separate analysis on whether demand traces need adjusting for weather differences across reference years, to turn this into a combined view of "how should we represent demand uncertainty" rather than two separate investigations.
5. **Decide on EV**: given it's a minor factor, agree whether it warrants any further work now or can be deprioritised.

## Open questions for the team

- Do we subtract real-world VPP behaviour from actuals, or add VPP behaviour into the model-basis trace, as the longer-term fix (point 4 above is the short-term workaround)?
- Is there an appetite to deviate from AEMO's BtM BESS dispatch profile in our own model if we conclude it understates winter discharge, or do we treat AEMO's assumption as the reference case regardless?
- What's the priority order between the BESS validation work and folding in the weather-year analysis?
