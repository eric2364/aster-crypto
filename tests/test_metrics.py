import json
import numpy as np
import pandas as pd
import pytest
from aster.analytics import metrics, daily_returns, drawdown_stats, monthly_returns, rolling_statistics, regime_analysis, json_safe


def frame(values, times=None):
    return pd.DataFrame({'timestamp': times if times is not None else pd.date_range('2024-01-01', periods=len(values), freq='D', tz='UTC'), 'equity': values})


def test_manually_calculated_returns_ratios_and_drawdowns():
    e = frame([100, 110, 99, 108.9])
    m = metrics(e)
    assert daily_returns(e).to_numpy() == pytest.approx([.1, -.1, .1])
    # sample sd of [.1,-.1,.1] = sqrt(.0133333333)
    sd = np.sqrt(.013333333333333333)
    assert m['total_return'] == pytest.approx(.089)
    assert m['annualized_volatility'] == pytest.approx(sd * np.sqrt(365))
    assert m['sharpe'] == pytest.approx((.1/3) / sd * np.sqrt(365))
    assert m['sortino'] == pytest.approx((.1/3) / np.sqrt(.01/3) * np.sqrt(365))
    assert m['cagr'] == pytest.approx(1.089 ** (365/3) - 1)
    assert m['max_drawdown'] == pytest.approx(.1)
    assert m['max_drawdown_duration_days'] == 2
    assert m['currently_underwater'] is True
    assert m['max_recovery_days'] is None


def test_drawdown_recovery_uses_actual_clock_and_includes_unrecovered_duration():
    e = frame([100, 80, 100, 90], pd.to_datetime(['2024-01-01', '2024-01-04', '2024-01-08', '2024-01-10'], utc=True))
    m = drawdown_stats(e)
    assert m['max_drawdown'] == pytest.approx(.2)
    assert m['max_drawdown_duration_days'] == 7
    assert m['max_recovery_days'] == 4
    assert m['currently_underwater']


def test_intraday_sampling_initial_baseline_and_utc_days():
    e = frame([100, 110, 121], ['2024-01-01T00:00:00Z', '2024-01-01T23:00:00Z', '2024-01-02T23:00:00Z'])
    assert daily_returns(e).to_numpy() == pytest.approx([.1, .1])
    gap = frame([100, 120], ['2024-01-01T12:00:00Z', '2024-01-04T12:00:00Z'])
    assert daily_returns(gap).to_numpy() == pytest.approx([0, 0, .2])


def test_trades_cost_attribution_does_not_double_subtract_slippage():
    e = frame([1000, 1009])
    e['realized_pnl'] = [0, 12]
    e['trading_fees'] = [0, 4]
    e['funding_pnl'] = [0, 1]
    e['slippage_cost'] = [0, 3]
    e['turnover'] = [0, 400]
    trades = pd.DataFrame({'net_pnl': [18, -9, 0], 'gross_pnl': [20, -8, 0], 'holding_seconds': [60, 120, 180], 'symbol': ['BTC', 'ETH', 'BTC'], 'exchange': ['binance']*3})
    fills = pd.DataFrame({'quantity': [1, 2], 'price': [100, 150], 'fee': [1, 3], 'liquidity_type': ['maker', 'taker']})
    m = metrics(e, trades, fills)
    assert m['net_profit'] == 9
    assert m['trading_pnl'] + m['funding_pnl'] - m['trading_fees'] == m['net_profit']
    assert m['profit_factor'] == 2
    assert m['win_rate'] == pytest.approx(1/3)
    assert m['expectancy'] == 3
    assert m['average_win'] == 18 and m['average_loss'] == -9
    assert m['payoff_ratio'] == 2
    assert m['average_holding_seconds'] == 120
    assert m['maker_ratio'] == .5 and m['maker_notional_ratio'] == .25
    assert m['fees_as_fraction_gross_profit'] == .2
    assert m['slippage_as_fraction_gross_profit'] == .15
    assert m['symbol_attribution'] == {'BTC': 18, 'ETH': -9}
    assert m['pnl_per_unit_turnover'] == pytest.approx(9/400)


def test_exposure_is_duration_weighted_not_row_weighted():
    e = frame([100]*3, ['2024-01-01T00:00Z','2024-01-01T01:00Z','2024-01-01T04:00Z'])
    e['gross_exposure'] = [0, 200, 999]
    e['gross_leverage'] = [0, 2, 9.99]
    e['net_exposure'] = [0, -100, 0]
    m = metrics(e)
    assert m['average_gross_exposure'] == 150
    assert m['average_gross_leverage'] == 1.5
    assert m['exposure_time'] == .75
    assert m['average_net_leverage'] == -.75


def test_alpha_beta_by_known_linear_returns():
    b = frame([100,110,99,108.9,119.79])
    p = frame([100,120,96,115.2,138.24])
    m = metrics(p, benchmark=b)
    assert m['beta'] == pytest.approx(2)
    assert m['alpha'] == pytest.approx(0, abs=1e-12)


def test_monthly_rolling_and_regimes_are_causal():
    e = frame([100,110,121], ['2024-01-01T00:00Z','2024-01-31T23:00Z','2024-02-29T23:00Z'])
    assert monthly_returns(e)['return'].to_numpy() == pytest.approx([.1,.1])
    x = frame([100,101,103,104,110,80])
    r = rolling_statistics(x, window=2)
    assert pd.isna(r.rolling_sharpe.iloc[0])
    assert r.rolling_return.iloc[1] == pytest.approx(.03)
    a = regime_analysis(x, window=2)
    changed = x.copy(); changed.loc[5,'equity'] = 500
    b = regime_analysis(changed, window=2)
    assert a['regime'].tolist() == b['regime'].tolist()


def test_undefined_ratios_bankruptcy_and_json_are_safe():
    for e in [frame([100]), frame([100,100,100]), frame([100,0,0]), frame([100,-5]), frame([100,110], ['2024-01-01T00:00Z','2024-01-01T00:01Z'])]:
        m = metrics(e)
        json.dumps(m, allow_nan=False)
    assert metrics(frame([100,100]))['sharpe'] is None
    assert metrics(frame([100,0]))['cagr'] is None
    assert json_safe({'a': np.nan, 'b': np.inf, 'c':np.int64(2)}) == {'a':None,'b':None,'c':2}


def test_rejects_duplicate_unsorted_or_nonfinite_equity():
    with pytest.raises(ValueError): metrics(frame([100,100], ['2024-01-01','2024-01-01']))
    with pytest.raises(ValueError): metrics(frame([100,100], ['2024-01-02','2024-01-01']))
    with pytest.raises(ValueError): metrics(frame([100,np.nan]))
