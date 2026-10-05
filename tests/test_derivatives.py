"""Independent hand-computed perpetual invariants and adversarial accounting cases."""
import pandas as pd
import pytest

from aster.backtest.models import Instrument, SimulationConfig
from aster.backtest.portfolio import Portfolio
from aster.backtest.engine import Engine
from aster.strategies.base import BaseStrategy

T = pd.Timestamp('2024-01-01', tz='UTC')


def instrument(venue='binance', symbol='BTCUSDT', **kwargs):
    values = dict(maker_bps=0, taker_bps=0, liquidation_bps=0,
                  min_quantity=0.001, min_notional=0, maintenance_rate=0.005)
    values.update(kwargs)
    return Instrument(f'{venue}:perpetual:{symbol}', venue, symbol, 'perpetual', **values)


def wallet(specs=None, mode='isolated', balances=None, leverage=10):
    specs = specs or [instrument()]
    p = Portfolio(specs, SimulationConfig(
        initial_balances=balances or {s.exchange: 1000.0 for s in specs},
        margin_mode=mode, leverage=leverage, max_gross_leverage=20,
        max_position_pct=20, slippage_bps=0))
    return p, specs[0].id


def fill(p, iid, side, quantity, price, seconds=0, **kwargs):
    outcome = p.apply_fill(iid, side, quantity, price, T + pd.Timedelta(seconds=seconds),
                           'taker', 'market', **kwargs)
    assert outcome == (True, ''), outcome


def funding(p, iid, rate, mark=100, seconds=1):
    p.settle_funding(dict(instrument_id=iid, timestamp=T + pd.Timedelta(seconds=seconds),
                         funding_rate=rate, mark_price=mark))


@pytest.mark.parametrize('side,mark', [(1,110), (-1,90)])
def test_derivative_opening_does_not_exchange_notional(side, mark):
    p, iid = wallet()
    fill(p, iid, side, 2, 100)
    p.marks[iid] = mark
    assert p.cash['binance'] == 1000
    assert p.margin_used() == 20
    assert p.unrealized(iid) == 20
    assert p.equity() == 1020


def test_short_round_trip_fee_and_funding_conservation():
    p, iid = wallet([instrument(taker_bps=10)])
    fill(p, iid, -1, 2, 100)
    funding(p, iid, 0.001)
    fill(p, iid, 1, 2, 90, seconds=2)
    assert p.realized == 20
    assert p.fees == pytest.approx(0.38)
    assert p.funding_pnl == pytest.approx(0.2)
    assert p.equity() == pytest.approx(1019.82)
    assert p.margin_used() == 0
    assert sum(t['net_pnl'] for t in p.trades) == pytest.approx(19.82)


@pytest.mark.parametrize('side,rate,expected', [
    (1, 0.001, -0.2), (-1, 0.001, 0.2),
    (1, -0.001, 0.2), (-1, -0.001, -0.2)])
def test_funding_all_four_directions_and_separate_cashflow(side, rate, expected):
    p, iid = wallet()
    fill(p, iid, side, 2, 100)
    funding(p, iid, rate)
    assert p.cash['binance'] == pytest.approx(1000 + expected)
    assert p.positions[iid].collateral == pytest.approx(20 + expected)
    assert p.positions[iid].quantity == side * 2
    assert p.positions[iid].average_price == 100
    assert p.realized == 0
    assert p.funding_pnl == pytest.approx(expected)
    assert p.funding[0]['funding_payment'] == pytest.approx(expected)


def test_funding_mark_not_entry_notional_and_not_leverage_multiplier():
    p, iid = wallet(leverage=5)
    fill(p, iid, 1, 2, 100)
    funding(p, iid, 0.001, mark=120)
    assert p.funding_pnl == pytest.approx(-0.24)
    assert p.equity() == pytest.approx(1039.76)


def test_flat_position_has_no_funding():
    p, iid = wallet()
    funding(p, iid, 0.1)
    assert p.cash['binance'] == 1000
    assert p.funding == []


