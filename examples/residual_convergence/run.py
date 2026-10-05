"""One exploratory residual family. Freeze/audit BEFORE --execute; no fitting on import."""
from __future__ import annotations
import argparse
from dataclasses import replace, asdict, is_dataclass
import hashlib
import gc
import importlib.metadata
import json
from pathlib import Path
import sys
import time
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aster.analytics import metrics, daily_returns, json_safe
from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, SimulationConfig
from aster.reproducibility import export_result, verify_ledgers
from examples.minute_research.downloadcarry import verify, cached_path
from examples.residual_convergence.signals import (
    SYMBOLS, ALTS, START, TRAIN_END, EVAL_START, END,
    hourly_prices, fit_models, build_features)
from examples.residual_convergence.strategy import ResidualPortfolio

FAMILY = 'btc_eth_hedged_residual_convergence'
INITIAL = 100000.
PHASES = [(f'validation{k+1}', TRAIN_END+pd.DateOffset(months=k),
           TRAIN_END+pd.DateOffset(months=k+1), False) for k in range(3)] + [
    ('evaluation', EVAL_START, END, False), ('evaluation_stress', EVAL_START, END, True)]
LEDGERS = ('equity', 'fills', 'trades', 'funding', 'events', 'positions')


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


def catalog(cache):
    return {spec.id: spec for spec in [Instrument(**item) for item in read(cache/'instruments.json')]}


def mappings(cache):
    items = read(cache/'cross_mapping.json')['mapping']
    result = {item['spot_symbol']: item['perpetual_instrument_id'] for item in items}
    if set(result) != set(SYMBOLS): raise ValueError('Exactly the declared eight underlying mappings required')
    if result['PEPEUSDT'] != 'binance:perpetual:1000PEPEUSDT':
        raise ValueError('PEPE must retain native 1000PEPE contract identity')
    return result


def identity(cache):
    source_folder=Path('examples/residual_convergence')
    sources = [source_folder/'run.py', source_folder/'signals.py',
               source_folder/'strategy.py', source_folder/'proposed_protocol.md',
               Path('examples/minute_research/downloadcarry.py'), *sorted(Path('aster').rglob('*.py'))]
    inputs = [cache/'instruments.json', cache/'cross_mapping.json', cache/'instrument_source_manifest.json']
    inputs += [cache/symbol/name for symbol in SYMBOLS
               for name in ('bars.parquet', 'funding.parquet', 'source_manifest.json')]
    for symbol in SYMBOLS:
        manifest=read(cache/symbol/'source_manifest.json')
        inputs += [cached_path(entry['cache_file']) for entry in
                   manifest['archives']+manifest['funding_pages']]
    inputs=list(dict.fromkeys(inputs))
    return {'sources': {str(path): digest(path) for path in sources},
            'inputs': {str(path): digest(path) for path in inputs},
            'runtime': {'python': sys.version,
                        **{name: importlib.metadata.version(name) for name in
                           ('numpy', 'pandas', 'pyarrow', 'statsmodels', 'scipy', 'plotly')}},
            'family': FAMILY, 'candidate_count_cumulative': 25,
            'phases': [[name,str(begin),str(stop),stress] for name,begin,stop,stress in PHASES]}


def freeze(cache, out):
    """Verify source data, then archive a pre-estimation, immutable source packet."""
    cache, out = Path(cache), Path(out)
    lock = identity(cache)
    if lock['runtime']['statsmodels'] != '0.14.6': raise RuntimeError('Protocol pins statsmodels 0.14.6')
    specs = catalog(cache); mapping = mappings(cache)
    if any(iid not in specs for iid in mapping.values()): raise ValueError('Native catalog mapping absent')
    verification = [verify(cache, symbol, specs) for symbol in SYMBOLS]
    lock['input_verification'] = verification
    path = out/'source_lock.json'
    if path.exists():
        if read(path) != lock: raise RuntimeError('Frozen source/input/runtime changed; preserve original experiment')
    else:
        if out.exists() and any(out.iterdir()): raise RuntimeError('Refuse to freeze into a nonempty unsealed directory')
        out.mkdir(parents=True, exist_ok=True)
        dump(path,lock)
        dump(out/'input_verification.json',verification)
        for name in lock['sources']:
            archive = out/'executed_source'/name
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(Path(name).read_bytes())
    guard(cache,out)
    return lock


