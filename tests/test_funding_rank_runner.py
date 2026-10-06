"""Synthetic runner provenance, accounting observer, endpoint and gate adversaries."""
from dataclasses import asdict
from types import SimpleNamespace
import copy
import json
from pathlib import Path
import pandas as pd
import pytest
from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, Order
from examples.funding_rank import run as r


def specs():
    return [Instrument(id=r.native_id('binance',s),exchange='binance',market_type='perpetual',
        symbol='1000PEPEUSDT' if s=='PEPEUSDT' else s,base='1000PEPE' if s=='PEPEUSDT' else s[:-4],
        quote='USDT',lot_size=.001,min_quantity=.001,min_notional=1,taker_bps=5) for s in r.SYMBOLS]


@pytest.fixture
def frozen(tmp_path,monkeypatch):
    repo=tmp_path/'repo';cache=tmp_path/'cache';out=tmp_path/'out'
    (repo/'aster').mkdir(parents=True);(repo/'aster/core.py').write_text('# synthetic source\n')
    for folder,names in [('examples/funding_rank',('run.py','signals.py','strategy.py','proposed_protocol.md')),
        ('examples/cross_venue',('signals.py',)),('examples/minute_research',('download.py','downloadcarry.py'))]:
        for n in names:
            path=repo/folder/n;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# synthetic source\n')
    cache.mkdir();r.dump(cache/'instruments.json',[asdict(s) for s in specs()])
    for n in ('cross_mapping.json','instrument_source_manifest.json','exchange_info_current.json'):r.dump(cache/n,{})
    for s in r.SYMBOLS:
        folder=cache/s;folder.mkdir()
        (folder/'bars.parquet').write_bytes(b'untouched synthetic bars')
        (folder/'funding.parquet').write_bytes(b'untouched synthetic funding')
        raw=folder/'raw.json';raw.write_bytes(b'raw delivery outside-year rows preserved')
        r.dump(folder/'source_manifest.json',{'archives':[],'funding_pages':[{'cache_file':str(raw)}]})
    monkeypatch.setattr(r,'REPO',repo);monkeypatch.setattr(r,'cached_path',lambda p:Path(p))
    monkeypatch.setattr(r,'verify',lambda cache,s,ins:{'spot_symbol':s,'minute_grid_exact':True})
    r.freeze(cache,out)
    return repo,cache,out


def test_freeze_archives_transitive_source_and_raw_inputs(frozen):
    repo,cache,out=frozen;lock=r.guard(cache,out)
    assert lock['candidate_count_cumulative']==27
    assert 'examples/minute_research/download.py' in lock['sources']
    assert 'examples/cross_venue/signals.py' in lock['sources']
    assert len([p for p in lock['inputs'] if p.endswith('raw.json')])==8
    for name,sha in lock['sources'].items():assert r.digest(out/'executed_source'/name)==sha


@pytest.mark.parametrize('target',['source','raw','normalized','archive','receipt'])
def test_frozen_drift_rejected(frozen,target):
    repo,cache,out=frozen
    path={'source':repo/'examples/funding_rank/signals.py','raw':cache/r.SYMBOLS[0]/'raw.json',
        'normalized':cache/r.SYMBOLS[0]/'bars.parquet','archive':out/'executed_source/aster/core.py',
        'receipt':out/'input_verification.json'}[target]
    path.write_bytes(path.read_bytes()+b' ')
    if target=='receipt':
        receipt=r.read(path);receipt[0]['minute_grid_exact']=False;r.dump(path,receipt)
    with pytest.raises(RuntimeError):r.guard(cache,out)


def test_prefreeze_blocks_builder(tmp_path,monkeypatch):
    from examples.funding_rank import signals
    calls=[];monkeypatch.setattr(signals,'build_features',lambda *args:calls.append(args))
    with pytest.raises(RuntimeError,match='Freeze BEFORE'):r.generate_features(tmp_path,tmp_path/'out')
    assert calls==[]


def test_refuse_nonempty_unsealed_directory(frozen,tmp_path):
    _,cache,_=frozen;out=tmp_path/'partial';out.mkdir();(out/'old.json').write_text('{}')
    with pytest.raises(RuntimeError,match='nonempty'):r.freeze(cache,out)


