"""Synthetic-only candidate28 runner locks, semantic cache and execution gates."""
from dataclasses import asdict
from pathlib import Path
import copy
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, Order
from examples.positioning_research import run as r
from examples.funding_rank import run as previous


def specs():
    return [Instrument(id=r.native_id('binance',s),exchange='binance',market_type='perpetual',
        symbol='1000PEPEUSDT' if s=='PEPEUSDT' else s,base='1000PEPE' if s=='PEPEUSDT' else s[:-4],
        quote='USDT',lot_size=.001,min_quantity=.001,min_notional=1,taker_bps=5) for s in r.SYMBOLS]


@pytest.fixture
def frozen(tmp_path,monkeypatch):
    repo=tmp_path/'repo';perp=tmp_path/'perp';metrics=tmp_path/'metrics';out=tmp_path/'out'
    names=[str(p.relative_to(r.REPO)) for p in r.source_paths()]
    for name in names:
        path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# synthetic source\n')
    perp.mkdir();metrics.mkdir()
    r.dump(perp/'instruments.json',[asdict(s) for s in specs()])
    raw=perp/'raw.json';raw.write_text('uninterpreted synthetic raw bytes')
    metric=metrics/'normalized.parquet';metric.write_bytes(b'synthetic normalized bytes')
    seal=metrics/'complete.json';r.dump(seal,{'complete':True})
    dataset=repo/'audit/positioning_dataset_evidence.json';r.dump(dataset,{'complete':True})
    monkeypatch.setattr(r,'REPO',repo);monkeypatch.setattr(r,'DATASET_CERT',dataset)
    monkeypatch.setattr(r,'require_reviewed_sources',lambda:None)
    monkeypatch.setattr(r,'dataset_certificate',lambda cache:{'complete':True,'source_seal':r.digest(Path(cache)/'complete.json')})
    monkeypatch.setattr(r.collector,'verify',lambda cache:None)
    monkeypatch.setattr(r,'verify',lambda cache,s,ins:{'spot_symbol':s,'minute_grid_exact':True})
    monkeypatch.setattr(previous,'identity',lambda cache:{'inputs':{str(raw.resolve()):r.digest(raw)},'runtime':{'python':'synthetic'}})
    r.freeze(perp,metrics,out)
    return repo,perp,metrics,out


def source_frames(start,end,iid):
    grid=pd.date_range(start,end,freq='min',inclusive='left')
    bars=pd.DataFrame({'timestamp':grid,'instrument_id':iid,'duration_seconds':60,'close':100.})
    mg=pd.date_range(start,end,freq='5min',inclusive='left')
    metrics=pd.DataFrame({'timestamp':mg,'instrument_id':iid,'sum_open_interest':1000.})
    return bars,metrics


def write_features(out,monkeypatch,minutes=100):
    start=pd.Timestamp('2026-04-05',tz='UTC');end=start+pd.Timedelta(minutes=minutes)
    monkeypatch.setattr(r,'START',start);monkeypatch.setattr(r,'END',end)
    packet={v:{} for v in r.DELAYS};paths=r.feature_paths(out)
    for s in r.SYMBOLS:
        iid=r.native_id('binance',s);bars,metrics=source_frames(start,end,iid)
        for variant,delay in r.DELAYS.items():
            frame=r.build_features(bars,metrics,instrument_id=iid,start=start,end=end,metric_delay_minutes=delay)
            packet[variant][iid]=frame;path=paths[variant][iid];path.parent.mkdir(parents=True,exist_ok=True);frame.to_parquet(path)
    r.dump(out/'feature_receipt.json',{'source_lock_sha256':r.digest(out/'source_lock.json'),
        'features_sha256':{v:{i:r.digest(p) for i,p in group.items()} for v,group in paths.items()},
        'rows_per_stream':minutes-2,'columns':r.FEATURE_COLUMNS,
        'availability_assumptions':{v:r.expected_attrs(d) for v,d in r.DELAYS.items()}})
    return packet


def reseal_features(out):
    receipt=r.read(out/'feature_receipt.json')
    receipt['features_sha256']={v:{i:r.digest(p) for i,p in group.items()} for v,group in r.feature_paths(out).items()}
    r.dump(out/'feature_receipt.json',receipt)