def guard(cache, out):
    path = Path(out)/'source_lock.json'
    if not path.exists(): raise RuntimeError('Freeze sources before any historical estimation')
    lock = read(path)
    if identity(Path(cache)) != {k:v for k,v in lock.items() if k!='input_verification'}:
        raise RuntimeError('Source, data or numerical runtime differs from pre-fit lock')
    for name, sha in lock['sources'].items():
        if digest(Path(out)/'executed_source'/name) != sha: raise RuntimeError('Executed source archive mismatch')
    verification = read(Path(out)/'input_verification.json')
    if verification != lock['input_verification']: raise RuntimeError('Input verification receipt differs from freeze')
    if len(verification)!=8 or {v['spot_symbol'] for v in verification}!=set(SYMBOLS):
        raise RuntimeError('Missing full-universe source verification')
    return lock


def available_prices(cache):
    """Native completed closes only; availability is raw interval start + two minutes."""
    cache = Path(cache); mapping = mappings(cache)
    expected = pd.date_range(START,END,freq='1min',inclusive='left').as_unit('ns')
    columns = {}
    for symbol in SYMBOLS:
        bars = pd.read_parquet(cache/symbol/'bars.parquet',
                               columns=['timestamp','duration_seconds','instrument_id','close'])
        clock = pd.DatetimeIndex(pd.to_datetime(bars.timestamp,utc=True)).as_unit('ns')
        if not clock.equals(expected) or not bars.duration_seconds.eq(60).all():
            raise ValueError('Exact last-year minute grid required; no interpolation')
        if not bars.instrument_id.eq(mapping[symbol]).all(): raise ValueError('Native source identity mismatch')
        values = bars.close.to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values<=0).any(): raise ValueError('Invalid observed trade closes')
        columns[symbol] = values
    return pd.DataFrame(columns,index=expected+pd.Timedelta(minutes=2))


def estimate(cache,out):
    guard(cache,out)  # Deliberately BEFORE fit_models or any historical feature generation.
    path = Path(out)/'models.json'; receipt = Path(out)/'estimation_receipt.json'
    if path.exists() or receipt.exists():
        if not (path.exists() and receipt.exists()): raise RuntimeError('Incomplete estimation artifacts')
        prior = read(receipt)
        if prior != {'source_lock_sha256':digest(Path(out)/'source_lock.json'),'models_sha256':digest(path)}:
            raise RuntimeError('Frozen estimates changed')
        return read(path)
    prices = available_prices(cache)
    training = hourly_prices(prices.loc[prices.index<TRAIN_END])
    models = fit_models(training)
    dump(path,models)
    dump(receipt,{'source_lock_sha256':digest(Path(out)/'source_lock.json'),'models_sha256':digest(path)})
    guard(cache,out)
    return models


def verified_models(out, supplied=None):
    out=Path(out); path=out/'models.json'; receipt=out/'estimation_receipt.json'
    if not (path.exists() and receipt.exists()): raise RuntimeError('Require complete frozen estimation artifacts')
    expected={'source_lock_sha256':digest(out/'source_lock.json'),'models_sha256':digest(path)}
    if read(receipt)!=expected: raise RuntimeError('Estimation receipt source/model mismatch')
    models=read(path)
    if supplied is not None and json_safe(supplied)!=models:
        raise RuntimeError('Caller model differs from frozen estimation artifact')
    return models


def verify_phase_metadata(destination, phase):
    name,begin,stop,stress=phase
    parameters=read(Path(destination)/'metadata.json')['parameters']
    expected={'family':FAMILY,'phase':name,'begin':str(begin),'stop':str(stop),'stress':stress}
    if any(parameters.get(k)!=v for k,v in expected.items()):
        raise RuntimeError('Sealed trial metadata differs from requested phase')


