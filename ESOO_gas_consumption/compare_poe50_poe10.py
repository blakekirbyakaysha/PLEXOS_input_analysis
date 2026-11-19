"""Compare the original single-reference-year POE50 and POE10 gas limit traces.

Run (no arguments):
    python compare_poe50_poe10.py
Inputs : "2025 gas fuel limitations data" (GPG_Limit_STEP_CHANGE_<zone>_GPG_Limit_TJ_<RY>_<POE>.csv)
Outputs: poe_comparison/
    summary_by_zone.csv, summary_by_zone_ry.csv, summary_by_zone_fy.csv, missing_pairs.csv
    zone_overview/<zone>_overview.png      4 panels per zone (pooled over all RYs)
    zone_ry_monthly/<zone>_RY<ry>_monthly.png   monthly medians, POE50 vs POE10, per RY
    daily_fy/<zone>/<zone>_RY<ry>_FY<fy>_daily.png   daily POE50 vs POE10 (only if MAKE_DAILY_PLOTS)

Difference = POE10 - POE50 (TJ/d). Only dates present in both files are compared.
Previous PNGs in the output folders are deleted first.
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
SINGLE_DIR = BASE / "2025 gas fuel limitations data"
OUT_DIR = BASE / "poe_comparison"

MAKE_ZONE_RY_PLOTS = True
MAKE_DAILY_PLOTS = False            # one PNG per zone, RY and FY: large; use the filters below
DAILY_ZONES: list[str] = []         # e.g. ["melbourne"]; empty = all
DAILY_RYS: list[int] = []           # e.g. [2011, 2019]; empty = all
DAILY_FY_START, DAILY_FY_END = 2026, 2046
SAME_TOL = 1e-6                     # |difference| below this counts as identical
DPI = 100

PATTERN = re.compile(
    r"^GPG_Limit_STEP_CHANGE_(?P<zone>.+?)_GPG_Limit_TJ_(?P<ry>\d{4})_(?P<poe>POE\d+)\.csv$", re.I)


def zone_key(name):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"^S__", "", name, flags=re.I).lower())


def read(path):
    df = pd.read_csv(path)
    missing = {"Year", "Month", "Day", "Value"} - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    df["Date"] = pd.to_datetime(dict(year=df.Year, month=df.Month, day=df.Day), errors="raise")
    return df.drop_duplicates("Date", keep="first").set_index("Date").Value.sort_index()


def load():
    if not SINGLE_DIR.is_dir():
        raise FileNotFoundError(f"Missing folder: {SINGLE_DIR}")
    traces, names = {}, {}
    for path in sorted(SINGLE_DIR.glob("*.csv")):
        m = PATTERN.fullmatch(path.name)
        if not m or m["poe"].upper() not in ("POE10", "POE50"):
            continue
        key = zone_key(m["zone"])
        names[key] = re.sub(r"^S__", "", m["zone"], flags=re.I)
        traces[(key, int(m["ry"]), m["poe"].upper())] = read(path)
    if not traces:
        raise FileNotFoundError(f"No POE10/POE50 files in {SINGLE_DIR}")
    return traces, names


def clear(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.rglob("*.png"):
        old.unlink()


def stats(g):
    d = g.D
    return pd.Series({
        "Days": len(g), "POE50_Mean": g.POE50.mean(), "POE10_Mean": g.POE10.mean(),
        "Mean_Diff": d.mean(), "Mean_Abs_Diff": d.abs().mean(), "Median_Diff": d.median(),
        "P5_Diff": d.quantile(.05), "P95_Diff": d.quantile(.95), "Min_Diff": d.min(), "Max_Diff": d.max(),
        "Share_Identical": (d.abs() < SAME_TOL).mean(), "Share_POE10_Higher": (d > SAME_TOL).mean(),
        "Share_POE10_Lower": (d < -SAME_TOL).mean(),
        "Corr": g.POE10.corr(g.POE50) if g.POE10.nunique() > 1 and g.POE50.nunique() > 1 else np.nan})


def main():
    traces, names = load()
    pairs = sorted({(z, ry) for z, ry, _ in traces})
    both = [(z, ry) for z, ry in pairs if (z, ry, "POE10") in traces and (z, ry, "POE50") in traces]
    unpaired = [{"Zone_Key": z, "RY": ry, "Has_POE10": (z, ry, "POE10") in traces,
                 "Has_POE50": (z, ry, "POE50") in traces} for z, ry in pairs if (z, ry) not in both]
    OUT_DIR.mkdir(exist_ok=True)
    pd.DataFrame(unpaired, columns=["Zone_Key", "RY", "Has_POE10", "Has_POE50"]).to_csv(
        OUT_DIR / "missing_pairs.csv", index=False)
    for u in unpaired:
        print(f"Note: {u['Zone_Key']} RY{u['RY']} not compared (POE10={u['Has_POE10']}, POE50={u['Has_POE50']})")

    frames = []
    for z, ry in both:
        f = pd.concat([traces[(z, ry, "POE10")].rename("POE10"), traces[(z, ry, "POE50")].rename("POE50")],
                      axis=1, join="inner")
        frames.append(f.assign(Zone_Key=z, RY=ry).rename_axis("Date").reset_index())
    d = pd.concat(frames, ignore_index=True)
    d["D"] = d.POE10 - d.POE50
    d["FYE"] = d.Date.dt.year + (d.Date.dt.month >= 7).astype(int)
    d["Month_Start"] = d.Date.dt.to_period("M").dt.to_timestamp()

    for keys, name in [(["Zone_Key"], "summary_by_zone"), (["Zone_Key", "RY"], "summary_by_zone_ry"),
                       (["Zone_Key", "FYE"], "summary_by_zone_fy")]:
        d.groupby(keys).apply(stats, include_groups=False).round(3).reset_index().to_csv(
            OUT_DIR / f"{name}.csv", index=False)

    zone_tbl = d.groupby("Zone_Key").apply(stats, include_groups=False)
    print("Pooled over all reference years (TJ/d, difference = POE10 - POE50):")
    print(zone_tbl[["Days", "POE50_Mean", "POE10_Mean", "Mean_Diff", "Mean_Abs_Diff",
                    "P5_Diff", "P95_Diff", "Share_Identical"]].round(2).to_string())

    folder = OUT_DIR / "zone_overview"
    clear(folder)
    cmap = plt.get_cmap("tab20")
    for key, g in d.groupby("Zone_Key"):
        nm = names.get(key, key)
        fig, ax = plt.subplots(2, 2, figsize=(16, 10))
        mm = g.groupby(["Month_Start", "RY"])[["POE10", "POE50"]].median().groupby("Month_Start").median()
        ax[0, 0].plot(mm.index, mm.POE50, label="POE50", lw=1.4)
        ax[0, 0].plot(mm.index, mm.POE10, label="POE10", lw=1.4, ls="--")
        ax[0, 0].set_title("Monthly median (median across reference years)")
        ax[0, 0].set_ylabel("RHS (TJ/d)")
        ax[0, 0].legend()
        sub = g.sample(min(len(g), 40000), random_state=0)
        ax[0, 1].scatter(sub.POE50, sub.POE10, s=2, alpha=.15)
        lim = [min(sub.POE50.min(), sub.POE10.min()), max(sub.POE50.max(), sub.POE10.max())]
        ax[0, 1].plot(lim, lim, "k", lw=.8)
        ax[0, 1].set_xlabel("POE50 (TJ/d)")
        ax[0, 1].set_ylabel("POE10 (TJ/d)")
        ax[0, 1].set_title("Daily values (sample), black line = equal")
        moy = g.assign(M=g.Date.dt.month).groupby("M").D
        mean_m, p5, p95 = (s.reindex(range(1, 13)) for s in (moy.mean(), moy.quantile(.05), moy.quantile(.95)))
        ax[1, 0].bar(range(1, 13), mean_m, color="C2", alpha=.7, label="mean")
        ax[1, 0].vlines(range(1, 13), p5, p95, color="k", lw=1.2, label="5th-95th percentile")
        ax[1, 0].axhline(0, color="k", lw=.6)
        ax[1, 0].set_xticks(range(1, 13), ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
        ax[1, 0].set_title("POE10 - POE50 by calendar month (all years, all RYs)")
        ax[1, 0].set_ylabel("TJ/d")
        ax[1, 0].legend()
        fy = g.groupby("FYE").D
        ax[1, 1].plot(fy.mean().index, fy.mean(), marker="o", label="mean")
        ax[1, 1].plot(fy.mean().index, fy.apply(lambda x: x.abs().mean()), marker="s", label="mean absolute")
        ax[1, 1].axhline(0, color="k", lw=.6)
        ax[1, 1].set_title("POE10 - POE50 by financial year (all RYs)")
        ax[1, 1].set_xlabel("FY ending")
        ax[1, 1].set_ylabel("TJ/d")
        ax[1, 1].legend()
        for a in ax.ravel():
            a.grid(alpha=.3)
        fig.suptitle(f"{nm}: POE10 vs POE50 single-reference-year traces "
                     f"(identical on {(g.D.abs() < SAME_TOL).mean():.0%} of days)")
        fig.tight_layout()
        fig.savefig(folder / f"{key}_overview.png", dpi=DPI)
        plt.close(fig)

    if MAKE_ZONE_RY_PLOTS:
        folder = OUT_DIR / "zone_ry_monthly"
        clear(folder)
        for (key, ry), g in d.groupby(["Zone_Key", "RY"]):
            mm = g.groupby("Month_Start")[["POE10", "POE50"]].median()
            fig, (a1, a2) = plt.subplots(2, 1, figsize=(16, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1.5]})
            a1.plot(mm.index, mm.POE50, label="POE50", lw=1.4)
            a1.plot(mm.index, mm.POE10, label="POE10", lw=1.4, ls="--")
            a1.set_ylabel("RHS monthly median (TJ/d)")
            a1.set_title(f"{names.get(key, key)} RY{ry}: monthly median POE50 vs POE10")
            a1.legend()
            md = g.groupby("Month_Start").D.agg(["mean", lambda x: x.quantile(.05), lambda x: x.quantile(.95)])
            a2.bar(md.index, md["mean"], width=25, color="C2", alpha=.6, label="mean daily difference")
            a2.fill_between(md.index, md.iloc[:, 1], md.iloc[:, 2], color="0.5", alpha=.25, label="5th-95th percentile")
            a2.axhline(0, color="k", lw=.6)
            a2.set_ylabel("POE10 - POE50 (TJ/d)")
            a2.legend(loc="upper left", fontsize=8)
            for a in (a1, a2):
                a.grid(alpha=.3)
            fig.tight_layout()
            fig.savefig(folder / f"{key}_RY{ry}_monthly.png", dpi=DPI)
            plt.close(fig)

    if MAKE_DAILY_PLOTS:
        root = OUT_DIR / "daily_fy"
        clear(root)
        zs = [zone_key(z) for z in DAILY_ZONES] or sorted(d.Zone_Key.unique())
        n = 0
        for (key, ry), g in d.groupby(["Zone_Key", "RY"]):
            if key not in zs or (DAILY_RYS and ry not in DAILY_RYS):
                continue
            (root / key).mkdir(exist_ok=True)
            for fy in range(DAILY_FY_START, DAILY_FY_END + 1):
                s = g[g.FYE == fy].set_index("Date")
                if s.empty:
                    continue
                fig, (a1, a2) = plt.subplots(2, 1, figsize=(16, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]})
                a1.plot(s.index, s.POE50, label="POE50", lw=1.2)
                a1.plot(s.index, s.POE10, label="POE10", lw=1.2, ls="--")
                a1.set_ylabel("RHS (TJ/d)")
                a1.set_title(f"{names.get(key, key)} RY{ry} FY{fy}: daily POE50 vs POE10")
                a1.legend()
                a2.bar(s.index, s.D, width=1, color=np.where(s.D > 0, "C2", "C3"))
                a2.set_ylabel("POE10 - POE50")
                a2.xaxis.set_major_locator(mdates.MonthLocator())
                a2.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
                for a in (a1, a2):
                    a.grid(alpha=.3)
                fig.tight_layout()
                fig.savefig(root / key / f"{key}_RY{ry}_FY{fy}_daily.png", dpi=DPI)
                plt.close(fig)
                n += 1
        print(f"{n} daily charts in {root}")
    print(f"\nOutputs in {OUT_DIR}")


if __name__ == "__main__":
    main()
