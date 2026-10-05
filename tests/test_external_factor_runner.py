"""Independent runner protocol, cutoff and inventory tests; no market outcomes."""
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from examples.external_factors import run as r
from aster.backtest.engine import Engine
from aster.backtest.models import Instrument,SimulationConfig
from aster.reproducibility import verify_ledgers

T=pd.Timestamp('2025-10-05',tz='UTC')


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_bootstrap_actual_timestamp_units_endpoint_and24_tails(unit):
    frame=pd.DataFrame({'timestamp':pd.date_range(T,periods=91,freq='D'),
                        'equity':[100.]*90+[150.]})
    frame.timestamp=frame.timestamp.astype(f'datetime64[{unit}, UTC]')
    before=frame.copy();out=r.bootstrap(frame)
    assert out['cumulative_economic_candidate_count']==24
    assert out['return_interval95'][1]>0
    assert out['return_interval_bonferroni24policies'][1]>0
    pd.testing.assert_frame_equal(frame,before)
    pd.testing.assert_series_equal(pd.Series(out['return_interval95']),pd.Series(r.bootstrap(frame)['return_interval95']))


@pytest.mark.parametrize('family',['qqq_risk_transmission','cpi_acceleration_event','taker_flow_drift'])
def test_macro_flow_phase_publication_cutoffs_before_build(monkeypatch,family):
    stop=T+pd.Timedelta(hours=1)
    frame=pd.DataFrame({'timestamp':[T,T], 'source_timestamp':[T,T], 'release_time':[T,T],
                        'available_at':[stop,stop+pd.Timedelta(seconds=1)]})
    monkeypatch.setattr(r.pd,'read_parquet',lambda *a,**kw:frame.copy())
    kw=r.phase_inputs(family,'PEPEUSDT',None,None,stop,'spot','factors',{})
    assert len(next(iter(kw.values())))==1
    assert next(iter(kw.values())).available_at.iloc[0]==stop


def test_funding_predictor_receipt_cutoff_cash_separate():
    stop=T+pd.Timedelta(hours=1)
    funding=pd.DataFrame({'timestamp':[T,T+pd.Timedelta(minutes=30)],
                          'available_at':[stop-pd.Timedelta(minutes=1),stop],
                          'funding_rate':[.001,.002]})
    kw=r.phase_inputs('funding_crowding_fade','PEPEUSDT',None,funding,stop,'spot','factors',{})
    assert len(kw['funding'])==1
    assert len(funding)==2  # Receipt cutoff never mutates settlement cash source.


def test_activity_uses_actual_signed_fills_including_delayed_unfilled_intents():
    clock=pd.date_range(T+pd.Timedelta(minutes=1),periods=5,freq='min')
    signals=pd.Series([1,1,-1,-1,0],index=clock)
    result=SimpleNamespace(fills=pd.DataFrame({'timestamp':[clock[1],clock[3]],
                                              'quantity':[10.,20.],'side':[1,-1]}),
                           instruments=[SimpleNamespace(lot_size=1.)])
    out=r.activity(signals,result,'funding_crowding_fade',{},T,clock[-1])
    assert out['active_signal_minutes']==4
    assert out['actual_position_minutes_by_calendar_month']['2025-10']=={'long_minutes':2,'short_minutes':2}
    assert out['signal_minutes_by_calendar_month']['2025-10']=={'long_minutes':2,'short_minutes':2}
    # Flat intent at the last minute has not filled; actual inventory remains short.
    assert out['entry_intent_count']==2


def test_no_fills_and_cpi_event_counts_are_distinct_from_intents():
    clock=pd.date_range(T+pd.Timedelta(minutes=1),periods=3,freq='min')
    signals=pd.Series([0,0,0],index=clock)
    events=pd.DataFrame({'release_time':[T-pd.Timedelta(days=30),T],
                         'available_at':[T-pd.Timedelta(days=30)+pd.Timedelta(minutes=1),clock[0]],
                         'reference_month':['2025-08','2025-09'],'headline_yoy':[2.,2.2],'core_yoy':[2.,2.2]})
    out=r.activity(signals,SimpleNamespace(fills=pd.DataFrame()),'cpi_acceleration_event',{'cpi':events},T,clock[-1])
    assert out['phase_cpi_release_count']==1
    assert out['phase_cpi_directional_source_event_count']==1
    assert out['phase_directional_cpi_release_times']==[]
    assert out['actual_position_minutes_by_calendar_month']['2025-10']=={'long_minutes':0,'short_minutes':0}


