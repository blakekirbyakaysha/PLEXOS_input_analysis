"""Phase 2: build the daily modelling dataset from Phase 1 raw parquet.

Plain script. Reads data/raw/*.parquet and the fixed inputs (station mapping,
holidays) and writes data/processed/daily_model_dataset.parquet plus the
inspection/quality reports. Makes no API calls.

Run: C:/anaconda3/python.exe -W ignore 02_prepare_daily.py
"""

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
OUTPUTS_DIR = BASE_DIR / "outputs"
INPUTS_DIR = BASE_DIR / "inputs"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

REGIONS = ["NSW1", "QLD1", "SA1", "TAS1", "VIC1"]
GRID_START = dt.date(2001, 1, 1)
GRID_END = dt.date(2026, 8, 31)
FAR_FUTURE = dt.date(2099, 12, 31)

TS_FMT = "%Y-%m-%d %H:%M:%S"

CITY_TO_REGION = {
    "Sydney": "NSW1", "Brisbane": "QLD1", "Adelaide": "SA1",
    "Melbourne": "VIC1", "Hobart": "TAS1",
}
JURIS_TO_REGION = {"nsw": "NSW1", "qld": "QLD1", "sa": "SA1", "tas": "TAS1", "vic": "VIC1"}

AVAIL = {
    "oper": (dt.date(2020, 12, 1), GRID_END),
    "pv": (dt.date(2018, 3, 8), GRID_END),
    "total": (dt.date(2010, 1, 1), GRID_END),
}

report_lines = []  # outputs/input_inspection.md
exclusion_counts = {}  # printed + used in handover


def log(msg=""):
    print(msg)
    report_lines.append(str(msg))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_ts_strict(series, label):
    try:
        return pd.to_datetime(series, format=TS_FMT, errors="raise")
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"{label}: unparseable timestamp(s) in {series.name!r}: {exc}") from exc


def require_columns(df, cols, label):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"{label}: missing required column(s) {missing}; has {list(df.columns)}")


def market_day(ts):
    """Market day = date(timestamp - 1 minute), for interval-ending series."""
    return (ts - pd.Timedelta(minutes=1)).dt.date


def check_regions(df, col, label):
    bad = sorted(set(df[col].unique()) - set(REGIONS))
    if bad:
        raise RuntimeError(f"{label}: unexpected REGIONID value(s) {bad}")


def dedupe_and_check_conflicts(df, key_cols, value_cols, label):
    """Drop exact duplicate rows (and count them). Raise if duplicates on key_cols
    disagree on any value_cols (conflicting duplicates -> hard error, per Spec §3)."""
    n_before = len(df)
    df = df.drop_duplicates()
    n_exact_dup = n_before - len(df)
    conflict_check = df.groupby(key_cols)[value_cols].nunique()
    conflicting = conflict_check[(conflict_check > 1).any(axis=1)]
    if len(conflicting):
        raise RuntimeError(
            f"{label}: {len(conflicting)} key(s) in {key_cols} have conflicting duplicate rows "
            f"(differing {value_cols}), e.g. {conflicting.index[:5].tolist()}"
        )
    return df, n_exact_dup


def full_index(regions, start, end):
    dates = pd.date_range(start, end, freq="D").date
    idx = pd.MultiIndex.from_product([regions, dates], names=["region", "date"])
    return idx.to_frame(index=False)


def full_grid_calendar():
    grid = full_index(REGIONS, GRID_START, GRID_END)
    d = pd.to_datetime(grid["date"])
    grid["year"] = d.dt.year
    grid["month"] = d.dt.month
    grid["doy"] = d.dt.dayofyear
    grid["dow"] = d.dt.dayofweek
    grid["weekend"] = (grid["dow"] >= 5).astype(int)
    grid["fy"] = np.where(grid["month"] <= 6, grid["year"], grid["year"] + 1)
    grid["xmas_period"] = (
        ((grid["month"] == 12) & (d.dt.day >= 24)) | ((grid["month"] == 1) & (d.dt.day <= 2))
    ).astype(int)
    return grid


# ---------------------------------------------------------------------------
# Station mapping
# ---------------------------------------------------------------------------

def parse_date_or_none(s):
    if pd.isna(s) or str(s).strip() == "":
        return None
    return dt.datetime.strptime(str(s).strip(), "%Y-%m-%d").date()


def load_mapping():
    m = pd.read_csv(INPUTS_DIR / "station_mapping.csv", dtype={"bom_site": str, "wmo_id": str})
    require_columns(
        m,
        ["region", "subregion", "station_name", "bom_site", "wmo_id", "valid_from",
         "valid_to", "hdd_threshold", "cdd_threshold"],
        "station_mapping.csv",
    )
    m["valid_from"] = m["valid_from"].apply(parse_date_or_none)
    if m["valid_from"].isna().any():
        raise RuntimeError("station_mapping.csv: valid_from must not be blank")
    m["valid_to"] = m["valid_to"].apply(parse_date_or_none)
    m["wmo_id"] = m["wmo_id"].astype(int)
    check_regions(m.rename(columns={"region": "REGIONID"}), "REGIONID", "station_mapping.csv")
    return m