def test_weighted_entry_partial_close_and_flip():
    p, iid = wallet()
    fill(p, iid, 1, 2, 100)
    fill(p, iid, 1, 1, 130, seconds=1)
    assert p.positions[iid].average_price == 110
    fill(p, iid, -1, 2, 120, seconds=2)
    assert p.realized == 20
    assert p.positions[iid].quantity == 1
    assert p.positions[iid].average_price == 110
    fill(p, iid, -1, 3, 90, seconds=3)
    assert p.realized == 0
    assert p.positions[iid].quantity == -2
    assert p.positions[iid].average_price == 90
    assert p.equity() == 1000


def test_partial_close_funding_allocated_once():
    p, iid = wallet()
    fill(p, iid, 1, 2, 100)
    funding(p, iid, 0.01)
    fill(p, iid, -1, 1, 110, seconds=2)
    assert p.trades[0]['funding_pnl'] == -1
    assert p.positions[iid].funding == -1
    fill(p, iid, -1, 1, 110, seconds=3)
    assert sum(t['funding_pnl'] for t in p.trades) == -2
    assert sum(t['net_pnl'] for t in p.trades) == 18
    assert p.cash['binance'] == 1018


@pytest.mark.parametrize('side,boundary', [
    (1, 90 / 0.995), (-1, 110 / 1.005)])
def test_isolated_liquidation_boundaries_long_short_asymmetric(side, boundary):
    p, iid = wallet()
    fill(p, iid, side, 1, 100)
    safe_mark = boundary + side * 0.001
    unsafe_mark = boundary - side * 0.001
    p.marks[iid] = safe_mark
    assert p.liquidation_candidates() == []
    p.marks[iid] = unsafe_mark
    assert p.liquidation_candidates() == [iid]
    assert p.cash['binance'] == 1000  # Unrelated cash cannot rescue isolated margin.


def test_liquidation_includes_configured_close_costs():
    p, iid = wallet([instrument(taker_bps=10, liquidation_bps=40)])
    fill(p, iid, 1, 1, 100)
    # Maintenance plus exit costs are 1% of mark, rather than 0.5%.
    boundary = 90 / 0.99
    p.marks[iid] = boundary - 0.0001
    assert p.liquidation_candidates() == [iid]


def test_funding_debit_can_trigger_isolated_liquidation():
    p, iid = wallet()
    fill(p, iid, 1, 1, 100)
    p.marks[iid] = 91
    assert p.liquidation_candidates() == []
    funding(p, iid, 0.01, mark=91)
    assert p.positions[iid].collateral == pytest.approx(9.09)
    assert p.liquidation_candidates() == [iid]


def test_cross_uses_shared_cash_while_isolated_does_not():
    cross, iid = wallet(mode='cross')
    isolated, _ = wallet()
    for p in [cross, isolated]:
        fill(p, iid, 1, 1, 100)
        p.marks[iid] = 90
    assert cross.liquidation_candidates() == []
    assert isolated.liquidation_candidates() == [iid]


def test_cross_hedged_upl_aggregates_but_gross_margin_remains():
    specs = [instrument(symbol='BTCUSDT'), instrument(symbol='ETHUSDT')]
    p, iid = wallet(specs, mode='cross')
    fill(p, iid, 1, 1, 100)
    fill(p, specs[1].id, -1, 1, 100)
    p.marks = {s.id:90 for s in specs}
    assert p.equity() == 1000
    assert p.margin_used() == 18
    assert p.exposure() == (90,90)
    assert p.liquidation_candidates() == []


def test_exchange_wallets_never_mutually_collateralize():
    specs = [instrument('binance'), instrument('bybit')]
    p, iid = wallet(specs, mode='cross', balances={'binance':10.0, 'bybit':1000.0})
    fill(p, iid, 1, 1, 100)
    p.marks[iid] = 90
    assert p.liquidation_candidates() == [iid]
    assert p.cash['bybit'] == 1000
    assert p.venue_equity('binance') == 0


