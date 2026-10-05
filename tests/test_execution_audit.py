"""Independent adversarial execution tests with manually derived expectations.

Author did not implement the engine. No downloaded prices or exchange credentials.
"""
import pandas as pd
import pytest

from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, Order, SimulationConfig
from aster.backtest.portfolio import Portfolio
from aster.strategies.base import BaseStrategy


def bars(prices, volumes=None):
    """Prices are (open, high, low, close); starts, not closes, identify bars."""
    volumes = [1000.0] * len(prices) if volumes is None else volumes
    return pd.DataFrame([
        dict(timestamp=pd.Timestamp('2024-01-01', tz='UTC') + pd.Timedelta(minutes=i),
             instrument_id='spot', open=o, high=h, low=l, close=c,
             volume=v, duration_seconds=60)
        for i, ((o, h, l, c), v) in enumerate(zip(prices, volumes))
    ])


class OrdersOnce(BaseStrategy):
    def __init__(self, orders):
        self.orders = orders
        self.sent = False

    def on_bar(self, context, bar):
        if not self.sent:
            self.sent = True
            for order in self.orders:
                context.order(order)


def run(frame, orders, **kwargs):
    instrument = Instrument('spot', 'binance', 'BTCUSDT', tick_size=0.01,
                            lot_size=0.001, min_quantity=0.001, min_notional=0,
                            maker_bps=2, taker_bps=5)
    config = SimulationConfig(initial_balances={'binance': 10000},
                              slippage_bps=0, spread_bps=0, **kwargs)
    return Engine([instrument], config).run(frame, OrdersOnce(orders))


def test_close_signal_cannot_fill_old_close_and_uses_next_open():
    result = run(bars([(100, 100, 100, 100), (120, 120, 120, 120)]),
                 [Order('spot', 1, 1)])
    assert len(result.fills) == 1
    fill = result.fills.iloc[0]
    assert fill.price == pytest.approx(120)
    assert pd.Timestamp(fill.timestamp) == pd.Timestamp('2024-01-01 00:01', tz='UTC')


def test_positive_latency_skips_open_that_precedes_arrival():
    result = run(bars([(100, 100, 100, 100), (120, 120, 120, 120),
                       (140, 140, 140, 140)]), [Order('spot', 1, 1)], latency_ms=1)
    assert len(result.fills) == 1
    assert result.fills.iloc[0].price == pytest.approx(140)


def test_open_fill_does_not_read_future_completed_volume():
    # Prior published volume 10 permits one unit at 10% participation.
    # Changing volume that will occur AFTER activation cannot change that fill.
    prices = [(100, 100, 100, 100), (100, 100, 100, 100)]
    a = run(bars(prices, [10, 1000]), [Order('spot', 1, 2, tif='IOC')])
    b = run(bars(prices, [10, 0]), [Order('spot', 1, 2, tif='IOC')])
    assert a.fills.quantity.sum() == pytest.approx(1)
    assert b.fills.quantity.sum() == pytest.approx(1)


def test_nonmarketable_ioc_cannot_rest_for_intrabar_excursion():
    result = run(bars([(100, 100, 100, 100), (100, 110, 80, 100),
                       (100, 110, 80, 100)]),
                 [Order('spot', 1, 1, 'limit', limit_price=90, tif='IOC')])
    assert result.fills.empty


def test_fok_has_no_partial_fill_or_fee_when_liquidity_insufficient():
    result = run(bars([(100, 100, 100, 100), (100, 100, 100, 100)], [10, 10]),
                 [Order('spot', 1, 2, tif='FOK')])
    assert result.fills.empty


def test_competing_market_orders_share_one_liquidity_budget():
    result = run(bars([(100, 100, 100, 100), (100, 100, 100, 100)], [10, 1000]),
                 [Order('spot', 1, 1, tif='IOC'), Order('spot', 1, 1, tif='IOC')])
    assert result.fills.quantity.sum() == pytest.approx(1)


def test_marketable_limit_is_taker_and_price_respects_limit():
    result = run(bars([(100, 100, 100, 100), (100, 100, 100, 100)]),
                 [Order('spot', 1, 1, 'limit', limit_price=110)])
    assert len(result.fills) == 1
    fill = result.fills.iloc[0]
    assert fill.liquidity_type == 'taker'
    assert fill.price <= 110


