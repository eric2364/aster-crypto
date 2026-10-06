"""Candidate27 fixed joint funding rank. Freeze BEFORE features; no fitting/selection."""
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
from examples.funding_rank.strategy import FundingRankPortfolio

REPO=Path(__file__).resolve().parents[2]
SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
START=pd.Timestamp('2025-10-05',tz='UTC')
END=pd.Timestamp('2026-10-05',tz='UTC')
VALID_START=pd.Timestamp('2026-04-05',tz='UTC')
EVAL_START=pd.Timestamp('2026-07-05',tz='UTC')
INITIAL=100000.
FAMILY='joint_cross_sectional_funding_rank'
PHASES=[(f'validation{k+1}',VALID_START+pd.DateOffset(months=k),VALID_START+pd.DateOffset(months=k+1),False) for k in range(3)]+[
 ('evaluation',EVAL_START,END,False),('evaluation_stress',EVAL_START,END,True)]
LEDGERS=('equity','fills','trades','funding','events','positions')
OUTPUTS=tuple([f'{n}.{ext}' for n in LEDGERS for ext in ('csv','parquet')]+[
 'metadata.json','metrics.json','source_manifest.json','quality.json','exposure.csv','exposure.parquet',
 'leg_contributions.csv','strategy_diagnostics.json','completed_baskets.json','proposal_ledger.json',
 'rejections.json','terminal_orders.json','daily_returns.csv'])


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


def catalog(cache,stress=False):
    specs=[Instrument(**x) for x in read(Path(cache)/'instruments.json')]
    check(len(specs)==8 and {s.id for s in specs}=={native_id('binance',s) for s in SYMBOLS},'Exact eight native Binance instruments required')
    for s in specs:
        check(s.exchange=='binance' and s.market_type=='perpetual' and s.contract_type=='linear'
              and s.quote=='USDT' and s.symbol==s.id.split(':')[-1] and s.base==s.symbol[:-4]
              and s.multiplier==1,'Native identity or quantity units differ')
    fee=10 if stress else 5
    by_id={s.id:replace(s,maker_bps=fee,taker_bps=fee) for s in specs}
    return [by_id[native_id('binance',s)] for s in SYMBOLS]


def config(stress):
    return SimulationConfig(initial_balances={'binance':INITIAL},margin_mode='cross',leverage=1,
        max_gross_leverage=.5,max_position_pct=.25,fill_model='volume_aware',record_every=1,
        slippage_bps=16 if stress else 8,participation=.025 if stress else .05,
        execution_delay_bars=1 if stress else 0)


def identity(cache):
    cache=Path(cache)
    sources=[*sorted((REPO/'aster').rglob('*.py')),
        *[REPO/'examples/funding_rank'/n for n in ('run.py','signals.py','strategy.py','proposed_protocol.md')],
        REPO/'examples/cross_venue/signals.py',
        *[REPO/'examples/minute_research'/n for n in ('download.py','downloadcarry.py')]]
    inputs=[cache/n for n in ('instruments.json','cross_mapping.json','instrument_source_manifest.json','exchange_info_current.json')]
    for symbol in SYMBOLS:
        inputs += [cache/symbol/n for n in ('bars.parquet','funding.parquet','source_manifest.json')]
        manifest=read(cache/symbol/'source_manifest.json')
        inputs += [cached_path(p['cache_file']) for p in manifest['archives']+manifest['funding_pages']]
    return {'sources':{str(p.relative_to(REPO)):digest(p) for p in sources},
            'inputs':{str(p.resolve()):digest(p) for p in sorted(set(inputs))},
            'runtime':{'python':sys.version,**{p:importlib.metadata.version(p) for p in ('numpy','pandas','pyarrow','scipy','plotly')}},
            'family':FAMILY,'candidate_count_cumulative':27,
            'phases':[[n,str(b),str(e),s] for n,b,e,s in PHASES]}


