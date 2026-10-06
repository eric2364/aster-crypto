"""Independent reconstruction adversaries; synthetic inputs only, no real cache."""
import ast
from pathlib import Path
import pandas as pd
import numpy as np
import pytest
from audit import verify_positioning_features as a
from examples.positioning_research.signals import build_features

START=pd.Timestamp('2026-04-05',tz='UTC');END=START+pd.Timedelta(hours=2)


def sources(native='1000PEPEUSDT'):
    identity=a.iid(native);clock=pd.date_range(START,END,freq='min',inclusive='left')
    bars=pd.DataFrame({'timestamp':clock,'instrument_id':identity,'duration_seconds':60,'close':100.+np.arange(120)})
    metric=pd.date_range(START,END,freq='5min',inclusive='left')
    metrics=pd.DataFrame({'timestamp':metric,'instrument_id':identity,'sum_open_interest':1000.+np.arange(24)})
    return bars,metrics,identity


def frame(delay=6):
    bars,metrics,native=sources()
    actual=build_features(bars,metrics,instrument_id=native,start=START,end=END,metric_delay_minutes=delay)
    return actual,bars,metrics,native,delay


def check_stream(data):return a.verify_stream(*data,start=START,end=END)


@pytest.mark.parametrize('delay',[6,11])
def test_known_scalar_boundary_values_and_complete_independent_stream(delay):
    actual,bars,metrics,native,_=data=frame(delay);proof=check_stream(data)
    assert proof['rows']==118 and proof['maximum_absolute_error']==0
    d=START+pd.Timedelta(minutes=61+delay);row=actual.loc[d]
    assert row.metric_source_label==START+pd.Timedelta(minutes=60)
    assert row.metric_available_at==d-pd.Timedelta(minutes=1) and row.metric_age_seconds==60
    assert row.native_open_interest==1012 and row.quantity_change_1h==1012/1000-1
    assert row.quantity_change_5m==1012/1011-1 and row.valid
    assert not actual.loc[d-pd.Timedelta(minutes=1),'valid']
    price=100+59+delay
    assert row.price==price and row.price_return_1h==price/(price-60)-1
    assert row.price_return_15m==price/(price-15)-1


@pytest.mark.parametrize('field',['price','price_return_1h','price_return_15m','native_open_interest',
                                'quantity_change_1h','quantity_change_5m','metric_age_seconds'])
def test_resealed_finite_numeric_forgery_fails_reference_arithmetic(field):
    data=frame();data[0].loc[data[0].index[-1],field]+=1e-8
    with pytest.raises(AssertionError,match='numeric reconstruction'):check_stream(data)


@pytest.mark.parametrize('mode',['valid','early_valid','identity','attrs','metric_equal','price_early','source_label','integer_valid','naive_source'])
def test_resealed_clock_flag_native_and_assumption_forgery_fails(mode):
    data=frame();actual=data[0];last=actual.index[-1]
    if mode=='valid':actual.loc[last,'valid']=False
    elif mode=='early_valid':actual.loc[actual.index[0],'valid']=True
    elif mode=='identity':actual['instrument_id']='binance:perpetual:PEPEUSDT'
    elif mode=='attrs':actual.attrs['metric_delay_minutes']=11
    elif mode=='metric_equal':actual.loc[last,'metric_available_at']=last
    elif mode=='price_early':actual.loc[last,'price_available_at']=last-pd.Timedelta(minutes=1)
    elif mode=='source_label':actual.loc[last,'metric_source_label']-=pd.Timedelta(minutes=5)
    elif mode=='integer_valid':actual['valid']=actual.valid.astype(int)
    else:actual['metric_source_label']=actual.metric_source_label.dt.tz_localize(None)
    with pytest.raises(AssertionError):check_stream(data)


@pytest.mark.parametrize('mode',['missing_price','extra_price','metric_gap','wrong_quantity_native','boolean_quantity','outside_warmup','receipt'])
def test_sources_do_not_silently_fill_reorder_rescale_or_discard_receipts(mode):
    actual,bars,metrics,native,delay=frame()
    if mode=='missing_price':bars=bars.iloc[1:]
    elif mode=='extra_price':bars=pd.concat([bars,bars.tail(1)],ignore_index=True)
    elif mode=='metric_gap':metrics=metrics.drop(index=5)
    elif mode=='wrong_quantity_native':metrics['instrument_id']='binance:perpetual:PEPEUSDT'
    elif mode=='boolean_quantity':metrics['sum_open_interest']=True
    elif mode=='outside_warmup':metrics.loc[0,'timestamp']=START-pd.Timedelta(minutes=5)
    else:metrics['available_at']=metrics.timestamp+pd.Timedelta(minutes=20)
    with pytest.raises(AssertionError):a.verify_stream(actual,bars,metrics,native,delay,START,END)


