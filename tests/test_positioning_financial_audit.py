"""Synthetic-only independent candidate28 wallet and closed-episode audit tests."""
from dataclasses import asdict,replace
import ast
import copy
from pathlib import Path
import subprocess
import numpy as np
import pandas as pd
import pytest
from aster.backtest.engine import Engine
from examples.positioning_research.strategy import PositioningPortfolio
from examples.funding_rank.run import SnapshotObserver
from examples.positioning_research import strategy as policy
from audit import verify_positioning_outputs as audit
from audit import verify_funding_rank_outputs as reference
from tests.test_funding_rank_execution import START,catalog,candles,config
from tests.test_positioning_strategy import features
from tests.test_positioning_runner_audit import executed


def evidence(monkeypatch,stress=False,partial=False,symbol='DOGEUSDT'):
    monkeypatch.setattr(policy,'HOLD',pd.Timedelta(minutes=2))
    specs=[replace(s,maker_bps=10 if stress else 5,taker_bps=10 if stress else 5) for s in catalog().values()]
    cfg=replace(config(int(stress)),slippage_bps=16 if stress else 8,participation=.025 if stress else .05)
    volumes={(m,symbol):40 for m in range(30)} if partial else None
    bars=candles(volumes,30)
    funding=pd.DataFrame([{'timestamp':START+pd.Timedelta(minutes=7),
        'instrument_id':spec.id,'funding_rate':.0002,'mark_price':.01 if spec.symbol=='1000PEPEUSDT' else 100.} for spec in specs])
    engine=Engine(specs,cfg);observer=SnapshotObserver(engine);engine.portfolio.snapshot=observer
    strategy=PositioningPortfolio(features(30,eligible=(symbol,)),START+pd.Timedelta(days=2))
    result=engine.run(bars,strategy,funding)
    tables={n:getattr(result,n) for n in audit.LEDGERS};exposure=pd.DataFrame(observer.rows)
    source={spec.id:bars.loc[bars.instrument_id.eq(spec.id)].reset_index(drop=True) for spec in specs}
    diagnostics={'events':[]}
    from examples.funding_rank.run import forensic_normalize
    diagnostics['events']=forensic_normalize(strategy.diagnostics)
    completed=forensic_normalize(strategy.completed_episodes)
    return (tables,exposure,source,funding,[asdict(s) for s in specs],asdict(cfg)),diagnostics,completed


@pytest.mark.parametrize('stress,partial,symbol',[(False,False,'DOGEUSDT'),(True,False,'PEPEUSDT'),
                                                (False,True,'DOGEUSDT'),(True,True,'DOGEUSDT')])
def test_independent_native_cash_margin_funding_replay_and_actual_episode(monkeypatch,stress,partial,symbol):
    args,diagnostics,completed=evidence(monkeypatch,stress,partial,symbol)
    state,preopen=audit.reconstruct(*args,START,START+pd.Timedelta(minutes=30))
    audit.verify_long_inventory(args[0],args[1])
    participants,count=audit.verify_completed_episodes(completed,diagnostics,preopen,args[0],START,START+pd.Timedelta(minutes=30))
    assert count==(0 if partial else 1) and participants==([] if partial else [symbol])
    assert state.cash['binance']==pytest.approx(args[0]['equity'].cash.iloc[-1])
    assert args[1].shape[1]==63 and all(q==0 for q in state.q.values())
    assert set(state.preopen_detail)==set(preopen)
    assert all(set(row)=={'marks','average_prices','liquidation_before_callback'} for row in state.preopen_detail.values())
    assert not any(row['liquidation_before_callback'] for row in state.preopen_detail.values())


@pytest.mark.parametrize('mutation',['cash','margin','collateral','mark','native','funding_sign','funding_clock',
                                    'quantity','fee','price','volume','activation','live_orders','source_rate'])