def check_mapping_coverage(mapping):
    """Hard failure: mapping gap or overlap on any date in the region's required range."""
    checks = {
        "SA1": GRID_START, "VIC1": GRID_START, "TAS1": GRID_START,
        "NSW1": dt.date(2007, 2, 20), "QLD1": dt.date(2007, 2, 20),
    }
    for region, start in checks.items():
        rows = mapping[mapping.region == region].sort_values("valid_from")
        if rows.empty:
            raise RuntimeError(f"station_mapping.csv: no rows for region {region}")
        intervals = [(r.valid_from, r.valid_to or FAR_FUTURE) for r in rows.itertuples()]
        if intervals[0][0] > start:
            raise RuntimeError(
                f"station_mapping.csv: {region} has a mapping gap before {intervals[0][0]} "
                f"(coverage required from {start})"
            )
        for (s1, e1), (s2, e2) in zip(intervals, intervals[1:]):
            expected_next_start = e1 + dt.timedelta(days=1)
            if s2 != expected_next_start:
                raise RuntimeError(
                    f"station_mapping.csv: {region} mapping gap or overlap between {e1} and {s2}"
                )
        if intervals[-1][1] < GRID_END:
            raise RuntimeError(
                f"station_mapping.csv: {region} mapping gap after {intervals[-1][1]} "
                f"(coverage required through {GRID_END})"
            )


def station_day_table(mapping):
    """Long table of (region, date, station_wmo) for every date any mapping row covers,
    clipped to [GRID_START, GRID_END]."""
    frames = []
    for row in mapping.itertuples():
        lo = max(GRID_START, row.valid_from)
        hi = min(GRID_END, row.valid_to or GRID_END)
        if lo > hi:
            continue
        dates = pd.date_range(lo, hi, freq="D").date
        frames.append(pd.DataFrame({"region": row.region, "date": dates, "station_wmo": row.wmo_id}))
    return pd.concat(frames, ignore_index=True)


def region_thresholds(mapping):
    g = mapping.groupby("region")[["hdd_threshold", "cdd_threshold"]].nunique()
    if (g > 1).any(axis=None):
        raise RuntimeError("station_mapping.csv: hdd/cdd threshold differs across rows for the same region")
    return mapping.groupby("region")[["hdd_threshold", "cdd_threshold"]].first()


def temp_availability_start(mapping, region):
    return max(GRID_START, mapping.loc[mapping.region == region, "valid_from"].min())


# ---------------------------------------------------------------------------
# 1. demand_oper
# ---------------------------------------------------------------------------

def prepare_oper(demand_oper):
    require_columns(demand_oper, ["INTERVAL_DATETIME", "REGIONID", "OPERATIONAL_DEMAND"], "demand_oper")
    df = demand_oper.copy()
    check_regions(df, "REGIONID", "demand_oper")
    df["ts"] = parse_ts_strict(df["INTERVAL_DATETIME"], "demand_oper")
    df["date"] = market_day(df["ts"])

    df, n_exact_dup = dedupe_and_check_conflicts(
        df, ["REGIONID", "ts"], ["OPERATIONAL_DEMAND"], "demand_oper"
    )
    # Hard-failure bound: operational demand <= 0 or > 20,000 MW.
    # Deviation (Opus review, Decisions log): SA1 has genuine negative operational
    # demand (rooftop-PV export exceeding load), so SA1 values <= 0 are kept as
    # real data and only counted. Any other region <= 0, or any value > 20,000, fails.
    sa1_neg = (df["REGIONID"] == "SA1") & (df["OPERATIONAL_DEMAND"] <= 0)
    oob_mask = ((df["OPERATIONAL_DEMAND"] <= 0) & ~sa1_neg) | (df["OPERATIONAL_DEMAND"] > 20000)
    if oob_mask.any():
        raise RuntimeError(
            f"demand_oper: OPERATIONAL_DEMAND <= 0 (outside SA1) or > 20,000 MW: "
            f"{df.loc[oob_mask, ['REGIONID', 'INTERVAL_DATETIME', 'OPERATIONAL_DEMAND']].head(10).to_dict('records')}"
        )
    exclusion_counts["oper_sa1_nonpositive_intervals_kept"] = int(sa1_neg.sum())
    exclusion_counts["oper_sa1_min_mw"] = float(df.loc[df["REGIONID"] == "SA1", "OPERATIONAL_DEMAND"].min())

    grp = df.groupby(["REGIONID", "date"])
    agg = grp.agg(
        n_int_oper=("OPERATIONAL_DEMAND", "size"),
        n_null_oper=("OPERATIONAL_DEMAND", lambda s: int(s.isna().sum())),
        valid_n_oper=("OPERATIONAL_DEMAND", lambda s: int(s.notna().sum())),
        sum_mw_oper=("OPERATIONAL_DEMAND", "sum"),
    ).reset_index().rename(columns={"REGIONID": "region"})
    agg["oper_gwh"] = np.where(agg["valid_n_oper"] > 0, agg["sum_mw_oper"] * 0.5 / 1000, np.nan)
    agg["n_dup_oper"] = 0  # no exact duplicates observed; kept for data_quality reasoning

    avail_grid = full_index(REGIONS, *AVAIL["oper"])
    out = avail_grid.merge(agg, on=["region", "date"], how="left")
    for c in ["n_int_oper", "n_null_oper", "n_dup_oper"]:
        out[c] = out[c].fillna(0).astype(int)
    out["ok_oper"] = (out["n_int_oper"] == 48) & (out["n_null_oper"] == 0) & (out["n_dup_oper"] == 0)
    return out[["region", "date", "oper_gwh", "n_int_oper", "n_null_oper", "n_dup_oper", "ok_oper"]], n_exact_dup