def test_gap_liquidation_retains_deficit_and_charges_penalty_once():
    p, iid = wallet([instrument(liquidation_bps=100)], balances={'binance':10.0})
    fill(p, iid, 1, 1, 100)
    p.marks[iid] = 80
    assert p.liquidation_candidates() == [iid]
    fill(p, iid, -1, 1, 80, seconds=1, forced=True, exit_reason='liquidation')
    assert p.realized == -20
    assert p.liquidation_fees == pytest.approx(0.8)
    assert p.cash['binance'] == pytest.approx(-10.8)
    assert p.equity() == pytest.approx(-10.8)
    assert p.trades[0]['net_pnl'] == pytest.approx(-20.8)
    assert p.positions[iid].quantity == 0


def test_slippage_already_embedded_in_fill_pnl():
    p, iid = wallet()
    fill(p, iid, 1, 1, 101, reference_price=100)
    fill(p, iid, -1, 1, 109, seconds=1, reference_price=110)
    assert p.realized == 8
    assert p.slippage == 2
    assert p.cash['binance'] == 1008
    assert p.trades[0]['net_pnl'] == 8
    assert p.trades[0]['slippage'] == 2


def test_opening_fee_is_in_margin_admission():
    p, iid = wallet([instrument(taker_bps=10)], balances={'binance':10.0})
    result = p.apply_fill(iid, 1, 1, 100, T, 'taker', 'market')
    assert result == (False, 'margin')
    assert p.cash['binance'] == 10
    assert p.positions[iid].quantity == 0


def test_insolvent_cross_wallet_can_reduce_risk():
    p, iid = wallet(mode='cross', balances={'binance':10.0})
    fill(p, iid, 1, 1, 100)
    p.marks[iid] = 80
    fill(p, iid, -1, 0.5, 80, seconds=1)
    assert p.positions[iid].quantity == 0.5
    assert p.cash['binance'] == 0


def test_snapshot_equity_reconciles_account_cash_and_unrealized():
    specs = [instrument('binance'), instrument('bybit')]
    p, iid = wallet(specs)
    fill(p, iid, 1, 1, 100)
    fill(p, specs[1].id, -1, 2, 100)
    funding(p, specs[1].id, -0.001, mark=90)
    p.marks[iid] = 110
    row = p.snapshot(T + pd.Timedelta(seconds=2))
    assert row['equity'] == pytest.approx(2029.82)
    assert row['equity'] == pytest.approx(row['cash'] + row['unrealized_pnl'])
    assert row['equity'] == pytest.approx(row['binance_equity'] + row['bybit_equity'])
    assert row['collateral'] == row['margin_used']


def test_cross_reversal_does_not_double_debit_existing_unrealized_loss():
    p, iid = wallet(mode='cross', balances={'binance':20.0})
    fill(p, iid, 1, 1, 100)
    p.marks[iid] = 90
    fill(p, iid, -1, 2, 90, seconds=1)
    # Old loss becomes realized: cash=10, short margin=9, available=1.
    assert p.cash['binance'] == 10
    assert p.positions[iid].quantity == -1
    assert p.available('binance') == pytest.approx(1)


def test_cross_reversal_does_not_double_credit_existing_unrealized_profit():
    p, iid = wallet(mode='cross', balances={'binance':10.0})
    fill(p, iid, 1, 1, 100)
    p.marks[iid] = 110
    outcome = p.apply_fill(iid, -1, 3.5, 110, T + pd.Timedelta(seconds=1), 'taker', 'market')
    # Closing earns 10, yielding 20 cash, insufficient for new short IM=27.5.
    assert outcome == (False, 'margin')
    assert p.positions[iid].quantity == 1
    assert p.cash['binance'] == 10


class EnterHedge(BaseStrategy):
    def on_bar(self, context, bar):
        if context.now == T + pd.Timedelta(minutes=1):
            side = 1 if 'BTC' in bar['instrument_id'] else -1
            context.target(bar['instrument_id'], side)