def training_rows():
    return [dict(family=f,scale=v,phase='training',stress=False,symbol=a,
                 metrics={'factor_activity':{'active_signal_minutes':0}})
            for f in r.FAMILIES for v in r.SCALES for a in r.SYMBOLS]


def test_training_selection_ignores_later_rows_and_undefined_not_positive(monkeypatch):
    monkeypatch.setattr(r,'aggregate',lambda rows:(None,{'sharpe':None}))
    rows=training_rows();rows += [dict(family=f,scale=.8,phase='holdout',stress=False,symbol=a,metrics={}) for f in r.FAMILIES for a in r.SYMBOLS]
    out=r.choose_training(rows)
    assert set(out['chosen'].values())=={1.}
    assert all(out['all_training_sharpes_undefined'].values())
    rows[0]['symbol']=rows[1]['symbol']
    with pytest.raises(ValueError):r.choose_training(rows)


def test_native_pepe_pending_flip_endpoint_funding_no_fabricated_close():
    spec=Instrument('binance:perpetual:1000PEPEUSDT','binance','1000PEPEUSDT','perpetual',
                    base='1000PEPE',tick_size=.000001,lot_size=1,min_quantity=1,min_notional=0,
                    maker_bps=0,taker_bps=0)
    times=pd.date_range(T,periods=4,freq='min')
    bars=pd.DataFrame({'timestamp':times,'instrument_id':spec.id,'duration_seconds':60,
                       'open':.01,'high':.01,'low':.01,'close':.01,'mark_open':.01,'mark_price':.01,'volume':1e9})
    stop=T+pd.Timedelta(minutes=4)
    signals=pd.Series([1,-1],index=pd.DatetimeIndex([T+pd.Timedelta(minutes=1),T+pd.Timedelta(minutes=3)]))
    funding=pd.DataFrame({'timestamp':[stop],'instrument_id':[spec.id],'funding_rate':[.001],'mark_price':[.01]})
    result=Engine([spec],SimulationConfig(initial_balances={'binance':1000},leverage=1,
                  max_gross_leverage=1,max_position_pct=.5,slippage_bps=0,participation=1,
                  execution_delay_bars=1)).run(bars,r.FixedDirectional(signals,stop),funding)
    assert result.fills.quantity.tolist()==[25000.]
    assert result.positions.quantity.iloc[0]==25000.
    assert result.funding.funding_payment.sum()==pytest.approx(-.25)
    assert result.equity.equity.iloc[-1]==pytest.approx(999.75)
    assert verify_ledgers(result)


def cached_trial(tmp_path,monkeypatch):
    family='funding_crowding_fade';symbol='PEPEUSDT'
    destination=tmp_path/'training'/family/'1'/'base'/symbol
    destination.mkdir(parents=True)
    identity={'modules':{'model.py':'sha'},'runtime':{'python':'synthetic'}}
    fingerprints={**identity,'data':{}}
    monkeypatch.setattr(r,'source_identity',lambda:identity)
    monkeypatch.setattr(r,'used_paths',lambda *a:[])
    (tmp_path/'source_lock.json').write_text(json.dumps({**identity,'data':{}}))
    metadata={'parameters':{'fingerprints':fingerprints,'family':family,'symbol':symbol,'scale':1.,'phase':'training',
                            'stress':False,'requested_start':str(T),'requested_end_exclusive':str(r.TRAIN_END)}}
    (destination/'metadata.json').write_text(json.dumps(metadata))
    (destination/'metrics.json').write_text(json.dumps({'total_return':999.}))
    args=(family,symbol,1.,'training',str(T),str(r.TRAIN_END),False,'unused','unused','unused',str(tmp_path))
    return args,destination,metadata


@pytest.mark.parametrize('field,value',[('symbol','BTCUSDT'),('family','taker_flow_drift'),('scale',.8),('phase','holdout'),
                                        ('stress',True),('requested_start',str(T+pd.Timedelta(days=1))),
                                        ('requested_end_exclusive',str(r.END))])
def test_cached_wrong_trial_cannot_be_relabelled(tmp_path,monkeypatch,field,value):
    args,destination,metadata=cached_trial(tmp_path,monkeypatch)
    metadata['parameters'][field]=value
    (destination/'metadata.json').write_text(json.dumps(metadata))
    seal_synthetic_cache(destination)  # Correctly sealed but economically wrong trial must still reject.
    with pytest.raises(RuntimeError):r.job(args)


