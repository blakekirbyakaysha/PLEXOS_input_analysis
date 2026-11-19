import pandas as pd

df = pd.read_csv("load.csv")

raw_datetime = df["Datetime"].copy()

parsed_datetime = pd.to_datetime(
    raw_datetime,
    errors="coerce"
)

bad = parsed_datetime.isna() & raw_datetime.notna()

print(f"Total rows: {len(df):,}")
print(f"Unparseable datetimes: {bad.sum():,}")

print("\nFirst 50 problematic raw values:")
print(
    df.loc[bad, ["Datetime"]]
    .drop_duplicates()
    .head(50)
    .to_string(index=False)
)