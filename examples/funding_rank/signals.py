"""Fixed causal eight-coin funding predictor; no fit or economic data on import."""
import numpy as np
import pandas as pd
from examples.cross_venue.signals import (
    START, END, SYMBOLS, native_id, prepare_funding, yield_at, utc)

ASSUMPTIONS = dict(
    availability='trade minute start + two minutes; settlement receipt + one minute strictly before decision',
    funding_receipts_assumed='settlement + one minute unless original historical receipt supplied',
    decision_clock='daily 00:05 UTC; proposals Sunday only',
    historical_schedule='past realized duration-weighted funding proxy, not recovered scheduled accrual',
    boundary='exclusive fixed year; terminal funding cash handled separately',
    economic_search=False,
)


def build_features(bars, funding):
    """Native closed prices + daily 00:05 UTC past-realized funding intensity.

    The availability grid has prices every minute, so a frozen Sunday proposal
    can size from later known closes after its old inventory actually exits.
    Funding fields deliberately remain missing/invalid outside daily reviews.
    Exact END settlements are not predictor observations in this exclusive year.
    Actual execution settlement cash is a separate, phase-bounded Engine input.
    """
    expected = {native_id('binance', label) for label in SYMBOLS}
    if set(bars) != expected or set(funding) != expected:
        raise ValueError('Require exactly eight native Binance price/funding streams')
    source_grid = pd.date_range(START, END, freq='min', inclusive='left').as_unit('ns')
    price_grid = source_grid[:-2] + pd.Timedelta(minutes=2)
    decisions = price_grid[(price_grid.hour == 0) & (price_grid.minute == 5)]
    result = pd.DataFrame(index=price_grid)
    for label in SYMBOLS:
        iid = native_id('binance', label)
        source = bars[iid]
        required = {'timestamp', 'instrument_id', 'duration_seconds', 'close'}
        if not required <= set(source):
            raise ValueError('Missing native closed-minute price fields')
        times = pd.DatetimeIndex(source.timestamp)
        if times.tz is None or times.hasnans:
            raise ValueError('Finite timezone-aware trade timestamps required')
        times = times.tz_convert('UTC').as_unit('ns')
        if (not times.equals(source_grid) or not source.instrument_id.eq(iid).all()
                or not source.duration_seconds.eq(60).all()):
            raise ValueError('Exact native closed-minute year grid required')
        prices = source.close.to_numpy(dtype=float)
        if not np.isfinite(prices).all() or not (prices > 0).all():
            raise ValueError('Require finite positive native trade closes')
        result[f'price_{label}'] = prices[:-2]
        stream = funding[iid]
        if not {'timestamp', 'instrument_id', 'funding_rate'} <= set(stream):
            raise ValueError('Missing native funding fields')
        if len(stream) and not stream.instrument_id.eq(iid).all():
            raise ValueError('Funding identity differs from native stream')
        # Validate all sourced clocks first; do not hide bad identities/receipts
        # by dropping a malformed row. Dataset freeze separately verifies raw
        # responses and exact normalization, including excluded boundary rows.
        timestamps = pd.DatetimeIndex([utc(time) for time in stream.timestamp])
        if timestamps.has_duplicates:
            raise ValueError('Duplicate sourced funding settlements')
        if (timestamps < START).any():
            raise ValueError('No outside-year funding predecessor')
        rates = pd.to_numeric(stream.funding_rate, errors='raise').to_numpy(dtype=float)
        if not np.isfinite(rates).all():
            raise ValueError('Nonfinite sourced funding rate')
        receipt_field = next((field for field in ('historical_receipt', 'available_at') if field in stream), None)
        if receipt_field:
            receipts = pd.DatetimeIndex([utc(time) for time in stream[receipt_field]])
            if (receipts < timestamps).any():
                raise ValueError('Historical funding receipt precedes settlement')
        # A raw API page can include END+milliseconds. Validate its identity and
        # clocks but exclude it BEFORE the fixed-year helper. Source verification
        # and hashes retain all raw bytes; no such rate enters the predictor.
        in_year = stream.loc[timestamps < END].copy()
        prepared = prepare_funding(in_year)
        values = [yield_at(prepared, time) for time in decisions]
        result[f'yield_{label}'] = pd.Series(
            [value['intensity'] for value in values], index=decisions, dtype=float
        ).reindex(price_grid)
        result[f'valid_{label}'] = pd.Series(
            [value['valid'] for value in values], index=decisions, dtype=bool
        ).reindex(price_grid, fill_value=False)
    result.attrs.update(ASSUMPTIONS)
    return result
