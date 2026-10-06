"""Assumed-availability positioning features; no data reads or fitting on import."""
from __future__ import annotations
from numbers import Integral
from pandas.api.types import is_bool_dtype, is_numeric_dtype
import numpy as np
import pandas as pd

START = pd.Timestamp('2025-10-05', tz='UTC')
END = pd.Timestamp('2026-10-05', tz='UTC')
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'DOGEUSDT', '1000PEPEUSDT', 'SOLUSDT', 'XRPUSDT', 'LINKUSDT', 'ADAUSDT')
ASSUMPTIONS = {
    'metric_label_timezone': 'UTC interpretation of offset-free archive labels',
    'metric_information_period': 'unverified; assume label plus a full five-minute interval',
    'metric_availability': 'label + fixed delay, strictly before decision; delay is an assumption',
    'price_availability': 'minute start + two minutes, at or before decision',
    'quantity_units': 'within-native dimensionless change; constant unit scaling cancels',
    'vintage': 'current downloaded archives, not verified historical delivery or original vintage',
    'economic_claim': 'position-unwind proxy; no observed liquidation or return guarantee',
}


def _clock(value):
    result = pd.Timestamp(value)
    if result.tzinfo is None or pd.isna(result):
        raise ValueError('Finite timezone-aware boundary required')
    return result.tz_convert('UTC').as_unit('ns')


def _stream(frame, iid, grid, numeric):
    if not {'timestamp', 'instrument_id', *numeric} <= set(frame):
        raise ValueError('Missing native source fields')
    times = pd.DatetimeIndex(frame.timestamp)
    if times.tz is None or times.hasnans:
        raise ValueError('Finite timezone-aware source clocks required')
    times = times.tz_convert('UTC').as_unit('ns')
    if not times.equals(grid) or not frame.instrument_id.eq(iid).all():
        raise ValueError('Exact native source grid required; no sorting, filling or outside-year rows')
    if any(is_bool_dtype(frame[key].dtype) or not is_numeric_dtype(frame[key].dtype) for key in numeric):
        raise ValueError('Numeric non-boolean native source dtype required')
    values = frame[list(numeric)].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not (values > 0).all():
        raise ValueError('Finite positive source values required')


def build_features(bars, metrics, *, instrument_id, start=START, end=END,
                   metric_delay_minutes=6):
    """Minute features for one native linear contract, assuming 6m or 11m delay.

    The first hour is missing, never warmed from earlier data. Source labels and
    assumed availability are retained separately; exact availability equality
    is excluded for metrics. Price changes use two delayed completed closes.
    Complete source grids are required, not inferred from the observed rows.
    No archive field is shifted to correct an alleged historical label change.
    """
    start, end = _clock(start), _clock(end)
    if (end <= start or start != start.floor('5min') or end != end.floor('5min')
            or isinstance(metric_delay_minutes, bool) or not isinstance(metric_delay_minutes, Integral)
            or metric_delay_minutes not in (6, 11)):
        raise ValueError('Five-minute boundaries and declared fixed delay 6 or 11 required')
    if instrument_id not in {f'binance:perpetual:{symbol}' for symbol in SYMBOLS}:
        raise ValueError('Native Binance USDT perpetual identity required')
    price_grid = pd.date_range(start, end, freq='min', inclusive='left').as_unit('ns')
    metric_grid = pd.date_range(start, end, freq='5min', inclusive='left').as_unit('ns')
    _stream(bars, instrument_id, price_grid, ('close',))
    _stream(metrics, instrument_id, metric_grid, ('sum_open_interest',))
    if {'historical_receipt', 'available_at', 'assumed_available_at'} & set(metrics):
        raise ValueError('Assumed-only archive API cannot ignore supplied receipt/availability fields')
    if 'duration_seconds' not in bars or not bars.duration_seconds.eq(60).all():
        raise ValueError('Completed native one-minute candles required')
    decision_grid = price_grid[2:]
    closes = pd.Series(bars.close.to_numpy(dtype=float), index=price_grid)
    price_features = pd.DataFrame({
        'timestamp': decision_grid,
        'price_source_label': price_grid[:-2],
        'price_available_at': price_grid[:-2] + pd.Timedelta(minutes=2),
        'price': closes.to_numpy()[:-2],
        'price_return_1h': (closes / closes.shift(60) - 1).to_numpy()[:-2],
        'price_return_15m': (closes / closes.shift(15) - 1).to_numpy()[:-2],
    })
    quantities = pd.Series(metrics.sum_open_interest.to_numpy(dtype=float))
    oi = pd.DataFrame({
        'metric_source_label': metric_grid,
        'metric_available_at': metric_grid + pd.Timedelta(minutes=metric_delay_minutes),
        'native_open_interest': quantities,
        'quantity_change_1h': quantities / quantities.shift(12) - 1,
        'quantity_change_5m': quantities / quantities.shift(1) - 1,
    })
    joined = pd.merge_asof(price_features, oi, left_on='timestamp',
                           right_on='metric_available_at', direction='backward',
                           allow_exact_matches=False)
    joined['metric_age_seconds'] = (joined.timestamp - joined.metric_available_at).dt.total_seconds()
    derived = ['price_return_1h', 'price_return_15m', 'quantity_change_1h', 'quantity_change_5m']
    joined[derived] = joined[derived].replace([np.inf, -np.inf], np.nan)
    joined['valid'] = (
        np.isfinite(joined[derived]).all(axis=1)
        & joined.metric_age_seconds.gt(0) & joined.metric_age_seconds.le(300)
    )
    joined['instrument_id'] = instrument_id
    joined = joined.set_index('timestamp')
    joined.attrs.update(ASSUMPTIONS, metric_delay_minutes=metric_delay_minutes,
                        start=start.isoformat(), end=end.isoformat())
    return joined