def test_freeze_binds_transitive_source_and_separate_input_namespaces(frozen):
    repo,perp,metrics,out=frozen;lock=r.guard(perp,metrics,out)
    assert lock['candidate_count_cumulative']==28
    for name in ('examples/funding_rank/run.py','examples/funding_rank/strategy.py',
                 'examples/minute_research/downloadcarry.py','examples/cross_venue/signals.py',
                 'examples/positioning/collect_archives.py','examples/positioning_research/strategy.py'):
        assert name in lock['sources']
    assert str((perp/'raw.json').resolve()) in lock['perpetual_inputs']
    assert str((metrics/'normalized.parquet').resolve()) in lock['metrics_inputs']
    assert lock['dataset_certificate_sha256']==r.digest(r.DATASET_CERT)


@pytest.mark.parametrize('kind',['source','raw_perp','normalized_metrics','raw_metrics','source_archive','input_receipt','dataset_certificate'])
def test_freeze_drift_rejected(frozen,kind):
    repo,perp,metrics,out=frozen
    if kind=='raw_metrics':(metrics/'unexpected_raw.txt').write_text('new raw input')
    else:
        path={'source':repo/'examples/positioning_research/strategy.py','raw_perp':perp/'raw.json',
              'normalized_metrics':metrics/'normalized.parquet','source_archive':out/'executed_source/aster/__init__.py',
              'input_receipt':out/'input_verification.json','dataset_certificate':r.DATASET_CERT}[kind]
        if kind=='input_receipt':r.dump(path,{})
        else:path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(RuntimeError):r.guard(perp,metrics,out)


def test_features_blocked_before_freeze_and_publication(frozen,tmp_path,monkeypatch):
    _,perp,metrics,out=frozen;calls=[]
    monkeypatch.setattr(r,'build_features',lambda *a,**k:calls.append(1))
    with pytest.raises(RuntimeError,match='Freeze BEFORE'):r.generate_features(perp,metrics,tmp_path/'unsealed')
    with pytest.raises(RuntimeError,match='published'):r.generate_features(perp,metrics,out)
    assert calls==[] and not (out/'features').exists()


def test_refuse_nonempty_unsealed_directory(frozen,tmp_path):
    _,perp,metrics,_=frozen;out=tmp_path/'partial';out.mkdir();(out/'leftover').write_text('preserve me')
    with pytest.raises(RuntimeError,match='nonempty'):r.freeze(perp,metrics,out)


def test_exact_sixteen_stream_cache_and_caller_identity(frozen,monkeypatch):
    _,_,_,out=frozen;packet=write_features(out,monkeypatch);verified=r.verified_features(out,packet)
    assert set(verified)=={'baseline','delayed'} and all(len(v)==8 for v in verified.values())
    wrong=copy.deepcopy(packet);wrong['baseline'][r.native_id('binance','DOGEUSDT')].iloc[-1,2]=999.
    with pytest.raises(AssertionError):r.verified_features(out,wrong)
    assert set(packet['baseline'])=={s.id for s in specs()}


@pytest.mark.parametrize('kind',['index','naive_index','native_id','column_order','attrs','integer_valid','string_valid',
                                'false_valid','early_valid','nan_price','inf_quantity','negative_quantity','publication_equality',
                                'age','warmup_return','missing_ready_return'])
def test_resealed_semantically_bad_streams_rejected(frozen,monkeypatch,kind):
    _,_,_,out=frozen;packet=write_features(out,monkeypatch);iid=r.native_id('binance','DOGEUSDT')
    frame=packet['baseline'][iid].copy();first,last=frame.index[0],frame.index[-1]
    if kind=='index':frame.index=frame.index+pd.Timedelta(seconds=1)
    elif kind=='naive_index':frame.index=frame.index.tz_localize(None)
    elif kind=='native_id':frame['instrument_id']='binance:perpetual:BTCUSDT'
    elif kind=='column_order':frame=frame[list(reversed(frame.columns))]
    elif kind=='attrs':frame.attrs['metric_delay_minutes']=0
    elif kind=='integer_valid':frame['valid']=frame.valid.astype(int)
    elif kind=='string_valid':frame['valid']=frame.valid.astype(str)
    elif kind=='false_valid':frame.loc[last,'valid']=False
    elif kind=='early_valid':frame.loc[first,'valid']=True
    elif kind=='nan_price':frame.loc[last,'price']=float('nan')
    elif kind=='inf_quantity':frame.loc[last,'native_open_interest']=float('inf')
    elif kind=='negative_quantity':frame.loc[last,'native_open_interest']=-1.
    elif kind=='publication_equality':frame.loc[last,'metric_available_at']=last
    elif kind=='age':frame.loc[last,'metric_age_seconds']=0.
    elif kind=='warmup_return':frame.loc[first,'quantity_change_1h']=0.
    else:frame.loc[last,'price_return_1h']=float('nan')
    frame.to_parquet(r.feature_paths(out)['baseline'][iid]);reseal_features(out)
    with pytest.raises(RuntimeError):r.verified_features(out)


