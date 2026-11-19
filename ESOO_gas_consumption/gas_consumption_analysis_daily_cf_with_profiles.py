"""
ESOO gas consumption analysis: 2011 POE50 Offtake.csv

- Regional/Southern-region summary stats (financial year ending, monthly,
  daily peak). The model run spans FY2028-FY2031 (1 July 2027 - 30 June 2031),
  so annual/peak stats are grouped by financial year ending (FYE) rather than
  calendar year.
- Comparison of daily zone offtake against AEMO's PLEXOS gas constraints
  (Gas Zone Daily Offtake Limit <zone>), using the maximum RHS found in the
  matching 2011_POE50 limitations file as the ceiling (avoids penalising the
  model for the RHS's built-in infrastructure-depletion decline).
"""
import glob
import os
import re
import matplotlib.pyplot as plt
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
LIMITS_DIR = os.path.join(BASE, "2025 gas fuel limitations data")
REFERENCE_YEAR = "2011"
POE = "POE50"

# Station name (as it appears in Offtake.csv "Name") -> NEM region,
# derived from Fuel_memberships.csv (Generator.Fuels rows, Parent Category
# suffix). "Southern" = NSW + VIC + SA + TAS (matches AEMO's "Southern" gas
# zone footprint below); QLD is excluded from that grouping.
STATION_REGION = {
    "Bairnsdale": "VIC", "Barcaldine": "QLD", "Barker Inlet": "SA",
    "Bolivar Power Station": "SA", "Braemar": "QLD", "Braemar 2": "QLD",
    "Brigalow GT (Kogan Creek GT)": "QLD", "Colongra": "NSW",
    "Condamine": "QLD", "Darling Downs": "QLD", "Dry Creek": "SA",
    "Hallett": "SA", "Hunter": "NSW", "Jeeralang": "VIC",
    "Ladbroke Grove": "SA", "Laverton North": "VIC",
    "Lockyer Valley GT": "QLD", "Mintaro": "SA", "Mortlake OCGT": "VIC",
    "Newport": "VIC", "Oakey": "QLD", "Osborne": "SA",
    "Pelican Point": "SA", "Quarantine": "SA", "Roma": "QLD",
    "SA new OCGT": "SA", "Smithfield": "NSW", "Somerton": "VIC",
    "Swanbank E": "QLD", "Tallawarra": "NSW", "Tallawarra B": "NSW",
    "Tamar Valley CCGT": "TAS", "Tamar Valley OCGT": "TAS",
    "Torrens Island": "SA", "Townsville": "QLD", "Uranquinty": "NSW",
    "Valley Power": "VIC", "Yarwun": "QLD",
}

# Generation/available-capacity object name -> station/fuel parent.
# Derived from Generator.Fuels memberships, with the four additional mappings
# confirmed for this analysis.
GENERATOR_STATION = {
    # NSW
    "CG1": "Colongra", "CG2": "Colongra", "CG3": "Colongra", "CG4": "Colongra",
    "Dubbo Firming Power Station": "Hunter",
    "HUNTER1": "Hunter", "HUNTER2": "Hunter",
    "SITHE01": "Smithfield", "SITHE02": "Smithfield",
    "SITHE03": "Smithfield", "SITHE04": "Smithfield",
    "TALWA1": "Tallawarra", "TALWB1": "Tallawarra B",
    "URANQ11": "Uranquinty", "URANQ12": "Uranquinty",
    "URANQ13": "Uranquinty", "URANQ14": "Uranquinty",

    # QLD
    "BARCALDN": "Barcaldine",
    "BRAEMAR1": "Braemar", "BRAEMAR2": "Braemar", "BRAEMAR3": "Braemar",
    "BRAEMAR5": "Braemar 2", "BRAEMAR6": "Braemar 2", "BRAEMAR7": "Braemar 2",
    "CPSA_GT1": "Condamine", "CPSA_GT2": "Condamine", "CPSA_ST": "Condamine",
    "DDPS1_GT1": "Darling Downs", "DDPS1_GT2": "Darling Downs",
    "DDPS1_GT3": "Darling Downs", "DDPS1_ST": "Darling Downs",
    "OAKEY1": "Oakey", "OAKEY2": "Oakey",
    "ROMA_7": "Roma", "ROMA_8": "Roma", "SWAN_E": "Swanbank E",
    "YABULU": "Townsville", "YABULU2": "Townsville", "YARWUN_1": "Yarwun",
    "Brigalow GT (Kogan Creek GT)": "Brigalow GT (Kogan Creek GT)",

    # SA
    "AGLHAL01": "Hallett", "AGLHAL02": "Hallett", "AGLHAL03": "Hallett",
    "AGLHAL04": "Hallett", "AGLHAL05": "Hallett", "AGLHAL06": "Hallett",
    "AGLHAL07": "Hallett", "AGLHAL08": "Hallett", "AGLHAL09": "Hallett",
    "AGLHAL10": "Hallett", "AGLHAL11": "Hallett", "AGLHAL12": "Hallett",
    "AGLHAL13": "Hallett", "AGLHALRE": "Hallett",
    "BARKIPS1": "Barker Inlet",
    "BIPS1_01": "Barker Inlet", "BIPS1_02": "Barker Inlet",
    "BIPS1_03": "Barker Inlet", "BIPS1_04": "Barker Inlet",
    "BIPS1_05": "Barker Inlet", "BIPS1_06": "Barker Inlet",
    "BIPS1_07": "Barker Inlet", "BIPS1_08": "Barker Inlet",
    "BIPS1_09": "Barker Inlet", "BIPS1_10": "Barker Inlet",
    "BIPS1_11": "Barker Inlet", "BIPS1_12": "Barker Inlet",
    "Bolivar": "Bolivar Power Station", "BOLIVPS1": "Bolivar Power Station",
    "DRYCGT1": "Dry Creek", "DRYCGT2": "Dry Creek", "DRYCGT3": "Dry Creek",
    "LADBROK1": "Ladbroke Grove", "LADBROK2": "Ladbroke Grove",
    "MINTARO": "Mintaro", "OsborneGT": "Osborne", "OsborneST": "Osborne",
    "PPCCGTGT1": "Pelican Point", "PPCCGTGT2": "Pelican Point",
    "PPCCGTST": "Pelican Point",
    "QPS1": "Quarantine", "QPS2": "Quarantine", "QPS3": "Quarantine",
    "QPS4": "Quarantine", "QPS5": "Quarantine",
    "SATGS1": "SA new OCGT", "SNAPPER1": "SA new OCGT",
    "TORRA1": "Torrens Island", "TORRA2": "Torrens Island",
    "TORRA3": "Torrens Island", "TORRA4": "Torrens Island",
    "TORRB1": "Torrens Island", "TORRB2": "Torrens Island",
    "TORRB3": "Torrens Island", "TORRB4": "Torrens Island",

    # TAS
    "BBTHREE1": "Tamar Valley OCGT", "BBTHREE2": "Tamar Valley OCGT",
    "BBTHREE3": "Tamar Valley OCGT", "TVPP104": "Tamar Valley OCGT",
    "TVCC201_GT": "Tamar Valley CCGT", "TVCC201_ST": "Tamar Valley CCGT",

    # VIC
    "AGLSOM01": "Somerton", "AGLSOM02": "Somerton",
    "AGLSOM03": "Somerton", "AGLSOM04": "Somerton",
    "BDL01": "Bairnsdale", "BDL02": "Bairnsdale",
    "JLA01": "Jeeralang", "JLA02": "Jeeralang",
    "JLA03": "Jeeralang", "JLA04": "Jeeralang",
    "JLB01": "Jeeralang", "JLB02": "Jeeralang", "JLB03": "Jeeralang",
    "LNGS1": "Laverton North", "LNGS2": "Laverton North",
    "MORTLK11": "Mortlake OCGT", "MORTLK12": "Mortlake OCGT",
    "NPS": "Newport",
    "VPGS1": "Valley Power", "VPGS2": "Valley Power",
    "VPGS3": "Valley Power", "VPGS4": "Valley Power",
    "VPGS5": "Valley Power", "VPGS6": "Valley Power",
}

