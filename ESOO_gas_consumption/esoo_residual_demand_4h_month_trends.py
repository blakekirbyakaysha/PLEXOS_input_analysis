"""
ESOO residual-demand 4-hour highest/lowest 4-hour spread analysis.

Inputs (stored beside this script):
    load.csv
    RE_gen.csv
    Objects_list.csv

Residual demand is calculated for each region, interval and result set as:
    Load_MW - Renewable_Generation_MW

The script fails on duplicate, unmapped or invalid data. Unaligned load/RE intervals are reported and excluded.
It does not clip negative residual demand.
"""

import os
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
LOAD_FILE = BASE / "load.csv"
RE_FILE = BASE / "RE_gen.csv"
OBJECTS_FILE = BASE / "Objects_list.csv"
OUTPUT_DIR = BASE / "residual_demand_outputs"

RESULT_SETS = ["1", "2", "3", "4", "5"]
CHUNK_SIZE = 1_000_000
REGIONS = ["NSW1", "QLD1", "SA1", "TAS1", "VIC1"]
REGION_TOKEN_MAP = {
    "NSW": "NSW1",
    "NSW1": "NSW1",
    "QLD": "QLD1",
    "QLD1": "QLD1",
    "VIC": "VIC1",
    "VIC1": "VIC1",
    "SA": "SA1",
    "SA1": "SA1",
    "TAS": "TAS1",
    "TAS1": "TAS1",
}

EXPLICIT_OBJECT_REGION_MAP = {
"PV NSW": "NSW1",
"PV QLD": "QLD1",
"PV SA": "SA1",
"PV TAS": "TAS1",
"PV VIC": "VIC1",
}


def require_file(path):
    if not path.is_file():
        raise FileNotFoundError(f"Required input file not found: {path}")


def require_columns(df, required, filename):
    missing = set(required).difference(df.columns)
    if missing:
        raise ValueError(f"{filename!r} is missing columns: {sorted(missing)}")


def financial_year_ending(values):
    return values.dt.year + (values.dt.month >= 7).astype(int)


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_")


def parse_region_from_category(category):
    """Extract exactly one NEM region token from an Objects_list category."""
    text = str(category).strip().upper()
    matches = []
    for token, region in REGION_TOKEN_MAP.items():
        if re.search(rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])", text):
            matches.append(region)
    matches = sorted(set(matches))
    if len(matches) == 1:
        return matches[0]
    return pd.NA


def load_object_region_map():
    objects = pd.read_csv(OBJECTS_FILE, usecols=["Class", "Name", "Category"])
    require_columns(objects, ["Class", "Name", "Category"], OBJECTS_FILE.name)
    objects["Name"] = objects["Name"].astype("string").str.strip()
    objects["Category"] = objects["Category"].astype("string").str.strip()

    if objects["Name"].isna().any() or (objects["Name"] == "").any():
        raise ValueError("Objects_list.csv contains blank object names.")

    objects["Region"] = objects["Category"].map(parse_region_from_category)

    duplicates = objects[objects.duplicated("Name", keep=False)].copy()
    if not duplicates.empty:
        conflicts = duplicates.groupby("Name")["Region"].nunique(dropna=False)
        conflict_names = conflicts[conflicts > 1].index.tolist()
        if conflict_names:
            detail = duplicates[duplicates["Name"].isin(conflict_names)]
            raise ValueError(
                "Objects_list.csv maps object names to conflicting regions:\n"
                + detail[["Class", "Name", "Category", "Region"]].to_string(index=False)
            )

    mapping = (
        objects.dropna(subset=["Region"])
        .drop_duplicates("Name")
        .set_index("Name")["Region"]
    )

    mapping = pd.concat([
        mapping,
        pd.Series(EXPLICIT_OBJECT_REGION_MAP, name="Region"),
    ])

    mapping = mapping[~mapping.index.duplicated(keep="first")]

    if mapping.empty:
        raise ValueError("No regional object mappings were found in Objects_list.csv.")
    return mapping, objects