def test_marketable_postonly_order_never_fills():
    result = run(bars([(100, 100, 100, 100), (100, 100, 100, 100),
                       (100, 100, 80, 100)]),
                 [Order('spot', 1, 1, 'limit', limit_price=110, post_only=True)])
    assert result.fills.empty


def test_conservative_equal_touch_never_fills():
    result = run(bars([(100, 100, 100, 100), (100, 100, 90, 100),
                       (100, 100, 90, 100), (100, 100, 90, 100)]),
                 [Order('spot', 1, 1, 'limit', limit_price=90)])
    assert result.fills.empty


def test_intrabar_stoplimit_does_not_assume_trigger_before_low():
    # Both high 120 and low 80 occur, but the path is unknown. Limit 90
    # cannot be treated as executed after a buy-stop at 110 in this candle.
    result = run(bars([(100, 100, 100, 100), (100, 120, 80, 100),
                       (100, 100, 100, 100)]),
                 [Order('spot', 1, 1, 'stop_limit', limit_price=90, stop_price=110)])
    assert result.fills.empty


def test_gap_stopmarket_executes_gap_price_not_favorable_stop():
    result = run(bars([(100, 100, 100, 100), (150, 150, 150, 150)]),
                 [Order('spot', 1, 1, 'stop_market', stop_price=110)])
    assert len(result.fills) == 1
    assert result.fills.iloc[0].price == pytest.approx(150)


def test_profitable_cross_margin_reversal_does_not_count_upl_twice():
    spec = Instrument('perp', 'binance', 'BTCUSDT', market_type='perpetual',
                      maker_bps=0, taker_bps=0, min_notional=0)
    config = SimulationConfig(initial_balances={'binance':100}, leverage=2,
                              max_gross_leverage=10, max_position_pct=10,
                              margin_mode='cross')
    portfolio = Portfolio([spec], config)
    now = pd.Timestamp('2024-01-01', tz='UTC')
    portfolio.marks['perp'] = 100
    assert portfolio.apply_fill('perp', 1, 1, 100, now, 'taker', 'market')[0]
    portfolio.marks['perp'] = 200
    # Close the 1-unit long: cash becomes 200. Opening 2.4 short at 200
    # requires 240 margin. The 100 UPL is realized once, so reject reversal.
    accepted, _ = portfolio.apply_fill('perp', -1, 3.4, 200, now, 'taker', 'market')
    assert not accepted
    assert portfolio.positions['perp'].quantity == pytest.approx(1)
    assert portfolio.cash['binance'] == pytest.approx(100)


def test_stoplimit_triggered_at_later_open_is_newly_active_taker():
    result = run(bars([(100,100,100,100), (100,100,100,100),
                       (120,120,120,120)]),
                 [Order('spot',1,1,'stop_limit',limit_price=150,stop_price=110)])
    assert len(result.fills) == 1
    assert result.fills.iloc[0].liquidity_type == 'taker'
    assert result.fills.iloc[0].price == pytest.approx(120)


def test_delayed_open_stoplimit_postonly_still_rejects_crossing():
    result = run(bars([(100,100,100,100), (100,100,100,100),
                       (120,120,120,120)]),
                 [Order('spot',1,1,'stop_limit',limit_price=150,stop_price=110,
                        post_only=True)])
    assert result.fills.empty


def test_simultaneous_mark_updates_do_not_liquidate_profitable_hedge():
    frame = bars([(100,100,100,100), (100,100,100,100), (40,40,40,40)])
    frame.instrument_id = 'long'
    other = frame.copy()
    other.instrument_id = 'short'
    frame = pd.concat([frame, other], ignore_index=True)
    specs = [Instrument(iid,'binance',iid,market_type='perpetual',
                        maker_bps=0,taker_bps=0,liquidation_bps=0,
                        maintenance_rate=.3,min_notional=0) for iid in ('long','short')]
    config = SimulationConfig(initial_balances={'binance':100},leverage=3,
                              margin_mode='cross',max_gross_leverage=10,
                              max_position_pct=10,slippage_bps=0,spread_bps=0)
    result = Engine(specs,config).run(frame,OrdersOnce([
        Order('long',1,1),Order('short',-1,1)]))
    # Both simultaneous marks move 100 -> 40. Long -60 and short +60:
    # total equity stays 100; maintenance shrinks from 60 to 24.
    assert not (result.events.type == 'LIQUIDATION').any()
    assert result.equity.iloc[-1].equity == pytest.approx(100)