def write_features(out,monkeypatch):
    from examples.funding_rank.signals import ASSUMPTIONS
    start=pd.Timestamp('2026-04-05',tz='UTC');end=start+pd.Timedelta(minutes=6)
    monkeypatch.setattr(r,'START',start);monkeypatch.setattr(r,'END',end)
    grid=pd.date_range(start+pd.Timedelta(minutes=2),end,freq='min',inclusive='left')
    daily=(grid.hour==0)&(grid.minute==5)
    frame=pd.DataFrame(index=grid)
    for s in r.SYMBOLS:
        frame[f'price_{s}']=100.
        frame[f'yield_{s}']=float('nan');frame.loc[daily,f'yield_{s}']=.001
        frame[f'valid_{s}']=daily
    frame.attrs=copy.deepcopy(ASSUMPTIONS)
    frame.to_parquet(out/'features.parquet');r.dump(out/'feature_receipt.json',{
        'source_lock_sha256':r.digest(out/'source_lock.json'),'features_sha256':r.digest(out/'features.parquet'),
        'rows':len(frame),'columns':list(frame),'availability_assumptions':frame.attrs})
    return frame


def test_features_hash_caller_and_incomplete_receipt_guards(frozen,monkeypatch):
    _,_,out=frozen;frame=write_features(out,monkeypatch);r.verified_features(out,frame)
    wrong=frame.copy();wrong.iloc[0,0]=999.
    with pytest.raises(AssertionError):r.verified_features(out,wrong)
    (out/'feature_receipt.json').unlink()
    with pytest.raises(RuntimeError,match='Missing/partial'):r.verified_features(out)


def test_resealed_features_wrong_grid_rejected(frozen,monkeypatch):
    _,_,out=frozen;frame=write_features(out,monkeypatch);frame.index=frame.index+pd.Timedelta(seconds=1)
    frame.to_parquet(out/'features.parquet');receipt=r.read(out/'feature_receipt.json')
    receipt['features_sha256']=r.digest(out/'features.parquet');r.dump(out/'feature_receipt.json',receipt)
    with pytest.raises(RuntimeError,match='grid'):r.verified_features(out)


@pytest.mark.parametrize('kind',['attrs','string_valid','integer_valid','nonfinite_price','zero_price','offdaily','valid_missing_yield','invalid_finite_yield'])
def test_resealed_semantically_invalid_features_rejected(frozen,monkeypatch,kind):
    _,_,out=frozen;frame=write_features(out,monkeypatch);first=frame.index[0];decision=frame.index[-1]
    if kind=='attrs':frame.attrs['unreviewed_availability']='immediate'
    elif kind=='string_valid':frame['valid_BTCUSDT']=frame.valid_BTCUSDT.astype(str)
    elif kind=='integer_valid':frame['valid_BTCUSDT']=frame.valid_BTCUSDT.astype(int)
    elif kind=='nonfinite_price':frame.loc[first,'price_BTCUSDT']=float('inf')
    elif kind=='zero_price':frame.loc[first,'price_BTCUSDT']=0.
    elif kind=='offdaily':frame.loc[first,'yield_BTCUSDT']=.001;frame.loc[first,'valid_BTCUSDT']=True
    elif kind=='valid_missing_yield':frame.loc[decision,'yield_BTCUSDT']=float('nan')
    else:frame.loc[decision,'valid_BTCUSDT']=False
    frame.to_parquet(out/'features.parquet');receipt=r.read(out/'feature_receipt.json')
    receipt.update(features_sha256=r.digest(out/'features.parquet'),availability_assumptions=frame.attrs)
    r.dump(out/'feature_receipt.json',receipt)
    with pytest.raises(RuntimeError):r.verified_features(out)