def load_regional_load():
    load = pd.read_csv(LOAD_FILE)
    required = [
        "Parent Name", "Model", "Phase", "Collection", "Child Name",
        "Property", "Sample", "Datetime", "Value", "Units",
    ]
    require_columns(load, required, LOAD_FILE.name)

    load["Collection"] = load["Collection"].astype("string").str.strip()
    load["Property"] = load["Property"].astype("string").str.strip()
    load["Units"] = load["Units"].astype("string").str.strip()
    load["Region"] = load["Child Name"].astype("string").str.strip().str.upper()

    unexpected_collection = sorted(load.loc[load["Collection"] != "Region", "Collection"].dropna().unique())
    unexpected_property = sorted(load.loc[load["Property"] != "Load", "Property"].dropna().unique())
    unexpected_units = sorted(load.loc[load["Units"].str.upper() != "MW", "Units"].dropna().unique())
    unexpected_regions = sorted(set(load["Region"].dropna()) - set(REGIONS))
    if unexpected_collection:
        raise ValueError(f"Unexpected Collection values in load.csv: {unexpected_collection}")
    if unexpected_property:
        raise ValueError(f"Unexpected Property values in load.csv: {unexpected_property}")
    if unexpected_units:
        raise ValueError(f"Unexpected Units values in load.csv: {unexpected_units}")
    if unexpected_regions:
        raise ValueError(f"Unexpected regions in load.csv: {unexpected_regions}")

    load["Result_Set"] = (
        load["Sample"].astype("string").str.extract(r"(\d+)\s*$", expand=False)
    )
    bad_samples = load.loc[~load["Result_Set"].isin(RESULT_SETS), "Sample"].drop_duplicates().tolist()
    if bad_samples:
        raise ValueError(f"Could not map load Sample values to result sets 1-5: {bad_samples}")

    raw_datetime = load["Datetime"].copy()
    load["Datetime"] = pd.to_datetime(
        load["Datetime"].astype("string").str.strip(),
        format="%d/%m/%Y %I:%M:%S %p",
        errors="coerce",
    )
    if load["Datetime"].isna().any():
        bad_values = (
            raw_datetime.loc[load["Datetime"].isna()]
            .drop_duplicates()
            .head(50)
        )
        raise ValueError(
            "load.csv contains unparseable Datetime values. "
            "First 50 original values:\n"
            f"{bad_values.to_string(index=False)}"
        )
    load["Load_MW"] = pd.to_numeric(load["Value"], errors="coerce")
    if load["Load_MW"].isna().any():
        raise ValueError("load.csv contains missing or non-numeric Value entries.")

    keys = ["Result_Set", "Region", "Datetime"]
    duplicates = load.duplicated(keys, keep=False)
    if duplicates.any():
        raise ValueError(
            "Duplicate regional load intervals found:\n"
            + load.loc[duplicates, keys + ["Load_MW"]].head(100).to_string(index=False)
        )

    load = load[keys + ["Load_MW"]].sort_values(keys).reset_index(drop=True)

    timestamps = pd.Series(load["Datetime"].drop_duplicates().sort_values().values)
    differences = timestamps.diff().dropna()
    positive_differences = differences[differences > pd.Timedelta(0)]
    if positive_differences.empty:
        raise ValueError("Could not infer the interval length from load.csv.")
    interval = positive_differences.mode().iloc[0]
    off_grid = ((load["Datetime"] - load["Datetime"].dt.normalize()) % interval) != pd.Timedelta(0)
    if off_grid.any():
        raise ValueError("load.csv contains timestamps that are not aligned to the inferred interval length.")

    return load, interval