def hedged_engine_fixture(last_mark=80):
    specs = [instrument(symbol='BTCUSDT'), instrument(symbol='ETHUSDT')]
    config = SimulationConfig(initial_balances={'binance':20.0}, leverage=10,
                              max_gross_leverage=20, max_position_pct=20,
                              margin_mode='cross', slippage_bps=0, participation=1)
    rows = []
    for minute in range(3):
        mark = last_mark if minute == 2 else 100
        for s in specs:
            rows.append(dict(timestamp=T + pd.Timedelta(minutes=minute), instrument_id=s.id,
                             open=mark, high=mark, low=mark, close=mark, volume=100,
                             duration_seconds=60, mark_open=mark, mark_price=mark))
    return Engine(specs,config), pd.DataFrame(rows), specs


def test_simultaneous_cross_marks_cannot_cause_transient_false_liquidation():
    engine, bars, specs = hedged_engine_fixture()
    result = engine.run(bars, EnterHedge())
    # Simultaneous 100->80 marks offset exactly across the hedge.
    assert result.events[result.events.type == 'LIQUIDATION'].empty
    assert engine.portfolio.positions[specs[0].id].quantity == 1
    assert engine.portfolio.positions[specs[1].id].quantity == -1
    assert engine.portfolio.equity() == 20


def test_simultaneous_funding_marks_are_batched_before_cross_risk():
    engine, bars, specs = hedged_engine_fixture(last_mark=100)
    settlements = pd.DataFrame([
        dict(timestamp=T + pd.Timedelta(seconds=90), instrument_id=s.id,
             funding_rate=0, mark_price=80) for s in specs])
    result = engine.run(bars, EnterHedge(), funding=settlements)
    assert result.events[result.events.type == 'LIQUIDATION'].empty
    assert len(result.funding) == 2


def test_duplicate_historical_settlements_rejected_before_cash_mutation():
    engine, bars, specs = hedged_engine_fixture(last_mark=100)
    row = dict(timestamp=T + pd.Timedelta(seconds=90), instrument_id=specs[0].id,
               funding_rate=0.01, mark_price=100)
    with pytest.raises(ValueError, match='Duplicate funding'):
        engine.run(bars, EnterHedge(), funding=pd.DataFrame([row,row]))
    assert engine.portfolio.cash['binance'] == 20


class EnterLongOnce(BaseStrategy):
    def on_bar(self, context, bar):
        if context.now == T + pd.Timedelta(minutes=1):
            context.target(bar['instrument_id'], 1)


def long_engine_fixture():
    s = instrument()
    config = SimulationConfig(initial_balances={'binance':1000.0}, leverage=10,
                              max_gross_leverage=20, max_position_pct=20,
                              slippage_bps=0, participation=1)
    rows = [dict(timestamp=T + pd.Timedelta(minutes=minute), instrument_id=s.id,
                 open=100, high=100, low=100, close=100, volume=100,
                 duration_seconds=60, mark_open=100, mark_price=100)
            for minute in range(3)]
    return Engine([s],config), pd.DataFrame(rows), s


def test_last_trade_crash_does_not_liquidate_stable_explicit_mark():
    engine, bars, spec = long_engine_fixture()
    bars.loc[2,['open','high','low','close']] = 80
    result = engine.run(bars, EnterLongOnce())
    assert result.events[result.events.type == 'LIQUIDATION'].empty
    assert engine.portfolio.positions[spec.id].quantity == 1
    assert engine.portfolio.unrealized(spec.id) == 0


def test_mark_crash_liquidates_despite_stable_last_trade():
    engine, bars, spec = long_engine_fixture()
    bars.loc[2,['mark_open','mark_price']] = 80
    result = engine.run(bars, EnterLongOnce())
    liquidations = result.events[result.events.type == 'LIQUIDATION']
    assert len(liquidations) == 1
    assert liquidations.iloc[0].mark_price == 80
    assert engine.portfolio.positions[spec.id].quantity == 0