class SnapshotObserver:
    """Pure observer: original snapshot is returned unchanged, after recording state.

    Strategy callbacks precede fills. The portfolio snapshot clock instead gives
    the actual state matching equity, including partial fills and funding marks.
    """
    def __init__(self, portfolio, mapping, models):
        self.portfolio=portfolio; self.mapping=mapping; self.models=models; self.rows=[]
        self.original=portfolio.snapshot
    def __call__(self,timestamp):
        row=self.original(timestamp)
        observed={'timestamp':timestamp,'cash':row['cash'],'equity':row['equity'],
                  'gross_exposure':row['gross_exposure'],'net_exposure':row['net_exposure']}
        signed={}
        for symbol,iid in self.mapping.items():
            position=self.portfolio.positions[iid]
            mark=self.portfolio.marks.get(iid,position.average_price)
            signed[symbol]=position.quantity*mark
            observed.update({f'quantity_{symbol}':position.quantity,f'mark_{symbol}':mark,
                             f'collateral_{symbol}':position.collateral,
                             f'unrealized_{symbol}':self.portfolio.unrealized(iid)})
        for factor,key in [('BTCUSDT','beta_btc'),('ETHUSDT','beta_eth')]:
            exposure=signed[factor]
            for alt in ALTS:
                beta=self.models['assets'][alt].get(key)
                if signed[alt]:
                    if beta is None or not np.isfinite(beta): raise AssertionError('Actual position lacks frozen factor beta')
                    exposure+=signed[alt]*beta
            observed[f'frozen_factor_exposure_{factor}']=exposure
        self.rows.append(observed)
        return row


def indicative_reserve(result):
    fee=sum(abs(p.quantity)*p.mark_price*next(s.taker_bps for s in result.instruments if s.id==p.instrument_id)/10000
            for p in result.positions.itertuples())
    slip=sum(abs(p.quantity)*p.mark_price*result.config.slippage_bps/10000 for p in result.positions.itertuples())
    return {'indicative_exit_fee_reserve':fee,'indicative_exit_slippage_reserve':slip,
            'indicative_exit_reserve_total':fee+slip,
            'return_after_indicative_exit_reserve':(float(result.equity.iloc[-1].equity)-fee-slip)/INITIAL-1}


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


def output_files(destination):
    names=[f'{name}.{extension}' for name in LEDGERS for extension in ('csv','parquet')]
    names+=['metadata.json','metrics.json','source_manifest.json','quality.json',
            'exposure.parquet','exposure.csv','leg_contributions.csv','strategy_diagnostics.json']
    return {name:digest(Path(destination)/name) for name in names}