def certificate(out,repo):
    auditor=repo/r.FEATURE_AUDITOR;auditor.parent.mkdir(parents=True,exist_ok=True);auditor.write_text('# separate independent synthetic auditor\n')
    cert={'complete':True,'errors':[],'source_lock_sha256':r.digest(out/'source_lock.json'),
          'feature_receipt_sha256':r.digest(out/'feature_receipt.json'),
          'features_sha256':r.read(out/'feature_receipt.json')['features_sha256'],
          'source_unchanged_during_audit':True,'input_unchanged_during_audit':True,
          'features_unchanged_during_audit':True,'auditor_source_unchanged':True,
          'scope':{'native_stream_count':8,'delays_minutes':[6,11],'begin':r.START.isoformat(),
                   'end':r.END.isoformat(),'full_reconstruction':True},
          'auditor_path':r.FEATURE_AUDITOR,'auditor_sha256':r.digest(auditor),
          'completed_at_utc':pd.Timestamp.now(tz='UTC').isoformat()}
    path=out/'independent_synthetic_feature_certificate.json';r.dump(path,cert);return path


@pytest.mark.parametrize('kind',['missing','errors','incomplete','scope','hash','source_drift','features_drift','auditor_drift','stale'])
def test_independent_certificate_gate_rejects_missing_partial_and_stale(frozen,monkeypatch,kind):
    repo,_,_,out=frozen;write_features(out,monkeypatch);monkeypatch.setattr(r,'published_lock',lambda out:{})
    path=certificate(out,repo)
    if kind=='missing':path=None
    else:
        cert=r.read(path)
        if kind=='errors':cert['errors']=['failed scalar reconstruction']
        elif kind=='incomplete':cert['complete']=False
        elif kind=='scope':cert['scope']['native_stream_count']=7
        elif kind=='hash':cert['features_sha256']['delayed'].pop(r.native_id('binance','PEPEUSDT'))
        elif kind=='source_drift':cert['source_unchanged_during_audit']=False
        elif kind=='features_drift':cert['features_unchanged_during_audit']=False
        elif kind=='auditor_drift':cert['auditor_sha256']='0'*64
        else:cert['completed_at_utc']='2020-01-01T00:00:00Z'
        r.dump(path,cert)
    with pytest.raises(RuntimeError):r.require_feature_audit(out,path)


def test_valid_certificate_binds_all_two_delay_eight_native_streams(frozen,monkeypatch):
    repo,_,_,out=frozen;write_features(out,monkeypatch);monkeypatch.setattr(r,'published_lock',lambda out:{})
    path=certificate(out,repo);assert r.require_feature_audit(out,path)['complete']


def test_execute_without_certificate_never_reads_features_or_constructs_engine(frozen,monkeypatch):
    _,perp,metrics,out=frozen;calls=[]
    monkeypatch.setattr(r,'Engine',lambda *a:calls.append('engine'))
    monkeypatch.setattr(r,'verified_features',lambda *a:calls.append('features'))
    with pytest.raises(RuntimeError,match='Separate independent'):r.run_phase(perp,metrics,out,r.PHASES[0])
    assert calls==[] and not (out/'trials').exists()


def test_wrong_phase_rejected_before_source_access(tmp_path):
    with pytest.raises(RuntimeError,match='five'):r.run_phase(tmp_path,tmp_path,tmp_path,('neighbor',r.START,r.END,False))


def episode(symbol='DOGEUSDT',generation=1):
    t=pd.Timestamp('2026-07-05',tz='UTC')
    return {'symbol':symbol,'generation':generation,'instrument_id':r.native_id('binance',symbol),
            'submitted_at':t.isoformat(),'entry_completed_at':(t+pd.Timedelta(minutes=1)).isoformat(),
            'closed_at':(t+pd.Timedelta(hours=4)).isoformat(),
            'observed_closed_at':(t+pd.Timedelta(hours=4,minutes=1)).isoformat(),
            'average_entry_price':100.,'failed':False}


