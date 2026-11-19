"""
Library: compare AEMO forecast demand traces (by reference year) against actual
realised demand, across every NEM region plus the NEM as a whole.

Not run directly. Use 04_compare_to_actuals.py, which sets the config below
(DATASET, POE, ACTUAL_START, ...) and writes to outputs/<DATASET>/vs_actuals/.

Inputs
------
1. demand_traces.parquet  - built by 01_build_parquet.py
       datetime, demand, dataset, source, scenario, region, subregion,
       reference_year, poe, trace_type, source_file
       Half-hourly, period-ending (interval 1 = 00:30, interval 48 = 00:00 next day).

2. Actual operational demand - pulled from NemPoint via helper_functions.get_operational_demand
       Half-hourly, period-ending MMS.DEMANDOPERATIONALACTUAL OPERATIONAL_DEMAND.
       OPERATIONAL_DEMAND is as-generated (includes power-station auxiliary
       load and each region's allocated share of interconnector losses) and
       excludes WDR add-back and RERT/load-shedding adjustments, while the
       ESOO OPSO_MODELLING trace is sent-out. With ACTUAL_BASIS = "SENT_OUT"
       (the default), actual_mw is converted onto the same sent-out basis as
       the trace:

           actual_mw = OPERATIONAL_DEMAND + WDR_ESTIMATE
                       + OPERATIONAL_DEMAND_ADJUSTMENT
                       - auxiliary_load_mw - interconnector_losses_mw

       Auxiliary load is estimated from MMS.DISPATCH_UNIT_SCADA generation by
       unit, scaled by the AEMO IASR auxiliary rate for that unit or station
       (AUX_RATES_FILE), falling back to a fuel-level rate. Interconnector losses are sourced from
       MMS.DISPATCHINTERCONNECTORRES and allocated to regions using
       FROMREGIONLOSSSHARE from MMS.INTERCONNECTORCONSTRAINT. Set
       ACTUAL_BASIS = "AS_GENERATED" to restore the raw OPERATIONAL_DEMAND
       comparison. See build_actual_basis_components for details and
       actual_basis_components_monthly.csv for the audited monthly components.

Alignment
---------
Forecast traces and actuals are matched on absolute calendar timestamps, so a
forecast half-hour in July 2025 is compared to the actual half-hour of the same
date and time. Every reference year supplies its own trace for that same
timestamp, so the comparison isolates weather-year variation.

Only year-months present in BOTH datasets are compared, and only where the
actual data covers the month completely, so partial months do not distort
energy totals. Incomplete months are reported and excluded.

NEM totals are formed by summing regions at each half-hour, on both sides.
A reference year is only included in the NEM total if it is present for every
region, so the sum is never built from a partial set of regions.

Outputs (per region, under OUTPUT_DIR/<region>/)
------------------------------------------------
- metrics CSV   : one row per reference year over the common period
- monthly CSV   : monthly energy / peak / average / RMSE / MAE by reference year
- best-month CSV: the lowest raw-RMSE reference year for each month
- sample CSV    : raw half-hourly rows for manual alignment checking
- charts        : monthly energy, monthly peak, monthly energy error,
                  average daily profile per month, normalised daily profile
                  per month, best reference year by month, duration curve

Plus a combined all-region metrics, monthly and best-by-month CSV at the top level.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from demand_lib import nempoint as hf
from demand_lib.nempoint import get_operational_demand
from demand_lib.paths import PARQUET_FILE, REFERENCE_DIR, CACHE_DIR

# =============================================================================
# CONFIG
# =============================================================================
# These are defaults. The numbered scripts override them (DATASET, POE,
# TRACE_TYPE, ACTUAL_START, ...) before calling in, so edit the script's CONFIG
# block rather than this one.

# Mapping from trace region code to NEM REGIONID.
REGION_TO_REGIONID = {
    "NSW": "NSW1",
    "QLD": "QLD1",
    "SA": "SA1",
    "TAS": "TAS1",
    "VIC": "VIC1",
}

NEM_LABEL = "NEM"

# Regions to run. "NEM" is the sum of all entries in REGION_TO_REGIONID.
REGIONS = list(REGION_TO_REGIONID) + [NEM_LABEL]

# Actual demand window, as period-ending half-hour labels, both inclusive.
# ACTUAL_START is a lower bound: the window never starts before the first
# forecast half-hour, since earlier actuals can't be compared.
# ACTUAL_END = None runs through to the last complete month (or yesterday if
# REQUIRE_COMPLETE_MONTHS is False).
ACTUAL_START = pd.Timestamp("2025-01-01 00:30:00")
ACTUAL_END = None

# Only compare months where the actual data is complete. Set False to include
# partial months (energy totals for those months will not be comparable).
REQUIRE_COMPLETE_MONTHS = True

# ---------------------------------------------------------------------------
# Actual demand basis
# ---------------------------------------------------------------------------
# "SENT_OUT": actual_mw = OPERATIONAL_DEMAND + WDR_ESTIMATE +
#   OPERATIONAL_DEMAND_ADJUSTMENT - auxiliary_load_mw - interconnector_losses_mw,
#   matching the sent-out, loss-excluded basis of the OPSO_MODELLING trace.
# "AS_GENERATED": actual_mw = raw OPERATIONAL_DEMAND (previous behaviour).
ACTUAL_BASIS = "SENT_OUT"
ADJUST_INTERCONNECTOR_LOSSES = True
ADD_WDR_AND_ADJUSTMENT = True

# AEMO IASR auxiliary load rates, columns "IASR ID", "Power Station",
# "Auxiliary load (% of generation)". Each DUID's rate is resolved as:
#   1. IASR ID equal to the DUID,
#   2. else IASR Power Station equal to the NEO.PLANTS station name
#      (normalised; only stations with a single rate across their units),
#   3. else the fuel default in AUX_RATE_BY_FUEL.
# IASR IDs are AEMO's own unit IDs, not MMS GENSETIDs, so DUALLOC cannot be
# used to map them. None disables the file and uses fuel defaults only.
AUX_RATES_FILE = REFERENCE_DIR / "IASR_aux.csv"

# Fuel-level fallback auxiliary rate (fraction of unit output), keyed on
# NEO.PLANTS FUEL, set from the IASR technology rates. Fuels not listed print
# a warning and use a rate of 0.
AUX_RATE_BY_FUEL = {
    "Black Coal": 0.0667,  # IASR QLD rate; NSW units are 0.0548
    "Brown Coal": 0.0837,
    "Gas": 0.0073,  # OCGT; CCGTs (0.0179) resolve via unit or station match
    "Natural Gas (Pipeline)": 0.0073,
    "Diesel": 0.01,
    "Diesel oil": 0.01,
    "Hydro": 0.0064,
    "Pump": 0.0052,
    "Wind": 0.00073,
    "Solar": 0.00014,
    "Battery": 0.0012,
    "Biofuel": 0.073,
    "Other Biofuels": 0.073,
    "Biomass and industrial materials": 0.073,
    "Bagasse": 0.073,
    "Landfill biogas methane": 0.01,
    "Coal mine waste gas": 0.01,
    "Coal seam methane": 0.01,
    "Ethane": 0.01,
    "Other": 0.01,
}

UNIT_SCADA_CACHE_DIR = CACHE_DIR / "unit_scada_hh"
INTERCONNECTOR_LOSSES_CACHE_DIR = CACHE_DIR / "interconnector_losses_hh"

COMPONENTS_AUDIT_CSV = "actual_basis_components_monthly.csv"
# Folder for the audit CSV above. Set by the calling script; None skips it.
AUDIT_DIR = None

# Trace filters
POE = 50
TRACE_TYPE = "OPSO_MODELLING"
DATASET = "ISP_STEP_CHANGE_2026"  # e.g. "ISP_STEP_CHANGE_2026", or None for all datasets in the file

# Label used in chart titles and axis labels. Defaults to TRACE_TYPE; scripts
# that reuse this module for other measures (e.g. rooftop PV, underlying
# demand) should set this before calling run_all / label().
SERIES_LABEL = TRACE_TYPE

# Restrict to specific reference years, or None for all available.
REFERENCE_YEARS = None

# ---------------------------------------------------------------------------
# Alignment sample
# ---------------------------------------------------------------------------
# A wide half-hourly extract (actual alongside every reference year) written
# for manual checking. Days are taken from the start of the first common month
# and the start of the last common month.
SAMPLE_DAYS = 2
SAMPLE_PRINT_ROWS = 12

INTERVAL_HOURS = 0.5
INTERVALS_PER_DAY = 48


def resolve_actual_start(*forecasts):
    """Return the later of ACTUAL_START and the first forecast half-hour."""
    first_forecast = min(f["datetime"].min() for f in forecasts)
    return max(ACTUAL_START, first_forecast)


def resolve_actual_end():
    """Return the last period-ending half-hour of the last complete month (or day)."""
    if ACTUAL_END is not None:
        return ACTUAL_END
    if REQUIRE_COMPLETE_MONTHS:
        # 00:00 on the 1st is the last period-ending interval of the previous
        # month; the current partial month would be discarded anyway.
        return pd.Timestamp.now().normalize().replace(day=1)
    yesterday = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)
    # Period-ending: the day ends at 00:00 the following morning.
    return yesterday + pd.Timedelta(days=1)


# =============================================================================
# LOAD FORECAST TRACES
# =============================================================================


def _read_forecast_raw(trace_types):
    """Read the parquet file once for one or more trace_type values.

    Returns raw rows (not yet summed to regional totals) with a trace_type
    column, filtered to POE/DATASET/REFERENCE_YEARS/REGION_TO_REGIONID.
    """
    filters = [
        ("poe", "=", POE),
        ("trace_type", "in", list(trace_types)),
    ]
    if DATASET is not None:
        filters.append(("dataset", "=", DATASET))

    df = pd.read_parquet(
        PARQUET_FILE,
        columns=["datetime", "demand", "region", "subregion", "reference_year", "trace_type"],
        filters=filters,
    )
    if df.empty:
        raise ValueError(
            f"No forecast rows matched poe={POE} trace_type in {list(trace_types)} "
            f"dataset={DATASET}."
        )

    df["datetime"] = pd.to_datetime(df["datetime"])

    if REFERENCE_YEARS is not None:
        df = df[df["reference_year"].isin(REFERENCE_YEARS)]
        if df.empty:
            raise ValueError(f"No forecast rows for reference years {REFERENCE_YEARS}.")

    return df[df["region"].isin(REGION_TO_REGIONID)]


def _summarise_forecast(df, trace_type):
    """Sum a raw forecast frame to region/reference_year/datetime and add NEM."""
    regional = (
        df.groupby(["region", "reference_year", "datetime"], as_index=False)["demand"]
        .sum()
        .rename(columns={"demand": "forecast_mw"})
    )

    print(f"  Regional trace coverage ({trace_type}):")
    for region, group in regional.groupby("region"):
        print(
            f"    {region}: {group['reference_year'].nunique()} reference years, "
            f"{len(group):,} rows, "
            f"{group['datetime'].min():%Y-%m-%d} to {group['datetime'].max():%Y-%m-%d}"
        )

    if NEM_LABEL in REGIONS:
        regional = pd.concat([regional, build_nem_forecast(regional)], ignore_index=True)

    return regional


def load_forecast_all(trace_type=None):
    """Return half-hourly forecast demand by region and reference year.

    Subregions are summed to a regional total. The NEM total is appended as an
    additional region, formed only from reference years available in every
    region so the sum is never built from a partial set.

    trace_type defaults to the current module-level TRACE_TYPE, read at call
    time (not at import time), so callers that reassign cta.TRACE_TYPE before
    calling this with no argument get the updated value.
    """
    if trace_type is None:
        trace_type = TRACE_TYPE

    df = _read_forecast_raw([trace_type])
    df = df[df["trace_type"] == trace_type]
    return _summarise_forecast(df, trace_type)


def load_forecast_multi(trace_types):
    """Return {trace_type: regional forecast frame}, reading the parquet once.

    Equivalent to calling load_forecast_all(t) for each t in trace_types, but
    avoids one parquet scan per trace type.
    """
    raw = _read_forecast_raw(trace_types)
    return {
        trace_type: _summarise_forecast(raw[raw["trace_type"] == trace_type], trace_type)
        for trace_type in trace_types
    }


def build_nem_forecast(regional):
    """Sum regions to a NEM total, using only fully covered reference years."""
    region_count = regional["region"].nunique()

    # Keep only (reference_year, datetime) pairs present in every region.
    counts = regional.groupby(["reference_year", "datetime"])["region"].transform("size")
    complete = regional[counts == region_count]

    dropped_years = set(regional["reference_year"]) - set(complete["reference_year"])
    if dropped_years:
        print(
            f"    {NEM_LABEL}: excluding reference years not present in all "
            f"{region_count} regions: {sorted(dropped_years)}"
        )

    nem = (
        complete.groupby(["reference_year", "datetime"], as_index=False)["forecast_mw"]
        .sum()
    )
    nem["region"] = NEM_LABEL

    print(
        f"    {NEM_LABEL}: {nem['reference_year'].nunique()} reference years, "
        f"{len(nem):,} rows"
    )
    return nem


# =============================================================================
# LOAD ACTUAL DEMAND
# =============================================================================


def _months_covering(start, end):
    """Return the calendar-month Periods whose period-ending data lies in [start, end].

    Timestamps are period-ending, so a timestamp T belongs to the month
    containing (T - 1 minute).
    """
    first = (pd.Timestamp(start) - pd.Timedelta(minutes=1)).to_period("M")
    last = (pd.Timestamp(end) - pd.Timedelta(minutes=1)).to_period("M")
    return pd.period_range(first, last, freq="M")


def _fetch_monthly_cached(cache_dir, start, end, fetch_month_fn, process_fn):
    """Fetch monthly data with Parquet caching for complete past months.

    fetch_month_fn(month_start, month_end) pulls raw rows for one calendar
    month (period-ending, month_start exclusive / month_end inclusive).
    process_fn(raw) reduces that to the half-hourly table that gets cached.
    The current, still-incomplete month is always fetched fresh, never cached.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    now = pd.Timestamp.now()

    frames = []
    for period in _months_covering(start, end):
        month_start = period.start_time
        month_end = (period + 1).start_time
        is_complete = month_end <= now
        cache_path = cache_dir / f"{period}.parquet"

        if is_complete and cache_path.exists():
            frames.append(pd.read_parquet(cache_path))
            continue

        print(f"    Fetching {period} from NemPoint ({cache_dir.name})...")
        processed = process_fn(fetch_month_fn(month_start, month_end))
        if is_complete:
            processed.to_parquet(cache_path, index=False)
        frames.append(processed)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Auxiliary load
