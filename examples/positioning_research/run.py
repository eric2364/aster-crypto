"""Candidate28 fixed native-OI rebound. Historical execution requires independent feature audit."""
from __future__ import annotations
import argparse
from dataclasses import asdict, is_dataclass, replace
import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import sys
import subprocess
import re
import time
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from aster.analytics import daily_returns, json_safe
from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, SimulationConfig
from aster.reproducibility import export_result, verify_ledgers
from examples.minute_research.downloadcarry import verify, cached_path
from examples.cross_venue.signals import native_id
from examples.positioning_research.strategy import PositioningPortfolio
from examples.positioning_research.signals import ASSUMPTIONS, build_features
from examples.positioning import collect_archives as collector
from examples.funding_rank.run import SnapshotObserver, catalog, config, phase_inputs

REPO=Path(__file__).resolve().parents[2]
SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
START=pd.Timestamp('2025-10-05',tz='UTC')
END=pd.Timestamp('2026-10-05',tz='UTC')
VALID_START=pd.Timestamp('2026-04-05',tz='UTC')
EVAL_START=pd.Timestamp('2026-07-05',tz='UTC')
INITIAL=100000.
FAMILY='confirmed_native_position_unwind_rebound'
DATASET_CERT=REPO/'audit/positioning_dataset_evidence.json'
DATASET_AUDITOR=REPO/'audit/verify_positioning_dataset.py'
FEATURE_AUDITOR='audit/verify_positioning_features.py'
PREREG_PATH='docs/positioning_preregistration'
DELAYS={'baseline':6,'delayed':11}
FEATURE_COLUMNS=['price_source_label','price_available_at','price','price_return_1h','price_return_15m',
 'metric_source_label','metric_available_at','native_open_interest','quantity_change_1h','quantity_change_5m',
 'metric_age_seconds','valid','instrument_id']
PHASES=[(f'validation{k+1}',VALID_START+pd.DateOffset(months=k),VALID_START+pd.DateOffset(months=k+1),False) for k in range(3)]+[
 ('evaluation',EVAL_START,END,False),('evaluation_stress',EVAL_START,END,True)]
LEDGERS=('equity','fills','trades','funding','events','positions')
OUTPUTS=tuple([f'{n}.{ext}' for n in LEDGERS for ext in ('csv','parquet')]+[
 'metadata.json','metrics.json','source_manifest.json','quality.json','exposure.csv','exposure.parquet',
 'leg_contributions.csv','strategy_diagnostics.json','completed_baskets.json','proposal_ledger.json',
 'rejections.json','terminal_orders.json','daily_returns.csv','completed_episodes.json'])


def check(ok,message):
    if not ok:raise RuntimeError(message)


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''): hasher.update(block)
    return hasher.hexdigest()

def forensic_normalize(value):
    if is_dataclass(value): return forensic_normalize(asdict(value))
    if isinstance(value, dict): return {str(k):forensic_normalize(v) for k,v in value.items()}
    if isinstance(value, set): return [forensic_normalize(v) for v in sorted(value)]
    if isinstance(value, (tuple,list)): return [forensic_normalize(v) for v in value]
    if isinstance(value, np.datetime64): return pd.Timestamp(value).isoformat()
    return json_safe(value)

def dump(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(forensic_normalize(value), indent=2, allow_nan=False)+'\n')

def read(path): return json.loads(Path(path).read_text())

def leg_contributions(result,mapping):
    rows=[]
    for symbol,iid in mapping.items():
        closed=result.trades[result.trades.instrument_id.eq(iid)] if not result.trades.empty else result.trades
        opened=result.positions[result.positions.instrument_id.eq(iid)] if not result.positions.empty else result.positions
        net=float(closed.net_pnl.sum()) if not closed.empty else 0.
        if not opened.empty: net+=float((opened.unrealized_pnl+opened.funding_pnl-opened.entry_fees).sum())
        fills=result.fills[result.fills.instrument_id.eq(iid)] if not result.fills.empty else result.fills
        rows.append({'symbol':symbol,'instrument_id':iid,'net_pnl':net,'fill_count':len(fills),
                     'open_quantity':float(opened.quantity.sum()) if not opened.empty else 0.,
                     'funding_cash':float(result.funding.loc[result.funding.instrument_id.eq(iid),'funding_payment'].sum())
                                    if not result.funding.empty else 0.})
    if not np.isclose(sum(row['net_pnl'] for row in rows),float(result.equity.iloc[-1].equity)-INITIAL,atol=1e-7,rtol=1e-10):
        raise AssertionError('All eight leg contributions must reconcile joint net P&L')
    return rows

def endpoint_daily(frame):
    adjusted=frame.copy()
    adjusted['timestamp']=pd.to_datetime(adjusted.timestamp,utc=True).dt.as_unit('ns')
    end=adjusted.timestamp.max()
    if end==end.normalize(): adjusted.loc[adjusted.timestamp.eq(end),'timestamp']=end-pd.Timedelta(microseconds=1)
    return daily_returns(adjusted)