# ---------------------------------------------------------------------------
# 2. rooftop_pv
# ---------------------------------------------------------------------------

def prepare_pv(rooftop_pv):
    require_columns(rooftop_pv, ["INTERVAL_DATETIME", "REGIONID", "POWER", "TYPE"], "rooftop_pv")
    df = rooftop_pv.copy()
    if not (df["TYPE"] == "MEASUREMENT").all():
        raise RuntimeError("rooftop_pv: expected TYPE == 'MEASUREMENT' only (Phase 1 should have filtered this)")
    check_regions(df, "REGIONID", "rooftop_pv")
    df["ts"] = parse_ts_strict(df["INTERVAL_DATETIME"], "rooftop_pv")
    df["date"] = market_day(df["ts"])

    if (df["POWER"] < 0).any():
        raise RuntimeError("rooftop_pv: negative POWER value(s) found")

    df, n_exact_dup = dedupe_and_check_conflicts(df, ["REGIONID", "ts"], ["POWER"], "rooftop_pv")

    grp = df.groupby(["REGIONID", "date"])
    agg = grp.agg(
        n_int_pv=("POWER", "size"),
        n_null_pv=("POWER", lambda s: int(s.isna().sum())),
        valid_n_pv=("POWER", lambda s: int(s.notna().sum())),
        sum_mw_pv=("POWER", "sum"),
    ).reset_index().rename(columns={"REGIONID": "region"})
    agg["pv_gwh"] = np.where(agg["valid_n_pv"] > 0, agg["sum_mw_pv"] * 0.5 / 1000, np.nan)
    agg["n_dup_pv"] = 0

    avail_grid = full_index(REGIONS, *AVAIL["pv"])
    out = avail_grid.merge(agg, on=["region", "date"], how="left")
    for c in ["n_int_pv", "n_null_pv", "n_dup_pv"]:
        out[c] = out[c].fillna(0).astype(int)
    out["ok_pv"] = (out["n_int_pv"] == 48) & (out["n_null_pv"] == 0) & (out["n_dup_pv"] == 0)
    return out[["region", "date", "pv_gwh", "n_int_pv", "n_null_pv", "n_dup_pv", "ok_pv"]], n_exact_dup


# ---------------------------------------------------------------------------
# 3. totaldemand_daily
# ---------------------------------------------------------------------------

def prepare_total(totaldemand_daily):
    require_columns(
        totaldemand_daily, ["REGIONID", "MARKET_DATE", "SUM_MW", "N_ROWS", "N_INTERVALS", "N_NULL"],
        "totaldemand_daily",
    )
    df = totaldemand_daily.copy()
    check_regions(df, "REGIONID", "totaldemand_daily")
    df["date"] = parse_ts_strict(df["MARKET_DATE"], "totaldemand_daily").dt.date

    df, n_exact_dup = dedupe_and_check_conflicts(
        df, ["REGIONID", "date"], ["SUM_MW", "N_ROWS", "N_INTERVALS", "N_NULL"], "totaldemand_daily"
    )
    dup_keys = df.duplicated(subset=["REGIONID", "date"], keep=False)
    if dup_keys.any():
        raise RuntimeError("totaldemand_daily: unexpected duplicate (REGIONID, date) rows after dedup")

    df = df.rename(columns={"REGIONID": "region"})
    df["total_gwh"] = df["SUM_MW"] / 12 / 1000
    df["n_dup_total"] = np.clip(df["N_ROWS"] - df["N_INTERVALS"], 0, None)
    df["ok_total"] = (df["N_INTERVALS"] == 288) & (df["N_ROWS"] == 288) & (df["N_NULL"] == 0)

    avail_grid = full_index(REGIONS, *AVAIL["total"])
    out = avail_grid.merge(
        df[["region", "date", "total_gwh", "N_ROWS", "N_INTERVALS", "N_NULL", "n_dup_total", "ok_total"]],
        on=["region", "date"], how="left",
    )
    for c in ["N_ROWS", "N_INTERVALS", "N_NULL", "n_dup_total"]:
        out[c] = out[c].fillna(0).astype(int)
    out["ok_total"] = out["ok_total"].fillna(False).astype(bool)
    out = out.rename(columns={"N_INTERVALS": "n_int_total"})
    return out[["region", "date", "total_gwh", "n_int_total", "N_ROWS", "N_NULL", "n_dup_total", "ok_total"]], n_exact_dup


