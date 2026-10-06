"""One prospective two-venue family: freeze before features, seven fixed runs only."""
from __future__ import annotations
import argparse
from dataclasses import asdict, replace
import gc
import importlib.metadata
from pathlib import Path
import resource
import sys
import time
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, SimulationConfig
from aster.reproducibility import export_result, verify_ledgers
from examples.minute_research.downloadcarry import verify as verify_binance, cached_path
from examples.cross_venue import download_bybit
from examples.cross_venue.signals import SYMBOLS, VENUES, START, END, native_id, build_features
from examples.cross_venue.strategy import CrossVenueCarry
# Executed helper imports are explicitly archived, including their transitive sources.
from examples.residual_convergence.run import digest, dump, read, leg_contributions, endpoint_daily

REPO=Path(__file__).resolve().parents[2]
INITIAL=100000.
FAMILY='cross_venue_realized_funding_differential'
VALID_START=pd.Timestamp('2026-04-05',tz='UTC')
EVAL_START=pd.Timestamp('2026-07-05',tz='UTC')
PHASES=[(f'validation{k+1}',VALID_START+pd.DateOffset(months=k),VALID_START+pd.DateOffset(months=k+1),False,'primary') for k in range(3)]+[
    ('evaluation',EVAL_START,END,False,'primary'),('evaluation_stress',EVAL_START,END,True,'primary'),
    ('evaluation_alternative',EVAL_START,END,False,'alternative'),('evaluation_alternative_stress',EVAL_START,END,True,'alternative')]
LEDGERS=('equity','fills','trades','funding','events','positions')
OUTPUTS=tuple([f'{name}.{ext}' for name in LEDGERS for ext in ('csv','parquet')]+[
    'metadata.json','metrics.json','source_manifest.json','quality.json','exposure.csv','exposure.parquet',
    'leg_contributions.csv','pair_contributions.csv','strategy_diagnostics.json','unmatched.csv','unmatched.parquet',
    'matched_entries.csv','matched_entries.parquet'])


def check(ok,message):
    if not ok:raise RuntimeError(message)


def catalog(binance,bybit,stress=False):
    specs=[]
    for venue,root in [('binance',Path(binance)),('bybit',Path(bybit))]:
        items=[Instrument(**x) for x in read(root/'instruments.json')]
        check(len(items)==8 and {x.id for x in items}=={native_id(venue,s) for s in SYMBOLS},'Wrong exact native venue catalog')
        for spec in items:
            check(spec.exchange==venue and spec.market_type=='perpetual' and spec.quote=='USDT'
                  and spec.symbol==spec.id.split(':')[-1] and spec.base==spec.symbol[:-4]
                  and spec.multiplier==1,'Native contract identity/unit mismatch')
            fee=(10 if venue=='binance' else 12) if stress else (5 if venue=='binance' else 6)
            specs.append(replace(spec,maker_bps=fee,taker_bps=fee))
    return sorted(specs,key=lambda x:x.id)


def config(stress):
    return SimulationConfig(initial_balances={'binance':50000.,'bybit':50000.},leverage=1,margin_mode='cross',
            max_gross_leverage=.5,max_position_pct=.25,fill_model='volume_aware',participation=.025 if stress else .05,
            slippage_bps=16 if stress else 8,execution_delay_bars=1 if stress else 0,record_every=1)


def identity(binance,bybit):
    source_paths=[*sorted((REPO/'aster').rglob('*.py')),
        *[REPO/'examples/cross_venue'/name for name in ('run.py','signals.py','strategy.py','units.py','download_bybit.py','proposed_protocol.md')],
        *[REPO/'examples/residual_convergence'/name for name in ('run.py','signals.py','strategy.py')],
        *[REPO/'examples/minute_research'/name for name in ('download.py','downloadcarry.py')]]
    inputs=[]
    binance,bybit=Path(binance),Path(bybit)
    inputs += [binance/name for name in ('instruments.json','cross_mapping.json','instrument_source_manifest.json','exchange_info_current.json')]
    inputs += [bybit/name for name in ('instruments.json','dataset_seal.json')]
    for symbol in SYMBOLS:
        inputs += [root/symbol/name for root in (binance,bybit) for name in ('bars.parquet','funding.parquet','source_manifest.json')]
        manifest=read(binance/symbol/'source_manifest.json')
        inputs += [cached_path(entry['cache_file']) for entry in manifest['archives']+manifest['funding_pages']]
        for receipt in read(bybit/symbol/'source_manifest.json')['raw_pages']:
            relative=Path(receipt['cache_file'])
            check(not relative.is_absolute() and relative.parts[0]=='raw' and '..' not in relative.parts,'Invalid raw envelope path')
            inputs.append(bybit/relative)
    return {'sources':{str(p.relative_to(REPO)):digest(p) for p in source_paths},
            'inputs':{str(p.resolve()):digest(p) for p in sorted(set(inputs))},
            'runtime':{'python':sys.version,**{p:importlib.metadata.version(p) for p in ('numpy','pandas','pyarrow','statsmodels','scipy','plotly')}},
            'family':FAMILY,'candidate_count_cumulative':26,
            'phases':[[name,str(begin),str(stop),stress,valuation] for name,begin,stop,stress,valuation in PHASES]}


