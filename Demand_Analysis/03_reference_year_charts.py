"""
Step 3 (reference years compared to each other): chart how demand outcomes vary
by reference year, for one dataset.

Reads the cuts from 02_reference_year_cuts.py and writes PNGs to
outputs/<DATASET>/reference_years/charts/.

Charts:
    1_energy_peak_by_fy   - FY energy and peak over the horizon, one line per
                            reference year
    2_spread_by_fy        - median with min-max band across reference years,
                            plus the spread as a % of median
    3_seasonal_profile    - average daily profile by season, one line per
                            reference year                      [per FY]
    4_daily_profile       - average daily profile, plus the two reference
                            years whose shapes diverge most     [per FY]
    4b_seasonal_contrast  - the most divergent pair, found separately within
                            each season                         [per FY]
    4c_raw_daily_difference - raw MW difference between the two reference years
                            with the largest raw-profile RMSE  [per FY]
    5_ranked              - reference years ranked by peak and by energy
                                                                [per FY]
    6_monthly_heatmap     - monthly energy, reference year vs month
                                                                [per FY]

The script loops through every REGION and SUBREGION area available for the
configured dataset, POE and trace type. Charts 1 and 2 span the whole horizon
for each area. Charts 3-6 describe a single financial year, so one set is
written per FY listed in FY_SELECT. Leave FY_SELECT as None to produce every FY
available.

Run: python 03_reference_year_charts.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import colors
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd

from demand_lib.paths import output_dir

# =============================================================================
# CONFIG
# =============================================================================

# Must match the DATASET used in 02_reference_year_cuts.py.
DATASET = "ESOO_2026_Central"

CUTS_DIR = output_dir(DATASET, "reference_years/cuts")
CHART_DIR = output_dir(DATASET, "reference_years/charts")

# The script automatically loops through every REGION and SUBREGION area.
# LEVEL and AREA are set internally for each loop iteration and are retained as
# globals because the chart titles and output helpers use them.
LEVEL = None
AREA = None
POE = 50
TRACE_TYPE = "OPSO_MODELLING"

# Financial years for the per-FY charts (3, 4, 5, 6).
#   None          -> every FY available
#   [2035, 2040]  -> just those two
#   range(2030, 2041) -> FY2030 to FY2040 inclusive
FY_SELECT = [2027,2030,2035,2045,2055]


# FY range for the horizon charts (1 and 2) only. None = all.
FY_RANGE = None            # e.g. (2030, 2045)

# Put each FY's charts in its own subfolder. False = one flat folder with the
# FY in each filename.
SUBFOLDER_PER_FY = True

# Use one y-axis scale across every FY so charts are directly comparable.
# Off by default: a wide horizon squashes each individual profile into a
# fraction of the axis and hides the shape.
SHARED_AXIS_LIMITS = False

# How to find the two most different reference years.
#   "shape"  - normalise each profile by its own daily mean first, so the
#              comparison is about the SHAPE of the day only
#   "level"  - compare raw MW, which is dominated by which reference year is
#              simply hotter or milder overall
CONTRAST_BASIS = "level"

DPI = 150

# =============================================================================
# HELPERS
# =============================================================================

SEASON_ORDER = ["Summer", "Autumn", "Winter", "Spring"]

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# FY runs Jul -> Jun, so order months accordingly for the heatmap.
FY_MONTH_ORDER = [7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6]
FY_MONTH_LABELS = [MONTH_LABELS[m - 1] for m in FY_MONTH_ORDER]


def load(name):
    """Load a cut and retain every region/subregion for the configured case."""

    df = pd.read_parquet(CUTS_DIR / f"{name}.parquet")

    mask = (
        (df["poe"] == POE)
        & (df["trace_type"] == TRACE_TYPE)
        & (df["dataset"] == DATASET)
    )

    df = df[mask].copy()

    if df.empty:
        raise ValueError(
            f"No rows in {name} for POE{POE}/{TRACE_TYPE}/{DATASET}."
        )

    return df


def select_area(df, level, area):
    """Return one level/area slice from a loaded cut."""

    return df[(df["level"] == level) & (df["area"] == area)].copy()


def resolve_fys(fy):
    """
    Work out which financial years to produce per-FY charts for.

    FY_SELECT = None means every FY present in the data.
    """

    available = sorted(int(v) for v in fy["fy"].unique())

    if FY_SELECT is None:
        return available

    wanted = [int(v) for v in FY_SELECT]

    selected = sorted(v for v in set(wanted) if v in available)
    missing = sorted(v for v in set(wanted) if v not in available)

    if missing:
        print(f"  FYs not available for {LEVEL}/{AREA}, skipped: {missing}")

    return selected


def profile_matrix(df):
    """reference_year x interval matrix of avg_mw."""

    return df.pivot_table(
        index="reference_year", columns="interval", values="avg_mw"
    ).sort_index(axis=1)


def most_different_pair(df, basis=None):
    """
    Find the two reference years whose daily profiles differ most.

    Distance is RMSE across the 48 intervals:

        rmse = sqrt(mean((a - b) ** 2))

    RMSE (equivalently the sum of SQUARED residuals) is the right metric
    here. A plain sum of residuals lets positive and negative differences
    cancel, so two profiles that diverge sharply in opposite directions at
    different times of day would score near zero.

    With basis="shape" each profile is divided by its own daily mean before
    the comparison, giving a dimensionless index that averages 1.0. Without
    that, the widest gap is almost always just the hottest reference year
    against the mildest - a level difference, not a shape difference.

    Returns (year_a, year_b, rmse, matrix) or None if there are fewer than
    two reference years. The matrix returned is the one the distance was
    measured on, so it is normalised when basis="shape".
    """

    basis = basis or CONTRAST_BASIS

    m = profile_matrix(df)

    if len(m) < 2:
        return None

    if basis == "shape":
        m = m.div(m.mean(axis=1), axis=0)

    years = list(m.index)
    values = m.to_numpy()

    # pairwise RMSE over every combination
    diff = values[:, None, :] - values[None, :, :]
    rmse = np.sqrt((diff ** 2).mean(axis=2))

    # ignore the diagonal (a year against itself)
    np.fill_diagonal(rmse, -1)

    i, j = np.unravel_index(np.argmax(rmse), rmse.shape)

    return years[i], years[j], rmse[i, j], m


def contrast_labels():
    """Axis labels that match the configured basis."""

    if CONTRAST_BASIS == "shape":
        return "Demand / daily mean", "Shape index"

    return "MW", "Demand (MW)"


def plot_contrast(ax, df, title_prefix=""):
    """
    Draw the two most different reference years and shade the gap between
    them. Returns the RMSE, or None if the panel could not be drawn.
    """

    result = most_different_pair(df)

    if result is None:
        ax.text(0.5, 0.5, "Need at least two reference years",
                ha="center", va="center", transform=ax.transAxes)
        return None

    ry_a, ry_b, rmse, m = result

    a = m.loc[ry_a]
    b = m.loc[ry_b]

    # Order by peak height, not mean: normalised profiles all have a mean of
    # 1.0, so ordering on the mean would be arbitrary and the colours would
    # flip between seasons. Red is always the peakier of the two.
    if a.max() < b.max():
        ry_a, ry_b = ry_b, ry_a
        a, b = b, a

    x = m.columns.to_numpy()

    ax.fill_between(x, a.to_numpy(), b.to_numpy(),
                    color="tab:orange", alpha=0.25, label="Difference")

    ax.plot(x, a.to_numpy(), color="tab:red", lw=1.8, label=str(ry_a))
    ax.plot(x, b.to_numpy(), color="tab:blue", lw=1.8, label=str(ry_b))

    unit = "" if CONTRAST_BASIS == "shape" else " MW"
    fmt = f"{rmse:.3f}" if CONTRAST_BASIS == "shape" else f"{rmse:,.0f}"

    ax.set_title(f"{title_prefix}{ry_a} vs {ry_b}  (RMSE {fmt}{unit})")

    return rmse


def ref_year_colours(ref_years):
    """Ordered colour map so reference years read as a sequence, not a jumble."""

    norm = colors.Normalize(vmin=min(ref_years), vmax=max(ref_years))
    cmap = matplotlib.colormaps["viridis"]

    return {ry: cmap(norm(ry)) for ry in ref_years}


def interval_ticks(ax):
    """Label interval 1-48 as clock time (period ending)."""

    ticks = [1, 9, 17, 25, 33, 41, 48]
    labels = ["00:30", "04:30", "08:30", "12:30", "16:30", "20:30", "00:00"]

    ax.set_xticks(ticks)
    ax.set_xticklabels(labels)
    ax.set_xlim(1, 48)


def fy_axis(ax):
    """Financial years are integers - stop matplotlib showing 2035.5."""
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlabel("Financial year")


def safe_path_component(value):
    """Make a stable Windows-safe folder/file component."""

    value = str(value).strip()
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value)


def finish(fig, name, fy=None):
    """Save a uniquely named chart under LEVEL/AREA, optionally under FY."""

    fig.tight_layout(rect=[0, 0, 1, 0.95])

    level_name = safe_path_component(LEVEL)
    area_name = safe_path_component(AREA)
    area_root = CHART_DIR / level_name / area_name
    unique_name = f"{level_name}_{area_name}_{name}"

    if fy is None:
        folder = area_root
        filename = f"{unique_name}.png"
    elif SUBFOLDER_PER_FY:
        folder = area_root / f"FY{fy}"
        filename = f"{unique_name}_FY{fy}.png"
    else:
        folder = area_root
        filename = f"{unique_name}_FY{fy}.png"

    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename

    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)

    return path


def title_suffix():
    return f"{AREA} | {DATASET} | POE{POE} | {TRACE_TYPE}"


# =============================================================================
# 1. ENERGY AND PEAK OVER THE HORIZON
# =============================================================================


def chart_energy_peak(fy):

    ref_years = sorted(fy["reference_year"].unique())
    cols = ref_year_colours(ref_years)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    for ry in ref_years:
        d = fy[fy["reference_year"] == ry].sort_values("fy")

        axes[0].plot(d["fy"], d["energy_gwh"], color=cols[ry],
                     lw=1.4, label=str(ry))
        axes[1].plot(d["fy"], d["max_mw"], color=cols[ry],
                     lw=1.4, label=str(ry))

    axes[0].set_title("Annual energy")
    axes[0].set_ylabel("GWh")

    axes[1].set_title("Peak demand")
    axes[1].set_ylabel("MW")

    for ax in axes:
        fy_axis(ax)
        ax.grid(alpha=0.3)

    axes[1].legend(title="Reference year", fontsize=8,
                   ncol=2, loc="upper left")

    fig.suptitle(f"Demand outcomes by reference year - {title_suffix()}",
                 fontsize=13)

    return finish(fig, "1_energy_peak_by_fy")


# =============================================================================
# 2. SPREAD ACROSS REFERENCE YEARS
# =============================================================================


def chart_spread(fy):
    """
    The question this answers: how much does the choice of weather year
    actually move the answer, and is that sensitivity growing over time.
    """

    g = fy.groupby("fy")

    stats = pd.DataFrame({
        "energy_med": g["energy_gwh"].median(),
        "energy_min": g["energy_gwh"].min(),
        "energy_max": g["energy_gwh"].max(),
        "peak_med": g["max_mw"].median(),
        "peak_min": g["max_mw"].min(),
        "peak_max": g["max_mw"].max(),
    }).reset_index()

    stats["energy_spread_pct"] = (
        (stats["energy_max"] - stats["energy_min"]) / stats["energy_med"] * 100
    )
    stats["peak_spread_pct"] = (
        (stats["peak_max"] - stats["peak_min"]) / stats["peak_med"] * 100
    )

    fig, axes = plt.subplots(1, 3, figsize=(17, 5))

    axes[0].fill_between(stats["fy"], stats["energy_min"], stats["energy_max"],
                         alpha=0.25, color="tab:blue", label="Min-max range")
    axes[0].plot(stats["fy"], stats["energy_med"], color="tab:blue",
                 lw=2, label="Median")
    axes[0].set_title("Annual energy")
    axes[0].set_ylabel("GWh")

    axes[1].fill_between(stats["fy"], stats["peak_min"], stats["peak_max"],
                         alpha=0.25, color="tab:red", label="Min-max range")
    axes[1].plot(stats["fy"], stats["peak_med"], color="tab:red",
                 lw=2, label="Median")
    axes[1].set_title("Peak demand")
    axes[1].set_ylabel("MW")

    axes[2].plot(stats["fy"], stats["energy_spread_pct"],
                 color="tab:blue", lw=1.8, label="Energy")
    axes[2].plot(stats["fy"], stats["peak_spread_pct"],
                 color="tab:red", lw=1.8, label="Peak")
    axes[2].set_title("Reference year spread")
    axes[2].set_ylabel("Max - min, % of median")

    for ax in axes:
        fy_axis(ax)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=9)

    fig.suptitle(f"Sensitivity to reference year - {title_suffix()}",
                 fontsize=13)

    return finish(fig, "2_spread_by_fy")


# =============================================================================
# 3. SEASONAL AVERAGE DAILY PROFILE
# =============================================================================


def chart_seasonal_profile(prof, focus_fy, ylim=None):

    d = prof[prof["fy"] == focus_fy]

    if d.empty:
        return None

    ref_years = sorted(d["reference_year"].unique())
    cols = ref_year_colours(ref_years)

    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True, sharey=True)

    for ax, season in zip(axes.ravel(), SEASON_ORDER):

        sd = d[d["season"] == season]

        for ry in ref_years:
            r = sd[sd["reference_year"] == ry].sort_values("interval")
            ax.plot(r["interval"], r["avg_mw"], color=cols[ry],
                    lw=1.3, label=str(ry))

        ax.set_title(season)
        ax.grid(alpha=0.3)
        interval_ticks(ax)

    if ylim:
        axes[0, 0].set_ylim(*ylim)

    for ax in axes[:, 0]:
        ax.set_ylabel("Average demand (MW)")

    axes[0, 1].legend(title="Reference year", fontsize=8, ncol=2)

    fig.suptitle(
        f"Seasonal average daily profile, FY{focus_fy} - {title_suffix()}",
        fontsize=13,
    )

    return finish(fig, "3_seasonal_profile", fy=focus_fy)


# =============================================================================
# 4. WHOLE YEAR AVERAGE DAILY PROFILE
# =============================================================================


def chart_daily_profile(daily, focus_fy, ylim=None):

    d = daily[daily["fy"] == focus_fy]

    if d.empty:
        return None

    ref_years = sorted(d["reference_year"].unique())
    cols = ref_year_colours(ref_years)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    for ry in ref_years:
        r = d[d["reference_year"] == ry].sort_values("interval")
        axes[0].plot(r["interval"], r["avg_mw"], color=cols[ry],
                     lw=1.4, label=str(ry))

    axes[0].set_title("Average daily profile")
    axes[0].set_ylabel("MW")
    axes[0].legend(title="Reference year", fontsize=8, ncol=2)

    if ylim:
        axes[0].set_ylim(*ylim)

    # the two reference years whose shapes diverge most
    plot_contrast(axes[1], d, title_prefix="Most different: ")

    ylabel, _ = contrast_labels()
    axes[1].set_ylabel(ylabel)
    axes[1].legend(fontsize=9)

    for ax in axes:
        ax.set_xlabel("Interval (period ending)")
        ax.grid(alpha=0.3)
        interval_ticks(ax)

    fig.suptitle(f"Daily shape, FY{focus_fy} - {title_suffix()}", fontsize=13)

    return finish(fig, "4_daily_profile", fy=focus_fy)


# =============================================================================
# 4c. RAW MW DIFFERENCE BETWEEN MOST DIFFERENT REFERENCE YEARS
# =============================================================================

def chart_raw_daily_difference(daily, focus_fy):
    """
    Find the pair with the largest RMSE using unnormalised average MW profiles.

    Panel 1 shows the two raw average profiles. Panel 2 shows the signed raw
    interval-by-interval difference in MW. Positive values mean the red
    reference year is higher; negative values mean the blue year is higher.
    """

    d = daily[daily["fy"] == focus_fy]
    if d.empty:
        return None

    result = most_different_pair(d, basis="level")
    if result is None:
        return None

    ry_a, ry_b, rmse, matrix = result
    a = matrix.loc[ry_a]
    b = matrix.loc[ry_b]

    # Keep colour ordering consistent: red is the profile with the higher peak.
    if a.max() < b.max():
        ry_a, ry_b = ry_b, ry_a
        a, b = b, a

    x = matrix.columns.to_numpy()
    raw_difference = a.to_numpy() - b.to_numpy()

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharex=True)

    axes[0].plot(x, a.to_numpy(), color="tab:red", lw=1.8, label=str(ry_a))
    axes[0].plot(x, b.to_numpy(), color="tab:blue", lw=1.8, label=str(ry_b))
    axes[0].fill_between(
        x, a.to_numpy(), b.to_numpy(), color="tab:orange", alpha=0.25
    )
    axes[0].set_title(
        f"Most different raw profiles: {ry_a} vs {ry_b} "
        f"(RMSE {rmse:,.0f} MW)"
    )
    axes[0].set_ylabel("Average demand (MW)")
    axes[0].legend(title="Reference year", fontsize=9)

    colours = np.where(raw_difference >= 0, "tab:red", "tab:blue")
    axes[1].bar(x, raw_difference, color=colours, width=0.85, alpha=0.8)
    axes[1].axhline(0, color="black", lw=0.9)
    axes[1].set_title(f"Raw difference: {ry_a} minus {ry_b}")
    axes[1].set_ylabel("Difference in average demand (MW)")

    for ax in axes:
        ax.set_xlabel("Interval (period ending)")
        ax.grid(alpha=0.3)
        interval_ticks(ax)

    fig.suptitle(
        f"Raw average-shape difference, FY{focus_fy} - {title_suffix()}",
        fontsize=13,
    )

    return finish(fig, "4c_raw_daily_difference", fy=focus_fy)


# =============================================================================
# 4b. SEASONAL SHAPE CONTRAST
# =============================================================================


def chart_seasonal_contrast(prof, focus_fy):
    """
    Same idea as panel 2 of chart 4, but per season. The pair that diverges
    most is found independently within each season, so summer and winter can
    (and often will) return different reference years.
    """

    d = prof[prof["fy"] == focus_fy]

    if d.empty:
        return None

    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True)

    ylabel, _ = contrast_labels()

    for ax, season in zip(axes.ravel(), SEASON_ORDER):

        sd = d[d["season"] == season]

        if sd.empty:
            ax.text(0.5, 0.5, f"No {season} data",
                    ha="center", va="center", transform=ax.transAxes)
            continue

        plot_contrast(ax, sd, title_prefix=f"{season}: ")

        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        interval_ticks(ax)

    for ax in axes[:, 0]:
        ax.set_ylabel(ylabel)

    for ax in axes[1, :]:
        ax.set_xlabel("Interval (period ending)")

    basis = ("shape, normalised by daily mean"
             if CONTRAST_BASIS == "shape" else "absolute MW")

    fig.suptitle(
        f"Most divergent reference years by season, FY{focus_fy} - "
        f"{title_suffix()}  [{basis}]",
        fontsize=13,
    )

    return finish(fig, "4b_seasonal_contrast", fy=focus_fy)


# =============================================================================
# 5. RANKED REFERENCE YEARS
# =============================================================================


def chart_ranked(fy, focus_fy):

    d = fy[fy["fy"] == focus_fy].copy()

    if d.empty:
        return None

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    for ax, col, label, colour in [
        (axes[0], "max_mw", "Peak demand (MW)", "tab:red"),
        (axes[1], "energy_gwh", "Annual energy (GWh)", "tab:blue"),
    ]:
        s = d.sort_values(col)
        pos = np.arange(len(s))

        ax.barh(pos, s[col], color=colour, alpha=0.8)
        ax.set_yticks(pos)
        ax.set_yticklabels(s["reference_year"].astype(str))
        ax.set_xlabel(label)
        ax.set_ylabel("Reference year")
        ax.grid(alpha=0.3, axis="x")

        med = s[col].median()
        ax.axvline(med, color="black", ls="--", lw=1, label="Median")
        ax.legend(fontsize=9, loc="lower right")

        # keep the bars readable rather than starting at zero
        ax.set_xlim(s[col].min() * 0.97, s[col].max() * 1.01)

    fig.suptitle(
        f"Reference years ranked, FY{focus_fy} - {title_suffix()}",
        fontsize=13,
    )

    return finish(fig, "5_ranked", fy=focus_fy)


# =============================================================================
# 6. MONTHLY HEATMAP
# =============================================================================


def chart_monthly_heatmap(monthly, focus_fy, clim=None):

    d = monthly[monthly["fy"] == focus_fy]

    if d.empty:
        return None

    pivot = (
        d.pivot_table(index="reference_year", columns="month",
                      values="energy_gwh")
        .reindex(columns=FY_MONTH_ORDER)
    )

    fig, ax = plt.subplots(figsize=(11, 5))

    kw = {}
    if clim:
        kw["vmin"], kw["vmax"] = clim

    im = ax.imshow(pivot.values, aspect="auto", cmap="YlOrRd", **kw)

    ax.set_xticks(range(12))
    ax.set_xticklabels(FY_MONTH_LABELS)

    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index.astype(str))

    ax.set_xlabel("Month")
    ax.set_ylabel("Reference year")

    fig.colorbar(im, ax=ax, label="Energy (GWh)")

    ax.set_title(
        f"Monthly energy by reference year, FY{focus_fy} - {title_suffix()}"
    )

    return finish(fig, "6_monthly_heatmap", fy=focus_fy)


# =============================================================================
# MAIN
# =============================================================================


def main():
    global LEVEL, AREA

    fy_all = load("fy_summary")
    daily_all = load("daily_profile")
    seasonal_all = load("seasonal_profile")
    monthly_all = load("monthly")

    area_keys = (
        fy_all[["level", "area"]]
        .drop_duplicates()
        .sort_values(["level", "area"])
        .itertuples(index=False, name=None)
    )
    area_keys = list(area_keys)

    print(f"Found {len(area_keys)} region/subregion areas")
    print(f"Output: {CHART_DIR}")
    print()

    total_written = 0
    skipped = []

    for level, area in area_keys:
        LEVEL = str(level)
        AREA = str(area)

        fy = select_area(fy_all, level, area)
        daily = select_area(daily_all, level, area)
        seasonal = select_area(seasonal_all, level, area)
        monthly = select_area(monthly_all, level, area)

        missing_cuts = [
            name for name, df in [
                ("daily_profile", daily),
                ("seasonal_profile", seasonal),
                ("monthly", monthly),
            ]
            if df.empty
        ]
        if missing_cuts:
            skipped.append((LEVEL, AREA, missing_cuts))
            print(f"Skipping {LEVEL}/{AREA}: missing {', '.join(missing_cuts)}")
            continue

        fy_horizon = fy
        if FY_RANGE is not None:
            lo, hi = FY_RANGE
            fy_horizon = fy[fy["fy"].between(lo, hi)]

        if fy_horizon.empty:
            print(f"Skipping {LEVEL}/{AREA}: FY_RANGE leaves no horizon data")
            continue

        focus_fys = resolve_fys(fy)
        if not focus_fys:
            print(f"Skipping {LEVEL}/{AREA}: none of FY_SELECT are available")
            continue

        n_ry = fy["reference_year"].nunique()

        print(
            f"{AREA} ({LEVEL}): {n_ry} reference years, "
            f"FY{int(fy['fy'].min())}-FY{int(fy['fy'].max())}"
        )

        if SHARED_AXIS_LIMITS:
            prof_ylim = (
                min(daily["avg_mw"].min(), seasonal["avg_mw"].min()) * 0.95,
                max(daily["avg_mw"].max(), seasonal["avg_mw"].max()) * 1.05,
            )
            heat_clim = (
                monthly["energy_gwh"].min(),
                monthly["energy_gwh"].max(),
            )
        else:
            prof_ylim = None
            heat_clim = None

        horizon_paths = [
            chart_energy_peak(fy_horizon),
            chart_spread(fy_horizon),
        ]
        total_written += len(horizon_paths)

        for f in focus_fys:
            paths = [
                chart_seasonal_profile(seasonal, f, ylim=prof_ylim),
                chart_daily_profile(daily, f, ylim=prof_ylim),
                chart_seasonal_contrast(seasonal, f),
                chart_raw_daily_difference(daily, f),
                chart_ranked(fy, f),
                chart_monthly_heatmap(monthly, f, clim=heat_clim),
            ]
            paths = [p for p in paths if p is not None]
            total_written += len(paths)
            print(f"  FY{f}: {len(paths)} per-FY charts")

        print()

    print(f"Done. Wrote {total_written} charts in {CHART_DIR}")

    if skipped:
        print("Skipped areas:")
        for level, area, missing in skipped:
            print(f"  {level}/{area}: missing {', '.join(missing)}")


if __name__ == "__main__":
    main()
