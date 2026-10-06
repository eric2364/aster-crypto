"""Independent financial replay adversaries; synthetic Engine fixtures only."""
import copy
import json
from dataclasses import asdict,replace
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from audit import verify_cross_venue_outputs as a
from aster.backtest.engine import Engine
from examples.cross_venue.strategy import CrossVenueCarry
from examples.cross_venue.run import SnapshotObserver
from test_cross_venue_execution import specs,features,bars,START


def fixture(delay=0,active='PEPEUSDT',partial=False,shock=False):
    minutes=14
    catalog=sorted(specs(),key=lambda x:x.id)
    cfg=a.configuration(bool(delay))
    from aster.backtest.models import SimulationConfig
    catalog=[replace(x,maker_bps=(10 if x.exchange=='binance' else 12) if delay else (5 if x.exchange=='binance' else 6),taker_bps=(10 if x.exchange=='binance' else 12) if delay else (5 if x.exchange=='binance' else 6)) for x in catalog]
    raw=bars(minutes,volume={(m,'bybit','1000PEPEUSDT'):0 if m>4 else 1000 for m in range(minutes)} if partial else None)
    raw['end']=raw.timestamp+pd.Timedelta(minutes=1)
    if shock:
        native='1000PEPEUSDT' if active=='PEPEUSDT' else active
        mask=raw.symbol.eq(native) if 'symbol' in raw else raw.instrument_id.eq(a.iid('bybit',active))
        mask &=raw.timestamp.ge(START+pd.Timedelta(minutes=9))
        for key in ('open','high','low','close','mark_open','mark_price'):raw.loc[mask,key]*=100
    fund=pd.DataFrame([dict(timestamp=START+pd.Timedelta(minutes=5),instrument_id=a.iid('bybit',active),funding_rate=.001,mark_price=.01 if active=='PEPEUSDT' else 100.),dict(timestamp=START+pd.Timedelta(minutes=7,milliseconds=500),instrument_id=a.iid('bybit',active),funding_rate=.001,mark_price=.01 if active=='PEPEUSDT' else 100.)])
    strategy=CrossVenueCarry(features(minutes,active=active),START+pd.Timedelta(days=30))
    engine=Engine(catalog,SimulationConfig(**cfg));observer=SnapshotObserver(engine.portfolio);engine.portfolio.snapshot=observer
    result=engine.run(raw,strategy,funding=fund)
    tables={n:getattr(result,n).copy(deep=True) for n in a.LEDGERS};exposure=pd.DataFrame(observer.rows)
    source={s.id:raw.loc[raw.instrument_id.eq(s.id)].copy().reset_index(drop=True) for s in catalog}
    return tables,exposure,source,fund,[asdict(s) for s in catalog],cfg,strategy


def run(data):
    tables,x,source,fund,spec,cfg,_=data
    return a.reconstruct(tables,x,source,fund,spec,cfg,START,START+pd.Timedelta(minutes=14))


@pytest.mark.parametrize('delay',[0,1])
def test_native_two_wallet_funding_at_ms_clock_and_no_principal(delay):
    data=fixture(delay=delay);state,preopen=run(data)
    q=125000
    assert abs(state.q[a.iid('bybit','PEPEUSDT')])==q
    assert state.leg_fund[a.iid('bybit','PEPEUSDT')]==pytest.approx(1.25)
    assert len(data[0]['funding'])==1  # same-clock admission does not earn already-settled funding.
    assert state.cash['bybit']==pytest.approx(50000-data[0]['fills'].loc[data[0]['fills'].exchange.eq('bybit'),'fee'].sum()+1.25)
    assert len(data[1].columns)==127
    assert preopen[START+pd.Timedelta(minutes=5)][a.iid('bybit','PEPEUSDT')]==0