def test_funding_at_entry_timestamp_assessed_before_new_order_fills():
    engine, bars, spec = long_engine_fixture()
    settlements = pd.DataFrame([
        dict(timestamp=T + pd.Timedelta(minutes=minute), instrument_id=spec.id,
             funding_rate=0.01, mark_price=100) for minute in [1,2]])
    result = engine.run(bars, EnterLongOnce(), funding=settlements)
    assert len(result.funding) == 1
    assert result.funding.iloc[0].timestamp == T + pd.Timedelta(minutes=2)
    assert engine.portfolio.funding_pnl == -1


def test_standalone_funding_debit_liquidates_without_waiting_for_next_candle():
    engine, bars, spec = long_engine_fixture()
    event_time = T + pd.Timedelta(seconds=90)
    settlements = pd.DataFrame([dict(timestamp=event_time, instrument_id=spec.id,
                                     funding_rate=0.10, mark_price=100)])
    result = engine.run(bars, EnterLongOnce(), funding=settlements)
    liquidations = result.events[result.events.type == 'LIQUIDATION']
    assert len(liquidations) == 1
    assert liquidations.iloc[0].timestamp == event_time
    assert engine.portfolio.positions[spec.id].quantity == 0


@pytest.mark.parametrize('side,expected', [(1,90 / 0.99),(-1,110 / 1.01)])
def test_reported_liquidation_price_matches_hand_formula_with_exit_reserve(side, expected):
    p, iid = wallet([instrument(taker_bps=10,liquidation_bps=40)])
    fill(p, iid, side, 1, 100)
    assert p.liquidation_price(iid) == pytest.approx(expected)
    p.marks[iid] = expected + side * 0.001
    assert p.liquidation_candidates() == []
    p.marks[iid] = expected - side * 0.001
    assert p.liquidation_candidates() == [iid]


def test_liquidation_price_is_none_for_cross_flat_and_spot():
    cross, iid = wallet(mode='cross')
    fill(cross, iid, 1, 1, 100)
    assert cross.liquidation_price(iid) is None
    isolated, iid = wallet()
    assert isolated.liquidation_price(iid) is None
    s = Instrument('binance:spot:BTCUSDT','binance','BTCUSDT', maker_bps=0,taker_bps=0)
    spot, iid = wallet([s])
    fill(spot, iid, 1, 1, 100)
    assert spot.liquidation_price(iid) is None


def test_fully_collateralized_long_has_no_positive_liquidation_boundary():
    p, iid = wallet(leverage=1)
    fill(p, iid, 1, 1, 100)
    assert p.liquidation_price(iid) == 0
    p.positions[iid].collateral = 150
    assert p.liquidation_price(iid) == 0
    p.marks[iid] = 0.001
    assert p.liquidation_candidates() == []


def test_funding_updates_reported_liquidation_boundary():
    p, iid = wallet()
    fill(p, iid, 1, 1, 100)
    funding(p, iid, 0.01)
    # Isolated collateral falls 10->9; the long boundary rises accordingly.
    assert p.liquidation_price(iid) == pytest.approx(91 / 0.995)


def test_reported_maintenance_margin_excludes_exit_reserve_and_sums_by_venue():
    specs = [instrument('binance',taker_bps=10,liquidation_bps=40),
             instrument('bybit',maintenance_rate=0.01)]
    p, iid = wallet(specs)
    fill(p, iid, 1, 2, 100)
    fill(p, specs[1].id, -1, 3, 100)
    p.marks = {iid:110,specs[1].id:90}
    assert p.maintenance_margin('binance') == pytest.approx(1.1)
    assert p.maintenance_margin('bybit') == pytest.approx(2.7)
    assert p.maintenance_margin() == pytest.approx(3.8)
    assert p.snapshot(T)['maintenance_margin'] == pytest.approx(3.8)