def run_phase(cache,out,models,phase):
    if phase not in PHASES: raise ValueError('Only the exact five predeclared joint phases are permitted')
    name,begin,stop,stress=phase
    guard(cache,out)
    verified_models(out,models)
    destination=Path(out)/'trials'/name
    if (destination/'completion.json').exists():
        receipt=read(destination/'completion.json')
        if receipt['phase']!=name or receipt['stress']!=stress: raise RuntimeError('Cached phase identity mismatch')
        verify_phase_metadata(destination,phase)
        if receipt['outputs_sha256']!=output_files(destination) or receipt['source_lock_sha256']!=digest(Path(out)/'source_lock.json'):
            raise RuntimeError('Cached phase output/source seal differs')
        if receipt['models_sha256']!=digest(Path(out)/'models.json'): raise RuntimeError('Cached phase model mismatch')
        return read(destination/'metrics.json')
    if destination.exists(): raise RuntimeError('Partial trial exists; preserve and explicitly recover it before rerunning')
    cache=Path(cache); mapping=mappings(cache); specs=catalog(cache)
    specs=[replace(specs[mapping[s]],maker_bps=10 if stress else 5,taker_bps=10 if stress else 5) for s in SYMBOLS]
    prices=available_prices(cache)
    features=build_features(prices.loc[(prices.index>=TRAIN_END)&(prices.index<=stop)],models)
    del prices
    strategy=ResidualPortfolio(models,features,stop); del features
    frames=[]; settlements=[]
    for symbol in SYMBOLS:
        bars=pd.read_parquet(cache/symbol/'bars.parquet')
        frames.append(bars.loc[bars.timestamp.ge(begin)&bars.timestamp.lt(stop)].copy())
        funding=pd.read_parquet(cache/symbol/'funding.parquet')
        settlements.append(funding.loc[funding.timestamp.ge(begin)&funding.timestamp.le(stop)].copy())
    bars=pd.concat(frames,ignore_index=True); funding=pd.concat(settlements,ignore_index=True)
    del frames,settlements
    config=SimulationConfig(initial_balances={'binance':INITIAL},leverage=1,margin_mode='isolated',
                            max_gross_leverage=1,max_position_pct=.5,fill_model='volume_aware',
                            participation=.025 if stress else .05,slippage_bps=16 if stress else 8,
                            execution_delay_bars=1 if stress else 0,record_every=1)
    engine=Engine(specs,config)
    observer=SnapshotObserver(engine.portfolio,mapping,models)
    engine.portfolio.snapshot=observer
    started=time.perf_counter()
    result=engine.run(bars,strategy,funding=funding)
    elapsed=time.perf_counter()-started
    verify_ledgers(result)
    parameters={'family':FAMILY,'phase':name,'begin':str(begin),'stop':str(stop),'stress':stress,
                'source_lock_sha256':digest(Path(out)/'source_lock.json'),
                'models_sha256':digest(Path(out)/'models.json'),'research_status':'exploratory reused year; candidate25'}
    _,score=export_result(result,destination,bars=bars,funding_source=funding,parameters=parameters,
                          data_source='Verified native Binance perpetual trades, independent marks and actual settlements',
                          source_manifest={'source_lock':read(Path(out)/'source_lock.json'),
                                           'funding_boundary':'actual sourced events begin<=timestamp<=stop; no synthetic event'})
    exposure=pd.DataFrame(observer.rows)
    if not pd.DatetimeIndex(exposure.timestamp).equals(pd.DatetimeIndex(result.equity.timestamp)):
        raise AssertionError('Exact equity/exposure clock mismatch')
    if not np.array_equal(exposure.equity.to_numpy(),result.equity.equity.to_numpy()):
        raise AssertionError('Observer changed or mismatched equity')
    exposure.to_parquet(destination/'exposure.parquet',index=False)
    exposure.to_csv(destination/'exposure.csv',index=False)
    pd.DataFrame(leg_contributions(result,mapping)).to_csv(destination/'leg_contributions.csv',index=False)
    dump(destination/'strategy_diagnostics.json',{'events':strategy.diagnostics,
         'admission_failures':dict(strategy.admission_failures),'terminal_state':strategy.state,
         'terminal_active_baskets':strategy.active,'terminal_transaction':strategy.transaction,
         'terminal_cleanup_order_count':len(strategy.cleanup_orders)})
    liquidations=int(result.events.type.eq('LIQUIDATION').sum()) if not result.events.empty else 0
    score.update(indicative_reserve(result))
    score.update({'liquidation_event_count':liquidations,'runtime_seconds':elapsed,
                  'open_position_count':len(result.positions),'joint_account':True})
    dump(destination/'metrics.json',score)
    guard(cache,out)
    dump(destination/'completion.json',{'phase':name,'stress':stress,
         'source_lock_sha256':digest(Path(out)/'source_lock.json'),'models_sha256':digest(Path(out)/'models.json'),
         'outputs_sha256':output_files(destination)})
    return score


def endpoint_daily(frame):
    adjusted=frame.copy()
    adjusted['timestamp']=pd.to_datetime(adjusted.timestamp,utc=True).dt.as_unit('ns')
    end=adjusted.timestamp.max()
    if end==end.normalize(): adjusted.loc[adjusted.timestamp.eq(end),'timestamp']=end-pd.Timedelta(microseconds=1)
    return daily_returns(adjusted)


def conditional_interval(frame):
    values=endpoint_daily(frame).dropna().to_numpy()
    if len(values)<7: return {'available':False,'reason':'fewer than seven daily observations'}
    if (values<=-1).any(): return {'available':False,'reason':'nonpositive compounded equity'}
    rng=np.random.default_rng(42); n=len(values)
    starts=rng.integers(0,n,(10000,int(np.ceil(n/7))))
    indices=((starts[:,:,None]+np.arange(7))%n).reshape(10000,-1)[:,:n]
    total=np.expm1(np.log1p(values[indices]).sum(axis=1))
    return {'available':True,'method':'conditional circular7day block bootstrap;10000 draws seed42',
            'limitations':'conditional fixed historical path; cannot undo adaptive reuse of this year',
            'comparison_count':25,'return_interval95':np.quantile(total,[.025,.975]).tolist(),
            'return_interval_bonferroni25':np.quantile(total,[.05/50,1-.05/50]).tolist()}