def test_participation_counts_closed_episodes_not_entries():
    participants,count=r.episode_participation([episode(),episode('PEPEUSDT',2)])
    assert participants=={'DOGEUSDT','PEPEUSDT'} and count==2
    for field,value in [('failed',True),('entry_completed_at',None),('closed_at',None),
                        ('instrument_id','binance:perpetual:PEPEUSDT'),('average_entry_price',0.)]:
        bad=episode();bad[field]=value
        with pytest.raises(RuntimeError):r.episode_participation([bad])
    with pytest.raises(RuntimeError,match='Duplicate'):r.episode_participation([episode(),episode()])


def test_account_config_observer_and_actual_endpoint_controls_unchanged():
    assert r.SnapshotObserver is previous.SnapshotObserver and r.config is previous.config and r.catalog is previous.catalog
    engine=Engine(specs(),r.config(False));t=pd.Timestamp('2026-07-05',tz='UTC')
    for spec in specs():engine.portfolio.marks[spec.id]=100.
    observer=r.SnapshotObserver(engine);observer(t)
    assert len(observer.rows[0])==63
    assert r.terminal_status(observer.rows[0],[])['terminal_flat_resolved']
    row=observer.rows[0].copy();row['quantity_PEPEUSDT']=1e-12
    assert not r.terminal_status(row,[])['terminal_flat_resolved']
    assert not r.terminal_status(observer.rows[0],[{'status':'accepted'}])['terminal_flat_resolved']
    assert r.config(True).slippage_bps==16 and r.config(False).slippage_bps==8


def test_exact_fifteen_prior_gates_and_cumulative_tails():
    scores={p[0]:{'total_return':.01,'return_after_indicative_exit_reserve':.009,'sharpe':.7,
                 'max_drawdown':.1,'liquidation_event_count':0,'terminal_flat_resolved':True} for p in r.PHASES}
    participants={'BTCUSDT','DOGEUSDT','PEPEUSDT','ADAUSDT'}
    assert r.gate_results(scores,[.01,-.01,.02],participants,2)==previous.gate_results(scores,[.01,-.01,.02],participants,2)
    clock=pd.date_range('2026-07-05',periods=12,freq='D',tz='UTC')
    frame=pd.DataFrame({'timestamp':clock,'equity':100000*1.001**np.arange(12)})
    result=r.conditional_interval(frame)
    assert result['comparison_count']==28 and result['tails']==[.05/56,1-.05/56]
    assert 'return_interval_bonferroni28' in result


def test_extra_hidden_feature_variants_rejected(frozen,monkeypatch):
    _,_,_,out=frozen;write_features(out,monkeypatch)
    (out/'features'/'outcome_selected').mkdir()
    with pytest.raises(RuntimeError,match='two feature'):r.verified_features(out)


def test_missing_native_stream_rejected(frozen,monkeypatch):
    _,_,_,out=frozen;write_features(out,monkeypatch)
    r.feature_paths(out)['delayed'][r.native_id('binance','PEPEUSDT')].unlink()
    with pytest.raises(RuntimeError,match='Missing/partial'):r.verified_features(out)


def test_publication_rejects_unapproved_git_namespace_and_no_prior_publication(frozen,monkeypatch):
    _,_,_,out=frozen
    with pytest.raises(RuntimeError,match='published'):r.published_lock(out)
    receipt={'source_lock_sha256':r.digest(out/'source_lock.json'),
             'input_verification_sha256':r.digest(out/'input_verification.json'),
             'remote_commit':'a'*40,'commit_path':'docs/other_trial',
             'historical_features_exist':False,'trials_exist':False}
    r.dump(out/'published_lock.json',receipt)
    with pytest.raises(RuntimeError,match='anchor/path'):r.published_lock(out)