def freeze(cache,out):
    cache,out=Path(cache),Path(out);lock=identity(cache)
    specs={s.id:s for s in catalog(cache)}
    verification=[verify(cache,s,specs) for s in SYMBOLS]
    check(identity(cache)==lock,'Source/input/runtime changed during source verification')
    lock['input_verification']=verification
    if (out/'source_lock.json').exists():check(read(out/'source_lock.json')==lock,'Existing frozen packet differs')
    else:
        check(not out.exists() or not any(out.iterdir()),'Refuse nonempty unsealed experiment')
        out.mkdir(parents=True,exist_ok=True)
        for name,sha in lock['sources'].items():
            target=out/'executed_source'/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((REPO/name).read_bytes());check(digest(target)==sha,'Source changed while archiving')
        dump(out/'input_verification.json',verification);dump(out/'source_lock.json',lock)
    guard(cache,out)
    return lock


def guard(cache,out):
    out=Path(out);check((out/'source_lock.json').exists(),'Freeze BEFORE historical features or Engine execution')
    lock=read(out/'source_lock.json')
    check(identity(cache)=={k:v for k,v in lock.items() if k!='input_verification'},'Frozen source/input/runtime changed')
    for name,sha in lock['sources'].items():check(digest(out/'executed_source'/name)==sha,'Executed source archive changed')
    verification=read(out/'input_verification.json')
    check(verification==lock['input_verification'] and len(verification)==8
          and {v['spot_symbol'] for v in verification}==set(SYMBOLS),'Incomplete or changed full-universe verification')
    return lock


def generate_features(cache,out):
    guard(cache,out);out=Path(out)
    if (out/'features.parquet').exists() or (out/'feature_receipt.json').exists():return verified_features(out)
    # Import only the fixed builder, after the required freeze; no estimation graph.
    from examples.funding_rank.signals import build_features
    bars={};funding={}
    for symbol in SYMBOLS:
        iid=native_id('binance',symbol);folder=Path(cache)/symbol
        bars[iid]=pd.read_parquet(folder/'bars.parquet',columns=['timestamp','duration_seconds','instrument_id','close'])
        frame=pd.read_parquet(folder/'funding.parquet')
        # Authentic raw API may contain END+milliseconds; raw bytes remain locked.
        funding[iid]=frame.loc[frame.timestamp.ge(START)&frame.timestamp.lt(END)].copy()
    features=build_features(bars,funding);del bars,funding;gc.collect()
    features.to_parquet(out/'features.parquet',index=True)
    dump(out/'feature_receipt.json',{'source_lock_sha256':digest(out/'source_lock.json'),
        'features_sha256':digest(out/'features.parquet'),'rows':len(features),'columns':list(features.columns),
        'availability_assumptions':features.attrs,'predictor_boundary':'START<=settlement<END; raw source remains preserved'})
    guard(cache,out)
    return verified_features(out)


def verified_features(out,supplied=None):
    out=Path(out);path=out/'features.parquet';receipt_path=out/'feature_receipt.json'
    check(path.exists() and receipt_path.exists(),'Missing/partial immutable feature packet')
    receipt=read(receipt_path)
    check(receipt['source_lock_sha256']==digest(out/'source_lock.json') and receipt['features_sha256']==digest(path),'Feature/source seal mismatch')
    frame=pd.read_parquet(path)
    from examples.funding_rank.signals import ASSUMPTIONS
    check(len(frame)==receipt['rows'] and list(frame.columns)==receipt['columns']
          and frame.attrs==receipt['availability_assumptions'],'Feature schema or assumptions changed')
    check(frame.attrs==ASSUMPTIONS,'Feature assumptions differ from fixed source definition')
    expected=pd.date_range(START+pd.Timedelta(minutes=2),END,freq='min',inclusive='left').as_unit('ns')
    check(pd.DatetimeIndex(frame.index).as_unit('ns').equals(expected),'Feature minute availability grid differs')
    check(set(frame.columns)=={f'{field}_{s}' for s in SYMBOLS for field in ('price','yield','valid')},'Exact 24 feature columns required')
    daily=(frame.index.hour==0)&(frame.index.minute==5)
    for symbol in SYMBOLS:
        valid=frame[f'valid_{symbol}'];price=frame[f'price_{symbol}'];yield_=frame[f'yield_{symbol}']
        check(pd.api.types.is_bool_dtype(valid.dtype) and not valid.isna().any(),'Validity fields must be nonmissing booleans')
        check(pd.api.types.is_numeric_dtype(price.dtype) and not pd.api.types.is_bool_dtype(price.dtype)
              and np.isfinite(price.to_numpy(dtype=float)).all() and price.gt(0).all(),'Feature prices must be finite positive numbers')
        check(pd.api.types.is_numeric_dtype(yield_.dtype) and not pd.api.types.is_bool_dtype(yield_.dtype),'Yield fields must be numeric')
        flags=valid.to_numpy(dtype=bool);values=yield_.to_numpy(dtype=float)
        check(not flags[~daily].any() and np.isnan(values[~daily]).all(),'Off-daily yields must be missing and invalid')
        check(np.isfinite(values[daily&flags]).all() and np.isnan(values[daily&~flags]).all(),'Daily yield/validity semantics differ')
    if supplied is not None:
        pd.testing.assert_frame_equal(supplied,frame,check_exact=True,check_freq=False)
        check(supplied.attrs==frame.attrs,'Caller feature assumptions differ')
    return frame