# ---------------------------------------------------------------------------
# 4. Temperature
# ---------------------------------------------------------------------------

def prepare_metar_daily(metar, mapping):
    require_columns(metar, ["MET_DATETIME", "ID_NUM", "T_DB"], "metar")
    df = metar.copy()

    valid_wmo = set(mapping["wmo_id"].unique())
    bad_ids = sorted(set(df["ID_NUM"].unique()) - valid_wmo)
    if bad_ids:
        raise RuntimeError(f"metar: WMO ID(s) not in station_mapping.csv: {bad_ids}")

    df["ts"] = parse_ts_strict(df["MET_DATETIME"], "metar")

    df, n_exact_dup = dedupe_and_check_conflicts(df, ["ID_NUM", "ts"], ["T_DB"], "metar")
    exclusion_counts["metar_exact_duplicate_rows_dropped"] = n_exact_dup

    # §2 hard-failure bound: T_DB outside [-15, 50].
    # Deviation (documented in PROGRESS): 479 rows carry BoM's own missing-value
    # sentinel T_DB == -9999 (a known BoM fill code, not a real reading). These
    # are dropped as missing observations (they naturally reduce n_obs_temp and
    # can trip the 44-of-48 rule); any *other* out-of-range value is a genuine
    # hard failure.
    oob_mask = (df["T_DB"] < -15) | (df["T_DB"] > 50)
    non_sentinel = df.loc[oob_mask & (df["T_DB"] != -9999)]
    if len(non_sentinel):
        raise RuntimeError(
            f"metar: T_DB outside [-15, 50] and not the -9999 missing sentinel: "
            f"{non_sentinel[['ID_NUM', 'MET_DATETIME', 'T_DB']].head(10).to_dict('records')}"
        )
    n_sentinel = int(oob_mask.sum())
    exclusion_counts["metar_sentinel_-9999_dropped"] = n_sentinel
    df = df.loc[~oob_mask].copy()

    # Regular obs only (minute in {0, 30}); irregular SPECI obs are excluded.
    minute_ok = df["ts"].dt.minute.isin([0, 30])
    exclusion_counts["metar_irregular_minute_obs_dropped"] = int((~minute_ok).sum())
    df = df.loc[minute_ok].copy()

    # Bucket each obs into the model-day window (21:00 d-1, 21:00 d].
    minutes_since_midnight = df["ts"].dt.hour * 60 + df["ts"].dt.minute
    shift_day = (minutes_since_midnight > 21 * 60).astype(int)
    df["bucket_date"] = (df["ts"].dt.normalize() + pd.to_timedelta(shift_day, unit="D")).dt.date

    grp = df.groupby(["ID_NUM", "bucket_date"])["T_DB"].agg(n_obs_temp="size", temp_sum="sum").reset_index()
    grp["mean_temp"] = np.where(grp["n_obs_temp"] >= 44, grp["temp_sum"] / grp["n_obs_temp"], np.nan)
    grp["ok_temp"] = grp["n_obs_temp"] >= 44
    grp = grp.rename(columns={"ID_NUM": "station_wmo", "bucket_date": "date"})
    return grp[["station_wmo", "date", "n_obs_temp", "mean_temp", "ok_temp"]]


def prepare_maxmin_daily(daily_maxmin, mapping):
    require_columns(
        daily_maxmin,
        ["Met_Date", "ID_Num", "Daily_Max_Temperature", "Daily_Min_Temperature", "Daily_Avg_Temperature"],
        "daily_maxmin",
    )
    df = daily_maxmin.copy()
    valid_wmo = set(mapping["wmo_id"].unique())
    bad_ids = sorted(set(df["ID_Num"].unique()) - valid_wmo)
    if bad_ids:
        raise RuntimeError(f"daily_maxmin: WMO ID(s) not in station_mapping.csv: {bad_ids}")

    df["date"] = parse_ts_strict(df["Met_Date"], "daily_maxmin").dt.date
    df, n_exact_dup = dedupe_and_check_conflicts(
        df, ["ID_Num", "date"],
        ["Daily_Max_Temperature", "Daily_Min_Temperature", "Daily_Avg_Temperature"],
        "daily_maxmin",
    )
    exclusion_counts["daily_maxmin_exact_duplicate_rows_dropped"] = n_exact_dup

    df["mean_temp_maxmin"] = np.where(
        df["Daily_Max_Temperature"].notna() & df["Daily_Min_Temperature"].notna(),
        (df["Daily_Max_Temperature"] + df["Daily_Min_Temperature"]) / 2,
        np.nan,
    )
    df["ok_temp_mm"] = df["Daily_Max_Temperature"].notna() & df["Daily_Min_Temperature"].notna()
    df = df.rename(columns={"ID_Num": "station_wmo"})
    return df[["station_wmo", "date", "mean_temp_maxmin", "ok_temp_mm", "Daily_Avg_Temperature"]]