SOUTHERN_REGIONS = {"NSW", "VIC", "SA", "TAS"}

# Station name -> PLEXOS gas zones it is a member of (Fuel.Constraints
# "Offtake Coefficient" rows in PLEXOS_gas_constraints.csv). Stations not
# listed here (SA new OCGT, Yarwun, Brigalow GT (Kogan Creek GT)) are
# candidate/new-build or otherwise not subject to an existing "Gas Zone
# Daily Offtake Limit" constraint in this dataset.
STATION_ZONES = {
    "Colongra": ["Colongra", "Newcastle", "Southern"],
    "Bairnsdale": ["Gippsland", "Southern"],
    "Jeeralang": ["Gippsland", "Southern"],
    "Smithfield": ["Gippsland", "Southern"],
    "Tallawarra": ["Gippsland", "Southern"],
    "Tallawarra B": ["Gippsland", "Southern"],
    "Valley Power": ["Gippsland", "Southern"],
    "Tamar Valley CCGT": ["Gippsland", "Southern"],
    "Tamar Valley OCGT": ["Gippsland", "Southern"],
    "Hunter": ["Kurri Kurri", "Newcastle", "Southern"],
    "Laverton North": ["Melbourne", "Southern"],
    "Newport": ["Melbourne", "Southern"],
    "Somerton": ["Melbourne", "Southern"],
    "Bolivar Power Station": ["Moomba", "Southern"],
    "Dry Creek": ["Moomba", "Southern"],
    "Mintaro": ["Moomba", "Southern"],
    "Osborne": ["Moomba", "Southern"],
    "Townsville": ["NQGP"],
    "Barcaldine": ["Northern"],
    "Braemar": ["Northern"],
    "Braemar 2": ["Northern"],
    "Condamine": ["Northern"],
    "Darling Downs": ["Northern"],
    "Lockyer Valley GT": ["Northern"],
    "Oakey": ["Northern"],
    "Roma": ["Northern"],
    "Swanbank E": ["Northern"],
    "Ladbroke Grove": ["Port Campbell", "Southern"],
    "Mortlake OCGT": ["Port Campbell", "Southern"],
    "Barker Inlet": ["Southern"],
    "Hallett": ["Southern"],
    "Pelican Point": ["Southern"],
    "Quarantine": ["Southern"],
    "Uranquinty": ["Southern"],
    "Torrens Island": ["Southern"],
}

UNIT_COLS = ["1", "2", "3", "4", "5"]

# Model run window: FY2028-FY2031 (1 July 2027 - 30 June 2031).
RUN_START = pd.Timestamp("2027-07-01")
RUN_END = pd.Timestamp("2031-06-30")


def financial_year_ending(date_series):
    """FYE label (e.g. 2028 for 1 Jul 2027 - 30 Jun 2028)."""
    return date_series.dt.year + (date_series.dt.month >= 7).astype(int)