def test_corrupt_financial_trajectory_rejected(monkeypatch,mutation):
    args,_,_=evidence(monkeypatch);tables,exposure,bars,funding,specs,cfg=copy.deepcopy(args)
    traded=tables['fills'].instrument_id.iloc[0]
    if mutation=='cash':tables['equity'].loc[7,'cash']+=1
    elif mutation=='margin':tables['equity'].loc[7,'margin_used']+=1
    elif mutation=='collateral':exposure.loc[7,'entry_collateral_field_DOGEUSDT']+=1
    elif mutation=='mark':exposure.loc[7,'mark_PEPEUSDT']*=1000
    elif mutation=='native':tables['fills'].loc[0,'instrument_id']='binance:perpetual:PEPEUSDT'
    elif mutation=='funding_sign':tables['funding'].loc[0,'funding_payment']*=-1
    elif mutation=='funding_clock':tables['funding'].loc[0,'timestamp']+=pd.Timedelta(seconds=1)
    elif mutation=='quantity':tables['fills'].loc[0,'quantity']+=1
    elif mutation=='fee':tables['fills'].loc[0,'fee']+=1
    elif mutation=='price':tables['fills'].loc[0,'price']+=1
    elif mutation=='volume':bars[traded].loc[4,'volume']=0
    elif mutation=='activation':
        row=tables['events'].index[tables['events'].type.eq('ORDER_SUBMITTED')][0]
        tables['events'].loc[row,'active_at']+=pd.Timedelta(minutes=1)
    elif mutation=='live_orders':exposure.loc[7,'live_order_count']+=1
    else:funding.loc[funding.instrument_id.eq(traded),'funding_rate']*=2
    with pytest.raises((AssertionError,KeyError)):
        audit.reconstruct(tables,exposure,bars,funding,specs,cfg,START,START+pd.Timedelta(minutes=30))


@pytest.mark.parametrize('mutation',['omit','duplicate','failed','entry_time','closed_time','observed_time','native','vwap','closing_qty'])
def test_actual_closed_episode_cannot_be_omitted_fabricated_or_resealed(monkeypatch,mutation):
    args,diagnostics,completed=evidence(monkeypatch)
    state,preopen=audit.reconstruct(*args,START,START+pd.Timedelta(minutes=30));tables=copy.deepcopy(args[0])
    completed=copy.deepcopy(completed)
    if mutation=='omit':completed=[]
    elif mutation=='duplicate':completed.append(copy.deepcopy(completed[0]))
    elif mutation=='failed':completed[0]['failed']=True
    elif mutation=='entry_time':completed[0]['entry_completed_at']=(pd.Timestamp(completed[0]['entry_completed_at'])+pd.Timedelta(seconds=1)).isoformat()
    elif mutation=='closed_time':completed[0]['closed_at']=completed[0]['entry_completed_at']
    elif mutation=='observed_time':completed[0]['observed_closed_at']=completed[0]['entry_completed_at']
    elif mutation=='native':completed[0]['instrument_id']='binance:perpetual:1000PEPEUSDT'
    elif mutation=='vwap':completed[0]['average_entry_price']+=1
    else:tables['fills'].loc[tables['fills'].side.eq(-1),'quantity']*=.5
    with pytest.raises(AssertionError):audit.verify_completed_episodes(completed,diagnostics,preopen,tables,START,START+pd.Timedelta(minutes=30))


def test_full_tiny_export_phase_independently_reconstructs_all_26_files(executed):
    cache,_,out,phase,cert,*_=executed;lock=audit.read(out/'source_lock.json')
    # The independent runner's tiny fixture deliberately omits runtime; supply
    # a complete synthetic provenance envelope without altering financial bytes.
    import importlib.metadata,sys
    from examples.positioning_research import run
    lock['runtime']={'python':sys.version,**{n:importlib.metadata.version(n) for n in ('numpy','pandas','pyarrow','scipy','plotly')}}
    run.dump(out/'source_lock.json',lock)
    folder=out/'trials'/phase[0];meta=run.read(folder/'metadata.json')
    meta['parameters']=run.parameters(out,phase,cert);meta['source_manifest']=run.source_manifest(out)
    run.dump(folder/'metadata.json',meta);run.dump(folder/'source_manifest.json',meta['source_manifest'])
    run.dump(folder/'completion.json',{'parameters':meta['parameters'],'outputs_sha256':run.output_files(folder)})
    anchor=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,check=True,text=True).stdout.strip()
    record,score,equity=audit.verify_phase(cache,out,phase,lock,anchor,cert)
    assert len(record['outputs_sha256'])==26 and record['completed_episodes']==1
    assert record['trajectory_reconstruction_passed'] and not record['recorded_policy_reconstruction_complete']
    assert score['completed_participants']==['BTCUSDT'] and score['terminal_flat_resolved']


def test_independent_arithmetic_import_graph_contains_no_production_modules():
    for path in (Path(audit.__file__),Path(reference.__file__)):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):assert not (node.module or '').startswith(('aster','examples'))
            elif isinstance(node,ast.Import):assert not any(a.name.startswith(('aster','examples')) for a in node.names)
    assert audit.Replay is reference.Replay and audit.reconstruct is not reference.reconstruct