def source_paths():
    explicit=['examples/positioning_research/'+n for n in ('run.py','signals.py','strategy.py','proposed_protocol.md')]
    explicit += ['examples/funding_rank/'+n for n in ('run.py','signals.py','strategy.py','proposed_protocol.md')]
    explicit += ['examples/cross_venue/signals.py','examples/minute_research/download.py',
                 'examples/minute_research/downloadcarry.py','examples/positioning/collect_archives.py',
                 'audit/verify_positioning_dataset.py','docs/positioning_economic_research.md']
    return sorted(set([* (REPO/'aster').rglob('*.py'),*[REPO/n for n in explicit]]))


def require_reviewed_sources():
    # Freeze can only archive tracked, committed source bytes, not drafts.
    for path in source_paths():
        name=str(path.relative_to(REPO))
        committed=subprocess.run(['git','show',f'HEAD:{name}'],cwd=REPO,capture_output=True,check=True).stdout
        check(committed==path.read_bytes(),'Commit reviewed source before freezing: '+name)


def dataset_certificate(metrics_cache):
    committed=subprocess.run(['git','show','HEAD:audit/positioning_dataset_evidence.json'],cwd=REPO,capture_output=True,check=True).stdout
    check(committed==DATASET_CERT.read_bytes(),'Independent dataset certificate differs from committed evidence')
    cert=read(DATASET_CERT);root=Path(metrics_cache)
    check(cert.get('complete') is True and cert.get('errors')==[], 'Complete independent dataset certificate required')
    check(cert.get('source_anchor')=='241a6502a939a4bfe27dea938bdb5ef151808f46', 'Dataset acquisition anchor differs')
    for flag in ('source_unchanged_during_audit','auditor_source_unchanged','exact_normalization_reconstruction_passed',
                 'source_and_runtime_reconstruction_passed','evidence_unchanged_during_audit'):
        check(cert.get(flag) is True,'Dataset certificate failed: '+flag)
    check(cert.get('auditor_sha256')==digest(DATASET_AUDITOR) and
          cert.get('collector_sha256')==digest(REPO/'examples/positioning/collect_archives.py') and
          cert.get('complete_seal_sha256')==digest(root/'complete.json'),'Dataset certificate/source/seal drift')
    check(cert.get('raw_archive_count')==2920 and cert.get('raw_source_files_checked')==8760
          and cert.get('normalized_source_file_count')==18,'Full-year dataset evidence required')
    return cert


def identity(perp_cache,metrics_cache):
    # Candidate27's complete raw/perpetual input traversal is reused unchanged.
    from examples.funding_rank import run as previous
    old=previous.identity(perp_cache);metrics_cache=Path(metrics_cache)
    files=sorted(p for p in metrics_cache.rglob('*') if p.is_file())
    check(files and all(not p.is_symlink() for p in metrics_cache.rglob('*')), 'Regular complete metrics cache required')
    metrics_inputs={str(p.resolve()):digest(p) for p in files}
    return {'sources':{str(p.relative_to(REPO)):digest(p) for p in source_paths()},
            'perpetual_inputs':old['inputs'],'metrics_inputs':metrics_inputs,
            'dataset_certificate_path':str(DATASET_CERT.resolve()),'dataset_certificate_sha256':digest(DATASET_CERT),
            'runtime':old['runtime'],'family':FAMILY,'candidate_count_cumulative':28,
            'phases':[[n,str(b),str(e),stress] for n,b,e,stress in PHASES]}


def freeze(perp_cache,metrics_cache,out):
    require_reviewed_sources();out=Path(out);lock=identity(perp_cache,metrics_cache)
    specs={spec.id:spec for spec in catalog(perp_cache)}
    verification={'perpetual':[verify(perp_cache,s,specs) for s in SYMBOLS],
                  'positioning_complete_seal_sha256':digest(Path(metrics_cache)/'complete.json'),
                  'positioning_dataset_certificate':dataset_certificate(metrics_cache)}
    collector.verify(Path(metrics_cache))  # offline data integrity only, no predictors
    check(identity(perp_cache,metrics_cache)==lock,'Source/input/runtime changed during source verification')
    lock['input_verification']=verification
    if (out/'source_lock.json').exists():check(read(out/'source_lock.json')==lock,'Existing frozen packet differs')
    else:
        check(not out.exists() or not any(out.iterdir()),'Refuse nonempty unsealed experiment')
        out.mkdir(parents=True,exist_ok=True)
        for name,sha in lock['sources'].items():
            target=out/'executed_source'/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((REPO/name).read_bytes());check(digest(target)==sha,'Source changed while archiving')
        dump(out/'input_verification.json',verification);dump(out/'source_lock.json',lock)
    guard(perp_cache,metrics_cache,out)
    return lock