def aggregate_renewable_generation(object_region_map, interval):
    header = pd.read_csv(RE_FILE, nrows=0)
    required = ["Name", "Year", "Month", "Day", "Period", *RESULT_SETS]
    require_columns(header, required, RE_FILE.name)

    interval_minutes = interval / pd.Timedelta(minutes=1)
    if interval_minutes <= 0 or not float(interval_minutes).is_integer():
        raise ValueError(f"Unsupported inferred load interval: {interval}")
    periods_per_day = int(pd.Timedelta(days=1) / interval)

    aggregated_chunks = []
    unmapped_names = set()
    bad_period_rows = []

    dtypes = {"Name": "string", "Year": "int16", "Month": "int8", "Day": "int8", "Period": "int16"}
    dtypes.update({column: "float64" for column in RESULT_SETS})

    for chunk_number, chunk in enumerate(
        pd.read_csv(RE_FILE, usecols=required, dtype=dtypes, chunksize=CHUNK_SIZE),
        start=1,
    ):
        chunk["Name"] = chunk["Name"].str.strip()
        chunk["Region"] = chunk["Name"].map(object_region_map)
        missing = chunk["Region"].isna()
        if missing.any():
            unmapped_names.update(chunk.loc[missing, "Name"].dropna().unique().tolist())
            continue

        invalid_period = ~chunk["Period"].between(1, periods_per_day)
        if invalid_period.any():
            bad_period_rows.append(chunk.loc[invalid_period, ["Name", "Year", "Month", "Day", "Period"]].head(20))
            continue

        if chunk[RESULT_SETS].isna().any().any():
            bad = chunk.loc[chunk[RESULT_SETS].isna().any(axis=1), ["Name", "Year", "Month", "Day", "Period", *RESULT_SETS]].head(20)
            raise ValueError("RE_gen.csv contains missing result values:\n" + bad.to_string(index=False))

        dates = pd.to_datetime(chunk[["Year", "Month", "Day"]].rename(
            columns={"Year": "year", "Month": "month", "Day": "day"}
        ), errors="coerce")
        if dates.isna().any():
            bad = chunk.loc[dates.isna(), ["Name", "Year", "Month", "Day", "Period"]].head(20)
            raise ValueError("RE_gen.csv contains invalid dates:\n" + bad.to_string(index=False))

        # PLEXOS timestamps are period-ending: Period 1 is 01:00 and
        # Period 24 is 00:00 on the following day.
        chunk["Datetime"] = dates + chunk["Period"] * interval
        grouped = (
            chunk.groupby(["Region", "Datetime"], as_index=False, observed=True)[RESULT_SETS]
            .sum()
        )
        aggregated_chunks.append(grouped)
        print(f"Processed RE_gen.csv chunk {chunk_number:,}")

    if unmapped_names:
        names = sorted(unmapped_names)
        preview = names[:200]
        suffix = "" if len(names) <= 200 else f"\n... plus {len(names) - 200:,} more"
        raise ValueError(
            "Renewable objects could not be mapped to a region through Objects_list.csv:\n"
            + "\n".join(preview) + suffix
        )
    if bad_period_rows:
        detail = pd.concat(bad_period_rows, ignore_index=True).head(100)
        raise ValueError(
            f"RE_gen.csv contains Period values outside 1-{periods_per_day} for a {interval} interval:\n"
            + detail.to_string(index=False)
        )
    if not aggregated_chunks:
        raise ValueError("RE_gen.csv produced no renewable-generation records.")

    regional_wide = (
        pd.concat(aggregated_chunks, ignore_index=True)
        .groupby(["Region", "Datetime"], as_index=False, observed=True)[RESULT_SETS]
        .sum()
    )
    regional = regional_wide.melt(
        id_vars=["Region", "Datetime"],
        value_vars=RESULT_SETS,
        var_name="Result_Set",
        value_name="Renewable_Generation_MW",
    )
    return regional.sort_values(["Result_Set", "Region", "Datetime"]).reset_index(drop=True)


def assemble_interval_data(load, renewable):
    """Calculate residual demand using only intervals present in both inputs."""
    keys = ["Result_Set", "Region", "Datetime"]

    merged = load.merge(
        renewable,
        on=keys,
        how="outer",
        validate="one_to_one",
        indicator=True,
    )

    unmatched = merged["_merge"] != "both"
    if unmatched.any():
        excluded = merged.loc[unmatched, keys + ["_merge"]].copy()
        excluded.to_csv(
            OUTPUT_DIR / "excluded_unaligned_intervals.csv",
            index=False,
        )
        counts = excluded["_merge"].value_counts().to_dict()
        print(
            "WARNING: Excluding unaligned intervals. "
            f"Counts: {counts}. "
            "See residual_demand_outputs/excluded_unaligned_intervals.csv."
        )

    data = merged.loc[merged["_merge"] == "both"].drop(columns="_merge").copy()

    if data.empty:
        raise ValueError("No aligned intervals exist between load.csv and RE_gen.csv.")

    data["Residual_Demand_MW"] = data["Load_MW"] - data["Renewable_Generation_MW"]
    data["Renewable_Share_Percent"] = np.where(
        data["Load_MW"] != 0,
        data["Renewable_Generation_MW"] / data["Load_MW"] * 100.0,
        np.nan,
    )
    data["Negative_Residual_Demand"] = data["Residual_Demand_MW"] < 0
    data["Date"] = data["Datetime"].dt.normalize()
    data["Month"] = data["Datetime"].dt.to_period("M").astype(str)
    data["FYE"] = financial_year_ending(data["Datetime"])

    # Hour-ending convention: 01:00 = Period 1; midnight = Period 24.
    data["Period"] = data["Datetime"].dt.hour
    data.loc[data["Period"] == 0, "Period"] = 24

    return data.sort_values(keys).reset_index(drop=True)

