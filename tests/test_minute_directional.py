"""Independent signed-signal, derivative accounting and exploratory-protocol audit."""
from importlib import import_module
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, SimulationConfig
from aster.reproducibility import verify_ledgers
from examples.minute_directional import signals as hypothesis

T=pd.Timestamp('2025-10-05',tz='UTC')


def frame(n=5000):
    rng=np.random.default_rng(27);close=100*np.exp(np.cumsum(rng.normal(0,.004,n)))
    target=pd.DataFrame({'timestamp':pd.date_range(T,periods=n,freq='min'),
        'instrument_id':'binance:perpetual:ETHUSDT','duration_seconds':60,'open':close,
        'high':close*1.001,'low':close*.999,'close':close,'volume':1e9,
        'mark_open':close,'mark_price':close})
    leader=target.copy();leader.instrument_id='binance:perpetual:BTCUSDT'
    values=100*np.exp(np.cumsum(rng.normal(0,.01,n)))
    leader[['open','high','low','close']]=np.repeat(values[:,None],4,axis=1)
    return target,leader


PRICE_FAMILIES=['slow_ema_trend','weekly_donchian','ts_momentum_agreement',
                'signed_mean_reversion','btc_conditioned_alt_lag']


@pytest.mark.parametrize('family',PRICE_FAMILIES)
def test_signed_signal_future_perturbation_and_truncated_prefix(family):
    target,leader=frame();cut=4001
    original=hypothesis.build_signals(target,family,.01,leader)
    changed=target.copy();changed.loc[cut:,['open','high','low','close']]*=100
    later_leader=leader.copy();later_leader.loc[cut:,['open','high','low','close']]*=.01
    mutated=hypothesis.build_signals(changed,family,.01,later_leader)
    prefix=hypothesis.build_signals(target.iloc[:cut],family,.01,leader.iloc[:cut])
    pd.testing.assert_series_equal(original.iloc[:cut],mutated.iloc[:cut])
    pd.testing.assert_series_equal(original.iloc[:cut],prefix)
    assert {-1,1}<=set(original.iloc[:cut].unique())
    assert set(original.unique())<= {-1,0,1}
    assert original.index[0]==target.timestamp.iloc[0]+pd.Timedelta(minutes=1)


@pytest.mark.parametrize('family',PRICE_FAMILIES[:4])
def test_directional_gap_requires_fresh_indicator_history(family):
    target,leader=frame();target.loc[3000:,'timestamp']+=pd.Timedelta(minutes=10)
    combined=hypothesis.build_signals(target,family,.01)
    restarted=hypothesis.build_signals(target.iloc[3000:],family,.01)
    pd.testing.assert_series_equal(combined.iloc[3000:],restarted)


def instrument(symbol='ETHUSDT',price_tick=.001,lot=.001):
    return Instrument('perp','binance',symbol,'perpetual',tick_size=price_tick,
        lot_size=lot,min_quantity=lot,min_notional=0,maker_bps=0,taker_bps=0,liquidation_bps=0)


def constant_bars(spec,price,n=7):
    return pd.DataFrame({'timestamp':pd.date_range(T,periods=n,freq='min'),
        'instrument_id':spec.id,'duration_seconds':60,'open':price,'high':price,'low':price,
        'close':price,'volume':1e9,'mark_open':price,'mark_price':price})


@pytest.mark.parametrize('delay',[0,1])
def test_signed_flip_fixed_units_no_principal_cash_and_actual_funding(delay):
    module=import_module('examples.minute_directional.run');spec=instrument();bars=constant_bars(spec,100)
    intent=pd.Series([1,1,-1,-1],index=pd.DatetimeIndex([T+pd.Timedelta(minutes=i) for i in [1,2,3,4]]))
    funding=pd.DataFrame([{'timestamp':T+pd.Timedelta(minutes=6),'instrument_id':spec.id,
                          'funding_rate':.001,'mark_price':100}])
    engine=Engine([spec],SimulationConfig(initial_balances={'binance':1000},leverage=1,
        max_gross_leverage=1,max_position_pct=.5,slippage_bps=0,participation=1,
        execution_delay_bars=delay))
    result=engine.run(bars,module.FixedDirectional(intent,T+pd.Timedelta(minutes=7)),funding)
    assert result.fills.quantity.tolist()==pytest.approx([2.5,5])
    assert result.fills.side.tolist()==[1,-1]
    assert result.fills.timestamp.iloc[0]==T+pd.Timedelta(minutes=1+delay)
    assert result.fills.timestamp.iloc[1]==T+pd.Timedelta(minutes=3+delay)
    assert engine.portfolio.positions[spec.id].quantity==-2.5
    assert engine.portfolio.cash['binance']==pytest.approx(1000.25)
    assert result.funding.funding_payment.sum()==pytest.approx(.25)
    assert verify_ledgers(result)