def guard(perp_cache,metrics_cache,out):
    out=Path(out);check((out/'source_lock.json').exists(),'Freeze BEFORE historical features or Engine execution')
    lock=read(out/'source_lock.json')
    check(identity(perp_cache,metrics_cache)=={k:v for k,v in lock.items() if k!='input_verification'},
          'Frozen source/input/runtime changed')
    for name,sha in lock['sources'].items():check(digest(out/'executed_source'/name)==sha,'Executed source archive changed')
    verification=read(out/'input_verification.json')
    check(verification==lock['input_verification'],'Input verification changed')
    checks=verification.get('perpetual',[])
    check(len(checks)==8 and {v['spot_symbol'] for v in checks}==set(SYMBOLS),'Incomplete perpetual verification')
    check(verification.get('positioning_dataset_certificate')==dataset_certificate(metrics_cache),
          'Positioning independent certificate changed')
    return lock


def published_lock(out):
    out=Path(out);path=out/'published_lock.json'
    check(path.exists(),'Privately published source/input lock required BEFORE features')
    receipt=read(path);commit=receipt.get('remote_commit','')
    check(bool(re.fullmatch('[a-f0-9]{40}',commit)) and receipt.get('commit_path')==PREREG_PATH,
          'Exact approved publication anchor/path required')
    check(receipt.get('historical_features_exist') is False and receipt.get('trials_exist') is False,
          'Publication must precede historical features and trials')
    for name,key in [('source_lock.json','source_lock_sha256'),('input_verification.json','input_verification_sha256')]:
        check(receipt.get(key)==digest(out/name),'Published lock digest differs')
        committed=subprocess.run(['git','show',f'{commit}:{PREREG_PATH}/{name}'],cwd=REPO,capture_output=True,check=True).stdout
        check(committed==(out/name).read_bytes(),'Lock differs from published Git anchor')
    result=subprocess.run(['git','merge-base','--is-ancestor',commit,'origin/main'],cwd=REPO,capture_output=True)
    check(result.returncode==0,'Publication commit must be an ancestor of origin/main')
    return receipt


def feature_paths(out):
    return {variant:{native_id('binance',s):Path(out)/'features'/variant/(native_id('binance',s).split(':')[-1]+'.parquet')
                     for s in SYMBOLS} for variant in DELAYS}


def expected_attrs(delay):
    return dict(ASSUMPTIONS,metric_delay_minutes=delay,start=START.isoformat(),end=END.isoformat())


def validate_feature_frame(frame,iid,delay):
    expected=pd.date_range(START+pd.Timedelta(minutes=2),END,freq='min',inclusive='left').as_unit('ns')
    clock=pd.DatetimeIndex(frame.index)
    check(clock.tz is not None and str(clock.tz)=='UTC' and not clock.hasnans and clock.as_unit('ns').equals(expected)
          and frame.index.name=='timestamp','Exact UTC feature minute decision index required')
    check(list(frame.columns)==FEATURE_COLUMNS and frame.instrument_id.eq(iid).all(),'Exact native feature schema/identity required')
    check(frame.attrs==expected_attrs(delay),'Feature source assumptions differ')
    check(pd.api.types.is_bool_dtype(frame.valid.dtype) and not frame.valid.isna().any(),'Nonmissing Boolean validity required')
    numeric=['price','price_return_1h','price_return_15m','native_open_interest','quantity_change_1h','quantity_change_5m','metric_age_seconds']
    for key in numeric:
        check(pd.api.types.is_numeric_dtype(frame[key].dtype) and not pd.api.types.is_bool_dtype(frame[key].dtype),'Numeric feature dtype required: '+key)
        check(not np.isinf(frame[key].to_numpy(dtype=float)).any(),'Infinite features forbidden')
    check(np.isfinite(frame.price.to_numpy(dtype=float)).all() and frame.price.gt(0).all(),'Finite positive feature prices required')
    # Exact mechanical source clocks, including missing initial metric rows.
    price_label=expected-pd.Timedelta(minutes=2)
    check(pd.DatetimeIndex(frame.price_source_label).equals(price_label) and
          pd.DatetimeIndex(frame.price_available_at).equals(expected),'Price availability clock differs')
    source=(expected-pd.Timedelta(minutes=delay)-pd.Timedelta(nanoseconds=1)).floor('5min')
    exists=source>=START;expected_label=pd.Series(source.where(exists),index=frame.index)
    expected_available=expected_label+pd.Timedelta(minutes=delay)
    for key,values in [('metric_source_label',expected_label),('metric_available_at',expected_available)]:
        check(isinstance(frame[key].dtype,pd.DatetimeTZDtype) and str(frame[key].dt.tz)=='UTC', 'Aware UTC metric clocks required')
        check(frame[key].equals(values.rename(key)),'Metric publication/source clock differs: '+key)
    expected_age=(pd.Series(expected,index=frame.index)-expected_available).dt.total_seconds()
    check(np.array_equal(frame.metric_age_seconds.to_numpy(),expected_age.to_numpy(),equal_nan=True),'Metric age differs')
    quantity=frame.native_open_interest.to_numpy(dtype=float)
    check(np.isnan(quantity[~exists]).all() and np.isfinite(quantity[exists]).all() and (quantity[exists]>0).all(),
          'Quantity availability/positivity differs')
    derived=['price_return_1h','price_return_15m','quantity_change_1h','quantity_change_5m']
    # Each return is missing exactly until both within-year source endpoints exist.
    warmups={'price_return_1h':price_label>=START+pd.Timedelta(hours=1),
             'price_return_15m':price_label>=START+pd.Timedelta(minutes=15),
             'quantity_change_1h':source>=START+pd.Timedelta(hours=1),
             'quantity_change_5m':source>=START+pd.Timedelta(minutes=5)}
    for key,ready in warmups.items():
        values=frame[key].to_numpy(dtype=float)
        check(np.isnan(values[~ready]).all() and np.isfinite(values[ready]).all() and (values[ready]>-1).all(),
              'Feature warmup/finite return semantics differ: '+key)
    flags=np.isfinite(frame[derived].to_numpy(dtype=float)).all(axis=1)&expected_age.gt(0).to_numpy()&expected_age.le(300).to_numpy()
    check(np.array_equal(frame.valid.to_numpy(dtype=bool),flags),'Feature validity differs from exact source semantics')