def test_bootstrap_matches_fixed_candidate28_runner_and_preserves_input():
    from examples.positioning_research import run
    clock=pd.date_range('2026-07-05',periods=14,freq='D',tz='UTC')
    frame=pd.DataFrame({'timestamp':clock,'equity':100000*np.cumprod(1+np.array([0,.001,-.002,.003,-.001,.002,0,.001,-.003,.001,.002,0,.001,-.001]))})
    original=frame.copy(deep=True)
    assert audit.conditional_interval(frame)==run.conditional_interval(frame)
    pd.testing.assert_frame_equal(frame,original)


def terminal_packet():
    t=pd.Timestamp('2026-04-05T00:05:00Z');stop=t+pd.Timedelta(minutes=5);i=audit.iid('binance','BTCUSDT')
    submitted={'type':'ORDER_SUBMITTED','timestamp':t,'instrument_id':i,'order_id':'O1','side':1,'quantity':3.,
               'order_type':'market','limit_price':None,'stop_price':None,'post_only':False,'reduce_only':False,'tif':'GTC','active_at':t}
    events=pd.DataFrame([submitted,{'type':'ORDER_ACCEPTED','timestamp':t,'order_id':'O1'},
                         {'type':'ORDER_PARTIALLY_FILLED','timestamp':t,'order_id':'O1','quantity':1.},
                         {'type':'ORDER_CANCELLED','timestamp':stop,'order_id':'O1','reason':'end_of_data'}])
    order={'instrument_id':i,'side':1,'quantity':3.,'order_type':'market','limit_price':None,'stop_price':None,
           'post_only':False,'reduce_only':False,'tif':'GTC','id':'O1','submitted_at':t.isoformat(),
           'active_at':t.isoformat(),'remaining':2.,'status':'partial','first_seen':t.isoformat(),'triggered':False}
    terminal={'before_end_of_data_cancellation':[order],'after_run_live_orders':[]}
    return terminal,{'events':events},pd.DataFrame({'live_order_count':[1]}),stop


def test_actual_pre_auto_cancellation_order_identity_remaining_and_state():
    packet=terminal_packet();assert audit.verify_terminal_orders(*packet)[0]['remaining']==2.


@pytest.mark.parametrize('key,value',[('id','O_FAKE'),('instrument_id','binance:perpetual:PEPEUSDT'),
                                     ('quantity',4.),('remaining',3.),('status','accepted'),('side',-1),
                                     ('active_at','2026-04-05T00:06:00Z'),('first_seen',None),('triggered',True)])
def test_resealed_terminal_order_fields_cannot_hide_live_inventory(key,value):
    terminal,tables,exposure,stop=terminal_packet();terminal['before_end_of_data_cancellation'][0][key]=value
    with pytest.raises(AssertionError):audit.verify_terminal_orders(terminal,tables,exposure,stop)


def test_intermediate_fills_cannot_create_simultaneous_or_short_inventory():
    ids=[audit.iid('binance',s) for s in ('BTCUSDT','DOGEUSDT')]
    tables={'events':pd.DataFrame([{'type':'ORDER_SUBMITTED','order_id':'1','reduce_only':False},
                                  {'type':'ORDER_SUBMITTED','order_id':'2','reduce_only':False}]),
            'fills':pd.DataFrame([{'instrument_id':ids[0],'side':1,'quantity':1.,'order_id':'1','exit_reason':'strategy'},
                                 {'instrument_id':ids[1],'side':1,'quantity':1.,'order_id':'2','exit_reason':'strategy'}])}
    exposure=pd.DataFrame({f'quantity_{s}':[0.] for s in audit.SYMBOLS})
    with pytest.raises(AssertionError,match='simultaneous'):audit.verify_long_inventory(tables,exposure)
    tables['fills']=tables['fills'].iloc[:1].copy();tables['fills'].loc[0,'side']=-1
    with pytest.raises(AssertionError):audit.verify_long_inventory(tables,exposure)