def freeze(binance,bybit,out):
    out=Path(out)
    lock=identity(binance,bybit)
    specs={s.id:s for s in catalog(binance,bybit)}
    verification=[verify_binance(Path(binance),symbol,specs) for symbol in SYMBOLS]
    download_bybit.run(bybit,workers=2,verify_only=True)
    check(identity(binance,bybit)==lock,'Inputs changed during full source verification')
    verification={'binance':verification,'bybit_dataset_seal_sha256':digest(Path(bybit)/'dataset_seal.json'),
                  'bybit_raw_reparse_verified':True,'scope':'source completeness checks; no features or outcomes'}
    lock['input_verification']=verification
    path=out/'source_lock.json'
    if path.exists():
        check(read(path)==lock,'Existing frozen packet differs; preserve it')
    else:
        check(not out.exists() or not any(out.iterdir()),'Refuse nonempty unsealed experiment')
        out.mkdir(parents=True,exist_ok=True)
        for name,sha in lock['sources'].items():
            target=out/'executed_source'/name
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((REPO/name).read_bytes())
            check(digest(target)==sha,'Source changed while archiving')
        dump(out/'input_verification.json',verification)
        dump(path,lock)
    guard(binance,bybit,out)
    return lock


def guard(binance,bybit,out):
    out=Path(out);path=out/'source_lock.json'
    check(path.exists(),'Freeze source/data/runtime before any historical features or Engine run')
    lock=read(path)
    check(identity(binance,bybit)=={k:v for k,v in lock.items() if k!='input_verification'},'Frozen source/data/runtime differs')
    for name,sha in lock['sources'].items():
        check(digest(out/'executed_source'/name)==sha,'Executed source archive differs')
    check(read(out/'input_verification.json')==lock['input_verification'],'Source verification receipt differs')
    check(len(lock['input_verification']['binance'])==8 and lock['input_verification']['bybit_raw_reparse_verified'] is True,'Incomplete source verification')
    return lock


def generate_features(binance,bybit,out):
    guard(binance,bybit,out)
    out=Path(out);path=out/'features.parquet';receipt_path=out/'feature_receipt.json'
    if path.exists() or receipt_path.exists():
        return verified_features(out)
    bars={};funding={}
    for venue,root in [('binance',Path(binance)),('bybit',Path(bybit))]:
        for symbol in SYMBOLS:
            iid=native_id(venue,symbol)
            bars[iid]=pd.read_parquet(root/symbol/'bars.parquet',columns=['timestamp','duration_seconds','instrument_id','close'])
            # Keep authentic optional historical_receipt/available_at fields; retrieval is not receipt.
            funding[iid]=pd.read_parquet(root/symbol/'funding.parquet')
    frame=build_features(bars,funding)
    del bars,funding;gc.collect()
    frame.to_parquet(path,index=True)
    dump(receipt_path,{'source_lock_sha256':digest(out/'source_lock.json'),'features_sha256':digest(path),
                      'availability_assumptions':frame.attrs,'rows':len(frame),'columns':list(frame.columns)})
    guard(binance,bybit,out)
    return verified_features(out)


def verified_features(out):
    out=Path(out);path=out/'features.parquet';receipt_path=out/'feature_receipt.json'
    check(path.exists() and receipt_path.exists(),'Partial or missing immutable features; preserve artifacts')
    receipt=read(receipt_path)
    check(receipt['source_lock_sha256']==digest(out/'source_lock.json') and receipt['features_sha256']==digest(path),'Feature/source seal mismatch')
    frame=pd.read_parquet(path)
    check(len(frame)==receipt['rows'] and list(frame.columns)==receipt['columns'] and frame.attrs==receipt['availability_assumptions'],'Feature schema/assumptions mismatch')
    return frame