def verified_features(out,supplied=None):
    out=Path(out);paths=feature_paths(out);receipt_path=out/'feature_receipt.json'
    check(receipt_path.exists() and all(p.exists() for group in paths.values() for p in group.values()),'Missing/partial immutable feature packet')
    receipt=read(receipt_path)
    check({p.name for p in (out/'features').iterdir()}==set(DELAYS),'Exact two feature namespaces required')
    for variant,group in paths.items():
        check({p.name for p in (out/'features'/variant).iterdir()}=={p.name for p in group.values()},'Exact eight native feature files required')
    check(receipt.get('source_lock_sha256')==digest(out/'source_lock.json'),'Feature/source seal mismatch')
    hashes={variant:{iid:digest(path) for iid,path in group.items()} for variant,group in paths.items()}
    check(receipt.get('features_sha256')==hashes,'Feature packet digest mismatch')
    features={variant:{} for variant in DELAYS}
    for variant,group in paths.items():
        for iid,path in group.items():
            frame=pd.read_parquet(path);validate_feature_frame(frame,iid,DELAYS[variant]);features[variant][iid]=frame
    check(receipt.get('rows_per_stream')==len(next(iter(features['baseline'].values())))
          and receipt.get('columns')==FEATURE_COLUMNS
          and receipt.get('availability_assumptions')=={v:expected_attrs(d) for v,d in DELAYS.items()},'Feature receipt schema/assumptions differ')
    if supplied is not None:
        check(set(supplied)==set(features),'Caller feature variants differ')
        for variant,group in features.items():
            check(set(supplied[variant])==set(group),'Caller native feature identities differ')
            for iid,frame in group.items():
                pd.testing.assert_frame_equal(supplied[variant][iid],frame,check_exact=True,check_freq=False)
                check(supplied[variant][iid].attrs==frame.attrs,'Caller feature assumptions differ')
    return features


def generate_features(perp_cache,metrics_cache,out):
    guard(perp_cache,metrics_cache,out);published_lock(out);out=Path(out)
    if (out/'features').exists() or (out/'feature_receipt.json').exists():return verified_features(out)
    paths=feature_paths(out)
    for s in SYMBOLS:
        iid=native_id('binance',s);native=iid.split(':')[-1]
        bars=pd.read_parquet(Path(perp_cache)/s/'bars.parquet',columns=['timestamp','duration_seconds','instrument_id','close'])
        metrics=pd.read_parquet(Path(metrics_cache)/native/'observations.parquet')
        for variant,delay in DELAYS.items():
            frame=build_features(bars,metrics,instrument_id=iid,start=START,end=END,metric_delay_minutes=delay)
            validate_feature_frame(frame,iid,delay);path=paths[variant][iid];path.parent.mkdir(parents=True,exist_ok=True)
            check(not path.exists(),'Refuse overwriting historical feature evidence');frame.to_parquet(path)
        del bars,metrics,frame;gc.collect()
    dump(out/'feature_receipt.json',{'source_lock_sha256':digest(out/'source_lock.json'),
        'features_sha256':{v:{i:digest(p) for i,p in group.items()} for v,group in paths.items()},
        'rows_per_stream':len(pd.date_range(START+pd.Timedelta(minutes=2),END,freq='min',inclusive='left')),
        'columns':FEATURE_COLUMNS,'availability_assumptions':{v:expected_attrs(d) for v,d in DELAYS.items()}})
    guard(perp_cache,metrics_cache,out)
    return verified_features(out)