def test_all_phase_and_common_evidence_snapshot_detects_cross_phase_and_helper_drift(tmp_path,monkeypatch):
    repo=tmp_path/'repo';out=tmp_path/'out';repo.mkdir();out.mkdir()
    monkeypatch.setattr(audit,'REPO',repo)
    source=repo/'source.py';source.write_text('# source\n')
    for name in ('audit/verify_funding_rank_outputs.py',audit.FEATURE_AUDITOR,audit.PREREG+'/preregistration.json'):
        p=repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic reviewed helper')
    cert=out/'independent_feature.json';cert.write_text('{}')
    dataset=repo/'dataset.json';dataset.write_text('{}')
    raw=tmp_path/'raw.zip';raw.write_bytes(b'synthetic raw archive')
    lock={'dataset_certificate_path':str(dataset),'sources':{'source.py':'synthetic'},
          'perpetual_inputs':{str(raw):'synthetic'},'metrics_inputs':{}}
    archive=out/'executed_source/source.py';archive.parent.mkdir();archive.write_bytes(source.read_bytes())
    for n in ('source_lock.json','input_verification.json','feature_receipt.json','published_lock.json','summary.json'):(out/n).write_text('{}')
    for group in audit.native_feature_paths(out).values():
        for p in group.values():p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'synthetic feature')
    for phase in audit.PHASES:
        for name in (*audit.OUTPUTS,'completion.json'):
            p=out/'trials'/phase[0]/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'synthetic evidence')
    before=audit.evidence_hashes(out,lock,cert)
    assert len([n for n in before if n.endswith('completion.json')])==5
    assert '__runtime__' in before
    target=out/'trials'/'validation1'/'fills.parquet';target.write_bytes(b'changed earlier phase')
    assert audit.evidence_hashes(out,lock,cert)!=before
    target.write_bytes(b'synthetic evidence');assert audit.evidence_hashes(out,lock,cert)==before
    (repo/'audit/verify_funding_rank_outputs.py').write_text('changed helper')
    assert audit.evidence_hashes(out,lock,cert)!=before


@pytest.fixture
def certified_features(tmp_path,monkeypatch):
    out=tmp_path/'out';repo=tmp_path/'repo';out.mkdir();repo.mkdir();monkeypatch.setattr(audit,'REPO',repo)
    for name in (audit.FEATURE_AUDITOR,'audit/verify_positioning_dataset.py'):
        path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# independent synthetic auditor\n')
    for name in ('source_lock.json','input_verification.json','published_lock.json'):(out/name).write_text('{}')
    for group in audit.native_feature_paths(out).values():
        for path in group.values():path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'synthetic immutable feature file')
    hashes={v:{i:audit.sha(p) for i,p in group.items()} for v,group in audit.native_feature_paths(out).items()}
    receipt={'source_lock_sha256':audit.sha(out/'source_lock.json'),'features_sha256':hashes}
    (out/'feature_receipt.json').write_text(__import__('json').dumps(receipt))
    certificate={'complete':True,'errors':[],'source_anchor':'a'*40,'input_anchor':'b'*40,
        'source_lock_sha256':audit.sha(out/'source_lock.json'),'feature_receipt_sha256':audit.sha(out/'feature_receipt.json'),
        'features_sha256':hashes,'published_lock_sha256':audit.sha(out/'published_lock.json'),
        'input_verification_sha256':audit.sha(out/'input_verification.json'),
        'source_unchanged_during_audit':True,'input_unchanged_during_audit':True,
        'features_unchanged_during_audit':True,'auditor_source_unchanged':True,
        'scope':{'native_stream_count':8,'delays_minutes':[6,11],'begin':audit.START.isoformat(),
                 'end':audit.END.isoformat(),'full_reconstruction':True},
        'auditor_path':audit.FEATURE_AUDITOR,'auditor_sha256':audit.sha(repo/audit.FEATURE_AUDITOR),
        'raw_dataset_helper_sha256':audit.sha(repo/'audit/verify_positioning_dataset.py'),
        'completed_at_utc':pd.Timestamp.now(tz='UTC').isoformat()}
    path=out/'independent_synthetic_certificate.json';path.write_text(__import__('json').dumps(certificate))
    return out,repo,path,certificate


def test_feature_certificate_exact_publication_raw_helper_scope_and_anchors(certified_features):
    out,_,path,cert=certified_features
    assert audit.verify_feature_certificate(out,path,'a'*40,'b'*40)==cert


@pytest.mark.parametrize('mutation',['input_anchor','scope','publication','input_verification','raw_helper',
                                     'feature_hash','feature_source','stale','failed','helper_file','extra_variant','symlink'])