def test_simultaneous_cross_funding_payments_are_settled_before_liquidation():
    frame = bars([(100,100,100,100)] * 3)
    frame.instrument_id = 'long'
    other = frame.copy()
    other.instrument_id = 'short'
    frame = pd.concat([frame,other],ignore_index=True)
    specs = [Instrument(iid,'binance',iid,market_type='perpetual',
                        maker_bps=0,taker_bps=0,liquidation_bps=0,
                        maintenance_rate=.45,min_notional=0) for iid in ('long','short')]
    config = SimulationConfig(initial_balances={'binance':100},leverage=3,
                              margin_mode='cross',max_gross_leverage=10,
                              max_position_pct=10,slippage_bps=0,spread_bps=0)
    funding = pd.DataFrame([
        dict(timestamp=pd.Timestamp('2024-01-01 00:02',tz='UTC'),
             instrument_id=iid,funding_rate=.2,mark_price=100)
        for iid in ('long','short')])
    result = Engine(specs,config).run(frame,OrdersOnce([
        Order('long',1,1),Order('short',-1,1)]),funding)
    # Long pays 20 and short receives 20 simultaneously in one venue account.
    assert not (result.events.type == 'LIQUIDATION').any()
    assert len(result.funding) == 2
    assert result.funding.funding_payment.sum() == pytest.approx(0)
    assert result.equity.iloc[-1].equity == pytest.approx(100)


def test_execution_model_rejects_nonpositive_adverse_sell_price():
    from aster.backtest.execution import adverse_price
    spec = Instrument('perp','binance','BTCUSDT',market_type='perpetual')
    with pytest.raises(ValueError):
        config = SimulationConfig(slippage_bps=15000)
        adverse_price(100,-1,spec,config,1,None)


def test_maximum_gross_leverage_accounts_for_execution_fee():
    spec = Instrument('perp','binance','BTCUSDT',market_type='perpetual',
                      taker_bps=100,min_notional=0)
    config = SimulationConfig(initial_balances={'binance':1000},leverage=3,
                              max_gross_leverage=1,max_position_pct=10,
                              margin_mode='cross')
    portfolio = Portfolio([spec],config)
    portfolio.marks['perp'] = 100
    accepted,_ = portfolio.apply_fill('perp',1,10,100,
        pd.Timestamp('2024-01-01',tz='UTC'),'taker','market')
    # Fee 10 leaves equity 990 and gross exposure 1000, violating 1x.
    assert not accepted


def test_actual_price_pnl_does_not_subtract_slippage_twice():
    class RoundTrip(BaseStrategy):
        def __init__(self): self.n = 0
        def on_bar(self,context,bar):
            self.n += 1
            if self.n <= 2: context.order(Order('spot',1 if self.n==1 else -1,1))
    spec = Instrument('spot','binance','BTCUSDT',min_notional=0)
    config = SimulationConfig(initial_balances={'binance':10000},
                              slippage_bps=100,spread_bps=0)
    result = Engine([spec],config).run(bars([
        (100,100,100,100),(100,110,100,110),(110,110,110,110)]),RoundTrip())
    # Buy101, sell108.90: actual trading P&L7.90; fees .0505+.05445.
    # Slippage1+1.1 is already embedded in actual-price P&L.
    assert result.fills.price.tolist() == pytest.approx([101,108.9])
    assert result.trades.iloc[0].gross_pnl == pytest.approx(7.9)
    assert result.trades.iloc[0].net_pnl == pytest.approx(7.79505)
    assert result.equity.iloc[-1].equity == pytest.approx(10007.79505)
    assert result.equity.iloc[-1].slippage_cost == pytest.approx(2.1)


def test_competing_reduceonly_orders_cannot_flip_long_to_short():
    class ClosingOrders(BaseStrategy):
        def __init__(self): self.n = 0
        def on_bar(self,context,bar):
            self.n += 1
            if self.n == 1: context.order(Order('spot',1,1))
            elif self.n == 2:
                context.order(Order('spot',-1,1,reduce_only=True))
                context.order(Order('spot',-1,1,reduce_only=True))
    spec = Instrument('spot','binance','BTCUSDT',market_type='perpetual',
                      min_notional=0,maker_bps=0,taker_bps=0)
    config = SimulationConfig(initial_balances={'binance':10000},
                              slippage_bps=0,spread_bps=0)
    result = Engine([spec],config).run(bars([(100,100,100,100)]*3),ClosingOrders())
    assert len(result.fills) == 2
    assert result.positions.empty
    assert result.equity.iloc[-1].equity == pytest.approx(10000)
