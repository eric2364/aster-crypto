from dataclasses import asdict
from types import SimpleNamespace
from pathlib import Path
import pandas as pd
import numpy as np
import pytest
from examples.cross_venue import run as r
from aster.backtest.models import Instrument
from aster.backtest.portfolio import Portfolio


def specs():
    return [Instrument(id=r.native_id(v,s),exchange=v,symbol=r.native_id(v,s).split(':')[-1],
                       market_type='perpetual',base='1000PEPE' if s=='PEPEUSDT' else s[:-4],quote='USDT',
                       tick_size=.01,lot_size=.01,min_quantity=.01,min_notional=1) for v in r.VENUES for s in r.SYMBOLS]


def test_seven_exact_phases_and_native_costs(tmp_path):
    assert len(r.PHASES)==7 and len({x[0] for x in r.PHASES})==7
    assert [x[4] for x in r.PHASES].count('alternative')==2
    assert sum(x[3] for x in r.PHASES)==2
    folders={v:tmp_path/v for v in r.VENUES}
    for v in r.VENUES:r.dump(folders[v]/'instruments.json',[asdict(s) for s in specs() if s.exchange==v])
    for stress,fees in [(False,{'binance':5,'bybit':6}),(True,{'binance':10,'bybit':12})]:
        catalog=r.catalog(folders['binance'],folders['bybit'],stress)
        assert len(catalog)==16
        assert all(x.taker_bps==fees[x.exchange] for x in catalog)
        c=r.config(stress)
        assert c.initial_balances=={'binance':50000,'bybit':50000}
        assert c.margin_mode=='cross' and c.leverage==1 and c.record_every==1
        assert c.max_gross_leverage==.5 and c.max_position_pct==.25
        assert c.slippage_bps==(16 if stress else 8)
        assert c.execution_delay_bars==int(stress)
        assert c.participation==(.025 if stress else .05)


def test_observer_original_once_unchanged_and_cross_margin():
    p=Portfolio(specs(),r.config(False));iid=r.native_id('binance','PEPEUSDT');other=r.native_id('bybit','PEPEUSDT')
    p.positions[iid].quantity=2;p.positions[iid].average_price=10;p.positions[iid].collateral=20;p.marks[iid]=12
    p.positions[other].quantity=-1;p.positions[other].average_price=10;p.positions[other].collateral=10;p.marks[other]=11
    original=p.snapshot;calls=[]
    def count(t):calls.append(t);return original(t)
    p.snapshot=count;observer=r.SnapshotObserver(p);before=dict(p.cash)
    time=pd.Timestamp('2026-04-05',tz='UTC');returned=observer(time)
    assert len(calls)==1 and returned==original(time) and p.cash==before
    row=observer.rows[0]
    assert row['matched_native_PEPEUSDT']==1
    assert row['unmatched_native_PEPEUSDT']==1 and row['unmatched_dollars_PEPEUSDT']==12
    assert row['net_marked_notional_PEPEUSDT']==13
    assert row['binance_margin_used']==24 and row['bybit_margin_used']==11
    assert row['current_mark_initial_margin_binance_PEPEUSDT']==24
    assert row['entry_collateral_field_binance_PEPEUSDT']==20
    assert row['binance_equity']==50004 and row['bybit_equity']==49999
    assert row['binance_available_margin']==49980


def test_alternative_proxy_completion_boundary_no_future():
    start=r.START;times=pd.date_range(start,periods=3,freq='min')
    bars=pd.DataFrame({'end':times+pd.Timedelta(minutes=1),'mark_price':[11.,22.,33.]})
    fund=pd.DataFrame({'timestamp':[times[1],times[2],times[2]+pd.Timedelta(minutes=1)],'mark_price':[999.]*3})
    out=r.alternative_funding(fund,bars)
    assert out.mark_price.tolist()==[11,22,33]
    assert fund.mark_price.tolist()==[999]*3
    with pytest.raises(RuntimeError):r.alternative_funding(pd.DataFrame({'timestamp':[start]}),bars)


def test_phase_clip_precedes_alternative_start_proxy(tmp_path,monkeypatch):
    begin=r.START+pd.Timedelta(minutes=1);stop=begin+pd.Timedelta(minutes=2)
    phase=('fake',begin,stop,False,'alternative');monkeypatch.setattr(r,'PHASES',[phase])
    times=pd.date_range(r.START,periods=3,freq='min')
    def fake_read(path):
        venue=Path(path).parts[0];sym=Path(path).parts[1];iid=r.native_id(venue,sym)
        if Path(path).name=='bars.parquet':
            return pd.DataFrame({'timestamp':times,'end':times+pd.Timedelta(minutes=1),'instrument_id':iid,'mark_price':[10.,20.,30.]})
        return pd.DataFrame({'timestamp':[r.START,begin,stop],'instrument_id':iid,'funding_rate':[.1,.2,.3],'mark_price':[100.]*3})
    monkeypatch.setattr(r.pd,'read_parquet',fake_read)
    bars,fund=r.phase_inputs('binance','bybit',phase)
    assert bars.timestamp.min()==begin and bars.timestamp.max()<stop
    bybit=fund[fund.instrument_id.str.startswith('bybit')]
    assert bybit.mark_price.tolist()==[10,30]*8
    assert fund.timestamp.min()==begin and fund.timestamp.max()==stop


def test_feature_missing_or_tampered_is_not_recreated(tmp_path):
    r.dump(tmp_path/'source_lock.json',{})
    frame=pd.DataFrame({'x':[1.]},index=pd.DatetimeIndex([r.START]))
    frame.to_parquet(tmp_path/'features.parquet')
    with pytest.raises(RuntimeError):r.verified_features(tmp_path)
    r.dump(tmp_path/'feature_receipt.json',{'source_lock_sha256':r.digest(tmp_path/'source_lock.json'),
        'features_sha256':r.digest(tmp_path/'features.parquet'),'availability_assumptions':{},'rows':1,'columns':['x']})
    pd.testing.assert_frame_equal(r.verified_features(tmp_path),frame)
    frame.x=2;frame.to_parquet(tmp_path/'features.parquet')
    with pytest.raises(RuntimeError):r.verified_features(tmp_path)