def require_feature_audit(out,certificate):
    check(certificate is not None,'Separate independent historical feature certificate required BEFORE Engine')
    out=Path(out);published_lock(out);cert=read(certificate);receipt=read(out/'feature_receipt.json')
    check(cert.get('complete') is True and cert.get('errors')==[], 'Independent feature reconstruction did not pass')
    check(cert.get('source_lock_sha256')==digest(out/'source_lock.json')
          and cert.get('feature_receipt_sha256')==digest(out/'feature_receipt.json')
          and cert.get('features_sha256')==receipt.get('features_sha256'),'Independent certificate feature/source binding differs')
    for flag in ('source_unchanged_during_audit','input_unchanged_during_audit','features_unchanged_during_audit','auditor_source_unchanged'):
        check(cert.get(flag) is True,'Independent feature certificate failed: '+flag)
    check(cert.get('scope')=={'native_stream_count':8,'delays_minutes':[6,11],'begin':START.isoformat(),
          'end':END.isoformat(),'full_reconstruction':True},'Independent feature certificate scope differs')
    check(cert.get('auditor_path')==FEATURE_AUDITOR and (REPO/FEATURE_AUDITOR).is_file()
          and cert.get('auditor_sha256')==digest(REPO/FEATURE_AUDITOR),'Independent feature auditor source differs')
    completed=pd.Timestamp(cert.get('completed_at_utc'))
    check(not pd.isna(completed) and completed.tzinfo is not None
          and completed>=pd.Timestamp((out/'feature_receipt.json').stat().st_mtime,unit='s',tz='UTC'),
          'Fresh independent certificate must follow feature packet creation')
    return cert


def common_artifacts(out,feature_audit):
    """Pin receipt bytes, including fields not consumed by semantic validators."""
    check(feature_audit is not None,'Separate independent historical feature certificate required BEFORE Engine')
    out=Path(out)
    paths={name:out/name for name in ('source_lock.json','input_verification.json',
                                    'feature_receipt.json','published_lock.json')}
    paths['feature_audit']=Path(feature_audit)
    return {name:digest(path) for name,path in paths.items()}


def phase_artifacts(out):
    """All previously verified financial packet bytes, not only selected metrics."""
    return {phase[0]:{'outputs':output_files(Path(out)/'trials'/phase[0]),
                     'completion':digest(Path(out)/'trials'/phase[0]/'completion.json')}
            for phase in PHASES}


def check_common_unchanged(out,feature_audit,pinned):
    check(common_artifacts(out,feature_audit)==pinned,'Common source/input/feature/publication/audit artifacts changed')


def check_summary_unchanged(out,feature_audit,common,phases):
    check_common_unchanged(out,feature_audit,common)
    check(phase_artifacts(out)==phases,'Previously verified phase artifacts changed during summary')


def parameters(out,phase,feature_audit=None):
    name,begin,stop,stress=phase
    return {'family':FAMILY,'phase':name,'begin':str(begin),'stop':str(stop),'stress':stress,
        'source_lock_sha256':digest(Path(out)/'source_lock.json'),'features_sha256':read(Path(out)/'feature_receipt.json')['features_sha256'],
        'feature_receipt_sha256':digest(Path(out)/'feature_receipt.json'),
        'feature_audit_sha256':digest(feature_audit) if feature_audit is not None else None,
        'published_lock_sha256':digest(Path(out)/'published_lock.json'),'research_status':'exploratory reused year; candidate28'}


def source_manifest(out):
    return {'source_lock':read(Path(out)/'source_lock.json'),
        'funding_boundary':'actual sourced begin<=timestamp<=stop; predictor excludes END; original mark and native units',
        'terminal_order_semantics':'captured at final equity clock BEFORE automatic end_of_data cancellations'}


def output_files(destination):return {name:digest(Path(destination)/name) for name in OUTPUTS}


def verify_completed(cache,out,phase,*,feature_audit=None):
    check(phase in PHASES,'Only exact approved phase tuples permitted')
    destination=Path(out)/'trials'/phase[0];receipt=read(destination/'completion.json');expected=parameters(out,phase,feature_audit)
    check(receipt.get('parameters')==expected,'Cached requested phase/source/features differs')
    check(receipt.get('outputs_sha256')==output_files(destination),'Cached output seal differs')
    metadata=read(destination/'metadata.json')
    check(metadata['parameters']==expected and metadata['engine']==asdict(config(phase[3])),'Cached phase configuration differs')
    check(metadata['instruments']==[asdict(s) for s in catalog(cache,phase[3])],'Cached native instruments/fees differ')
    check(metadata.get('strategy')==PositioningPortfolio.__name__ and metadata.get('strategy_version')==str(PositioningPortfolio.version),'Cached coordinator class/version differs')
    lock=read(Path(out)/'source_lock.json');core={n.removeprefix('aster/'):sha for n,sha in lock['sources'].items() if n.startswith('aster/')}
    check(metadata.get('source_sha256')==core,'Cached executed core hashes differ')
    check(metadata.get('source_manifest')==source_manifest(out) and read(destination/'source_manifest.json')==source_manifest(out),'Cached source manifest differs')
    check(metadata.get('start')==str(phase[1]) and metadata.get('end')==str(phase[2]),'Cached execution bounds differ')
    return read(destination/'metrics.json')


