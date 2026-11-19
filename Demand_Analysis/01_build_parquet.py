"""
Step 1: read AEMO trace CSVs (loose, zipped, or nested zips) from data/raw/ and
write one long-format file, data/parquet/demand_traces.parquet.

Run: python 01_build_parquet.py
"""

from pathlib import Path
from zipfile import ZipFile
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import re

from demand_lib.paths import RAW_DIR, PARQUET_FILE

# =============================================================================
# CONFIG
# =============================================================================

# One entry per dataset. "dataset" is the name used by every later script to
# select it (DATASET in 02/03/04 and in the output folder name). Each path may
# be a folder of CSVs, a zip, or a zip of zips, placed under data/raw/.
INPUT_SOURCES = [
    {
        "dataset": "ISP_STEP_CHANGE_2026",
        "source": "ISP",
        "scenario": "STEP_CHANGE",
        "path": RAW_DIR / "ISP_Step_Change_2026",
    },
    {
        "dataset": "ISP_NSW_STEP_CHANGE_POE50",
        "source": "ISP",
        "scenario": "STEP_CHANGE",
        "path": RAW_DIR / "ISP_NSW_Step_Change_POE50.zip",
    },
    {
        "dataset": "ESOO_2026_Central",
        "source": "ESOO",
        "scenario": "CENTRAL",
        "path": RAW_DIR / "ESOO_2026_POE50.zip",
    },
    # {
    #     "dataset": "INTERNAL_CENTRAL_V1",
    #     "source": "INTERNAL",
    #     "scenario": "CENTRAL",
    #     "path": RAW_DIR / "Internal_Central",
    # },
]

OUTPUT_FILE = PARQUET_FILE

TARGET_POES = ["POE50"]

TARGET_TRACES = [
    "OPSO_MODELLING",
    "PV_TOT",
    "ESS",
    "EV",
]


# =============================================================================
# SCHEMA (fixed, so every chunk written is compatible)
# =============================================================================

SCHEMA = pa.schema([
    ("datetime", pa.timestamp("ns")),
    ("demand", pa.float32()),
    ("dataset", pa.string()),
    ("source", pa.string()),
    ("scenario", pa.string()),
    ("region", pa.string()),
    ("subregion", pa.string()),
    ("reference_year", pa.int16()),
    ("poe", pa.int16()),
    ("trace_type", pa.string()),
    ("source_file", pa.string()),
])

COLUMN_ORDER = [f.name for f in SCHEMA]


# =============================================================================
# FILENAME PARSER
# =============================================================================

FILENAME_PATTERN = re.compile(
    r"""
    ^
    (?P<region>[A-Z]+)_
    (?:(?P<subregion>[A-Z]+)_)?
    RefYear_
    (?P<reference_year>\d{4})_
    (?P<scenario>.*?)_
    POE(?P<poe>\d+)_
    (?P<trace_suffix>.+)
    $
    """,
    re.VERBOSE,
)

# Everything after the POE token identifies the trace. Supported forms include:
#
#   ..._POE50_OPSO_MODELLING
#   ..._POE50_OPSO_MODELLING_PVLITE
#   ..._POE50_PV_TOT
#   ..._POE50_ESS
#   ..._POE50_EV
#
# The suffix is matched whole, so OPSO_MODELLING_PVLITE cannot be mistaken
# for OPSO_MODELLING. Anything unrecognised is passed through verbatim rather
# than being silently dropped.

TRACE_TYPE_MAP = {
    "OPSO_MODELLING_PVLITE": "PV_LITE",
    "OPSO_MODELLING": "OPSO_MODELLING",
    "PV_TOT": "PV_TOT",
    "ESS": "ESS",
    "EV": "EV",
}


def extract_metadata(filename):

    match = FILENAME_PATTERN.match(Path(filename).stem)

    if not match:
        return {
            "region": None,
            "subregion": None,
            "reference_year": None,
            "scenario": None,
            "poe": None,
            "trace_type": None,
        }

    d = match.groupdict()

    suffix = d.pop("trace_suffix").upper().strip("_")

    return {
        "region": d["region"],
        "subregion": d["subregion"],
        "reference_year": int(d["reference_year"]),
        "scenario": d["scenario"].upper(),
        "poe": int(d["poe"]),
        "trace_type": TRACE_TYPE_MAP.get(suffix, suffix),
    }