def load_interval_results(filename, value_name):
    """Load and validate a unit-level PLEXOS interval result file."""
    path = os.path.join(BASE, filename)
    df = pd.read_csv(path)

    required_columns = {"Name", "Year", "Month", "Day", "Period", *UNIT_COLS}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise ValueError(
            f"{filename!r} is missing columns: {sorted(missing_columns)}"
        )

    df["Name"] = df["Name"].str.strip()
    df = df.melt(
        id_vars=["Name", "Year", "Month", "Day", "Period"],
        value_vars=UNIT_COLS,
        var_name="Result_Set",
        value_name=value_name,
    )
    df["Date"] = pd.to_datetime(
        dict(year=df["Year"], month=df["Month"], day=df["Day"])
    )
    df = df[(df["Date"] >= RUN_START) & (df["Date"] <= RUN_END)].copy()

    df["Station"] = df["Name"].map(GENERATOR_STATION)
    unmapped_units = sorted(df.loc[df["Station"].isna(), "Name"].unique())
    if unmapped_units:
        raise ValueError(
            f"Unmapped generator names in {filename!r}: {unmapped_units}"
        )

    df["Region"] = df["Station"].map(STATION_REGION)
    unmapped_stations = sorted(df.loc[df["Region"].isna(), "Station"].unique())
    if unmapped_stations:
        raise ValueError(
            f"Generator stations without a region in {filename!r}: "
            f"{unmapped_stations}"
        )

    key_columns = ["Name", "Date", "Period", "Result_Set"]
    duplicate_keys = df.duplicated(subset=key_columns, keep=False)
    if duplicate_keys.any():
        duplicates = df.loc[duplicate_keys, key_columns]
        raise ValueError(
            f"Duplicate interval records found in {filename!r}:\n"
            f"{duplicates.to_string(index=False)}"
        )

    return df
def load_offtake():
    df = pd.read_csv(os.path.join(BASE, "Offtake.csv"))
    df["Name"] = df["Name"].str.strip()

    # Columns 1-5 are separate result sets, not additive units.
    df = df.melt(
        id_vars=["Name", "Year", "Month", "Day"],
        value_vars=UNIT_COLS,
        var_name="Result_Set",
        value_name="Offtake_GJ",
    )

    df["Date"] = pd.to_datetime(
        dict(year=df["Year"], month=df["Month"], day=df["Day"])
    )

    df = df[(df["Date"] >= RUN_START) & (df["Date"] <= RUN_END)]

    df["Region"] = df["Name"].map(STATION_REGION)

    unmapped = df.loc[df["Region"].isna(), "Name"].unique()
    if len(unmapped):
        raise ValueError(f"Unmapped station names: {unmapped}")

    return df

def regional_stats(df):
    daily = (
        df.groupby(["Result_Set", "Region", "Date"], as_index=False)["Offtake_GJ"]
        .sum()
    )
    daily["Offtake_TJ"] = daily["Offtake_GJ"] / 1000.0

    southern = daily[daily["Region"].isin(SOUTHERN_REGIONS)]

    southern_daily = (
        southern.groupby(["Result_Set", "Date"], as_index=False)["Offtake_TJ"]
        .sum()
    )
    southern_daily["Region"] = "Southern (NSW+VIC+SA+TAS)"

    all_daily = pd.concat(
        [
            daily[["Result_Set", "Region", "Date", "Offtake_TJ"]],
            southern_daily[["Result_Set", "Region", "Date", "Offtake_TJ"]],
        ],
        ignore_index=True,
    )

    all_daily["FYE"] = financial_year_ending(all_daily["Date"])
    all_daily["Month"] = all_daily["Date"].dt.to_period("M")

    annual = (
        all_daily.groupby(["Result_Set", "Region", "FYE"], as_index=False)["Offtake_TJ"]
        .sum()
        .rename(columns={"Offtake_TJ": "Annual_TJ"})
    )

    monthly = (
        all_daily.groupby(["Result_Set", "Region", "Month"], as_index=False)["Offtake_TJ"]
        .sum()
        .rename(columns={"Offtake_TJ": "Monthly_TJ"})
    )

    daily_peak = (
        all_daily.groupby(["Result_Set", "Region", "FYE"], as_index=False)["Offtake_TJ"]
        .max()
        .rename(columns={"Offtake_TJ": "Peak_Daily_TJ"})
    )

    return annual, monthly, daily_peak, all_daily