# ---------------------------------------------------------------------------


def get_unit_scada_hh(start, end):
    """Return half-hourly mean unit SCADA output by DUID/region/fuel, cached monthly."""

    def process(raw):
        # Sum / 6 rather than mean: the query keeps only SCADAVALUE > 0, so a
        # mean would overstate output for units running part of the half-hour.
        hh = raw.groupby(
            [
                "DUID", "REGION", "FUEL",
                pd.Grouper(key="SETTLEMENTDATE", freq="30min", label="right", closed="right"),
            ],
            as_index=False,
        )["SCADAVALUE"].sum()
        hh["SCADAVALUE"] = hh["SCADAVALUE"] / 6
        return hh.rename(columns={"SETTLEMENTDATE": "datetime", "SCADAVALUE": "scada_mw"})

    return _fetch_monthly_cached(UNIT_SCADA_CACHE_DIR, start, end, hf.get_unit_scada, process)


def _normalise_station(name):
    name = str(name).lower().replace("power station", "")
    return "".join(ch for ch in name if ch.isalnum())


def _load_iasr_aux(path):
    """Return (rate by IASR ID, rate by normalised station) as fractions."""
    iasr = pd.read_csv(path, encoding="utf-8-sig")
    iasr = iasr.rename(
        columns={
            "IASR ID": "id",
            "Power Station": "station",
            "Auxiliary load (% of generation)": "rate",
        }
    )[["id", "station", "rate"]].dropna(subset=["rate"])
    iasr["rate"] = iasr["rate"] / 100

    by_id = iasr.drop_duplicates("id", keep="last").set_index("id")["rate"]

    iasr["station_key"] = iasr["station"].map(_normalise_station)
    station_rates = iasr.groupby("station_key")["rate"].agg(["min", "max", "first"])
    single_rate = station_rates["min"] == station_rates["max"]
    by_station = station_rates.loc[single_rate, "first"]

    return by_id, by_station


