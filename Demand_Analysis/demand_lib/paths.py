"""Single source of truth for folder locations.

Layout (relative to Demand_Analysis/):

    data/raw/         AEMO trace zips and folders (inputs, never written to)
    data/reference/   Static reference files (IASR auxiliary rates)
    data/parquet/     demand_traces.parquet, built by 01_build_parquet.py
    data/cache/       Monthly NemPoint caches (safe to delete)
    outputs/<DATASET>/<workflow>/   Everything the analysis scripts write
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
REFERENCE_DIR = DATA_DIR / "reference"
PARQUET_FILE = DATA_DIR / "parquet" / "demand_traces.parquet"
CACHE_DIR = DATA_DIR / "cache"

OUTPUTS_DIR = ROOT / "outputs"


def output_dir(dataset, workflow):
    """outputs/<DATASET>/<workflow>, so each dataset's results live separately."""
    return OUTPUTS_DIR / dataset / workflow
