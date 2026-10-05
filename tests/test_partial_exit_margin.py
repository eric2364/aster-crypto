"""Independent margin allocation hand cases, distinct from cash reconciliation."""
import pandas as pd
import pytest
from aster.backtest.models import Instrument, SimulationConfig
from aster.backtest.portfolio import Portfolio

TIME = pd.Timestamp('2026-01-01', tz='UTC')


def account(side=1, fee_bps=0, leverage=1, mode='isolated'):
    spec = Instrument('binance:perpetual:TESTUSDT', 'binance', 'TESTUSDT', 'perpetual',
                      taker_bps=fee_bps, maker_bps=0, liquidation_bps=0,
                      min_quantity=.001, min_notional=0, maintenance_rate=.005)
    portfolio = Portfolio([spec], SimulationConfig(initial_balances={'binance': 1000},
                           margin_mode=mode, leverage=leverage, max_gross_leverage=20,
                           max_position_pct=20, slippage_bps=0))
    assert portfolio.apply_fill(spec.id, side, 1, 100, TIME, 'taker', 'market') == (True, '')
    return portfolio, spec.id


@pytest.mark.parametrize('side,exit_price', [(1, 95), (-1, 105), (1, 105), (-1, 95)])
def test_closed_leg_result_does_not_transfer_to_residual_isolated_margin(side, exit_price):
    portfolio, iid = account(side)
    portfolio.marks[iid] = exit_price
    assert portfolio.apply_fill(iid, -side, .95, exit_price, TIME + pd.Timedelta(minutes=1),
                                'taker', 'market') == (True, '')
    assert portfolio.positions[iid].quantity == pytest.approx(side * .05)
    assert portfolio.positions[iid].collateral == pytest.approx(5)
    assert portfolio.cash['binance'] == pytest.approx(1000 + side * .95 * (exit_price - 100))
    assert portfolio.unrealized(iid) == pytest.approx(side * .05 * (exit_price - 100))
    assert portfolio.available('binance') == pytest.approx(portfolio.cash['binance'] - 5)
    assert portfolio.liquidation_candidates() == []


def test_closed_execution_fee_is_paid_by_cash_not_remaining_isolated_reserve():
    portfolio, iid = account(fee_bps=5)
    portfolio.marks[iid] = 95
    portfolio.apply_fill(iid, -1, .95, 95, TIME + pd.Timedelta(minutes=1), 'taker', 'market')
    assert portfolio.cash['binance'] == pytest.approx(1000 - .05 - 4.75 - .045125)
    assert portfolio.positions[iid].collateral == pytest.approx(5)
    assert portfolio.positions[iid].taker_fees == pytest.approx(.0025)
    assert portfolio.trades[0]['taker_fees'] == pytest.approx(.0475 + .045125)
    assert portfolio.liquidation_candidates() == []


@pytest.mark.parametrize('rate,expected_reserve', [(.02, 4.9), (-.02, 5.1)])
def test_partial_exit_releases_proportional_funding_adjusted_reserve(rate, expected_reserve):
    portfolio, iid = account()
    portfolio.settle_funding({'instrument_id': iid, 'timestamp': TIME + pd.Timedelta(seconds=1),
                             'funding_rate': rate, 'mark_price': 100})
    portfolio.marks[iid] = 95
    portfolio.apply_fill(iid, -1, .95, 95, TIME + pd.Timedelta(minutes=1), 'taker', 'market')
    assert portfolio.positions[iid].collateral == pytest.approx(expected_reserve)
    assert portfolio.positions[iid].funding == pytest.approx(-5 * rate)
    assert portfolio.trades[0]['funding_pnl'] == pytest.approx(-95 * rate)
    assert portfolio.cash['binance'] == pytest.approx(1000 - 100 * rate - 4.75)
    assert portfolio.liquidation_candidates() == []


def test_partial_exit_still_preserves_genuine_residual_isolated_liquidation():
    portfolio, iid = account(leverage=10)
    portfolio.apply_fill(iid, -1, .95, 99, TIME + pd.Timedelta(minutes=1), 'taker', 'market')
    assert portfolio.positions[iid].collateral == pytest.approx(.5)
    portfolio.marks[iid] = 89
    # Remaining .05 has -.55 unrealized against .5 reserve; free wallet cannot rescue it.
    assert portfolio.liquidation_candidates() == [iid]


def test_split_close_and_single_close_have_same_cash_without_interim_forced_exit():
    split, iid = account(fee_bps=5)
    whole, other = account(fee_bps=5)
    split.marks[iid] = whole.marks[other] = 95
    split.apply_fill(iid, -1, .95, 95, TIME + pd.Timedelta(minutes=1), 'taker', 'market')
    assert split.liquidation_candidates() == []
    split.apply_fill(iid, -1, .05, 95, TIME + pd.Timedelta(minutes=2), 'taker', 'market')
    whole.apply_fill(other, -1, 1, 95, TIME + pd.Timedelta(minutes=2), 'taker', 'market')
    assert split.cash == pytest.approx(whole.cash)
    assert split.margin_used() == whole.margin_used() == 0
    assert sum(t['net_pnl'] for t in split.trades) == pytest.approx(sum(t['net_pnl'] for t in whole.trades))


def test_cross_margin_partial_exit_keeps_wallet_and_mark_based_reserve():
    portfolio, iid = account(mode='cross')
    portfolio.marks[iid] = 95
    portfolio.apply_fill(iid, -1, .95, 95, TIME + pd.Timedelta(minutes=1), 'taker', 'market')
    assert portfolio.cash['binance'] == pytest.approx(995.25)
    assert portfolio.margin_used() == pytest.approx(4.75)
    assert portfolio.equity() == pytest.approx(995)
    assert portfolio.liquidation_candidates() == []


def test_spot_partial_exit_has_no_isolated_margin_allocation():
    spec = Instrument('binance:spot:TESTUSDT', 'binance', 'TESTUSDT', 'spot',
                      min_notional=0, taker_bps=5)
    portfolio = Portfolio([spec], SimulationConfig(initial_balances={'binance': 1000},
                          margin_mode='isolated', max_position_pct=1))
    portfolio.apply_fill(spec.id, 1, 1, 100, TIME, 'taker', 'market')
    portfolio.marks[spec.id] = 95
    portfolio.apply_fill(spec.id, -1, .95, 95, TIME + pd.Timedelta(minutes=1), 'taker', 'market')
    assert portfolio.cash['binance'] == pytest.approx(1000 - 100 - .05 + .95 * 95 - .95 * 95 * .0005)
    assert portfolio.equity() == pytest.approx(995 - .05 - .95 * 95 * .0005)
    assert portfolio.margin_used() == 0
    assert portfolio.positions[spec.id].collateral == 0
    assert portfolio.liquidation_candidates() == []
