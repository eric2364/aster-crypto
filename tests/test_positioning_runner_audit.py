"""Independent tiny Engine/export cache and runner guard adversaries; no history."""
from dataclasses import asdict
import copy
import pandas as pd
import pytest
from examples.positioning_research import run as r
from examples.positioning_research import strategy as control
from examples.funding_rank import run as previous
from tests.test_funding_rank_execution import START,catalog,candles
from tests.test_positioning_strategy import features
from tests.test_positioning_runner import frozen,write_features,certificate


@pytest.fixture
def executed(tmp_path,monkeypatch):
    cache=tmp_path/'perp';cache.mkdir();metrics=tmp_path/'metrics';metrics.mkdir();out=tmp_path/'out';out.mkdir()
    begin=START+pd.Timedelta(minutes=80);stop=START+pd.Timedelta(minutes=110)
    phase=('evaluation',begin,stop,False)
    monkeypatch.setattr(r,'PHASES',[phase]);monkeypatch.setattr(previous,'PHASES',[phase]);monkeypatch.setattr(control,'HOLD',pd.Timedelta(minutes=1))
    monkeypatch.setattr(previous,'START',START);monkeypatch.setattr(previous,'END',START+pd.Timedelta(minutes=120))
    specs=catalog();r.dump(cache/'instruments.json',[asdict(v) for v in specs.values()]);bars=candles(minutes=120)
    for symbol,spec in specs.items():
        folder=cache/symbol;folder.mkdir()
        bars.loc[bars.instrument_id.eq(spec.id)].reset_index(drop=True).to_parquet(folder/'bars.parquet',index=False)
        pd.DataFrame({'timestamp':pd.Series([],dtype='datetime64[ns, UTC]'),'instrument_id':pd.Series([],dtype=str),
                      'funding_rate':pd.Series([],dtype=float),'mark_price':pd.Series([],dtype=float)}).to_parquet(folder/'funding.parquet',index=False)
    lock={'sources':{str(p.relative_to(r.REPO)):r.digest(p) for p in (r.REPO/'aster').rglob('*.py')}}
    r.dump(out/'source_lock.json',lock);r.dump(out/'input_verification.json',{});r.dump(out/'published_lock.json',{'synthetic':True});r.dump(out/'feature_receipt.json',{'features_sha256':{'baseline':'synthetic','delayed':'synthetic'}})
    fp=out/'synthetic_certificate.json';r.dump(fp,{'complete':True})
    packet={v:features(minutes=120) for v in r.DELAYS}
    calls=[]
    monkeypatch.setattr(r,'guard',lambda *args:calls.append('guard'))
    monkeypatch.setattr(r,'require_feature_audit',lambda *args:{'complete':True})
    monkeypatch.setattr(r,'verified_features',lambda *args:copy.deepcopy(packet))
    r.run_phase(cache,metrics,out,phase,feature_audit=fp)
    return cache,metrics,out,phase,fp,packet,calls


def reseal(data):
    cache,metrics,out,phase,fp,*_=data;folder=out/'trials'/phase[0]
    receipt=r.read(folder/'completion.json');receipt['outputs_sha256']=r.output_files(folder);r.dump(folder/'completion.json',receipt)


def test_real_tiny_pipeline_closes_episode_and_preserves_full_native_terminal(executed):
    cache,metrics,out,phase,fp,packet,calls=executed;folder=out/'trials'/phase[0]
    score=r.verify_completed(cache,out,phase,feature_audit=fp)
    assert len(r.read(folder/'completion.json')['outputs_sha256'])==26
    assert score['completed_episode_count']==1 and score['completed_participants']==['BTCUSDT']
    assert score['terminal_flat_resolved'] and score['terminal_observed_nonzero_position_count']==0
    assert len(pd.read_parquet(folder/'fills.parquet'))==2
    assert r.read(folder/'completed_baskets.json')==r.read(folder/'completed_episodes.json')
    assert len(calls)==2
    before=r.digest(folder/'completion.json')
    assert r.run_phase(cache,metrics,out,phase,feature_audit=fp)==score
    assert r.digest(folder/'completion.json')==before


@pytest.mark.parametrize('kind',['phase','start','stress','class','version','core','source_manifest','native','fees','config'])
def test_resealed_cached_metadata_identity_is_rejected(executed,kind):
    cache,_,out,phase,fp,*_=executed;folder=out/'trials'/phase[0];meta=r.read(folder/'metadata.json')
    if kind=='phase':meta['parameters']['phase']='validation1'
    elif kind=='start':meta['start']=str(phase[1]+pd.Timedelta(minutes=1))
    elif kind=='stress':meta['parameters']['stress']=True
    elif kind=='class':meta['strategy']='FundingRankPortfolio'
    elif kind=='version':meta['strategy_version']='old'
    elif kind=='core':meta['source_sha256']={}
    elif kind=='source_manifest':meta['source_manifest']['source_lock']={}
    elif kind=='native':meta['instruments'][3]['id']='binance:perpetual:PEPEUSDT'
    elif kind=='fees':meta['instruments'][0]['taker_bps']=0
    else:meta['engine']['participation']=1.
    r.dump(folder/'metadata.json',meta);reseal(executed)
    with pytest.raises(RuntimeError):r.verify_completed(cache,out,phase,feature_audit=fp)