def summarise(data, interval):
    interval_hours = interval / pd.Timedelta(hours=1)
    data = data.copy()
    data["Load_MWh"] = data["Load_MW"] * interval_hours
    data["Renewable_MWh"] = data["Renewable_Generation_MW"] * interval_hours
    data["Residual_MWh"] = data["Residual_Demand_MW"] * interval_hours
    data["Negative_Hours"] = data["Negative_Residual_Demand"].astype(float) * interval_hours

    def aggregate(group_columns):
        result = (
            data.groupby(group_columns, as_index=False, observed=True)
            .agg(
                Load_MWh=("Load_MWh", "sum"),
                Renewable_Generation_MWh=("Renewable_MWh", "sum"),
                Residual_Demand_MWh=("Residual_MWh", "sum"),
                Mean_Load_MW=("Load_MW", "mean"),
                Mean_Renewable_Generation_MW=("Renewable_Generation_MW", "mean"),
                Mean_Residual_Demand_MW=("Residual_Demand_MW", "mean"),
                Minimum_Residual_Demand_MW=("Residual_Demand_MW", "min"),
                Maximum_Residual_Demand_MW=("Residual_Demand_MW", "max"),
                Negative_Residual_Demand_Hours=("Negative_Hours", "sum"),
                Intervals=("Residual_Demand_MW", "size"),
            )
        )
        result["Renewable_Share_Percent"] = np.where(
            result["Load_MWh"] != 0,
            result["Renewable_Generation_MWh"] / result["Load_MWh"] * 100.0,
            np.nan,
        )
        return result

    daily = aggregate(["Result_Set", "Region", "Date"])
    monthly = aggregate(["Result_Set", "Region", "Month"])
    fye = aggregate(["Result_Set", "Region", "FYE"])

    extrema = []
    for keys, group in data.groupby(["Result_Set", "Region", "FYE"], observed=True):
        minimum = group.loc[group["Residual_Demand_MW"].idxmin()]
        maximum = group.loc[group["Residual_Demand_MW"].idxmax()]
        extrema.append({
            "Result_Set": keys[0], "Region": keys[1], "FYE": keys[2],
            "Minimum_Residual_Demand_MW": minimum["Residual_Demand_MW"],
            "Minimum_Datetime": minimum["Datetime"],
            "Load_at_Minimum_MW": minimum["Load_MW"],
            "Renewable_at_Minimum_MW": minimum["Renewable_Generation_MW"],
            "Maximum_Residual_Demand_MW": maximum["Residual_Demand_MW"],
            "Maximum_Datetime": maximum["Datetime"],
            "Load_at_Maximum_MW": maximum["Load_MW"],
            "Renewable_at_Maximum_MW": maximum["Renewable_Generation_MW"],
        })
    extrema = pd.DataFrame(extrema)
    fye = fye.merge(extrema, on=["Result_Set", "Region", "FYE"], how="left", validate="one_to_one")

    lowest = (
        data.sort_values("Residual_Demand_MW")
        .groupby(["Result_Set", "Region", "FYE"], as_index=False, observed=True)
        .head(100)
        .sort_values(["Result_Set", "Region", "FYE", "Residual_Demand_MW"])
    )
    negatives = data[data["Negative_Residual_Demand"]].copy()
    return daily, monthly, fye, lowest, negatives


