from dataclasses import dataclass, field, asdict
import numpy as np
import pandas as pd

@dataclass
class QualityReport:
    rows: int = 0
    instruments: int = 0
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    def to_dict(self): return asdict(self)

REQUIRED = ['timestamp','instrument_id','open','high','low','close','volume','duration_seconds']

def normalize_bars(frame, catalog=None):
    df = frame.copy()
    missing = set(REQUIRED) - set(df.columns)
    if missing: raise ValueError(f'Missing fields: {sorted(missing)}')
    # Refuse naive times; callers must explicitly assign the source timezone.
    parsed = pd.to_datetime(df.timestamp, format='mixed')
    if not isinstance(parsed.dtype, pd.DatetimeTZDtype):
        raise ValueError('Timezone-aware timestamps required; input is interval start')
    df['timestamp'] = parsed.dt.tz_convert('UTC')
    for c in REQUIRED[2:]: df[c] = pd.to_numeric(df[c], errors='raise')
    report = QualityReport(len(df), df.instrument_id.nunique())
    if df.empty: report.errors.append('Empty dataset')
    if df[REQUIRED].isna().any().any(): report.errors.append('Missing values')
    if not np.isfinite(df[REQUIRED[2:]].to_numpy()).all(): report.errors.append('Nonfinite values')
    if df.duplicated(['instrument_id','timestamp']).any(): report.errors.append('Duplicate candles')
    if (df[['open','high','low','close']] <= 0).any().any(): report.errors.append('Nonpositive prices')
    if (df.volume < 0).any(): report.errors.append('Negative volume')
    if (df.duration_seconds <= 0).any(): report.errors.append('Nonpositive duration')
    if ((df.high < df[['open','close','low']].max(axis=1)) | (df.low > df[['open','close','high']].min(axis=1))).any():
        report.errors.append('Impossible OHLC')
    for c in ('mark_price','mark_open','index_price'):
        if c in df and ((df[c] <= 0).any() or not np.isfinite(df[c]).all()): report.errors.append(f'Invalid {c}')
    df = df.sort_values(['timestamp','instrument_id']).reset_index(drop=True)
    df['end'] = df.timestamp + pd.to_timedelta(df.duration_seconds, unit='s')
    for iid,g in df.groupby('instrument_id'):
        previous_end = g.end.shift()
        overlap = g.timestamp < previous_end
        if overlap.any(): report.errors.append(f'Overlapping candles: {iid}')
        for idx in g.index[g.timestamp > previous_end]:
            report.gaps.append({'instrument_id':iid,'from':str(previous_end.loc[idx]),'to':str(df.loc[idx,'timestamp'])})
        if g.duration_seconds.nunique() > 1: report.warnings.append(f'Variable bar duration: {iid}')
        jumps = g.close.pct_change().abs() > .5
        if jumps.any(): report.warnings.append(f'Price jumps >50%: {iid} ({jumps.sum()})')
        if catalog is not None:
            if iid not in catalog: report.errors.append(f'Unknown instrument: {iid}'); continue
            spec = catalog[iid]
            if spec.listed_at and (g.timestamp < pd.Timestamp(spec.listed_at)).any(): report.errors.append(f'Before listing: {iid}')
            if spec.delisted_at and (g.end > pd.Timestamp(spec.delisted_at)).any(): report.errors.append(f'After delisting: {iid}')
    if report.gaps: report.warnings.append(f'{len(report.gaps)} gaps; no synthetic tradable bars inserted')
    if report.errors: raise ValueError('; '.join(report.errors))
    return df, report

def normalize_funding(frame, catalog):
    cols = ['timestamp','instrument_id','funding_rate','mark_price']
    if frame is None or frame.empty: return pd.DataFrame(columns=cols)
    df = frame.copy()
    if not set(cols).issubset(df): raise ValueError('Funding requires timestamp, instrument_id, funding_rate, mark_price')
    dt = pd.to_datetime(df.timestamp, format='mixed')
    if not isinstance(dt.dtype, pd.DatetimeTZDtype): raise ValueError('Funding timestamps must be timezone-aware')
    df.timestamp = dt.dt.tz_convert('UTC')
    if df[cols].isna().any().any(): raise ValueError('Missing funding values or timestamps')
    if df.duplicated(['timestamp','instrument_id']).any(): raise ValueError('Duplicate funding settlements')
    if not np.isfinite(df[['funding_rate','mark_price']].to_numpy(dtype=float)).all() or (df.mark_price <= 0).any():
        raise ValueError('Invalid funding rate or mark')
    for iid in df.instrument_id:
        if iid not in catalog or catalog[iid].market_type != 'perpetual': raise ValueError('Funding instrument must be perpetual')
    return df.sort_values(['timestamp','instrument_id']).reset_index(drop=True)