def test_fixed_native_catalog_and_config(tmp_path):
    r.dump(tmp_path/'instruments.json',[asdict(s) for s in specs()])
    assert r.catalog(tmp_path)[3].base=='1000PEPE'
    assert all(s.taker_bps==10 for s in r.catalog(tmp_path,True))
    for stress in (False,True):
        cfg=r.config(stress)
        assert cfg.initial_balances=={'binance':100000.} and cfg.margin_mode=='cross' and cfg.leverage==1
        assert cfg.slippage_bps==(16 if stress else 8) and cfg.execution_delay_bars==int(stress)
    wrong=[asdict(s) for s in specs()];wrong[3]['base']='PEPE';r.dump(tmp_path/'instruments.json',wrong)
    with pytest.raises(RuntimeError,match='units'):r.catalog(tmp_path)


def test_actual_observer_calls_original_once_and_freezes_pre_cancel_orders():
    engine=Engine(specs(),r.config(False));p=engine.portfolio;t=pd.Timestamp('2026-04-05',tz='UTC')
    for s in specs():p.marks[s.id]=100.
    iid=specs()[0].id
    p.apply_fill(iid,1,2,100,t,'taker','market')
    p.settle_funding({'timestamp':t,'instrument_id':iid,'funding_rate':.001,'mark_price':100})
    calls=[];original=p.snapshot
    def wrapped(time):calls.append(time);return original(time)
    p.snapshot=wrapped;observer=r.SnapshotObserver(engine)
    order=Order(iid,-1,2,reduce_only=True);order.status='accepted';engine.orders[order.id]=order
    result=observer(t)
    assert calls==[t] and observer.rows[-1]['equity']==result['equity']
    assert observer.rows[-1]['binance_cash']==p.cash['binance']
    assert observer.rows[-1]['quantity_BTCUSDT']==2 and observer.rows[-1]['current_mark_initial_margin_BTCUSDT']==200
    assert observer.rows[-1]['maintenance_margin']==p.maintenance_margin('binance')
    order.status='cancelled';engine.orders.clear()
    assert observer.last_orders[0]['status']=='accepted' and observer.rows[-1]['live_order_count']==1


def test_forensic_orders_sets_export(tmp_path):
    order=Order(specs()[0].id,1,1);r.dump(tmp_path/'diagnostic.json',{'transaction':{'orders':{order.id:order}},'blocked':{'z','a'}})
    value=r.read(tmp_path/'diagnostic.json')
    assert value['blocked']==['a','z'] and value['transaction']['orders'][order.id]['quantity']==1


def test_terminal_gate_rejects_sub_epsilon_inventory_and_pre_autocancel_orders():
    row={f'quantity_{s}':0. for s in r.SYMBOLS}
    assert r.terminal_status(row,[])['terminal_flat_resolved']
    row['quantity_PEPEUSDT']=1e-12
    assert r.terminal_status(row,[])['terminal_observed_nonzero_position_count']==1
    assert not r.terminal_status(row,[])['terminal_flat_resolved']
    row['quantity_PEPEUSDT']=0
    assert not r.terminal_status(row,[{'status':'accepted'}])['terminal_flat_resolved']


def completed(generation=1):
    longs=['BTCUSDT','DOGEUSDT'];shorts=['PEPEUSDT','ADAUSDT']
    return {'generation':generation,'proposal':{'longs':longs,'shorts':shorts},
        'targets':{r.native_id('binance',s):1 if s in longs else -1 if s in shorts else 0 for s in r.SYMBOLS}}


def good_scores():
    return {p[0]:{'total_return':.01,'return_after_indicative_exit_reserve':.009,'sharpe':.7,
        'max_drawdown':.1,'liquidation_event_count':0,'terminal_flat_resolved':True} for p in r.PHASES}


def test_fifteen_gates_and_completed_breadth():
    participants,generations=r.basket_participation([completed(1),completed(2)])
    validation,vr,gates=r.gate_results(good_scores(),[.01,-.01,.02],participants,generations)
    assert len(gates)==15 and all(gates.values()) and validation==pytest.approx(1.01**3-1)
    assert vr==pytest.approx(1.009**3-1)
    with pytest.raises(RuntimeError,match='Duplicate'):r.basket_participation([completed(),completed()])
    bad=completed();bad['targets'][r.native_id('binance','PEPEUSDT')]=1
    with pytest.raises(RuntimeError,match='signed'):r.basket_participation([bad])