def test_bootstrap_26_comparison_tails_deterministic():
    times=pd.date_range(r.EVAL_START,periods=20,freq='D')
    frame=pd.DataFrame({'timestamp':times,'equity':100000*np.exp(np.arange(20)*.001)})
    a=r.conditional_interval(frame);b=r.conditional_interval(frame)
    assert a==b and a['comparison_count']==26 and a['tails']==[.05/52,1-.05/52]


def test_only_seven_phases_before_any_guard(tmp_path):
    with pytest.raises(RuntimeError):r.run_phase(tmp_path,tmp_path,tmp_path,('wrong',r.START,r.END,False,'primary'))


def test_reserve_native_venue_fees_not_second_cash_debit():
    instruments=specs()
    instruments=[r.replace(x,taker_bps=5 if x.exchange=='binance' else 6) for x in instruments]
    result=SimpleNamespace(instruments=instruments,config=r.config(False),
        positions=pd.DataFrame([{'instrument_id':r.native_id(v,'PEPEUSDT'),'quantity':1 if v=='binance' else -1,'mark_price':10.} for v in r.VENUES]),
        equity=pd.DataFrame({'equity':[100010.]}))
    before=result.equity.copy();out=r.reserve(result)
    assert out['indicative_exit_fee_reserve']==pytest.approx(.011)
    assert out['indicative_exit_slippage_reserve']==pytest.approx(.016)
    assert out['return_after_indicative_exit_reserve']==pytest.approx((100010-.027)/100000-1)
    pd.testing.assert_frame_equal(before,result.equity)


def test_synthetic_actual_engine_exports_and_cached_phase_identity(tmp_path,monkeypatch):
    begin=r.VALID_START;stop=begin+pd.Timedelta(minutes=3)
    phase=('synthetic',begin,stop,False,'primary');monkeypatch.setattr(r,'PHASES',[phase])
    monkeypatch.setattr(r,'guard',lambda *args:{})
    r.dump(tmp_path/'source_lock.json',{'sources':{str(path.relative_to(r.REPO)):r.digest(path) for path in (r.REPO/'aster').rglob('*.py')}})
    frame=pd.DataFrame(index=pd.date_range(begin,stop,freq='min'))
    for v in r.VENUES:
        for s in r.SYMBOLS:
            frame[f'yield_{v}_{s}']=np.nan;frame[f'valid_{v}_{s}']=False;frame[f'price_{v}_{s}']=100.
    frame.to_parquet(tmp_path/'features.parquet')
    r.dump(tmp_path/'feature_receipt.json',{'source_lock_sha256':r.digest(tmp_path/'source_lock.json'),
        'features_sha256':r.digest(tmp_path/'features.parquet'),'availability_assumptions':{},'rows':len(frame),'columns':list(frame)})
    instruments=[r.replace(x,maker_bps=5 if x.exchange=='binance' else 6,taker_bps=5 if x.exchange=='binance' else 6) for x in specs()]
    monkeypatch.setattr(r,'catalog',lambda *args:instruments)
    rows=[{'timestamp':t,'end':t+pd.Timedelta(minutes=1),'duration_seconds':60,'instrument_id':spec.id,
           'open':100.,'high':100.,'low':100.,'close':100.,'volume':1000.,'mark_open':100.,'mark_price':100.}
          for spec in instruments for t in pd.date_range(begin,stop,freq='min',inclusive='left')]
    funding=pd.DataFrame(columns=['timestamp','instrument_id','funding_rate','mark_price'])
    monkeypatch.setattr(r,'phase_inputs',lambda *args:(pd.DataFrame(rows),funding))
    result=r.run_phase(tmp_path,tmp_path,tmp_path,phase)
    assert result['total_return']==0 and result['liquidation_event_count']==0 and result['matched_pairs']==[]
    destination=tmp_path/'trials/synthetic'
    assert set(r.output_files(destination))==set(r.OUTPUTS) and len(r.OUTPUTS)==25
    exposure=pd.read_parquet(destination/'exposure.parquet')
    assert exposure.equity.tolist()==[100000.]*4
    assert exposure.binance_equity.tolist()==[50000.]*4
    assert exposure.bybit_equity.tolist()==[50000.]*4
    assert r.run_phase(tmp_path,tmp_path,tmp_path,phase)==result
    meta=r.read(destination/'metadata.json');meta['parameters']['valuation']='alternative';r.dump(destination/'metadata.json',meta)
    with pytest.raises(RuntimeError):r.run_phase(tmp_path,tmp_path,tmp_path,phase)


def test_partial_phase_never_overwritten(tmp_path,monkeypatch):
    phase=r.PHASES[0]
    monkeypatch.setattr(r,'guard',lambda *args:{})
    monkeypatch.setattr(r,'verified_features',lambda out:pd.DataFrame())
    destination=tmp_path/'trials'/phase[0];destination.mkdir(parents=True)
    marker=destination/'original.partial';marker.write_text('preserve')
    with pytest.raises(RuntimeError):r.run_phase(tmp_path,tmp_path,tmp_path,phase)
    assert marker.read_text()=='preserve'


def test_synthetic_observer_memory_benchmark_only():
    result=r.synthetic_memory_benchmark(100)
    assert result['synthetic'] and result['rows']==100 and result['columns']>=100
    assert result['observer_and_frame_peak_allocated_mib']<20