def test_pepe_short_funding_uses_native_bundle_quantity_and_price():
    module=import_module('examples.minute_directional.run');spec=instrument('1000PEPEUSDT',.000001,1)
    bars=constant_bars(spec,.01)
    signals=pd.Series([-1],index=pd.DatetimeIndex([T+pd.Timedelta(minutes=1)]))
    funding=pd.DataFrame([{'timestamp':T+pd.Timedelta(minutes=7),'instrument_id':spec.id,
                          'funding_rate':.001,'mark_price':.01}])
    engine=Engine([spec],SimulationConfig(initial_balances={'binance':1000},leverage=1,
        max_gross_leverage=1,max_position_pct=.5,slippage_bps=0,participation=1))
    result=engine.run(bars,module.FixedDirectional(signals,T+pd.Timedelta(minutes=7)),funding)
    assert engine.portfolio.positions[spec.id].quantity==-25000
    assert result.funding.funding_payment.sum()==pytest.approx(.25)
    assert result.equity.equity.iloc[-1]==pytest.approx(1000.25)
    assert len(result.fills)==1 and len(result.positions)==1  # marked, never fabricated closed
    assert verify_ledgers(result)


def test_observed_close_stop_exits_at_later_gap_open_not_guaranteed_stop_price():
    module=import_module('examples.minute_directional.run');spec=instrument();bars=constant_bars(spec,100,n=18)
    values=[99,101]*7+[90,70,50,50]
    bars[['open','high','low','close','mark_open','mark_price']]=np.repeat(np.asarray(values)[:,None],6,axis=1)
    bars.loc[15,['open','high','mark_open']]=90
    signal=hypothesis.build_signals(bars,'signed_mean_reversion',.01)
    assert signal.iloc[14]==1 and signal.iloc[15]==0
    engine=Engine([spec],SimulationConfig(initial_balances={'binance':1000},leverage=1,
        max_gross_leverage=1,max_position_pct=.5,slippage_bps=0,participation=1))
    result=engine.run(bars,module.FixedDirectional(signal,T+pd.Timedelta(minutes=18)))
    assert result.fills.price.tolist()==[90,50]
    assert result.trades.net_pnl.iloc[0]<-100
    assert verify_ledgers(result)


def test_indicative_exit_reserve_is_separate_diagnostic_and_does_not_mutate_equity():
    module=import_module('examples.minute_directional.run');spec=instrument()
    spec=Instrument(**{**spec.__dict__,'taker_bps':5})
    result=SimpleNamespace(instruments=[spec],config=SimulationConfig(initial_balances={'binance':1000},slippage_bps=8),
        positions=pd.DataFrame([{'instrument_id':spec.id,'quantity':-2,'mark_price':100}]),
        equity=pd.DataFrame([{'equity':1100.}]))
    original=result.equity.copy(deep=True)
    reserve=module.exit_reserve(result)
    assert reserve['indicative_exit_fee_reserve']==pytest.approx(.1)
    assert reserve['indicative_exit_slippage_reserve']==pytest.approx(.16)
    assert reserve['return_after_indicative_exit_reserve']==pytest.approx(.09974)
    pd.testing.assert_frame_equal(result.equity,original)


