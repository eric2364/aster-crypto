"""Independent causal and portfolio-protocol checks for minute research."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aster.strategies.minute_research import FAMILIES, build_signals, bootstrap_daily_returns
from aster.strategies.leading_factors import FACTOR_FAMILIES, build_factor_signals, _external_asof


def frame(n=3500):
    rng=np.random.default_rng(17)
    close=100*np.exp(np.cumsum(rng.normal(.00005,.004,n)))
    return pd.DataFrame({'timestamp':pd.date_range('2025-01-01',periods=n,freq='min',tz='UTC'),
        'duration_seconds':60,'instrument_id':'s','open':close,'high':close*1.001,
        'low':close*.999,'close':close,'volume':1000})


@pytest.mark.parametrize('family',list(FAMILIES))
def test_future_prices_and_truncated_15minute_buckets_cannot_change_past(family):
    bars=frame();cut=2801
    original=build_signals(bars,family,.1)
    changed=bars.copy()
    changed.loc[cut:,['open','high','low','close']]*=100
    changed.loc[cut:,'volume']=0
    alternate=build_signals(changed,family,.1)
    prefix=build_signals(bars.iloc[:cut],family,.1)
    pd.testing.assert_series_equal(original.iloc[:cut],alternate.iloc[:cut])
    pd.testing.assert_series_equal(original.iloc[:cut],prefix)
    assert original.iloc[:cut].sum()>0  # causal comparison must contain actual entries
    assert set(original.unique())<= {0,1}
    assert original.index[0]==bars.timestamp.iloc[0]+pd.Timedelta(minutes=1)


@pytest.mark.parametrize('family',list(FAMILIES))
def test_gap_restarts_history_instead_of_carrying_indicator_state(family):
    bars=frame();bars.loc[2000:,'timestamp']+=pd.Timedelta(minutes=9)
    combined=build_signals(bars,family,.1)
    restarted=build_signals(bars.iloc[2000:],family,.1)
    pd.testing.assert_series_equal(combined.iloc[2000:],restarted)


def test_microsecond_datetime_unit_and_unsorted_input_preserve_schedule():
    bars=frame(400)
    expected=build_signals(bars,'trend',.1)
    bars.timestamp=bars.timestamp.astype('datetime64[us, UTC]')
    pd.testing.assert_series_equal(expected,build_signals(bars.sample(frac=1,random_state=3),'trend',.1))


@pytest.mark.parametrize('fault',['naive','missing_timestamp','duplicate','nonminute','multi_symbol','impossible'])
def test_signal_inputs_reject_invalid_time_or_market_data(fault):
    bars=frame(400)
    if fault=='naive':bars.timestamp=bars.timestamp.dt.tz_localize(None)
    elif fault=='missing_timestamp':bars.loc[0,'timestamp']=pd.NaT
    elif fault=='duplicate':bars.loc[1,'timestamp']=bars.loc[0,'timestamp']
    elif fault=='nonminute':bars.loc[0,'duration_seconds']=300
    elif fault=='multi_symbol':bars.loc[0,'instrument_id']='other'
    else:bars.loc[0,'high']=1
    with pytest.raises(ValueError):build_signals(bars,'trend')


def test_bootstrap_constant_return_exact_and_small_sample_not_overconfident():
    result=bootstrap_daily_returns(np.full(90,.001),samples=1000)
    assert result['mean_daily_ci95']==pytest.approx([.001,.001])
    assert result['mean_daily_ci99_bonferroni5']==pytest.approx([.001,.001])
    assert result['daily_observations']==90
    assert bootstrap_daily_returns(np.ones(13))['mean_daily_ci95'] is None


def test_bootstrap_is_seeded_and_bonferroni_interval_is_wider():
    returns=np.sin(np.arange(90))*.02
    first=bootstrap_daily_returns(returns,samples=1000)
    assert first==bootstrap_daily_returns(returns,samples=1000)
    lo,hi=first['mean_daily_ci95'];low,high=first['mean_daily_ci99_bonferroni5']
    assert low<=lo<=hi<=high
    with pytest.raises(ValueError):bootstrap_daily_returns([np.nan])


def runner():
    path=Path(__file__).resolve().parents[1]/'examples/minute_research/run.py'
    spec=importlib.util.spec_from_file_location('audited_minute_runner',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_sleeve_aggregation_adds_assets_but_recomputes_ratios(tmp_path):
    module=runner();rows=[]
    for i in range(2):
        root=tmp_path/str(i);root.mkdir()
        ledger=pd.DataFrame({'timestamp':pd.date_range('2025-01-01',periods=2,freq='D',tz='UTC'),
            'equity':[100,100],'gross_exposure':[50,50],'net_exposure':[50,50],
            'margin_used':[0,0],'gross_leverage':[.5,.5],'net_leverage':[.5,.5],
            'margin_utilization':[0,0]})
        ledger.to_parquet(root/'equity.parquet',index=False)
        pd.DataFrame().to_parquet(root/'trades.parquet');pd.DataFrame().to_parquet(root/'fills.parquet')
        rows.append({'path':str(root)})
    pooled,score=module.aggregate(rows)
    assert pooled.equity.eq(200).all()
    assert pooled.gross_exposure.eq(100).all()
    assert pooled.gross_leverage.eq(.5).all()
    assert pooled.net_leverage.eq(.5).all()
    assert score['max_gross_leverage']==.5


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_bootstrap_retains_real_terminal_midnight_valuation_change(unit):
    module=runner()
    ledger=pd.DataFrame({'timestamp':pd.date_range('2026-07-05',periods=91,freq='D',tz='UTC'),
                         'equity':[100.]*90+[150.]})
    ledger.timestamp=ledger.timestamp.astype(f'datetime64[{unit}, UTC]')
    unchanged=ledger.copy(deep=True)
    result=module.bootstrap(ledger)
    assert result['return_interval_95'][1]>0  # terminal50%profit must not disappear
    assert result['return_interval_bonferroni_8_families'][1]>0
    pd.testing.assert_frame_equal(ledger,unchanged)


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_report_combined_policy_bootstrap_supports_actual_parquet_datetime_units(unit):
    path=Path(__file__).resolve().parents[1]/'examples/minute_research/report.py'
    spec=importlib.util.spec_from_file_location('audited_minute_report',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    ledger=pd.DataFrame({'timestamp':pd.date_range('2026-07-05',periods=91,freq='D',tz='UTC'),
                         'equity':[100.]*90+[150.]})
    ledger.timestamp=ledger.timestamp.astype(f'datetime64[{unit}, UTC]')
    unchanged=ledger.copy(deep=True)
    result=module.combined_bootstrap(ledger)
    assert result['total_policy_tests']==13
    assert result['bonferroni_13_interval'][1]>0
    pd.testing.assert_frame_equal(ledger,unchanged)


def test_deep_drawdown_cannot_pass_the_research_hurdles(monkeypatch,tmp_path):
    module=runner()
    class Pool:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def map(self,func,jobs):
            for family,symbol,scale,phase,start,end,stress,cache,out in jobs:
                yield {'family':family,'symbol':symbol,'scale':scale,'phase':phase,
                       'stress':stress,'path':'mock','metrics':{'total_return':.1}}
    equity=pd.DataFrame({'timestamp':pd.date_range('2026-07-05',periods=2,freq='D',tz='UTC'),
                         'equity':[100,110]})
    monkeypatch.setattr(module,'ProcessPoolExecutor',Pool)
    monkeypatch.setattr(module,'aggregate',lambda rows:(equity,{'total_return':.1,'sharpe':1,'max_drawdown':.8}))
    monkeypatch.setattr(module,'anchored_months',lambda *args:[.01,.01,.01])
    monkeypatch.setattr(module,'bootstrap',lambda *args:{})
    monkeypatch.setattr(module.sys,'argv',['run.py','--out',str(tmp_path)])
    module.main()
    summary=json.loads((tmp_path/'summary.json').read_text())
    assert summary['pass_count']==0
    assert all(not record['checks']['sampled_drawdown_within20pct'] for record in summary['families'])


@pytest.mark.parametrize('family',list(FACTOR_FAMILIES))
def test_factor_future_target_leader_and_funding_cannot_change_prefix(family):
    bars=frame();bars.instrument_id='binance:spot:ETHUSDT';leader=frame()
    leader.instrument_id='binance:spot:BTCUSDT'
    leader[['open','high','low','close']]=leader[['open','high','low','close']].rolling(2,min_periods=1).mean()
    funding=pd.DataFrame({'timestamp':bars.timestamp.iloc[::480],
        'funding_rate':-.001,'instrument_id':'binance:perpetual:ETHUSDT'})
    cut=2801;original=build_factor_signals(bars,family,leader,funding,scale=.1)
    later=bars.copy();later.loc[cut:,['open','high','low','close']]*=100
    future_leader=leader.copy();future_leader.loc[cut:,['open','high','low','close']]*=.01
    future_funding=funding.copy()
    future_funding.loc[future_funding.timestamp>=bars.timestamp.iloc[cut],'funding_rate']=1
    changed=build_factor_signals(later,family,future_leader,future_funding,scale=.1)
    pd.testing.assert_series_equal(original.iloc[:cut],changed.iloc[:cut])
    truncated=build_factor_signals(bars.iloc[:cut],family,leader.iloc[:cut],
        funding[funding.timestamp<bars.timestamp.iloc[cut]],scale=.1)
    pd.testing.assert_series_equal(original.iloc[:cut],truncated)


def test_delayed_published_funding_and_pepe_alias_are_point_in_time():
    bars=frame(260);start=bars.timestamp.iloc[0]
    bars.instrument_id='binance:spot:PEPEUSDT'
    prices=100*np.exp(np.arange(len(bars))*.0005)
    bars[['open','high','low','close']]=np.repeat(prices[:,None],4,axis=1)
    funding=pd.DataFrame({'timestamp':[start+pd.Timedelta(minutes=50)],
        'available_at':[start+pd.Timedelta(minutes=150)],'funding_rate':[-.001],
        'instrument_id':['binance:perpetual:1000PEPEUSDT'],
        'spot_instrument_id':['binance:spot:PEPEUSDT']})
    signals=build_factor_signals(bars,'funding_contrarian',funding=funding,scale=.1)
    assert signals.loc[signals.index<start+pd.Timedelta(minutes=151)].eq(0).all()
    assert signals.loc[signals.index>=start+pd.Timedelta(minutes=151)].sum()>0
    funding['available_at']=start+pd.Timedelta(minutes=40)
    with pytest.raises(ValueError):build_factor_signals(bars,'funding_contrarian',funding=funding,scale=.1)


def test_external_observation_lag_and_staleness_do_not_forward_fill_future():
    start=pd.Timestamp('2025-01-01',tz='UTC')
    features=pd.DataFrame({'value':[7.]},index=pd.DatetimeIndex([start]))
    target=pd.date_range(start,periods=5,freq='min')
    aligned=_external_asof(target,features,1,2)
    assert pd.isna(aligned.value.iloc[0])
    assert aligned.value.iloc[1:4].eq(7).all()
    assert pd.isna(aligned.value.iloc[4])


def test_btc_leader_requires_actual_btc_and_qqq_is_not_claimed():
    target=frame(400);target.instrument_id='binance:spot:ETHUSDT'
    fake_leader=frame(400);fake_leader.instrument_id='binance:spot:SOLUSDT'
    with pytest.raises(ValueError):build_factor_signals(target,'btc_lead_momentum',leader_bars=fake_leader)
    with pytest.raises(ValueError,match='QQQ'):
        build_factor_signals(target,'btc_lead_momentum',leader_bars=fake_leader,qqq=pd.DataFrame())
    target.instrument_id='binance:spot:BTCUSDT'
    assert build_factor_signals(target,'btc_lead_momentum',leader_bars=fake_leader).eq(0).all()


def test_leader_reversal_fixture_contains_an_actual_causal_entry():
    target=frame(100);leader=target.copy()
    target.instrument_id='binance:spot:ETHUSDT';leader.instrument_id='binance:spot:BTCUSDT'
    t=np.full(100,100.);l=np.full(100,100.)
    t[54:60]=[98,97,96,95.7,95.9,96];t[60:]=96
    l[54:60]=[98,97,96.9,97,97.05,97.1];l[60:]=97.1
    target[['open','high','low','close']]=np.repeat(t[:,None],4,axis=1)
    leader[['open','high','low','close']]=np.repeat(l[:,None],4,axis=1)
    signal=build_factor_signals(target,'btc_lead_reversal',leader_bars=leader,scale=.1)
    assert signal.iloc[59]==1
    assert signal.iloc[:59].eq(0).all()