def test_cached_feature_certificate_bytes_remain_exact(executed):
    cache,_,out,phase,fp,*_=executed
    fp.write_bytes(fp.read_bytes()+b' ')
    with pytest.raises(RuntimeError,match='phase/source/features'):r.verify_completed(cache,out,phase,feature_audit=fp)


def test_unsealed_output_change_fails_before_cached_metrics(executed):
    cache,_,out,phase,fp,*_=executed;(out/'trials'/phase[0]/'completed_episodes.json').write_text('[]')
    with pytest.raises(RuntimeError,match='output seal'):r.verify_completed(cache,out,phase,feature_audit=fp)


def test_partial_trial_is_preserved_not_automatically_rerun(executed):
    cache,metrics,out,phase,fp,*_=executed;(out/'trials'/phase[0]/'completion.json').unlink()
    with pytest.raises(RuntimeError,match='Partial trial'):r.run_phase(cache,metrics,out,phase,feature_audit=fp)


@pytest.mark.parametrize('field',['source_unchanged_during_audit','input_unchanged_during_audit','features_unchanged_during_audit','auditor_source_unchanged'])
def test_independent_feature_certificate_each_stability_flag_required(frozen,monkeypatch,field):
    repo,_,_,out=frozen;write_features(out,monkeypatch);monkeypatch.setattr(r,'published_lock',lambda out:{})
    fp=certificate(out,repo);value=r.read(fp);value.pop(field);r.dump(fp,value)
    with pytest.raises(RuntimeError,match=field):r.require_feature_audit(out,fp)


def test_missing_independent_auditor_module_prevents_future_launch(frozen,monkeypatch):
    repo,_,_,out=frozen;write_features(out,monkeypatch);monkeypatch.setattr(r,'published_lock',lambda out:{})
    fp=certificate(out,repo);(repo/r.FEATURE_AUDITOR).unlink()
    with pytest.raises(RuntimeError,match='auditor source'):r.require_feature_audit(out,fp)


@pytest.mark.parametrize('artifact',['published_lock.json','source_lock.json','input_verification.json','feature_receipt.json','feature_audit'])
def test_common_receipts_cannot_change_during_engine_execution(executed,monkeypatch,artifact):
    import shutil
    cache,metrics,out,phase,fp,*_=executed
    shutil.rmtree(out/'trials'/phase[0]) # fresh synthetic re-execution only
    original=r.Engine.run
    def change_receipt(engine,*args,**kwargs):
        result=original(engine,*args,**kwargs)
        path=fp if artifact=='feature_audit' else out/artifact
        receipt=r.read(path);receipt['irrelevant_new_field']='changed during execution'
        r.dump(path,receipt)
        return result
    monkeypatch.setattr(r.Engine,'run',change_receipt)
    with pytest.raises(RuntimeError,match='changed|drift|differ'):
        r.run_phase(cache,metrics,out,phase,feature_audit=fp)


def test_real_publication_guard_accepts_extra_receipt_field_when_anchor_unchanged(frozen,monkeypatch):
    from types import SimpleNamespace
    _,_,_,out=frozen
    receipt={'source_lock_sha256':r.digest(out/'source_lock.json'),
        'input_verification_sha256':r.digest(out/'input_verification.json'),'remote_commit':'a'*40,
        'commit_path':r.PREREG_PATH,'historical_features_exist':False,'trials_exist':False,
        'irrelevant_new_field':'the same mutation used by the execution-race test'}
    r.dump(out/'published_lock.json',receipt)
    def command(args,**kwargs):
        if args[1]=='show':return SimpleNamespace(stdout=(out/args[2].split('/')[-1]).read_bytes(),returncode=0)
        return SimpleNamespace(stdout=b'',returncode=0)
    monkeypatch.setattr(r.subprocess,'run',command)
    assert r.published_lock(out)==receipt


def test_cached_ledgers_cannot_change_after_initial_seal_verification(executed,monkeypatch):
    cache,metrics,out,phase,fp,*_=executed;original=r.verify_completed
    def alter(*args,**kwargs):
        score=original(*args,**kwargs)
        path=out/'trials'/phase[0]/'fills.csv';path.write_bytes(path.read_bytes()+b' ')
        return score
    monkeypatch.setattr(r,'verify_completed',alter)
    with pytest.raises(RuntimeError,match='Cached phase packet changed'):
        r.run_phase(cache,metrics,out,phase,feature_audit=fp)