def capacity_factor_analysis():
    """Calculate availability-adjusted CFs by unit, station, and region."""
    generation = load_interval_results("Generation.csv", "Generation_MW")
    available_capacity = load_interval_results(
        "Available Capacity.csv", "Available_Capacity_MW"
    )

    merge_keys = [
        "Name", "Station", "Region", "Date", "Period", "Result_Set"
    ]
    interval_data = generation[merge_keys + ["Generation_MW"]].merge(
        available_capacity[merge_keys + ["Available_Capacity_MW"]],
        on=merge_keys,
        how="outer",
        validate="one_to_one",
        indicator=True,
    )

    unmatched = interval_data["_merge"] != "both"
    if unmatched.any():
        missing = interval_data.loc[unmatched, merge_keys + ["_merge"]]
        raise ValueError(
            "Generation and available-capacity records do not align:\n"
            f"{missing.to_string(index=False)}"
        )
    interval_data = interval_data.drop(columns="_merge")
    interval_data["FYE"] = financial_year_ending(interval_data["Date"])
    interval_data["Month"] = interval_data["Date"].dt.to_period("M")

    invalid_capacity = interval_data["Available_Capacity_MW"] < 0
    if invalid_capacity.any():
        invalid = interval_data.loc[
            invalid_capacity, merge_keys + ["Available_Capacity_MW"]
        ]
        raise ValueError(
            "Negative available-capacity values found:\n"
            f"{invalid.to_string(index=False)}"
        )

    generation_above_capacity = (
        interval_data["Generation_MW"]
        > interval_data["Available_Capacity_MW"] + 1e-6
    )
    if generation_above_capacity.any():
        breaches = interval_data.loc[
            generation_above_capacity,
            merge_keys + ["Generation_MW", "Available_Capacity_MW"],
        ].copy()
        breaches["Exceedance_MW"] = (
            breaches["Generation_MW"] - breaches["Available_Capacity_MW"]
        )
        print(
            "WARNING: Generation exceeds available capacity in "
            f"{len(breaches):,} interval records. "
            "See capacity_factor_generation_above_available.csv."
        )
    else:
        breaches = pd.DataFrame()

    unit_daily = aggregate_capacity_factor(
        interval_data,
        ["Result_Set", "Name", "Station", "Region", "Date"],
    )
    unit_fye = aggregate_capacity_factor(
        interval_data, ["Result_Set", "Name", "Station", "Region", "FYE"]
    )
    unit_monthly = aggregate_capacity_factor(
        interval_data, ["Result_Set", "Name", "Station", "Region", "Month"]
    )

    station_interval = (
        interval_data.groupby(
            ["Result_Set", "Station", "Region", "Date", "Period", "FYE", "Month"],
            as_index=False,
        )[["Generation_MW", "Available_Capacity_MW"]]
        .sum()
    )
    station_daily = aggregate_capacity_factor(
        station_interval, ["Result_Set", "Station", "Region", "Date"]
    )
    station_fye = aggregate_capacity_factor(
        station_interval, ["Result_Set", "Station", "Region", "FYE"]
    )
    station_monthly = aggregate_capacity_factor(
        station_interval, ["Result_Set", "Station", "Region", "Month"]
    )

    region_interval = (
        station_interval.groupby(
            ["Result_Set", "Region", "Date", "Period", "FYE", "Month"],
            as_index=False,
        )[["Generation_MW", "Available_Capacity_MW"]]
        .sum()
    )
    southern_interval = (
        region_interval[region_interval["Region"].isin(SOUTHERN_REGIONS)]
        .groupby(
            ["Result_Set", "Date", "Period", "FYE", "Month"],
            as_index=False,
        )[["Generation_MW", "Available_Capacity_MW"]]
        .sum()
    )
    southern_interval["Region"] = "Southern (NSW+VIC+SA+TAS)"
    all_region_interval = pd.concat(
        [region_interval, southern_interval], ignore_index=True
    )
    region_daily = aggregate_capacity_factor(
        all_region_interval, ["Result_Set", "Region", "Date"]
    )
    region_fye = aggregate_capacity_factor(
        all_region_interval, ["Result_Set", "Region", "FYE"]
    )
    region_monthly = aggregate_capacity_factor(
        all_region_interval, ["Result_Set", "Region", "Month"]
    )

    return (
        unit_daily, unit_fye, unit_monthly,
        station_daily, station_fye, station_monthly,
        region_daily, region_fye, region_monthly,
        all_region_interval, breaches,
    )
def aggregate_capacity_factor(df, group_columns):
    """
    Calculate weighted capacity factors over the specified grouping.

    The denominator is the sum of interval available capacity, so periods
    with more available capacity receive proportionately more weight.
    """
    result = (
        df.groupby(group_columns, as_index=False)
        .agg(
            Generation_MW_Intervals=(
                "Generation_MW",
                "sum",
            ),
            Available_Capacity_MW_Intervals=(
                "Available_Capacity_MW",
                "sum",
            ),
            Maximum_Generation_MW=(
                "Generation_MW",
                "max",
            ),
            Maximum_Available_Capacity_MW=(
                "Available_Capacity_MW",
                "max",
            ),
            Intervals=(
                "Generation_MW",
                "size",
            ),
            Available_Intervals=(
                "Available_Capacity_MW",
                lambda values: (values > 0).sum(),
            ),
        )
    )

    result["Capacity_Factor"] = (
        result["Generation_MW_Intervals"]
        / result["Available_Capacity_MW_Intervals"]
    )

    result.loc[
        result["Available_Capacity_MW_Intervals"] == 0,
        "Capacity_Factor",
    ] = pd.NA

    result["Capacity_Factor_Percent"] = (
        result["Capacity_Factor"] * 100.0
    )

    result["Availability_Percent"] = (
        result["Available_Intervals"]
        / result["Intervals"]
        * 100.0
    )

    return result


