"""Fixed, strictly previous realized-funding intensities; no training or fitting."""
import math
import numpy as np
import pandas as pd

START = pd.Timestamp('2025-10-05', tz='UTC')
END = pd.Timestamp('2026-10-05', tz='UTC')
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'DOGEUSDT', 'PEPEUSDT', 'SOLUSDT', 'XRPUSDT', 'LINKUSDT', 'ADAUSDT')
VENUES = ('binance', 'bybit')
LOOKBACK = pd.Timedelta(hours=168)
PROCESSING = pd.Timedelta(minutes=1)
CADENCES = (1, 2, 4, 8)
JITTER = pd.Timedelta(seconds=5)


def utc(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or pd.isna(timestamp):
        raise ValueError('Require a finite timezone-aware clock')
    return timestamp.tz_convert('UTC')


def prepare_funding(frame):
    """One native instrument. Explicit receipt/available_at means receipt + lag.

    Without an original receipt, settlement+one minute is an assumption, recorded
    separately from the downloaded source. Retrieval today is never a receipt.
    """
    if frame.attrs.get('cross_venue_prepared'):
        raise ValueError('Funding already prepared; do not apply processing twice')
    if not {'timestamp', 'instrument_id', 'funding_rate'} <= set(frame):
        raise ValueError('Missing funding identity/rate/time')
    result = frame[['timestamp', 'instrument_id', 'funding_rate']].copy()
    result['timestamp'] = pd.DatetimeIndex([utc(t) for t in frame.timestamp]).as_unit('ns')
    if result.instrument_id.nunique() > 1 or result.instrument_id.isna().any():
        raise ValueError('Prepare one instrument at a time')
    allowed = {native_id(v, s) for v in VENUES for s in SYMBOLS}
    if len(result) and not result.instrument_id.isin(allowed).all():
        raise ValueError('Unsupported venue-native funding identity')
    if result.timestamp.duplicated().any():
        raise ValueError('Duplicate funding settlements')
    if not result.timestamp.between(START, END, inclusive='both').all():
        raise ValueError('No outside-year funding or predecessor')
    result['funding_rate'] = pd.to_numeric(result.funding_rate, errors='raise')
    if not np.isfinite(result.funding_rate.to_numpy(dtype=float)).all():
        raise ValueError('Nonfinite funding rate')
    receipt_field = next((c for c in ('historical_receipt', 'available_at') if c in frame), None)
    if receipt_field:
        receipts = pd.DatetimeIndex([utc(t) for t in frame[receipt_field]]).as_unit('ns')
        if (receipts < pd.DatetimeIndex(result.timestamp)).any():
            raise ValueError('Historical receipt precedes settlement')
        result['available_at'] = receipts + PROCESSING
    else:
        result['available_at'] = result.timestamp + PROCESSING
    result['availability_is_assumed'] = receipt_field is None
    result = result.sort_values('timestamp').reset_index(drop=True)
    result.attrs['cross_venue_prepared'] = True
    return result


def yield_at(prepared, now):
    """Derive predecessors from known rows only, including out-of-order delivery."""
    now = utc(now)
    if not prepared.attrs.get('cross_venue_prepared'):
        raise ValueError('Call prepare_funding before yield_at')
    known = prepared.loc[prepared.available_at < now].sort_values('timestamp')
    output = dict(intensity=None, valid=False, reason='insufficient_history', covered_hours=0.,
                  latest_settlement=None, latest_available_at=None, latest_interval_hours=None)
    if len(known) < 2:
        return output
    times = pd.DatetimeIndex(known.timestamp).as_unit('ns')
    output.update(latest_settlement=times[-1], latest_available_at=known.available_at.iloc[-1])
    durations = np.diff(times.asi8)
    hourly_ns = pd.Timedelta(hours=1).value
    labels = np.zeros(len(durations), dtype=int)
    for cadence in CADENCES:
        labels[np.abs(durations-cadence*hourly_ns) <= JITTER.value] = cadence
    output['latest_interval_hours'] = float(durations[-1]/hourly_ns)
    window_start = now-LOOKBACK
    lower = np.maximum(times.asi8[:-1], window_start.value)
    upper = np.minimum(times.asi8[1:], now.value)
    weights = np.maximum(0, upper-lower)/hourly_ns
    overlap = weights > 0
    if not labels[-1] or (labels[overlap] == 0).any():
        output['reason'] = 'unrecognized_interval'
        return output
    if len(set(labels[overlap])) > 1:
        output['reason'] = 'mixed_cadence_window'
        return output
    # Exact timestamp comparison preserves submicrosecond expiry boundaries.
    if now-times[-1] > pd.Timedelta(int(durations[-1]), unit='ns')+pd.Timedelta(minutes=10):
        output['reason'] = 'stale_funding'
        return output
    covered = float(weights.sum())
    output['covered_hours'] = covered
    if covered < .90*168:
        output['reason'] = 'insufficient_coverage'
        return output
    rates = known.funding_rate.to_numpy(dtype=float)[1:]
    intensity = float(np.sum(weights * (rates/(durations/hourly_ns)))/covered)
    if not math.isfinite(intensity):
        raise ValueError('Nonfinite funding intensity')
    output.update(intensity=intensity, valid=True, reason='')
    return output


def native_id(venue, label):
    return venue+':perpetual:'+('1000PEPEUSDT' if label == 'PEPEUSDT' else label)


def build_features(bars, funding):
    """16 separately sourced streams -> minute availability prices/hourly yields.

    Normal decisions are UTC :05 only. Yield fields deliberately remain NaN and
    invalid outside those clocks; execution/risk monitoring still runs each minute.
    """
    expected_ids = {native_id(v, s) for v in VENUES for s in SYMBOLS}
    if set(bars) != expected_ids or set(funding) != expected_ids:
        raise ValueError('Require all sixteen venue-native price/funding streams')
    price_grid = pd.date_range(START+pd.Timedelta(minutes=2), END, freq='min', inclusive='left').as_unit('ns')
    source_grid = pd.date_range(START, END, freq='min', inclusive='left').as_unit('ns')
    result = pd.DataFrame(index=price_grid)
    decisions = price_grid[price_grid.minute == 5]
    for venue in VENUES:
        for label in SYMBOLS:
            iid = native_id(venue, label)
            source = bars[iid]
            times = pd.DatetimeIndex(source.timestamp)
            if times.tz is None or times.hasnans:
                raise ValueError('Trade timestamps must be finite and timezone aware')
            times = times.tz_convert('UTC').as_unit('ns')
            if (not times.equals(source_grid) or not source.instrument_id.eq(iid).all()
                    or not source.duration_seconds.eq(60).all()):
                raise ValueError('Require exact native closed minute price coverage')
            prices = source.close.to_numpy(dtype=float)
            if not np.isfinite(prices).all() or not (prices > 0).all():
                raise ValueError('Invalid trade closes')
            # Last two minute closes become available at/after the year endpoint.
            result[f'price_{venue}_{label}'] = prices[:-2]
            source_funding = funding[iid]
            if len(source_funding) and not source_funding.instrument_id.eq(iid).all():
                raise ValueError('Funding identity differs from native stream')
            prepared = prepare_funding(source_funding)
            values = [yield_at(prepared, time) for time in decisions]
            intensity = pd.Series([x['intensity'] for x in values], index=decisions, dtype=float)
            valid = pd.Series([x['valid'] for x in values], index=decisions, dtype=bool)
            result[f'yield_{venue}_{label}'] = intensity.reindex(price_grid)
            result[f'valid_{venue}_{label}'] = valid.reindex(price_grid, fill_value=False)
    result.attrs.update(availability='trade close at minute end plus one minute; settled rate receipt plus one minute strictly before decision',
                        funding_receipts_assumed='unless original historical receipt supplied',
                        historical_schedule='realized intensity proxy, not recovered scheduled accrual',
                        economic_search=False)
    return result