def phase_inputs(cache,phase):
    check(phase in PHASES,'Only five exact fixed phases permitted')
    _,begin,stop,_=phase;bars=[];funding=[]
    expected=pd.date_range(START,END,freq='min',inclusive='left').as_unit('ns')
    for symbol in SYMBOLS:
        iid=native_id('binance',symbol);folder=Path(cache)/symbol
        source=pd.read_parquet(folder/'bars.parquet');fund=pd.read_parquet(folder/'funding.parquet')
        check(source.instrument_id.eq(iid).all() and fund.instrument_id.eq(iid).all(),'Wrong phase native identity')
        check(pd.DatetimeIndex(source.timestamp).as_unit('ns').equals(expected)
              and source.duration_seconds.eq(60).all(),'Exact full-year source minute grid required')
        bars.append(source.loc[source.timestamp.ge(begin)&source.timestamp.lt(stop)].copy())
        funding.append(fund.loc[fund.timestamp.ge(begin)&fund.timestamp.le(stop)].copy())
    return pd.concat(bars,ignore_index=True),pd.concat(funding,ignore_index=True)


class SnapshotObserver:
    """One original call, post-fill state only; capture orders BEFORE core END cancellation."""
    def __init__(self,engine):
        self.engine=engine;self.portfolio=engine.portfolio;self.original=self.portfolio.snapshot
        self.rows=[];self.last_orders=[]
    def __call__(self,timestamp):
        original=self.original(timestamp);p=self.portfolio
        live=[forensic_normalize(o) for o in self.engine.orders.values() if o.status in ('accepted','partial')]
        row={'timestamp':timestamp,'cash':original['cash'],'equity':original['equity'],
            'gross_exposure':original['gross_exposure'],'net_exposure':original['net_exposure'],
            'available_margin':p.available('binance'),'margin_used':p.margin_used('binance'),
            'maintenance_margin':p.maintenance_margin('binance'),'live_order_count':len(live),
            'binance_cash':p.cash['binance'],'binance_equity':p.venue_equity('binance'),
            'binance_gross_exposure':sum(p.exposure('binance')),'binance_available_margin':p.available('binance'),
            'binance_margin_used':p.margin_used('binance'),'binance_maintenance_margin':p.maintenance_margin('binance')}
        for symbol in SYMBOLS:
            iid=native_id('binance',symbol);position=p.positions[iid];mark=p.marks.get(iid,position.average_price)
            for field,value in [('quantity',position.quantity),('mark',mark),('unrealized',p.unrealized(iid)),
                ('entry_collateral_field',position.collateral),('signed_notional',position.quantity*mark),
                ('current_mark_initial_margin',abs(position.quantity)*mark/p.config.leverage)]:row[f'{field}_{symbol}']=value
        self.rows.append(row);self.last_orders=live
        return original


def parameters(out,phase):
    name,begin,stop,stress=phase
    return {'family':FAMILY,'phase':name,'begin':str(begin),'stop':str(stop),'stress':stress,
        'source_lock_sha256':digest(Path(out)/'source_lock.json'),'features_sha256':digest(Path(out)/'features.parquet'),
        'feature_receipt_sha256':digest(Path(out)/'feature_receipt.json'),'research_status':'exploratory reused year; candidate27'}