def _aux_rate_by_duid(scada_hh):
    """Return a Series of auxiliary rates indexed by DUID.

    Resolved per DUID from AUX_RATES_FILE by unit ID, then by station name,
    then from the AUX_RATE_BY_FUEL fallback. Prints the share of generation
    resolved at each step.
    """
    duid_fuel = scada_hh.drop_duplicates("DUID").set_index("DUID")["FUEL"]

    unmapped = sorted(set(duid_fuel) - set(AUX_RATE_BY_FUEL))
    if unmapped:
        print(f"  WARNING: no auxiliary rate mapped for fuels {unmapped}; using 0.0")

    rates = duid_fuel.map(lambda fuel: AUX_RATE_BY_FUEL.get(fuel, 0.0))
    source = pd.Series("fuel default", index=rates.index)

    if AUX_RATES_FILE:
        by_id, by_station = _load_iasr_aux(AUX_RATES_FILE)

        stations = hf.get_plant_stations()
        duid_station = (
            stations.drop_duplicates("INSTANCENAME", keep="last")
            .set_index("INSTANCENAME")["STATIONNAME"]
            .map(_normalise_station)
            .reindex(rates.index)
        )
        station_rate = duid_station.map(by_station).dropna()
        rates.update(station_rate)
        source[station_rate.index] = "IASR station"

        id_rate = by_id.reindex(rates.index).dropna()
        rates.update(id_rate)
        source[id_rate.index] = "IASR unit ID"

        energy = scada_hh.groupby("DUID")["scada_mw"].sum()
        summary = (
            pd.DataFrame({"fuel": duid_fuel, "source": source, "energy": energy})
            .pivot_table(index="fuel", columns="source", values="energy", aggfunc="sum", fill_value=0)
        )
        summary = summary.div(summary.sum(axis=1), axis=0) * 100
        print("  Auxiliary rate source, % of generation by fuel:")
        print(summary.round(1).to_string())

    return rates


def compute_auxiliary_load(scada_hh):
    """Return half-hourly auxiliary_load_mw by region, from unit SCADA and rates."""
    rates = _aux_rate_by_duid(scada_hh)
    result = scada_hh.copy()
    result["aux_mw"] = result["scada_mw"] * result["DUID"].map(rates)

    regionid_to_region = {v: k for k, v in REGION_TO_REGIONID.items()}
    result["region"] = result["REGION"].map(regionid_to_region)
    result = result.dropna(subset=["region"])

    return (
        result.groupby(["region", "datetime"], as_index=False)["aux_mw"]
        .sum()
        .rename(columns={"aux_mw": "auxiliary_load_mw"})
    )


# ---------------------------------------------------------------------------
# Interconnector losses
# ---------------------------------------------------------------------------


def get_interconnector_losses_hh(start, end):
    """Return half-hourly mean interconnector losses by interconnector, cached monthly."""

    def process(raw):
        hh = hf.aggregate_to_half_hour(
            raw, "MWLOSSES", ["INTERCONNECTORID"], timestamp_column="SETTLEMENTDATE"
        )
        return hh.rename(columns={"SETTLEMENTDATE": "datetime"})

    return _fetch_monthly_cached(
        INTERCONNECTOR_LOSSES_CACHE_DIR, start, end, hf.get_interconnector_losses, process
    )