# =============================================================================
# FILE FILTERING
# =============================================================================

def is_target_file(filename):
    filename = filename.upper()

    return (
        filename.endswith(".CSV")
        and any(poe in filename for poe in TARGET_POES)
        and any(trace in filename for trace in TARGET_TRACES)
    )

# =============================================================================
# FILE DISCOVERY
# =============================================================================

def discover_files(root):
    root = Path(root)

    # Source path is directly to a ZIP file
    if root.is_file() and root.suffix.lower() == ".zip":
        with ZipFile(root) as z:
            for member in z.namelist():
                if is_target_file(member):
                    yield ("zip", root, member)
        return

    # Source path is a directory
    for item in root.rglob("*"):
        if not item.is_file():
            continue

        if item.suffix.lower() == ".csv" and is_target_file(item.name):
            yield ("csv", item, item.name)

        elif item.suffix.lower() == ".zip":
            with ZipFile(item) as z:
                for member in z.namelist():
                    if is_target_file(member):
                        yield ("zip", item, member)

# =============================================================================
# LOADING
# =============================================================================

def load_trace(file_type, path, filename):
    if file_type == "csv":
        return pd.read_csv(path)

    with ZipFile(path) as z:
        with z.open(filename) as f:
            return pd.read_csv(f)

# =============================================================================
# RESHAPE
# =============================================================================

def reshape_trace(df):
    interval_cols = [c for c in df.columns if c not in ["Year", "Month", "Day"]]

    long_df = df.melt(
        id_vars=["Year", "Month", "Day"],
        value_vars=interval_cols,
        var_name="interval",
        value_name="demand",
    )

    long_df["interval"] = long_df["interval"].astype("int16")

    midnight = pd.to_datetime({
        "year": long_df["Year"],
        "month": long_df["Month"],
        "day": long_df["Day"],
    })

    # Intervals are period-ending: interval 1 = 00:30, interval 48 = 00:00 next day
    long_df["datetime"] = midnight + pd.to_timedelta(
        long_df["interval"].astype("int32") * 30,
        unit="min",
    )

    long_df["demand"] = pd.to_numeric(
        long_df["demand"], errors="coerce"
    ).astype("float32")

    return (
        long_df[["datetime", "demand"]]
        .sort_values("datetime")
        .reset_index(drop=True)
    )

# =============================================================================
# MAIN
# =============================================================================

def build_dataset():

    output_path = Path(OUTPUT_FILE)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    writer = None
    total_rows = 0

    try:
        for source_cfg in INPUT_SOURCES:

            print()
            print(f"Scanning {source_cfg['dataset']}")

            for file_type, parent_path, filename in discover_files(source_cfg["path"]):

                print(f"Processing {Path(filename).name}")

                df = load_trace(file_type, parent_path, filename)
                df = reshape_trace(df)

                metadata = extract_metadata(filename)

                df["dataset"] = source_cfg["dataset"]
                df["source"] = source_cfg["source"]
                df["scenario"] = source_cfg["scenario"]

                for k, v in metadata.items():
                    df[k] = v

                df["source_file"] = Path(filename).stem

                table = pa.Table.from_pandas(
                    df[COLUMN_ORDER],
                    schema=SCHEMA,
                    preserve_index=False,
                )

                if writer is None:
                    writer = pq.ParquetWriter(
                        output_path,
                        SCHEMA,
                        compression="snappy",
                    )

                writer.write_table(table)

                total_rows += len(df)

                # release before the next file is read
                del df, table

    finally:
        if writer is not None:
            writer.close()

    print()
    if total_rows == 0:
        print("No matching files found - nothing written")
    else:
        print(f"Written {total_rows:,} rows")
        print(output_path)


if __name__ == "__main__":
    build_dataset()