def alternative_funding(funding,bars):
    """Already phase-clipped events; only completed within-year Bybit mark closes."""
    result=funding.copy()
    if result.empty:return result
    clocks=pd.DatetimeIndex(bars.end).as_unit('ns')
    check(clocks.tz is not None and clocks.is_monotonic_increasing and not clocks.has_duplicates,'Invalid mark completion grid')
    events=pd.DatetimeIndex(result.timestamp).as_unit('ns')
    index=clocks.searchsorted(events,side='right')-1
    check((index>=0).all(),'Alternative mark unavailable: no pre-year fabricated predecessor')
    marks=bars.mark_price.to_numpy(dtype=float)[index]
    check(np.isfinite(marks).all() and (marks>0).all(),'Invalid alternative completed mark')
    result['mark_price']=marks
    result['mark_price_source']='latest_completed_mark_close_at_or_before_settlement'
    return result


def phase_inputs(binance,bybit,phase):
    check(phase in PHASES,'Only seven exact fixed phases permitted')
    _,begin,stop,_,valuation=phase
    frames=[];settlements=[]
    for venue,root in [('binance',Path(binance)),('bybit',Path(bybit))]:
        for symbol in SYMBOLS:
            iid=native_id(venue,symbol)
            source=pd.read_parquet(root/symbol/'bars.parquet')
            fund=pd.read_parquet(root/symbol/'funding.parquet')
            check(source.instrument_id.eq(iid).all() and fund.instrument_id.eq(iid).all(),'Phase source native identity differs')
            # Clip BEFORE alternative valuation: the raw START event has no prior mark.
            fund=fund.loc[fund.timestamp.ge(begin)&fund.timestamp.le(stop)].copy()
            if venue=='bybit' and valuation=='alternative':fund=alternative_funding(fund,source)
            frames.append(source.loc[source.timestamp.ge(begin)&source.timestamp.lt(stop)].copy())
            settlements.append(fund)
            del source,fund
    return pd.concat(frames,ignore_index=True),pd.concat(settlements,ignore_index=True)


class SnapshotObserver:
    """Pure post-fill observer; returns the original snapshot unchanged, calls it once."""
    def __init__(self,portfolio):
        self.portfolio=portfolio;self.original=portfolio.snapshot;self.rows=[]
    def __call__(self,timestamp):
        original=self.original(timestamp);p=self.portfolio
        row={'timestamp':timestamp,'cash':original['cash'],'equity':original['equity'],
             'gross_exposure':original['gross_exposure'],'net_exposure':original['net_exposure']}
        for venue in VENUES:
            long,short=p.exposure(venue)
            row.update({f'{venue}_cash':p.cash[venue],f'{venue}_equity':p.venue_equity(venue),
                        f'{venue}_gross_exposure':long+short,f'{venue}_available_margin':p.available(venue),
                        f'{venue}_margin_used':p.margin_used(venue)})
        for symbol in SYMBOLS:
            quantities={};marks={}
            for venue in VENUES:
                iid=native_id(venue,symbol);position=p.positions[iid];mark=p.marks.get(iid,position.average_price)
                quantities[venue]=position.quantity;marks[venue]=mark
                for key,value in [('quantity',position.quantity),('mark',mark),('entry_collateral_field',position.collateral),('current_mark_initial_margin',abs(position.quantity)*mark/p.config.leverage),('unrealized',p.unrealized(iid))]:
                    row[f'{key}_{venue}_{symbol}']=value
            qb,qy=quantities['binance'],quantities['bybit']
            matched=min(abs(qb),abs(qy)) if qb*qy<0 else 0.
            residual_b=max(0,abs(qb)-matched);residual_y=max(0,abs(qy)-matched)
            row[f'matched_native_{symbol}']=matched
            row[f'unmatched_native_{symbol}']=residual_b+residual_y
            row[f'unmatched_dollars_{symbol}']=residual_b*marks['binance']+residual_y*marks['bybit']
            row[f'net_marked_notional_{symbol}']=qb*marks['binance']+qy*marks['bybit']
        self.rows.append(row)
        return original


def parameters(out,phase):
    name,begin,stop,stress,valuation=phase
    return {'family':FAMILY,'phase':name,'begin':str(begin),'stop':str(stop),'stress':stress,'valuation':valuation,
            'source_lock_sha256':digest(Path(out)/'source_lock.json'),'features_sha256':digest(Path(out)/'features.parquet'),
            'feature_receipt_sha256':digest(Path(out)/'feature_receipt.json'),'research_status':'exploratory reused year; candidate26'}