def summarize(cache,out):
    guard(cache,out)
    verified_models(out)
    expected={name for name,*_ in PHASES}
    trials=Path(out)/'trials'
    if not trials.exists() or {p.name for p in trials.iterdir()}!=expected:
        raise RuntimeError('Require all five exact joint simulations, no hidden variants')
    scores={}
    for phase in PHASES:
        name,_,_,stress=phase; directory=trials/name; receipt=read(directory/'completion.json')
        if receipt['phase']!=name or receipt['stress']!=stress or receipt['outputs_sha256']!=output_files(directory):
            raise RuntimeError('Completed phase identity/output seal mismatch')
        if receipt['models_sha256']!=digest(Path(out)/'models.json') or receipt['source_lock_sha256']!=digest(Path(out)/'source_lock.json'):
            raise RuntimeError('Completed phase source/model seal mismatch')
        verify_phase_metadata(directory,phase)
        scores[name]=read(directory/'metrics.json')
    validation=np.prod([1+scores[f'validation{k}']['total_return'] for k in (1,2,3)])-1
    validation_reserve=np.prod([1+scores[f'validation{k}']['return_after_indicative_exit_reserve'] for k in (1,2,3)])-1
    base=scores['evaluation']; stress=scores['evaluation_stress']
    frame=pd.read_parquet(trials/'evaluation'/'equity.parquet')
    series=frame.set_index('timestamp').equity
    points=[float(series.asof(EVAL_START+pd.DateOffset(months=k))) for k in range(4)]
    months=[points[k+1]/points[k]-1 for k in range(3)]
    legs=pd.read_csv(trials/'evaluation'/'leg_contributions.csv')
    participants=set(legs.loc[legs.fill_count.gt(0)&legs.symbol.isin(ALTS),'symbol'])
    gates={'positive_compounded_validation':validation>0,
           'positive_validation_after_exit_reserve':validation_reserve>0,
           'positive_evaluation':base['total_return']>0,
           'positive_evaluation_after_exit_reserve':base['return_after_indicative_exit_reserve']>0,
           'positive_stress':stress['total_return']>0,
           'positive_stress_after_exit_reserve':stress['return_after_indicative_exit_reserve']>0,
           'two_positive_anchored_months':sum(x>0 for x in months)>=2,
           'daily_sharpe_at_least_half':base.get('sharpe') is not None and base['sharpe']>=.5,
           'minute_drawdown_at_most_twenty_percent':base['max_drawdown']<=.2,
           'no_liquidation_all_five_runs':sum(s['liquidation_event_count'] for s in scores.values())==0,
           'four_target_alts_including_doge_or_pepe':len(participants)>=4 and bool(participants&{'DOGEUSDT','PEPEUSDT'})}
    summary={'family':FAMILY,'candidate_count_cumulative':25,'research_status':'exploratory reused year; no untouched holdout',
             'passes_hurdles':all(gates.values()),'gates':gates,'failed_gates':[name for name,ok in gates.items() if not ok],
             'validation_compounded_return':validation,'validation_after_exit_reserve':validation_reserve,
             'scores':scores,'anchored_month_returns':months,'target_alt_participants':sorted(participants),
             'all_evaluation_leg_contributions':legs.to_dict('records'),
             'conditional_interval':conditional_interval(frame),
             'full_resolution_evaluation_equity_sha256':digest(trials/'evaluation'/'equity.parquet'),
             'source_lock_sha256':digest(Path(out)/'source_lock.json'),'models_sha256':digest(Path(out)/'models.json'),
             'publication_status':'UNPUBLISHED: independent source, trajectory and summary audit required'}
    dump(Path(out)/'summary.json',summary)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',default='data_cache/minute-perpetual-1y')
    parser.add_argument('--out',default='results/residual-convergence-1y-v1')
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--freeze-only',action='store_true')
    action.add_argument('--execute',action='store_true')
    action.add_argument('--analysis-only',action='store_true')
    args=parser.parse_args(); cache=Path(args.cache); out=Path(args.out)
    if args.freeze_only:
        freeze(cache,out); print('Pre-estimation source packet frozen; no historical fitting or simulation performed.'); return
    guard(cache,out)
    if args.execute:
        models=estimate(cache,out)
        for phase in PHASES:
            run_phase(cache,out,models,phase)
            gc.collect()  # Release observer/portfolio reference cycles before the next joint run.
            print(f'Completed {phase[0]}',flush=True)
    summarize(cache,out)
    print('All five joint trials sealed; provisional summary awaits independent audit.',flush=True)

if __name__=='__main__': main()