def plot_capacity_factors(station_daily, region_daily, region_fye, out_dir):
    """Create daily time-series, duration-curve, and annual summary CF charts."""
    plot_dir = os.path.join(out_dir, "capacity_factor_plots")
    region_daily_dir = os.path.join(plot_dir, "region_daily")
    station_daily_dir = os.path.join(plot_dir, "station_daily")
    duration_dir = os.path.join(plot_dir, "region_duration_curves")
    annual_dir = os.path.join(plot_dir, "region_fye")

    for directory in [
        region_daily_dir,
        station_daily_dir,
        duration_dir,
        annual_dir,
    ]:
        os.makedirs(directory, exist_ok=True)

    def safe_name(value):
        return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")

    # Daily regional CF with a 30-day rolling mean for readability.
    for region, data in region_daily.groupby("Region"):
        fig, ax = plt.subplots(figsize=(16, 8))
        for result_set in UNIT_COLS:
            subset = data[data["Result_Set"] == result_set].sort_values("Date")
            if subset.empty:
                continue
            ax.plot(
                subset["Date"],
                subset["Capacity_Factor_Percent"],
                linewidth=0.5,
                alpha=0.25,
                color=f"C{int(result_set) - 1}",
            )
            rolling = subset.set_index("Date")["Capacity_Factor_Percent"].rolling(
                window=30,
                min_periods=1,
            ).mean()
            ax.plot(
                rolling.index,
                rolling.values,
                linewidth=1.8,
                color=f"C{int(result_set) - 1}",
                label=f"Result Set {result_set}, 30-day mean",
            )

        ax.set_title(f"Daily Availability-Adjusted Capacity Factor: {region}")
        ax.set_xlabel("Date")
        ax.set_ylabel("Capacity Factor (%)")
        ax.axhline(100, color="black", linestyle="--", linewidth=1.0, alpha=0.6)
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best", ncol=2)
        ax.margins(x=0)
        fig.tight_layout()
        fig.savefig(
            os.path.join(region_daily_dir, f"region_{safe_name(region)}_daily_cf.png"),
            dpi=200,
            bbox_inches="tight",
        )
        plt.close(fig)

    # Daily station CF. Raw daily lines are retained because peaking stations
    # can have sparse operation that a rolling average would conceal.
    for station, data in station_daily.groupby("Station"):
        fig, ax = plt.subplots(figsize=(16, 8))
        for result_set in UNIT_COLS:
            subset = data[data["Result_Set"] == result_set].sort_values("Date")
            if subset.empty:
                continue
            ax.plot(
                subset["Date"],
                subset["Capacity_Factor_Percent"],
                linewidth=0.9,
                label=f"Result Set {result_set}",
            )

        ax.set_title(f"Daily Availability-Adjusted Capacity Factor: {station}")
        ax.set_xlabel("Date")
        ax.set_ylabel("Capacity Factor (%)")
        ax.axhline(100, color="black", linestyle="--", linewidth=1.0, alpha=0.6)
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best", ncol=2)
        ax.margins(x=0)
        fig.tight_layout()
        fig.savefig(
            os.path.join(station_daily_dir, f"station_{safe_name(station)}_daily_cf.png"),
            dpi=200,
            bbox_inches="tight",
        )
        plt.close(fig)

        # Regional daily CF duration curves by financial year.
    region_daily = region_daily.copy()
    region_daily["FYE"] = financial_year_ending(
        region_daily["Date"]
    )

    for region, region_data in region_daily.groupby("Region"):

        for fye, data in region_data.groupby("FYE"):

            fig, ax = plt.subplots(figsize=(12, 8))

            for result_set in UNIT_COLS:
                values = (
                    data.loc[
                        data["Result_Set"] == result_set,
                        "Capacity_Factor_Percent",
                    ]
                    .dropna()
                    .sort_values(ascending=False)
                    .reset_index(drop=True)
                )

                if values.empty:
                    continue

                exceedance_percent = (
                    (values.index + 1)
                    / len(values)
                    * 100.0
                )

                ax.plot(
                    exceedance_percent,
                    values,
                    linewidth=1.6,
                    label=f"Result Set {result_set}",
                )

            ax.set_title(
                f"Daily Capacity Factor Duration Curve: "
                f"{region} - FY{fye}"
            )

            ax.set_xlabel(
                "Percentage of Days Met or Exceeded (%)"
            )
            ax.set_ylabel("Daily Capacity Factor (%)")

            ax.axhline(
                100,
                color="black",
                linestyle="--",
                linewidth=1.0,
                alpha=0.6,
            )

            ax.grid(True, alpha=0.25)
            ax.legend(loc="best")

            fig.tight_layout()

            fig.savefig(
                os.path.join(
                    duration_dir,
                    (
                        f"region_{safe_name(region)}_"
                        f"FY{fye}_daily_cf_duration.png"
                    ),
                ),
                dpi=200,
                bbox_inches="tight",
            )

            plt.close(fig)

    # One annual regional comparison chart per result set.
    for result_set in UNIT_COLS:
        subset = region_fye[region_fye["Result_Set"] == result_set]
        if subset.empty:
            continue
        pivot = subset.pivot(
            index="FYE",
            columns="Region",
            values="Capacity_Factor_Percent",
        )
        ax = pivot.plot(kind="bar", figsize=(14, 8), width=0.85)
        ax.set_title(f"Regional Capacity Factor by FYE: Result Set {result_set}")
        ax.set_xlabel("Financial Year Ending")
        ax.set_ylabel("Capacity Factor (%)")
        ax.grid(axis="y", alpha=0.25)
        ax.legend(title="Region", loc="best")
        ax.get_figure().tight_layout()
        ax.get_figure().savefig(
            os.path.join(annual_dir, f"region_fye_cf_result_set_{result_set}.png"),
            dpi=200,
            bbox_inches="tight",
        )
        plt.close(ax.get_figure())

    print(f"Saved capacity-factor charts under: {plot_dir}")