def reserve(result):
    fee=sum(abs(p.quantity)*p.mark_price*next(s.taker_bps for s in result.instruments if s.id==p.instrument_id)/10000 for p in result.positions.itertuples())
    slip=sum(abs(p.quantity)*p.mark_price*result.config.slippage_bps/10000 for p in result.positions.itertuples())
    return {'indicative_exit_fee_reserve':fee,'indicative_exit_slippage_reserve':slip,'indicative_exit_reserve_total':fee+slip,
        'return_after_indicative_exit_reserve':(float(result.equity.iloc[-1].equity)-fee-slip)/INITIAL-1}


def terminal_status(last_observation,orders):
    """Strict packet flatness includes dust the core positions export may omit."""
    quantities=[float(last_observation[f'quantity_{s}']) for s in SYMBOLS]
    check(np.isfinite(quantities).all(),'Nonfinite terminal observed native quantity')
    return {'terminal_observed_nonzero_position_count':sum(q!=0 for q in quantities),
        'terminal_live_order_count':len(orders),
        'terminal_flat_resolved':all(q==0 for q in quantities) and not orders}


def episode_participation(completed):
    participants=set();generations=set()
    for row in completed:
        symbol=row.get('symbol');generation=row.get('generation')
        check(symbol in SYMBOLS and row.get('instrument_id')==native_id('binance',symbol),'Invalid completed native episode membership')
        check(type(generation) is int and generation>0 and generation not in generations,'Duplicate/invalid completed episode generation')
        check(row.get('failed') is False and row.get('entry_completed_at') is not None and row.get('closed_at') is not None,
              'Only fully entered and actually closed episodes count')
        times=[pd.Timestamp(row.get(k)) for k in ('submitted_at','entry_completed_at','closed_at','observed_closed_at')]
        check(all(not pd.isna(t) and t.tzinfo is not None for t in times) and times==sorted(times),
              'Completed episode clocks invalid')
        check(np.isfinite(row.get('average_entry_price',float('nan'))) and row['average_entry_price']>0,'Completed actual entry VWAP required')
        generations.add(generation);participants.add(symbol)
    return participants,len(generations)


