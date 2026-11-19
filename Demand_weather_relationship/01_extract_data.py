"""Phase 1: pull raw NEM demand, rooftop-PV and BoM weather data from QueryTool.

Plain extraction script. Does not transform anything beyond column selection
(and, for totaldemand_daily and pv_satellite_annual, the SQL aggregation the
task card specifies). Each chunk is cached as data/raw/<source>/<chunk>.parquet;
a chunk already on disk is skipped (no re-query). At the end each source's
chunks are concatenated into data/raw/<source>.parquet. Delete cached files to
refresh.

Run: C:/anaconda3/python.exe -W ignore 01_extract_data.py
"""

import datetime as dt
from pathlib import Path

import pandas as pd

from helper_functions import qt_post_request

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
OUTPUTS_DIR = BASE_DIR / "outputs"
RAW_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

REGIONS = ["NSW1", "QLD1", "SA1", "TAS1", "VIC1"]
REGION_LIST_SQL = ", ".join(f"'{r}'" for r in REGIONS)

# Overall caps used by the metar/daily_maxmin station ranges (task card).
FLOOR_DATE = dt.date(2000, 12, 31)
CAP_DATE = dt.date(2026, 9, 1)

queries_run = 0  # number of chunk queries actually issued this run (cache misses)


def _ts(d):
    """Format a date as a query-string timestamp at 00:00:00."""
    return dt.datetime.combine(d, dt.time.min).strftime("%Y-%m-%d %H:%M:%S")


def year_bounds(year, overall_start, overall_end):
    """Clip a calendar year to an overall [overall_start, overall_end) range."""
    lo = max(overall_start, dt.date(year, 1, 1))
    hi = min(overall_end, dt.date(year + 1, 1, 1))
    return lo, hi


def run_chunk(source, chunk_id, build_sql, required_columns):
    """Run one chunk query unless already cached. Returns True if a query was issued.

    QueryTool streams CSV; a stalled query can return HTTP 200 with the stream cut
    mid-file (observed: 29 rows ending at a half-written timestamp). So the same
    query is counted server-side and the chunk is only cached if the counts match.
    """
    global queries_run
    source_dir = RAW_DIR / source
    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / f"{chunk_id}.parquet"
    if path.exists():
        return False
    print(f"  querying {source}/{chunk_id} ...")
    sql = build_sql()
    df = qt_post_request(sql, required_columns=required_columns)
    n_expected = int(qt_post_request(f"SELECT count(*) AS N FROM ({sql}) q", required_columns=["N"])["N"].iloc[0])
    if len(df) != n_expected:
        raise RuntimeError(
            f"{source}/{chunk_id}: received {len(df)} rows but the query has {n_expected} "
            f"(truncated response; not cached)"
        )
    df.to_parquet(path, index=False)
    queries_run += 1
    return True


def concat_source(source):
    """Concatenate every cached chunk for a source into data/raw/<source>.parquet."""
    source_dir = RAW_DIR / source
    files = sorted(source_dir.glob("*.parquet"))
    if not files:
        raise RuntimeError(f"No cached chunks found for {source}; extraction did not run")
    frames = [pd.read_parquet(f) for f in files]
    combined = pd.concat(frames, ignore_index=True)
    combined.to_parquet(RAW_DIR / f"{source}.parquet", index=False)
    return combined


# ---------------------------------------------------------------------------
# 1. demand_oper: mms.demandoperationalactual, one query per calendar year.
# ---------------------------------------------------------------------------

DEMAND_OPER_START = dt.date(2020, 12, 1)
DEMAND_OPER_END = dt.date(2026, 9, 1)
DEMAND_OPER_COLUMNS = [
    "INTERVAL_DATETIME", "REGIONID", "OPERATIONAL_DEMAND",
    "OPERATIONAL_DEMAND_ADJUSTMENT", "WDR_ESTIMATE", "LASTCHANGED",
]


