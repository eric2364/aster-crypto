"""Fresh independent adversarial audit; this author did not implement the core."""
import numpy as np
import pandas as pd
import pytest

from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, SimulationConfig
from aster.data.validation import normalize_bars, normalize_funding
from aster.optimization.search import walk_forward
from aster.strategies.base import BaseStrategy
from aster.strategies.vectorized import moving_average_signals, screen_returns

T = pd.Timestamp('2024-01-01', tz='UTC')


def spec(**kwargs):
    return Instrument('perp', 'binance', 'BTCUSDT', 'perpetual',
                      maker_bps=0, taker_bps=0, liquidation_bps=0,
                      min_notional=0, **kwargs)


def candles(n=4):
    return pd.DataFrame([dict(timestamp=T + pd.Timedelta(minutes=i),
        instrument_id='perp', open=100., high=100., low=100., close=100.,
        volume=100., duration_seconds=60) for i in range(n)])


class EnterOnce(BaseStrategy):
    def on_bar(self, ctx, bar):
        if ctx.now == T + pd.Timedelta(minutes=1):
            ctx.target('perp', 1)


def test_settlement_mark_risk_precedes_receipt_that_would_rescue_position():
    # C=10, entry100, settlement mark90: local equity0, maintenance.45.
    # Negative 2% rate would pay1.8 and improperly rescue this already insolvent long.
    s = spec()
    cfg = SimulationConfig(initial_balances={'binance':1000}, leverage=10,
        max_gross_leverage=20, max_position_pct=20, slippage_bps=0, participation=1)
    engine = Engine([s], cfg)
    settlement = T + pd.Timedelta(seconds=90)
    events = pd.DataFrame([dict(timestamp=settlement, instrument_id=s.id,
        funding_rate=-.02, mark_price=90)])
    result = engine.run(candles(), EnterOnce(), events)
    liquidations = result.events[result.events.type == 'LIQUIDATION']
    assert len(liquidations) == 1
    assert liquidations.iloc[0].timestamp == settlement
    assert liquidations.iloc[0].mark_price == 90
    assert result.funding.empty


def test_walk_forward_test_candles_cannot_close_beyond_declared_window():
    frame = candles()
    frame.timestamp = [T + pd.Timedelta(days=i) for i in [0,1,2,4]]
    frame.duration_seconds = [86400,86400,172800,86400]
    # Retain a complete test candle on another instrument so the fold is real.
    other = Instrument('other', 'binance', 'ETHUSDT', 'perpetual')
    complete = frame.iloc[[2]].copy()
    complete.instrument_id = other.id
    complete.duration_seconds = 86400
    frame = pd.concat([frame,complete], ignore_index=True)
    cfg = SimulationConfig(initial_balances={'binance':1000})
    folds = walk_forward([spec(),other], cfg, frame, BaseStrategy, {},
                         train_days=2, test_days=1, objective='total_return')
    assert folds
    for fold in folds:
        assert fold['result'].equity.timestamp.max() <= fold['test_end']


def test_timezone_is_converted_to_utc_and_naive_input_rejected():
    frame = candles()
    frame.timestamp = frame.timestamp.dt.tz_convert('Asia/Hong_Kong')
    normalized, _ = normalize_bars(frame, {'perp':spec()})
    assert str(normalized.timestamp.dt.tz) == 'UTC'
    assert normalized.timestamp.iloc[0] == T
    frame.timestamp = frame.timestamp.dt.tz_localize(None)
    with pytest.raises(ValueError, match='Timezone-aware'):
        normalize_bars(frame)


@pytest.mark.parametrize('corruption,reason', [
    ('duplicate','Duplicate'), ('overlap','Overlapping'), ('missing','Missing'),
    ('zero_price','Nonpositive'), ('negative_volume','Negative volume')])
