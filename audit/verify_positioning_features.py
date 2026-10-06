"""Independent assumed-availability positioning reconstruction; no model imports.

Minute indexing and division below are independently authored. The sole helper
is the earlier independent raw ZIP dataset verifier, never a collector, Engine,
feature builder or runner. No historical files are read on import.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import numpy as np
import pandas as pd
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from audit import verify_positioning_dataset as dataset_reference

START=pd.Timestamp('2025-10-05',tz='UTC');END=pd.Timestamp('2026-10-05',tz='UTC')
SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','1000PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
DELAYS={'baseline':6,'delayed':11};PREREG='docs/positioning_preregistration'
FAMILY='confirmed_native_position_unwind_rebound';AUDITOR='audit/verify_positioning_features.py'
COLUMNS=['price_source_label','price_available_at','price','price_return_1h','price_return_15m',
 'metric_source_label','metric_available_at','native_open_interest','quantity_change_1h','quantity_change_5m',
 'metric_age_seconds','valid','instrument_id']
ASSUMPTIONS={
 'metric_label_timezone':'UTC interpretation of offset-free archive labels',
 'metric_information_period':'unverified; assume label plus a full five-minute interval',
 'metric_availability':'label + fixed delay, strictly before decision; delay is an assumption',
 'price_availability':'minute start + two minutes, at or before decision',
 'quantity_units':'within-native dimensionless change; constant unit scaling cancels',
 'vintage':'current downloaded archives, not verified historical delivery or original vintage',
 'economic_claim':'position-unwind proxy; no observed liquidation or return guarantee'}


def require(ok,message):
    if not ok:raise AssertionError(message)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def regular(path):
    path=Path(path)
    return path.is_file() and not path.is_symlink() and not any(p.is_symlink() for p in path.absolute().parents)


def read(path):return json.loads(Path(path).read_bytes())
def iid(symbol):return 'binance:perpetual:'+symbol

def attributes(delay,start=START,end=END):return dict(ASSUMPTIONS,metric_delay_minutes=delay,start=start.isoformat(),end=end.isoformat())

def source_values(frame,native,grid,key):
    require({'timestamp','instrument_id',key}<=set(frame),'Missing native source fields')
    clock=pd.DatetimeIndex(frame.timestamp)
    require(clock.tz is not None and not clock.hasnans and clock.tz_convert('UTC').as_unit('ns').equals(grid),'Exact in-year source grid required')
    require(frame.instrument_id.eq(native).all(),'Wrong native source identity')
    require(pd.api.types.is_numeric_dtype(frame[key].dtype) and not pd.api.types.is_bool_dtype(frame[key].dtype),'Numeric nonboolean source required')
    values=frame[key].to_numpy(dtype=float)
    require(np.isfinite(values).all() and (values>0).all(),'Nonpositive/nonfinite source')
    return values


def ratios(values,lookback):
    """Independent completed-source lookback; overflow becomes missing."""
    out=np.full(len(values),np.nan)
    with np.errstate(over='ignore',divide='ignore',invalid='ignore'):
        out[lookback:]=values[lookback:]/values[:-lookback]-1
    out[~np.isfinite(out)]=np.nan
    return out


def reference_frame(bars,metrics,native,delay,start=START,end=END):
    require(native in {iid(s) for s in SYMBOLS} and type(delay) is int and delay in (6,11),'Fixed native/delay contract required')
    require(start.tzinfo is not None and end.tzinfo is not None and end>start and start==start.floor('5min') and end==end.floor('5min'),'Aware five-minute bounds required')
    minutes=pd.date_range(start,end,freq='min',inclusive='left').as_unit('ns')
    polls=minutes[::5];prices=source_values(bars,native,minutes,'close');quantity=source_values(metrics,native,polls,'sum_open_interest')
    require('duration_seconds' in bars and bars.duration_seconds.eq(60).all(),'Actual one-minute bars required')
    require(not {'historical_receipt','available_at','assumed_available_at'}&set(metrics),'Assumed-only source contract cannot ignore receipt fields')
    # For decision minute n, usable source k satisfies 5*k+delay<n. No asof join or builder helper.
    n=np.arange(2,len(minutes),dtype=np.int64);k=(n-delay-1)//5;exists=k>=0
    labels_ns=np.full(len(n),pd.NaT.value,dtype=np.int64)
    labels_ns[exists]=polls.asi8[k[exists]]
    available_ns=labels_ns.copy();available_ns[exists]+=delay*60*1_000_000_000
    selected_quantity=np.full(len(n),np.nan);selected_quantity[exists]=quantity[k[exists]]
    age=np.full(len(n),np.nan);age[exists]=(minutes.asi8[n[exists]]-available_ns[exists])/1e9
    qh=ratios(quantity,12);q5=ratios(quantity,1)
    changes_h=np.full(len(n),np.nan);changes_5=np.full(len(n),np.nan)
    changes_h[exists]=qh[k[exists]];changes_5[exists]=q5[k[exists]]
    ph=ratios(prices,60)[n-2];p15=ratios(prices,15)[n-2]
    valid=np.isfinite(ph)&np.isfinite(p15)&np.isfinite(changes_h)&np.isfinite(changes_5)&(age>0)&(age<=300)
    frame=pd.DataFrame(dict(price_source_label=minutes[n-2],price_available_at=minutes[n],price=prices[n-2],
        price_return_1h=ph,price_return_15m=p15,metric_source_label=pd.to_datetime(labels_ns,utc=True),
        metric_available_at=pd.to_datetime(available_ns,utc=True),native_open_interest=selected_quantity,
        quantity_change_1h=changes_h,quantity_change_5m=changes_5,metric_age_seconds=age,valid=valid,instrument_id=native),index=minutes[n])
    frame.index.name='timestamp';frame.attrs=attributes(delay,start,end)
    return frame


def verify_stream(actual,bars,metrics,native,delay,start=START,end=END):
    expected=reference_frame(bars,metrics,native,delay,start,end)
    require(list(actual)==COLUMNS and actual.index.name=='timestamp','Exact feature schema/index required')
    clock=pd.DatetimeIndex(actual.index)
    require(clock.tz is not None and str(clock.tz)=='UTC' and clock.as_unit('ns').equals(expected.index),'Exact UTC minute feature index required')
    require(actual.attrs==expected.attrs,'Resealed availability/unit/vintage assumptions differ')
    require(actual.instrument_id.eq(native).all() and pd.api.types.is_bool_dtype(actual.valid.dtype) and not actual.valid.isna().any(),'Native/Boolean validity differs')
    maximum=0.
    for name in COLUMNS:
        if name=='instrument_id':continue
        if name=='valid':require(np.array_equal(actual[name].to_numpy(),expected[name].to_numpy()),'Independent valid flags differ');continue
        if name.endswith('_label') or name.endswith('_at'):
            require(isinstance(actual[name].dtype,pd.DatetimeTZDtype) and str(actual[name].dt.tz)=='UTC','Naive/nonUTC source clock: '+name)
            require(np.array_equal(pd.DatetimeIndex(actual[name]).as_unit('ns').asi8,pd.DatetimeIndex(expected[name]).asi8),'Independent source/availability clocks differ: '+name);continue
        require(pd.api.types.is_numeric_dtype(actual[name].dtype) and not pd.api.types.is_bool_dtype(actual[name].dtype),'Feature numeric dtype differs: '+name)
        a=actual[name].to_numpy(dtype=float);b=expected[name].to_numpy(dtype=float)
        require(np.array_equal(a,b,equal_nan=True),'Independent exact numeric reconstruction differs: '+name)
        finite=np.isfinite(b)
        if finite.any():maximum=max(maximum,float(np.max(np.abs(a[finite]-b[finite]))))
    return dict(native_id=native,delay_minutes=delay,rows=len(actual),valid_rows=int(expected.valid.sum()),
                source_price_rows=len(bars),source_metric_rows=len(metrics),numeric_fields_checked=7*len(actual),maximum_absolute_error=maximum,
                full_reconstruction=True)


def git_bytes(commit,name):
    require(isinstance(commit,str) and bool(re.fullmatch('[a-f0-9]{40}',commit)),'Full Git anchor required')
    return subprocess.run(['git','show',f'{commit}:{name}'],cwd=REPO,capture_output=True,check=True).stdout


def ancestors(commit,target):return subprocess.run(['git','merge-base','--is-ancestor',commit,target],cwd=REPO,capture_output=True).returncode==0

def expected_sources(commit):
    tree=subprocess.run(['git','ls-tree','-r','--name-only',commit,'aster'],cwd=REPO,capture_output=True,check=True).stdout.decode().splitlines()
    explicit=['examples/'+folder+'/'+n for folder in ('positioning_research','funding_rank') for n in ('run.py','signals.py','strategy.py','proposed_protocol.md')]
    explicit+=['examples/cross_venue/signals.py','examples/minute_research/download.py','examples/minute_research/downloadcarry.py',
        'examples/positioning/collect_archives.py','audit/verify_positioning_dataset.py','docs/positioning_economic_research.md']
    return set(n for n in tree if n.endswith('.py'))|set(explicit)


def input_paths(perp,metrics):
    paths={Path(perp)/n for n in ('instruments.json','cross_mapping.json','instrument_source_manifest.json','exchange_info_current.json')}
    for native in SYMBOLS:
        symbol='PEPEUSDT' if native=='1000PEPEUSDT' else native;folder=Path(perp)/symbol
        paths.update(folder/n for n in ('bars.parquet','funding.parquet','source_manifest.json'))
        manifest=read(folder/'source_manifest.json')
        for page in manifest['archives']+manifest['funding_pages']:
            raw=Path(page['cache_file']);raw=raw if raw.is_absolute() else REPO/raw
            paths.add(raw)
    require(all(regular(p) for p in paths),'Missing/symlink perpetual source')
    metric_paths=set()
    require(Path(metrics).is_dir() and not Path(metrics).is_symlink(),'Regular metrics root required')
    for p in Path(metrics).rglob('*'):
        require(not p.is_symlink(),'Metrics source symlink unsupported')
        if p.is_file():metric_paths.add(p)
    return {str(p.resolve()):sha(p) for p in paths},{str(p.resolve()):sha(p) for p in metric_paths}


def verify_provenance(out,perp,metrics,source_anchor,input_anchor):
    out=Path(out)
    for name in ('source_lock.json','input_verification.json'):
        anchored=git_bytes(input_anchor,PREREG+'/'+name)
        require(regular(out/name) and (out/name).read_bytes()==anchored and regular(REPO/PREREG/name) and (REPO/PREREG/name).read_bytes()==anchored,'Published/current Git input packet differs: '+name)
    prereg_bytes=git_bytes(input_anchor,PREREG+'/preregistration.json');prereg=json.loads(prereg_bytes)
    require((REPO/PREREG/'preregistration.json').read_bytes()==prereg_bytes,'Current preregistration changed')
    lock=read(out/'source_lock.json');verification=read(out/'input_verification.json');published=read(out/'published_lock.json')
    require(published.get('remote_commit')==input_anchor and published.get('commit_path')==PREREG
            and published.get('historical_features_exist') is False and published.get('trials_exist') is False,'Published lock origin differs')
    require(ancestors(source_anchor,input_anchor) and ancestors(input_anchor,'origin/main'),'Source/input publication ancestry missing')
    for n,key in [('source_lock.json','source_lock_sha256'),('input_verification.json','input_verification_sha256')]:
        require(published.get(key)==sha(out/n) and prereg.get(key)==sha(out/n),'Published/preregistered digest differs')
    require(prereg.get('source_commit')==source_anchor and prereg.get('proposed_candidate_number')==28
            and prereg.get('historical_features_exist') is False and prereg.get('trial_directory_exists') is False,'Pre-outcome preregistration claims differ')
    require(set(lock['sources'])==expected_sources(source_anchor),'Transitive source namespace differs')
    archive=out/'executed_source'
    require(archive.is_dir() and not archive.is_symlink(),'Regular executed source root required')
    archived=set()
    for path in archive.rglob('*'):
        require(not path.is_symlink(),'Executed source symlink unsupported')
        if path.is_file():archived.add(path.relative_to(archive).as_posix())
    require(archived==set(lock['sources']),'Exact archived source namespace differs')
    for name,digest in lock['sources'].items():
        require(hashlib.sha256(git_bytes(source_anchor,name)).hexdigest()==digest,'Source Git anchor differs: '+name)
        require(regular(REPO/name) and regular(out/'executed_source'/name) and sha(REPO/name)==digest and sha(out/'executed_source'/name)==digest,'Source/archive drift: '+name)
    expected_perp,expected_metrics=input_paths(perp,metrics)
    require(lock['perpetual_inputs']==expected_perp and lock['metrics_inputs']==expected_metrics,'Exact raw/normalized input map differs')
    versions={'python':sys.version,**{n:importlib.metadata.version(n) for n in ('numpy','pandas','pyarrow','scipy','plotly')}}
    require(lock['runtime']==versions,'Runtime drift')
    phases=[(f'validation{k+1}',pd.Timestamp('2026-04-05',tz='UTC')+pd.DateOffset(months=k),pd.Timestamp('2026-04-05',tz='UTC')+pd.DateOffset(months=k+1),False) for k in range(3)]+[('evaluation',pd.Timestamp('2026-07-05',tz='UTC'),END,False),('evaluation_stress',pd.Timestamp('2026-07-05',tz='UTC'),END,True)]
    require(lock['family']==FAMILY and lock['candidate_count_cumulative']==28 and lock['phases']==[[n,str(b),str(e),x] for n,b,e,x in phases],'Candidate/phases drift')
    require(lock['input_verification']==verification and len(verification['perpetual'])==8
            and {x['spot_symbol'] for x in verification['perpetual']}=={('PEPEUSDT' if n=='1000PEPEUSDT' else n) for n in SYMBOLS},'Full universe input verification differs')
    cert_path=REPO/'audit/positioning_dataset_evidence.json';cert=read(cert_path)
    require(cert_path.read_bytes()==git_bytes(source_anchor,'audit/positioning_dataset_evidence.json'),'Independent dataset evidence differs from source anchor')
    require(lock['dataset_certificate_path']==str(cert_path.resolve()) and lock['dataset_certificate_sha256']==sha(cert_path)
            and verification['positioning_dataset_certificate']==cert,'Dataset evidence identity differs')
    require(cert.get('complete') is True and cert.get('errors')==[] and cert.get('source_anchor')==dataset_reference.SOURCE_ANCHOR,'Dataset certificate incomplete/wrong acquisition')
    for k in ('source_unchanged_during_audit','auditor_source_unchanged','exact_normalization_reconstruction_passed','source_and_runtime_reconstruction_passed','evidence_unchanged_during_audit'):
        require(cert.get(k) is True,'Dataset proof missing: '+k)
    require(cert['auditor_sha256']==sha(dataset_reference.__file__) and cert['collector_sha256']==sha(REPO/'examples/positioning/collect_archives.py')
            and cert['complete_seal_sha256']==sha(Path(metrics)/'complete.json')==verification['positioning_complete_seal_sha256'],'Dataset source/seal proof changed')
    require(cert['raw_archive_count']==2920 and cert['raw_source_files_checked']==8760 and cert['normalized_source_file_count']==18,'Dataset proof not full year')
    require(prereg.get('source_files')==len(lock['sources']) and prereg.get('perpetual_input_files')==len(expected_perp) and prereg.get('metrics_input_files')==len(expected_metrics),'Preregistration packet counts differ')
    return lock


def feature_hashes(out):
    root=Path(out)/'features';require(root.is_dir() and not root.is_symlink(),'Missing/invalid feature directory')
    require({p.name for p in root.iterdir()}==set(DELAYS),'Exactly two feature variants required')
    hashes={}
    for v in DELAYS:
        group=root/v;require(group.is_dir() and not group.is_symlink(),'Feature variant must be a regular directory')
        require({p.name for p in group.iterdir()}=={n+'.parquet' for n in SYMBOLS},'Exactly eight native feature files required')
        require(all(p.is_file() and not p.is_symlink() for p in group.iterdir()),'Feature symlink/nonfile unsupported')
        hashes[v]={iid(n):sha(group/(n+'.parquet')) for n in SYMBOLS}
    return hashes


def verify(out,perp,metrics,source_anchor,input_anchor):
    out,perp,metrics=map(Path,(out,perp,metrics));own=sha(__file__);helper=sha(dataset_reference.__file__)
    packet={n:sha(out/n) for n in ('source_lock.json','input_verification.json','published_lock.json','feature_receipt.json')}
    hashes=feature_hashes(out)
    lock=verify_provenance(out,perp,metrics,source_anchor,input_anchor)
    require({n:sha(out/n) for n in packet}==packet and feature_hashes(out)==hashes,'Packet/features changed during initial provenance validation')
    receipt=read(out/'feature_receipt.json')
    require(receipt==dict(source_lock_sha256=packet['source_lock.json'],features_sha256=hashes,rows_per_stream=525598,
        columns=COLUMNS,availability_assumptions={v:attributes(d) for v,d in DELAYS.items()}),'Exact feature receipt differs')
    # Reparse every original metrics ZIP/CSV/checksum independently, not via the collector.
    raw_proof=dataset_reference.verify_dataset(metrics)
    require(raw_proof['complete_seal_sha256']==lock['input_verification']['positioning_complete_seal_sha256'],'Raw dataset reconstruction differs')
    checks=[]
    for n in SYMBOLS:
        symbol='PEPEUSDT' if n=='1000PEPEUSDT' else n
        bars=pd.read_parquet(perp/symbol/'bars.parquet',columns=['timestamp','instrument_id','duration_seconds','close'])
        observations=pd.read_parquet(metrics/n/'observations.parquet')
        for v,d in DELAYS.items():
            actual=pd.read_parquet(out/'features'/v/(n+'.parquet'))
            checks.append(verify_stream(actual,bars,observations,iid(n),d))
        del bars,observations,actual
    require(verify_provenance(out,perp,metrics,source_anchor,input_anchor)==lock,'Source/input/runtime changed during audit')
    require({n:sha(out/n) for n in packet}==packet and feature_hashes(out)==hashes,'Feature/receipt/lock changed during audit')
    require(sha(__file__)==own and sha(dataset_reference.__file__)==helper,'Auditor/helper changed during audit')
    completed=datetime.now(timezone.utc)
    require(pd.Timestamp(completed)>=pd.Timestamp((out/'feature_receipt.json').stat().st_mtime,unit='s',tz='UTC'),'Audit predates feature receipt creation')
    return dict(complete=True,errors=[],source_anchor=source_anchor,input_anchor=input_anchor,
        source_lock_sha256=packet['source_lock.json'],feature_receipt_sha256=packet['feature_receipt.json'],features_sha256=hashes,
        published_lock_sha256=packet['published_lock.json'],input_verification_sha256=packet['input_verification.json'],
        source_unchanged_during_audit=True,input_unchanged_during_audit=True,features_unchanged_during_audit=True,auditor_source_unchanged=True,
        scope=dict(native_stream_count=8,delays_minutes=[6,11],begin=START.isoformat(),end=END.isoformat(),full_reconstruction=True),
        auditor_path=AUDITOR,auditor_sha256=own,raw_dataset_helper_sha256=helper,completed_at_utc=completed.isoformat(),checks=checks,
        raw_archives_reparsed=raw_proof['raw_archive_count'],raw_source_files_checked=raw_proof['raw_source_files_checked'],
        dataset_certificate_sha256=lock['dataset_certificate_sha256'],historical_delivery_verified=False,historical_units_verified=False,
        limitations=['Exact reproduction is conditional on fixed assumed availability, not original historical receipts/vintages.',
            'Constant native scaling cancels; historical unit-definition breaks remain unverified.',
            'No strategy, economic forecast, profitability, liquidation attribution or untouched validation is certified.'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-anchor',required=True);p.add_argument('--input-anchor',required=True)
    p.add_argument('--out',type=Path,default=Path('results/positioning-rebound-1y-v1'))
    p.add_argument('--perp-cache',type=Path,default=Path('data_cache/minute-perpetual-1y'));p.add_argument('--metrics-cache',type=Path,default=Path('data_cache/positioning-metrics-1y'))
    p.add_argument('--certificate',type=Path,default=Path('audit/positioning_feature_evidence.json'));a=p.parse_args()
    require(not a.certificate.exists(),'Preserve prior certificate; fresh path required')
    result=verify(a.out,a.perp_cache,a.metrics_cache,a.source_anchor,a.input_anchor)
    a.certificate.parent.mkdir(parents=True,exist_ok=True)
    with a.certificate.open('x') as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps(dict(complete=result['complete'],streams=len(result['checks']),rows_checked=sum(c['rows'] for c in result['checks']),auditor_sha256=result['auditor_sha256'])))

if __name__=='__main__':main()
