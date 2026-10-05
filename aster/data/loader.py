from pathlib import Path
import pandas as pd

def load(path):
    path = Path(path)
    if path.suffix == '.parquet': return pd.read_parquet(path)
    if path.suffix == '.csv': return pd.read_csv(path)
    raise ValueError('Use CSV or Parquet')

def save_partitioned(frame, root):
    """Catalog-enriched table partitioned by venue / market / symbol / year / month."""
    df = frame.copy()
    df['year'] = pd.to_datetime(df.timestamp, utc=True).dt.year
    df['month'] = pd.to_datetime(df.timestamp, utc=True).dt.month
    df.to_parquet(root, index=False, partition_cols=['exchange','market_type','symbol','year','month'])