def test_training_selection_ignores_outcome_rows_and_prefers_central_scale(monkeypatch):
    module=import_module('examples.minute_directional.run')
    monkeypatch.setattr(module,'FAMILIES',{'fixture':{}})
    def aggregate(rows):
        assert all(r['phase']=='training' and not r['stress'] for r in rows)
        return None,{'sharpe':1}
    monkeypatch.setattr(module,'aggregate',aggregate)
    rows=[{'family':'fixture','phase':'training','scale':s,'stress':False} for s in module.SCALES]
    rows+=[{'family':'fixture','phase':'holdout','scale':.8,'stress':False,'sharpe':999}]
    assert module.choose_training(rows)['chosen']=={'fixture':1.}


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_directional_bootstrap_retains_terminal_pnl_for_parquet_precision(unit):
    module=import_module('examples.minute_directional.run')
    bars=pd.DataFrame({'timestamp':pd.date_range(T,periods=91,freq='D'),'equity':[100.]*90+[150.]})
    bars.timestamp=bars.timestamp.astype(f'datetime64[{unit}, UTC]')
    original=bars.copy(deep=True);interval=module.bootstrap(bars)
    assert interval['return_interval95'][1]>0
    assert interval['return_interval_bonferroni19policies'][1]>0
    pd.testing.assert_frame_equal(bars,original)


def cross_universe(n=3000):
    pieces=[]
    for i in range(8):
        symbol='1000PEPEUSDT' if i==0 else f'ALT{i}USDT'
        close=(.01 if i==0 else 100)*np.exp((i-3.5)*.00001*np.arange(n))
        pieces.append(pd.DataFrame({'timestamp':pd.date_range(T,periods=n,freq='min'),
            'instrument_id':f'binance:perpetual:{symbol}','duration_seconds':60,'close':close}))
    return pd.concat(pieces,ignore_index=True)


def test_cross_asset_native_normalized_returns_and_signed_rank_counts_are_causal():
    universe=cross_universe();signals=hypothesis.build_cross_signals(universe,scale=.01)
    assert signals.iloc[:1440].eq(0).all().all()
    assert signals.iloc[1440].eq(1).sum()==2
    assert signals.iloc[1440].eq(-1).sum()==2
    assert signals.iloc[1440].eq(0).sum()==4
    cut=T+pd.Timedelta(minutes=1901)
    mutated=universe.copy();mutated.loc[mutated.timestamp>=cut,'close']*=100
    changed=hypothesis.build_cross_signals(mutated,scale=.01)
    pd.testing.assert_frame_equal(signals.loc[signals.index<=cut],changed.loc[changed.index<=cut])
    shortened=hypothesis.build_cross_signals(universe[universe.timestamp<cut],scale=.01)
    pd.testing.assert_frame_equal(signals.loc[signals.index<=cut],shortened)
    converted=universe.copy()
    converted.loc[converted.instrument_id.str.contains('1000PEPE'),'close']*=1000
    pd.testing.assert_frame_equal(signals,hypothesis.build_cross_signals(converted,scale=.01))
    pd.testing.assert_frame_equal(signals,hypothesis.build_cross_signals(universe.sample(frac=1,random_state=2),scale=.01))


@pytest.mark.parametrize('fault',['one_missing','shared_missing','duplicate','too_few','spot_identity'])
def test_cross_rank_rejects_incomplete_or_mismatched_universe(fault):
    universe=cross_universe(1500)
    if fault=='one_missing':universe=universe.drop(index=50)
    elif fault=='shared_missing':universe=universe[universe.timestamp!=T+pd.Timedelta(minutes=50)]
    elif fault=='duplicate':universe=pd.concat([universe,universe.iloc[[50]]])
    elif fault=='too_few':universe=universe[~universe.instrument_id.str.contains('1000PEPE')]
    else:universe.loc[0,'instrument_id']='binance:spot:PEPEUSDT'
    with pytest.raises(ValueError):hypothesis.build_cross_signals(universe,scale=.01)