def test_native_constant_quantity_scaling_cancels_but_value_substitution_does_not():
    actual,bars,metrics,native,delay=frame()
    scaled=metrics.copy();scaled.sum_open_interest*=1000
    expected=a.reference_frame(bars,scaled,native,delay,START,END)
    assert np.array_equal(actual.quantity_change_1h,expected.quantity_change_1h,equal_nan=True)
    altered=metrics.copy();altered.sum_open_interest*=bars.close.iloc[::5].to_numpy()
    with pytest.raises(AssertionError,match='numeric reconstruction'):a.verify_stream(actual,bars,altered,native,delay,START,END)


def test_independent_module_imports_no_production_model_or_data_collector():
    tree=ast.parse(Path(a.__file__).read_text());imports=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):imports.extend(alias.name for alias in node.names)
        elif isinstance(node,ast.ImportFrom):imports.append(node.module or '')
    assert not any(n.startswith(('aster','examples')) for n in imports)


@pytest.fixture
def packet(tmp_path,monkeypatch):
    out=tmp_path/'out';perp=tmp_path/'perp';metrics=tmp_path/'metrics';out.mkdir();perp.mkdir();metrics.mkdir()
    for name in ('source_lock.json','input_verification.json','published_lock.json'): (out/name).write_text('{}\n')
    for native in a.SYMBOLS:
        symbol='PEPEUSDT' if native=='1000PEPEUSDT' else native
        bars,obs,iid=sources(native);bp=perp/symbol/'bars.parquet';bp.parent.mkdir();bars.to_parquet(bp)
        mp=metrics/native/'observations.parquet';mp.parent.mkdir();obs.to_parquet(mp)
        for variant,delay in a.DELAYS.items():
            path=out/'features'/variant/(native+'.parquet');path.parent.mkdir(parents=True,exist_ok=True)
            build_features(bars,obs,instrument_id=iid,start=START,end=END,metric_delay_minutes=delay).to_parquet(path)
    lock={'input_verification':{'positioning_complete_seal_sha256':'synthetic-seal'},'dataset_certificate_sha256':'synthetic-data-certificate'}
    original=a.verify_stream;original_attrs=a.attributes
    monkeypatch.setattr(a,'verify_provenance',lambda *args:lock.copy())
    monkeypatch.setattr(a.dataset_reference,'verify_dataset',lambda *args:{'complete_seal_sha256':'synthetic-seal','raw_archive_count':2920,'raw_source_files_checked':8760})
    monkeypatch.setattr(a,'verify_stream',lambda actual,bars,obs,native,delay:original(actual,bars,obs,native,delay,START,END))
    monkeypatch.setattr(a,'attributes',lambda delay,*bounds:original_attrs(delay,*(bounds or (START,END))))
    receipt={'source_lock_sha256':a.sha(out/'source_lock.json'),'features_sha256':a.feature_hashes(out),
        'rows_per_stream':525598,'columns':a.COLUMNS,'availability_assumptions':{v:original_attrs(d,START,END) for v,d in a.DELAYS.items()}}
    (out/'feature_receipt.json').write_text(__import__('json').dumps(receipt))
    return out,perp,metrics


def verify_packet(packet):return a.verify(*packet,'a'*40,'b'*40)


def test_all_sixteen_streams_execute_independent_numeric_reconstruction(packet):
    result=verify_packet(packet)
    assert result['complete'] and not result['errors'] and len(result['checks'])==16
    assert all(c['full_reconstruction'] and c['rows']==118 for c in result['checks'])
    assert result['historical_delivery_verified'] is False and result['historical_units_verified'] is False


@pytest.mark.parametrize('kind',['missing','extra_variant','extra_native','symlink'])
def test_feature_namespace_rejected_before_arbitrary_reads(packet,tmp_path,kind):
    out,_,_=packet;folder=out/'features/baseline';path=folder/'BTCUSDT.parquet'
    if kind=='missing':path.unlink()
    elif kind=='extra_variant':(out/'features/outcome_selected').mkdir()
    elif kind=='extra_native':(folder/'PEPEUSDT.parquet').write_bytes(b'not a parquet')
    else:path.unlink();path.symlink_to(tmp_path/'outside')
    with pytest.raises(AssertionError):verify_packet(packet)