def test_worker_rejects_changed_source_before_cache_return(tmp_path,monkeypatch):
    args,destination,metadata=cached_trial(tmp_path,monkeypatch)
    monkeypatch.setattr(r,'source_identity',lambda:{'modules':{'model.py':'different'}})
    with pytest.raises(RuntimeError,match='Worker code'):r.job(args)


def test_dispatch_exact400_distinct_trials_selects_before_later_phases(tmp_path,monkeypatch):
    from collections import Counter
    class Pool:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
    captured=[]
    monkeypatch.setattr(r,'ProcessPoolExecutor',Pool)
    monkeypatch.setattr(r,'freeze',lambda *args:{})
    def execute(pool,jobs,rows,root):
        for task in jobs:
            f,a,v,p,begin,stop,stress,*rest=task
            captured.append((f,a,v,p,begin,stop,stress))
            rows.append({'family':f,'symbol':a,'scale':v,'phase':p,'stress':stress})
    monkeypatch.setattr(r,'execute_jobs',execute)
    def choose(rows):
        assert len(rows)==120 and all(x['phase']=='training' for x in rows)
        return {'chosen':{f:1. for f in r.FAMILIES}}
    monkeypatch.setattr(r,'choose_training',choose)
    monkeypatch.setattr(r,'summarize',lambda rows,*args:len(rows)==400 or pytest.fail('Incomplete trials'))
    monkeypatch.setattr(r,'report',lambda *args:'synthetic-report')
    monkeypatch.setattr(r.sys,'argv',['runner','--out',str(tmp_path)])
    r.main()
    assert len(captured)==len(set(captured))==400
    counts=Counter('stress' if x[-1] else x[3] for x in captured)
    assert counts=={'training':120,'validation1':40,'validation2':40,'validation3':40,'holdout':120,'stress':40}
    for f,a,v,phase,begin,stop,stress in captured:
        expected_start={'training':r.START,'validation1':r.TRAIN_END,'validation2':r.TRAIN_END+pd.DateOffset(months=1),
                        'validation3':r.TRAIN_END+pd.DateOffset(months=2),'holdout':r.EVALUATION_START}[phase]
        assert pd.Timestamp(begin)==expected_start
        assert pd.Timestamp(stop)<=r.END


def test_summary_deduplicates_macro_events_and_keeps_breadth_drawdown_reserve_hurdles(tmp_path,monkeypatch):
    rows=[]
    for family in r.FAMILIES:
        for phase in ['validation1','validation2','validation3','holdout']:
            variants=[(.8,False),(1.,False),(1.2,False),(1.,True)] if phase=='holdout' else [(1.,False)]
            for scale,stress in variants:
                for i,symbol in enumerate(r.SYMBOLS):
                    rows.append({'family':family,'scale':scale,'stress':stress,'phase':phase,'symbol':symbol,
                                 'metrics':{'total_return':.1 if i<4 else -.01,'fill_count':1,'liquidation_event_count':0,
                                            'factor_activity':{'phase_cpi_release_times':['event-A','event-B'],
                                                               'phase_directional_cpi_release_times':['event-A']}}})
    frame=pd.DataFrame({'timestamp':[r.EVALUATION_START,r.END],'equity':[100000.,110000.]})
    score={'total_return':.1,'return_after_indicative_exit_reserve':-.01,'sharpe':1.,'max_drawdown':.21}
    monkeypatch.setattr(r,'aggregate',lambda group:(frame.copy(),score.copy()))
    monkeypatch.setattr(r,'anchored_months',lambda frame:[.03,.03,.03])
    monkeypatch.setattr(r,'bootstrap',lambda frame:{})
    (tmp_path/'source_lock.json').write_text(json.dumps({'input_coverage':{}}))
    result=r.summarize(rows,{'chosen':{f:1. for f in r.FAMILIES}},tmp_path,{})
    assert result['pass_count']==0
    for family in result['families']:
        assert family['evaluation_unique_cpi_release_count']==2  # Never 16.
        assert family['evaluation_unique_directional_cpi_release_count']==1
        assert not family['checks']['broad_symbol_success']
        assert not family['checks']['minute_drawdown_within20pct']
        assert not family['checks']['evaluation_positive_after_indicative_reserve']


def test_worker_data_change_rejects_before_cache_return(tmp_path,monkeypatch):
    args,destination,metadata=cached_trial(tmp_path,monkeypatch)
    source=tmp_path/'data.parquet';source.write_bytes(b'changed')
    monkeypatch.setattr(r,'used_paths',lambda *a:[source])
    lock=json.loads((tmp_path/'source_lock.json').read_text());lock['data']={str(source.resolve()):'old-sha'}
    (tmp_path/'source_lock.json').write_text(json.dumps(lock))
    with pytest.raises(RuntimeError,match='Worker data'):r.job(args)