@pytest.mark.parametrize('kind',['liquidation','terminal','undefined_sharpe','reserve','one_generation','missing_pepe'])
def test_material_gate_failures(kind):
    scores=good_scores();participants={'BTCUSDT','DOGEUSDT','PEPEUSDT','ADAUSDT'};generations=2
    if kind=='liquidation':scores['validation2']['liquidation_event_count']=1
    elif kind=='terminal':scores['validation1']['terminal_flat_resolved']=False
    elif kind=='undefined_sharpe':scores['evaluation']['sharpe']=None
    elif kind=='reserve':scores['evaluation_stress']['return_after_indicative_exit_reserve']=0.
    elif kind=='one_generation':generations=1
    else:participants.remove('PEPEUSDT');participants.add('ETHUSDT')
    assert not all(r.gate_results(scores,[.01,.02,-.01],participants,generations)[2].values())


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_endpoint_bootstrap_all_datetime_units_without_mutation(unit):
    clock=pd.date_range('2026-07-05',periods=12,freq='D',tz='UTC').as_unit(unit)
    frame=pd.DataFrame({'timestamp':clock,'equity':[100000*(1.001**k) for k in range(12)]})
    original=frame.copy(deep=True);daily=r.endpoint_daily(frame)
    interval=r.conditional_interval(frame)
    pd.testing.assert_frame_equal(frame,original)
    assert daily.index.max()<clock[-1] and interval['comparison_count']==27
    assert interval['tails']==[.05/54,1-.05/54]


def sealed_trial(cache,out,phase):
    dest=out/'trials'/phase[0];dest.mkdir(parents=True)
    for name in r.OUTPUTS:(dest/name).write_bytes(b'preserved synthetic output')
    expected=r.parameters(out,phase);lock=r.read(out/'source_lock.json');manifest=r.source_manifest(out)
    r.dump(dest/'metadata.json',{'parameters':expected,'engine':asdict(r.config(phase[3])),
        'instruments':[asdict(s) for s in r.catalog(cache,phase[3])],
        'strategy':r.FundingRankPortfolio.__name__,'strategy_version':str(r.FundingRankPortfolio.version),
        'source_sha256':{n.removeprefix('aster/'):h for n,h in lock['sources'].items() if n.startswith('aster/')},
        'source_manifest':manifest,'start':str(phase[1]),'end':str(phase[2])})
    r.dump(dest/'source_manifest.json',manifest);r.dump(dest/'metrics.json',{'total_return':0})
    r.dump(dest/'completion.json',{'parameters':expected,'outputs_sha256':r.output_files(dest)})
    return dest


@pytest.mark.parametrize('kind',['hash','resealed_phase','resealed_config','resealed_core','resealed_strategy'])
def test_cached_seal_rejects_output_and_resealed_identity_drift(frozen,kind):
    _,cache,out=frozen
    (out/'features.parquet').write_bytes(b'synthetic features');r.dump(out/'feature_receipt.json',{})
    phase=r.PHASES[0];dest=sealed_trial(cache,out,phase);r.verify_completed(cache,out,phase)
    if kind=='hash':(dest/'equity.parquet').write_bytes(b'loss omitted')
    else:
        meta=r.read(dest/'metadata.json')
        if kind=='resealed_phase':meta['parameters']['phase']='validation3'
        elif kind=='resealed_config':meta['engine']['slippage_bps']=0
        elif kind=='resealed_core':meta['source_sha256']={}
        else:meta['strategy']='DifferentPolicy'
        r.dump(dest/'metadata.json',meta);receipt=r.read(dest/'completion.json');receipt['outputs_sha256']=r.output_files(dest);r.dump(dest/'completion.json',receipt)
    with pytest.raises(RuntimeError):r.verify_completed(cache,out,phase)


def test_unapproved_phase_rejected_before_source_access(tmp_path):
    bad=('hidden_neighbor',r.VALID_START,r.EVAL_START,False)
    with pytest.raises(RuntimeError,match='five'):r.run_phase(tmp_path,tmp_path,bad)