def test_forged_or_stale_feature_certificates_rejected(certified_features,mutation):
    out,repo,path,cert=certified_features
    if mutation=='input_anchor':cert['input_anchor']='c'*40
    elif mutation=='scope':cert['scope']['native_stream_count']=7
    elif mutation=='publication':cert['published_lock_sha256']='0'*64
    elif mutation=='input_verification':cert['input_verification_sha256']='0'*64
    elif mutation=='raw_helper':cert['raw_dataset_helper_sha256']='0'*64
    elif mutation=='feature_hash':next(iter(audit.native_feature_paths(out)['baseline'].values())).write_bytes(b'resealed different source')
    elif mutation=='feature_source':cert['features_unchanged_during_audit']=False
    elif mutation=='stale':cert['completed_at_utc']='2020-01-01T00:00:00Z'
    elif mutation=='failed':cert['errors']=['independent parser failed']
    elif mutation=='helper_file':(repo/'audit/verify_positioning_dataset.py').write_text('# changed helper\n')
    elif mutation=='extra_variant':(out/'features'/'chosen_on_returns').mkdir()
    else:
        source=next(iter(audit.native_feature_paths(out)['baseline'].values()));copy_path=out/'unchanged_copy';copy_path.write_bytes(source.read_bytes())
        source.unlink();source.symlink_to(copy_path)
    path.write_text(__import__('json').dumps(cert))
    with pytest.raises(AssertionError):audit.verify_feature_certificate(out,path,'a'*40,'b'*40)


def artifact_packet(tmp_path,monkeypatch):
    repo=tmp_path/'repo';out=tmp_path/'out';repo.mkdir();out.mkdir();monkeypatch.setattr(audit,'REPO',repo)
    for name in ('audit/verify_funding_rank_outputs.py',audit.FEATURE_AUDITOR,audit.PREREG+'/preregistration.json'):
        path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('synthetic reviewed helper')
    raw=tmp_path/'raw.zip';raw.write_bytes(b'synthetic raw source')
    dataset=repo/'dataset.json';dataset.write_text('{}')
    lock={'dataset_certificate_path':str(dataset),'sources':{},'perpetual_inputs':{str(raw):audit.sha(raw)},'metrics_inputs':{}}
    import json
    (out/'source_lock.json').write_text(json.dumps(lock))
    for name in ('input_verification.json','feature_receipt.json','published_lock.json','summary.json'):(out/name).write_text('{}')
    cert=out/'synthetic_feature_certificate.json';cert.write_text('{}')
    for group in audit.native_feature_paths(out).values():
        for path in group.values():path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'synthetic feature')
    for phase in audit.PHASES:
        for name in (*audit.OUTPUTS,'completion.json'):
            path=out/'trials'/phase[0]/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'synthetic phase evidence')
    return repo,out,raw,lock,cert


@pytest.mark.parametrize('target',['publication','helper','raw','feature','summary'])
def test_initial_provenance_boundary_is_pinned_before_guard(tmp_path,monkeypatch,target):
    repo,out,raw,lock,cert=artifact_packet(tmp_path,monkeypatch)
    path={'publication':out/'published_lock.json','helper':repo/'audit/verify_funding_rank_outputs.py',
          'raw':raw,'feature':next(iter(audit.native_feature_paths(out)['baseline'].values())),
          'summary':out/'summary.json'}[target]
    def mutate_guard(*args):
        path.write_bytes(path.read_bytes()+b' ')
        return lock
    calls=[];monkeypatch.setattr(audit,'packet_guard',mutate_guard)
    monkeypatch.setattr(audit,'verify_feature_certificate',lambda *a:calls.append('numeric stage'))
    with pytest.raises(AssertionError,match='initial provenance'):audit.verify(tmp_path,tmp_path,out,'a'*40,'b'*40,cert)
    assert calls==[]


@pytest.mark.parametrize('target',['earlier_phase','publication','helper','raw'])
def test_later_phase_cannot_rebind_initial_financial_evidence(tmp_path,monkeypatch,target):
    repo,out,raw,lock,cert=artifact_packet(tmp_path,monkeypatch)
    monkeypatch.setattr(audit,'packet_guard',lambda *args:lock)
    monkeypatch.setattr(audit,'verify_feature_certificate',lambda *args:{'complete':True})
    path={'earlier_phase':out/'trials'/'validation1'/'fills.parquet','publication':out/'published_lock.json',
          'helper':repo/'audit/verify_funding_rank_outputs.py','raw':raw}[target]
    calls=[]
    def phase(*args):
        name=args[2][0];calls.append(name)
        if name=='validation2':path.write_bytes(path.read_bytes()+b' ')
        return {},{},pd.DataFrame()
    monkeypatch.setattr(audit,'verify_phase',phase)
    with pytest.raises(AssertionError,match='during reconstruction'):audit.verify(tmp_path,tmp_path,out,'a'*40,'b'*40,cert)
    assert calls==['validation1','validation2']
