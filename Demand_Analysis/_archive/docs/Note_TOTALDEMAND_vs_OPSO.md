# Why TOTALDEMAND is the wrong demand input for the PLEXOS backcast

## Summary

The backcast model is set up for AEMO's `OPSO_MODELLING` trace. `TOTALDEMAND` measures something different, so using it gives the wrong demand for the model to meet. The size of the error depends on region and time of day.

For historical actuals, use operational demand from `MMS.DEMANDOPERATIONALACTUAL`, converted to a sent-out basis (details below).

## What each series is

**`OPSO_MODELLING`** is what the model expects. It is operational demand:
- **sent-out**, meaning it excludes power-station auxiliary load;
- **excluding inter-regional transmission losses**, which PLEXOS models itself;
- **net of rooftop PV and PVNSG**.

It covers demand met by scheduled, semi-scheduled and *significant non-scheduled* generation. That last group is non-scheduled wind/solar of 30 MW or more plus a few named units, and the model represents it as generators.

**`TOTALDEMAND`** (`DISPATCHREGIONSUM`) is the starting demand figure AEMO's dispatch engine (NEMDE) uses in each 5-minute dispatch run. It is not a clean measure of demand:
1. **It excludes demand met by significant non-scheduled generation.** The model still generates from those units, so their output is counted twice. The effect moves with wind and solar output.
2. **It is as-generated, not sent-out.** It includes auxiliary load, which the OPSO trace excludes, so it overstates demand in coal-heavy regions.
3. **It isn't a pure measurement.** In dispatch it is metered initial output plus a 5-minute demand-forecast offset and an aggregate dispatch error term. It is a dispatch target, not measured demand.

## How big the difference is (Jul–Aug 2026 energy)

| Region | TOTALDEMAND vs raw operational demand | TOTALDEMAND vs sent-out operational demand (OPSO basis) |
|---|---|---|
| NSW | −1.0% | **+3.1%** |
| QLD | −0.5% | **+5.9%** |
| VIC | −3.1% | **+3.3%** |
| SA | −0.5% | **+0.9%** |
| TAS | −3.5% | **−2.8%** |

The missing non-scheduled generation pushes `TOTALDEMAND` down, and the included auxiliary load pushes it up. The two partly cancel, so `TOTALDEMAND` can look close to operational demand in aggregate. But the net error varies by region, from −3% to +6%, and by half-hour, because the non-scheduled part follows wind and solar output. That will bias dispatch, prices and unserved energy in the backcast.

## What to use instead

Use actual operational demand, converted to the same basis as `OPSO_MODELLING`, half-hourly and period-ending:

```
demand = OPERATIONAL_DEMAND + WDR_ESTIMATE + OPERATIONAL_DEMAND_ADJUSTMENT   (MMS.DEMANDOPERATIONALACTUAL)
         - auxiliary load       (unit SCADA x AEMO IASR auxiliary rates)
         - allocated interconnector losses   (DISPATCHINTERCONNECTORRES.MWLOSSES x FROMREGIONLOSSSHARE)
```

- **Don't add rooftop PV or PVNSG back.** Operational demand is already net of both, the same as `OPSO_MODELLING`.
- **Keep large non-scheduled wind/solar in demand.** The model supplies it from its own generator traces.
- **Code:** `load_actual_all()` in `Demand_Analysis/compare_to_actuals.py` produces exactly this series (`ACTUAL_BASIS = "SENT_OUT"`). For Jul–Aug 2026, the auxiliary load removed is about 3.6–5.6% in NSW/QLD/VIC and under 1% in SA/TAS. Interconnector losses are about 0.4–0.6%.

Reference: AEMO, *Demand Terms in EMMS Data Model* (July 2025); AEMO, *2025 ESOO Input Data Package and Model Instructions*.
