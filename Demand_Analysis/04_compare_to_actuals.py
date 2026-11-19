"""
Step 4 (reference years compared to actuals): compare one dataset's forecast
traces against actual NEM data, by reference year, region and NEM.

Measures are operational demand, rooftop PV, and underlying demand
(operational demand + rooftop PV). Every measure goes through
demand_lib/actuals_comparison.py, so period alignment, complete-month
filtering, metrics and charts are identical across them.

Run: python 04_compare_to_actuals.py   (needs NEMPOINT_API_KEY set)

Measures
--------
OPERATIONAL : forecast OPSO_MODELLING trace vs actual demand from
              cta.load_actual_all, which by default converts
              MMS.DEMANDOPERATIONALACTUAL onto a sent-out basis (see the
              actuals_comparison.py module docstring).
ROOFTOP_PV  : forecast PV_TOT trace vs actual MMS.ROOFTOP_PV_ACTUAL.
UNDERLYING  : forecast OPSO_MODELLING + PV_TOT vs actual operational + PV.

PV actual is MEASUREMENT, filled from SATELLITE where missing.

Caveat: PV_TOT likely covers rooftop PV plus small non-scheduled PV
(PVNSG), while ROOFTOP_PV_ACTUAL is rooftop only. If so, forecast PV reads
systematically above actual PV, and some of the underlying error reflects
how PV is defined rather than forecast error.

Known cosmetic issue: the reused charts label the y-axis "Demand (MW)" even
for the ROOFTOP_PV measure. Left as-is.

Outputs
-------
outputs/<DATASET>/vs_actuals/{OPERATIONAL,ROOFTOP_PV,UNDERLYING}/<region>/...
plus top-level all_regions_*.csv per measure and, when all three measures run,
an all_regions_error_decomposition.csv at the top level, decomposing the
underlying energy error into its operational-demand and rooftop-PV parts.
"""

from pathlib import Path

import pandas as pd

from demand_lib import actuals_comparison as cta
from demand_lib.nempoint import get_rooftop_pv_actual
from demand_lib.paths import output_dir

OPERATIONAL = "OPERATIONAL"
ROOFTOP_PV = "ROOFTOP_PV"
UNDERLYING = "UNDERLYING"

# =============================================================================
# CONFIG
# =============================================================================

# Forecast to compare ("dataset" value from 01_build_parquet.py) and its POE.
DATASET = "ESOO_2026_Central"
POE = 50

# Which measures to run. The error decomposition needs all three.
MEASURES = [OPERATIONAL, ROOFTOP_PV, UNDERLYING]

# Restrict to specific reference years, or None for all available.
REFERENCE_YEARS = None

# Actual window (period-ending half-hours). ACTUAL_END = None runs to the last
# complete month.
ACTUAL_START = pd.Timestamp("2025-01-01 00:30:00")
ACTUAL_END = None

# "SENT_OUT" converts actuals to the sent-out basis of the trace; "AS_GENERATED"
# uses the raw MMS series. See the README for the definition.
ACTUAL_BASIS = "SENT_OUT"

OUTPUT_DIR = output_dir(DATASET, "vs_actuals")
PV_TYPE_PRIORITY = ["MEASUREMENT", "SATELLITE"]

# Push the settings above into the shared comparison library.
cta.DATASET = DATASET
cta.POE = POE
cta.REFERENCE_YEARS = REFERENCE_YEARS
cta.ACTUAL_START = ACTUAL_START
cta.ACTUAL_END = ACTUAL_END
cta.ACTUAL_BASIS = ACTUAL_BASIS
cta.AUDIT_DIR = OUTPUT_DIR


# =============================================================================
# LOAD ACTUAL ROOFTOP PV
# =============================================================================


