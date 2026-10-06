"""Independent candidate27 price/funding reconstruction; no production model imports."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import subprocess
import sys
import numpy as np
import pandas as pd

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from audit import verify_cross_venue_features as reference

START=pd.Timestamp('2025-10-05',tz='UTC')
END=pd.Timestamp('2026-10-05',tz='UTC')
SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
FAMILY='joint_cross_sectional_funding_rank'
PREREG_PATH='docs/funding_rank_preregistration'
ASSUMPTIONS={
    'availability':'trade minute start + two minutes; settlement receipt + one minute strictly before decision',
    'funding_receipts_assumed':'settlement + one minute unless original historical receipt supplied',
    'decision_clock':'daily 00:05 UTC; proposals Sunday only',
    'historical_schedule':'past realized duration-weighted funding proxy, not recovered scheduled accrual',
    'boundary':'exclusive fixed year; terminal funding cash handled separately','economic_search':False}


def check(ok,message):
    if not ok:raise RuntimeError(message)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def read(path):return json.loads(Path(path).read_bytes())


def native(symbol):return 'binance:perpetual:'+('1000PEPEUSDT' if symbol=='PEPEUSDT' else symbol)


def sequence(frame,iid,start=START,end=END):
    """Validate all source fields, then exclude unavailable outside-end predictors."""
    check({'timestamp','instrument_id','funding_rate'}<=set(frame),'Funding schema missing')
    check(frame.instrument_id.eq(iid).all(),'Wrong native source funding identity')
    clocks=pd.DatetimeIndex([reference.clock(value) for value in frame.timestamp]).as_unit('ns')
    check(not clocks.has_duplicates and (clocks>=start).all(),'Duplicate or outside-year funding predecessor')
    rates=frame.funding_rate.to_numpy(dtype=float);check(np.isfinite(rates).all(),'Nonfinite sourced funding')
    receipt_name=next((name for name in ('historical_receipt','available_at') if name in frame),None)
    if receipt_name:
        receipts=pd.DatetimeIndex([reference.clock(value) for value in frame[receipt_name]]).as_unit('ns')
        check((receipts>=clocks).all(),'Receipt precedes settlement')
    selected=frame.loc[clocks<end].copy()
    return reference.funding_sequence(selected,iid,start,end)


def verify_grid(features,start=START,end=END):
    expected=pd.date_range(start+pd.Timedelta(minutes=2),end,freq='min',inclusive='left').as_unit('ns')
    check(isinstance(features.index,pd.DatetimeIndex) and features.index.tz is not None,'Aware feature availability index required')
    actual=features.index.tz_convert('UTC').as_unit('ns')
    check(actual.equals(expected),'Exact synchronized minute availability grid differs')
    check(list(features.columns)==[f'{field}_{s}' for s in SYMBOLS for field in ('price','yield','valid')],'Exact24 field schema/order differs')
    check(features.attrs==ASSUMPTIONS,'Feature assumptions differ from reviewed static protocol')
    return expected


def verify_stream(features,bars,funding,symbol,start=START,end=END):
    iid=native(symbol);source_grid=pd.date_range(start,end,freq='min',inclusive='left').as_unit('ns')
    check({'timestamp','instrument_id','duration_seconds','close'}<=set(bars),'Source price schema missing')
    check(isinstance(bars.timestamp.dtype,pd.DatetimeTZDtype),'Naive source price clock')
    timestamps=pd.DatetimeIndex(bars.timestamp).tz_convert('UTC').as_unit('ns')
    check(timestamps.equals(source_grid) and bars.instrument_id.eq(iid).all(),'Source native minute grid differs')
    check(bars.duration_seconds.eq(60).all(),'Source prices are not minute bars')
    prices=bars.close.to_numpy(dtype=float);check(np.isfinite(prices).all() and (prices>0).all(),'Invalid source close')
    check(np.array_equal(features[f'price_{symbol}'].to_numpy(dtype=float),prices[:-2]),'Prior completed+processing prices differ')
    flags=features[f'valid_{symbol}'];values=features[f'yield_{symbol}']
    check(pd.api.types.is_bool_dtype(flags.dtype),'Funding validity is not Boolean')
    grid=features.index.tz_convert('UTC').as_unit('ns');decision=(grid.hour==0)&(grid.minute==5)
    check(not flags.loc[~decision].any() and values.loc[~decision].isna().all(),'Nondecision funding values/validity leaked')
    fund=sequence(funding,iid,start,end);counts=Counter();maximum_error=0.
    for timestamp in grid[decision]:
        expected=reference.reference_at(fund,timestamp);actual_flag=flags.loc[timestamp];actual_value=values.loc[timestamp]
        check(bool(actual_flag)==expected['valid'],f'Causal validity differs {iid} at {timestamp}')
        if expected['valid']:
            check(pd.notna(actual_value) and math.isfinite(float(actual_value)),'Valid intensity is nonfinite')
            error=abs(float(actual_value)-expected['intensity']);maximum_error=max(maximum_error,error)
            check(error<=max(1e-15,abs(expected['intensity'])*1e-12),f'Known-only intensity differs {iid} at {timestamp}')
            counts['valid']+=1
        else:
            check(pd.isna(actual_value),f'Invalid intensity must be NaN {iid} at {timestamp}')
            counts[expected['reason']]+=1
    return dict(native_id=iid,source_price_rows=len(bars),daily_decisions_checked=int(decision.sum()),
                prior_prices_checked=len(features),decision_status_counts=dict(counts),
                maximum_intensity_absolute_error=maximum_error,historical_receipt_assumed=fund['availability_assumed'])


def git_bytes(commit,path):
    check(bool(__import__('re').fullmatch('[0-9a-f]{40}',commit)),'Full source/input Git anchor required')
    return subprocess.run(['git','show',f'{commit}:{path}'],cwd=REPO,capture_output=True,check=True).stdout


def verify_provenance(root,cache,source_anchor,input_anchor):
    root,cache=map(Path,(root,cache));anchored={}
    for name in ('source_lock.json','input_verification.json','preregistration.json'):
        expected=git_bytes(input_anchor,f'{PREREG_PATH}/{name}')
        path=REPO/PREREG_PATH/name if name=='preregistration.json' else root/name
        check(path.read_bytes()==expected,f'Published pre-feature freeze bytes differ: {name}')
        anchored[name]=json.loads(expected)
    lock=anchored['source_lock.json'];prereg=anchored['preregistration.json']
    check(prereg['source_commit']==source_anchor and prereg['proposed_candidate_number']==27,'Wrong pre-feature source/candidate anchor')
    check(prereg['historical_features_exist'] is False and prereg['trial_directory_exists'] is False,'Freeze not before numerical research')
    check(prereg['input_files']==len(lock['inputs']) and prereg['source_files']==len(lock['sources']),'Exact pre-feature file counts differ')
    check(prereg['source_lock_sha256']==sha(root/'source_lock.json') and prereg['input_verification_sha256']==sha(root/'input_verification.json'),'Pre-feature receipt seals differ')
    core=subprocess.run(['git','ls-tree','-r','--name-only',source_anchor,'--','aster'],cwd=REPO,capture_output=True,check=True,text=True).stdout.splitlines()
    sources={name for name in core if name.endswith('.py')}
    sources|={f'examples/funding_rank/{name}' for name in ('run.py','signals.py','strategy.py','proposed_protocol.md')}
    sources|={'examples/cross_venue/signals.py','examples/minute_research/download.py','examples/minute_research/downloadcarry.py'}
    check(set(lock['sources'])==sources,'Complete executed source/import set differs')
    for name,digest in lock['sources'].items():
        check(hashlib.sha256(git_bytes(source_anchor,name)).hexdigest()==digest and sha(REPO/name)==digest,'Source differs from pre-feature commit')
        check(sha(root/'executed_source'/name)==digest,'Archived execution source differs')
    expected_inputs={(cache/name).resolve() for name in ('instruments.json','cross_mapping.json','instrument_source_manifest.json','exchange_info_current.json')}
    for symbol in SYMBOLS:
        expected_inputs|={(cache/symbol/name).resolve() for name in ('bars.parquet','funding.parquet','source_manifest.json')}
        manifest=read(cache/symbol/'source_manifest.json')
        for item in manifest['archives']+manifest['funding_pages']:
            path=Path(item['cache_file'])
            if not path.exists():path=REPO/path
            expected_inputs.add(path.resolve())
    check(set(lock['inputs'])=={str(path) for path in expected_inputs},'Complete normalized/raw input set differs')
    for name,digest in lock['inputs'].items():check(sha(name)==digest,'Frozen input changed')
    versions={'python':sys.version,**{name:importlib.metadata.version(name) for name in ('numpy','pandas','pyarrow','scipy','plotly')}}
    check(lock['runtime']==versions and lock['family']==FAMILY and lock['candidate_count_cumulative']==27,'Runtime/family/search identity differs')
    verification=anchored['input_verification.json']
    check(lock['input_verification']==verification and len(verification)==8 and {v['spot_symbol'] for v in verification}==set(SYMBOLS),'Full-universe input verification differs')
    expected_phases=[(f'validation{k+1}',pd.Timestamp('2026-04-05T00:00Z')+pd.DateOffset(months=k),pd.Timestamp('2026-04-05T00:00Z')+pd.DateOffset(months=k+1),False) for k in range(3)]+[
        ('evaluation',pd.Timestamp('2026-07-05T00:00Z'),END,False),('evaluation_stress',pd.Timestamp('2026-07-05T00:00Z'),END,True)]
    check(lock['phases']==[[name,str(begin),str(stop),stress] for name,begin,stop,stress in expected_phases],'Five frozen phase identities differ')
    receipt=read(root/'feature_receipt.json')
    check(receipt['source_lock_sha256']==sha(root/'source_lock.json') and receipt['features_sha256']==sha(root/'features.parquet'),'Feature receipt/source seal differs')
    check(receipt['predictor_boundary']=='START<=settlement<END; raw source remains preserved','Predictor source boundary differs')
    return lock,receipt


def verify_features(root,cache,source_anchor,input_anchor):
    root,cache=map(Path,(root,cache));auditor_sha=sha(__file__);helper_sha=sha(reference.__file__)
    lock,receipt=verify_provenance(root,cache,source_anchor,input_anchor)
    before={str(root/name):sha(root/name) for name in ('source_lock.json','input_verification.json','features.parquet','feature_receipt.json')}
    before[str(REPO/PREREG_PATH/'preregistration.json')]=sha(REPO/PREREG_PATH/'preregistration.json')
    before.update(lock['inputs'])
    features=pd.read_parquet(root/'features.parquet');verify_grid(features)
    check(receipt['rows']==len(features) and receipt['columns']==list(features.columns) and receipt['availability_assumptions']==features.attrs,'Immutable feature receipt schema differs')
    checks=[]
    for symbol in SYMBOLS:
        bars=pd.read_parquet(cache/symbol/'bars.parquet',columns=['timestamp','instrument_id','duration_seconds','close'])
        funding=pd.read_parquet(cache/symbol/'funding.parquet')
        checks.append(verify_stream(features,bars,funding,symbol))
    after,_=verify_provenance(root,cache,source_anchor,input_anchor);check(after==lock,'Freeze changed during audit')
    check(all(sha(path)==digest for path,digest in before.items()),'Input/features changed during audit')
    check(sha(__file__)==auditor_sha and sha(reference.__file__)==helper_sha,'Independent auditor/helper changed during audit')
    return dict(complete=True,errors=[],source_anchor=source_anchor,input_freeze_anchor=input_anchor,
                auditor_sha256=auditor_sha,reference_helper_sha256=helper_sha,source_unchanged_during_audit=True,auditor_source_unchanged=True,
                source_lock_sha256=sha(root/'source_lock.json'),features_sha256=sha(root/'features.parquet'),feature_receipt_sha256=sha(root/'feature_receipt.json'),
                reference_reconstruction_passed=True,feature_rows=len(features),feature_columns=24,checks=checks,
                scope='Independent scalar known-settlement history and synchronized prior-close reconstruction; no production model imports',
                limits=['Historical receipt absence uses explicit assumed processing clock.','Observed regular cadence does not prove missing payments absent.','Neither funding persistence nor neutral price risk is established.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path('results/funding-rank-1y-v1'))
    parser.add_argument('--cache',type=Path,default=Path('data_cache/minute-perpetual-1y'))
    parser.add_argument('--source-anchor',required=True);parser.add_argument('--input-anchor',required=True)
    parser.add_argument('--output',type=Path,default=Path('audit/funding_rank_feature_evidence.json'))
    args=parser.parse_args();check(not args.output.exists(),'Preserve existing independent certificate')
    result=verify_features(args.out,args.cache,args.source_anchor,args.input_anchor)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'complete':True,'feature_rows':result['feature_rows'],'daily_decisions_checked':sum(c['daily_decisions_checked'] for c in result['checks']),'auditor_sha256':result['auditor_sha256']}))


if __name__=='__main__':main()