def extract_demand_oper():
    print("== demand_oper ==")
    for year in range(DEMAND_OPER_START.year, DEMAND_OPER_END.year + 1):
        lo, hi = year_bounds(year, DEMAND_OPER_START, DEMAND_OPER_END)
        if lo >= hi:
            continue

        def build(lo=lo, hi=hi):
            return f"""
            SELECT {', '.join(DEMAND_OPER_COLUMNS)}
            FROM mms.demandoperationalactual
            WHERE INTERVAL_DATETIME > '{_ts(lo)}' AND INTERVAL_DATETIME <= '{_ts(hi)}'
            AND REGIONID IN ({REGION_LIST_SQL})
            """

        run_chunk("demand_oper", str(year), build, DEMAND_OPER_COLUMNS)
    return concat_source("demand_oper")


# ---------------------------------------------------------------------------
# 2. totaldemand_daily: mms.dispatchregionsum, one query per calendar month,
#    aggregated in SQL to region/market-day.
# ---------------------------------------------------------------------------

TOTALDEMAND_START = dt.date(2010, 1, 1)
TOTALDEMAND_END = dt.date(2026, 9, 1)  # covers 2026-08 inclusive
TOTALDEMAND_COLUMNS = ["REGIONID", "MARKET_DATE", "SUM_MW", "N_ROWS", "N_INTERVALS", "N_NULL"]


def extract_totaldemand_daily():
    print("== totaldemand_daily ==")
    months = pd.period_range(
        start=f"{TOTALDEMAND_START:%Y-%m}",
        end="2026-08",
        freq="M",
    )
    for period in months:
        lo = period.start_time.date()
        hi = (period + 1).start_time.date()
        chunk_id = str(period)

        def build(lo=lo, hi=hi):
            return f"""
            SELECT REGIONID,
                DATE(DATE_SUB(SETTLEMENTDATE, INTERVAL 1 MINUTE)) as MARKET_DATE,
                sum(TOTALDEMAND) as SUM_MW,
                count(*) as N_ROWS,
                count(distinct SETTLEMENTDATE) as N_INTERVALS,
                sum(case when TOTALDEMAND is null then 1 else 0 end) as N_NULL
            FROM mms.dispatchregionsum
            WHERE SETTLEMENTDATE > '{_ts(lo)}' AND SETTLEMENTDATE <= '{_ts(hi)}'
            AND INTERVENTION = 0
            AND REGIONID IN ({REGION_LIST_SQL})
            GROUP BY REGIONID, MARKET_DATE
            ORDER BY REGIONID, MARKET_DATE
            """

        run_chunk("totaldemand_daily", chunk_id, build, TOTALDEMAND_COLUMNS)
    return concat_source("totaldemand_daily")


# ---------------------------------------------------------------------------
# 3. rooftop_pv: mms.rooftop_pv_actual, TYPE = 'MEASUREMENT', one query per year.
#    Plus a single small SATELLITE annual-total query.
# ---------------------------------------------------------------------------

PV_START = dt.date(2018, 3, 8)
PV_END = dt.date(2026, 9, 1)
PV_COLUMNS = ["INTERVAL_DATETIME", "REGIONID", "POWER", "TYPE", "QI"]


def extract_rooftop_pv():
    print("== rooftop_pv ==")
    for year in range(PV_START.year, PV_END.year + 1):
        lo, hi = year_bounds(year, PV_START, PV_END)
        if lo >= hi:
            continue

        def build(lo=lo, hi=hi):
            return f"""
            SELECT {', '.join(PV_COLUMNS)}
            FROM mms.rooftop_pv_actual
            WHERE INTERVAL_DATETIME > '{_ts(lo)}' AND INTERVAL_DATETIME <= '{_ts(hi)}'
            AND TYPE = 'MEASUREMENT'
            AND REGIONID IN ({REGION_LIST_SQL})
            """

        run_chunk("rooftop_pv", str(year), build, PV_COLUMNS)
    return concat_source("rooftop_pv")


def extract_pv_satellite_annual():
    print("== pv_satellite_annual ==")
    global queries_run
    path = RAW_DIR / "pv_satellite_annual.parquet"
    if path.exists():
        return pd.read_parquet(path)
    sql = f"""
    SELECT REGIONID, YEAR(INTERVAL_DATETIME) as YR, sum(POWER)*0.5/1000 as GWH
    FROM mms.rooftop_pv_actual
    WHERE TYPE = 'SATELLITE'
    AND REGIONID IN ({REGION_LIST_SQL})
    AND INTERVAL_DATETIME > '{_ts(PV_START)}' AND INTERVAL_DATETIME <= '{_ts(PV_END)}'
    GROUP BY REGIONID, YR
    ORDER BY REGIONID, YR
    """
    print("  querying pv_satellite_annual ...")
    df = qt_post_request(sql, required_columns=["REGIONID", "YR", "GWH"])
    df.to_parquet(path, index=False)
    queries_run += 1
    return df