def plot_regional_generation_profiles(region_interval, out_dir):
    """Create compact regional gas-generation profile outputs."""
    plot_dir = os.path.join(out_dir, "generation_profile_plots")
    monthly_dir = os.path.join(plot_dir, "monthly")
    fye_dir = os.path.join(plot_dir, "fye")
    os.makedirs(monthly_dir, exist_ok=True)
    os.makedirs(fye_dir, exist_ok=True)

    profile_data = region_interval.copy()
    profile_data["Period"] = pd.to_numeric(profile_data["Period"], errors="raise")

    # Common y-axis maximum for each region across the entire run.
    # Add 5% headroom above the highest regional generation observation.
    region_ymax = (
    profile_data.groupby("Region")["Generation_MW"]
    .max()
    .mul(1.05)
    .to_dict()
    )

    # Retain the complete regional series for ad hoc daily inspection.
    profile_data.to_csv(
        os.path.join(out_dir, "regional_generation.csv"),
        index=False,
    )

    def safe_name(value):
        return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_")

    monthly_profiles = (
        profile_data.groupby(
            ["Result_Set", "Region", "Month", "Period"],
            as_index=False,
        )["Generation_MW"]
        .mean()
        .rename(columns={"Generation_MW": "Mean_Generation_MW"})
    )

    monthly_profiles.to_csv(
        os.path.join(out_dir, "regional_monthly_hourly_profiles.csv"),
        index=False,
    )

    for (region, month), data in monthly_profiles.groupby(["Region", "Month"]):
        fig, ax = plt.subplots(figsize=(14, 8))

        for result_set in UNIT_COLS:
            subset = data[data["Result_Set"] == result_set].sort_values("Period")
            if subset.empty:
                continue

            colour = f"C{int(result_set) - 1}"
            x = subset["Period"].to_numpy(dtype=float)
            mean = subset["Mean_Generation_MW"].to_numpy(dtype=float)
            ax.plot(
                x,
                mean,
                color=colour,
                linewidth=1.8,
                label=f"Result Set {result_set}",
            )

        ax.set_title(f"Average Gas Generation: {region} - {month}")
        ax.set_xlabel("Hour")
        ax.set_ylabel("Generation (MW)")
        ax.set_xticks(range(1, 25, 2))
        ax.set_ylim(
        bottom=0,
        top=region_ymax[region],
        )
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best", ncol=2)
        fig.tight_layout()
        fig.savefig(
            os.path.join(
                monthly_dir,
                f"{safe_name(region)}_{safe_name(month)}_hourly_generation.png",
            ),
            dpi=200,
            bbox_inches="tight",
        )
        plt.close(fig)

    # FYE profiles: average generation for each result set.
    fye_profiles = (
        profile_data.groupby(
            ["Result_Set", "Region", "FYE", "Period"],
            as_index=False,
        )["Generation_MW"]
        .mean()
        .rename(columns={"Generation_MW": "Mean_Generation_MW"})
    )

    fye_profiles.to_csv(
        os.path.join(out_dir, "regional_fye_hourly_profiles.csv"),
        index=False,
    )

    for (region, fye), data in fye_profiles.groupby(["Region", "FYE"]):
        fig, ax = plt.subplots(figsize=(14, 8))

        for result_set in UNIT_COLS:
            subset = data[data["Result_Set"] == result_set].sort_values("Period")
            if subset.empty:
                continue

            ax.plot(
                subset["Period"],
                subset["Mean_Generation_MW"],
                linewidth=1.8,
                label=f"Result Set {result_set}",
            )

        ax.set_title(f"Average Gas Generation: {region} - FY{fye}")
        ax.set_xlabel("Hour")
        ax.set_ylabel("Generation (MW)")
        ax.set_xticks(range(1, 25, 2))
        ax.set_ylim(
        bottom=0,
        top=region_ymax[region],
        )
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best", ncol=2)
        fig.tight_layout()
        fig.savefig(
            os.path.join(
                fye_dir,
                f"{safe_name(region)}_FY{fye}_hourly_generation.png",
            ),
            dpi=200,
            bbox_inches="tight",
        )
        plt.close(fig)

    print(f"Saved regional generation-profile charts under: {plot_dir}")

def load_rhs_for_zone(zone):
    """
    Load the dated raw RHS series for a gas-zone constraint.

    Returns columns:
        Zone, Date, RHS_Raw_TJ
    """
    fname = (
        f"GPG_Limit_STEP_CHANGE_{zone}_GPG_Limit_TJ_"
        f"{REFERENCE_YEAR}_{POE}.csv"
    )
    path = os.path.join(LIMITS_DIR, fname)

    if not os.path.exists(path):
        matches = glob.glob(
            os.path.join(
                LIMITS_DIR,
                f"*{zone}*{REFERENCE_YEAR}_{POE}.csv",
            )
        )

        if not matches:
            raise FileNotFoundError(
                f"No RHS file found for zone {zone!r} ({fname})"
            )

        if len(matches) > 1:
            raise ValueError(
                f"Multiple RHS files found for zone {zone!r}: {matches}"
            )

        path = matches[0]

    rhs = pd.read_csv(path)

    required_columns = {"Year", "Month", "Day", "Value"}
    missing_columns = required_columns.difference(rhs.columns)

    if missing_columns:
        raise ValueError(
            f"RHS file {os.path.basename(path)!r} is missing columns: "
            f"{sorted(missing_columns)}"
        )

    rhs["Date"] = pd.to_datetime(
        dict(
            year=rhs["Year"],
            month=rhs["Month"],
            day=rhs["Day"],
        )
    )

    rhs = rhs[
        (rhs["Date"] >= RUN_START)
        & (rhs["Date"] <= RUN_END)
    ].copy()

    duplicate_dates = rhs["Date"].duplicated(keep=False)

    if duplicate_dates.any():
        duplicated = (
            rhs.loc[duplicate_dates, "Date"]
            .dt.strftime("%Y-%m-%d")
            .unique()
        )

        raise ValueError(
            f"RHS file for zone {zone!r} contains duplicate dates: "
            f"{duplicated}"
        )

    rhs = rhs.rename(columns={"Value": "RHS_Raw_TJ"})
    rhs["Zone"] = zone

    return rhs[["Zone", "Date", "RHS_Raw_TJ"]]