def compute_interconnector_losses_by_region(losses_hh):
    """Return half-hourly interconnector_losses_mw allocated to each region.

    MWLOSSES for an interconnector is allocated FROMREGIONLOSSSHARE to
    REGIONFROM and the remainder to REGIONTO, using the FROMREGIONLOSSSHARE
    version effective at (i.e. most recently effective on or before) each
    half-hour.
    """
    meta = hf.get_interconnector_meta()
    shares = hf.get_interconnector_loss_shares()
    # Keep the latest version per (interconnector, effective date).
    shares = (
        shares.sort_values(["INTERCONNECTORID", "EFFECTIVEDATE", "VERSIONNO"])
        .drop_duplicates(["INTERCONNECTORID", "EFFECTIVEDATE"], keep="last")
    )

    losses = losses_hh.sort_values("datetime")
    shares = shares.sort_values("EFFECTIVEDATE")
    merged = pd.merge_asof(
        losses,
        shares,
        left_on="datetime",
        right_on="EFFECTIVEDATE",
        by="INTERCONNECTORID",
        direction="backward",
    )

    missing_share = merged["FROMREGIONLOSSSHARE"].isna()
    if missing_share.any():
        print(
            f"  WARNING: {int(missing_share.sum()):,} half-hours have no "
            "FROMREGIONLOSSSHARE version effective yet; dropping"
        )
        merged = merged[~missing_share]

    merged = merged.merge(meta, on="INTERCONNECTORID", how="left")

    regionid_to_region = {v: k for k, v in REGION_TO_REGIONID.items()}

    from_side = merged[["datetime", "REGIONFROM"]].copy()
    from_side["losses_mw"] = merged["MWLOSSES"] * merged["FROMREGIONLOSSSHARE"]
    from_side = from_side.rename(columns={"REGIONFROM": "REGIONID"})

    to_side = merged[["datetime", "REGIONTO"]].copy()
    to_side["losses_mw"] = merged["MWLOSSES"] * (1 - merged["FROMREGIONLOSSSHARE"])
    to_side = to_side.rename(columns={"REGIONTO": "REGIONID"})

    allocated = pd.concat([from_side, to_side], ignore_index=True)
    allocated["region"] = allocated["REGIONID"].map(regionid_to_region)

    unmapped_regions = sorted(
        set(allocated.loc[allocated["region"].isna(), "REGIONID"].dropna().unique())
    )
    if unmapped_regions:
        print(f"  Interconnector losses reference regions outside the NEM 5: {unmapped_regions} (dropped)")
    allocated = allocated.dropna(subset=["region"])

    return (
        allocated.groupby(["region", "datetime"], as_index=False)["losses_mw"]
        .sum()
        .rename(columns={"losses_mw": "interconnector_losses_mw"})
    )


# ---------------------------------------------------------------------------
# Combine into the sent-out actual and audit the components
# ---------------------------------------------------------------------------


def build_actual_basis_components(query_start, query_end):
    """Return operational demand plus the components needed to convert it to
    a sent-out basis: wdr_estimate_mw, operational_demand_adjustment_mw,
    auxiliary_load_mw, interconnector_losses_mw. One row per region/datetime.
    """
    raw = get_operational_demand(query_start, query_end)

    regionid_to_region = {v: k for k, v in REGION_TO_REGIONID.items()}
    raw = raw[raw["REGIONID"].isin(regionid_to_region)].copy()
    if raw.empty:
        raise ValueError("No actual demand returned for any NEM region.")
    raw["region"] = raw["REGIONID"].map(regionid_to_region)

    operational = raw.rename(columns={"INTERVAL_DATETIME": "datetime"})[
        [
            "region", "datetime", "OPERATIONAL_DEMAND", "WDR_ESTIMATE",
            "OPERATIONAL_DEMAND_ADJUSTMENT", "LASTCHANGED",
        ]
    ]
    operational = operational.dropna(subset=["OPERATIONAL_DEMAND"])
    operational[["WDR_ESTIMATE", "OPERATIONAL_DEMAND_ADJUSTMENT"]] = operational[
        ["WDR_ESTIMATE", "OPERATIONAL_DEMAND_ADJUSTMENT"]
    ].fillna(0)

    # Sort so the most recently revised row is kept for each (region, datetime).
    operational = operational.sort_values("LASTCHANGED")
    duplicate_mask = operational.duplicated(subset=["region", "datetime"], keep="last")
    duplicate_count = int(duplicate_mask.sum())
    if duplicate_count:
        print(f"  Dropping {duplicate_count:,} duplicate (region, datetime) actual rows")
        operational = operational[~duplicate_mask]
    operational = operational.drop(columns="LASTCHANGED")
    operational = operational.rename(
        columns={
            "OPERATIONAL_DEMAND": "operational_demand_mw",
            "WDR_ESTIMATE": "wdr_estimate_mw",
            "OPERATIONAL_DEMAND_ADJUSTMENT": "operational_demand_adjustment_mw",
        }
    )

    # query_end is exclusive (+1 minute); the monthly fetchers take the
    # inclusive period-ending end so they don't pull the following month.
    last_interval = query_end - pd.Timedelta(minutes=1)
    scada_hh = get_unit_scada_hh(query_start, last_interval)
    aux = compute_auxiliary_load(scada_hh)

    losses_hh = get_interconnector_losses_hh(query_start, last_interval)
    losses = compute_interconnector_losses_by_region(losses_hh)

    components = operational.merge(aux, on=["region", "datetime"], how="left")
    components = components.merge(losses, on=["region", "datetime"], how="left")

    missing_aux = int(components["auxiliary_load_mw"].isna().sum())
    missing_losses = int(components["interconnector_losses_mw"].isna().sum())
    if missing_aux:
        print(f"  WARNING: {missing_aux:,} region-half-hours missing auxiliary load; dropping")
    if missing_losses:
        print(f"  WARNING: {missing_losses:,} region-half-hours missing interconnector losses; dropping")
    components = components.dropna(subset=["auxiliary_load_mw", "interconnector_losses_mw"])

    return components.reset_index(drop=True)