def test_publication_requires_exact_anchored_bytes_and_origin_ancestry(frozen,monkeypatch):
    _,_,_,out=frozen
    receipt={'source_lock_sha256':r.digest(out/'source_lock.json'),
             'input_verification_sha256':r.digest(out/'input_verification.json'),
             'remote_commit':'a'*40,'commit_path':r.PREREG_PATH,
             'historical_features_exist':False,'trials_exist':False}
    r.dump(out/'published_lock.json',receipt)
    calls=[]
    def command(args,**kwargs):
        calls.append(args)
        if args[1]=='show':return SimpleNamespace(stdout=(out/args[2].split('/')[-1]).read_bytes(),returncode=0)
        return SimpleNamespace(stdout=b'',returncode=0)
    monkeypatch.setattr(r.subprocess,'run',command)
    assert r.published_lock(out)==receipt
    assert calls[-1]==['git','merge-base','--is-ancestor','a'*40,'origin/main']
    monkeypatch.setattr(r.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=b'resealed wrong bytes',returncode=0))
    with pytest.raises(RuntimeError,match='Git anchor'):r.published_lock(out)
    def not_pushed(args,**kwargs):
        if args[1]=='show':return SimpleNamespace(stdout=(out/args[2].split('/')[-1]).read_bytes(),returncode=0)
        return SimpleNamespace(stdout=b'',returncode=1)
    monkeypatch.setattr(r.subprocess,'run',not_pushed)
    with pytest.raises(RuntimeError,match='origin/main'):r.published_lock(out)


def test_dataset_certificate_bytes_must_match_committed_evidence(tmp_path,monkeypatch):
    # No actual dataset read: fail first, before considering a forged complete flag.
    cert=tmp_path/'dataset.json';r.dump(cert,{'complete':True,'errors':[]})
    monkeypatch.setattr(r,'DATASET_CERT',cert)
    monkeypatch.setattr(r.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=b'{"complete": false}',returncode=0))
    with pytest.raises(RuntimeError,match='committed evidence'):r.dataset_certificate(tmp_path)


def test_freeze_requires_committed_reviewed_sources_before_input_reads(tmp_path,monkeypatch):
    path=tmp_path/'new.py';path.write_text('# uncommitted edit\n')
    monkeypatch.setattr(r,'REPO',tmp_path);monkeypatch.setattr(r,'source_paths',lambda:[path])
    monkeypatch.setattr(r.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=b'# committed bytes\n',returncode=0))
    with pytest.raises(RuntimeError,match='Commit reviewed'):r.freeze(tmp_path,tmp_path,tmp_path/'out')


def sealed_trial(perp,out,phase,certificate_path):
    dest=out/'trials'/phase[0];dest.mkdir(parents=True)
    for name in r.OUTPUTS:(dest/name).write_bytes(b'preserved synthetic output')
    expected=r.parameters(out,phase,certificate_path);lock=r.read(out/'source_lock.json');manifest=r.source_manifest(out)
    r.dump(dest/'metadata.json',{'parameters':expected,'engine':asdict(r.config(phase[3])),
        'instruments':[asdict(s) for s in r.catalog(perp,phase[3])],
        'strategy':r.PositioningPortfolio.__name__,'strategy_version':str(r.PositioningPortfolio.version),
        'source_sha256':{n.removeprefix('aster/'):h for n,h in lock['sources'].items() if n.startswith('aster/')},
        'source_manifest':manifest,'start':str(phase[1]),'end':str(phase[2])})
    r.dump(dest/'source_manifest.json',manifest);r.dump(dest/'metrics.json',{'total_return':0})
    r.dump(dest/'completion.json',{'parameters':expected,'outputs_sha256':r.output_files(dest)})
    return dest


@pytest.mark.parametrize('kind',['output_hash','resealed_config','resealed_strategy','certificate_hash','published_receipt_hash'])
def test_cached_output_phase_audit_and_publication_bindings(frozen,monkeypatch,kind):
    repo,perp,_,out=frozen;write_features(out,monkeypatch);cert=certificate(out,repo)
    r.dump(out/'published_lock.json',{'synthetic_publication':True})
    phase=r.PHASES[0];dest=sealed_trial(perp,out,phase,cert)
    assert r.verify_completed(perp,out,phase,feature_audit=cert)=={'total_return':0}
    if kind=='output_hash':(dest/'equity.parquet').write_bytes(b'changed synthetic loss')
    elif kind=='certificate_hash':r.dump(cert,{'forged_replacement':True})
    elif kind=='published_receipt_hash':r.dump(out/'published_lock.json',{'changed_receipt':True})
    else:
        meta=r.read(dest/'metadata.json')
        if kind=='resealed_config':meta['engine']['slippage_bps']=0
        else:meta['strategy']='FundingRankPortfolio'
        r.dump(dest/'metadata.json',meta);receipt=r.read(dest/'completion.json')
        receipt['outputs_sha256']=r.output_files(dest);r.dump(dest/'completion.json',receipt)
    with pytest.raises(RuntimeError):r.verify_completed(perp,out,phase,feature_audit=cert)


