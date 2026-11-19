"""Compare AEMO gas-constraint RHS traces across reference years.

Place this script beside the folder defined by LIMITS_DIR_NAME and run it.
It scans POE50 GPG limit CSVs, infers gas zone and reference year from each
filename, and creates daily and monthly comparison plots by gas zone and
projection financial year.
"""

from pathlib import Path
import calendar
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
LIMITS_DIR_NAME = "2025 gas fuel limitations data"
LIMITS_DIR = BASE / LIMITS_DIR_NAME
OUTPUT_DIR = BASE / "rhs_reference_year_analysis"
POE = "POE50"

# Keep consistent with the earlier analysis. Set either to None to use all dates.
RUN_START = pd.Timestamp("2027-07-01")
RUN_END = pd.Timestamp("2031-06-30")

# Expected example:
# GPG_Limit_STEP_CHANGE_Melbourne_GPG_Limit_TJ_2011_POE50.csv
FILE_RE = re.compile(
    r"^GPG_Limit_STEP_CHANGE_(?P<zone>.+?)_GPG_Limit_TJ_"
    r"(?P<reference_year>\d{4})_(?P<poe>POE\d+)\.csv$",
    flags=re.IGNORECASE,
)


def financial_year_ending(dates: pd.Series) -> pd.Series:
    return dates.dt.year + (dates.dt.month >= 7).astype(int)


def safe_name(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_")


def discover_files() -> list[tuple[Path, str, int]]:
    if not LIMITS_DIR.exists():
        raise FileNotFoundError(f"Gas limitations folder not found: {LIMITS_DIR}")

    found = []
    ignored = []

    for path in sorted(LIMITS_DIR.glob("*.csv")):
        match = FILE_RE.match(path.name)
        if not match:
            continue
        if match.group("poe").upper() != POE.upper():
            continue

        found.append(
            (path, match.group("zone"), int(match.group("reference_year")))
        )

    if not found:
        examples = "\n".join(p.name for p in sorted(LIMITS_DIR.glob("*.csv"))[:20])
        raise FileNotFoundError(
            f"No {POE} gas RHS files matching the expected naming convention were "
            f"found in {LIMITS_DIR}.\n\nFirst CSV filenames found:\n{examples}"
        )

    return found


def load_rhs_file(path: Path, zone: str, reference_year: int) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"Year", "Month", "Day", "Value"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"{path.name!r} is missing columns: {sorted(missing)}")

    df = df.copy()
    df["Date"] = pd.to_datetime(
        dict(year=df["Year"], month=df["Month"], day=df["Day"]),
        errors="raise",
    )
    df["RHS_TJ"] = pd.to_numeric(df["Value"], errors="raise")

    if RUN_START is not None:
        df = df[df["Date"] >= RUN_START]
    if RUN_END is not None:
        df = df[df["Date"] <= RUN_END]

    duplicate_dates = df["Date"].duplicated(keep=False)
    if duplicate_dates.any():
        duplicates = df.loc[duplicate_dates, "Date"].dt.strftime("%Y-%m-%d").tolist()
        raise ValueError(f"Duplicate dates in {path.name!r}: {duplicates}")

    df["Zone"] = zone
    df["Reference_Year"] = reference_year
    df["FYE"] = financial_year_ending(df["Date"])
    df["Month"] = df["Date"].dt.month
    df["Day"] = df["Date"].dt.day
    df["Month_Day"] = df["Date"].dt.strftime("%m-%d")
    df["Source_File"] = path.name

    return df[
        [
            "Zone",
            "Reference_Year",
            "Date",
            "FYE",
            "Month",
            "Day",
            "Month_Day",
            "RHS_TJ",
            "Source_File",
        ]
    ]


