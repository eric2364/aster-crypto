"""Synthetic causal clocks/native identity tests; no historical outcomes."""
import numpy as np
import pandas as pd
import pytest
from examples.funding_rank import signals


@pytest.fixture
def source(monkeypatch):
    start = pd.Timestamp('2025-10-05', tz='UTC')
    end = start + pd.Timedelta(days=9)
    monkeypatch.setattr(signals, 'START', start)
    monkeypatch.setattr(signals, 'END', end)
    clocks = pd.date_range(start, end, freq='min', inclusive='left')
    settlements = pd.date_range(start, end, freq='8h')
    bars, funding = {}, {}
    for number, label in enumerate(signals.SYMBOLS):
        iid = signals.native_id('binance', label)
        bars[iid] = pd.DataFrame(dict(timestamp=clocks, instrument_id=iid,
            duration_seconds=60, close=np.arange(len(clocks), dtype=float)+number+1))
        funding[iid] = pd.DataFrame(dict(timestamp=settlements, instrument_id=iid,
            funding_rate=.00008*(number+1)))
    return bars, funding


def test_exact_availability_daily_clock_and_native_pepe(source):
    bars, funding = source
    result = signals.build_features(bars, funding)
    assert len(result) == 9*1440-2 and len(result.columns) == 24
    assert result.index[0] == signals.START+pd.Timedelta(minutes=2)
    assert result.index[-1] == signals.END-pd.Timedelta(minutes=1)
    assert result.price_PEPEUSDT.iloc[0] == 4  # native bundle price, no /1000
    daily = (result.index.hour == 0) & (result.index.minute == 5)
    assert result.loc[~daily, 'yield_BTCUSDT'].isna().all()
    assert not result.loc[~daily, 'valid_BTCUSDT'].any()
    assert not result.loc[signals.START+pd.Timedelta(minutes=5), 'valid_BTCUSDT']
    assert result.loc[signals.START+pd.Timedelta(days=7, minutes=5), 'valid_BTCUSDT']
    assert result.loc[signals.START+pd.Timedelta(days=7, minutes=5), 'yield_BTCUSDT'] == pytest.approx(.00001)
    assert result.attrs['economic_search'] is False


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'identity', 'gap', 'duplicate', 'naive', 'duration', 'nonfinite', 'zero'])
def test_price_sources_fail_closed(source, mutation):
    bars, funding = source
    iid = signals.native_id('binance', 'PEPEUSDT')
    if mutation == 'missing': bars.pop(iid)
    elif mutation == 'extra': bars['other'] = bars[iid]
    elif mutation == 'gap': bars[iid] = bars[iid].iloc[1:]
    elif mutation == 'duplicate': bars[iid].loc[1, 'timestamp'] = bars[iid].loc[0, 'timestamp']
    elif mutation == 'naive': bars[iid]['timestamp'] = bars[iid].timestamp.dt.tz_localize(None)
    elif mutation == 'identity': bars[iid]['instrument_id'] = 'binance:perpetual:PEPEUSDT'
    elif mutation == 'duration': bars[iid].loc[0, 'duration_seconds'] = 300
    elif mutation == 'nonfinite': bars[iid].loc[0, 'close'] = np.inf
    else: bars[iid].loc[0, 'close'] = 0
    with pytest.raises(ValueError): signals.build_features(bars, funding)


def test_future_funding_and_unavailable_prices_cannot_change_past(source):
    bars, funding = source
    first = signals.build_features(bars, funding)
    decision = signals.START+pd.Timedelta(days=7, minutes=5)
    for iid in bars:
        bars[iid].loc[bars[iid].timestamp+pd.Timedelta(minutes=2)>decision, 'close'] *= 1e6
        funding[iid].loc[funding[iid].timestamp+pd.Timedelta(minutes=1)>=decision, 'funding_rate'] = -99
    changed = signals.build_features(bars, funding)
    pd.testing.assert_frame_equal(first.loc[:decision], changed.loc[:decision], check_exact=True)


def test_explicit_delayed_receipt_strict_boundary_and_known_predecessors(source):
    bars, funding = source
    iid = signals.native_id('binance', 'BTCUSDT')
    decision = signals.START+pd.Timedelta(days=7, minutes=5)
    frame = funding[iid]
    frame['historical_receipt'] = frame.timestamp.astype('datetime64[ns, UTC]')
    latest = frame.timestamp.eq(signals.START+pd.Timedelta(days=7))
    frame.loc[latest, 'historical_receipt'] = decision-pd.Timedelta(minutes=1)
    result = signals.build_features(bars, funding)
    assert result.loc[decision, 'valid_BTCUSDT']
    # At equality the latest is unknown. Corrupting its rate cannot leak in.
    frame.loc[latest, 'funding_rate'] = 100
    changed = signals.build_features(bars, funding)
    assert changed.loc[decision, 'yield_BTCUSDT'] == result.loc[decision, 'yield_BTCUSDT']
    frame.loc[latest, 'historical_receipt'] -= pd.Timedelta(nanoseconds=1)
    received = signals.build_features(bars, funding)
    assert received.loc[decision, 'yield_BTCUSDT'] > result.loc[decision, 'yield_BTCUSDT']


@pytest.mark.parametrize('mutation', ['identity', 'duplicate', 'preyear', 'receipt_before', 'rate_nan'])
def test_funding_sources_fail_closed(source, mutation):
    bars, funding = source
    iid = signals.native_id('binance', 'BTCUSDT')
    if mutation == 'identity': funding[iid].loc[0, 'instrument_id'] = signals.native_id('binance', 'DOGEUSDT')
    elif mutation == 'duplicate': funding[iid].loc[1, 'timestamp'] = funding[iid].loc[0, 'timestamp']
    elif mutation == 'preyear': funding[iid].loc[0, 'timestamp'] -= pd.Timedelta(hours=8)
    elif mutation == 'receipt_before': funding[iid]['historical_receipt'] = funding[iid].timestamp-pd.Timedelta(nanoseconds=1)
    else: funding[iid].loc[0, 'funding_rate'] = np.nan
    with pytest.raises(ValueError): signals.build_features(bars, funding)


def test_endpoint_settlement_never_changes_features(source):
    bars, funding = source
    first = signals.build_features(bars, funding)
    for frame in funding.values():
        frame.loc[frame.timestamp.eq(signals.END), 'funding_rate'] = 1000
    changed = signals.build_features(bars, funding)
    pd.testing.assert_frame_equal(first, changed, check_exact=True)
