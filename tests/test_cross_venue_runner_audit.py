"""Prospective runner audit, synthetic artifacts only; no historical feature calls."""
import copy
from dataclasses import asdict
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from examples.cross_venue import run as r
from aster.backtest.portfolio import Portfolio
from test_cross_venue_runner import specs


@pytest.fixture
def frozen(tmp_path,monkeypatch):
    repo=tmp_path/'repo';bybit=tmp_path/'bybit';out=tmp_path/'out'
    sources=['examples/cross_venue/run.py','aster/backtest/portfolio.py']
    for name in sources:
        path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('original '+name)
    bybit.mkdir();(bybit/'dataset_seal.json').write_text('{}')
    data=tmp_path/'input.raw';data.write_text('actual raw fixture')
    runtime={'numpy':'synthetic-runtime'}
    def identity(*args):return {'sources':{name:r.digest(repo/name) for name in sources},
        'inputs':{str(data):r.digest(data)},'runtime':dict(runtime),'family':r.FAMILY,
        'phases':[[name,str(a),str(b),stress,v] for name,a,b,stress,v in r.PHASES]}
    monkeypatch.setattr(r,'REPO',repo);monkeypatch.setattr(r,'identity',identity)
    monkeypatch.setattr(r,'catalog',lambda *a:specs())
    calls=[]
    monkeypatch.setattr(r,'verify_binance',lambda root,symbol,catalog:{'symbol':symbol,'verified':True})
    monkeypatch.setattr(r.download_bybit,'run',lambda *a,**k:calls.append(k))
    r.freeze(tmp_path/'binance',bybit,out)
    assert calls==[{'workers':2,'verify_only':True}]
    return repo,data,runtime,bybit,out


@pytest.mark.parametrize('what',['source','input','runtime','archive','receipt'])
def test_guard_rejects_frozen_source_input_runtime_archive_and_receipt_drift(frozen,what):
    repo,data,runtime,bybit,out=frozen
    if what=='source':(repo/'examples/cross_venue/run.py').write_text('changed')
    elif what=='input':data.write_text('changed')
    elif what=='runtime':runtime['numpy']='changed'
    elif what=='archive':(out/'executed_source/examples/cross_venue/run.py').write_text('changed')
    else:r.dump(out/'input_verification.json',{'binance':[]})
    with pytest.raises(RuntimeError):r.guard('binance',bybit,out)


def test_freeze_archives_relative_sources_and_refuses_unsealed_nonempty(tmp_path,frozen):
    repo,data,runtime,bybit,out=frozen
    lock=r.guard('binance',bybit,out)
    assert all(not r.Path(name).is_absolute() and '..' not in r.Path(name).parts for name in lock['sources'])
    for name in lock['sources']:
        assert (out/'executed_source'/name).read_bytes()==(repo/name).read_bytes()
    rejected=tmp_path/'unsealed';rejected.mkdir();(rejected/'marker').write_text('preserve')
    with pytest.raises(RuntimeError):r.freeze('binance',bybit,rejected)
    assert (rejected/'marker').read_text()=='preserve'


def test_generate_features_guard_runs_before_any_source_or_builder(tmp_path,monkeypatch):
    def forbidden(*a,**k):raise AssertionError('Feature/data access before guard')
    monkeypatch.setattr(r.pd,'read_parquet',forbidden);monkeypatch.setattr(r,'build_features',forbidden)
    with pytest.raises(RuntimeError,match='Freeze'):
        r.generate_features('binance','bybit',tmp_path)


def test_generate_features_preserves_explicit_delayed_receipt(tmp_path,monkeypatch):
    r.dump(tmp_path/'source_lock.json',{})
    monkeypatch.setattr(r,'guard',lambda *a:{})
    stamp=r.START+pd.Timedelta(hours=8);receipt=stamp+pd.Timedelta(hours=4)
    def parquet(path,columns=None):
        path=r.Path(path);venue=path.parts[0];label=path.parts[1];iid=r.native_id(venue,label)
        if path.name=='bars.parquet':frame=pd.DataFrame({'timestamp':[r.START],'duration_seconds':[60],'instrument_id':[iid],'close':[100.]})
        else:frame=pd.DataFrame({'timestamp':[stamp],'instrument_id':[iid],'funding_rate':[.001],
                                 'historical_receipt':[receipt]})
        return frame if columns is None else frame[columns]
    monkeypatch.setattr(r.pd,'read_parquet',parquet)
    def build(bars,funding):
        assert len(funding)==16
        assert all('historical_receipt' in f and f.historical_receipt.iloc[0]==receipt for f in funding.values()),'Runner discarded actual receipt'
        return pd.DataFrame({'fixture':[1]},index=pd.DatetimeIndex([receipt]))
    monkeypatch.setattr(r,'build_features',build)
    monkeypatch.setattr(r,'verified_features',lambda out:None)
    r.generate_features('binance','bybit',tmp_path)


