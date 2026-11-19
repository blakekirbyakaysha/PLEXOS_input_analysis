"""
Step 2 (reference years compared to each other): summarise one dataset in
demand_traces.parquet into small tables that 03_reference_year_charts.py plots.

Reads the parquet one row group at a time so memory stays flat.

Writes four parquet files to outputs/<DATASET>/reference_years/cuts/:
    fy_summary        - FY energy, max/min/avg demand, load factor
    daily_profile     - average demand by interval (1-48)
    seasonal_profile  - average demand by season x interval
    monthly           - monthly energy, peak, average

Each table is produced at SUBREGION and REGION level. Region rows are the
half-hourly sum of their subregions. A NEM row is also added at REGION level
as the half-hourly sum of every region/subregion in the source.

Run: python 02_reference_year_cuts.py
"""

import pandas as pd
import pyarrow.parquet as pq

from demand_lib.paths import PARQUET_FILE, output_dir

# =============================================================================
# CONFIG
# =============================================================================

# The dataset to summarise (the "dataset" value set in 01_build_parquet.py).
DATASET = "ESOO_2026_Central"

SOURCE = PARQUET_FILE

# Each table is written as its own parquet file in this folder.
OUTPUT_DIR = output_dir(DATASET, "reference_years/cuts")

# Optional filters. Set to None for everything.
FILTER_POE = None               # e.g. [50]
FILTER_REFERENCE_YEARS = None   # e.g. [2011, 2012]
FILTER_FY = None                # e.g. (2030, 2040) inclusive

# Set False to skip the corresponding aggregate level.
INCLUDE_REGION_TOTALS = True
INCLUDE_NEM_TOTAL = True

# Columns read from the parquet. Nothing else is touched.
COLS = [
    "datetime", "demand", "dataset", "scenario", "trace_type",
    "region", "subregion", "reference_year", "poe",
]

# How each cut is identified.
CUT_KEYS = ["level", "area", "dataset", "scenario", "trace_type", "reference_year", "poe"]

SEASONS = {
    12: "Summer", 1: "Summer", 2: "Summer",
    3: "Autumn", 4: "Autumn", 5: "Autumn",
    6: "Winter", 7: "Winter", 8: "Winter",
    9: "Spring", 10: "Spring", 11: "Spring",
}

# =============================================================================
# DERIVED COLUMNS
# =============================================================================


def add_calendar(df):
    """
    Intervals are period-ENDING: interval 1 = 00:30, interval 48 = 00:00 the
    next day. So every calendar field is derived from the period START,
    otherwise the last interval of a day/month/FY lands in the wrong period.

    Australian FY is labelled by its ending year: Jul 2035 - Jun 2036 = FY2036.
    """
    start = df["datetime"] - pd.Timedelta(minutes=30)

    month = start.dt.month

    df["fy"] = start.dt.year + (month >= 7).astype("int16")
    df["month"] = month.astype("int8")
    df["season"] = month.map(SEASONS).astype("category")
    df["interval"] = (
        start.dt.hour * 2 + (start.dt.minute == 30).astype("int8") + 1
    ).astype("int8")

    return df


def apply_filters(df):

    if FILTER_POE is not None:
        df = df[df["poe"].isin(FILTER_POE)]

    if FILTER_REFERENCE_YEARS is not None:
        df = df[df["reference_year"].isin(FILTER_REFERENCE_YEARS)]

    if FILTER_FY is not None:
        lo, hi = FILTER_FY
        df = df[df["fy"].between(lo, hi)]

    return df


# =============================================================================
# PARTIAL AGGREGATES
# =============================================================================
#
# Each row group is summarised on its own, then the partials are combined at
# the end. Sum/count/max/min all combine cleanly; averages are recovered as
# sum / count, never as an average of averages.


