"""Apply structural adjustments to single-reference-year (single-RY) GPG gas RHS
traces and write continuous daily traces to OUTPUT_END_DATE.

Run (no arguments):
    python apply_rry_gas_levels.py
Edit the inputs, run again, review, repeat. Every run overwrites the outputs.

Inputs (rry_gas_manual_inputs/)
-------------------------------
zone_settings.csv  Zone_Key, Treatment, Transplant_Censored, Note
    Treatment:
      adjust        : single-RY + your held level (levels.csv) + seasonal (seasonal.csv)
      auto          : as adjust, but adopt RRY in FYs where the RRY is a constant limit
      adopt_rry     : use the RRY daily values
      median_offset : no manual inputs. Adjustment(d) = SMOOTH_DAYS centred rolling mean of
                      [RRY(d) - median across all single-RY traces on d]. Same adjustment
                      added to every RY. Needs no matched trace, so data gaps are covered.
levels.csv         Zone_Key, Date, Level_TJ, Note     (adjust / auto zones only)
    STEP-HOLD: each level applies from its Date until the day before the next Date
    for that zone; the first also covers earlier dates, the last runs to
    OUTPUT_END_DATE. Duplicate dates: the LAST row wins (printed).
seasonal.csv       Zone_Key, From_Date, Jan..Dec, Note (adjust / auto zones only)
Note columns are ignored by the script.

Derived value on day d (single-RY trace for reference year RY):
    adjust / median_offset : max(Single_RY(d) + Adjustment(d), min(0, Single_RY(d)))
    adopt_rry              : RRY(d)
    rry_transplant         : adjust zones with Transplant_Censored = TRUE, in months where
                             most single-RY days (all RYs) are ~0
    pre_rry                : dates before the RRY starts are left unchanged

Continuity
----------
* Output for every file runs daily from its first date to OUTPUT_END_DATE.
* Single-RY extension past its last date: same month/day from the file's last
  available year (29 Feb in a non-leap source year uses 28 Feb).
* Missing dates inside a source file are filled from the previous day, up to
  MAX_FILL_DAYS consecutive days; longer gaps raise.
* All fills and extensions are listed in fill_and_extension_report.csv.
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
SINGLE_DIR = BASE / "2025 gas fuel limitations data"
RRY_DIR = BASE / "ISP 2026 RRY gas fuel limitations"
INPUT_DIR = BASE / "rry_gas_manual_inputs"
OUT_DIR = BASE / "rry_gas_adjusted_traces"

SINGLE_POE = "POE10"
RRY_POE = "POE10"
OUTPUT_END_DATE = pd.Timestamp("2050-12-31")
MAX_FILL_DAYS = 3

SMOOTH_DAYS = 31                 # median_offset smoothing window (centred, days)

LIMIT_TOP_N_VALUES = 3
LIMIT_SHARE = 0.90
LIMIT_ROUND_DP = 3
MIN_DAYS_PER_MONTH = 10
CENSOR_TJ = 1.0
CENSORED_MONTH_SHARE = 0.5
SMOOTH_WINDOW_MONTHS = 13
SMOOTH_MIN_MONTHS = 7

MAKE_PLOTS = True
MAKE_DAILY_PLOTS = True           # daily chart per zone and FY, one line per reference year
DAILY_ZONES: list[str] = []       # e.g. ["melbourne", "southern"]; empty = all zones
DAILY_FY_START, DAILY_FY_END = 2027, 2051   # FY ending years (2051 = Jul-Dec 2050 only)
DAILY_DPI = 100
RRY_TO_SINGLE_ZONE: dict[str, str] = {}

TREATMENTS = ["auto", "adjust", "adopt_rry", "median_offset"]

REFERENCE_SEQUENCE = [2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018,
                      2019, 2020, 2021, 2022, 2023, 2024, 2025, 2015]
FYE_TO_RY = {2026: 2015}
FYE_TO_RY.update({f: REFERENCE_SEQUENCE[(f - 2027) % 16] for f in range(2027, 2055)})

SINGLE_PATTERN = re.compile(
    r"^GPG_Limit_STEP_CHANGE_(?P<zone>.+?)_GPG_Limit_TJ_(?P<code>\d{4})_(?P<poe>POE\d+)\.csv$", re.I)
RRY_PATTERN = re.compile(
    r"^GPG_Limit_STEP_CHANGE_(?P<zone>.+?)_GPG_Limit_TJ_(?P<code>\d+)_(?P<poe>POE\d+)\.csv$", re.I)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAY = pd.Timedelta(days=1)


# ============================================================ helpers
def zone_key(name):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"^S__", "", name, flags=re.I).lower())


def fye(dates):
    return dates.dt.year + (dates.dt.month >= 7).astype(int)


def month_start(dates):
    return dates.dt.to_period("M").dt.to_timestamp()


def is_leap(y):
    y = np.asarray(y)
    return ((y % 4 == 0) & (y % 100 != 0)) | (y % 400 == 0)


def make_dates(yr, mo, dy):
    dy = np.where((np.asarray(mo) == 2) & (np.asarray(dy) == 29) & ~is_leap(yr), 28, dy)
    return pd.DatetimeIndex(pd.to_datetime(pd.DataFrame({"year": yr, "month": mo, "day": dy})))


def parse_dates(series, where):
    out = pd.to_datetime(series.astype(str).str.strip(), format="mixed", dayfirst=True, errors="coerce")
    if out.isna().any():
        raise ValueError(f"{where}: unparseable dates {series[out.isna()].tolist()[:5]} (use YYYY-MM-DD)")
    return out.dt.normalize()


def parse_bool(series, where):
    m = {"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False}
    s = series.astype(str).str.strip().str.lower()
    if (~s.isin(m)).any():
        raise ValueError(f"{where}: expected TRUE/FALSE, got {series[~s.isin(m)].tolist()[:5]}")
    return s.map(m)


def blocks(x, mask):
    mask = pd.Series(np.asarray(mask, dtype=bool))
    x = pd.Series(pd.to_datetime(np.asarray(x)))
    for _, b in x[mask].groupby((mask != mask.shift()).cumsum()[mask]):
        yield b.min(), b.max() + pd.offsets.MonthEnd(1)


# ============================================================ loading
def read_trace(path, is_rry):
    df = pd.read_csv(path)
    needed = {"Year", "Month", "Day", "Value"}
    if not needed.issubset(df.columns):
        raise ValueError(f"{path}: missing columns {sorted(needed - set(df.columns))}")
    extra = set(df.columns) - needed
    if extra:
        raise ValueError(f"{path}: unexpected columns {sorted(extra)}; output writes Year, Month, Day, Value only")
    df["Date"] = pd.to_datetime(dict(year=df.Year, month=df.Month, day=df.Day), errors="raise")
    df["Value"] = pd.to_numeric(df.Value, errors="raise")
    if df.Value.isna().any() or not np.isfinite(df.Value.to_numpy(dtype=float)).all():
        raise ValueError(f"{path}: null or non-finite RHS")
    dup = df[df.Date.duplicated(keep=False)]
    if not dup.empty:
        if is_rry:
            conflicts = dup.groupby("Date").Value.nunique(dropna=False)
            if (conflicts > 1).any():
                raise ValueError(f"{path}: conflicting RRY duplicate dates: "
                                 f"{conflicts[conflicts > 1].index.tolist()[:10]}")
        df = df.drop_duplicates("Date", keep="first")
    return df[["Date", "Value"]].sort_values("Date").reset_index(drop=True)


def complete(df, end, extend, label, report):
    s = df.set_index("Date").Value
    first, last = s.index.min(), s.index.max()
    stop = end if extend else last
    full = pd.date_range(first, stop, freq="D")
    out = pd.DataFrame({"Date": full, "Value": s.reindex(full).to_numpy()})
    out["Source"] = np.where(out.Value.notna(), "original", "")

    internal = out.Value.isna() & (out.Date <= last)
    if internal.any():
        run_id = internal.ne(internal.shift()).cumsum()
        lens = internal.groupby(run_id).transform("sum")
        if (lens[internal] > MAX_FILL_DAYS).any():
            bad = out.Date[internal & (lens > MAX_FILL_DAYS)]
            raise ValueError(f"{label}: internal gap longer than {MAX_FILL_DAYS} days starting "
                             f"{bad.min().date()} ({int(lens[internal].max())} days)")
        out.loc[internal, "Value"] = out.Value.ffill()[internal]
        out.loc[internal, "Source"] = "filled_previous_day"
        report.append({"Series": label, "Type": "filled_previous_day", "Days": int(internal.sum()),
                       "Dates": ";".join(out.Date[internal].dt.strftime("%Y-%m-%d").tolist()[:20])})

    ext = out.Date > last
    if ext.any():
        d = out.Date[ext]
        yr = np.full(len(d), last.year)
        src = make_dates(yr, d.dt.month.to_numpy(), d.dt.day.to_numpy())
        yr = np.where(src > last, yr - 1, yr)
        src = make_dates(yr, d.dt.month.to_numpy(), d.dt.day.to_numpy())
        vals = out.set_index("Date").Value.reindex(src).to_numpy()
        if np.isnan(vals).any():
            raise ValueError(f"{label}: extension source dates missing, e.g. {src[np.isnan(vals)][:5].date.tolist()}")
        out.loc[ext, "Value"] = vals
        out.loc[ext, "Source"] = "extended_repeat_last_year"
        report.append({"Series": label, "Type": "extended_repeat_last_year", "Days": int(ext.sum()),
                       "Dates": f"{d.min().date()}..{d.max().date()} from {src.min().date()}..{src.max().date()}"})
    return out


def load_traces(folder, pattern, expected_poe, is_rry):
    if not folder.is_dir():
        raise FileNotFoundError(f"Missing folder: {folder}")
    files = sorted(folder.glob("*.csv"))
    aliases = {zone_key(k): zone_key(v) for k, v in RRY_TO_SINGLE_ZONE.items()}
    records, seen = [], set()
    for path in files:
        m = pattern.fullmatch(path.name)
        if not m or m["poe"].upper() != expected_poe:
            continue
        key = zone_key(m["zone"])
        if is_rry:
            key = aliases.get(key, key)
        ry = None if is_rry else int(m["code"])
        if not is_rry and ry not in set(FYE_TO_RY.values()):
            continue
        if (key, ry) in seen:
            raise ValueError(f"Multiple {expected_poe} files for {(key, ry)}, including {path.name}")
        seen.add((key, ry))
        records.append({"Zone_Key": key, "Zone": re.sub(r"^S__", "", m["zone"], flags=re.I),
                        "RY": ry, "Path": path, "Frame": read_trace(path, is_rry)})
    if not records:
        raise FileNotFoundError(f"No {expected_poe} matching gas files in {folder}; CSV count: {len(files)}")
    return records


# ============================================================ inputs
def read_inputs(zones):
    paths = {n: INPUT_DIR / f"{n}.csv" for n in ("zone_settings", "levels", "seasonal")}
    for p in paths.values():
        if not p.exists():
            raise FileNotFoundError(f"Missing input {p}")
    st = pd.read_csv(paths["zone_settings"], dtype=str).fillna("")
    lv = pd.read_csv(paths["levels"], dtype=str).fillna("")
    se = pd.read_csv(paths["seasonal"], dtype=str).fillna("")
    for name, df, cols in [("zone_settings", st, ["Zone_Key", "Treatment", "Transplant_Censored"]),
                           ("levels", lv, ["Zone_Key", "Date", "Level_TJ"]),
                           ("seasonal", se, ["Zone_Key", "From_Date"] + MONTHS)]:
        miss = set(cols) - set(df.columns)
        if miss:
            raise ValueError(f"{name}.csv missing columns {sorted(miss)}")
        df["Zone_Key"] = df.Zone_Key.str.strip().str.lower()
        unknown = set(df.Zone_Key) - set(zones)
        if unknown:
            raise ValueError(f"{name}.csv: unknown Zone_Key {sorted(unknown)}; valid: {sorted(zones)}")
        if "Note" not in df.columns:
            df["Note"] = ""

    st["Treatment"] = st.Treatment.str.strip().str.lower()
    bad = ~st.Treatment.isin(TREATMENTS)
    if bad.any():
        raise ValueError(f"zone_settings.csv: Treatment must be one of {TREATMENTS}, got "
                         f"{st.loc[bad, ['Zone_Key', 'Treatment']].values.tolist()}")
    st["Transplant_Censored"] = parse_bool(st.Transplant_Censored, "zone_settings.csv Transplant_Censored")
    if st.Zone_Key.duplicated().any():
        raise ValueError(f"zone_settings.csv: duplicate zones {st.Zone_Key[st.Zone_Key.duplicated()].tolist()}")
    if set(zones) - set(st.Zone_Key):
        raise ValueError(f"zone_settings.csv: missing zones {sorted(set(zones) - set(st.Zone_Key))}")

    lv["Csv_Row"] = lv.index + 2
    lv["Date"] = parse_dates(lv.Date, "levels.csv Date")
    lv["Level_TJ"] = pd.to_numeric(lv.Level_TJ, errors="coerce")
    if lv.Level_TJ.isna().any():
        raise ValueError(f"levels.csv: non-numeric Level_TJ in rows {lv.Csv_Row[lv.Level_TJ.isna()].tolist()}")
    dup = lv.duplicated(["Zone_Key", "Date"], keep="last")
    if dup.any():
        for _, r in lv[dup].iterrows():
            print(f"levels.csv: {r.Zone_Key} {r.Date.date()} has more than one row; row {r.Csv_Row} "
                  f"(Level {r.Level_TJ:g}) ignored, the last row for that date is used")
        lv = lv[~dup]
    lv = lv.sort_values(["Zone_Key", "Date"]).reset_index(drop=True)

    se["From_Date"] = parse_dates(se.From_Date, "seasonal.csv From_Date")
    for mth in MONTHS:
        se[mth] = pd.to_numeric(se[mth], errors="coerce")
        if se[mth].isna().any():
            raise ValueError(f"seasonal.csv: non-numeric {mth} for zones {se.Zone_Key[se[mth].isna()].tolist()}")
    if se.duplicated(["Zone_Key", "From_Date"]).any():
        raise ValueError("seasonal.csv: duplicate Zone_Key + From_Date rows")
    return st, lv, se


def level_schedule(lv, zones_end):
    rows = []
    for key, g in lv.groupby("Zone_Key"):
        g = g.sort_values("Date").reset_index(drop=True)
        for i, r in g.iterrows():
            to = g.Date.iloc[i + 1] - DAY if i + 1 < len(g) else zones_end
            rows.append({"Zone_Key": key, "From_Date": r.Date.date(), "To_Date": to.date(),
                         "Level_TJ": r.Level_TJ, "Csv_Row": r.Csv_Row, "Note": r.Note})
    return pd.DataFrame(rows, columns=["Zone_Key", "From_Date", "To_Date", "Level_TJ", "Csv_Row", "Note"])


def build_adjustment(lv, se, adjust_zones, rry_start):
    parts = []
    for key in adjust_zones:
        days = pd.date_range(rry_start[key], OUTPUT_END_DATE, freq="D")
        zl = lv[lv.Zone_Key == key].sort_values("Date")
        zs = se[se.Zone_Key == key].sort_values("From_Date")
        if zl.empty:
            raise ValueError(f"levels.csv: no rows for adjusted zone '{key}'")
        if zs.empty:
            raise ValueError(f"seasonal.csv: no rows for adjusted zone '{key}'")
        if zs.From_Date.min() > days[0]:
            raise ValueError(f"seasonal.csv {key}: first From_Date {zs.From_Date.min().date()} is after "
                             f"the RRY start {days[0].date()}")
        li = np.searchsorted(zl.Date.to_numpy(), days.to_numpy(), side="right") - 1
        level = zl.Level_TJ.to_numpy()[np.clip(li, 0, None)]
        si = np.searchsorted(zs.From_Date.to_numpy(), days.to_numpy(), side="right") - 1
        seas = zs[MONTHS].to_numpy(dtype=float)[si, days.month.to_numpy() - 1]
        parts.append(pd.DataFrame({"Zone_Key": key, "Date": days, "Level_TJ": level,
                                   "Seasonal_TJ": seas, "Delta_TJ": level + seas}))
    cols = ["Zone_Key", "Date", "Level_TJ", "Seasonal_TJ", "Delta_TJ"]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)


def build_median_offset(single, rry, mo_zones, rry_start):
    """Adjustment = centred rolling mean of (RRY - median of all single-RY traces)."""
    parts = []
    for key in mo_zones:
        days = pd.date_range(rry_start[key], OUTPUT_END_DATE, freq="D")
        med = (single[single.Zone_Key == key].groupby("Date").Single_RY_RHS_TJ.median().reindex(days))
        r = rry[rry.Zone_Key == key].set_index("Date").RRY_RHS_TJ.reindex(days)
        if med.isna().any() or r.isna().any():
            raise ValueError(f"{key}: median_offset needs RRY and single-RY data on every day from "
                             f"{days[0].date()} to {days[-1].date()}")
        raw = r - med
        sm = raw.rolling(SMOOTH_DAYS, center=True, min_periods=SMOOTH_DAYS // 2 + 1).mean()
        parts.append(pd.DataFrame({"Zone_Key": key, "Date": days, "Level_TJ": np.nan, "Seasonal_TJ": np.nan,
                                   "Delta_TJ": sm.to_numpy(), "RRY_TJ": r.to_numpy(),
                                   "Single_Median_TJ": med.to_numpy(), "Raw_Diff_TJ": raw.to_numpy()}))
    cols = ["Zone_Key", "Date", "Level_TJ", "Seasonal_TJ", "Delta_TJ", "RRY_TJ", "Single_Median_TJ", "Raw_Diff_TJ"]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)


# ============================================================ modes / transplant
def constant_limit_fys(rry):
    rows = []
    for (key, year), g in rry.groupby(["Zone_Key", "FYE"], sort=True):
        counts = g.RRY_RHS_TJ.round(LIMIT_ROUND_DP).value_counts()
        share = float(counts.iloc[:LIMIT_TOP_N_VALUES].sum() / counts.sum())
        rows.append({"Zone_Key": key, "FYE": int(year), "Constant_Limit": share >= LIMIT_SHARE})
    return pd.DataFrame(rows)


def resolve_modes(limits, settings):
    m = limits.merge(settings[["Zone_Key", "Treatment"]], on="Zone_Key", how="left", validate="many_to_one")
    m["Mode"] = np.select([m.Treatment.eq("adopt_rry"), m.Treatment.eq("median_offset"),
                           m.Treatment.eq("adjust"), m.Treatment.eq("auto") & m.Constant_Limit],
                          ["adopt_rry", "median_offset", "adjust", "adopt_rry"], default="adjust")
    return m


def rry_smooth_table(rry):
    rm = (rry.assign(Month_Start=month_start(rry.Date)).groupby(["Zone_Key", "Month_Start"])
          .RRY_RHS_TJ.median().reset_index())
    parts = []
    for key, g in rm.groupby("Zone_Key"):
        g = g.sort_values("Month_Start").reset_index(drop=True)
        cal = g.Month_Start.dt.month.to_numpy()
        y = g.RRY_RHS_TJ
        s = np.zeros(len(g))
        for _ in range(3):
            lvl = (y - s).rolling(SMOOTH_WINDOW_MONTHS, center=True, min_periods=SMOOTH_MIN_MONTHS).median()
            r = pd.Series((y - lvl).to_numpy()).groupby(cal).median().reindex(range(1, 13)).fillna(0.0)
            r -= r.median()
            s = r.loc[cal].to_numpy()
        sm = pd.Series(lvl.to_numpy() + s).interpolate(limit_direction="both").to_numpy()
        parts.append(pd.DataFrame({"Zone_Key": key, "Month_Start": g.Month_Start, "RRY_Smooth_TJ": sm}))
    return pd.concat(parts, ignore_index=True).set_index(["Zone_Key", "Month_Start"]).RRY_Smooth_TJ


def transplant_source_dates(dates, ry, rry_fyes):
    cands = np.array(sorted(f for f in rry_fyes if FYE_TO_RY.get(f) == ry))
    if cands.size == 0:
        raise ValueError(f"RY{ry}: no RRY financial year uses this reference year; cannot transplant")
    dates = pd.Series(pd.to_datetime(np.asarray(dates)))
    tgt = (dates.dt.year + (dates.dt.month >= 7).astype(int)).to_numpy()
    src = cands[np.abs(cands[None, :] - tgt[:, None]).argmin(axis=1)]
    return make_dates(dates.dt.year.to_numpy() + (src - tgt), dates.dt.month.to_numpy(), dates.dt.day.to_numpy())


# ============================================================ apply
def apply(m, ry, ctx):
    m = m.copy()
    m["FYE"] = fye(m.Date)
    m["Month_Start"] = month_start(m.Date)
    rng = ctx["rry_range"]
    m["Pre_RRY"] = m.Date < m.Zone_Key.map(rng["min"])
    m = m.merge(ctx["modes"][["Zone_Key", "FYE", "Mode"]], on=["Zone_Key", "FYE"], how="left", validate="many_to_one")
    m = m.merge(ctx["transplant"], on=["Zone_Key", "Month_Start"], how="left", validate="many_to_one")
    m = m.merge(ctx["adj"][["Zone_Key", "Date", "Delta_TJ"]], on=["Zone_Key", "Date"], how="left", validate="many_to_one")
    m = m.merge(ctx["rry_daily"], on=["Zone_Key", "Date"], how="left", validate="many_to_one")
    m.loc[m.Pre_RRY, "Mode"] = "pre_rry_unchanged"

    m["Transplant_Value_TJ"] = np.nan
    tp = m.Transplant.eq(True) & m.Mode.eq("adjust")
    if tp.any():
        ry_ser = pd.Series(ry if np.ndim(ry) else np.full(len(m), ry), index=m.index)
        rd, rs = ctx["rry_idx"], ctx["rry_smooth"]
        for r_val, idx in m[tp].groupby(ry_ser[tp]).groups.items():
            sub = m.loc[idx]
            sd = transplant_source_dates(sub.Date, int(r_val), ctx["rry_fyes"])
            val = rd.reindex(pd.MultiIndex.from_arrays([sub.Zone_Key, sd])).to_numpy()
            lt = rs.reindex(pd.MultiIndex.from_arrays([sub.Zone_Key, sub.Month_Start])).to_numpy()
            ls = rs.reindex(pd.MultiIndex.from_arrays([sub.Zone_Key, sd.to_period("M").to_timestamp()])).to_numpy()
            bad = np.isnan(val) | np.isnan(lt) | np.isnan(ls)
            if bad.any():
                raise ValueError(f"RY{int(r_val)}: RRY source data missing for {int(bad.sum())} transplant days, "
                                 f"e.g. {sub.Date[bad].head(5).dt.date.tolist()}")
            m.loc[idx, "Transplant_Value_TJ"] = np.maximum(lt + val - ls, 0.0)
        m.loc[tp, "Mode"] = "rry_transplant"

    raw = m.Single_RY_RHS_TJ + m.Delta_TJ
    adj = raw.clip(lower=np.minimum(m.Single_RY_RHS_TJ, 0.0))
    additive = m.Mode.isin(["adjust", "median_offset"])
    m["Floored"] = additive & (adj != raw)
    m["Derived_RHS_TJ"] = np.select(
        [m.Mode.eq("pre_rry_unchanged"), m.Mode.eq("adopt_rry"), additive, m.Mode.eq("rry_transplant")],
        [m.Single_RY_RHS_TJ, m.RRY_RHS_TJ, adj, m.Transplant_Value_TJ], default=np.nan)
    if m.Derived_RHS_TJ.isna().any():
        b = m[m.Derived_RHS_TJ.isna()]
        raise ValueError(f"{len(b)} derived values missing (e.g. adopt_rry beyond the RRY end, or no mode); "
                         f"first rows:\n{b[['Zone_Key', 'Date', 'Mode', 'Delta_TJ', 'RRY_RHS_TJ']].head(10)}")
    return m


# ============================================================ plots
def plots(t, dm, adj, lv, se, names, adjust_zones, mo_zones, mo, allry, rry_month):
    folder = OUT_DIR / "review_plots"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.png"):
        old.unlink()
    for key in sorted(t.Zone_Key.unique()):
        g = t[t.Zone_Key == key].sort_values("Month_Start").reset_index(drop=True)
        x, mid = g.Month_Start, g.Month_Start + pd.Timedelta(days=14)
        shade = [("no matched single-RY (gap)", ~g.Has_Match & ~g.Mode.eq("median_offset"), "orange"),
                 ("single-RY extended (repeat last year)", g.Extended_Share.fillna(0) > .5, "lightblue"),
                 ("RRY weather transplant", g.Transplant, "plum"),
                 ("adopt RRY", g.Mode.eq("adopt_rry"), "0.7")]

        def shade_ax(ax):
            for lab, mask, col in shade:
                first = True
                for a, b in blocks(x, mask):
                    ax.axvspan(a, b, color=col, alpha=.2, zorder=0, label=lab if first else None)
                    first = False

        if key in adjust_zones:
            mz = dm[dm.Zone_Key == key].set_index("Date").sort_index()
            az = adj[adj.Zone_Key == key].set_index("Date")
            fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(18, 14), sharex=True,
                                             gridspec_kw={"height_ratios": [3, 1.3, 2]})
            a1.plot(mz.index, mz.Diff_TJ, color="0.8", lw=.4, label="daily RRY - matched single-RY")
            a1.scatter(mid[g.Fit], g.Observed_Diff_TJ[g.Fit], s=14, color="C0", zorder=3, label="monthly median difference")
            nf = g.Has_Match & ~g.Fit
            a1.scatter(mid[nf], g.Observed_Diff_TJ[nf], s=16, facecolors="none", edgecolors="C0", zorder=3,
                       label="not usable (censored / transplant / adopt RRY)")
            a1.step(az.index, az.Level_TJ, where="post", color="k", lw=1.2, label="your level (held)")
            a1.plot(az.index, az.Delta_TJ, color="C3", lw=1, alpha=.8, label="level + seasonal")
            zl = lv[lv.Zone_Key == key]
            a1.scatter(zl.Date, zl.Level_TJ, color="k", s=28, zorder=5, label="level rows (label = levels.csv row)")
            for _, r in zl.iterrows():
                a1.annotate(f"r{r.Csv_Row}", (r.Date, r.Level_TJ), textcoords="offset points", xytext=(3, 6), fontsize=8)
            a1.set_ylabel("TJ/d")
            a1.set_title(f"{names.get(key, key)}: RRY minus matched single-RY and your adjustment")

            lo = g.Leftover_TJ
            a2.bar(mid[g.Fit], lo[g.Fit], width=25, color=np.where(lo[g.Fit] > 0, "C2", "C3"), alpha=.6)
            a2.plot(mid, lo.rolling(12, center=True, min_periods=6).mean(), color="k", lw=1.4,
                    label="12-month average (should hover around 0)")
            a2.axhline(0, color="k", lw=.6)
            a2.set_ylabel("difference - adjustment\n(TJ/d)")
            a2.set_title("Leftover: persistent + = raise level, persistent - = lower level", fontsize=10)

            a3.plot(mid, g.RRY_Month_Median_TJ, lw=1.5, label="RRY")
            a3.plot(mid, g.Matched_Single_Median_TJ, color="0.55", label="original matched single-RY (extended after its end)")
            a3.plot(mid, g.Derived_Matched_Median_TJ, color="C1", ls="--", lw=1.3, label="derived matched single-RY")
            gm = ~g.Has_Match & g.Mode.eq("adjust") & ~g.Transplant
            if gm.any():
                a3.plot(mid.where(gm), g.Gap_Proxy_TJ.where(gm), color="C2", lw=1.5,
                        label="gap check: all-RY single median + adjustment")
            a3.set_ylabel("RHS monthly median (TJ/d)")
            for ax in (a1, a2, a3):
                shade_ax(ax)
                ax.grid(alpha=.2)
                ax.legend(loc="upper left", fontsize=7)
            fig.tight_layout()
            fig.savefig(folder / f"{key}_1_level_review.png", dpi=120)
            plt.close(fig)

            fig, ax = plt.subplots(figsize=(11, 6))
            f = g[g.Fit].copy()
            f["r"] = f.Observed_Diff_TJ - f.Level_TJ
            yrs = sorted(f.Month_Start.dt.year.unique())
            cmap = plt.get_cmap("viridis")
            for i, (yr, fy) in enumerate(f.groupby(f.Month_Start.dt.year)):
                ax.plot(fy.Month_Start.dt.month, fy.r, color=cmap(i / max(len(yrs) - 1, 1)), lw=.9, alpha=.8,
                        marker=".", label=str(yr))
            for _, r in se[se.Zone_Key == key].iterrows():
                ax.plot(range(1, 13), r[MONTHS].to_numpy(dtype=float), color="C3", lw=2.8,
                        label=f"your seasonal from {r.From_Date.date()}")
            ax.axhline(0, color="k", lw=.5)
            ax.set_xticks(range(1, 13), MONTHS)
            ax.set_ylabel("monthly difference - your level (TJ/d)")
            ax.set_title(f"{names.get(key, key)}: seasonal review")
            ax.grid(alpha=.2)
            ax.legend(fontsize=7, ncol=3)
            fig.tight_layout()
            fig.savefig(folder / f"{key}_2_seasonal_review.png", dpi=110)
            plt.close(fig)

        if key in mo_zones:
            z = mo[mo.Zone_Key == key].set_index("Date")
            dmed = allry[allry.Zone_Key == key].groupby("Month_Start").Derived_Month_Median_TJ.median()
            omed = z.Single_Median_TJ.resample("MS").median()
            fig, (a1, a2) = plt.subplots(2, 1, figsize=(18, 10), sharex=True)
            a1.plot(z.index, z.Raw_Diff_TJ, color="0.8", lw=.4, label="daily RRY - median of all single-RY traces")
            a1.plot(z.index, z.Delta_TJ, color="C3", lw=1.6, label=f"applied adjustment ({SMOOTH_DAYS}-day centred mean)")
            a1.axhline(0, color="k", lw=.5)
            a1.set_ylabel("TJ/d")
            a1.set_title(f"{names.get(key, key)}: median_offset adjustment")
            rz = rry_month[rry_month.Zone_Key == key].set_index("Month_Start").RRY_Month_Median_TJ
            a2.plot(rz.index + pd.Timedelta(days=14), rz, color="k", lw=1.6, label="RRY")
            a2.plot(omed.index + pd.Timedelta(days=14), omed, color="0.55", label="original single-RY, median of all RYs")
            a2.plot(dmed.index + pd.Timedelta(days=14), dmed, color="C1", ls="--", lw=1.3,
                    label="derived single-RY, median of all RYs")
            a2.set_ylabel("RHS monthly median (TJ/d)")
            for ax in (a1, a2):
                shade_ax(ax)
                ax.grid(alpha=.2)
                ax.legend(loc="upper left", fontsize=7)
            fig.tight_layout()
            fig.savefig(folder / f"{key}_1_median_offset_review.png", dpi=120)
            plt.close(fig)

        fig, ax = plt.subplots(figsize=(18, 6))
        az_ = allry[allry.Zone_Key == key]
        for ry, r in az_.groupby("RY"):
            ax.plot(r.Month_Start + pd.Timedelta(days=14), r.Derived_Month_Median_TJ, lw=.7, alpha=.6)
        rz = rry_month[rry_month.Zone_Key == key]
        ax.plot(rz.Month_Start + pd.Timedelta(days=14), rz.RRY_Month_Median_TJ, color="k", lw=2, label="RRY")
        ax.plot([], [], color="0.5", lw=.7, label="derived single-RY traces (one line per RY)")
        shade_ax(ax)
        ax.axvline(OUTPUT_END_DATE, color="k", ls=":", lw=1)
        ax.set_ylabel("RHS monthly median (TJ/d)")
        ax.set_title(f"{names.get(key, key)}: all output traces (monthly median) to {OUTPUT_END_DATE.date()}")
        ax.grid(alpha=.2)
        ax.legend(loc="upper left", fontsize=7)
        fig.tight_layout()
        fig.savefig(folder / f"{key}_3_all_traces.png", dpi=110)
        plt.close(fig)


def daily_fy_plots(derived, original, filled, rry, names, modes):
    """One PNG per zone and financial year: daily RHS, one line per reference year.
    Top panel = adjusted (output) traces with the RRY in black; bottom panel = original
    single-RY traces on the same y-axis, so the adjustment can be seen directly."""
    import matplotlib.dates as mdates
    root = OUT_DIR / "daily_fy_plots"
    root.mkdir(parents=True, exist_ok=True)
    for old in root.rglob("*.png"):
        old.unlink()
    keys = [zone_key(z) for z in DAILY_ZONES] or sorted({k for k, _ in derived})
    unknown = set(keys) - {k for k, _ in derived}
    if unknown:
        raise ValueError(f"DAILY_ZONES not found: {sorted(unknown)}")
    cmap = plt.get_cmap("tab20")
    n = 0
    for key in keys:
        ries = sorted(ry for k, ry in derived if k == key)
        rz = rry[rry.Zone_Key == key].set_index("Date").RRY_RHS_TJ
        zm = modes[modes.Zone_Key == key].set_index("FYE").Mode
        folder = root / key
        folder.mkdir(exist_ok=True)
        for fy in range(DAILY_FY_START, DAILY_FY_END + 1):
            a, b = pd.Timestamp(fy - 1, 7, 1), min(pd.Timestamp(fy, 6, 30), OUTPUT_END_DATE)
            if a > OUTPUT_END_DATE:
                continue
            fig, (a1, a2) = plt.subplots(2, 1, figsize=(16, 11), sharex=True, sharey=True)
            for i, ry in enumerate(ries):
                lab = f"{ry}*" if (key, ry) in filled else str(ry)
                a1.plot(derived[(key, ry)].loc[a:b], lw=1, alpha=.75, color=cmap(i % 20), label=lab)
                a2.plot(original[(key, ry)].loc[a:b], lw=1, alpha=.75, color=cmap(i % 20))
            r = rz.loc[a:b]
            if not r.empty:
                a1.plot(r, color="k", lw=1.8, label="RRY")
                a2.plot(r, color="k", lw=1.0, ls="--", label="RRY")
            mode = zm.get(fy, "n/a")
            a1.set_title(f"{names.get(key, key)} FY{fy}: ADJUSTED daily RHS by reference year (mode: {mode})")
            a2.set_title("ORIGINAL single-RY traces (before adjustment; 2046+ = repeat of 2045)")
            a2.set_xlim(a, b)
            a2.xaxis.set_major_locator(mdates.MonthLocator())
            a2.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
            for ax in (a1, a2):
                ax.set_ylabel("RHS (TJ/day)")
                ax.grid(alpha=.3)
            a1.legend(title="Reference year (* = filled)", loc="upper left", ncol=3, fontsize=8)
            fig.tight_layout()
            fig.savefig(folder / f"{key}_FY{fy}_daily_by_reference_year.png", dpi=DAILY_DPI)
            plt.close(fig)
            n += 1
        print(f"daily plots: {names.get(key, key)} done")
    print(f"{n} daily charts in {root}")


# ============================================================ main
def main():
    report = []
    single_recs = load_traces(SINGLE_DIR, SINGLE_PATTERN, SINGLE_POE, False)
    rry_recs = load_traces(RRY_DIR, RRY_PATTERN, RRY_POE, True)

    rry_parts = []
    for r in rry_recs:
        c = complete(r["Frame"], None, False, f"RRY {r['Path'].name}", report)
        c["Zone_Key"], c["Zone"] = r["Zone_Key"], r["Zone"]
        rry_parts.append(c)
    rry = pd.concat(rry_parts, ignore_index=True).rename(columns={"Value": "RRY_RHS_TJ"})
    rry["FYE"] = fye(rry.Date)
    unmapped = sorted(set(rry.FYE) - set(FYE_TO_RY))
    if unmapped:
        raise ValueError(f"Unmapped RRY FYEs: {unmapped}")
    rry["Matched_RY"] = rry.FYE.map(FYE_TO_RY)
    rng = rry.groupby("Zone_Key").Date.agg(["min", "max"])
    short = rng[rng["max"] < OUTPUT_END_DATE]
    if not short.empty:
        print(f"Note: RRY ends before {OUTPUT_END_DATE.date()} for {short.index.tolist()}; "
              "adopt_rry / median_offset / transplant dates after that will raise.")

    for r in single_recs:
        r["Complete"] = complete(r["Frame"], OUTPUT_END_DATE, True, r["Path"].name, report)
    single = pd.concat([r["Complete"].assign(Zone_Key=r["Zone_Key"], RY=r["RY"]) for r in single_recs],
                       ignore_index=True).rename(columns={"Value": "Single_RY_RHS_TJ"})

    # Missing single-RY files: fill from the daily median of that zone's other RYs (flagged in the report).
    # Added after `single` is built, so the filled series does not feed any statistics.
    all_ry = {r["RY"] for r in single_recs}
    for key in sorted({r["Zone_Key"] for r in single_recs}):
        have = [r for r in single_recs if r["Zone_Key"] == key]
        for ry in sorted(all_ry - {r["RY"] for r in have}):
            stack = pd.concat([r["Complete"].set_index("Date").Value.rename(i) for i, r in enumerate(have)], axis=1)
            med = stack.median(axis=1)
            tmpl = have[0]["Path"].name
            name = re.sub(r"_TJ_\d{4}_", f"_TJ_{ry}_", tmpl)
            single_recs.append({"Zone_Key": key, "Zone": have[0]["Zone"], "RY": ry, "Path": Path(name),
                                "Complete": pd.DataFrame({"Date": med.index, "Value": med.to_numpy(),
                                                          "Source": "filled_median_of_other_RYs"})})
            report.append({"Series": name, "Type": "filled_median_of_other_RYs", "Days": len(med),
                           "Dates": f"{med.index.min().date()}..{med.index.max().date()} "
                                    f"(median of {len(have)} RYs: {sorted(r['RY'] for r in have)})"})
            print(f"Note: {key} has no RY{ry} single-RY file; filled with the median of the other {len(have)} RYs.")

    zones = sorted(rry.Zone_Key.unique())
    if set(single.Zone_Key) != set(zones):
        raise ValueError(f"Zone mismatch. Only single-RY: {sorted(set(single.Zone_Key) - set(zones))}; "
                         f"only RRY: {sorted(set(zones) - set(single.Zone_Key))}")
    names = rry.drop_duplicates("Zone_Key").set_index("Zone_Key").Zone.to_dict()

    st, lv, se = read_inputs(zones)
    modes = resolve_modes(constant_limit_fys(rry), st)
    adjust_zones = sorted(modes.loc[modes.Mode.eq("adjust"), "Zone_Key"].unique())
    mo_zones = sorted(modes.loc[modes.Mode.eq("median_offset"), "Zone_Key"].unique())
    mo = build_median_offset(single, rry, mo_zones, rng["min"])
    adj_parts = [f for f in (build_adjustment(lv, se, adjust_zones, rng["min"]),
                             mo[["Zone_Key", "Date", "Level_TJ", "Seasonal_TJ", "Delta_TJ"]]) if not f.empty]
    adj = (pd.concat(adj_parts, ignore_index=True) if adj_parts else
           pd.DataFrame(columns=["Zone_Key", "Date", "Level_TJ", "Seasonal_TJ", "Delta_TJ"]))
    adj["Date"] = pd.to_datetime(adj.Date)
    for c in ("Level_TJ", "Seasonal_TJ", "Delta_TJ"):
        adj[c] = adj[c].astype(float)

    s = single[single.Date >= single.Zone_Key.map(rng["min"])].copy()
    s["Month_Start"] = month_start(s.Date)
    s["Cens"] = s.Single_RY_RHS_TJ <= CENSOR_TJ
    pooled = s.groupby(["Zone_Key", "Month_Start"]).Cens.mean().rename("Pooled_Censored_Share").reset_index()
    allry_single = (s.groupby(["Zone_Key", "RY", "Month_Start"]).Single_RY_RHS_TJ.median().groupby(
        ["Zone_Key", "Month_Start"]).median().rename("Single_AllRY_Median_TJ").reset_index())

    matched = rry[["Zone_Key", "Date", "Matched_RY", "RRY_RHS_TJ"]].merge(
        single[["Zone_Key", "Date", "RY", "Single_RY_RHS_TJ", "Source"]].rename(columns={"RY": "Matched_RY"}),
        on=["Zone_Key", "Date", "Matched_RY"], how="inner", validate="one_to_one")
    matched["Diff_TJ"] = matched.RRY_RHS_TJ - matched.Single_RY_RHS_TJ
    mm = matched.assign(Month_Start=month_start(matched.Date), Cens=matched.Single_RY_RHS_TJ <= CENSOR_TJ,
                        Ext=matched.Source.eq("extended_repeat_last_year"))
    obs = mm.groupby(["Zone_Key", "Month_Start"]).agg(
        Observed_Diff_TJ=("Diff_TJ", "median"), Matched_Days=("Diff_TJ", "size"),
        Matched_RY=("Matched_RY", "first"), Matched_Censored_Share=("Cens", "mean"),
        Matched_Single_Median_TJ=("Single_RY_RHS_TJ", "median"), Extended_Share=("Ext", "mean")).reset_index()
    rry_month = (rry.assign(Month_Start=month_start(rry.Date)).groupby(["Zone_Key", "Month_Start"])
                 .RRY_RHS_TJ.median().rename("RRY_Month_Median_TJ").reset_index())

    t = pd.concat([pd.DataFrame({"Zone_Key": k, "Month_Start": pd.date_range(
        rng.loc[k, "min"].to_period("M").to_timestamp(), OUTPUT_END_DATE.to_period("M").to_timestamp(), freq="MS")})
        for k in zones], ignore_index=True)
    for f in (obs, allry_single, pooled, rry_month):
        t = t.merge(f, on=["Zone_Key", "Month_Start"], how="left")
    t["FYE"] = t.Month_Start.dt.year + (t.Month_Start.dt.month >= 7).astype(int)
    t = t.merge(modes[["Zone_Key", "FYE", "Mode"]], on=["Zone_Key", "FYE"], how="left")
    t = t.merge(st[["Zone_Key", "Transplant_Censored"]], on="Zone_Key", how="left")
    t["Matched_Days"] = t.Matched_Days.fillna(0).astype(int)
    t["Has_Match"] = t.Matched_Days >= MIN_DAYS_PER_MONTH
    t["Transplant"] = (t.Mode.eq("adjust") & t.Transplant_Censored.eq(True)
                       & t.Pooled_Censored_Share.gt(CENSORED_MONTH_SHARE))
    t["Fit"] = (t.Has_Match & t.Mode.eq("adjust") & ~t.Matched_Censored_Share.gt(CENSORED_MONTH_SHARE)
                & ~t.Transplant)

    ctx = {"modes": modes, "adj": adj, "transplant": t[["Zone_Key", "Month_Start", "Transplant"]],
           "rry_daily": rry[["Zone_Key", "Date", "RRY_RHS_TJ"]], "rry_range": rng,
           "rry_idx": rry.set_index(["Zone_Key", "Date"]).RRY_RHS_TJ,
           "rry_smooth": rry_smooth_table(rry), "rry_fyes": set(rry.FYE.unique())}

    dm = apply(matched[["Zone_Key", "Date", "Single_RY_RHS_TJ"]], matched.Matched_RY.to_numpy(), ctx)
    dm = dm.merge(matched[["Zone_Key", "Date", "Diff_TJ"]], on=["Zone_Key", "Date"], validate="one_to_one")
    am = (adj.assign(Month_Start=month_start(adj.Date)).groupby(["Zone_Key", "Month_Start"])
          [["Level_TJ", "Seasonal_TJ", "Delta_TJ"]].mean().rename(columns={"Delta_TJ": "Applied_Adjustment_TJ"})
          .reset_index())
    dmm = dm.groupby(["Zone_Key", "Month_Start"]).Derived_RHS_TJ.median().rename("Derived_Matched_Median_TJ").reset_index()
    t = t.merge(am, on=["Zone_Key", "Month_Start"], how="left").merge(dmm, on=["Zone_Key", "Month_Start"], how="left")
    t["Leftover_TJ"] = (t.Observed_Diff_TJ - t.Applied_Adjustment_TJ).where(t.Fit)
    t["Gap_Proxy_TJ"] = t.Single_AllRY_Median_TJ + t.Applied_Adjustment_TJ
    t["Gap_Resid_TJ"] = (t.RRY_Month_Median_TJ - t.Gap_Proxy_TJ).where(~t.Has_Match & t.Mode.eq("adjust") & ~t.Transplant)

    out = OUT_DIR / "adjusted_single_ry_traces"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.csv"):
        old.unlink()
    floored, allry_rows, mode_days = 0, [], []
    derived, original, filled = {}, {}, set()
    for r in single_recs:
        c = r["Complete"]
        res = apply(pd.DataFrame({"Zone_Key": r["Zone_Key"], "Date": c.Date, "Single_RY_RHS_TJ": c.Value}),
                    r["RY"], ctx)
        expected = pd.date_range(c.Date.min(), OUTPUT_END_DATE, freq="D")
        if len(res) != len(expected) or not (res.Date.to_numpy() == expected.to_numpy()).all() \
                or res.Derived_RHS_TJ.isna().any():
            raise RuntimeError(f"{r['Path'].name}: output is not a complete daily series to {OUTPUT_END_DATE.date()}")
        derived[(r["Zone_Key"], r["RY"])] = res.set_index("Date").Derived_RHS_TJ
        original[(r["Zone_Key"], r["RY"])] = c.set_index("Date").Value
        if c.Source.eq("filled_median_of_other_RYs").all():
            filled.add((r["Zone_Key"], r["RY"]))
        floored += int(res.Floored.sum())
        pd.DataFrame({"Year": res.Date.dt.year, "Month": res.Date.dt.month, "Day": res.Date.dt.day,
                      "Value": res.Derived_RHS_TJ}).to_csv(out / r["Path"].name, index=False)
        allry_rows.append(res.groupby("Month_Start").Derived_RHS_TJ.median().rename("Derived_Month_Median_TJ")
                          .reset_index().assign(Zone_Key=r["Zone_Key"], RY=r["RY"]))
        mode_days.append(res.Mode.value_counts().rename("Days").reset_index().assign(File=r["Path"].name))
    allry = pd.concat(allry_rows, ignore_index=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    level_schedule(lv[lv.Zone_Key.isin(adjust_zones)], OUTPUT_END_DATE).to_csv(OUT_DIR / "level_schedule.csv", index=False)
    t.to_csv(OUT_DIR / "monthly_review.csv", index=False)
    modes.to_csv(OUT_DIR / "zone_fy_modes.csv", index=False)
    if not mo.empty:
        mo.to_csv(OUT_DIR / "median_offset_daily.csv", index=False)
    pd.DataFrame(report, columns=["Series", "Type", "Days", "Dates"]).to_csv(
        OUT_DIR / "fill_and_extension_report.csv", index=False)
    pd.concat(mode_days, ignore_index=True)[["File", "Mode", "Days"]].to_csv(OUT_DIR / "days_by_mode.csv", index=False)

    if MAKE_PLOTS:
        plots(t, dm, adj, lv, se, names, adjust_zones, mo_zones, mo, allry, rry_month)
    if MAKE_DAILY_PLOTS:
        daily_fy_plots(derived, original, filled, rry, names, modes)

    fills = [x for x in report if x["Type"] == "filled_previous_day"]
    print(f"Adjusted traces: {len(single_recs)} files, daily to {OUTPUT_END_DATE.date()}, in {out}")
    print(f"Floored days: {floored:,}; internal gaps filled: {len(fills)} series "
          f"(see fill_and_extension_report.csv)")
    print("Treatment by zone: " + ", ".join(f"{k}={v}" for k, v in st.set_index("Zone_Key").Treatment.items()))
    if adjust_zones:
        last_orig = single.loc[single.Source.eq("original")].groupby("Zone_Key").Date.max()
        t2 = t.assign(Ext=t.Month_Start > t.Zone_Key.map(last_orig))
        summ = t2[t2.Zone_Key.isin(adjust_zones)].groupby("Zone_Key").apply(lambda g: pd.Series({
            "Leftover_Mean": g.Leftover_TJ[~g.Ext].mean(),
            "Leftover_MeanAbs": g.Leftover_TJ[~g.Ext].abs().mean(),
            "Leftover_Mean_Extended": g.Leftover_TJ[g.Ext].mean(),
            "Gap_Resid_Mean": g.Gap_Resid_TJ.mean(),
            "Transplant_Months": int(g.Transplant.sum())}), include_groups=False)
        print("\nAdjust zones (TJ/d). Leftover_Mean near 0 = level about right.")
        print(summ.round(1).to_string())
    if mo_zones:
        dmed = allry.groupby(["Zone_Key", "Month_Start"]).Derived_Month_Median_TJ.median().rename("D").reset_index()
        cmp_ = dmed.merge(rry_month, on=["Zone_Key", "Month_Start"])
        cmp_ = cmp_[cmp_.Zone_Key.isin(mo_zones) & (cmp_.Month_Start >= cmp_.Zone_Key.map(rng["min"]))]
        cmp_["E"] = cmp_.RRY_Month_Median_TJ - cmp_.D
        print(f"\nmedian_offset zones ({SMOOTH_DAYS}-day smoothing). RRY monthly median minus median of derived traces:")
        print(cmp_.groupby("Zone_Key").E.agg(Mean="mean", MeanAbs=lambda x: x.abs().mean()).round(1).to_string())
    print(f"\nReview plots: {OUT_DIR / 'review_plots'}")


if __name__ == "__main__":
    main()