def load_pv_actual(actual_start, actual_end):
    """Return half-hourly actual rooftop PV by region, plus the NEM total."""
    query_start = actual_start
    query_end = actual_end + pd.Timedelta(minutes=1)

    raw = get_rooftop_pv_actual(query_start, query_end)

    # MMS.ROOFTOP_PV_ACTUAL also carries sub-regional rows (e.g. QLDC, QLDN,
    # QLDS, TASN, TASS) in some periods. Keep only the region-level IDs to
    # avoid double counting.
    region_ids = set(cta.REGION_TO_REGIONID.values())
    raw = raw[raw["REGIONID"].isin(region_ids)].copy()
    if raw.empty:
        raise ValueError("No rooftop PV actual returned for any NEM region.")

    # Sort so, if the API ever returns a revised duplicate for the same
    # (REGIONID, INTERVAL_DATETIME, TYPE), the most recently changed row wins.
    raw = raw.sort_values("LASTCHANGED")
    pivot = raw.pivot_table(
        index=["REGIONID", "INTERVAL_DATETIME"],
        columns="TYPE",
        values="POWER",
        aggfunc="last",
    ).reset_index()

    for pv_type in PV_TYPE_PRIORITY:
        if pv_type not in pivot.columns:
            pivot[pv_type] = pd.NA

    pivot["actual_mw"] = pivot["MEASUREMENT"]
    filled_mask = pivot["actual_mw"].isna() & pivot["SATELLITE"].notna()
    pivot.loc[filled_mask, "actual_mw"] = pivot.loc[filled_mask, "SATELLITE"]

    regionid_to_region = {v: k for k, v in cta.REGION_TO_REGIONID.items()}
    pivot["region"] = pivot["REGIONID"].map(regionid_to_region)

    for region, group in pivot.groupby("region"):
        filled = int((group["MEASUREMENT"].isna() & group["SATELLITE"].notna()).sum())
        print(f"    {region}: {filled:,} half-hours filled from SATELLITE")

    actual = pivot.rename(columns={"INTERVAL_DATETIME": "datetime"})[
        ["region", "datetime", "actual_mw"]
    ].dropna(subset=["actual_mw"])

    actual = actual[
        (actual["datetime"] >= actual_start) & (actual["datetime"] <= actual_end)
    ]

    if cta.NEM_LABEL in cta.REGIONS:
        actual = pd.concat([actual, cta.build_nem_actual(actual)], ignore_index=True)

    return actual.reset_index(drop=True)


# =============================================================================
# COMBINE OPERATIONAL DEMAND + ROOFTOP PV
# =============================================================================


def combine(a, b, keys, value_col):
    """Inner-merge two frames on keys, summing value_col. Prints rows dropped."""
    merged = a.merge(b, on=keys, suffixes=("_a", "_b"), how="inner", validate="one_to_one")

    dropped_a = len(a) - len(merged)
    dropped_b = len(b) - len(merged)
    print(
        f"    Merge on {keys}: {len(merged):,} rows kept, "
        f"{dropped_a:,} rows dropped from first input, "
        f"{dropped_b:,} rows dropped from second input"
    )

    merged[value_col] = merged[f"{value_col}_a"] + merged[f"{value_col}_b"]
    return merged[keys + [value_col]]


# =============================================================================
# ERROR DECOMPOSITION
# =============================================================================


def error_decomposition(monthly_by_measure, output_root):
    """Decompose underlying energy error into operational and PV components.

    Writes all_regions_error_decomposition.csv under output_root and returns
    the decomposition frame.
    """
    keys = ["region", "reference_year", "period"]

    op = monthly_by_measure[OPERATIONAL][keys + ["energy_gwh", "actual_energy_gwh"]].rename(
        columns={
            "energy_gwh": "op_forecast_energy_gwh",
            "actual_energy_gwh": "op_actual_energy_gwh",
        }
    )
    pv = monthly_by_measure[ROOFTOP_PV][keys + ["energy_gwh", "actual_energy_gwh"]].rename(
        columns={
            "energy_gwh": "pv_forecast_energy_gwh",
            "actual_energy_gwh": "pv_actual_energy_gwh",
        }
    )
    underlying = monthly_by_measure[UNDERLYING][
        keys + ["energy_gwh", "actual_energy_gwh"]
    ].rename(
        columns={
            "energy_gwh": "underlying_forecast_energy_gwh",
            "actual_energy_gwh": "underlying_actual_energy_gwh",
        }
    )

    before = (len(op), len(pv), len(underlying))
    decomposition = op.merge(pv, on=keys, how="inner").merge(underlying, on=keys, how="inner")
    print(
        f"    Decomposition merge: {before[0]:,}/{before[1]:,}/{before[2]:,} "
        f"(op/pv/underlying) rows in, {len(decomposition):,} rows kept"
    )

    decomposition["op_energy_error_gwh"] = (
        decomposition["op_forecast_energy_gwh"] - decomposition["op_actual_energy_gwh"]
    )
    decomposition["pv_energy_error_gwh"] = (
        decomposition["pv_forecast_energy_gwh"] - decomposition["pv_actual_energy_gwh"]
    )
    decomposition["underlying_energy_error_gwh"] = (
        decomposition["underlying_forecast_energy_gwh"]
        - decomposition["underlying_actual_energy_gwh"]
    )

    decomposition["op_energy_error_pct"] = (
        decomposition["op_energy_error_gwh"] / decomposition["op_actual_energy_gwh"] * 100
    )
    decomposition["pv_energy_error_pct"] = (
        decomposition["pv_energy_error_gwh"] / decomposition["pv_actual_energy_gwh"] * 100
    )
    decomposition["underlying_energy_error_pct"] = (
        decomposition["underlying_energy_error_gwh"]
        / decomposition["underlying_actual_energy_gwh"]
        * 100
    )

    decomposition["pv_share_of_underlying_error"] = (
        decomposition["pv_energy_error_gwh"] / decomposition["underlying_energy_error_gwh"]
    )

    check = decomposition["underlying_energy_error_gwh"] - (
        decomposition["op_energy_error_gwh"] + decomposition["pv_energy_error_gwh"]
    )
    max_diff = check.abs().max()
    if max_diff > 1e-6:
        print(
            f"    WARNING: underlying error != op error + pv error for some rows "
            f"(max diff {max_diff:.6f} GWh). This can happen if the underlying "
            f"merge dropped intervals present in only one of operational/PV."
        )
    else:
        print(
            "    Decomposition check passed: underlying error == op error + pv error "
            "(within 1e-6 GWh)."
        )

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    out_path = output_root / "all_regions_error_decomposition.csv"
    decomposition.to_csv(out_path, index=False)
    print(f"    Written {out_path}")

    return decomposition