def summarise_chunk(df):

    out = {}

    def agg(extra_keys):
        g = df.groupby(CUT_KEYS + extra_keys, observed=True)["demand"]
        return pd.DataFrame({
            "sum": g.sum(),
            "count": g.size(),
            "max": g.max(),
            "min": g.min(),
        }).reset_index()

    out["fy_summary"] = agg(["fy"])
    out["daily_profile"] = agg(["fy", "interval"])
    out["seasonal_profile"] = agg(["fy", "season", "interval"])
    out["monthly"] = agg(["fy", "month"])

    return out


def combine(partials, extra_keys):
    """Re-aggregate the partials and turn sums/counts into the final columns."""

    keys = CUT_KEYS + extra_keys

    df = pd.concat(partials, ignore_index=True)

    g = df.groupby(keys, observed=True)

    out = pd.DataFrame({
        "energy_gwh": g["sum"].sum() * 0.5 / 1000,
        "max_mw": g["max"].max(),
        "min_mw": g["min"].min(),
        "avg_mw": g["sum"].sum() / g["count"].sum(),
        "intervals": g["count"].sum(),
    }).reset_index()

    out["load_factor"] = out["avg_mw"] / out["max_mw"].replace(0, pd.NA)

    return out.sort_values(keys).reset_index(drop=True)


# =============================================================================
# PASS 1 - SUBREGION
# =============================================================================


def row_group_index(pf):
    """Map (region, scenario, trace_type, reference_year, poe) to row groups.

    Only row groups for DATASET (and the POE / reference-year filters) are
    kept, so the passes below never read the other datasets.
    """

    groups = {}

    for i in range(pf.metadata.num_row_groups):

        # read the key columns only, first row is enough to identify the group
        head = pf.read_row_group(
            i,
            columns=["dataset", "region", "scenario", "trace_type",
                     "reference_year", "poe"],
        ).slice(0, 1).to_pydict()

        if head["dataset"][0] != DATASET:
            continue
        if FILTER_POE is not None and head["poe"][0] not in FILTER_POE:
            continue
        if (FILTER_REFERENCE_YEARS is not None
                and head["reference_year"][0] not in FILTER_REFERENCE_YEARS):
            continue

        key = (
            head["region"][0],
            head["scenario"][0],
            head["trace_type"][0],
            head["reference_year"][0],
            head["poe"][0],
        )
        groups.setdefault(key, []).append(i)

    return groups


def pass_subregion(pf, groups):

    partials = {k: [] for k in
                ["fy_summary", "daily_profile", "seasonal_profile", "monthly"]}

    indices = sorted(i for idx in groups.values() for i in idx)
    n = len(indices)

    for count, i in enumerate(indices, start=1):

        df = pf.read_row_group(i, columns=COLS).to_pandas()

        df = add_calendar(df)
        df = apply_filters(df)

        if df.empty:
            continue

        df["level"] = "SUBREGION"
        df["area"] = df["subregion"]

        for name, part in summarise_chunk(df).items():
            partials[name].append(part)

        print(f"  subregion pass: row group {count}/{n}", end="\r", flush=True)

        del df

    print()
    return partials


# =============================================================================
# PASS 2 - REGION TOTALS
# =============================================================================
#
# A region's peak is NOT the sum of its subregion peaks, because subregions
# do not peak at the same half hour. The subregions have to be added together
# interval by interval first. That means loading the row groups belonging to
# one region/scenario/reference_year/poe combination at the same time - a
# handful of files, not the whole dataset.


def pass_region(pf, groups):

    partials = {k: [] for k in
                ["fy_summary", "daily_profile", "seasonal_profile", "monthly"]}

    for j, (key, indices) in enumerate(groups.items(), start=1):

        region, scenario, trace_type, reference_year, poe = key

        df = pd.concat(
            [pf.read_row_group(i, columns=COLS).to_pandas() for i in indices],
            ignore_index=True,
        )

        # add subregions together at each half hour
        df = (
            df.groupby("datetime", as_index=False)["demand"]
            .sum()
        )

        df["level"] = "REGION"
        df["area"] = region
        df["dataset"] = DATASET
        df["scenario"] = scenario
        df["trace_type"] = trace_type
        df["reference_year"] = reference_year
        df["poe"] = poe

        df = add_calendar(df)
        df = apply_filters(df)

        if not df.empty:
            for name, part in summarise_chunk(df).items():
                partials[name].append(part)

        print(f"  region pass: {j}/{len(groups)}", end="\r", flush=True)

        del df

    print()
    return partials