def run_phase(perp_cache,metrics_cache,out,phase,features=None,*,feature_audit=None):
    cache=perp_cache
    check(phase in PHASES,'Only five fixed phases permitted');guard(cache,metrics_cache,out)
    common=common_artifacts(out,feature_audit)
    certificate=require_feature_audit(out,feature_audit);certificate_digest=common['feature_audit']
    packet=verified_features(out,features);frozen=packet['delayed' if phase[3] else 'baseline'];destination=Path(out)/'trials'/phase[0]
    if (destination/'completion.json').exists():
        cached={'outputs':output_files(destination),'completion':digest(destination/'completion.json')}
        score=verify_completed(cache,out,phase,feature_audit=feature_audit)
        guard(cache,metrics_cache,out);verified_features(out)
        check(digest(feature_audit)==certificate_digest and require_feature_audit(out,feature_audit)==certificate,'Certificate changed during cached verification')
        check_common_unchanged(out,feature_audit,common)
        check(cached=={'outputs':output_files(destination),'completion':digest(destination/'completion.json')},'Cached phase packet changed during verification')
        return score
    check(not destination.exists(),'Partial trial exists; preserve before explicit recovery')
    destination.mkdir(parents=True);_,begin,stop,stress=phase
    bars,funding=phase_inputs(cache,phase)
    strategy=PositioningPortfolio({iid:frame.loc[(frame.index>=begin)&(frame.index<stop)] for iid,frame in frozen.items()},stop);del frozen,packet
    engine=Engine(catalog(cache,stress),config(stress));observer=SnapshotObserver(engine);engine.portfolio.snapshot=observer
    phase_parameters=parameters(out,phase,feature_audit);manifest=source_manifest(out)
    check_common_unchanged(out,feature_audit,common)
    started=time.perf_counter();result=engine.run(bars,strategy,funding=funding);elapsed=time.perf_counter()-started
    check_common_unchanged(out,feature_audit,common)  # BEFORE any financial exports
    verify_ledgers(result)
    _,score=export_result(result,destination,bars=bars,funding_source=funding,parameters=phase_parameters,
        data_source='Verified native Binance perpetual minute trade/mark/funding and reported OI archives; historical delivery and units unverified',source_manifest=manifest)
    exposure=pd.DataFrame(observer.rows)
    check(pd.DatetimeIndex(exposure.timestamp).equals(pd.DatetimeIndex(result.equity.timestamp))
          and np.array_equal(exposure.equity.to_numpy(),result.equity.equity.to_numpy()),'Pure observer/equity clocks differ')
    exposure.to_csv(destination/'exposure.csv',index=False);exposure.to_parquet(destination/'exposure.parquet',index=False)
    mapping={s:native_id('binance',s) for s in SYMBOLS}
    pd.DataFrame(leg_contributions(result,mapping)).to_csv(destination/'leg_contributions.csv',index=False)
    completed=forensic_normalize(strategy.completed_episodes);participants,generations=episode_participation(completed)
    diagnostics=forensic_normalize(strategy.diagnostics)
    dump(destination/'completed_baskets.json',completed)  # prior gate/file compatibility; rows are closed episodes
    dump(destination/'completed_episodes.json',completed)
    dump(destination/'proposal_ledger.json',strategy.proposals)
    dump(destination/'rejections.json',strategy.rejections)
    dump(destination/'terminal_orders.json',{'before_end_of_data_cancellation':observer.last_orders,
        'after_run_live_orders':[forensic_normalize(o) for o in engine.orders.values() if o.status in ('accepted','partial')]})
    dump(destination/'strategy_diagnostics.json',{'events':diagnostics,'terminal_state':strategy.state,
        'terminal_active_basket':strategy.active,'terminal_transaction':strategy.transaction,'terminal_proposal':strategy.proposal,
        'terminal_cleanup_orders':strategy.cleanup_orders,'terminal_blocked':strategy.blocked,
        'terminal_cleanup_deadline':strategy.cleanup_deadline,'terminal_cleanup_deadline_exceeded':strategy.cleanup_deadline_exceeded,
        'terminal_requested':strategy.terminal_requested,'unmatched':strategy.unmatched,'last_targets':strategy.last_targets})
    daily=endpoint_daily(result.equity).dropna();daily.rename('return').to_csv(destination/'daily_returns.csv')
    std=float(daily.std(ddof=1));score.update(reserve(result))
    score.update({'sharpe':float(daily.mean()/std*np.sqrt(365)) if np.isfinite(std) and std>0 else None,
        'daily_return_count':len(daily),'liquidation_event_count':int(result.events.type.eq('LIQUIDATION').sum()) if not result.events.empty else 0,
        'open_position_count':len(result.positions),**terminal_status(observer.rows[-1],observer.last_orders),
        'completed_basket_count':generations,'completed_episode_count':generations,'completed_participants':sorted(participants),
        'joint_account':True,'runtime_seconds':elapsed,'peak_rss_mib_process':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024})
    dump(destination/'metrics.json',score);guard(cache,metrics_cache,out);verified_features(out)
    check(digest(feature_audit)==certificate_digest and require_feature_audit(out,feature_audit)==certificate,'Independent feature certificate changed during phase')
    outputs=output_files(destination)
    check_common_unchanged(out,feature_audit,common)  # final receipt check BEFORE completion seal
    dump(destination/'completion.json',{'parameters':phase_parameters,'outputs_sha256':outputs})
    engine.portfolio.snapshot=observer.original
    return score


def conditional_interval(frame):
    values=endpoint_daily(frame).dropna().to_numpy()
    if len(values)<7 or not np.isfinite(values).all() or (values<=-1).any():return {'available':False,'reason':'insufficient/invalid daily observations'}
    rng=np.random.default_rng(42);n=len(values);starts=rng.integers(0,n,(10000,int(np.ceil(n/7))))
    indices=((starts[:,:,None]+np.arange(7))%n).reshape(10000,-1)[:,:n]
    totals=np.expm1(np.log1p(values[indices]).sum(axis=1))
    return {'available':True,'comparison_count':28,'method':'conditional circular seven-day blocks;10000 draws;seed42',
        'tails':[.05/56,1-.05/56],'return_interval95':np.quantile(totals,[.025,.975]).tolist(),
        'return_interval_bonferroni28':np.quantile(totals,[.05/56,1-.05/56]).tolist(),
        'limitations':'conditional reused year; diagnostic only; cannot undo adaptive research'}


def gate_results(scores,months,participants,generations):
    check(set(scores)=={p[0] for p in PHASES},'Exactly five scores required')
    check(len(months)==3 and np.isfinite(months).all(),'Exactly three finite anchored months required')
    check(set(participants)<=set(SYMBOLS) and isinstance(generations,int) and generations>=0,'Invalid completed-basket activity')
    validation=float(np.prod([1+scores[f'validation{k}']['total_return'] for k in (1,2,3)])-1)
    vr=float(np.prod([1+scores[f'validation{k}']['return_after_indicative_exit_reserve'] for k in (1,2,3)])-1)
    base,stress=scores['evaluation'],scores['evaluation_stress']
    gates={'positive_compounded_validation':validation>0,'positive_validation_after_exit_reserve':vr>0,
        'positive_evaluation':base['total_return']>0,'positive_evaluation_after_exit_reserve':base['return_after_indicative_exit_reserve']>0,
        'positive_stress':stress['total_return']>0,'positive_stress_after_exit_reserve':stress['return_after_indicative_exit_reserve']>0,
        'two_positive_anchored_months':sum(x>0 for x in months)>=2,
        'daily_sharpe_at_least_half':base['sharpe'] is not None and np.isfinite(base['sharpe']) and base['sharpe']>=.5,
        'minute_drawdown_at_most_twenty_percent':np.isfinite(base['max_drawdown']) and base['max_drawdown']<=.2,
        'no_liquidation_all_five_runs':sum(s['liquidation_event_count'] for s in scores.values())==0,
        'four_completed_assets':len(participants)>=4,'completed_doge_participation':'DOGEUSDT' in participants,
        'completed_pepe_participation':'PEPEUSDT' in participants,'two_completed_entry_generations':generations>=2,
        'actual_terminal_flat_all_five_runs':all(s['terminal_flat_resolved'] is True for s in scores.values())}
    return validation,vr,{k:bool(v) for k,v in gates.items()}


