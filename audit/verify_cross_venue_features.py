"""Standalone causal reconstruction; imports no strategy, signal or runner module.

All reference arithmetic is independent. It reads immutable features only after
an operator explicitly dispatches the verification; never runs Engine or fits.
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import subprocess
import sys
from collections import Counter
import numpy as np
import pandas as pd

REPO=Path(__file__).resolve().parents[1]
ANCHOR='98fe45a55866ccfd1fa5a4e68deb52a127ff7ff2'
INPUT_ANCHOR='1820b8278bfae8a3775fce3b0ee15be8ac2a5448'
START=pd.Timestamp('2025-10-05',tz='UTC')
END=pd.Timestamp('2026-10-05',tz='UTC')
SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
VENUES=('binance','bybit')
HOUR=3600*10**9
MINUTE=60*10**9
WINDOW=168*HOUR
RECEIPT_ASSUMPTIONS={'availability':'trade close at minute end plus one minute; settled rate receipt plus one minute strictly before decision',
    'funding_receipts_assumed':'unless original historical receipt supplied',
    'historical_schedule':'realized intensity proxy, not recovered scheduled accrual','economic_search':False}


def check(ok,message):
    if not ok:raise AssertionError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read(path):return json.loads(Path(path).read_bytes())

def iid(venue,symbol):return venue+':perpetual:'+('1000PEPEUSDT' if symbol=='PEPEUSDT' else symbol)


def clock(value):
    result=pd.Timestamp(value)
    check(not pd.isna(result) and result.tzinfo is not None,'Finite aware clock required')
    return result.tz_convert('UTC')


def funding_sequence(frame,expected_id=None,start=START,end=END):
    """Independent source checks; return sorted settlement/receipt/rate arrays."""
    check({'timestamp','funding_rate','instrument_id'}<=set(frame),'Funding schema missing')
    identity=set(frame.instrument_id)
    allowed={iid(v,s) for v in VENUES for s in SYMBOLS}
    check(len(identity)<=1 and identity<=allowed,'Mixed/unknown native funding identity')
    check(expected_id is None or not identity or identity=={expected_id},'Wrong native funding source')
    events=np.array([clock(t).value for t in frame.timestamp],dtype=np.int64)
    check(len(set(events))==len(events),'Duplicate settlements')
    check(((events>=start.value)&(events<=end.value)).all(),'Outside-year predecessor/event')
    rates=frame.funding_rate.to_numpy(dtype=float)
    check(np.isfinite(rates).all(),'Nonfinite funding rate')
    receipt_name=next((name for name in ('historical_receipt','available_at') if name in frame),None)
    receipt=np.array([clock(t).value for t in frame[receipt_name]],dtype=np.int64) if receipt_name else events.copy()
    check((receipt>=events).all(),'Receipt precedes actual settlement')
    order=np.argsort(events)
    return {'settlement':events[order],'availability':receipt[order]+MINUTE,'rates':rates[order],
            'availability_assumed':receipt_name is None}


def reference_at(sequence,now):
    """Only available endpoints create intervals; use scalar overlap/f-sum."""
    now=clock(now).value
    known=sequence['availability']<now
    events=sequence['settlement'][known];rates=sequence['rates'][known]
    out={'valid':False,'intensity':None,'covered_hours':0.,'reason':'insufficient_history'}
    if len(events)<2:return out
    delta=events[1:]-events[:-1]
    labels=[next((h for h in (1,2,4,8) if abs(int(d)-h*HOUR)<=5*10**9),None) for d in delta]
    left=now-WINDOW
    terms=[];durations=[];overlap_labels=[]
    for k in range(1,len(events)):
        lower=max(int(events[k-1]),left);upper=min(int(events[k]),now)
        if upper<=lower:continue
        weight=(upper-lower)/HOUR
        overlap_labels.append(labels[k-1]);durations.append(weight)
        if labels[k-1] is not None:
            terms.append(weight*float(rates[k])/((int(events[k])-int(events[k-1]))/HOUR))
    covered=math.fsum(durations);out['covered_hours']=covered
    if labels[-1] is None or None in overlap_labels:out['reason']='unrecognized_interval';return out
    if len(set(overlap_labels))>1:out['reason']='mixed_cadence_window';return out
    if now-int(events[-1])>int(delta[-1])+10*MINUTE:out['reason']='stale_funding';return out
    if covered<151.2:out['reason']='insufficient_coverage';return out
    out.update(valid=True,intensity=math.fsum(terms)/covered,reason='')
    return out


def verify_grid(features,start=START,end=END):
    grid=pd.date_range(start+pd.Timedelta(minutes=2),end,freq='min',inclusive='left').as_unit('ns')
    check(isinstance(features.index,pd.DatetimeIndex) and features.index.tz is not None,'Feature availability index must be aware')
    index=features.index.tz_convert('UTC').as_unit('ns')
    check(index.equals(grid),'Exact synchronized availability grid differs')
    columns=[f'{field}_{v}_{s}' for v in VENUES for s in SYMBOLS for field in ('price','yield','valid')]
    check(list(features.columns)==columns and len(columns)==48,'Exact48 field schema/order differs')
    check(features.attrs==RECEIPT_ASSUMPTIONS,'Feature availability assumptions differ')
    return grid


def verify_stream(features,bars,funding,venue,symbol,start=START,end=END):
    grid=features.index.tz_convert('UTC').as_unit('ns')
    expected=pd.date_range(start,end,freq='min',inclusive='left').as_unit('ns')
    check(isinstance(bars.timestamp.dtype,pd.DatetimeTZDtype),'Source price clock is naive')
    times=pd.DatetimeIndex(bars.timestamp).tz_convert('UTC').as_unit('ns')
    native=iid(venue,symbol)
    check(times.equals(expected) and bars.instrument_id.eq(native).all(),'Native source minute grid/identity differs')
    check(bars.duration_seconds.eq(60).all(),'Nonminute source bars')
    source=bars.close.to_numpy(dtype=float)
    check(np.isfinite(source).all() and (source>0).all(),'Invalid source closes')
    actual_prices=features[f'price_{venue}_{symbol}'].to_numpy(dtype=float)
    check(np.array_equal(actual_prices,source[:-2]),'Prior completed+processing price differs')
    flags=features[f'valid_{venue}_{symbol}'];yields=features[f'yield_{venue}_{symbol}']
    check(pd.api.types.is_bool_dtype(flags.dtype),'Valid field is not boolean')
    decisions=grid.minute==5
    check(not bool(flags.loc[~decisions].any()) and yields.loc[~decisions].isna().all(),'Offhour yield/valid leak')
    sequence=funding_sequence(funding,native,start,end)
    counts=Counter();max_error=0.
    for t in grid[decisions]:
        reference=reference_at(sequence,t);a=features.loc[t,f'valid_{venue}_{symbol}'];b=features.loc[t,f'yield_{venue}_{symbol}']
        check(bool(a)==reference['valid'],f'Causal validity mismatch {native} at{t}')
        if reference['valid']:
            check(pd.notna(b) and math.isfinite(float(b)),'Valid yield is nonfinite')
            error=abs(float(b)-reference['intensity']);max_error=max(error,max_error)
            check(error<=max(1e-15,abs(reference['intensity'])*1e-12),f'Causal intensity mismatch {native} at{t}')
            counts['valid']+=1
        else:
            check(pd.isna(b),f'Invalid yield must be NaN {native} at{t}')
            counts[reference['reason']]+=1
    return {'native_id':native,'source_rows':len(bars),'decision_count':int(decisions.sum()),
            'decision_status_counts':dict(counts),'maximum_intensity_absolute_error':max_error,
            'historical_receipt_assumed':sequence['availability_assumed']}


def verify_input_anchor(root):
    """Exact pre-feature published bytes prohibit a rewritten or shortened lock."""
    root=Path(root);records={}
    for name in ('source_lock.json','input_verification.json','preregistration.json'):
        raw=subprocess.run(['git','show',f'{INPUT_ANCHOR}:docs/cross_venue_preregistration/{name}'],
            cwd=REPO,capture_output=True,check=True).stdout
        path=root/name if name!='preregistration.json' else REPO/'docs/cross_venue_preregistration'/name
        check(path.read_bytes()==raw,'Pre-feature input/preregistration anchor differs:'+name)
        records[name]=json.loads(raw)
    prereg=records['preregistration.json'];lock=records['source_lock.json']
    check(prereg['source_commit']==ANCHOR and prereg['proposed_candidate_number']==26,
          'Wrong pre-feature source/candidate receipt')
    check(prereg['historical_features_exist'] is False and prereg['trial_directory_exists'] is False,
          'Input freeze was not prior to numerical research')
    check(prereg['source_lock_sha256']==sha(root/'source_lock.json') and
          prereg['input_verification_sha256']==sha(root/'input_verification.json'),
          'Pre-feature receipt hashes disagree')
    check(prereg['input_files']==len(lock['inputs']) and prereg['source_files']==len(lock['sources']),
          'Pre-feature exact source/input count differs')


def verify_provenance(root,binance,bybit):
    root,binance,bybit=map(Path,(root,binance,bybit));verify_input_anchor(root);lock=read(root/'source_lock.json')
    core=subprocess.run(['git','ls-tree','-r','--name-only',ANCHOR,'--','aster'],cwd=REPO,capture_output=True,check=True,text=True).stdout.splitlines()
    sources={p for p in core if p.endswith('.py')}
    sources|={f'examples/cross_venue/{name}' for name in ('run.py','signals.py','strategy.py','units.py','download_bybit.py','proposed_protocol.md')}
    sources|={f'examples/residual_convergence/{name}' for name in ('run.py','signals.py','strategy.py')}
    sources|={f'examples/minute_research/{name}' for name in ('download.py','downloadcarry.py')}
    check(set(lock['sources'])==sources,'Frozen executed source set differs from preregistration')
    for name,value in lock['sources'].items():
        raw=subprocess.run(['git','show',f'{ANCHOR}:{name}'],cwd=REPO,capture_output=True,check=True).stdout
        check(hashlib.sha256(raw).hexdigest()==value and sha(REPO/name)==value,'Source differs from pre-featurecommit')
        check(sha(root/'executed_source'/name)==value,'Archived executed source differs')
    for name,value in lock['inputs'].items():check(sha(name)==value,f'Frozen input changed:{name}')
    for cache in (binance,bybit):
        for name in ['instruments.json',*[f'{s}/{n}' for s in SYMBOLS for n in ('bars.parquet','funding.parquet','source_manifest.json')]]:
            check(str((cache/name).resolve()) in lock['inputs'],'Loaded normalized input not pinned')
    check(str((bybit/'dataset_seal.json').resolve()) in lock['inputs'],'Bybit completedseal not pinned')
    check(lock['family']=='cross_venue_realized_funding_differential' and lock['candidate_count_cumulative']==26,'Frozen family/count differs')
    for symbol in SYMBOLS:
        manifest=read(binance/symbol/'source_manifest.json')
        for entry in manifest['archives']+manifest['funding_pages']:
            raw=Path(entry['cache_file'])
            if not raw.exists():raw=REPO/raw
            check(str(raw.resolve()) in lock['inputs'],'Binance original raw source omitted from freeze')
        for entry in read(bybit/symbol/'source_manifest.json')['raw_pages']:
            relative=Path(entry['cache_file'])
            check(not relative.is_absolute() and relative.parts and relative.parts[0]=='raw' and '..' not in relative.parts,'Unsafe Bybit envelope path')
            path=bybit/relative
            check(lock['inputs'].get(str(path.resolve()))==entry['envelope_sha256'],'Bybit envelope receipt not pinned exactly')
    seal=read(bybit/'dataset_seal.json')
    expected={'instruments.json'}|{s+'/'+name for s in SYMBOLS for name in ('bars.parquet','funding.parquet','source_manifest.json')}
    check(set(seal['files'])==expected,'Bybit completed seal file set differs')
    check(all(lock['inputs'].get(str((bybit/name).resolve()))==value for name,value in seal['files'].items()),'Bybit normalized seal/input pins disagree')
    runtime={'python':sys.version,**{p:importlib.metadata.version(p) for p in ('numpy','pandas','pyarrow','statsmodels','scipy','plotly')}}
    check(lock['runtime']==runtime,'Numerical runtime differs')
    receipt=read(root/'input_verification.json')
    check(receipt==lock['input_verification'] and len(receipt['binance'])==8 and receipt['bybit_raw_reparse_verified'] is True,'Input verification differs/incomplete')
    check(receipt['bybit_dataset_seal_sha256']==sha(bybit/'dataset_seal.json'),'Verified Bybit seal differs')
    feature_receipt=read(root/'feature_receipt.json')
    check(feature_receipt['source_lock_sha256']==sha(root/'source_lock.json') and feature_receipt['features_sha256']==sha(root/'features.parquet'),'Feature receipt/source/bytes differs')
    return lock,feature_receipt


def verify_features(result_root,binance_root,bybit_root):
    auditor_sha=sha(__file__)
    root=Path(result_root);lock,receipt=verify_provenance(root,binance_root,bybit_root)
    features=pd.read_parquet(root/'features.parquet');grid=verify_grid(features)
    check(receipt['rows']==len(features) and receipt['columns']==list(features.columns) and receipt['availability_assumptions']==features.attrs,'Feature receipt schema differs')
    checks=[]
    for v,cache in [('binance',Path(binance_root)),('bybit',Path(bybit_root))]:
        for s in SYMBOLS:
            bars=pd.read_parquet(cache/s/'bars.parquet',columns=['timestamp','instrument_id','duration_seconds','close'])
            funding=pd.read_parquet(cache/s/'funding.parquet')
            checks.append(verify_stream(features,bars,funding,v,s))
    # Ensure no concurrent frozen artifact mutation during the full reconstruction.
    lock_after,_=verify_provenance(root,binance_root,bybit_root)
    check(lock_after==lock,'Frozen lock changed during verification')
    check(sha(__file__)==auditor_sha,'Independent auditor changed during verification')
    return {'complete':True,'errors':[],'source_anchor':ANCHOR,'input_freeze_anchor':INPUT_ANCHOR,
            'auditor_sha256':auditor_sha,'source_unchanged_during_audit':True,'auditor_source_unchanged':True,'source_lock_sha256':sha(root/'source_lock.json'),
            'features_sha256':sha(root/'features.parquet'),'feature_receipt_sha256':sha(root/'feature_receipt.json'),
            'reference_reconstruction_passed':True,'feature_rows':len(features),'feature_columns':48,
            'checks':checks,'scope':'Independent known-settlement sequence and synchronized prior-close reconstruction; no Engine/model imports',
            'limits':['Settlement+1minute availability is an assumption without historical receipts.',
                      'Consistent observed cadence and coverage cannot prove missing-payment absence.',
                      'Realized intensity does not establish contractual earning periods or future funding.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default='results/cross-venue-funding-1y-v1')
    parser.add_argument('--binance',default='data_cache/minute-perpetual-1y')
    parser.add_argument('--bybit',default='data_cache/minute-bybit-1y')
    parser.add_argument('--certificate',default='audit/cross_venue_feature_evidence.json')
    args=parser.parse_args();certificate=verify_features(args.root,args.binance,args.bybit)
    target=Path(args.certificate);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(certificate,indent=2,allow_nan=False))
    print(json.dumps({'complete':certificate['complete'],'feature_rows':certificate['feature_rows'],'streams':len(certificate['checks'])}))


if __name__=='__main__':main()
