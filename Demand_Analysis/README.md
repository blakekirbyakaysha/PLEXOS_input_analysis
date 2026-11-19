# Demand Analysis

Tools for working with AEMO ESOO and ISP half-hourly demand traces. There are two things you can do with them:

1. **Compare reference years to each other.** How much do outcomes vary with the weather year?
2. **Compare reference years to actuals.** Which reference year, if any, tracks what actually happened?

## Setup

- Python environment: the `bidenv` conda env (`C:\Users\<user>\.conda\envs\bidenv\python.exe`). Do not use the base conda or Windows Store `python`. The base env's pyarrow 19 can't read the parquet file and crashes, and the Store python has no pandas or matplotlib.
- Actual data comes from NemPoint. Set `NEMPOINT_API_KEY` in your environment before running step 4. `NEMPOINT_URL` is optional.
- Every script is configured by constants in the `CONFIG` block at the top of the file. There are no command-line arguments. Edit the block, then run `python <script>.py` from this folder.

## Workflow

```
data/raw/  (AEMO zips)
   │
   ▼  01_build_parquet.py
data/parquet/demand_traces.parquet      one table, every dataset
   │
   ├──► 02_reference_year_cuts.py ──► 03_reference_year_charts.py      reference years vs each other
   │
   └──► 04_compare_to_actuals.py                                        reference years vs actuals
```

| Step | Script | What it does | Writes to |
|---|---|---|---|
| 1 | `01_build_parquet.py` | Reads the trace files listed in `INPUT_SOURCES`, reshapes to long format, writes one Parquet file. Run again only when you add or change input data. | `data/parquet/` |
| 2 | `02_reference_year_cuts.py` | Summarises one `DATASET` into FY, monthly, daily-profile and seasonal-profile tables at subregion, region and NEM level. | `outputs/<DATASET>/reference_years/cuts/` |
| 3 | `03_reference_year_charts.py` | Charts the spread across reference years for every area: energy and peak by FY, profiles, rankings, monthly heatmaps, raw MW differences. | `outputs/<DATASET>/reference_years/charts/` |
| 4 | `04_compare_to_actuals.py` | Compares each reference year with actual NEM data, month by month, for operational demand, rooftop PV and underlying demand. Also decomposes the underlying error into its operational and PV parts. | `outputs/<DATASET>/vs_actuals/` |

`DATASET` is the same name in every script (set per input in `01_build_parquet.py`, for example `ISP_STEP_CHANGE_2026` or `ESOO_2026_Central`). **To run a different forecast, change `DATASET` in the script's CONFIG block.** Each dataset writes to its own folder, so results from one forecast never overwrite another's.

Steps 2 and 3 must use the same `DATASET`.

### Shared code (`demand_lib/`)

| Module | Contents |
|---|---|
| `paths.py` | Every folder location. Change a path here, not in the scripts. |
| `nempoint.py` | NemPoint query builders and data access. |
| `actuals_comparison.py` | Loads forecasts and actuals (including the sent-out conversion), aligns them, computes metrics and draws the comparison charts. Imported by step 4. It is not run directly. |

## Folders

| Folder | Contents |
|---|---|
| `data/raw/` | AEMO trace zips and folders (inputs). |
| `data/reference/` | `IASR_aux.csv`, the AEMO auxiliary load rates. |
| `data/parquet/` | `demand_traces.parquet`. |
| `data/cache/` | Monthly caches of unit SCADA and interconnector losses from NemPoint. Only completed months are cached. Safe to delete. |
| `outputs/<DATASET>/` | Everything the analysis scripts write. Safe to delete and regenerate. |
| `_archive/` | Old outputs, one-off scripts and notes kept for reference. Nothing in the workflow reads from here. |

## Data definitions

These matter: mixing definitions produced misleading conclusions in earlier comparisons.

### AEMO trace types (from the ESOO Input Data Package and Model Instructions)