# ---------------------------------------------------------------------------
# 4/5. metar and daily_maxmin: bom.metar / bom.daily_max_min_temperature,
#      per mapped WMO ID over that station's valid date range.
# ---------------------------------------------------------------------------

def load_station_mapping():
    mapping = pd.read_csv(
        BASE_DIR / "inputs" / "station_mapping.csv",
        dtype={"bom_site": str, "wmo_id": str},
    )
    mapping["valid_from"] = pd.to_datetime(mapping["valid_from"]).dt.date
    mapping["valid_to"] = pd.to_datetime(mapping["valid_to"], errors="coerce")
    return mapping


def station_range(row):
    """Return (lo, hi) date range for a station: lo inclusive, hi exclusive."""
    lo = max(FLOOR_DATE, row["valid_from"] - dt.timedelta(days=1))
    if pd.isna(row["valid_to"]):
        hi = CAP_DATE
    else:
        hi = min(row["valid_to"].date() + dt.timedelta(days=1), CAP_DATE)
    return lo, hi


METAR_COLUMNS = ["MET_DATETIME", "ID_NUM", "T_DB"]


def extract_metar(mapping):
    # One query per calendar month covering every mapped station, each clipped to
    # its own range (deviation, 2026-09-25). bom.metar's primary key leads with
    # MET_DATETIME, so a month query scans all stations whatever the ID filter;
    # year-sized queries stall past the proxy limit and return truncated streams.
    print("== metar ==")
    ranges = [(row["wmo_id"], *station_range(row)) for _, row in mapping.iterrows()]
    start = min(lo for _, lo, _ in ranges)
    end = max(hi for _, _, hi in ranges)
    for period in pd.period_range(start=f"{start:%Y-%m}", end=f"{end - dt.timedelta(days=1):%Y-%m}", freq="M"):
        plo = period.start_time.date()
        phi = (period + 1).start_time.date()
        clauses = []
        for wmo, lo, hi in ranges:
            mlo, mhi = max(lo, plo), min(hi, phi)
            if mlo < mhi:
                clauses.append(
                    f"(ID_NUM = '{wmo}' AND MET_DATETIME >= '{_ts(mlo)}' AND MET_DATETIME < '{_ts(mhi)}')"
                )

        def build(plo=plo, phi=phi, clauses=clauses):
            return f"""
            SELECT MET_DATETIME, ID_NUM, T_DB
            FROM bom.metar
            WHERE MET_DATETIME >= '{_ts(plo)}' AND MET_DATETIME < '{_ts(phi)}'
            AND ({' OR '.join(clauses)})
            """

        run_chunk("metar", str(period), build, METAR_COLUMNS)
    return concat_source("metar")


DAILY_MAXMIN_COLUMNS = [
    "Met_Date", "ID_Num", "Daily_Max_Temperature", "Daily_Min_Temperature", "Daily_Avg_Temperature",
]


def extract_daily_maxmin(mapping):
    print("== daily_maxmin ==")
    for _, row in mapping.iterrows():
        wmo = row["wmo_id"]
        lo, hi = station_range(row)

        def build(lo=lo, hi=hi, wmo=wmo):
            return f"""
            SELECT Met_Date, ID_Num, Daily_Max_Temperature, Daily_Min_Temperature, Daily_Avg_Temperature
            FROM bom.daily_max_min_temperature
            WHERE ID_Num = '{wmo}'
            AND Met_Date >= '{_ts(lo)}' AND Met_Date < '{_ts(hi)}'
            """

        run_chunk("daily_maxmin", str(wmo), build, DAILY_MAXMIN_COLUMNS)
    return concat_source("daily_maxmin")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def market_day(timestamps):
    """Market day = date(timestamp - 1 minute), for interval-ending series."""
    return (pd.to_datetime(timestamps) - pd.Timedelta(minutes=1)).dt.date