def calculate_daily_four_hour_metrics(data, interval):
    """Calculate each day's four lowest and four highest RD intervals."""
    intervals_to_select = int(pd.Timedelta(hours=4) / interval)
    if intervals_to_select < 1 or intervals_to_select * interval != pd.Timedelta(hours=4):
        raise ValueError(
            f"The inferred interval {interval} cannot form exactly 4 hours."
        )

    records = []
    group_columns = ["Result_Set", "Region", "Date"]

    for (result_set, region, date), day in data.groupby(group_columns, observed=True):
        day = day.sort_values("Datetime").copy()
        if len(day) < intervals_to_select:
            continue

        lowest = day.nsmallest(intervals_to_select, "Residual_Demand_MW")
        highest = day.nlargest(intervals_to_select, "Residual_Demand_MW")

        low_value = lowest["Residual_Demand_MW"].mean()
        high_value = highest["Residual_Demand_MW"].mean()

        records.append({
            "Result_Set": result_set,
            "Region": region,
            "Date": date,
            "Month": date.to_period("M").strftime("%Y-%m"),
            "Calendar_Year": date.year,
            "Calendar_Month_Number": date.month,
            "Calendar_Month": date.strftime("%B"),
            "FYE": date.year + (date.month >= 7),
            "Lowest_4h_Average_Residual_Demand_MW": low_value,
            "Lowest_4h_Datetimes": " | ".join(
                lowest.sort_values("Datetime")["Datetime"].dt.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            ),
            "Highest_4h_Average_Residual_Demand_MW": high_value,
            "Highest_4h_Datetimes": " | ".join(
                highest.sort_values("Datetime")["Datetime"].dt.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            ),
            "Four_Hour_Residual_Demand_Spread_MW": high_value - low_value,
            "Lowest_4h_Average_Is_Negative": low_value < 0,
        })

    daily = pd.DataFrame(records)
    if daily.empty:
        raise ValueError("No days contained enough intervals for the 4-hour analysis.")
    return daily

def aggregate_four_hour_metrics(daily, group_columns):
    """Summarise daily 4-hour metrics for months or financial years."""
    return (
        daily.groupby(group_columns, as_index=False, observed=True)
        .agg(
            Days=("Date", "size"),
            Mean_Lowest_4h_MW=("Lowest_4h_Average_Residual_Demand_MW", "mean"),
            Median_Lowest_4h_MW=("Lowest_4h_Average_Residual_Demand_MW", "median"),
            Mean_Highest_4h_MW=("Highest_4h_Average_Residual_Demand_MW", "mean"),
            Median_Highest_4h_MW=("Highest_4h_Average_Residual_Demand_MW", "median"),
            Mean_4h_Spread_MW=("Four_Hour_Residual_Demand_Spread_MW", "mean"),
            Median_4h_Spread_MW=("Four_Hour_Residual_Demand_Spread_MW", "median"),
            P10_4h_Spread_MW=(
                "Four_Hour_Residual_Demand_Spread_MW",
                lambda values: values.quantile(0.10),
            ),
            P90_4h_Spread_MW=(
                "Four_Hour_Residual_Demand_Spread_MW",
                lambda values: values.quantile(0.90),
            ),
            Days_With_Negative_Lowest_4h=("Lowest_4h_Average_Is_Negative", "sum"),
        )
    )



def aggregate_calendar_month_trends(daily):
    """Compare the same calendar month across model years."""
    return aggregate_four_hour_metrics(
        daily,
        [
            "Result_Set",
            "Region",
            "Calendar_Month_Number",
            "Calendar_Month",
            "Calendar_Year",
        ],
    )