def test_directional_union_pooling_keeps_past_values_and_exit_reserve_separate(tmp_path):
    module=import_module('examples.minute_directional.run');rows=[]
    for i in range(2):
        folder=tmp_path/str(i);folder.mkdir()
        ledger=pd.DataFrame({'timestamp':[T,T+pd.Timedelta(minutes=i+1),T+pd.Timedelta(minutes=3)],
            'equity':[100,110+10*i,110+10*i],'gross_exposure':50,'net_exposure':50*(1 if i==0 else -1),
            'margin_used':10,'gross_leverage':.5,'net_leverage':.5*(1 if i==0 else -1),'margin_utilization':.1})
        ledger.to_parquet(folder/'equity.parquet',index=False)
        pd.DataFrame().to_parquet(folder/'trades.parquet');pd.DataFrame().to_parquet(folder/'fills.parquet')
        rows.append({'path':str(folder),'metrics':{'indicative_exit_reserve_total':i+1,'liquidation_event_count':i}})
    pooled,score=module.aggregate(rows)
    assert pooled.equity.tolist()==[200,210,230,230]
    assert pooled.net_exposure.eq(0).all()
    assert pooled.gross_leverage.iloc[-1]==pytest.approx(100/230)
    assert score['total_return']==pytest.approx(.15)
    assert score['return_after_indicative_exit_reserve']==pytest.approx(.135)
    assert score['indicative_exit_reserve_total']==3
    assert score['liquidation_event_count']==1


def test_cross_feature_cache_rejects_source_and_cached_matrix_changes(monkeypatch,tmp_path):
    module=import_module('examples.minute_directional.run');universe=cross_universe(1500)
    symbols=[]
    for iid,group in universe.groupby('instrument_id'):
        symbol=iid.rsplit(':',1)[-1];symbols.append(symbol)
        folder=tmp_path/'data'/symbol;folder.mkdir(parents=True)
        group.to_parquet(folder/'bars.parquet',index=False)
    monkeypatch.setattr(module,'SYMBOLS',symbols)
    stop=T+pd.Timedelta(minutes=1500);out=tmp_path/'out'
    path=module.cross_features(tmp_path/'data',out,stop,.01)
    assert module.cross_features(tmp_path/'data',out,stop,.01)==path
    original=path.read_bytes();path.write_bytes(b'altered cached matrix')
    with pytest.raises(RuntimeError,match='cached values changed'):
        module.cross_features(tmp_path/'data',out,stop,.01)
    path.write_bytes(original)
    source=tmp_path/'data'/symbols[0]/'bars.parquet'
    changed=pd.read_parquet(source);changed['close']*=2;changed.to_parquet(source,index=False)
    with pytest.raises(RuntimeError,match='source mismatch'):
        module.cross_features(tmp_path/'data',out,stop,.01)


@pytest.mark.parametrize('participating,passed',[(3,False),(4,True)])
def test_cross_basket_breadth_uses_actual_participation_and_keeps_losing_legs(monkeypatch,tmp_path,participating,passed):
    module=import_module('examples.minute_directional.run');family='cross_sectional_momentum'
    rows=[]
    for phase in ['validation1','validation2','validation3','holdout']:
        for scale in (module.SCALES if phase=='holdout' else [1.]):
            for stress in ([False,True] if phase=='holdout' and scale==1 else [False]):
                for i in range(8):
                    rows.append({'family':family,'scale':scale,'phase':phase,'stress':stress,
                        'symbol':f'ALT{i}','metrics':{'total_return':.1 if i<2 else -.01,
                            'fill_count':1 if i<participating else 0,'liquidation_event_count':0}})
    equity=pd.DataFrame({'timestamp':[module.EVALUATION_START,module.END],'equity':[100,110]})
    score={'total_return':.1,'return_after_indicative_exit_reserve':.09,'sharpe':1,'max_drawdown':.1}
    monkeypatch.setattr(module,'aggregate',lambda group:(equity.copy(),score.copy()))
    monkeypatch.setattr(module,'anchored_months',lambda frame:[.01,.01,.01])
    monkeypatch.setattr(module,'bootstrap',lambda frame:{})
    result=module.summarize(rows,{'chosen':{family:1.}},tmp_path,{})
    item=result['families'][0]
    assert item['traded_symbols']==participating
    assert item['positive_symbols']==2
    assert len(item['symbols'])==8
    assert item['checks']['basket_traded_at_least_four_assets']==passed
    assert item['historical_hurdles_passed']==passed
    assert 'broad_symbol_success' not in item['checks']
