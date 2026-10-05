"""Independent paired-market causal, accounting and terminal-order audit."""
import importlib.util
from dataclasses import asdict
from types import SimpleNamespace
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, SimulationConfig
from aster.backtest.portfolio import Portfolio
from aster.reproducibility import verify_ledgers


def runner():
    path=Path(__file__).resolve().parents[1]/'examples/minute_carry/run.py'
    spec=importlib.util.spec_from_file_location('audited_minute_carry',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


T=pd.Timestamp('2025-10-05',tz='UTC')


def pair(units=1):
    values=dict(maker_bps=0,taker_bps=0,min_notional=0,liquidation_bps=0,
                tick_size=.000001,lot_size=.001,min_quantity=.001)
    spot=Instrument('spot','binance','PEPEUSDT' if units==1000 else 'BTCUSDT',**values)
    perp=Instrument('perp','binance','1000PEPEUSDT' if units==1000 else 'BTCUSDT',
                    'perpetual',**values)
    return spot,perp


def bars(spec,price,n=12):
    return pd.DataFrame({'timestamp':pd.date_range(T,periods=n,freq='min'),
        'instrument_id':spec.id,'open':price,'high':price,'low':price,'close':price,
        'volume':1e9,'duration_seconds':60,'mark_open':price,'mark_price':price})


@pytest.mark.parametrize('units',[1,1000])
def test_spot_short_perp_cash_margin_funding_conservation(units):
    spot,perp=pair(units)
    p=Portfolio([spot,perp],SimulationConfig(initial_balances={'binance':1000},
        leverage=3,max_gross_leverage=3,max_position_pct=1,slippage_bps=0))
    spot_quantity=6*units;spot_price=100/units
    assert p.apply_fill(spot.id,1,spot_quantity,spot_price,T,'taker','market')==(True,'')
    assert p.apply_fill(perp.id,-1,6,100,T,'taker','market')==(True,'')
    p.marks={spot.id:spot_price,perp.id:100}
    assert p.cash['binance']==400
    assert p.margin_used()==200
    assert p.equity()==1000
    p.settle_funding({'timestamp':T+pd.Timedelta(hours=8),'instrument_id':perp.id,
                     'funding_rate':.001,'mark_price':100})
    assert p.cash['binance']==pytest.approx(400.6)
    assert p.funding_pnl==pytest.approx(.6)
    p.marks={spot.id:110/units,perp.id:110}
    assert p.equity()==pytest.approx(1000.6)
    assert p.positions[spot.id].quantity+p.positions[perp.id].quantity*units==0


def test_common_decimal_lot_grid_preserves_both_native_units():
    module=runner()
    assert module.common_step(.1,1,1000)==1000
    assert module.common_step(.3,.2,1000)==600
    assert module.common_step(.003,.002,1)==.006


def test_past_funding_publication_and_future_perturbation_are_causal():
    module=runner()
    times=pd.date_range(T,periods=6,freq='8h')
    funding=pd.DataFrame({'timestamp':times,'funding_rate':[.001,.002,-.003,.004,.005,.006]})
    clock=pd.DatetimeIndex([times[2],times[2]+pd.Timedelta(minutes=1)])
    seen=module.published_factors(funding,clock)
    assert seen.funding_rate.tolist()==[.002,-.003]
    assert pd.isna(seen.trailing_mean.iloc[0])
    assert seen.trailing_mean.iloc[1]==pytest.approx(0)
    changed=funding.copy();changed.loc[3:,'funding_rate']=-99
    pd.testing.assert_frame_equal(seen,module.published_factors(changed,clock))


@pytest.mark.parametrize('delay',[0,1])
@pytest.mark.parametrize('units',[1,1000])
def test_terminal_exit_keeps_delayed_orders_until_last_eligible_open(delay,units):
    module=runner();spot,perp=pair(units);n=12;end=T+pd.Timedelta(minutes=n)
    frame=pd.concat([bars(spot,100/units,n),bars(perp,100,n)],ignore_index=True)
    strategy=module.MatchedCarry(spot.id,perp.id,units,
        pd.Series([1],index=pd.DatetimeIndex([T+pd.Timedelta(minutes=1)])),1000,end)
    config=SimulationConfig(initial_balances={'binance':1000},leverage=2,
        max_gross_leverage=1,max_position_pct=.5,slippage_bps=0,
        participation=1,execution_delay_bars=delay)
    engine=Engine([spot,perp],config)
    result=engine.run(frame,strategy)
    assert len(result.fills)==4
    assert result.positions.empty
    assert result.fills.timestamp.max()<=end-pd.Timedelta(minutes=1)
    assert result.equity.equity.iloc[-1]==pytest.approx(1000)
    assert verify_ledgers(result)


def test_rotation_ranking_never_reads_future_cross_asset_settlements(monkeypatch,tmp_path):
    module=runner();symbols=['BTCUSDT','ETHUSDT','DOGEUSDT'];module.SYMBOLS=symbols
    times=pd.date_range(module.START,periods=15,freq='8h')
    histories={s:pd.DataFrame({'timestamp':times,'funding_rate':rate})
               for s,rate in zip(symbols,[.001,.002,.003])}
    def read(path):return histories[Path(path).parent.name].copy()
    monkeypatch.setattr(module.pd,'read_parquet',read)
    stop=module.START+pd.Timedelta(days=4)
    first=module.rotation_signals(tmp_path,tmp_path,module.START,stop)
    cut=module.START+pd.Timedelta(days=2)
    histories['BTCUSDT'].loc[histories['BTCUSDT'].timestamp>=cut,'funding_rate']=9
    later=module.rotation_signals(tmp_path,tmp_path,module.START,stop)
    pd.testing.assert_frame_equal(first.loc[first.index<cut],later.loc[later.index<cut])
    assert first.iloc[1:3].sum(axis=1).eq(2).all()


def test_pooled_equity_uses_union_and_past_values_not_future_fill(tmp_path):
    module=runner();rows=[]
    for i in range(2):
        folder=tmp_path/str(i);folder.mkdir()
        times=[T,T+pd.Timedelta(minutes=1+i),T+pd.Timedelta(minutes=3)]
        values=[100,110 if i==0 else 120,110 if i==0 else 120]
        frame=pd.DataFrame({'timestamp':times,'equity':values,'gross_exposure':50,
                           'net_exposure':0,'margin_used':10,'gross_leverage':.5,
                           'net_leverage':0,'margin_utilization':.1})
        frame.to_parquet(folder/'equity.parquet',index=False)
        pd.DataFrame().to_parquet(folder/'trades.parquet');pd.DataFrame().to_parquet(folder/'fills.parquet')
        rows.append({'path':str(folder)})
    combined,score=module.aggregate(rows)
    assert combined.equity.tolist()==[200,210,230,230]
    assert combined.gross_leverage.iloc[-1]==pytest.approx(100/230)
    assert score['total_return']==pytest.approx(.15)


def test_residual_hedge_is_marked_and_owes_terminal_negative_funding():
    module=runner();spot,perp=pair();n=12;end=T+pd.Timedelta(minutes=n)
    s=bars(spot,100,n);p=bars(perp,100,n)
    # Entry executes normally; no completed prior liquidity remains for the exit.
    s.loc[8:,'volume']=0;p.loc[8:,'volume']=0
    strategy=module.MatchedCarry(spot.id,perp.id,1,
        pd.Series([1],index=pd.DatetimeIndex([T+pd.Timedelta(minutes=1)])),1000,end)
    funding=pd.DataFrame([{'timestamp':end,'instrument_id':perp.id,'funding_rate':-.01,'mark_price':100}])
    engine=Engine([spot,perp],SimulationConfig(initial_balances={'binance':1000},leverage=2,
        max_gross_leverage=1,max_position_pct=.5,slippage_bps=0,participation=1,execution_delay_bars=1))
    result=engine.run(pd.concat([s,p],ignore_index=True),strategy,funding)
    assert len(result.fills)==2
    assert len(result.positions)==2  # truthful marked residuals, no fabricated terminal fill
    assert result.funding.funding_payment.sum()==pytest.approx(-3)
    assert result.equity.equity.iloc[-1]==pytest.approx(997)
    assert verify_ledgers(result)


def test_run_job_preserves_funding_at_its_terminal_valuation_boundary(monkeypatch,tmp_path):
    module=runner();spot,perp=pair();spot=Instrument(**{**asdict(spot),'symbol':'BTCUSDT'})
    roots=[tmp_path/'spot',tmp_path/'perp'];stop=module.TRAIN_END
    for root,spec in zip(roots,[spot,perp]):
        folder=root/'BTCUSDT';folder.mkdir(parents=True)
        bars(spec,100,2).to_parquet(folder/'bars.parquet',index=False)
        (root/'instruments.json').write_text(json.dumps([asdict(spec)]))
        (folder/'source_manifest.json').write_text('{}')
    funding=pd.DataFrame([{'timestamp':stop,'instrument_id':perp.id,'funding_rate':-.01,'mark_price':100}])
    funding.to_parquet(roots[1]/'BTCUSDT'/'funding.parquet',index=False)
    mapping={'spot_symbol':'BTCUSDT','perpetual_instrument_id':perp.id,
             'spot_base_units_per_perpetual_quantity_unit':1}
    (roots[1]/'cross_mapping.json').write_text(json.dumps({'mapping':[mapping]}))
    captured=[]
    class FakeEngine:
        def __init__(self,*args):pass
        def run(self,bars,strategy,funding):
            captured.append(funding.copy());return SimpleNamespace(positions=pd.DataFrame())
    monkeypatch.setattr(module,'Engine',FakeEngine)
    monkeypatch.setattr(module,'verify_ledgers',lambda result:True)
    monkeypatch.setattr(module,'export_result',lambda *args,**kwargs:(tmp_path,{'total_return':0}))
    module.run_job(('always_hedged','BTCUSDT','training',False,str(roots[0]),str(roots[1]),str(tmp_path/'out'),None))
    assert captured[0].timestamp.tolist()==[stop]


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_carry_interval_preserves_terminal_valuation_for_actual_parquet_units(unit):
    module=runner()
    frame=pd.DataFrame({'timestamp':pd.date_range('2026-07-05',periods=91,freq='D',tz='UTC'),
                        'equity':[100.]*90+[150.]})
    frame.timestamp=frame.timestamp.astype(f'datetime64[{unit}, UTC]')
    original=frame.copy(deep=True)
    values=module.interval(frame)
    assert values['return_interval95'][1]>0
    assert values['return_interval_bonferroni13policies'][1]>0
    pd.testing.assert_frame_equal(frame,original)