@pytest.mark.parametrize('case',['quantity','fee','funding_sign','funding_ms','reference','adverse','capacity','reduce_only','activation','wallet','entry_reserve','mark','margin'])
def test_financial_replay_rejects_coherently_exported_bad_evidence(case):
    data=fixture();tables,x,source,fund,spec,cfg,strategy=data
    if case=='quantity':tables['fills'].loc[0,'quantity']*=1000
    elif case=='fee':tables['fills'].loc[0,'fee']=0
    elif case=='funding_sign':tables['funding'].loc[0,'funding_payment']*=-1
    elif case=='funding_ms':tables['funding'].loc[0,'timestamp']+=pd.Timedelta(milliseconds=1)
    elif case=='reference':tables['fills'].loc[0,'reference_price']*=1.01
    elif case=='adverse':tables['fills'].loc[0,'price']*=1.01
    elif case=='capacity':
        source[tables['fills'].iloc[0].instrument_id].loc[4,'volume']=0
    elif case=='reduce_only':tables['events'].loc[tables['events'].type.eq('ORDER_SUBMITTED'),'reduce_only']=True
    elif case=='activation':tables['events'].loc[tables['events'].type.eq('ORDER_SUBMITTED'),'active_at']+=pd.Timedelta(days=1)
    elif case=='wallet':tables['equity'].loc[8,'bybit_cash']+=100
    elif case=='entry_reserve':x.loc[8,'entry_collateral_field_bybit_PEPEUSDT']+=100
    elif case=='mark':x.loc[8,'mark_bybit_PEPEUSDT']+=.000001
    else:x.loc[8,'bybit_margin_used']+=100
    with pytest.raises(AssertionError):run(data)


def test_partial_zero_capacity_cleanup_and_closed_trade_cost_allocations():
    data=fixture(partial=True);state,_=run(data)
    assert data[0]['trades'].shape[0]>0
    legs,pairs=a.contributions(state)
    assert len(legs)==16 and len(pairs)==8
    assert sum(r['net_pnl'] for r in legs)==pytest.approx(data[0]['equity'].equity.iloc[-1]-100000)


def test_true_local_liquidation_despite_other_wallet_positive():
    data=fixture(active='DOGEUSDT',shock=True)
    state,_=run(data)
    assert state.liqfees>0 and data[0]['events'].type.eq('LIQUIDATION').any()


def test_trade_or_final_position_forgery_rejected():
    data=fixture(partial=True)
    assert len(data[0]['trades'])
    data[0]['trades'].loc[0,'net_pnl']+=1
    with pytest.raises(AssertionError):run(data)
    data=fixture();data[0]['positions'].loc[0,'funding_pnl']+=1
    with pytest.raises(AssertionError):run(data)