# =============================================================================
# PASS 3 - NEM TOTAL
# =============================================================================
#
# NEM is written as level REGION, area NEM so the visualisation script treats
# it exactly like any other region. Demand is summed half-hour by half-hour
# before peaks, profiles, energy and averages are calculated.
#
def pass_nem(pf, groups):
    """Create NEM totals by summing all source demand at each half hour."""

    partials = {k: [] for k in
                ["fy_summary", "daily_profile", "seasonal_profile", "monthly"]}

    # Merge the per-region groups into one group per scenario/trace/year/POE.
    nem_groups = {}
    for (region, scenario, trace_type, reference_year, poe), indices in groups.items():
        nem_groups.setdefault(
            (scenario, trace_type, reference_year, poe), []
        ).extend(indices)

    for j, (key, indices) in enumerate(nem_groups.items(), start=1):
        scenario, trace_type, reference_year, poe = key

        # Aggregate each row group to datetime first, then combine those small
        # partial totals. This avoids holding every raw subregion row for the
        # whole NEM case in memory at once.
        datetime_partials = []
        for i in indices:
            part = pf.read_row_group(
                i, columns=["datetime", "demand"]
            ).to_pandas()
            part = part.groupby("datetime", as_index=False)["demand"].sum()
            datetime_partials.append(part)

        df = pd.concat(datetime_partials, ignore_index=True)
        df = df.groupby("datetime", as_index=False)["demand"].sum()

        df["level"] = "REGION"
        df["area"] = "NEM"
        df["dataset"] = DATASET
        df["scenario"] = scenario
        df["trace_type"] = trace_type
        df["reference_year"] = reference_year
        df["poe"] = poe

        df = add_calendar(df)
        df = apply_filters(df)

        if not df.empty:
            for name, part in summarise_chunk(df).items():
                partials[name].append(part)

        print(f"  NEM pass: {j}/{len(nem_groups)}", end="\r", flush=True)
        del df, datetime_partials

    print()
    return partials


# =============================================================================
# MAIN
# =============================================================================


def main():

    pf = pq.ParquetFile(SOURCE)

    print(f"{pf.metadata.num_rows:,} rows, "
          f"{pf.metadata.num_row_groups} row groups")
    print()

    print(f"Dataset: {DATASET}")
    groups = row_group_index(pf)
    if not groups:
        raise ValueError(f"No row groups found for dataset {DATASET!r}.")
    print(f"{sum(len(v) for v in groups.values())} row groups selected")
    print()

    partials = pass_subregion(pf, groups)

    if INCLUDE_REGION_TOTALS:
        for name, parts in pass_region(pf, groups).items():
            partials[name].extend(parts)

    if INCLUDE_NEM_TOTAL:
        for name, parts in pass_nem(pf, groups).items():
            partials[name].extend(parts)

    extra = {
        "fy_summary": ["fy"],
        "daily_profile": ["fy", "interval"],
        "seasonal_profile": ["fy", "season", "interval"],
        "monthly": ["fy", "month"],
    }

    tables = {}
    for name, keys in extra.items():
        if partials[name]:
            tables[name] = combine(partials[name], keys)
            print(f"{name}: {len(tables[name]):,} rows")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print()
    for name, df in tables.items():
        target = OUTPUT_DIR / f"{name}.parquet"
        df.to_parquet(target, index=False, compression="snappy")
        print(f"wrote {target.name}  ({len(df):,} rows)")

    print(f"\nDone. Output in {OUTPUT_DIR}")

    return tables


if __name__ == "__main__":
    main()