def output_files(destination):
    return {name:digest(Path(destination)/name) for name in OUTPUTS}


def phase_source_manifest(out,valuation):
    return {'source_lock':read(Path(out)/'source_lock.json'),'valuation':valuation,
            'funding_boundary':'actual sourced begin<=timestamp<=stop; Bybit mark valuation explicitly approximate'}


def verify_completed(binance,bybit,out,phase):
    destination=Path(out)/'trials'/phase[0]
    receipt=read(destination/'completion.json');expected=parameters(out,phase)
    check(receipt.get('parameters')==expected,'Cached phase identity/source/features differs')
    check(receipt.get('outputs_sha256')==output_files(destination),'Cached execution output seal differs')
    metadata=read(destination/'metadata.json')
    check(metadata['parameters']==expected and metadata['engine']==asdict(config(phase[3])),'Cached requested configuration differs')
    check(metadata['instruments']==[asdict(x) for x in catalog(binance,bybit,phase[3])],'Cached native instruments/fees differ')
    check(metadata.get('strategy')==CrossVenueCarry.__name__ and metadata.get('strategy_version')==str(CrossVenueCarry.version),'Cached coordinator class/version differs')
    lock=read(Path(out)/'source_lock.json')
    core={name.removeprefix('aster/'):sha for name,sha in lock['sources'].items() if name.startswith('aster/')}
    check(metadata.get('source_sha256')==core,'Cached core source hashes differ from frozen packet')
    manifest=phase_source_manifest(out,phase[4])
    check(metadata.get('source_manifest')==manifest and read(destination/'source_manifest.json')==manifest,'Cached source/valuation manifest differs from frozen packet')
    check(metadata.get('start')==str(phase[1]) and metadata.get('end')==str(phase[2]),'Cached actual execution bounds differ')
    return read(destination/'metrics.json')


def reserve(result):
    fee=sum(abs(p.quantity)*p.mark_price*next(s.taker_bps for s in result.instruments if s.id==p.instrument_id)/10000 for p in result.positions.itertuples())
    slip=sum(abs(p.quantity)*p.mark_price*result.config.slippage_bps/10000 for p in result.positions.itertuples())
    return {'indicative_exit_fee_reserve':fee,'indicative_exit_slippage_reserve':slip,'indicative_exit_reserve_total':fee+slip,
            'return_after_indicative_exit_reserve':(float(result.equity.iloc[-1].equity)-fee-slip)/INITIAL-1}