@pytest.mark.parametrize('kind',['source_lock','input_verification','published_lock','feature_receipt','feature','auditor','helper'])
def test_common_features_and_auditor_helpers_cannot_mutate_during_reconstruction(packet,tmp_path,monkeypatch,kind):
    out,_,_=packet;original=a.verify_stream
    if kind in ('auditor','helper'):
        source=tmp_path/(kind+'.py');source.write_text('# synthetic unchanged implementation\n')
        monkeypatch.setattr(a if kind=='auditor' else a.dataset_reference,'__file__',str(source))
    def altered(*args,**kwargs):
        proof=original(*args,**kwargs)
        target=source if kind in ('auditor','helper') else out/'features/baseline/BTCUSDT.parquet' if kind=='feature' else out/(kind+'.json')
        target.write_bytes(target.read_bytes()+b' ')
        return proof
    monkeypatch.setattr(a,'verify_stream',altered)
    with pytest.raises(AssertionError,match='changed'):verify_packet(packet)


def test_certificate_cli_preserves_existing_evidence_before_any_input_access(tmp_path,monkeypatch):
    path=tmp_path/'certificate.json';path.write_text('preserve me')
    monkeypatch.setattr(a.sys,'argv',['auditor','--source-anchor','a'*40,'--input-anchor','b'*40,'--certificate',str(path)])
    calls=[];monkeypatch.setattr(a,'verify',lambda *args:calls.append(args))
    with pytest.raises(AssertionError,match='Preserve prior'):a.main()
    assert not calls and path.read_text()=='preserve me'


def test_publication_receipt_is_pinned_before_initial_provenance_validation(packet,monkeypatch):
    out,_,_=packet;original=a.verify_provenance;calls=[]
    def changed(*args,**kwargs):
        lock=original(*args,**kwargs)
        if not calls:
            path=out/'published_lock.json';value=a.read(path);value['extra']='changed during first provenance check'
            path.write_text(__import__('json').dumps(value))
        calls.append(1)
        return lock
    monkeypatch.setattr(a,'verify_provenance',changed)
    with pytest.raises(AssertionError,match='changed'):verify_packet(packet)