@pytest.mark.parametrize('unit',['ms','us','ns'])
def test_bootstrap_endpoint_precision_and_26_comparison_quantiles(unit):
    clock=pd.date_range(r.EVAL_START,periods=20,freq='D').as_unit(unit)
    daily=np.array([.002,-.001,.004,-.003,.001,.002,-.001,.003,-.004,.002,.003,-.001,.002,-.002,.001,.002,-.001,.003,.002])
    equity=100000*np.r_[1,np.cumprod(1+daily)]
    frame=pd.DataFrame({'timestamp':clock,'equity':equity})
    original=frame.copy();actual=r.conditional_interval(frame)
    # Exclusive midnight endpoint belongs to preceding day: final daily equity replaces priorclose.
    expected_daily=np.r_[daily[:-2],(1+daily[-2])*(1+daily[-1])-1]
    rng=np.random.default_rng(42);n=len(expected_daily)
    starts=rng.integers(0,n,size=(10000,(n+6)//7))
    sample=((starts[:,:,None]+np.arange(7))%n).reshape(10000,-1)[:,:n]
    totals=np.prod(1+expected_daily[sample],axis=1)-1
    assert actual['comparison_count']==26
    assert actual['return_interval_bonferroni26']==pytest.approx(np.quantile(totals,[.05/52,1-.05/52]),abs=1e-12)
    pd.testing.assert_frame_equal(frame,original)


def test_observer_is_pure_once_and_exposes_same_direction_unmatched_native():
    p=Portfolio(specs(),r.config(False));b=r.native_id('binance','PEPEUSDT');y=r.native_id('bybit','PEPEUSDT')
    for iid,q,mark in [(b,3,12),(y,2,11)]:
        p.positions[iid].quantity=q;p.positions[iid].average_price=10;p.positions[iid].collateral=10*q;p.marks[iid]=mark
    baseline=p.snapshot;calls=[]
    def original(t):calls.append(t);return baseline(t)
    p.snapshot=original;observer=r.SnapshotObserver(p)
    state=copy.deepcopy((p.cash,p.positions,p.events));time=r.VALID_START
    returned=observer(time)
    assert calls==[time] and returned==baseline(time)
    assert (p.cash,p.positions,p.events)==state
    row=observer.rows[0]
    assert row['matched_native_PEPEUSDT']==0 and row['unmatched_native_PEPEUSDT']==5
    assert row['unmatched_dollars_PEPEUSDT']==58
    assert row['binance_margin_used']==36 and row['entry_collateral_field_binance_PEPEUSDT']==30


def test_alternative_subminute_and_end_marks_never_use_future_close():
    grid=pd.date_range(r.START,periods=3,freq='min')
    bars=pd.DataFrame({'end':grid+pd.Timedelta(minutes=1),'mark_price':[10,20,30]})
    facts=pd.DataFrame({'timestamp':[grid[1],grid[1]+pd.Timedelta(milliseconds=999),grid[2]+pd.Timedelta(minutes=1)],'mark_price':[999]*3})
    actual=r.alternative_funding(facts,bars)
    assert actual.mark_price.tolist()==[10,10,30]
    assert facts.mark_price.tolist()==[999]*3


def test_exact_phases_sourcehelper_hashes_and_raw_receipts_pinned(tmp_path,monkeypatch):
    binance=tmp_path/'binance';bybit=tmp_path/'bybit'
    def read(path):
        if str(path).startswith(str(binance)):
            return {'archives':[{'cache_file':'official-archive'}],'funding_pages':[{'cache_file':'official-funding'}]}
        return {'raw_pages':[{'cache_file':'raw/actual-envelope.json'}]}
    monkeypatch.setattr(r,'read',read);monkeypatch.setattr(r,'digest',lambda path:'fixture-hash')
    monkeypatch.setattr(r,'cached_path',lambda value:tmp_path/value)
    lock=r.identity(binance,bybit)
    for name in ['examples/residual_convergence/run.py','examples/residual_convergence/signals.py',
                 'examples/residual_convergence/strategy.py','examples/minute_research/downloadcarry.py',
                 'examples/minute_research/download.py','examples/cross_venue/signals.py','aster/backtest/portfolio.py']:
        assert name in lock['sources']
    assert str((tmp_path/'official-archive').resolve()) in lock['inputs']
    assert str((tmp_path/'official-funding').resolve()) in lock['inputs']
    assert str((bybit/'raw/actual-envelope.json').resolve()) in lock['inputs']
    assert str((bybit/'dataset_seal.json').resolve()) in lock['inputs']
    assert len(lock['phases'])==7 and lock['candidate_count_cumulative']==26


@pytest.fixture
def cached(frozen):
    repo,data,runtime,bybit,out=frozen;phase=r.PHASES[0]
    frame=pd.DataFrame({'fixture':[1.]},index=pd.DatetimeIndex([phase[1]]));frame.to_parquet(out/'features.parquet')
    r.dump(out/'feature_receipt.json',{'source_lock_sha256':r.digest(out/'source_lock.json'),
        'features_sha256':r.digest(out/'features.parquet'),'availability_assumptions':{},'rows':1,'columns':['fixture']})
    path=out/'trials'/phase[0];path.mkdir(parents=True)
    for name in r.OUTPUTS:(path/name).write_bytes(b'synthetic execution fixture')
    lock=r.read(out/'source_lock.json')
    manifest={'source_lock':lock,'valuation':phase[4],
        'funding_boundary':'actual sourced begin<=timestamp<=stop; Bybit mark valuation explicitly approximate'}
    meta={'parameters':r.parameters(out,phase),'engine':asdict(r.config(phase[3])),
        'instruments':[asdict(x) for x in specs()],'strategy':'CrossVenueCarry','strategy_version':r.CrossVenueCarry.version,
        'source_sha256':{name.removeprefix('aster/'):sha for name,sha in lock['sources'].items() if name.startswith('aster/')},
        'source_manifest':manifest,'start':str(phase[1]),'end':str(phase[2])}
    r.dump(path/'metadata.json',meta);r.dump(path/'metrics.json',{'synthetic':True})
    r.dump(path/'source_manifest.json',manifest)
    r.dump(path/'completion.json',{'parameters':r.parameters(out,phase),'outputs_sha256':r.output_files(path)})
    return bybit,out,phase,path


@pytest.mark.parametrize('what',['strategy','version','core_hash','manifest'])
def test_resealed_cache_metadata_must_match_frozen_execution_provenance(cached,what):
    bybit,out,phase,path=cached
    assert r.verify_completed('binance',bybit,out,phase)=={'synthetic':True}
    meta=r.read(path/'metadata.json')
    if what=='strategy':meta['strategy']='DifferentCoordinator'
    elif what=='version':meta['strategy_version']='future-retuned'
    elif what=='core_hash':meta['source_sha256']={key:'0'*64 for key in meta['source_sha256']}
    else:meta['source_manifest']['source_lock']['family']='another-family'
    r.dump(path/'metadata.json',meta)
    seal=r.read(path/'completion.json');seal['outputs_sha256']=r.output_files(path);r.dump(path/'completion.json',seal)
    with pytest.raises(RuntimeError):r.verify_completed('binance',bybit,out,phase)


@pytest.mark.parametrize('what',['changed','missing'])
def test_cache_execution_outputs_changed_or_incomplete_fail_closed(cached,what):
    bybit,out,phase,path=cached
    if what=='changed':(path/'fills.parquet').write_bytes(b'changed execution')
    else:(path/'exposure.parquet').unlink()
    with pytest.raises((RuntimeError,FileNotFoundError)):
        r.verify_completed('binance',bybit,out,phase)


def test_seven_phases_have_fixed_disjoint_validation_and_stressed_sensitivities():
    expected=[('validation1','2026-04-05','2026-05-05',False,'primary'),
              ('validation2','2026-05-05','2026-06-05',False,'primary'),
              ('validation3','2026-06-05','2026-07-05',False,'primary'),
              ('evaluation','2026-07-05','2026-10-05',False,'primary'),
              ('evaluation_stress','2026-07-05','2026-10-05',True,'primary'),
              ('evaluation_alternative','2026-07-05','2026-10-05',False,'alternative'),
              ('evaluation_alternative_stress','2026-07-05','2026-10-05',True,'alternative')]
    assert [(n,str(a.date()),str(b.date()),stress,v) for n,a,b,stress,v in r.PHASES]==expected
    assert len(r.OUTPUTS)==25 and len(set(r.OUTPUTS))==25


def test_summary_refuses_hidden_or_missing_phase_before_metrics(tmp_path,monkeypatch):
    monkeypatch.setattr(r,'guard',lambda *a:{})
    monkeypatch.setattr(r,'verified_features',lambda *a:pd.DataFrame())
    monkeypatch.setattr(r,'verify_completed',lambda *a:pytest.fail('Incomplete cohort reached metrics'))
    trials=tmp_path/'trials';trials.mkdir()
    for p in r.PHASES:(trials/p[0]).mkdir()
    (trials/'hidden_variant').mkdir()
    with pytest.raises(RuntimeError,match='seven exact'):r.summarize('b','y',tmp_path)
    (trials/'hidden_variant').rmdir();(trials/r.PHASES[0][0]).rmdir()
    with pytest.raises(RuntimeError,match='seven exact'):r.summarize('b','y',tmp_path)