def run_phase(binance,bybit,out,phase,features=None):
    check(phase in PHASES,'Only seven exact fixed phases permitted')
    guard(binance,bybit,out)
    frozen=verified_features(out)
    if features is not None:pd.testing.assert_frame_equal(features,frozen,check_exact=True)
    destination=Path(out)/'trials'/phase[0]
    if (destination/'completion.json').exists():
        return verify_completed(binance,bybit,out,phase)
    check(not destination.exists(),'Partial trial exists; preserve it before explicit recovery')
    destination.mkdir(parents=True)
    name,begin,stop,stress,valuation=phase
    specs=catalog(binance,bybit,stress)
    bars,funding=phase_inputs(binance,bybit,phase)
    strategy=CrossVenueCarry(frozen.loc[(frozen.index>=begin)&(frozen.index<=stop)],stop)
    del frozen
    engine=Engine(specs,config(stress));observer=SnapshotObserver(engine.portfolio)
    engine.portfolio.snapshot=observer
    started=time.perf_counter();result=engine.run(bars,strategy,funding=funding);elapsed=time.perf_counter()-started
    verify_ledgers(result)
    _,score=export_result(result,destination,bars=bars,funding_source=funding,parameters=parameters(out,phase),
                          data_source='Verified Binance/Bybit native trade, independent mark candles and actual settlements',
                          source_manifest=phase_source_manifest(out,valuation))
    exposure=pd.DataFrame(observer.rows)
    check(pd.DatetimeIndex(exposure.timestamp).equals(pd.DatetimeIndex(result.equity.timestamp))
          and np.array_equal(exposure.equity.to_numpy(),result.equity.equity.to_numpy()),'Pure observer/equity clock differs')
    for venue in VENUES:
        check(np.array_equal(exposure[f'{venue}_cash'],result.equity[f'{venue}_cash'])
              and np.array_equal(exposure[f'{venue}_equity'],result.equity[f'{venue}_equity']),'Venue wallet observer differs')
    for frame,label in [(exposure,'exposure'),(pd.DataFrame(strategy.unmatched),'unmatched'),(pd.DataFrame(strategy.matched_entries),'matched_entries')]:
        frame.to_csv(destination/f'{label}.csv',index=False);frame.to_parquet(destination/f'{label}.parquet',index=False)
    mapping={venue+'_'+symbol:native_id(venue,symbol) for symbol in SYMBOLS for venue in VENUES}
    legs=pd.DataFrame(leg_contributions(result,mapping))
    legs['venue']=legs.instrument_id.str.split(':').str[0]
    legs['pair']=legs.symbol.str.split('_',n=1).str[1]
    legs.to_csv(destination/'leg_contributions.csv',index=False)
    pairs=legs.groupby('pair',sort=False).agg(net_pnl=('net_pnl','sum'),funding_cash=('funding_cash','sum'),fill_count=('fill_count','sum')).reset_index()
    check(len(pairs)==8 and np.isclose(pairs.net_pnl.sum(),result.equity.iloc[-1].equity-INITIAL,atol=1e-7,rtol=1e-10),'Eight-pair/16-leg P&L conservation failed')
    pairs.to_csv(destination/'pair_contributions.csv',index=False)
    dump(destination/'strategy_diagnostics.json',{'events':strategy.diagnostics,'matched_entries':strategy.matched_entries,
          'unmatched_observation_semantics':'strategy callbacks before current open fills; exposure ledger is actual post-fill',
          'terminal_pairs':strategy.pairs,'terminal_targets':strategy.last_targets,'global_abort':strategy.global_abort})
    daily=endpoint_daily(result.equity).dropna();std=float(daily.std(ddof=1))
    score.update(reserve(result));score.update({'sharpe':float(daily.mean()/std*np.sqrt(365)) if std>0 else None,
          'daily_return_count':len(daily),'liquidation_event_count':int(result.events.type.eq('LIQUIDATION').sum()) if not result.events.empty else 0,
          'open_position_count':len(result.positions),'matched_entry_count':len(strategy.matched_entries),
          'matched_pairs':sorted({x['symbol'] for x in strategy.matched_entries}),
          'runtime_seconds':elapsed,'peak_rss_mib_process':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
          'joint_account':True,'separate_venue_wallets':True})
    dump(destination/'metrics.json',score)
    guard(binance,bybit,out)
    dump(destination/'completion.json',{'parameters':parameters(out,phase),'outputs_sha256':output_files(destination)})
    # Break snapshot/portfolio cycles; caller also collects between phases.
    engine.portfolio.snapshot=observer.original
    return score


def conditional_interval(frame):
    values=endpoint_daily(frame).dropna().to_numpy()
    if len(values)<7 or (values<=-1).any():return {'available':False,'reason':'insufficient/invalid daily observations'}
    rng=np.random.default_rng(42);n=len(values)
    starts=rng.integers(0,n,(10000,int(np.ceil(n/7))))
    indices=((starts[:,:,None]+np.arange(7))%n).reshape(10000,-1)[:,:n]
    totals=np.expm1(np.log1p(values[indices]).sum(axis=1))
    return {'available':True,'method':'conditional circular seven-day blocks; 10000 draws; seed42',
            'comparison_count':26,'tails':[.05/52,1-.05/52],
            'return_interval95':np.quantile(totals,[.025,.975]).tolist(),
            'return_interval_bonferroni26':np.quantile(totals,[.05/52,1-.05/52]).tolist(),
            'limitations':'conditional fixed reused year; no cure for adaptive research'}