def test_job_native_cash_endpoint_and_warmup_cutoffs_before_signalconstruction(tmp_path,monkeypatch):
    stop=T+pd.Timedelta(minutes=3);begin=T+pd.Timedelta(minutes=1)
    spec=Instrument('binance:perpetual:1000PEPEUSDT','binance','1000PEPEUSDT','perpetual',base='1000PEPE')
    from dataclasses import asdict
    mapping={'spot_symbol':'PEPEUSDT','perpetual_instrument_id':spec.id,'spot_base_units_per_perpetual_quantity_unit':1000}
    cache=tmp_path/'cache';cache.mkdir()
    (cache/'cross_mapping.json').write_text(json.dumps({'mapping':[mapping]}))
    (cache/'instruments.json').write_text(json.dumps([asdict(spec)]))
    (tmp_path/'source_lock.json').write_text(json.dumps({'modules':{},'data':{}}))
    monkeypatch.setattr(r,'source_identity',lambda:{'modules':{}})
    monkeypatch.setattr(r,'used_paths',lambda *a:[])
    b=pd.DataFrame({'timestamp':pd.date_range(T,periods=5,freq='min'),'duration_seconds':60,'instrument_id':spec.id})
    f=pd.DataFrame({'timestamp':pd.DatetimeIndex([T,begin,stop,stop+pd.Timedelta(minutes=1)]),
                    'instrument_id':spec.id,'funding_rate':.001})
    monkeypatch.setattr(r.pd,'read_parquet',lambda path,*a,**kw:f.copy() if path.name=='funding.parquet' else b.copy())
    def builder(all_bars,family,scale,**kw):
        assert all_bars.timestamp.tolist()==[T,begin,begin+pd.Timedelta(minutes=1)]
        assert kw['funding'].timestamp.tolist()==[T,begin]  # Endpoint cash isn't an available predictor.
        return pd.Series(0,index=pd.DatetimeIndex(all_bars.timestamp+pd.Timedelta(minutes=1)))
    monkeypatch.setattr(r,'build_signals',builder)
    class Captured(Exception):pass
    class MockEngine:
        def __init__(self,specs,config):
            assert specs[0].base=='1000PEPE'
            assert config.execution_delay_bars==1 and config.participation==.025
            assert config.slippage_bps==16 and specs[0].taker_bps==10
        def run(self,bars,strategy,funding):
            assert bars.timestamp.tolist()==[begin,begin+pd.Timedelta(minutes=1)]
            assert funding.timestamp.tolist()==[begin,stop]
            raise Captured
    monkeypatch.setattr(r,'Engine',MockEngine)
    args=('funding_crowding_fade','PEPEUSDT',1.,'holdout',str(begin),str(stop),True,str(cache),'unused','unused',str(tmp_path))
    with pytest.raises(Captured):r.job(args)


def seal_synthetic_cache(destination):
    for name in r.OUTPUT_FILES:
        path=destination/name
        if not path.exists():path.write_bytes(b'synthetic-result-file')
    r.seal_outputs(destination)


def test_cached_correct_trial_roundtrip_and_output_tamper_rejects(tmp_path,monkeypatch):
    args,destination,metadata=cached_trial(tmp_path,monkeypatch)
    seal_synthetic_cache(destination)
    out=r.job(args)
    assert out['symbol']=='PEPEUSDT' and out['metrics']['total_return']==999.
    # Source identity is unchanged; execution result corruption is independent.
    (destination/'metrics.json').write_text(json.dumps({'total_return':1000000.}))
    with pytest.raises(RuntimeError,match='output hash mismatch'):r.job(args)


@pytest.mark.parametrize('defect',['unsealed','missing_file','missing_hash','equity_tamper'])
def test_cache_output_integrity_fail_closed(tmp_path,monkeypatch,defect):
    args,destination,metadata=cached_trial(tmp_path,monkeypatch)
    if defect!='unsealed':seal_synthetic_cache(destination)
    if defect=='missing_file':(destination/'funding.parquet').unlink()
    elif defect=='missing_hash':
        seal=json.loads((destination/'execution_outputs.json').read_text());seal['sha256'].pop('funding.parquet')
        (destination/'execution_outputs.json').write_text(json.dumps(seal))
    elif defect=='equity_tamper':(destination/'equity.parquet').write_bytes(b'corrupted')
    with pytest.raises(RuntimeError):r.job(args)