def test_bad_candles_rejected(corruption, reason):
    frame = candles()
    if corruption == 'duplicate': frame = pd.concat([frame,frame.iloc[[0]]])
    elif corruption == 'overlap': frame.loc[0,'duration_seconds'] = 120
    elif corruption == 'missing': frame.loc[0,'close'] = np.nan
    elif corruption == 'zero_price': frame.loc[0,'low'] = 0
    else: frame.loc[0,'volume'] = -1
    with pytest.raises(ValueError, match=reason): normalize_bars(frame)


def test_gaps_and_extreme_jumps_warn_without_inventing_bars():
    frame = candles(2)
    frame.loc[1,'timestamp'] = T + pd.Timedelta(days=100)
    frame.loc[1,['open','high','low','close']] = 200
    normalized, report = normalize_bars(frame)
    assert len(normalized) == 2
    assert len(report.gaps) == 1
    assert any('Price jumps' in warning for warning in report.warnings)


def test_zero_volume_is_valid_but_cannot_supply_opening_capacity():
    frame = candles()
    frame.volume = 0
    result = Engine([spec()], SimulationConfig()).run(frame, EnterOnce())
    assert result.fills.empty


@pytest.mark.parametrize('metadata,reason', [
    ({'listed_at':'2024-01-02T00:00:00Z'},'Before listing'),
    ({'delisted_at':'2024-01-01T00:01:00Z'},'After delisting')])
def test_symbol_lifecycle_rejected(metadata, reason):
    with pytest.raises(ValueError, match=reason):
        normalize_bars(candles(), {'perp':spec(**metadata)})


def test_funding_duplicate_and_unknown_instrument_rejected():
    row = dict(timestamp=T, instrument_id='perp', funding_rate=.01, mark_price=100.)
    with pytest.raises(ValueError, match='Duplicate funding'):
        normalize_funding(pd.DataFrame([row,row]), {'perp':spec()})
    with pytest.raises(ValueError, match='must be perpetual'):
        normalize_funding(pd.DataFrame([{**row,'instrument_id':'missing'}]), {'perp':spec()})


def test_missing_funding_timestamp_is_rejected_instead_of_silently_omitted():
    row = dict(timestamp=T, instrument_id='perp', funding_rate=.01, mark_price=100.)
    with pytest.raises(ValueError, match='Missing|timestamp'):
        normalize_funding(pd.DataFrame([row,{**row,'timestamp':pd.NaT}]), {'perp':spec()})


def test_future_perturbation_cannot_change_indicator_or_screened_prefix():
    index = pd.date_range(T, periods=80, freq='h')
    close = pd.Series(np.linspace(100,120,80), index=index)
    changed = close.copy(); changed.iloc[40:] = 1e6
    a = moving_average_signals(close, 3, 8)
    b = moving_average_signals(changed, 3, 8)
    pd.testing.assert_series_equal(a.iloc[:40], b.iloc[:40])
    ra = screen_returns(close.to_frame('perp'), a.to_frame('perp'))
    rb = screen_returns(changed.to_frame('perp'), b.to_frame('perp'))
    pd.testing.assert_frame_equal(ra.iloc[:40], rb.iloc[:40])


def test_walk_forward_selection_is_invariant_to_future_holdout_prices():
    frame = candles(7)
    frame.timestamp = pd.date_range(T, periods=7, freq='D')
    frame.duration_seconds = 86400
    altered = frame.copy()
    altered.loc[altered.timestamp >= T + pd.Timedelta(days=3),
                ['open','high','low','close']] = 1000
    cfg = SimulationConfig(initial_balances={'binance':1000})
    factory = lambda unused: BaseStrategy()
    first = walk_forward([spec()], cfg, frame, factory, {'unused':[1,2]},
                         train_days=3, test_days=2, objective='total_return')[0]
    second = walk_forward([spec()], cfg, altered, factory, {'unused':[1,2]},
                          train_days=3, test_days=2, objective='total_return')[0]
    assert first['parameters'] == second['parameters']
    assert first['in_sample'] == second['in_sample']