def constraint_violations(df):
    zones = sorted({
        zone
        for station_zones in STATION_ZONES.values()
        for zone in station_zones
    })

    rhs_data = pd.concat(
        [load_rhs_for_zone(zone) for zone in zones],
        ignore_index=True,
    )

    rhs_max = (
        rhs_data.groupby("Zone", as_index=False)["RHS_Raw_TJ"]
        .max()
        .rename(columns={"RHS_Raw_TJ": "RHS_Max_TJ"})
    )

    zone_daily = df.copy()
    zone_daily["Zones"] = zone_daily["Name"].map(STATION_ZONES)
    zone_daily = zone_daily.dropna(subset=["Zones"])
    zone_daily = zone_daily.explode("Zones")

    daily_zone_totals = (
        zone_daily.groupby(
            ["Result_Set", "Zones", "Date"],
            as_index=False,
        )["Offtake_GJ"]
        .sum()
        .rename(columns={"Zones": "Zone"})
    )

    daily_zone_totals["Offtake_TJ"] = (
        daily_zone_totals["Offtake_GJ"] / 1000.0
    )

    daily_zone_totals["FYE"] = financial_year_ending(
        daily_zone_totals["Date"]
    )

    daily_zone_totals = daily_zone_totals.merge(
        rhs_data,
        on=["Zone", "Date"],
        how="left",
        validate="many_to_one",
    )

    daily_zone_totals = daily_zone_totals.merge(
        rhs_max,
        on="Zone",
        how="left",
        validate="many_to_one",
    )

    missing_raw_rhs = daily_zone_totals["RHS_Raw_TJ"].isna()

    if missing_raw_rhs.any():
        missing = (
            daily_zone_totals.loc[
                missing_raw_rhs,
                ["Zone", "Date"],
            ]
            .drop_duplicates()
            .sort_values(["Zone", "Date"])
        )

        raise ValueError(
            "Raw RHS values are missing for the following zone-dates:\n"
            f"{missing.to_string(index=False)}"
        )

    daily_zone_totals["Violation_Max_RHS"] = (
        daily_zone_totals["Offtake_TJ"]
        > daily_zone_totals["RHS_Max_TJ"]
    )

    daily_zone_totals["Exceedance_Max_RHS_TJ"] = (
        daily_zone_totals["Offtake_TJ"]
        - daily_zone_totals["RHS_Max_TJ"]
    ).clip(lower=0)

    daily_zone_totals["Violation_Raw_RHS"] = (
        daily_zone_totals["Offtake_TJ"]
        > daily_zone_totals["RHS_Raw_TJ"]
    )

    daily_zone_totals["Exceedance_Raw_RHS_TJ"] = (
        daily_zone_totals["Offtake_TJ"]
        - daily_zone_totals["RHS_Raw_TJ"]
    ).clip(lower=0)

    return daily_zone_totals

def plot_constraints(constraint_data, out_dir):
    """
    Create two plots for each gas zone:

    1. LHS against the constant maximum RHS.
    2. LHS against the dated raw RHS.
    """
    plot_dir = os.path.join(out_dir, "constraint_plots")
    max_rhs_dir = os.path.join(plot_dir, "maximum_rhs")
    raw_rhs_dir = os.path.join(plot_dir, "raw_rhs")

    os.makedirs(max_rhs_dir, exist_ok=True)
    os.makedirs(raw_rhs_dir, exist_ok=True)

    required_columns = {
        "Result_Set",
        "Zone",
        "Date",
        "Offtake_TJ",
        "RHS_Max_TJ",
        "RHS_Raw_TJ",
        "Violation_Max_RHS",
        "Violation_Raw_RHS",
    }

    missing_columns = required_columns.difference(
        constraint_data.columns
    )

    if missing_columns:
        raise ValueError(
            "Constraint plotting data is missing columns: "
            f"{sorted(missing_columns)}"
        )

    for zone, zone_data in constraint_data.groupby("Zone"):
        zone_data = zone_data.sort_values(
            ["Result_Set", "Date"]
        )

        safe_zone_name = re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            zone,
        ).strip("_")

        # -------------------------------------------------------------
        # Plot 1: LHS against constant maximum RHS
        # -------------------------------------------------------------
        fig, ax = plt.subplots(figsize=(16, 8))

        for result_set in UNIT_COLS:
            result_data = zone_data[
                zone_data["Result_Set"] == result_set
            ].sort_values("Date")

            if result_data.empty:
                continue

            line = ax.plot(
                result_data["Date"],
                result_data["Offtake_TJ"],
                linewidth=1.2,
                label=f"Result Set {result_set} LHS",
            )[0]

            violating = result_data[
                result_data["Violation_Max_RHS"]
            ]

            if not violating.empty:
                ax.scatter(
                    violating["Date"],
                    violating["Offtake_TJ"],
                    color=line.get_color(),
                    edgecolor="red",
                    linewidth=0.8,
                    s=24,
                    zorder=3,
                )

        rhs_max_values = zone_data["RHS_Max_TJ"].dropna().unique()

        if len(rhs_max_values) != 1:
            raise ValueError(
                f"Expected one maximum RHS for zone {zone!r}, "
                f"but found {rhs_max_values}"
            )

        rhs_max = rhs_max_values[0]

        ax.axhline(
            rhs_max,
            color="black",
            linestyle="--",
            linewidth=2.0,
            label=f"Maximum RHS: {rhs_max:,.1f} TJ/day",
        )

        ax.set_title(
            f"Gas Zone Daily Offtake Constraint: {zone}\n"
            "Comparison Against Maximum RHS"
        )
        ax.set_xlabel("Date")
        ax.set_ylabel("Daily Offtake / Constraint RHS (TJ)")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best", ncol=2)
        ax.margins(x=0)

        fig.tight_layout()

        max_output_path = os.path.join(
            max_rhs_dir,
            f"constraint_{safe_zone_name}_maximum_rhs.png",
        )

        fig.savefig(
            max_output_path,
            dpi=200,
            bbox_inches="tight",
        )

        plt.close(fig)

        # -------------------------------------------------------------
        # Plot 2: LHS against dated raw RHS
        # -------------------------------------------------------------
        fig, ax = plt.subplots(figsize=(16, 8))

        for result_set in UNIT_COLS:
            result_data = zone_data[
                zone_data["Result_Set"] == result_set
            ].sort_values("Date")

            if result_data.empty:
                continue

            line = ax.plot(
                result_data["Date"],
                result_data["Offtake_TJ"],
                linewidth=1.2,
                label=f"Result Set {result_set} LHS",
            )[0]

            violating = result_data[
                result_data["Violation_Raw_RHS"]
            ]

            if not violating.empty:
                ax.scatter(
                    violating["Date"],
                    violating["Offtake_TJ"],
                    color=line.get_color(),
                    edgecolor="red",
                    linewidth=0.8,
                    s=24,
                    zorder=3,
                )

        raw_rhs = (
            zone_data[["Date", "RHS_Raw_TJ"]]
            .drop_duplicates()
            .sort_values("Date")
        )

        ax.plot(
            raw_rhs["Date"],
            raw_rhs["RHS_Raw_TJ"],
            color="black",
            linestyle="--",
            linewidth=2.0,
            label="Raw dated RHS",
        )

        ax.set_title(
            f"Gas Zone Daily Offtake Constraint: {zone}\n"
            "Comparison Against Raw RHS"
        )
        ax.set_xlabel("Date")
        ax.set_ylabel("Daily Offtake / Constraint RHS (TJ)")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best", ncol=2)
        ax.margins(x=0)

        fig.tight_layout()

        raw_output_path = os.path.join(
            raw_rhs_dir,
            f"constraint_{safe_zone_name}_raw_rhs.png",
        )

        fig.savefig(
            raw_output_path,
            dpi=200,
            bbox_inches="tight",
        )

        plt.close(fig)

        print(f"Saved maximum RHS plot: {max_output_path}")
        print(f"Saved raw RHS plot:     {raw_output_path}")