- **`OPSO_MODELLING`**: operational demand, **sent-out**, **excluding inter-regional transmission losses**, after the impact of rooftop PV and PVNSG. This is the main forecast series.
- **`OPSO_MODELLING_PVLITE`**: operational demand before the impact of rooftop PV and PVNSG.
- **`PV_TOT`**: all embedded PV, meaning **rooftop PV plus PVNSG**. PVNSG is non-scheduled PV from 100 kW up to 30 MW.
- In the ESOO package, scenario label `CER_SENSITIVITY` is the ESOO Central / Step Change demand used in the Committed and Anticipated Investments reliability assessment.

### Actual operational demand

`MMS.DEMANDOPERATIONALACTUAL.OPERATIONAL_DEMAND` is **as-generated**: it includes power-station auxiliary load and each region's allocated share of interconnector losses. It does not add back Wholesale Demand Response.

Don't use `TOTALDEMAND` from the dispatch tables as the actual series. That is NEMDE's scheduled-demand figure, which also excludes large-scale non-scheduled wind and solar, so it isn't comparable with the forecast traces.

### Sent-out conversion (`demand_lib/actuals_comparison.py`)

With the default `ACTUAL_BASIS = "SENT_OUT"`, actuals are converted to the same basis as `OPSO_MODELLING`:

```
actual_mw = OPERATIONAL_DEMAND + WDR_ESTIMATE + OPERATIONAL_DEMAND_ADJUSTMENT
            - auxiliary_load_mw - interconnector_losses_mw
```

- **Auxiliary load**: unit output from `MMS.DISPATCH_UNIT_SCADA`, multiplied by the AEMO IASR auxiliary rate in `data/reference/IASR_aux.csv`. Each unit's rate is looked up in this order:
  1. The IASR ID matches the DUID. This covers all coal units.
  2. Otherwise the IASR power station name matches the NEO.PLANTS station name, ignoring case, punctuation and "power station". This covers most CCGTs and Snowy/Tasmanian hydro.
  3. Otherwise a fuel-level fallback set from IASR technology rates (`AUX_RATE_BY_FUEL`).

  IASR IDs are AEMO's own unit IDs, not MMS GENSETIDs, so the MMS `DUALLOC` table can't be used to map them. The run prints the share of generation resolved at each step.
- **Interconnector losses**: `MMS.DISPATCHINTERCONNECTORRES.MWLOSSES`, split between the two regions using AEMO's `FROMREGIONLOSSSHARE` from `MMS.INTERCONNECTORCONSTRAINT`. AEMO allocates all Basslink losses to VIC, so TAS shows zero losses.
- Set `ACTUAL_BASIS = "AS_GENERATED"` in `04_compare_to_actuals.py` to go back to the raw series. The monthly size of each component is written to `outputs/<DATASET>/vs_actuals/actual_basis_components_monthly.csv`.

Size for Jul–Aug 2026 using IASR rates, as a share of operational demand:

| Region | Auxiliary load | Interconnector losses |
|---|---|---|
| QLD | ~5.6% | ~0.5% |
| VIC | ~5.6% | ~0.6% |
| NSW | ~3.6% | ~0.4% |
| SA | ~0.7% | ~0.6% |
| TAS | ~0.7% | 0 |

### Rooftop PV and underlying demand

The forecast side uses `PV_TOT`, which includes PVNSG. The actual side uses `MMS.ROOFTOP_PV_ACTUAL`, which is **rooftop only**. PVNSG mostly has no SCADA, so it can't be measured from MMS.

As a result, the ROOFTOP_PV and UNDERLYING measures overstate forecast error, most of all in SA. Treat the OPERATIONAL measure as the clean test.

## Known issues

- ISP `PV_TOT` files named `..._Area1_RefYear_...` don't match the filename pattern in `01_build_parquet.py`. They are written to the Parquet file with null region and reference year.
- Charts reused for the ROOFTOP_PV measure are labelled "Demand (MW)".
- Only a few months currently overlap between the traces and actuals. Weather alone explains about ±1.5–2% of operational-demand error across reference years, so check the sample size before drawing conclusions.
- `data/raw/ISP_Step_Change_2026/parquet/` holds about 8.8 GB of per-file Parquet from an earlier conversion. Nothing in the workflow reads it, so it can probably be deleted. I left it alone because I don't know why it's there.