def write_components_audit(components, output_dir):
    """Write monthly energy (GWh) by component per region, plus aux/loss shares."""
    stamp = components["datetime"] - pd.Timedelta(minutes=1)
    monthly = components.assign(period=stamp.dt.to_period("M")).groupby(
        ["region", "period"], as_index=False
    ).agg(
        operational_gwh=("operational_demand_mw", lambda s: s.sum() * INTERVAL_HOURS / 1000),
        wdr_gwh=("wdr_estimate_mw", lambda s: s.sum() * INTERVAL_HOURS / 1000),
        adjustment_gwh=("operational_demand_adjustment_mw", lambda s: s.sum() * INTERVAL_HOURS / 1000),
        auxiliary_gwh=("auxiliary_load_mw", lambda s: s.sum() * INTERVAL_HOURS / 1000),
        losses_gwh=("interconnector_losses_mw", lambda s: s.sum() * INTERVAL_HOURS / 1000),
    )
    monthly["final_actual_gwh"] = (
        monthly["operational_gwh"] + monthly["wdr_gwh"] + monthly["adjustment_gwh"]
        - monthly["auxiliary_gwh"] - monthly["losses_gwh"]
    )
    monthly["auxiliary_pct_of_operational"] = (
        monthly["auxiliary_gwh"] / monthly["operational_gwh"] * 100
    )
    monthly["losses_pct_of_operational"] = (
        monthly["losses_gwh"] / monthly["operational_gwh"] * 100
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / COMPONENTS_AUDIT_CSV
    monthly.to_csv(path, index=False)

    print(f"  Actual-basis components written to {path}")
    print(
        monthly.to_string(
            index=False,
            float_format=lambda v: f"{v:,.2f}",
        )
    )
    return monthly


def load_actual_all(actual_start, actual_end):
    """Return half-hourly actual operational demand by region, plus the NEM total."""
    # DEMANDOPERATIONALACTUAL is already half-hourly, period-ending, matching
    # the trace convention directly. The query end is exclusive, so add one
    # minute to include actual_end.
    query_start = actual_start
    query_end = actual_end + pd.Timedelta(minutes=1)

    components = build_actual_basis_components(query_start, query_end)
    if AUDIT_DIR is not None:
        write_components_audit(components, AUDIT_DIR)

    actual = components.copy()
    actual["actual_mw"] = actual["operational_demand_mw"]
    if ADD_WDR_AND_ADJUSTMENT:
        actual["actual_mw"] = (
            actual["actual_mw"] + actual["wdr_estimate_mw"] + actual["operational_demand_adjustment_mw"]
        )
    if ACTUAL_BASIS == "SENT_OUT":
        actual["actual_mw"] = actual["actual_mw"] - actual["auxiliary_load_mw"]
        if ADJUST_INTERCONNECTOR_LOSSES:
            actual["actual_mw"] = actual["actual_mw"] - actual["interconnector_losses_mw"]
    elif ACTUAL_BASIS != "AS_GENERATED":
        raise ValueError(f"Unknown ACTUAL_BASIS: {ACTUAL_BASIS!r}")

    actual = actual[["region", "datetime", "actual_mw"]]
    actual = actual[
        (actual["datetime"] >= actual_start) & (actual["datetime"] <= actual_end)
    ]

    if NEM_LABEL in REGIONS:
        actual = pd.concat([actual, build_nem_actual(actual)], ignore_index=True)

    return actual.reset_index(drop=True)


def build_nem_actual(actual):
    """Sum regional actuals to a NEM total, keeping only fully covered intervals."""
    region_count = actual["region"].nunique()
    counts = actual.groupby("datetime")["region"].transform("size")

    incomplete = int((counts != region_count).sum())
    if incomplete:
        print(
            f"  {NEM_LABEL}: dropping {incomplete:,} half-hours missing one or more regions"
        )

    nem = (
        actual[counts == region_count]
        .groupby("datetime", as_index=False)["actual_mw"]
        .sum()
    )
    nem["region"] = NEM_LABEL
    return nem


# =============================================================================
# ALIGNMENT
# =============================================================================


def add_period_keys(df):
    """Add the year-month and half-hour-of-day keys used for reporting."""
    result = df.copy()
    # Shift back one minute so 00:00 belongs to the preceding day, consistent
    # with the period-ending convention used in the traces.
    stamp = result["datetime"] - pd.Timedelta(minutes=1)
    result["period"] = stamp.dt.to_period("M")
    result["hh"] = stamp.dt.hour * 2 + stamp.dt.minute // 30
    return result


def complete_periods(actual):
    """Return the year-months for which actual data covers every interval."""
    counts = actual.groupby("period").size()
    expected = pd.Series(
        {period: period.days_in_month * INTERVALS_PER_DAY for period in counts.index}
    )
    complete = counts[counts == expected]
    incomplete = counts[counts != expected]
    return list(complete.index), incomplete, expected


def build_comparison(forecast, actual):
    """Join every reference year to actual demand on matching calendar periods."""
    forecast = add_period_keys(forecast)
    actual = add_period_keys(actual)

    forecast_periods = set(forecast["period"].unique())
    actual_periods = set(actual["period"].unique())
    overlap = sorted(forecast_periods & actual_periods)

    if not overlap:
        raise ValueError(
            "Forecast and actual data share no overlapping months. "
            f"Forecast covers {min(forecast_periods)} to {max(forecast_periods)}; "
            f"actual covers {min(actual_periods)} to {max(actual_periods)}."
        )

    usable, incomplete, expected = complete_periods(actual)

    if REQUIRE_COMPLETE_MONTHS:
        excluded = [p for p in overlap if p not in set(usable)]
        if excluded:
            print("    Excluding incomplete actual months:")
            for period in excluded:
                observed = incomplete.get(period, 0)
                print(
                    f"      {period}: {observed:,} of {expected.get(period, 0):,} intervals"
                )
        overlap = [p for p in overlap if p in set(usable)]
        if not overlap:
            raise ValueError(
                "No complete overlapping months. Set REQUIRE_COMPLETE_MONTHS = False "
                "to compare partial months."
            )

    overlap_set = set(overlap)
    forecast = forecast[forecast["period"].isin(overlap_set)]
    actual = actual[actual["period"].isin(overlap_set)]

    merged = forecast.merge(
        actual[["datetime", "actual_mw"]],
        on="datetime",
        how="inner",
        validate="many_to_one",
    )
    if merged.empty:
        raise ValueError("No matched half-hour observations after aligning periods.")

    merged["error_mw"] = merged["forecast_mw"] - merged["actual_mw"]
    return merged, overlap


# =============================================================================
# ALIGNMENT SAMPLE
# =============================================================================


def build_alignment_sample(merged, periods):
    """Return a wide half-hourly extract for manual checking.

    One column per reference year alongside the actual, with the raw timestamp,
    period and half-hour index visible so the period-ending convention can be
    verified by eye.
    """
    sample_periods = sorted({periods[0], periods[-1]})

    windows = []
    for period in sample_periods:
        period_data = merged[merged["period"] == period]
        first = period_data["datetime"].min()
        # First SAMPLE_DAYS days of the month, period-ending.
        end = first + pd.Timedelta(days=SAMPLE_DAYS) - pd.Timedelta(minutes=30)
        windows.append(
            period_data[
                (period_data["datetime"] >= first) & (period_data["datetime"] <= end)
            ]
        )

    window = pd.concat(windows, ignore_index=True)

    wide = window.pivot_table(
        index=["period", "datetime", "hh"],
        columns="reference_year",
        values="forecast_mw",
    )
    wide.columns = [f"refyear_{int(c)}_mw" for c in wide.columns]

    actuals = (
        window.drop_duplicates(subset="datetime")
        .set_index(["period", "datetime", "hh"])["actual_mw"]
    )

    sample = wide.join(actuals).reset_index()
    sample = sample.sort_values("datetime").reset_index(drop=True)

    # Put the actual first so it reads left to right against the reference years.
    columns = ["period", "datetime", "hh", "actual_mw"] + [
        c for c in sample.columns if c.startswith("refyear_")
    ]
    return sample[columns]


def print_alignment_sample(sample, region):
    """Print a trimmed view of the sample so alignment can be eyeballed."""
    refyear_columns = [c for c in sample.columns if c.startswith("refyear_")]
    # Show the actual and the first three reference years only, so the table fits.
    preview_columns = ["datetime", "hh", "actual_mw"] + refyear_columns[:3]
    preview = sample[preview_columns].head(SAMPLE_PRINT_ROWS)

    print(f"    Alignment sample ({region}), first {len(preview)} half-hours:")
    print(
        preview.to_string(
            index=False,
            float_format=lambda v: f"{v:,.1f}",
        )
    )
    print(
        f"    hh 0 = period ending 00:30, hh 47 = period ending 00:00 next day. "
        f"{len(refyear_columns)} reference years in the CSV."
    )


# =============================================================================
# METRICS
# =============================================================================


def actual_series(merged):
    """Return the deduplicated actual half-hourly series over the common period."""
    return merged.drop_duplicates(subset="datetime").sort_values("datetime")


def summarise_metrics(merged):
    """Return one row of key metrics per reference year, plus an actual row."""
    actuals = actual_series(merged)["actual_mw"]
    actual_energy = actuals.sum() * INTERVAL_HOURS / 1000
    actual_peak = actuals.max()

    rows = [
        {
            "reference_year": "ACTUAL",
            "energy_gwh": actual_energy,
            "peak_mw": actual_peak,
            "min_mw": actuals.min(),
            "average_mw": actuals.mean(),
            "load_factor": actuals.mean() / actual_peak,
            "energy_error_pct": np.nan,
            "peak_error_pct": np.nan,
            "mae_mw": np.nan,
            "rmse_mw": np.nan,
            "bias_mw": np.nan,
        }
    ]

    for ref_year, group in merged.groupby("reference_year"):
        energy = group["forecast_mw"].sum() * INTERVAL_HOURS / 1000
        peak = group["forecast_mw"].max()
        rows.append(
            {
                "reference_year": int(ref_year),
                "energy_gwh": energy,
                "peak_mw": peak,
                "min_mw": group["forecast_mw"].min(),
                "average_mw": group["forecast_mw"].mean(),
                "load_factor": group["forecast_mw"].mean() / peak,
                "energy_error_pct": (energy / actual_energy - 1) * 100,
                "peak_error_pct": (peak / actual_peak - 1) * 100,
                "mae_mw": group["error_mw"].abs().mean(),
                "rmse_mw": np.sqrt((group["error_mw"] ** 2).mean()),
                "bias_mw": group["error_mw"].mean(),
            }
        )

    return pd.DataFrame(rows)


def summarise_monthly(merged):
    """Return monthly energy, peak, average and raw half-hourly errors.

    rmse_mw and mae_mw are calculated from every matched half-hour in the
    month, not from the 48-point average daily profile.
    """
    forecast_monthly = (
        merged.groupby(["reference_year", "period"])
        .agg(
            energy_gwh=("forecast_mw", lambda s: s.sum() * INTERVAL_HOURS / 1000),
            peak_mw=("forecast_mw", "max"),
            average_mw=("forecast_mw", "mean"),
            rmse_mw=("error_mw", lambda s: np.sqrt(np.mean(np.square(s)))),
            mae_mw=("error_mw", lambda s: np.mean(np.abs(s))),
        )
        .reset_index()
    )

    actual_monthly = (
        actual_series(merged)
        .groupby("period")
        .agg(
            actual_energy_gwh=("actual_mw", lambda s: s.sum() * INTERVAL_HOURS / 1000),
            actual_peak_mw=("actual_mw", "max"),
            actual_average_mw=("actual_mw", "mean"),
        )
        .reset_index()
    )

    monthly = forecast_monthly.merge(actual_monthly, on="period", how="left")

    monthly["energy_error_pct"] = (
        monthly["energy_gwh"] / monthly["actual_energy_gwh"] - 1
    ) * 100
    monthly["peak_error_pct"] = (
        monthly["peak_mw"] / monthly["actual_peak_mw"] - 1
    ) * 100
    monthly["average_error_pct"] = (
        monthly["average_mw"] / monthly["actual_average_mw"] - 1
    ) * 100

    return monthly.sort_values(["reference_year", "period"]).reset_index(drop=True)


def monthly_profiles(merged):
    """Return the average half-hourly shape for each month and reference year."""
    forecast_shape = (
        merged.groupby(["reference_year", "period", "hh"], as_index=False)["forecast_mw"]
        .mean()
    )
    actual_shape = (
        actual_series(merged).groupby(["period", "hh"], as_index=False)["actual_mw"].mean()
    )
    return forecast_shape, actual_shape


def best_reference_year_by_month(monthly):
    """Return the reference year with the lowest raw RMSE in each month."""
    required_columns = {"period", "reference_year", "rmse_mw"}
    missing = required_columns - set(monthly.columns)
    if missing:
        raise ValueError(
            "Cannot determine monthly best reference years. "
            f"Missing columns: {sorted(missing)}"
        )

    valid = monthly.dropna(subset=["period", "reference_year", "rmse_mw"]).copy()
    if valid.empty:
        raise ValueError("No valid monthly RMSE values were available.")

    # Stable sorting makes the lowest reference year win an exact RMSE tie.
    valid = valid.sort_values(
        ["period", "rmse_mw", "reference_year"],
        kind="mergesort",
    )

    best = (
        valid.groupby("period", as_index=False)
        .first()[
            [
                "period",
                "reference_year",
                "rmse_mw",
                "mae_mw",
                "energy_error_pct",
                "peak_error_pct",
                "average_error_pct",
            ]
        ]
    )
    return best


# =============================================================================
# CHARTS
# =============================================================================


def label(region):
    return f"{region} POE{POE} {SERIES_LABEL}"


def period_labels(periods):
    return [str(p) for p in periods]


def tick_rotation(count):
    """Keep month labels horizontal when there are only a few months."""
    if count <= 4:
        return 0, "center"
    return 45, "right"


def plot_monthly_metric(monthly, periods, region, forecast_col, actual_col, title, ylabel, path):
    positions = {period: index for index, period in enumerate(periods)}
    fig_width = max(7, min(14, len(periods) * 0.9))

    fig, ax = plt.subplots(figsize=(fig_width, 5))

    for ref_year, group in monthly.groupby("reference_year"):
        group = group.sort_values("period")
        ax.plot(
            [positions[p] for p in group["period"]],
            group[forecast_col],
            linewidth=0.9,
            alpha=0.55,
            label=f"RefYear {int(ref_year)}",
        )

    actual = monthly.drop_duplicates(subset="period").sort_values("period")
    ax.plot(
        [positions[p] for p in actual["period"]],
        actual[actual_col],
        color="black",
        linewidth=2.4,
        marker="o",
        markersize=4,
        label="Actual",
    )

    rotation, alignment = tick_rotation(len(periods))
    ax.set_xticks(range(len(periods)))
    ax.set_xticklabels(period_labels(periods), rotation=rotation, ha=alignment)
    ax.set_ylabel(ylabel)
    ax.set_title(f"{title} - {label(region)}")
    ax.grid(alpha=0.25)
    ax.legend(ncol=3, fontsize=7)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_monthly_error(monthly, periods, region, path):
    """Spread of monthly energy error across reference years."""
    pivot = monthly.pivot(index="period", columns="reference_year", values="energy_error_pct")
    pivot = pivot.reindex(periods)

    fig_width = max(7, min(14, len(periods) * 0.9))
    fig, ax = plt.subplots(figsize=(fig_width, 5))

    data = [pivot.loc[period].dropna().values for period in pivot.index]

    # matplotlib renamed the boxplot label kwarg in 3.9; support both.
    try:
        ax.boxplot(data, tick_labels=period_labels(pivot.index), showfliers=False)
    except TypeError:
        ax.boxplot(data, labels=period_labels(pivot.index), showfliers=False)

    for ref_year in pivot.columns:
        ax.plot(
            range(1, len(pivot.index) + 1),
            pivot[ref_year].values,
            linewidth=0.7,
            alpha=0.35,
        )

    ax.axhline(0, color="black", linewidth=1.2)
    ax.set_ylabel("Energy error (%)")
    ax.set_title(f"Monthly energy error across reference years - {label(region)}")

    rotation, _ = tick_rotation(len(periods))
    ax.tick_params(axis="x", rotation=rotation)
    ax.grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_monthly_profiles(forecast_shape, actual_shape, periods, region, path):
    """Average daily demand profile per month, in MW."""
    columns = min(4, len(periods))
    rows = int(np.ceil(len(periods) / columns))

    fig, axes = plt.subplots(
        rows,
        columns,
        figsize=(5 * columns, 4 * rows),
        sharex=True,
        squeeze=False,
    )

    hours = np.arange(INTERVALS_PER_DAY) / 2 + 0.5

    for index, period in enumerate(periods):
        ax = axes[index // columns][index % columns]

        month_forecast = forecast_shape[forecast_shape["period"] == period]
        for position, (_, group) in enumerate(month_forecast.groupby("reference_year")):
            group = group.sort_values("hh")
            ax.plot(
                hours,
                group["forecast_mw"].values,
                linewidth=0.7,
                alpha=0.45,
                label="Reference years" if position == 0 else None,
            )

        month_actual = actual_shape[actual_shape["period"] == period].sort_values("hh")
        ax.plot(
            hours,
            month_actual["actual_mw"].values,
            color="black",
            linewidth=2.0,
            label="Actual",
        )

        ax.set_title(str(period), fontsize=10)
        ax.grid(alpha=0.25)
        ax.set_xticks([0, 6, 12, 18, 24])

    for index in range(len(periods), rows * columns):
        axes[index // columns][index % columns].axis("off")

    axes[0][0].legend(fontsize=8)

    fig.suptitle(f"Average daily demand profile - {label(region)}", fontsize=12)
    fig.supylabel("Demand (MW)")
    fig.supxlabel("Hour ending")
    fig.tight_layout()
    fig.savefig(path, dpi=150)

    plt.close(fig)


def plot_normalised_monthly_profiles(forecast_shape, actual_shape, periods, region, path):
    """Monthly average daily profiles normalised by their own monthly mean.

    Dividing each profile by its own mean removes the average volume
    difference, so what remains is the difference in intraday shape.
    """
    columns = min(4, len(periods))
    rows = int(np.ceil(len(periods) / columns))

    fig, axes = plt.subplots(
        rows,
        columns,
        figsize=(5 * columns, 4 * rows),
        sharex=True,
        sharey=True,
        squeeze=False,
    )

    hours = np.arange(INTERVALS_PER_DAY) / 2 + 0.5

    for index, period in enumerate(periods):
        ax = axes[index // columns][index % columns]

        month_forecast = forecast_shape[forecast_shape["period"] == period]
        plotted = 0
        for _, group in month_forecast.groupby("reference_year"):
            group = group.sort_values("hh")
            values = group["forecast_mw"].to_numpy()

            profile_mean = values.mean()
            if not np.isfinite(profile_mean) or profile_mean == 0:
                continue

            ax.plot(
                hours,
                values / profile_mean,
                linewidth=0.7,
                alpha=0.45,
                label="Reference years" if plotted == 0 else None,
            )
            plotted += 1

        month_actual = actual_shape[actual_shape["period"] == period].sort_values("hh")
        actual_values = month_actual["actual_mw"].to_numpy()
        actual_mean = actual_values.mean()

        if np.isfinite(actual_mean) and actual_mean != 0:
            ax.plot(
                hours,
                actual_values / actual_mean,
                color="black",
                linewidth=2.0,
                label="Actual",
            )

        ax.axhline(1.0, color="grey", linewidth=0.8, linestyle="--", alpha=0.6)
        ax.set_title(str(period), fontsize=10)
        ax.grid(alpha=0.25)
        ax.set_xticks([0, 6, 12, 18, 24])

    for index in range(len(periods), rows * columns):
        axes[index // columns][index % columns].axis("off")

    axes[0][0].legend(fontsize=8)

    fig.suptitle(f"Normalised average daily demand profile - {label(region)}", fontsize=12)
    fig.supylabel("Demand relative to monthly mean")
    fig.supxlabel("Hour ending")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print("Monthly normalised profiles")
    plt.close(fig)


def plot_best_reference_year_by_month(
    best_monthly,
    forecast_shape,
    actual_shape,
    periods,
    region,
    path,
):
    """Plot the lowest raw-RMSE reference year profile against actual, per month.

    The shaded band is the gap between the best available reference year and
    the actual, so the residual shape error is visible directly.
    """
    best_monthly = best_monthly.set_index("period")

    columns = min(4, len(periods))
    rows = int(np.ceil(len(periods) / columns))

    fig, axes = plt.subplots(
        rows,
        columns,
        figsize=(5 * columns, 4 * rows),
        sharex=True,
        squeeze=False,
    )

    hours = np.arange(INTERVALS_PER_DAY) / 2 + 0.5

    for index, period in enumerate(periods):
        ax = axes[index // columns][index % columns]

        best_year = int(best_monthly.loc[period, "reference_year"])
        best_rmse = best_monthly.loc[period, "rmse_mw"]

        best_profile = forecast_shape[
            (forecast_shape["period"] == period)
            & (forecast_shape["reference_year"] == best_year)
        ].sort_values("hh")

        month_actual = (
            actual_shape[actual_shape["period"] == period].sort_values("hh")
        )

        best_values = best_profile["forecast_mw"].to_numpy()
        actual_values = month_actual["actual_mw"].to_numpy()

        ax.fill_between(
            hours,
            actual_values,
            best_values,
            color="#1f77b4",
            alpha=0.18,
            linewidth=0,
            label="Difference",
        )

        ax.plot(
            hours,
            actual_values,
            color="black",
            linewidth=2.0,
            label="Actual",
        )

        ax.plot(
            hours,
            best_values,
            color="#1f77b4",
            linewidth=2.0,
            label=f"RefYear {best_year}",
        )

        ax.set_title(
            f"{period}  -  RefYear {best_year}  (RMSE {best_rmse:,.0f} MW)",
            fontsize=10,
        )
        ax.set_xticks([0, 6, 12, 18, 24])
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)

    for index in range(len(periods), rows * columns):
        axes[index // columns][index % columns].axis("off")

    fig.suptitle(
        f"Best reference year by raw monthly RMSE - {label(region)}",
        fontsize=12,
    )
    fig.supylabel("Demand (MW)")
    fig.supxlabel("Hour ending")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)

def plot_duration_curves(merged, region, path):
    fig, ax = plt.subplots(figsize=(11, 5))

    for ref_year, group in merged.groupby("reference_year"):
        values = np.sort(group["forecast_mw"].values)[::-1]
        ax.plot(
            np.linspace(0, 100, len(values)),
            values,
            linewidth=0.8,
            alpha=0.5,
            label=f"RefYear {int(ref_year)}",
        )

    actuals = np.sort(actual_series(merged)["actual_mw"].values)[::-1]
    ax.plot(
        np.linspace(0, 100, len(actuals)),
        actuals,
        color="black",
        linewidth=2.4,
        label="Actual",
    )

    ax.set_xlabel("Percentage of time (%)")
    ax.set_ylabel("Demand (MW)")
    ax.set_title(f"Demand duration curve - {label(region)}")
    ax.grid(alpha=0.25)
    ax.legend(ncol=3, fontsize=7)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# =============================================================================
# PER-REGION RUN
# =============================================================================


def run_region(region, forecast, actual, output_root):
    """Build all outputs for one region. Returns (metrics, monthly, best) or None."""
    print()
    print(f"[{region}]")

    region_forecast = forecast[forecast["region"] == region]
    region_actual = actual[actual["region"] == region]

    if region_forecast.empty:
        print("    No forecast traces - skipped")
        return None
    if region_actual.empty:
        print("    No actual demand - skipped")
        return None

    try:
        merged, periods = build_comparison(region_forecast, region_actual)
    except ValueError as error:
        print(f"    Skipped: {error}")
        return None

    print(f"    {len(periods)} common months: {periods[0]} to {periods[-1]}")
    print(f"    {len(merged):,} matched observations")

    output_dir = output_root / region
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{region}_POE{POE}_{periods[0]}_{periods[-1]}"

    metrics = summarise_metrics(merged)
    monthly = summarise_monthly(merged)
    best_monthly = best_reference_year_by_month(monthly)
    forecast_shape, actual_shape = monthly_profiles(merged)

    sample = build_alignment_sample(merged, periods)
    sample.to_csv(output_dir / f"{prefix}_alignment_sample.csv", index=False)
    print_alignment_sample(sample, region)

    metrics.to_csv(output_dir / f"{prefix}_metrics.csv", index=False)
    monthly.to_csv(output_dir / f"{prefix}_monthly.csv", index=False)
    best_monthly.to_csv(
        output_dir / f"{prefix}_best_reference_year_by_month.csv", index=False
    )

    plot_path = output_dir / f"{prefix}_monthly_energy.png"
    print(f"    Plotting to: {plot_path}")
    plot_monthly_metric(
        monthly, periods, region,
        "energy_gwh", "actual_energy_gwh",
        "Monthly energy", "Energy (GWh)",
        plot_path,
    )
    plot_monthly_metric(
        monthly, periods, region,
        "peak_mw", "actual_peak_mw",
        "Monthly peak demand", "Peak demand (MW)",
        output_dir / f"{prefix}_monthly_peak.png",
    )
    plot_monthly_error(
        monthly, periods, region,
        output_dir / f"{prefix}_monthly_energy_error.png",
    )
    plot_monthly_profiles(
        forecast_shape, actual_shape, periods, region,
        output_dir / f"{prefix}_monthly_profiles.png",
    )
    plot_normalised_monthly_profiles(
        forecast_shape, actual_shape, periods, region,
        output_dir / f"{prefix}_normalised_monthly_profiles.png",
    )
    plot_best_reference_year_by_month(
        best_monthly,
        forecast_shape,
        actual_shape,
        periods,
        region,
        output_dir / f"{prefix}_best_reference_year_by_month.png",
    )
    plot_duration_curves(
        merged, region,
        output_dir / f"{prefix}_duration_curve.png",
    )

    ranked = metrics[metrics["reference_year"] != "ACTUAL"].sort_values("rmse_mw")
    print("    Closest reference years by RMSE:")
    print(
        ranked.head(3)[
            ["reference_year", "rmse_mw", "energy_error_pct", "peak_error_pct"]
        ].to_string(index=False, float_format=lambda v: f"{v:,.2f}")
    )

    print("    Best reference year by raw monthly RMSE:")
    print(
        best_monthly[["period", "reference_year", "rmse_mw"]].to_string(
            index=False, float_format=lambda v: f"{v:,.2f}"
        )
    )

    metrics.insert(0, "region", region)
    monthly.insert(0, "region", region)
    best_monthly.insert(0, "region", region)

    return metrics, monthly, best_monthly


# =============================================================================
# MAIN
# =============================================================================


def run_all(forecast, actual, output_root):
    """Run every region's comparison and write the combined top-level CSVs.

    Returns (combined_metrics, combined_monthly, combined_best_monthly), or
    None if no region produced a comparison.
    """
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    all_metrics = []
    all_monthly = []
    all_best_monthly = []

    for region in REGIONS:
        result = run_region(region, forecast, actual, output_root)
        if result is None:
            continue
        metrics, monthly, best_monthly = result
        all_metrics.append(metrics)
        all_monthly.append(monthly)
        all_best_monthly.append(best_monthly)

    if not all_metrics:
        print()
        print("No regions produced a comparison.")
        return None

    combined_metrics = pd.concat(all_metrics, ignore_index=True)
    combined_monthly = pd.concat(all_monthly, ignore_index=True)
    combined_best_monthly = pd.concat(all_best_monthly, ignore_index=True)

    combined_metrics.to_csv(output_root / "all_regions_metrics.csv", index=False)
    combined_monthly.to_csv(output_root / "all_regions_monthly.csv", index=False)
    combined_best_monthly.to_csv(
        output_root / "all_regions_best_reference_year_by_month.csv", index=False
    )

    print()
    print("Best reference year by RMSE, per region:")
    best = (
        combined_metrics[combined_metrics["reference_year"] != "ACTUAL"]
        .sort_values("rmse_mw")
        .groupby("region", as_index=False)
        .first()
    )
    print(
        best[["region", "reference_year", "rmse_mw", "energy_error_pct", "peak_error_pct"]]
        .to_string(index=False, float_format=lambda v: f"{v:,.2f}")
    )

    print()
    print("Best reference year by raw monthly RMSE, per region and month:")
    print(
        combined_best_monthly[["region", "period", "reference_year", "rmse_mw"]]
        .to_string(index=False, float_format=lambda v: f"{v:,.2f}")
    )

    print()
    print(f"Outputs written to {output_root}")

    return combined_metrics, combined_monthly, combined_best_monthly