def main():
    df = load_offtake()
    annual, monthly, daily_peak, _ = regional_stats(df)
    violations = constraint_violations(df)

    (
        unit_daily_cf,
        unit_fye_cf,
        unit_monthly_cf,
        station_daily_cf,
        station_fye_cf,
        station_monthly_cf,
        region_daily_cf,
        region_fye_cf,
        region_monthly_cf,
        regional_generation_interval,
        cf_breaches,
    ) = capacity_factor_analysis()

    out_dir = os.path.join(BASE, "analysis_outputs")
    os.makedirs(out_dir, exist_ok=True)

    annual.to_csv(os.path.join(out_dir, "annual_by_region.csv"), index=False)
    monthly.to_csv(os.path.join(out_dir, "monthly_by_region.csv"), index=False)
    daily_peak.to_csv(os.path.join(out_dir, "daily_peak_by_region.csv"), index=False)
    violations.to_csv(os.path.join(out_dir, "gas_zone_constraint_check.csv"), index=False)
    unit_daily_cf.to_csv(os.path.join(out_dir, "capacity_factor_by_unit_day.csv"), index=False)
    unit_fye_cf.to_csv(os.path.join(out_dir, "capacity_factor_by_unit_fye.csv"), index=False)
    unit_monthly_cf.to_csv(os.path.join(out_dir, "capacity_factor_by_unit_month.csv"), index=False)
    station_daily_cf.to_csv(os.path.join(out_dir, "capacity_factor_by_station_day.csv"), index=False)
    station_fye_cf.to_csv(os.path.join(out_dir, "capacity_factor_by_station_fye.csv"), index=False)
    station_monthly_cf.to_csv(os.path.join(out_dir, "capacity_factor_by_station_month.csv"), index=False)
    region_daily_cf.to_csv(os.path.join(out_dir, "capacity_factor_by_region_day.csv"), index=False)
    region_fye_cf.to_csv(os.path.join(out_dir, "capacity_factor_by_region_fye.csv"), index=False)
    region_monthly_cf.to_csv(os.path.join(out_dir, "capacity_factor_by_region_month.csv"), index=False)
    if not cf_breaches.empty:
        cf_breaches.to_csv(
            os.path.join(out_dir, "capacity_factor_generation_above_available.csv"),
            index=False,
        )

    plot_constraints(violations, out_dir)
    plot_capacity_factors(
        station_daily_cf,
        region_daily_cf,
        region_fye_cf,
        out_dir,
    )
    plot_regional_generation_profiles(
        regional_generation_interval,
        out_dir,
    )

    print("=== Annual (FYE) TJ by region ===")
    for result_set in UNIT_COLS:
        subset = annual[annual["Result_Set"] == result_set]
        print(f"\n--- Result Set {result_set} ---")
        print(
            subset.pivot(
                index="FYE",
                columns="Region",
                values="Annual_TJ",
            ).round(1).to_string()
        )

    print("\n=== Peak daily TJ by region (per FYE) ===")
    for result_set in UNIT_COLS:
        subset = daily_peak[daily_peak["Result_Set"] == result_set]
        print(f"\n--- Result Set {result_set} ---")
        print(
            subset.pivot(
                index="FYE",
                columns="Region",
                values="Peak_Daily_TJ",
            ).round(1).to_string()
        )

    print("\n=== Constraint violations against maximum RHS ===")

    max_rhs_summary = (
        violations[violations["Violation_Max_RHS"]]
        .groupby(["Result_Set", "Zone"])
        .agg(
            Violating_Days=("Violation_Max_RHS", "sum"),
            Max_Exceedance_TJ=("Exceedance_Max_RHS_TJ", "max"),
            Mean_Exceedance_TJ=("Exceedance_Max_RHS_TJ", "mean"),
        )
    )

    if max_rhs_summary.empty:
        print("No violations against maximum RHS found.")
    else:
        print(max_rhs_summary.round(1).to_string())


    #     print("\n=== Capacity factor by station and FYE ===")

    # for result_set in UNIT_COLS:
    #     subset = station_fye_cf[station_fye_cf["Result_Set"] == result_set]

    #     print(f"\n--- Result Set {result_set} ---")

    #     print(
    #         subset.pivot(
    #             index="FYE",
    #             columns="Name",
    #             values="Capacity_Factor_Percent",
    #         )
    #         .round(1)
    #         .to_string()
    #     )

    # print("\n=== Capacity factor by region and FYE ===")

    # for result_set in UNIT_COLS:
    #     subset = region_fye_cf[
    #         region_fye_cf["Result_Set"] == result_set
    #     ]

    #     print(f"\n--- Result Set {result_set} ---")

    #     print(
    #         subset.pivot(
    #             index="FYE",
    #             columns="Region",
    #             values="Capacity_Factor_Percent",
    #         )
    #         .round(1)
    #         .to_string()
    #     )


if __name__ == "__main__":
    main()