def load_all_rhs() -> pd.DataFrame:
    frames = [
        load_rhs_file(path, zone, reference_year)
        for path, zone, reference_year in discover_files()
    ]
    data = pd.concat(frames, ignore_index=True)

    duplicate_keys = data.duplicated(
        subset=["Zone", "Reference_Year", "Date"], keep=False
    )
    if duplicate_keys.any():
        duplicates = data.loc[
            duplicate_keys, ["Zone", "Reference_Year", "Date", "Source_File"]
        ].sort_values(["Zone", "Reference_Year", "Date"])
        raise ValueError(
            "Multiple files supply the same Zone / Reference Year / Date:\n"
            + duplicates.to_string(index=False)
        )

    return data.sort_values(["Zone", "FYE", "Reference_Year", "Date"])


def make_daily_overlay_plots(data: pd.DataFrame) -> None:
    out_dir = OUTPUT_DIR / "daily_overlay"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Use a synthetic financial-year axis: Jul-Dec in 2000, Jan-Jun in 2001.
    # This preserves the true Jul -> Jun order and prevents Matplotlib from
    # drawing an artificial line from December back to January.
    for (zone, fye), group in data.groupby(["Zone", "FYE"], sort=True):
        fig, ax = plt.subplots(figsize=(16, 8))

        for ref_year, ref_data in group.groupby("Reference_Year", sort=True):
            ref_data = ref_data.sort_values("Date").copy()
            ref_data["Plot_Year"] = np.where(ref_data["Month"] >= 7, 2000, 2001)
            ref_data["Plot_Date"] = pd.to_datetime(
                {
                    "year": ref_data["Plot_Year"],
                    "month": ref_data["Month"],
                    "day": ref_data["Day"],
                },
                errors="coerce",
            )
            ref_data = ref_data.dropna(subset=["Plot_Date"]).sort_values("Plot_Date")
            ax.plot(
                ref_data["Plot_Date"],
                ref_data["RHS_TJ"],
                linewidth=1.0,
                alpha=0.65,
                label=str(ref_year),
            )

        fy_months = list(range(7, 13)) + list(range(1, 7))
        month_starts = [
            pd.Timestamp(2000 if month >= 7 else 2001, month, 1)
            for month in fy_months
        ]
        ax.set_xticks(month_starts)
        ax.set_xticklabels([calendar.month_abbr[m] for m in fy_months])
        ax.set_xlim(pd.Timestamp(2000, 7, 1), pd.Timestamp(2001, 6, 30))
        ax.set_title(f"Daily Gas Constraint RHS by Reference Year: {zone} - FY{fye}")
        ax.set_xlabel("Month")
        ax.set_ylabel("RHS (TJ/day)")
        ax.grid(True, alpha=0.25)
        ax.legend(title="Reference year", loc="best", ncol=2)
        ax.margins(x=0)
        fig.tight_layout()
        fig.savefig(
            out_dir / f"{safe_name(zone)}_FY{fye}_daily_rhs_by_reference_year.png",
            dpi=200,
            bbox_inches="tight",
        )
        plt.close(fig)