def summarize(perp_cache,metrics_cache,out,*,feature_audit=None):
    cache=perp_cache
    guard(cache,metrics_cache,out);out=Path(out);common=common_artifacts(out,feature_audit)
    require_feature_audit(out,feature_audit);verified_features(out);trials=out/'trials'
    check(trials.exists() and {p.name for p in trials.iterdir()}=={p[0] for p in PHASES},'Require all five exact trials; no hidden variants')
    phases=phase_artifacts(out)  # pin every phase before any sequential verification/read
    scores={p[0]:verify_completed(cache,out,p,feature_audit=feature_audit) for p in PHASES}
    check_summary_unchanged(out,feature_audit,common,phases)
    frame=pd.read_parquet(trials/'evaluation/equity.parquet');series=frame.set_index('timestamp').equity
    points=[float(series.asof(EVAL_START+pd.DateOffset(months=k))) for k in range(4)]
    check(np.isfinite(points).all() and min(points)>0,'Missing/nonpositive anchored month equity')
    months=[points[k+1]/points[k]-1 for k in range(3)]
    participants,generations=episode_participation(read(trials/'evaluation/completed_baskets.json'))
    check(sorted(participants)==scores['evaluation']['completed_participants'] and generations==scores['evaluation']['completed_basket_count'],'Completed breadth differs from sealed ledger')
    validation,vr,gates=gate_results(scores,months,participants,generations)
    summary={'family':FAMILY,'candidate_count_cumulative':28,'research_status':'exploratory reused year; no untouched holdout',
        'passes_hurdles':all(gates.values()),'gates':gates,'failed_gates':[k for k,v in gates.items() if not v],
        'validation_compounded_return':validation,'validation_after_exit_reserve':vr,'scores':scores,
        'anchored_month_returns':months,'completed_participants':sorted(participants),'completed_basket_count':generations,'completed_episode_count':generations,
        'all_evaluation_leg_contributions':pd.read_csv(trials/'evaluation/leg_contributions.csv').to_dict('records'),
        'conditional_interval':conditional_interval(frame),'full_resolution_evaluation_equity_sha256':digest(trials/'evaluation/equity.parquet'),
        'source_lock_sha256':digest(out/'source_lock.json'),'features_sha256':read(out/'feature_receipt.json')['features_sha256'],
        'feature_receipt_sha256':digest(out/'feature_receipt.json'),'feature_audit_sha256':digest(feature_audit),
        'publication_status':'UNPUBLISHED: independent policy, trajectory and summary reconstruction required'}
    check_summary_unchanged(out,feature_audit,common,phases)
    dump(out/'summary.json',summary);guard(cache,metrics_cache,out);verified_features(out);require_feature_audit(out,feature_audit)
    check_summary_unchanged(out,feature_audit,common,phases)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--perp-cache',required=True);parser.add_argument('--metrics-cache',required=True)
    parser.add_argument('--out',required=True);parser.add_argument('--feature-audit',type=Path)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--freeze-only',action='store_true');action.add_argument('--features-only',action='store_true')
    action.add_argument('--execute',action='store_true');action.add_argument('--analysis-only',action='store_true')
    args=parser.parse_args()
    if args.freeze_only:
        freeze(args.perp_cache,args.metrics_cache,args.out)
        print('Sources/inputs frozen; no historical features or Engine execution.');return
    guard(args.perp_cache,args.metrics_cache,args.out)
    if args.features_only:
        generate_features(args.perp_cache,args.metrics_cache,args.out)
        print('Assumed-availability features written; independent historical certification required before Engine.');return
    check(args.feature_audit is not None,'--feature-audit required; never generate/execute without independent certification')
    require_feature_audit(args.out,args.feature_audit)
    if args.execute:
        verified_features(args.out)
        for phase in PHASES:
            print('Executing fixed phase',phase[0],flush=True)
            run_phase(args.perp_cache,args.metrics_cache,args.out,phase,feature_audit=args.feature_audit);gc.collect()
    summarize(args.perp_cache,args.metrics_cache,args.out,feature_audit=args.feature_audit)


if __name__=='__main__':main()