def source_manifest(out):
    return {'source_lock':read(Path(out)/'source_lock.json'),
        'funding_boundary':'actual sourced begin<=timestamp<=stop; predictor excludes END; original mark and native units',
        'terminal_order_semantics':'captured at final equity clock BEFORE automatic end_of_data cancellations'}


def output_files(destination):return {name:digest(Path(destination)/name) for name in OUTPUTS}


def verify_completed(cache,out,phase):
    check(phase in PHASES,'Only exact approved phase tuples permitted')
    destination=Path(out)/'trials'/phase[0];receipt=read(destination/'completion.json');expected=parameters(out,phase)
    check(receipt.get('parameters')==expected,'Cached requested phase/source/features differs')
    check(receipt.get('outputs_sha256')==output_files(destination),'Cached output seal differs')
    metadata=read(destination/'metadata.json')
    check(metadata['parameters']==expected and metadata['engine']==asdict(config(phase[3])),'Cached phase configuration differs')
    check(metadata['instruments']==[asdict(s) for s in catalog(cache,phase[3])],'Cached native instruments/fees differ')
    check(metadata.get('strategy')==FundingRankPortfolio.__name__ and metadata.get('strategy_version')==str(FundingRankPortfolio.version),'Cached coordinator class/version differs')
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


def basket_participation(completed):
    participants=set();generations=set()
    for row in completed:
        proposal=row['proposal'];longs=proposal['longs'];shorts=proposal['shorts'];targets=row['targets']
        check(len(longs)==len(shorts)==2 and len(set(longs+shorts))==4 and set(longs+shorts)<=set(SYMBOLS),'Invalid completed basket membership')
        expected={native_id('binance',s):1 if s in longs else -1 for s in longs+shorts}
        check(set(targets)=={native_id('binance',s) for s in SYMBOLS},'Completed targets must retain all eight native instruments')
        check(all(np.isfinite(q) and (q*expected[i]>0 if i in expected else q==0) for i,q in targets.items()),'Invalid completed basket signed targets')
        check(row['generation'] not in generations,'Duplicate completed entry generation')
        generations.add(row['generation']);participants.update(longs+shorts)
    return participants,len(generations)


def run_phase(cache,out,phase,features=None):
    check(phase in PHASES,'Only five fixed phases permitted');guard(cache,out)
    frozen=verified_features(out,features);destination=Path(out)/'trials'/phase[0]
    if (destination/'completion.json').exists():return verify_completed(cache,out,phase)
    check(not destination.exists(),'Partial trial exists; preserve before explicit recovery')
    destination.mkdir(parents=True);_,begin,stop,stress=phase
    bars,funding=phase_inputs(cache,phase)
    strategy=FundingRankPortfolio(frozen.loc[(frozen.index>=begin)&(frozen.index<stop)],stop);del frozen
    engine=Engine(catalog(cache,stress),config(stress));observer=SnapshotObserver(engine);engine.portfolio.snapshot=observer
    started=time.perf_counter();result=engine.run(bars,strategy,funding=funding);elapsed=time.perf_counter()-started
    verify_ledgers(result)
    _,score=export_result(result,destination,bars=bars,funding_source=funding,parameters=parameters(out,phase),
        data_source='Verified native Binance perpetual minute trade/mark bars and actual funding settlements',source_manifest=source_manifest(out))
    exposure=pd.DataFrame(observer.rows)
    check(pd.DatetimeIndex(exposure.timestamp).equals(pd.DatetimeIndex(result.equity.timestamp))
          and np.array_equal(exposure.equity.to_numpy(),result.equity.equity.to_numpy()),'Pure observer/equity clocks differ')
    exposure.to_csv(destination/'exposure.csv',index=False);exposure.to_parquet(destination/'exposure.parquet',index=False)
    mapping={s:native_id('binance',s) for s in SYMBOLS}
    pd.DataFrame(leg_contributions(result,mapping)).to_csv(destination/'leg_contributions.csv',index=False)
    completed=forensic_normalize(strategy.completed_baskets);participants,generations=basket_participation(completed)
    diagnostics=forensic_normalize(strategy.diagnostics)
    dump(destination/'completed_baskets.json',completed)
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
        'completed_basket_count':generations,'completed_participants':sorted(participants),
        'joint_account':True,'runtime_seconds':elapsed,'peak_rss_mib_process':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024})
    dump(destination/'metrics.json',score);guard(cache,out)
    dump(destination/'completion.json',{'parameters':parameters(out,phase),'outputs_sha256':output_files(destination)})
    engine.portfolio.snapshot=observer.original
    return score