def calculate_monthly(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    monthly = (
        data.groupby(["Zone", "FYE", "Reference_Year", "Month"], as_index=False)[
            "RHS_TJ"
        ]
        .mean()
        .rename(columns={"RHS_TJ": "Mean_RHS_TJ"})
    )

    monthly_range = (
        monthly.groupby(["Zone", "FYE", "Month"], as_index=False)
        .agg(
            Reference_Year_Count=("Reference_Year", "nunique"),
            Mean_RHS_TJ=("Mean_RHS_TJ", "mean"),
            Min_RHS_TJ=("Mean_RHS_TJ", "min"),
            Max_RHS_TJ=("Mean_RHS_TJ", "max"),
        )
    )

    return monthly, monthly_range


def make_monthly_overlay_plots(monthly: pd.DataFrame) -> None:
    out_dir = OUTPUT_DIR / "monthly_overlay"
    out_dir.mkdir(parents=True, exist_ok=True)

    for (zone, fye), group in monthly.groupby(["Zone", "FYE"], sort=True):
        fig, ax = plt.subplots(figsize=(14, 8))

        for ref_year, ref_data in group.groupby("Reference_Year", sort=True):
            ref_data = ref_data.sort_values("Month")
            ax.plot(
                ref_data["Month"],
                ref_data["Mean_RHS_TJ"],
                marker="o",
                markersize=3,
                linewidth=1.0,
                alpha=0.65,
                label=str(ref_year),
            )

        cross_ref_mean = (
            group.groupby("Month", as_index=False)["Mean_RHS_TJ"].mean()
        )
        ax.plot(
            cross_ref_mean["Month"],
            cross_ref_mean["Mean_RHS_TJ"],
            color="black",
            marker="o",
            linewidth=2.8,
            label="Reference-year mean",
            zorder=10,
        )

        ax.set_xticks(range(1, 13))
        ax.set_xticklabels([calendar.month_abbr[m] for m in range(1, 13)])
        ax.set_title(f"Monthly Mean Gas Constraint RHS: {zone} - FY{fye}")
        ax.set_xlabel("Month")
        ax.set_ylabel("Mean RHS (TJ/day)")
        ax.grid(True, alpha=0.25)
        ax.legend(title="Reference year", loc="best", ncol=2)
        fig.tight_layout()
        fig.savefig(
            out_dir / f"{safe_name(zone)}_FY{fye}_monthly_rhs_by_reference_year.png",
            dpi=200,
            bbox_inches="tight",
        )
        plt.close(fig)


def make_monthly_range_plots(monthly_range: pd.DataFrame) -> None:
    out_dir = OUTPUT_DIR / "monthly_range"
    out_dir.mkdir(parents=True, exist_ok=True)

    for (zone, fye), group in monthly_range.groupby(["Zone", "FYE"], sort=True):
        group = group.sort_values("Month")
        x = group["Month"].to_numpy(dtype=float)
        mean = group["Mean_RHS_TJ"].to_numpy(dtype=float)
        low = group["Min_RHS_TJ"].to_numpy(dtype=float)
        high = group["Max_RHS_TJ"].to_numpy(dtype=float)

        fig, ax = plt.subplots(figsize=(14, 8))
        ax.fill_between(
            x,
            low,
            high,
            alpha=0.25,
            color="C0",
            label="Reference-year min-max",
        )
        ax.plot(
            x,
            mean,
            color="black",
            marker="o",
            linewidth=2.2,
            label="Reference-year mean",
        )
        ax.plot(x, low, color="C0", linewidth=0.8, alpha=0.8)
        ax.plot(x, high, color="C0", linewidth=0.8, alpha=0.8)

        ax.set_xticks(range(1, 13))
        ax.set_xticklabels([calendar.month_abbr[m] for m in range(1, 13)])
        ax.set_title(f"Monthly Reference-Year Range of Gas Constraint RHS: {zone} - FY{fye}")
        ax.set_xlabel("Month")
        ax.set_ylabel("Mean RHS (TJ/day)")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(
            out_dir / f"{safe_name(zone)}_FY{fye}_monthly_rhs_reference_year_range.png",
            dpi=200,
            bbox_inches="tight",
        )
        plt.close(fig)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data = load_all_rhs()
    monthly, monthly_range = calculate_monthly(data)

    data.to_csv(OUTPUT_DIR / "rhs_daily_all_reference_years.csv", index=False)
    monthly.to_csv(OUTPUT_DIR / "rhs_reference_year_monthly_means.csv", index=False)
    monthly_range.to_csv(OUTPUT_DIR / "rhs_reference_year_monthly_range.csv", index=False)

    make_daily_overlay_plots(data)
    make_monthly_overlay_plots(monthly)
    make_monthly_range_plots(monthly_range)

    print(f"Loaded {len(data):,} daily RHS records.")
    print(f"Zones: {', '.join(sorted(data['Zone'].unique()))}")
    print(
        "Reference years: "
        + ", ".join(str(x) for x in sorted(data["Reference_Year"].unique()))
    )
    print(f"Outputs saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