@pytest.fixture
def provenance(tmp_path,monkeypatch):
    import hashlib,importlib.metadata,json,sys
    repo=tmp_path/'repo';out=tmp_path/'out';perp=tmp_path/'perp';metrics=tmp_path/'metrics'
    for p in (repo,out,perp,metrics):p.mkdir()
    source_anchor='c'*40;input_anchor='d'*40;name='examples/positioning_research/run.py'
    source=repo/name;source.parent.mkdir(parents=True);source.write_text('# synthetic reviewed source\n')
    archive=out/'executed_source'/name;archive.parent.mkdir(parents=True);archive.write_bytes(source.read_bytes())
    collector=repo/'examples/positioning/collect_archives.py';collector.parent.mkdir(parents=True);collector.write_text('# synthetic collector\n')
    seal=metrics/'complete.json';seal.write_text('{}')
    raw=perp/'raw.zip';raw.write_bytes(b'unchanged synthetic raw');norm=metrics/'observations.parquet';norm.write_bytes(b'unchanged synthetic normalized')
    flags=('source_unchanged_during_audit','auditor_source_unchanged','exact_normalization_reconstruction_passed','source_and_runtime_reconstruction_passed','evidence_unchanged_during_audit')
    cert={'complete':True,'errors':[],'source_anchor':a.dataset_reference.SOURCE_ANCHOR,
        'auditor_sha256':a.sha(a.dataset_reference.__file__),'collector_sha256':a.sha(collector),'complete_seal_sha256':a.sha(seal),
        'raw_archive_count':2920,'raw_source_files_checked':8760,'normalized_source_file_count':18,**{k:True for k in flags}}
    certpath=repo/'audit/positioning_dataset_evidence.json';certpath.parent.mkdir();certpath.write_text(json.dumps(cert))
    verification={'perpetual':[{'spot_symbol':'PEPEUSDT' if n=='1000PEPEUSDT' else n} for n in a.SYMBOLS],
        'positioning_complete_seal_sha256':a.sha(seal),'positioning_dataset_certificate':cert}
    phases=[(f'validation{k+1}',pd.Timestamp('2026-04-05',tz='UTC')+pd.DateOffset(months=k),pd.Timestamp('2026-04-05',tz='UTC')+pd.DateOffset(months=k+1),False) for k in range(3)]+[('evaluation',pd.Timestamp('2026-07-05',tz='UTC'),a.END,False),('evaluation_stress',pd.Timestamp('2026-07-05',tz='UTC'),a.END,True)]
    lock={'sources':{name:a.sha(source)},'perpetual_inputs':{str(raw.resolve()):a.sha(raw)},'metrics_inputs':{str(norm.resolve()):a.sha(norm)},
        'runtime':{'python':sys.version,**{n:importlib.metadata.version(n) for n in ('numpy','pandas','pyarrow','scipy','plotly')}},
        'family':a.FAMILY,'candidate_count_cumulative':28,'phases':[[n,str(b),str(e),x] for n,b,e,x in phases],
        'input_verification':verification,'dataset_certificate_path':str(certpath.resolve()),'dataset_certificate_sha256':a.sha(certpath)}
    git={(source_anchor,name):source.read_bytes()};preregdir=repo/a.PREREG;preregdir.mkdir(parents=True)
    def reseal():
        lock['input_verification']=verification;lock['dataset_certificate_sha256']=a.sha(certpath)
        for n,value in [('source_lock.json',lock),('input_verification.json',verification)]:
            (out/n).write_text(json.dumps(value));(preregdir/n).write_bytes((out/n).read_bytes());git[(input_anchor,a.PREREG+'/'+n)]=(out/n).read_bytes()
        prereg={'source_commit':source_anchor,'proposed_candidate_number':28,'historical_features_exist':False,'trial_directory_exists':False,
            'source_files':1,'perpetual_input_files':1,'metrics_input_files':1,'source_lock_sha256':a.sha(out/'source_lock.json'),
            'input_verification_sha256':a.sha(out/'input_verification.json')}
        (preregdir/'preregistration.json').write_text(json.dumps(prereg));git[(input_anchor,a.PREREG+'/preregistration.json')]=(preregdir/'preregistration.json').read_bytes()
        published={'remote_commit':input_anchor,'commit_path':a.PREREG,'historical_features_exist':False,'trials_exist':False,
            'source_lock_sha256':prereg['source_lock_sha256'],'input_verification_sha256':prereg['input_verification_sha256']}
        (out/'published_lock.json').write_text(json.dumps(published));git[(source_anchor,'audit/positioning_dataset_evidence.json')]=certpath.read_bytes()
    reseal();monkeypatch.setattr(a,'REPO',repo);monkeypatch.setattr(a,'git_bytes',lambda c,n:git[(c,n)])
    monkeypatch.setattr(a,'ancestors',lambda *args:True);monkeypatch.setattr(a,'expected_sources',lambda *args:{name})
    monkeypatch.setattr(a,'input_paths',lambda *args:({str(raw.resolve()):a.sha(raw)},{str(norm.resolve()):a.sha(norm)}))
    return out,perp,metrics,source_anchor,input_anchor,lock,verification,certpath,reseal,source,raw,norm


def test_provenance_guard_positive_synthetic_committed_packet(provenance):
    assert a.verify_provenance(*provenance[:5])==provenance[5]


@pytest.mark.parametrize('field',['source_unchanged_during_audit','auditor_source_unchanged','exact_normalization_reconstruction_passed','source_and_runtime_reconstruction_passed','evidence_unchanged_during_audit'])
def test_resealed_dataset_certificate_cannot_drop_independent_proof_flags(provenance,field):
    import json
    cert=a.read(provenance[7]);cert[field]=False;provenance[7].write_text(json.dumps(cert))
    provenance[6]['positioning_dataset_certificate']=cert;provenance[8]()
    with pytest.raises(AssertionError,match='Dataset proof missing: '+field):a.verify_provenance(*provenance[:5])


@pytest.mark.parametrize('kind',['source','archive_extra','raw_input','normalized_input','dataset_source','runtime'])
def test_pinned_source_raw_normalized_and_runtime_provenance_cannot_drift(provenance,kind):
    out,perp,metrics,source_anchor,input_anchor,lock,verification,certpath,reseal,source,raw,norm=provenance
    if kind=='source':source.write_bytes(source.read_bytes()+b' ')
    elif kind=='archive_extra':(out/'executed_source'/'secret.py').write_text('unreviewed source')
    elif kind=='raw_input':raw.write_bytes(raw.read_bytes()+b' ')
    elif kind=='normalized_input':norm.write_bytes(norm.read_bytes()+b' ')
    elif kind=='dataset_source':
        import json
        cert=a.read(certpath);cert['collector_sha256']='wrong';certpath.write_text(json.dumps(cert));verification['positioning_dataset_certificate']=cert;reseal()
    else:lock['runtime']['python']='wrong';reseal()
    with pytest.raises(AssertionError):a.verify_provenance(*provenance[:5])