def build_temperature(mapping, metar_daily, maxmin_daily):
    stn_day = station_day_table(mapping)
    thresholds = region_thresholds(mapping)

    out = stn_day.merge(metar_daily, on=["station_wmo", "date"], how="left")
    out = out.merge(maxmin_daily, on=["station_wmo", "date"], how="left")
    for c in ["n_obs_temp"]:
        out[c] = out[c].fillna(0).astype(int)
    out["ok_temp"] = out["ok_temp"].fillna(False).astype(bool)
    out["ok_temp_mm"] = out["ok_temp_mm"].fillna(False).astype(bool)

    out = out.merge(thresholds, left_on="region", right_index=True, how="left")
    out["HDD"] = np.maximum(0, out["hdd_threshold"] - out["mean_temp"])
    out["CDD"] = np.maximum(0, out["mean_temp"] - out["cdd_threshold"])
    out["HDD_mm"] = np.maximum(0, out["hdd_threshold"] - out["mean_temp_maxmin"])
    out["CDD_mm"] = np.maximum(0, out["mean_temp_maxmin"] - out["cdd_threshold"])

    out = out.sort_values(["region", "date"])
    out["HDD_lag1"] = out.groupby("region")["HDD"].shift(1)
    out["CDD_lag1"] = out.groupby("region")["CDD"].shift(1)
    out["HDD_mm_lag1"] = out.groupby("region")["HDD_mm"].shift(1)
    out["CDD_mm_lag1"] = out.groupby("region")["CDD_mm"].shift(1)
    out["ok_temp_lag"] = out.groupby("region")["ok_temp"].shift(1).fillna(False).astype(bool)

    return out[[
        "region", "date", "station_wmo", "n_obs_temp", "mean_temp", "mean_temp_maxmin",
        "HDD", "CDD", "HDD_lag1", "CDD_lag1", "HDD_mm", "CDD_mm", "HDD_mm_lag1", "CDD_mm_lag1",
        "ok_temp", "ok_temp_lag", "ok_temp_mm", "Daily_Avg_Temperature",
    ]]


# ---------------------------------------------------------------------------
# 5. Holidays
# ---------------------------------------------------------------------------

def load_holidays_xlsx():
    xl = pd.read_excel(INPUTS_DIR / "holidays" / "Public holidays.xlsx", sheet_name="Dates")
    require_columns(xl, ["Date", "Public holiday"] + list(CITY_TO_REGION.keys()), "Public holidays.xlsx")
    rows = []
    for city, region in CITY_TO_REGION.items():
        sub = xl.loc[xl[city] == 1.0, ["Date", "Public holiday"]].copy()
        sub["region"] = region
        sub = sub.rename(columns={"Public holiday": "name"})
        sub["date"] = pd.to_datetime(sub["Date"]).dt.date
        rows.append(sub[["date", "region", "name"]])
    out = pd.concat(rows, ignore_index=True).drop_duplicates()
    out["year"] = pd.to_datetime(out["date"]).dt.year
    return out


def load_holidays_csv():
    files = {y: INPUTS_DIR / "holidays" / f"australian_public_holidays_{y}.csv" for y in range(2019, 2026)}
    files[2026] = INPUTS_DIR / "holidays" / "Aus-Holidays-2026.csv"
    frames = []
    for year, path in files.items():
        df = pd.read_csv(path, encoding="latin1")
        require_columns(df, ["Date", "Holiday Name", "Jurisdiction"], path.name)
        n_before = len(df)
        df = df.dropna(subset=["Date"]).copy()
        n_dropped = n_before - len(df)
        if n_dropped:
            exclusion_counts[f"holiday_csv_{year}_rows_without_a_date_dropped"] = n_dropped
        df["date"] = pd.to_datetime(df["Date"].astype(int).astype(str), format="%Y%m%d", errors="raise").dt.date
        df["jurisdiction"] = df["Jurisdiction"].str.strip().str.lower()
        df = df[df["jurisdiction"].isin(JURIS_TO_REGION)].copy()
        df["region"] = df["jurisdiction"].map(JURIS_TO_REGION)
        df["name"] = df["Holiday Name"].str.strip()
        df["year"] = year
        frames.append(df[["date", "region", "name", "year"]])
    return pd.concat(frames, ignore_index=True).drop_duplicates()