def summarise_measures(monthly_by_measure):
    """Print the mean energy error % across reference years, per region and measure."""
    print()
    print("Mean energy error % across reference years, by region and measure:")
    for measure in MEASURES:
        monthly = monthly_by_measure.get(measure)
        if monthly is None:
            continue
        summary = monthly.groupby("region")["energy_error_pct"].mean()
        print(f"  {measure}:")
        print(summary.to_string(float_format=lambda v: f"{v:,.2f}"))


# =============================================================================
# MAIN
# =============================================================================


def main():
    output_root = Path(OUTPUT_DIR)
    output_root.mkdir(parents=True, exist_ok=True)

    actual_end = cta.resolve_actual_end()

    print("Loading forecast traces (operational demand + rooftop PV)...")
    forecast_by_type = cta.load_forecast_multi(["OPSO_MODELLING", "PV_TOT"])
    forecast_op = forecast_by_type["OPSO_MODELLING"]
    forecast_pv = forecast_by_type["PV_TOT"]

    print("Combining forecast underlying demand...")
    forecast_underlying = combine(
        forecast_op, forecast_pv, ["region", "reference_year", "datetime"], "forecast_mw"
    )

    actual_start = cta.resolve_actual_start(forecast_op, forecast_pv)
    window = f"{actual_start:%Y-%m-%d %H:%M} to {actual_end:%Y-%m-%d %H:%M}"

    print(f"Loading actual operational demand {window}...")
    actual_op = cta.load_actual_all(actual_start, actual_end)

    print(f"Loading actual rooftop PV {window}...")
    actual_pv = load_pv_actual(actual_start, actual_end)

    print("Combining actual underlying demand...")
    actual_underlying = combine(actual_op, actual_pv, ["region", "datetime"], "actual_mw")

    nem_actual_underlying = actual_underlying[actual_underlying["region"] == cta.NEM_LABEL]
    nem_from_regions = (
        actual_underlying[actual_underlying["region"] != cta.NEM_LABEL]
        .groupby("datetime")["actual_mw"]
        .sum()
    )
    if not nem_actual_underlying.empty:
        nem_check = nem_actual_underlying.set_index("datetime")["actual_mw"] - nem_from_regions
        max_nem_diff = nem_check.abs().max()
        print(f"    NEM underlying actual vs sum of regions: max diff {max_nem_diff:.6f} MW")

    measures = {
        OPERATIONAL: (forecast_op, actual_op),
        ROOFTOP_PV: (forecast_pv, actual_pv),
        UNDERLYING: (forecast_underlying, actual_underlying),
    }

    monthly_by_measure = {}
    for measure in MEASURES:
        forecast, actual = measures[measure]
        print()
        print(f"=== {measure} ===")
        cta.SERIES_LABEL = measure
        result = cta.run_all(forecast, actual, output_root / measure)
        if result is None:
            print(f"    {measure}: no comparison produced")
            continue
        _, monthly, _ = result
        monthly_by_measure[measure] = monthly

    if set(monthly_by_measure) == {OPERATIONAL, ROOFTOP_PV, UNDERLYING}:
        print()
        print("Building error decomposition...")
        error_decomposition(monthly_by_measure, output_root)
    else:
        print()
        print("Skipping error decomposition: not all three measures produced output.")

    summarise_measures(monthly_by_measure)

    print()
    print(f"Outputs written to {output_root}")


if __name__ == "__main__":
    main()