@pytest.mark.parametrize('name',['source_lock.json','input_verification.json','feature_receipt.json','published_lock.json','feature_audit'])
def test_common_artifacts_pin_all_receipt_bytes(frozen,monkeypatch,name):
    repo,_,_,out=frozen;write_features(out,monkeypatch);cert=certificate(out,repo)
    r.dump(out/'published_lock.json',{'synthetic':True})
    pinned=r.common_artifacts(out,cert)
    assert set(pinned)=={'source_lock.json','input_verification.json','feature_receipt.json','published_lock.json','feature_audit'}
    path=cert if name=='feature_audit' else out/name
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(RuntimeError,match='artifacts changed'):r.check_common_unchanged(out,cert,pinned)


@pytest.mark.parametrize('when,target',[('later_phase','metrics'),('bootstrap','earlier_output'),
                                        ('bootstrap','earlier_completion'),('bootstrap','publication'),
                                        ('summary_write','earlier_output'),('summary_write','publication')])
def test_summary_rejects_packet_drift_during_verification_bootstrap_and_dump(frozen,monkeypatch,when,target):
    repo,perp,metrics,out=frozen
    r.dump(out/'published_lock.json',{'synthetic':True});r.dump(out/'feature_receipt.json',{'features_sha256':{}})
    cert=out/'independent_synthetic_certificate.json';r.dump(cert,{'complete':True})
    for phase in r.PHASES:
        folder=out/'trials'/phase[0];folder.mkdir(parents=True)
        for name in r.OUTPUTS:(folder/name).write_bytes(b'synthetic immutable packet')
        r.dump(folder/'completion.json',{'synthetic':True})
    evalfolder=out/'trials'/'evaluation'
    clock=pd.date_range(r.EVAL_START,r.END,freq='D')
    pd.DataFrame({'timestamp':clock,'equity':100000*1.001**np.arange(len(clock))}).to_parquet(evalfolder/'equity.parquet')
    completed=[episode(symbol,k+1) for k,symbol in enumerate(('BTCUSDT','DOGEUSDT','PEPEUSDT','ADAUSDT'))]
    r.dump(evalfolder/'completed_baskets.json',completed)
    (evalfolder/'leg_contributions.csv').write_text('symbol,net_pnl\nBTCUSDT,1\n')
    score={'total_return':.01,'return_after_indicative_exit_reserve':.009,'sharpe':.7,'max_drawdown':.1,
           'liquidation_event_count':0,'terminal_flat_resolved':True,
           'completed_participants':sorted(['BTCUSDT','DOGEUSDT','PEPEUSDT','ADAUSDT']),'completed_basket_count':4}
    monkeypatch.setattr(r,'guard',lambda *a:None)
    monkeypatch.setattr(r,'require_feature_audit',lambda *a:{'complete':True})
    monkeypatch.setattr(r,'verified_features',lambda *a:None)
    mutated=[]
    def mutate():
        if mutated:return
        mutated.append(True)
        path={'metrics':out/'trials'/'validation1'/'metrics.json',
              'earlier_output':out/'trials'/'validation1'/'fills.parquet',
              'earlier_completion':out/'trials'/'validation1'/'completion.json',
              'publication':out/'published_lock.json'}[target]
        path.write_bytes(path.read_bytes()+b' ')
    def verify(cache,dest,phase,**kwargs):
        if when=='later_phase' and phase[0]=='validation2':mutate()
        return copy.deepcopy(score)
    monkeypatch.setattr(r,'verify_completed',verify)
    original_bootstrap=r.conditional_interval
    def bootstrap(frame):
        result=original_bootstrap(frame)
        if when=='bootstrap':mutate()
        return result
    monkeypatch.setattr(r,'conditional_interval',bootstrap)
    original_dump=r.dump
    def dump(path,value):
        original_dump(path,value)
        if when=='summary_write' and Path(path).name=='summary.json':mutate()
    monkeypatch.setattr(r,'dump',dump)
    with pytest.raises(RuntimeError,match='artifacts changed'):
        r.summarize(perp,metrics,out,feature_audit=cert)
    assert mutated