def build_holidays():
    xlsx = load_holidays_xlsx()
    csv = load_holidays_csv()

    xlsx_use = xlsx[xlsx["year"] <= 2018]
    csv_use = csv[(csv["year"] >= 2019) & (csv["year"] <= 2026)]
    final = pd.concat([xlsx_use[["date", "region"]], csv_use[["date", "region"]]], ignore_index=True).drop_duplicates()
    final["holiday"] = 1

    # Overlap years 2019-2023: xlsx has these years too; write mismatches (informational).
    overlap_years = range(2019, 2024)
    xlsx_overlap = set(map(tuple, xlsx[xlsx["year"].isin(overlap_years)][["date", "region"]].values.tolist()))
    csv_overlap = set(map(tuple, csv[(csv["year"].isin(overlap_years))][["date", "region"]].values.tolist()))
    only_xlsx = xlsx_overlap - csv_overlap
    only_csv = csv_overlap - xlsx_overlap
    mismatch_rows = (
        [{"date": d, "region": r, "in_xlsx": True, "in_csv": False} for d, r in sorted(only_xlsx)]
        + [{"date": d, "region": r, "in_xlsx": False, "in_csv": True} for d, r in sorted(only_csv)]
    )
    mismatch_df = pd.DataFrame(mismatch_rows, columns=["date", "region", "in_xlsx", "in_csv"])
    mismatch_df.to_csv(OUTPUTS_DIR / "holiday_mismatch.csv", index=False)
    exclusion_counts["holiday_mismatch_rows_2019_2023"] = len(mismatch_df)

    return final[["date", "region", "holiday"]]


# ---------------------------------------------------------------------------
# Inspection report
# ---------------------------------------------------------------------------

def mode_diff_minutes(ts_series):
    d = ts_series.sort_values().diff().dropna()
    if d.empty:
        return None
    return d.dt.total_seconds().mode().iloc[0] / 60


def inspect_source(name, df, ts_col, id_col, id_label, unit_note, group_col=None):
    log(f"\n### {name}\n")
    log(f"- columns and dtypes:\n\n```\n{df.dtypes}\n```\n")
    ts = pd.to_datetime(df[ts_col], format=TS_FMT, errors="coerce")
    log(f"- date coverage: {ts.min()} to {ts.max()}")
    if id_col:
        ids = sorted(df[id_col].unique().tolist())
        log(f"- {id_label} present ({len(ids)}): {ids}")
    if group_col:
        diffs = []
        for _, g in df.assign(_ts=ts).groupby(group_col):
            m = mode_diff_minutes(g["_ts"])
            if m is not None:
                diffs.append(m)
        if diffs:
            log(f"- interval resolution (mode of diffs per {group_col}, minutes): "
                f"min {min(diffs)}, median {pd.Series(diffs).median()}, max {max(diffs)}")
    na_counts = df.isna().sum()
    log(f"- missing-value counts:\n\n```\n{na_counts[na_counts > 0]}\n```\n" if (na_counts > 0).any()
        else "- missing-value counts: none")
    log(f"- units: {unit_note}")


# ---------------------------------------------------------------------------
# data_quality.csv
# ---------------------------------------------------------------------------

def quality_rows(df, series, expected, avail_start, avail_end, n_int_col, n_null_col, n_dup_col, ok_col):
    d = df.loc[(df["date"] >= avail_start) & (df["date"] <= avail_end) & (~df[ok_col])].copy()
    rows = []
    for r in d.itertuples():
        n_int = getattr(r, n_int_col)
        n_null = getattr(r, n_null_col)
        n_dup = getattr(r, n_dup_col)
        reasons = []
        if n_int < expected:
            reasons.append("missing intervals")
        elif n_int > expected:
            reasons.append("extra intervals")
        if n_dup > 0:
            reasons.append("duplicate")
        if n_null > 0:
            reasons.append("NaN value")
        if not reasons:
            reasons.append("NaN value")  # e.g. energy NaN with count matching but all-null edge case
        for reason in reasons:
            rows.append({"region": r.region, "date": r.date, "series": series, "reason": reason})
    return pd.DataFrame(rows, columns=["region", "date", "series", "reason"])