def test_exit_reserve_diagnostic_does_not_debit_cash_twice():
    data=fixture();state,_=run(data);tables=data[0]
    score=a.phase_statistics(tables['equity'],tables['trades'],tables['fills'],tables['positions'],state,data[6].matched_entries)
    assert score['indicative_exit_reserve_total']>0
    assert score['return_after_indicative_exit_reserve']<score['total_return']
    assert state.cash['bybit']==pytest.approx(tables['equity'].iloc[-1].bybit_cash)


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_bootstrap_endpoint_and_26_comparison_tails(unit):
    daily=np.array([.002,-.001,.004,-.003,.001,.002,-.001,.003,-.004,.002,.003,-.001,.002,-.002,.001,.002,-.001,.003,.002])
    frame=pd.DataFrame({'timestamp':pd.date_range(a.EVAL,periods=20,freq='D').as_unit(unit),'equity':100000*np.r_[1,np.cumprod(1+daily)]});old=frame.copy()
    result=a.interval(frame);values=np.r_[daily[:-2],(1+daily[-2])*(1+daily[-1])-1]
    n=len(values);rng=np.random.default_rng(42);starts=rng.integers(0,n,(10000,(n+6)//7));indices=((starts[:,:,None]+np.arange(7))%n).reshape(10000,-1)[:,:n]
    totals=np.prod(1+values[indices],axis=1)-1
    assert result['return_interval_bonferroni26']==pytest.approx(np.quantile(totals,[.05/52,1-.05/52]),abs=1e-12)
    pd.testing.assert_frame_equal(frame,old)


def test_no_frozen_economic_module_imports():
    source=Path(a.__file__).read_text()
    assert 'from examples.' not in source and 'from aster.' not in source


def test_sameclock_cancellation_before_fill_event_is_not_eligible():
    data=fixture();events=data[0]['events'];fills=data[0]['fills'];fill=fills.iloc[0]
    matched=events.loc[events.type.eq('ORDER_FILLED')&events.order_id.eq(fill.order_id)].index[0]
    cancel=dict(events.loc[matched]);cancel.update(type='ORDER_CANCELLED',reason='strategy')
    data[0]['events']=pd.concat([events.iloc[:matched],pd.DataFrame([cancel]),events.iloc[matched:]],ignore_index=True)
    with pytest.raises(AssertionError,match='cancellation'):run(data)


@pytest.mark.parametrize('partial',[False,True])
def test_independent_all_descriptive_metrics_match_synthetic_export(partial):
    from aster.analytics import metrics
    data=fixture(partial=partial);tables=data[0]
    a.compare(a.reference_metrics(tables['equity'],tables['trades'],tables['fills']),metrics(tables['equity'],tables['trades'],tables['fills']))


@pytest.fixture
def exported(tmp_path,monkeypatch):
    """Exercise all file formats and phase seals using only a 14-minute synthetic market."""
    from examples.cross_venue import run as r
    from aster.backtest.models import Instrument
    out=tmp_path/'out';out.mkdir();binance=tmp_path/'binance';bybit=tmp_path/'bybit';end=START+pd.Timedelta(minutes=14)
    data=fixture();_,_,source,fund,spec,cfg,strategy=data
    for venue,root in [('binance',binance),('bybit',bybit)]:
        root.mkdir();(root/'instruments.json').write_text(json.dumps([s for s in spec if s['exchange']==venue]))
        for symbol in a.SYMBOLS:
            path=root/symbol;path.mkdir();identity=a.iid(venue,symbol)
            source[identity].to_parquet(path/'bars.parquet',index=False)
            fund.loc[fund.instrument_id.eq(identity)].to_parquet(path/'funding.parquet',index=False)
    hashes={str(p.relative_to(a.REPO)):a.sha(p) for p in (a.REPO/'aster').rglob('*.py')}
    runtime={'python':__import__('sys').version,**{p:a.importlib.metadata.version(p) for p in ('numpy','pandas','pyarrow','statsmodels','scipy','plotly')}}
    lock={'sources':hashes,'runtime':runtime}
    (out/'source_lock.json').write_text(json.dumps(lock));features(14,active='PEPEUSDT').to_parquet(out/'features.parquet');(out/'feature_receipt.json').write_text('{}')
    target=out/'executed_source/aster/__init__.py';target.parent.mkdir(parents=True);target.write_bytes((a.REPO/'aster/__init__.py').read_bytes())
    phase=('synthetic',START,end,False,'primary')
    monkeypatch.setattr(r,'PHASES',[phase]);monkeypatch.setattr(r,'guard',lambda *args:lock)
    monkeypatch.setattr(r,'verified_features',lambda out:features(14,active='PEPEUSDT'))
    monkeypatch.setattr(r,'catalog',lambda *args:[Instrument(**s) for s in spec])
    monkeypatch.setattr(r,'phase_inputs',lambda *args:(pd.concat([source[a.iid(v,s)] for v in a.VENUES for s in a.SYMBOLS],ignore_index=True),fund))
    # Synthetic export retains a long strategy horizon so its 14-minute tape can exercise entries.
    monkeypatch.setattr(r,'CrossVenueCarry',lambda f,stop:CrossVenueCarry(f,stop+pd.Timedelta(days=30)))
    r.run_phase(binance,bybit,out,phase)
    monkeypatch.setattr(a,'START',START);monkeypatch.setattr(a,'END',end)
    return binance,bybit,out,phase,lock


def test_full_exported_phase_independent_verification(exported):
    record,score,*_=a.verify_phase(*exported)
    assert len(record['outputs_sha256'])==25 and record['trajectory_reconstruction_passed']
    assert score['matched_entry_count']==1


@pytest.mark.parametrize('field',['stress','valuation','strategy','core','seal','funding_hash'])
def test_resealed_phase_metadata_or_identity_rejected(exported,field):
    binance,bybit,out,phase,lock=exported;path=out/'trials'/phase[0];metadata=a.read(path/'metadata.json')
    if field=='stress':metadata['parameters']['stress']=True
    elif field=='valuation':metadata['parameters']['valuation']='alternative'
    elif field=='strategy':metadata['strategy']='Invented'
    elif field=='core':metadata['source_sha256']={}
    elif field=='funding_hash':metadata['funding_sha256']='0'*64
    else:
        frame=pd.read_parquet(path/'exposure.parquet');frame.loc[8,'cash']+=1;frame.to_parquet(path/'exposure.parquet',index=False)
    if field!='seal':
        (path/'metadata.json').write_text(json.dumps(metadata));completion=a.read(path/'completion.json');completion['outputs_sha256']['metadata.json']=a.sha(path/'metadata.json');(path/'completion.json').write_text(json.dumps(completion))
    with pytest.raises(AssertionError):a.verify_phase(*exported)


def summary_fixture(tmp_path):
    clock=pd.date_range(a.EVAL,a.END,freq='D');frame=pd.DataFrame({'timestamp':clock,'equity':100000*1.001**np.arange(len(clock))})
    path=tmp_path/'trials/evaluation';path.mkdir(parents=True);frame.to_parquet(path/'equity.parquet');(tmp_path/'source_lock.json').write_text('{}');(tmp_path/'features.parquet').write_bytes(b'no historical features')
    records={}
    for phase in a.PHASES:
        score=dict(total_return=.1,return_after_indicative_exit_reserve=.09,sharpe=.6,max_drawdown=.1,liquidation_event_count=0,matched_pairs=['BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT'])
        records[phase[0]]=({},score,frame,[],[])
    return records


def test_independent_summary_economic_breadth_and_strict_positive_gates(tmp_path):
    records=summary_fixture(tmp_path);summary=a.rebuild_summary(tmp_path,records)
    assert summary['passes_hurdles'] and len(summary['gates'])==15
    records['evaluation_stress'][1]['total_return']=0
    records['evaluation'][1]['matched_pairs']=['BTCUSDT','ETHUSDT','DOGEUSDT','SOLUSDT']
    records['validation2'][1]['liquidation_event_count']=1
    summary=a.rebuild_summary(tmp_path,records)
    assert not summary['passes_hurdles']
    assert {'positive_evaluation_stress','four_matched_pairs_including_both_doge_and_pepe','no_liquidation_all_seven_runs'}<=set(summary['failed_gates'])


def test_committed_input_packet_rejects_resealed_source_set(tmp_path,monkeypatch):
    lock={'sources':{'reviewed':'x'},'inputs':{'actual':'y'}}
    original=json.dumps(lock).encode();verification=b'{}';(tmp_path/'source_lock.json').write_bytes(original);(tmp_path/'input_verification.json').write_bytes(verification)
    prereg=dict(source_commit=a.ANCHOR,source_lock_sha256=a.sha(tmp_path/'source_lock.json'),input_verification_sha256=a.sha(tmp_path/'input_verification.json'),historical_features_exist=False,trial_directory_exists=False,source_files=1,input_files=1)
    committed={'source_lock.json':original,'input_verification.json':verification,'preregistration.json':json.dumps(prereg).encode()}
    monkeypatch.setattr(a,'committed_file',lambda commit,path:committed[Path(path).name])
    a.verify_input_anchor(tmp_path)
    lock['sources']={};(tmp_path/'source_lock.json').write_text(json.dumps(lock))
    with pytest.raises(AssertionError,match='committed pre-outcome'):a.verify_input_anchor(tmp_path)


def test_auditor_source_change_during_reconstruction_rejected(tmp_path,monkeypatch):
    trials=tmp_path/'trials';trials.mkdir()
    for phase in a.PHASES:(trials/phase[0]).mkdir()
    (tmp_path/'summary.json').write_text('{}')
    monkeypatch.setattr(a,'packet_guard',lambda out:{'sources':{},'inputs':{}})
    monkeypatch.setattr(a,'verify_phase',lambda *args:({},None,None,None,None))
    monkeypatch.setattr(a,'rebuild_summary',lambda *args:{})
    called=[]
    def changing(path):
        if str(path)==str(a.__file__):called.append(path);return 'original' if len(called)==1 else 'changed'
        return 'same'
    monkeypatch.setattr(a,'sha',changing)
    with pytest.raises(AssertionError,match='Auditor source changed'):a.verify('binance','bybit',tmp_path)


def test_multiple_instruments_share_one_minute_or_ms_settlement_clock():
    data=fixture();tables,x,source,fund,spec,cfg,strategy=data
    extra=fund.copy();extra['instrument_id']=a.iid('binance','BTCUSDT');extra['mark_price']=100.
    source_fund=pd.concat([fund,extra],ignore_index=True)
    state,_=a.reconstruct(tables,x,source,source_fund,spec,cfg,START,START+pd.Timedelta(minutes=14))
    assert state.leg_fund[a.iid('binance','BTCUSDT')]==0
    assert state.leg_fund[a.iid('bybit','PEPEUSDT')]==pytest.approx(1.25)