def conditional_interval(frame):
    values=endpoint_daily(frame).dropna().to_numpy()
    if len(values)<7 or not np.isfinite(values).all() or (values<=-1).any():return {'available':False,'reason':'insufficient/invalid daily observations'}
    rng=np.random.default_rng(42);n=len(values);starts=rng.integers(0,n,(10000,int(np.ceil(n/7))))
    indices=((starts[:,:,None]+np.arange(7))%n).reshape(10000,-1)[:,:n]
    totals=np.expm1(np.log1p(values[indices]).sum(axis=1))
    return {'available':True,'comparison_count':27,'method':'conditional circular seven-day blocks;10000 draws;seed42',
        'tails':[.05/54,1-.05/54],'return_interval95':np.quantile(totals,[.025,.975]).tolist(),
        'return_interval_bonferroni27':np.quantile(totals,[.05/54,1-.05/54]).tolist(),
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


def summarize(cache,out):
    guard(cache,out);verified_features(out);out=Path(out);trials=out/'trials'
    check(trials.exists() and {p.name for p in trials.iterdir()}=={p[0] for p in PHASES},'Require all five exact trials; no hidden variants')
    scores={p[0]:verify_completed(cache,out,p) for p in PHASES}
    frame=pd.read_parquet(trials/'evaluation/equity.parquet');series=frame.set_index('timestamp').equity
    points=[float(series.asof(EVAL_START+pd.DateOffset(months=k))) for k in range(4)]
    check(np.isfinite(points).all() and min(points)>0,'Missing/nonpositive anchored month equity')
    months=[points[k+1]/points[k]-1 for k in range(3)]
    participants,generations=basket_participation(read(trials/'evaluation/completed_baskets.json'))
    check(sorted(participants)==scores['evaluation']['completed_participants'] and generations==scores['evaluation']['completed_basket_count'],'Completed breadth differs from sealed ledger')
    validation,vr,gates=gate_results(scores,months,participants,generations)
    summary={'family':FAMILY,'candidate_count_cumulative':27,'research_status':'exploratory reused year; no untouched holdout',
        'passes_hurdles':all(gates.values()),'gates':gates,'failed_gates':[k for k,v in gates.items() if not v],
        'validation_compounded_return':validation,'validation_after_exit_reserve':vr,'scores':scores,
        'anchored_month_returns':months,'completed_participants':sorted(participants),'completed_basket_count':generations,
        'all_evaluation_leg_contributions':pd.read_csv(trials/'evaluation/leg_contributions.csv').to_dict('records'),
        'conditional_interval':conditional_interval(frame),'full_resolution_evaluation_equity_sha256':digest(trials/'evaluation/equity.parquet'),
        'source_lock_sha256':digest(out/'source_lock.json'),'features_sha256':digest(out/'features.parquet'),
        'feature_receipt_sha256':digest(out/'feature_receipt.json'),
        'publication_status':'UNPUBLISHED: independent policy, trajectory and summary reconstruction required'}
    dump(out/'summary.json',summary);guard(cache,out)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cache',default='data_cache/minute-perpetual-1y')
    parser.add_argument('--out',default='results/funding-rank-1y-v1')
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--freeze-only',action='store_true');action.add_argument('--execute',action='store_true');action.add_argument('--analysis-only',action='store_true')
    args=parser.parse_args()
    if args.freeze_only:freeze(args.cache,args.out);print('Sources/inputs frozen; no features or Engine execution.');return
    guard(args.cache,args.out)
    if args.execute:
        generate_features(args.cache,args.out)
        for phase in PHASES:
            print('Executing fixed phase',phase[0],flush=True);run_phase(args.cache,args.out,phase);gc.collect()
    summarize(args.cache,args.out)


if __name__=='__main__':main()