def quality_rows_temp(temp_df):
    rows = []
    for region in REGIONS:
        start = temp_availability_start(load_mapping(), region)
        d = temp_df[(temp_df["region"] == region) & (temp_df["date"] >= start) & (temp_df["date"] <= GRID_END)
                    & (~temp_df["ok_temp"])]
        for r in d.itertuples():
            rows.append({"region": r.region, "date": r.date, "series": "temp", "reason": "insufficient temperature obs"})
    return pd.DataFrame(rows, columns=["region", "date", "series", "reason"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("# Phase 2 input inspection\n")

    mapping = load_mapping()
    check_mapping_coverage(mapping)

    demand_oper = pd.read_parquet(RAW_DIR / "demand_oper.parquet")
    totaldemand_daily = pd.read_parquet(RAW_DIR / "totaldemand_daily.parquet")
    rooftop_pv = pd.read_parquet(RAW_DIR / "rooftop_pv.parquet")
    metar = pd.read_parquet(RAW_DIR / "metar.parquet")
    daily_maxmin = pd.read_parquet(RAW_DIR / "daily_maxmin.parquet")

    inspect_source("demand_oper (mms.demandoperationalactual)", demand_oper, "INTERVAL_DATETIME", "REGIONID",
                    "REGIONID", "MW", group_col="REGIONID")
    inspect_source("totaldemand_daily (mms.dispatchregionsum, pre-aggregated)", totaldemand_daily, "MARKET_DATE",
                    "REGIONID", "REGIONID", "MW (summed to GWh in Phase 2)")
    inspect_source("rooftop_pv (mms.rooftop_pv_actual, MEASUREMENT)", rooftop_pv, "INTERVAL_DATETIME", "REGIONID",
                    "REGIONID", "MW", group_col="REGIONID")
    inspect_source("metar (bom.metar)", metar, "MET_DATETIME", "ID_NUM", "WMO ID", "degrees C",
                    group_col="ID_NUM")
    inspect_source("daily_maxmin (bom.daily_max_min_temperature)", daily_maxmin, "Met_Date", "ID_Num", "WMO ID",
                    "degrees C")

    # ---- demand / PV / total ----
    oper_df, oper_dup = prepare_oper(demand_oper)
    pv_df, pv_dup = prepare_pv(rooftop_pv)
    total_df, total_dup = prepare_total(totaldemand_daily)
    exclusion_counts["demand_oper_exact_duplicate_rows_dropped"] = oper_dup
    exclusion_counts["rooftop_pv_exact_duplicate_rows_dropped"] = pv_dup
    exclusion_counts["totaldemand_daily_exact_duplicate_rows_dropped"] = total_dup

    # ---- temperature ----
    metar_daily = prepare_metar_daily(metar, mapping)
    maxmin_daily = prepare_maxmin_daily(daily_maxmin, mapping)
    temp_df = build_temperature(mapping, metar_daily, maxmin_daily)

    # ---- holidays ----
    holidays = build_holidays()

    # ---- assemble ----
    grid = full_grid_calendar()
    out = grid.merge(oper_df, on=["region", "date"], how="left")
    out = out.merge(pv_df, on=["region", "date"], how="left")
    out = out.merge(total_df, on=["region", "date"], how="left")
    out = out.merge(temp_df, on=["region", "date"], how="left")
    out = out.merge(holidays, on=["region", "date"], how="left")
    out["holiday"] = out["holiday"].fillna(0).astype(int)

    out["underlying_gwh"] = out["oper_gwh"] + out["pv_gwh"]
    out["ok_oper"] = out["ok_oper"].fillna(False).astype(bool)
    out["ok_pv"] = out["ok_pv"].fillna(False).astype(bool)
    out["ok_underlying"] = out["ok_oper"] & out["ok_pv"]
    out["total_pv_gwh"] = out["total_gwh"] + out["pv_gwh"]
    out["ok_total"] = out["ok_total"].fillna(False).astype(bool)
    out["ok_total_pv"] = out["ok_total"] & out["ok_pv"]
    out["ok_temp"] = out["ok_temp"].fillna(False).astype(bool)
    out["ok_temp_lag"] = out["ok_temp_lag"].fillna(False).astype(bool)
    out["ok_temp_mm"] = out["ok_temp_mm"].fillna(False).astype(bool)
    for c in ["n_int_oper", "n_int_pv", "n_int_total", "n_obs_temp"]:
        out[c] = out[c].fillna(0).astype(int)

    cols = [
        "region", "date", "year", "fy", "month", "doy", "dow", "weekend", "holiday", "xmas_period",
        "station_wmo", "n_obs_temp", "mean_temp", "mean_temp_maxmin",
        "HDD", "CDD", "HDD_lag1", "CDD_lag1", "HDD_mm", "CDD_mm", "HDD_mm_lag1", "CDD_mm_lag1",
        "oper_gwh", "pv_gwh", "underlying_gwh", "total_gwh", "total_pv_gwh",
        "n_int_oper", "n_int_pv", "n_int_total",
        "ok_oper", "ok_pv", "ok_underlying", "ok_total", "ok_total_pv", "ok_temp", "ok_temp_lag", "ok_temp_mm",
    ]
    full = out.sort_values(["region", "date"]).reset_index(drop=True)  # keeps Daily_Avg_Temperature for checks
    out = full[cols]

    if out.duplicated(subset=["region", "date"]).any():
        raise RuntimeError("daily_model_dataset: (region, date) is not unique")

    out.to_parquet(PROCESSED_DIR / "daily_model_dataset.parquet", index=False)
    (OUTPUTS_DIR / "input_inspection.md").write_text("\n".join(report_lines), encoding="utf-8")

    # ---- data_quality.csv ----
    dq_oper = quality_rows(out.merge(oper_df[["region", "date", "n_int_oper", "n_null_oper", "n_dup_oper"]],
                                      on=["region", "date"], how="left", suffixes=("", "_r")),
                            "oper", 48, *AVAIL["oper"], "n_int_oper_r", "n_null_oper", "n_dup_oper", "ok_oper")
    dq_pv = quality_rows(out.merge(pv_df[["region", "date", "n_int_pv", "n_null_pv", "n_dup_pv"]],
                                    on=["region", "date"], how="left", suffixes=("", "_r")),
                          "pv", 48, *AVAIL["pv"], "n_int_pv_r", "n_null_pv", "n_dup_pv", "ok_pv")
    dq_total = quality_rows(out.merge(total_df[["region", "date", "N_ROWS", "N_NULL", "n_dup_total"]],
                                       on=["region", "date"], how="left"),
                             "total", 288, *AVAIL["total"], "N_ROWS", "N_NULL", "n_dup_total", "ok_total")
    dq_temp = quality_rows_temp(out)

    dq = pd.concat([dq_oper, dq_pv, dq_total, dq_temp], ignore_index=True)
    dq.to_csv(OUTPUTS_DIR / "data_quality.csv", index=False)

    log("\n## Exclusion / data-quality summary\n")
    summary = dq.groupby(["region", "series", "reason"]).size().reset_index(name="n")
    log(summary.to_string(index=False))
    print("\nExclusion counts:")
    for k, v in exclusion_counts.items():
        print(f"  {k}: {v}")

    # ---- acceptance / reviewer checks ----
    print("\n=== Acceptance checks ===")
    print("(region, date) unique:", not out.duplicated(subset=["region", "date"]).any())

    do = demand_oper.copy()
    do["ts"] = parse_ts_strict(do["INTERVAL_DATETIME"], "check")
    do["date"] = market_day(do["ts"])
    day_rows = do[(do["REGIONID"] == "NSW1") & (do["date"] == dt.date(2024, 1, 3))]
    hand_gwh = day_rows["OPERATIONAL_DEMAND"].sum() * 0.5 / 1000
    script_gwh = out.loc[(out.region == "NSW1") & (out.date == dt.date(2024, 1, 3)), "oper_gwh"].iloc[0]
    print(f"NSW1 2024-01-03 oper_gwh: hand {hand_gwh:.6f} vs script {script_gwh:.6f} "
          f"(n_intervals={len(day_rows)})")

    m = metar.copy()
    m["ts"] = parse_ts_strict(m["MET_DATETIME"], "check")
    win = m[(m["ID_NUM"] == 94765) & (m["ts"].dt.minute.isin([0, 30]))
            & (m["ts"] > pd.Timestamp("2024-01-02 21:00:00")) & (m["ts"] <= pd.Timestamp("2024-01-03 21:00:00"))]
    hand_mean = win["T_DB"].mean()
    script_mean = out.loc[(out.region == "NSW1") & (out.date == dt.date(2024, 1, 3)), "mean_temp"].iloc[0]
    print(f"Bankstown 2024-01-03 mean_temp: hand {hand_mean:.6f} (n={len(win)}) vs script {script_mean:.6f}")

    print("\n=== Reviewer checks ===")
    for region in REGIONS:
        wmo_ids = mapping.loc[mapping.region == region, "wmo_id"].unique()
        for wmo in wmo_ids:
            merged = full.loc[
                (full.region == region) & (full.station_wmo == wmo)
                & full["mean_temp"].notna() & full["Daily_Avg_Temperature"].notna()
            ]
            if len(merged) < 2:
                continue
            corr = merged["mean_temp"].corr(merged["Daily_Avg_Temperature"])
            print(f"  {region} station {wmo}: corr(mean_temp, Daily_Avg_Temperature) n={len(merged)} r={corr:.4f}")

    for region, switch_date in [("SA1", dt.date(2020, 8, 1)), ("VIC1", dt.date(2015, 1, 6))]:
        before = out.loc[(out.region == region) & (out.date == switch_date - dt.timedelta(days=1)), "station_wmo"]
        after = out.loc[(out.region == region) & (out.date == switch_date), "station_wmo"]
        print(f"  {region} switch {switch_date}: day before station={before.iloc[0] if len(before) else None}, "
              f"switch day station={after.iloc[0] if len(after) else None}")

    for region in REGIONS:
        sub = out[(out.region == region) & out["oper_gwh"].notna() & out["total_gwh"].notna()]
        if len(sub) > 1:
            print(f"  {region}: corr(oper_gwh, total_gwh) n={len(sub)} r={sub['oper_gwh'].corr(sub['total_gwh']):.4f}")

    print(f"\nRows written: {len(out)}  ->  data/processed/daily_model_dataset.parquet")


if __name__ == "__main__":
    main()