def plot_four_hour_metrics(monthly, fye, calendar_month_trends):
    """Create only the structural 4-hour BESS-proxy plots."""
    plot_dir = OUTPUT_DIR / "four_hour_spread_plots"
    high_low_dir = plot_dir / "monthly_high_low"
    spread_dir = plot_dir / "monthly_spread"
    fye_dir = plot_dir / "fye_spread"
    month_trend_spread_dir = plot_dir / "calendar_month_spread_trends"
    month_trend_high_low_dir = plot_dir / "calendar_month_high_low_trends"
    for directory in [
        high_low_dir,
        spread_dir,
        fye_dir,
        month_trend_spread_dir,
        month_trend_high_low_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    monthly = monthly.copy()
    monthly["Month_Date"] = pd.to_datetime(monthly["Month"] + "-01")

    for region, region_data in monthly.groupby("Region", observed=True):
        # Plot 1: monthly highest and lowest four-hour blocks.
        fig, ax = plt.subplots(figsize=(16, 8))
        for result_set, subset in region_data.groupby("Result_Set", observed=True):
            subset = subset.sort_values("Month_Date")
            colour = f"C{int(result_set) - 1}"
            ax.plot(
                subset["Month_Date"], subset["Mean_Highest_4h_MW"],
                color=colour, linewidth=1.8,
                label=f"Result Set {result_set} highest 4h",
            )
            ax.plot(
                subset["Month_Date"], subset["Mean_Lowest_4h_MW"],
                color=colour, linewidth=1.8, linestyle="--",
                label=f"Result Set {result_set} lowest 4h",
            )
        ax.axhline(0, color="black", linewidth=1)
        ax.set_title(f"Monthly Mean Daily Highest and Lowest Four-Hour Residual Demand: {region}")
        ax.set_xlabel("Month")
        ax.set_ylabel("Residual Demand (MW)")
        ax.grid(True, alpha=0.25)
        ax.legend(ncol=2, fontsize=9)
        ax.margins(x=0)
        fig.tight_layout()
        fig.savefig(
            high_low_dir / f"{safe_name(region)}_monthly_highest_lowest_4h.png",
            dpi=200, bbox_inches="tight",
        )
        plt.close(fig)

        # Plot 2: monthly mean daily 4-hour spread by result set.
        fig, ax = plt.subplots(figsize=(16, 8))
        for result_set, subset in region_data.groupby("Result_Set", observed=True):
            subset = subset.sort_values("Month_Date")
            ax.plot(
                subset["Month_Date"], subset["Mean_4h_Spread_MW"],
                linewidth=2.0, label=f"Result Set {result_set}",
            )
        ax.set_title(f"Monthly Mean Daily Four-Hour Residual-Demand Spread: {region}")
        ax.set_xlabel("Month")
        ax.set_ylabel("Average of highest 4 hours minus average of lowest 4 hours (MW)")
        ax.set_ylim(bottom=0)
        ax.grid(True, alpha=0.25)
        ax.legend(ncol=2)
        ax.margins(x=0)
        fig.tight_layout()
        fig.savefig(
            spread_dir / f"{safe_name(region)}_monthly_4h_spread.png",
            dpi=200, bbox_inches="tight",
        )
        plt.close(fig)

    # Calendar-month structural trends: one July chart, one December chart, etc.
    for (region, month_number, month_name), month_data in calendar_month_trends.groupby(
        ["Region", "Calendar_Month_Number", "Calendar_Month"],
        observed=True,
    ):
        month_data = month_data.sort_values(["Result_Set", "Calendar_Year"])

        # Same-month spread trend across calendar years.
        fig, ax = plt.subplots(figsize=(12, 8))
        for result_set, subset in month_data.groupby("Result_Set", observed=True):
            ax.plot(
                subset["Calendar_Year"],
                subset["Mean_4h_Spread_MW"],
                marker="o",
                linewidth=2.0,
                label=f"Result Set {result_set}",
            )
        ax.set_title(
            f"{month_name} Mean Daily 4-Hour Residual-Demand Spread: {region}"
        )
        ax.set_xlabel("Calendar Year")
        ax.set_ylabel(
            "Average of highest 4 hours minus average of lowest 4 hours (MW)"
        )
        ax.set_ylim(bottom=0)
        ax.set_xticks(sorted(month_data["Calendar_Year"].unique()))
        ax.grid(True, alpha=0.25)
        ax.legend(ncol=2)
        fig.tight_layout()
        fig.savefig(
            month_trend_spread_dir
            / f"{safe_name(region)}_{month_number:02d}_{safe_name(month_name)}_4h_spread_trend.png",
            dpi=200,
            bbox_inches="tight",
        )
        plt.close(fig)

        # Same-month decomposition of highest and lowest four hours.
        fig, ax = plt.subplots(figsize=(12, 8))
        for result_set, subset in month_data.groupby("Result_Set", observed=True):
            colour = f"C{int(result_set) - 1}"
            ax.plot(
                subset["Calendar_Year"],
                subset["Mean_Highest_4h_MW"],
                color=colour,
                marker="o",
                linewidth=1.8,
                label=f"Result Set {result_set} highest 4h",
            )
            ax.plot(
                subset["Calendar_Year"],
                subset["Mean_Lowest_4h_MW"],
                color=colour,
                marker="o",
                linewidth=1.8,
                linestyle="--",
                label=f"Result Set {result_set} lowest 4h",
            )
        ax.axhline(0, color="black", linewidth=1)
        ax.set_title(
            f"{month_name} Highest and Lowest 4-Hour Residual Demand: {region}"
        )
        ax.set_xlabel("Calendar Year")
        ax.set_ylabel("Residual Demand (MW)")
        ax.set_xticks(sorted(month_data["Calendar_Year"].unique()))
        ax.grid(True, alpha=0.25)
        ax.legend(ncol=2, fontsize=9)
        fig.tight_layout()
        fig.savefig(
            month_trend_high_low_dir
            / f"{safe_name(region)}_{month_number:02d}_{safe_name(month_name)}_high_low_trend.png",
            dpi=200,
            bbox_inches="tight",
        )
        plt.close(fig)

    # Plot 3: annual structural change, one chart per region.
    for region, region_data in fye.groupby("Region", observed=True):
        fig, ax = plt.subplots(figsize=(14, 8))
        for result_set, subset in region_data.groupby("Result_Set", observed=True):
            subset = subset.sort_values("FYE")
            ax.plot(
                subset["FYE"], subset["Mean_4h_Spread_MW"],
                marker="o", linewidth=2.0, label=f"Result Set {result_set}",
            )
        ax.set_title(f"Financial-Year Mean Daily Four-Hour Residual-Demand Spread: {region}")
        ax.set_xlabel("Financial Year Ending")
        ax.set_ylabel("Average of highest 4 hours minus average of lowest 4 hours (MW)")
        ax.set_ylim(bottom=0)
        ax.grid(True, alpha=0.25)
        ax.legend(ncol=2)
        fig.tight_layout()
        fig.savefig(
            fye_dir / f"{safe_name(region)}_fye_4h_spread.png",
            dpi=200, bbox_inches="tight",
        )
        plt.close(fig)

def main():
    for path in [LOAD_FILE, RE_FILE, OBJECTS_FILE]:
        require_file(path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading object-to-region mappings...")
    object_region_map, objects = load_object_region_map()
    print("Loading regional load...")
    load, interval = load_regional_load()
    print(f"Inferred interval length: {interval}")
    print("Streaming and aggregating renewable generation...")
    renewable = aggregate_renewable_generation(object_region_map, interval)
    print("Aligning load and renewable generation...")
    data = assemble_interval_data(load, renewable)

    print("Calculating daily four-hour high/low metrics...")
    daily_4h = calculate_daily_four_hour_metrics(data, interval)
    monthly_4h = aggregate_four_hour_metrics(
        daily_4h, ["Result_Set", "Region", "Month"]
    )
    fye_4h = aggregate_four_hour_metrics(
        daily_4h, ["Result_Set", "Region", "FYE"]
    )
    calendar_month_trends = aggregate_calendar_month_trends(daily_4h)

    data.to_csv(OUTPUT_DIR / "regional_residual_demand.csv", index=False)
    daily_4h.to_csv(OUTPUT_DIR / "daily_four_hour_metrics.csv", index=False)
    monthly_4h.to_csv(OUTPUT_DIR / "monthly_four_hour_metrics.csv", index=False)
    fye_4h.to_csv(OUTPUT_DIR / "fye_four_hour_metrics.csv", index=False)
    calendar_month_trends.to_csv(
        OUTPUT_DIR / "calendar_month_four_hour_trends.csv", index=False
    )

    included = objects[
        objects["Name"].isin(object_region_map.index)
    ][["Class", "Name", "Category", "Region"]].drop_duplicates()
    included.to_csv(
        OUTPUT_DIR / "renewable_object_region_mapping.csv", index=False
    )

    print("Creating 4-hour high/low structural-change plots...")
    plot_four_hour_metrics(monthly_4h, fye_4h, calendar_month_trends)
    print(f"Complete. Outputs saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