def rows_per_group_stats(df, group_cols):
    counts = df.groupby(group_cols).size()
    return counts.min(), counts.median(), counts.max()


def fmt_stats(label, counts):
    lo, med, hi = counts
    return f"{label}: min {lo}, median {med}, max {hi}"


def summarize(lines, name, df, ts_col, id_cols, per_day_group=None, per_day_label=None):
    lines.append(f"\n### {name}\n")
    lines.append(f"- rows: {len(df)}")
    ts = pd.to_datetime(df[ts_col])
    lines.append(f"- {ts_col} range: {ts.min()} to {ts.max()}")
    for col in id_cols:
        vals = sorted(df[col].unique().tolist())
        lines.append(f"- distinct {col} ({len(vals)}): {vals}")
    if per_day_group is not None:
        lo, med, hi = rows_per_group_stats(df, per_day_group)
        lines.append(f"- {per_day_label} per group: min {lo}, median {med}, max {hi}")
    return lines


def write_summary(demand_oper, totaldemand_daily, rooftop_pv, pv_satellite_annual, metar, daily_maxmin):
    lines = ["# Phase 1 extract summary\n"]

    demand_oper = demand_oper.assign(MARKET_DAY=market_day(demand_oper["INTERVAL_DATETIME"]))
    summarize(
        lines, "demand_oper", demand_oper, "INTERVAL_DATETIME", ["REGIONID"],
        per_day_group=["REGIONID", "MARKET_DAY"], per_day_label="obs",
    )

    lines.append("\n### totaldemand_daily\n")
    lines.append(f"- rows: {len(totaldemand_daily)}")
    md = pd.to_datetime(totaldemand_daily["MARKET_DATE"])
    lines.append(f"- MARKET_DATE range: {md.min()} to {md.max()}")
    regs = sorted(totaldemand_daily["REGIONID"].unique().tolist())
    lines.append(f"- distinct REGIONID ({len(regs)}): {regs}")
    ni = totaldemand_daily["N_INTERVALS"]
    lines.append(f"- N_INTERVALS: min {ni.min()}, median {ni.median()}, max {ni.max()}")
    pct288 = (ni == 288).mean() * 100
    lines.append(f"- share of region-days with N_INTERVALS == 288: {pct288:.2f}%")
    lines.append(f"- total N_NULL: {int(totaldemand_daily['N_NULL'].sum())}")

    rooftop_pv = rooftop_pv.assign(MARKET_DAY=market_day(rooftop_pv["INTERVAL_DATETIME"]))
    summarize(
        lines, "rooftop_pv (MEASUREMENT)", rooftop_pv, "INTERVAL_DATETIME", ["REGIONID", "TYPE"],
        per_day_group=["REGIONID", "MARKET_DAY"], per_day_label="obs",
    )

    lines.append("\n### pv_satellite_annual\n")
    lines.append(f"- rows: {len(pv_satellite_annual)}")
    lines.append(pv_satellite_annual.to_string(index=False))

    metar = metar.assign(DAY=pd.to_datetime(metar["MET_DATETIME"]).dt.date)
    summarize(
        lines, "metar", metar, "MET_DATETIME", ["ID_NUM"],
        per_day_group=["ID_NUM", "DAY"], per_day_label="obs",
    )

    summarize(
        lines, "daily_maxmin", daily_maxmin, "Met_Date", ["ID_Num"],
    )

    text = "\n".join(str(x) for x in lines)
    print(text)
    (OUTPUTS_DIR / "extract_summary.md").write_text(text, encoding="utf-8")


def main():
    mapping = load_station_mapping()

    demand_oper = extract_demand_oper()
    totaldemand_daily = extract_totaldemand_daily()
    rooftop_pv = extract_rooftop_pv()
    pv_satellite_annual = extract_pv_satellite_annual()
    metar = extract_metar(mapping)
    daily_maxmin = extract_daily_maxmin(mapping)

    write_summary(demand_oper, totaldemand_daily, rooftop_pv, pv_satellite_annual, metar, daily_maxmin)

    print(f"\nQueries issued this run: {queries_run}")


if __name__ == "__main__":
    main()