def summarize(binance,bybit,out):
    guard(binance,bybit,out);verified_features(out)
    trials=Path(out)/'trials'
    check(trials.exists() and {p.name for p in trials.iterdir()}=={p[0] for p in PHASES},'Require seven exact phase directories')
    scores={phase[0]:verify_completed(binance,bybit,out,phase) for phase in PHASES}
    validation=float(np.prod([1+scores[f'validation{k}']['total_return'] for k in (1,2,3)])-1)
    vr=float(np.prod([1+scores[f'validation{k}']['return_after_indicative_exit_reserve'] for k in (1,2,3)])-1)
    base=scores['evaluation'];frame=pd.read_parquet(trials/'evaluation/equity.parquet')
    series=frame.set_index('timestamp').equity
    points=[float(series.asof(EVAL_START+pd.DateOffset(months=k))) for k in range(4)]
    months=[points[k+1]/points[k]-1 for k in range(3)]
    matched=pd.read_parquet(trials/'evaluation/matched_entries.parquet')
    participants=set(matched.symbol) if len(matched) else set()
    check(participants==set(base['matched_pairs']),'Matched entry breadth differs from sealed ledger')
    gates={'positive_compounded_validation':validation>0,'positive_validation_after_exit_reserve':vr>0,
           'two_positive_anchored_months':sum(x>0 for x in months)>=2,
           'daily_sharpe_at_least_half':base['sharpe'] is not None and base['sharpe']>=.5,
           'minute_drawdown_at_most_twenty_percent':base['max_drawdown']<=.2,
           'no_liquidation_all_seven_runs':sum(s['liquidation_event_count'] for s in scores.values())==0,
           'four_matched_pairs_including_both_doge_and_pepe':len(participants)>=4 and {'DOGEUSDT','PEPEUSDT'}<=participants}
    for name in ('evaluation','evaluation_stress','evaluation_alternative','evaluation_alternative_stress'):
        gates['positive_'+name]=scores[name]['total_return']>0
        gates['positive_'+name+'_after_exit_reserve']=scores[name]['return_after_indicative_exit_reserve']>0
    summary={'family':FAMILY,'candidate_count_cumulative':26,'research_status':'exploratory reused year; no untouched holdout',
             'passes_hurdles':all(gates.values()),'gates':gates,'failed_gates':[k for k,v in gates.items() if not v],
             'validation_compounded_return':validation,'validation_after_exit_reserve':vr,'scores':scores,
             'anchored_month_returns':months,'actual_matched_pairs':sorted(participants),
             'evaluation_leg_contributions':pd.read_csv(trials/'evaluation/leg_contributions.csv').to_dict('records'),
             'evaluation_pair_contributions':pd.read_csv(trials/'evaluation/pair_contributions.csv').to_dict('records'),
             'conditional_interval':conditional_interval(frame),'full_resolution_evaluation_equity_sha256':digest(trials/'evaluation/equity.parquet'),
             'source_lock_sha256':digest(Path(out)/'source_lock.json'),'features_sha256':digest(Path(out)/'features.parquet'),
             'publication_status':'UNPUBLISHED: separate independent seven-phase reconstruction receipt required'}
    dump(Path(out)/'summary.json',summary)
    return summary


def synthetic_memory_benchmark(minutes=2000):
    """Observer-only constant synthetic state; no source files/features/Engine runs."""
    import tracemalloc
    from aster.backtest.portfolio import Portfolio
    check(isinstance(minutes,int) and 1 <= minutes <= 10000,'Bounded synthetic benchmark')
    specs=[Instrument(id=native_id(v,s),exchange=v,symbol=native_id(v,s).split(':')[-1],
                      market_type='perpetual',base='1000PEPE' if s=='PEPEUSDT' else s[:-4],quote='USDT')
           for v in VENUES for s in SYMBOLS]
    portfolio=Portfolio(specs,config(False))
    for spec in specs:portfolio.marks[spec.id]=100.
    observer=SnapshotObserver(portfolio)
    tracemalloc.start();started=time.perf_counter()
    for clock in pd.date_range(VALID_START,periods=minutes,freq='min'):observer(clock)
    frame=pd.DataFrame(observer.rows)
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    return {'synthetic':True,'rows':len(frame),'columns':len(frame.columns),
            'observer_and_frame_peak_allocated_mib':peak/1048576,'frame_mib':frame.memory_usage(deep=True).sum()/1048576,
            'elapsed_seconds':time.perf_counter()-started,'scope':'Synthetic observer only; excludes real Engine, bars, features and exports; not a full-phase memory guarantee'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binance',default='data_cache/minute-perpetual-1y')
    parser.add_argument('--bybit',default='data_cache/minute-bybit-1y')
    parser.add_argument('--out',default='results/cross-venue-funding-1y-v1')
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--freeze-only',action='store_true');action.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if args.freeze_only:freeze(args.binance,args.bybit,args.out)
    else:
        guard(args.binance,args.bybit,args.out)
        generate_features(args.binance,args.bybit,args.out)
        for phase in PHASES:
            print('Executing fixed phase',phase[0],flush=True)
            run_phase(args.binance,args.bybit,args.out,phase);gc.collect()
        summarize(args.binance,args.bybit,args.out)


if __name__=='__main__':main()
