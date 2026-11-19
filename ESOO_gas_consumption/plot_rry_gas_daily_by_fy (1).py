"""Daily gas constraint RHS by reference year: one chart per zone per financial year.

Run:
    python plot_rry_gas_daily_by_fy.py
Charts go to OUT_DIR/<zone>/<Zone>_FY<year>_daily_rhs_by_reference_year.png
(previous PNGs in OUT_DIR are deleted first).

Each chart: every ORIGINAL single-reference-year trace for the zone (from
"2025 gas fuel limitations data"), Jul-Jun of that FY, one line per reference
year. Optional black overlay of the ISP 2026 RRY trace (off by default).
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

BASE = Path(__file__).resolve().parent
TRACE_DIR = BASE / "2025 gas fuel limitations data"
RRY_DIR = BASE / "ISP 2026 RRY gas fuel limitations"
OUT_DIR = BASE / "rry_gas_daily_by_fy_plots"

POE = "POE10"
FY_START, FY_END = 2026, 2046        # FY ending; originals run Jan 2025 - Dec 2045 (FY2046 = Jul-Dec only)
ZONES: list[str] = []                # e.g. ["melbourne", "southern"]; empty = all
SHOW_RRY = False                     # True = overlay the RRY trace in black
DPI = 110

SINGLE_PATTERN = re.compile(
    r"^GPG_Limit_STEP_CHANGE_(?P<zone>.+?)_GPG_Limit_TJ_(?P<ry>\d{4})_(?P<poe>POE\d+)\.csv$", re.I)
RRY_PATTERN = re.compile(
    r"^GPG_Limit_STEP_CHANGE_(?P<zone>.+?)_GPG_Limit_TJ_(?P<code>\d+)_(?P<poe>POE\d+)\.csv$", re.I)


def zone_key(name):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"^S__", "", name, flags=re.I).lower())


def read(path):
    df = pd.read_csv(path)
    missing = {"Year", "Month", "Day", "Value"} - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    df["Date"] = pd.to_datetime(dict(year=df.Year, month=df.Month, day=df.Day), errors="raise")
    df = df.drop_duplicates("Date", keep="first")
    return df.set_index("Date").Value.sort_index()


def load(folder, pattern, is_rry):
    if not folder.is_dir():
        raise FileNotFoundError(f"Missing folder: {folder}")
    out = {}
    for path in sorted(folder.glob("*.csv")):
        m = pattern.fullmatch(path.name)
        if not m or m["poe"].upper() != POE:
            continue
        key = zone_key(m["zone"])
        name = re.sub(r"^S__", "", m["zone"], flags=re.I)
        if is_rry:
            if key in out:
                raise ValueError(f"Multiple RRY {POE} files for {key}")
            out[key] = (name, read(path))
        else:
            out.setdefault(key, (name, {}))[1][int(m["ry"])] = read(path)
    if not out:
        raise FileNotFoundError(f"No {POE} gas limit files matched in {folder}")
    return out


def main():
    singles = load(TRACE_DIR, SINGLE_PATTERN, False)
    rry = load(RRY_DIR, RRY_PATTERN, True) if SHOW_RRY else {}
    zones = [zone_key(z) for z in ZONES] or sorted(singles)
    unknown = set(zones) - set(singles)
    if unknown:
        raise ValueError(f"ZONES not found: {sorted(unknown)}; available: {sorted(singles)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.rglob("*.png"):
        old.unlink()

    cmap = plt.get_cmap("tab10")
    count, skipped = 0, []
    for key in zones:
        name, traces = singles[key]
        folder = OUT_DIR / key
        folder.mkdir(exist_ok=True)
        for fy in range(FY_START, FY_END + 1):
            start, end = pd.Timestamp(fy - 1, 7, 1), pd.Timestamp(fy, 6, 30)
            data = {ry: s.loc[start:end] for ry, s in sorted(traces.items())}
            data = {ry: s for ry, s in data.items() if not s.empty}
            if not data:
                skipped.append(f"{name} FY{fy}")
                continue
            fig, ax = plt.subplots(figsize=(16, 8))
            for i, (ry, s) in enumerate(data.items()):
                ax.plot(s.index, s.values, lw=1, alpha=.7, color=cmap(i % 10), label=str(ry))
            if SHOW_RRY and key in rry:
                r = rry[key][1].loc[start:end]
                if not r.empty:
                    ax.plot(r.index, r.values, color="k", lw=1.6, label="RRY")
            ax.set_xlim(start, end)
            ax.xaxis.set_major_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
            ax.set_xlabel("Month")
            ax.set_ylabel("RHS (TJ/day)")
            ax.set_title(f"Daily Gas Constraint RHS by Reference Year: {name} - FY{fy}")
            ax.grid(alpha=.3)
            ax.legend(title="Reference year", loc="upper left", ncol=2, fontsize=9)
            fig.tight_layout()
            fig.savefig(folder / f"{name.replace(' ', '_')}_FY{fy}_daily_rhs_by_reference_year.png", dpi=DPI)
            plt.close(fig)
            count += 1
        print(f"{name}: done")
    print(f"\n{count} charts written to {OUT_DIR}")
    if skipped:
        print(f"No data (skipped): {', '.join(skipped)}")


if __name__ == "__main__":
    main()
