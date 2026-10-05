"""Independent actual-execution regressions for proportional isolated reserve release."""
import pandas as pd
import pytest

from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, Order, SimulationConfig
from aster.strategies.base import BaseStrategy


class CloseAfterEntry(BaseStrategy):
    def __init__(self, side):
        self.side = side
        self.seen = 0

    def on_bar(self, context, bar):
        self.seen += 1
        if self.seen == 1:
            context.order(Order('perp', self.side, 1, tif='IOC'))
        elif self.seen == 2:
            context.order(Order('perp', -self.side, 1, tif='IOC', reduce_only=True))


@pytest.mark.parametrize('side,exit_price', [(1, 95), (-1, 105), (1, 105), (-1, 95)])
@pytest.mark.parametrize('fee_bps', [0, 5])
def test_volume_limited_ioc_close_keeps_safe_residual_margin(side, exit_price, fee_bps):
    # The published entry candle's 9.5 volume permits only .95 closing units.
    # The IOC remainder is cancelled; no later order can close the residual .05.
    times = pd.date_range('2026-01-01', periods=4, freq='min', tz='UTC')
    prices = [100, 100, exit_price, exit_price]
    bars = pd.DataFrame([
        dict(timestamp=t, instrument_id='perp', open=p, high=p, low=p, close=p,
             mark_open=p, mark_price=p, volume=v, duration_seconds=60)
        for t, p, v in zip(times, prices, [10, 9.5, 0, 0])
    ])
    spec = Instrument('perp', 'binance', 'TESTUSDT', 'perpetual',
                      min_notional=0, maker_bps=0, taker_bps=fee_bps, liquidation_bps=0)
    config = SimulationConfig(initial_balances={'binance': 1000}, leverage=1,
                              margin_mode='isolated', max_gross_leverage=20,
                              max_position_pct=20, participation=.1,
                              slippage_bps=0, spread_bps=0)
    result = Engine([spec], config).run(bars, CloseAfterEntry(side))
    assert list(result.fills.quantity) == pytest.approx([1, .95])
    assert list(result.fills.side) == [side, -side]
    assert len(result.trades) == 1
    assert result.trades.iloc[0].quantity == pytest.approx(.95)
    assert not result.fills.exit_reason.eq('liquidation').any()
    assert len(result.positions) == 1
    residual = result.positions.iloc[0]
    assert residual.quantity == pytest.approx(side * .05)
    assert residual.collateral == pytest.approx(5)
    assert residual.unrealized_pnl == pytest.approx(side * .05 * (exit_price - 100))
    fees = (100 + .95 * exit_price) * fee_bps / 10000
    final = result.equity.iloc[-1]
    assert final.cash == pytest.approx(1000 + side * .95 * (exit_price - 100) - fees)
    assert final.equity == pytest.approx(1000 + side * (exit_price - 100) - fees)
    assert final.margin_used == pytest.approx(5)


@pytest.mark.parametrize('side', [1, -1])
def test_funded_reversal_allocates_fresh_reserve_without_old_leg_pnl(side):
    from aster.backtest.portfolio import Portfolio
    timestamp = pd.Timestamp('2026-01-01', tz='UTC')
    spec = Instrument('perp', 'binance', 'TESTUSDT', 'perpetual',
                      min_notional=0, maker_bps=0, taker_bps=5, liquidation_bps=0)
    portfolio = Portfolio([spec], SimulationConfig(initial_balances={'binance': 1000},
                          leverage=1, margin_mode='isolated', max_gross_leverage=20,
                          max_position_pct=20, slippage_bps=0))
    assert portfolio.apply_fill('perp', side, 1, 100, timestamp, 'taker', 'market')[0]
    portfolio.settle_funding(dict(instrument_id='perp', timestamp=timestamp,
                                 mark_price=100, funding_rate=.01))
    portfolio.marks['perp'] = 95
    assert portfolio.apply_fill('perp', -side, 1.5, 95, timestamp, 'taker', 'market')[0]
    remaining = portfolio.positions['perp']
    assert remaining.quantity == pytest.approx(-side * .5)
    assert remaining.average_price == 95
    assert remaining.collateral == pytest.approx(47.5)
    assert remaining.funding == 0
    assert remaining.taker_fees == pytest.approx(.5 * 95 * .0005)
    assert portfolio.trades[0]['funding_pnl'] == pytest.approx(-side)
    assert portfolio.cash['binance'] == pytest.approx(1000 - .05 - side + side * (95 - 100) - 1.5 * 95 * .0005)
    assert portfolio.liquidation_candidates() == []
